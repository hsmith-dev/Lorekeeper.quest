"""Prompt budgets: fit every local-LLM prompt under the context window.

The local model runs with a fixed context (settings.ollama_context_length,
4096 on the Reference Box) and per-call num_ctx is always stripped, so a
prompt that is too long is cut by Ollama without telling us. Prompt builders
instead describe their prompt as PromptParts and call fit(task, parts):

- each task has one TaskPolicy in TASK_POLICIES: how to trim
  (`drop_oldest`, `truncate_tail` or `map_reduce`) and how many tokens to
  leave for the reply. The window for a task is the context length minus
  that reserve.
- trimming only ever removes whole history turns or optional blocks, never
  text inside one, and FitResult (fit_report) says how many were left out.
- required parts are never trimmed: if system + instructions + required
  don't fit, fit raises errors.PromptBudgetError ("no silent truncation").
- inputs bigger than one window go through split_text + map_reduce.

Tokens are estimated offline (no tokenizer package, no network): characters
/ CHARS_PER_TOKEN, plus a SAFETY_MARGIN, plus MESSAGE_OVERHEAD_TOKENS per
chat message. E0-LLM.6 calibrates these against Ollama's prompt_eval_count.
"""

import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.errors import PromptBudgetError

logger = logging.getLogger(__name__)

# Average characters per token for English prose on Mistral's tokenizer.
CHARS_PER_TOKEN = 3.2
# Multiplier on the raw estimate, so an underestimate still fits.
SAFETY_MARGIN = 1.1
# Role markers the chat template wraps each message in ([INST] ... [/INST],
# BOS/EOS). Counted separately from SAFETY_MARGIN; E0-LLM.6 calibrates both.
MESSAGE_OVERHEAD_TOKENS = 6

DROP_OLDEST = "drop_oldest"
TRUNCATE_TAIL = "truncate_tail"
MAP_REDUCE = "map_reduce"
POLICIES = frozenset({DROP_OLDEST, TRUNCATE_TAIL, MAP_REDUCE})

# Blank line between blocks of the final user turn, and between results
# packed into one map_reduce batch.
BLOCK_SEPARATOR = "\n\n"


def estimate_tokens(text: str) -> int:
    """ceil(ceil(len(text) / 3.2) * 1.1); 0 for empty text. Integer math, so
    float rounding can't move a boundary (3.2 = 32/10, 1.1 = 11/10)."""
    if not text:
        return 0
    raw = -(-len(text) * 10 // 32)
    return -(-raw * 11 // 10)


def estimate_messages(messages: Sequence[dict]) -> int:
    """Estimated prompt tokens of a chat message list: each message's content
    plus MESSAGE_OVERHEAD_TOKENS for its template markers."""
    return sum(estimate_tokens(m.get("content") or "") + MESSAGE_OVERHEAD_TOKENS for m in messages)


@dataclass(frozen=True)
class TaskPolicy:
    policy: str           # DROP_OLDEST | TRUNCATE_TAIL | MAP_REDUCE
    reserved_output: int  # tokens kept free for the reply

    def __post_init__(self):
        if self.policy not in POLICIES:
            raise ValueError(f"unknown prompt budget policy {self.policy!r}")


# One line per task. The reserves are first guesses at each reply's length;
# E0-LLM.6 calibrates them (and CHARS_PER_TOKEN) against the real model.
# Feature epics add their own task here as a one-line entry.
TASK_POLICIES: dict[str, TaskPolicy] = {
    "chat": TaskPolicy(DROP_OLDEST, 800),            # GM chat: older turns go first
    "narrative": TaskPolicy(TRUNCATE_TAIL, 800),     # notes -> journal entry (kobold_max_length)
    "structured": TaskPolicy(TRUNCATE_TAIL, 1024),   # complete_structured JSON replies
    "live_recap": TaskPolicy(TRUNCATE_TAIL, 600),    # Rolling Recap update; reports what didn't fit
    "live_draft": TaskPolicy(MAP_REDUCE, 1024),      # whole-session draft over a long transcript
    "npc_chat": TaskPolicy(DROP_OLDEST, 400),        # NPC conversation: oldest turns go first
    "lookup_answer": TaskPolicy(TRUNCATE_TAIL, 512), # grounded answer: least relevant snippets go first
}


def policy_for(task: str) -> TaskPolicy:
    try:
        return TASK_POLICIES[task]
    except KeyError:
        raise ValueError(f"unknown prompt budget task {task!r}") from None


def window_tokens(task: str, context_length: int | None = None) -> int:
    """Prompt tokens available to `task`: the context length (default
    settings.ollama_context_length) minus the task's reserved output."""
    ctx = context_length if context_length is not None else get_settings().ollama_context_length
    return ctx - policy_for(task).reserved_output


@dataclass
class PromptParts:
    """What a prompt is made of. Layout (see fit): the system message, then
    the kept history in order, then one final user turn holding the required
    blocks, the kept optional blocks and the instructions, last."""

    system: str = ""
    instructions: str = ""
    required: list[str] = field(default_factory=list)   # never trimmed
    optional: list[str] = field(default_factory=list)   # most relevant first
    history: list[dict] = field(default_factory=list)   # chat messages, oldest first


@dataclass
class FitResult:
    messages: list[dict]
    tokens: int            # estimated prompt tokens of messages
    budget: int            # the task's window
    dropped_history: int   # this many oldest history turns were left out
    dropped_optional: int  # this many optional blocks from the tail were left out


def _assemble(parts: PromptParts, dropped_history: int, dropped_optional: int) -> list[dict]:
    messages: list[dict] = []
    if parts.system:
        messages.append({"role": "system", "content": parts.system})
    messages.extend(parts.history[dropped_history:])
    kept_optional = parts.optional[: len(parts.optional) - dropped_optional]
    blocks = [b for b in (*parts.required, *kept_optional, parts.instructions) if b]
    if blocks:
        messages.append({"role": "user", "content": BLOCK_SEPARATOR.join(blocks)})
    return messages


def _drops(policy: str, k: int, n_history: int, n_optional: int) -> tuple[int, int]:
    """(dropped_history, dropped_optional) after the first k removals of the
    policy's drop order."""
    if policy == DROP_OLDEST:
        return min(k, n_history), max(0, k - n_history)
    return max(0, k - n_optional), min(k, n_optional)  # TRUNCATE_TAIL


def _log(event: str, **fields) -> None:
    logger.info(json.dumps({"event": event, **fields}))


def fit_report(task: str, parts: PromptParts, *, context_length: int | None = None) -> FitResult:
    """Assemble parts into chat messages under the task's window, trimming
    whole items per the task's policy:

    - drop_oldest: history from the front, then optional from the tail.
    - truncate_tail: optional from the tail, then history from the front.
    - map_reduce: nothing; everything must fit (use map_reduce() for more).

    Raises PromptBudgetError if system + instructions + required alone, or
    (map_reduce) the whole prompt, exceed the window. ValueError for an
    unknown task."""
    policy = policy_for(task).policy
    budget = window_tokens(task, context_length)
    n_hist, n_opt = len(parts.history), len(parts.optional)

    def at(k: int) -> FitResult:
        dh, do = _drops(policy, k, n_hist, n_opt) if policy != MAP_REDUCE else (0, 0)
        msgs = _assemble(parts, dh, do)
        return FitResult(msgs, estimate_messages(msgs), budget, dh, do)

    full = at(0)
    if full.tokens <= budget:
        return full
    if policy == MAP_REDUCE:
        raise PromptBudgetError(
            f"Prompt for {task!r} needs ~{full.tokens} tokens but the window is {budget}; "
            "a map_reduce task must split its input with prompt_budget.map_reduce."
        )
    total = n_hist + n_opt
    floor = at(total)
    if floor.tokens > budget:
        raise PromptBudgetError(
            f"Required prompt parts for {task!r} need ~{floor.tokens} tokens but the window is {budget}."
        )
    # Dropping more items never makes the prompt longer, so binary-search the
    # fewest drops that fit (lo doesn't fit, hi does).
    lo, hi = 0, total
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if at(mid).tokens <= budget:
            hi = mid
        else:
            lo = mid
    result = at(hi)
    _log(
        "prompt_budget_trimmed",
        task=task,
        dropped_history=result.dropped_history,
        dropped_optional=result.dropped_optional,
        tokens=result.tokens,
        budget=budget,
    )
    return result


def fit(task: str, parts: PromptParts, *, context_length: int | None = None) -> list[dict]:
    """fit_report(...).messages — for callers that don't need to know what
    was left out."""
    return fit_report(task, parts, context_length=context_length).messages


_SEPARATORS = (r"\n\s*\n", r"\n", r" +")


def split_text(text: str, max_tokens: int) -> list[str]:
    """Split text into chunks whose estimate is at most max_tokens, breaking
    on paragraph, then line, then word, then character boundaries. Each
    chunk keeps its trailing separator, so "".join(chunks) == text: nothing
    is lost. Empty text gives []."""
    if max_tokens < estimate_tokens("x"):
        raise ValueError(f"max_tokens must be at least {estimate_tokens('x')}")
    if not text:
        return []
    return _split(text, max_tokens, 0)


def _split(text: str, max_tokens: int, level: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    if level == len(_SEPARATORS):
        return _split_chars(text, max_tokens)
    # Pieces end with their separator; the last may have none.
    parts = re.split(f"({_SEPARATORS[level]})", text)
    pieces = [p for p in ("".join(parts[i : i + 2]) for i in range(0, len(parts), 2)) if p]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if estimate_tokens(current + piece) <= max_tokens:
            current += piece
            continue
        if current:
            chunks.append(current)
            current = ""
        if estimate_tokens(piece) <= max_tokens:
            current = piece
        else:
            chunks.extend(_split(piece, max_tokens, level + 1))
    if current:
        chunks.append(current)
    return chunks


def _split_chars(text: str, max_tokens: int) -> list[str]:
    # Largest n with estimate_tokens of n chars <= max_tokens.
    n = 1
    while estimate_tokens("x" * (n + 1)) <= max_tokens:
        n += 1
    return [text[i : i + n] for i in range(0, len(text), n)]


async def _call(fn: Callable, arg):
    out = fn(arg)
    if inspect.isawaitable(out):
        out = await out
    return out


def _batch_tokens(batch: Sequence[str]) -> int:
    return estimate_tokens(BLOCK_SEPARATOR.join(batch))


async def map_reduce(
    chunks: Sequence[str],
    map_fn: Callable[[str], Awaitable[str] | str],
    reduce_fn: Callable[[list[str]], Awaitable[str] | str],
    *,
    task: str,
    overhead_tokens: int = 0,
) -> str:
    """Run map_fn on every chunk in order, then reduce the results.

    Results are packed in order into batches whose estimate (joined with
    blank lines) fits the task's window minus overhead_tokens (the reduce
    prompt's own framing); each batch goes to reduce_fn, and that repeats
    until all results fit one batch, which gets the final reduce_fn call.

    Raises ValueError if the task's policy isn't map_reduce or there are no
    chunks; PromptBudgetError if one result can't fit a batch on its own or
    a round doesn't shrink the total (so it never loops forever)."""
    if policy_for(task).policy != MAP_REDUCE:
        raise ValueError(f"task {task!r} does not use the map_reduce policy")
    if not chunks:
        raise ValueError("map_reduce needs at least one chunk")
    capacity = window_tokens(task) - overhead_tokens
    if capacity <= 0:
        raise PromptBudgetError(f"Reduce overhead for {task!r} leaves no room in the window.")

    results = [await _call(map_fn, c) for c in chunks]
    rounds = 0
    while _batch_tokens(results) > capacity:
        batches: list[list[str]] = []
        for r in results:
            if estimate_tokens(r) > capacity:
                raise PromptBudgetError(
                    f"A {task!r} map/reduce result needs ~{estimate_tokens(r)} tokens; "
                    f"one reduce call holds {capacity}."
                )
            if batches and _batch_tokens([*batches[-1], r]) <= capacity:
                batches[-1].append(r)
            else:
                batches.append([r])
        reduced = [await _call(reduce_fn, b) for b in batches]
        rounds += 1
        if _batch_tokens(reduced) >= _batch_tokens(results):
            raise PromptBudgetError(f"{task!r} reduce round {rounds} did not shrink its input.")
        results = reduced
    if rounds:
        _log("prompt_budget_map_reduce", task=task, chunks=len(chunks), rounds=rounds)
    return await _call(reduce_fn, results)
