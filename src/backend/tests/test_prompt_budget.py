"""E0-LLM.3: prompt_budget — token estimate, task registry, fit, map_reduce.

Pure module: no network, no database, no gate.
"""

import json
import logging
import math

import pytest

from app.core.config import get_settings
from app.core.errors import PromptBudgetError
from app.services import prompt_budget as pb
from app.services.prompt_budget import (
    MESSAGE_OVERHEAD_TOKENS,
    PromptParts,
    TASK_POLICIES,
    estimate_messages,
    estimate_tokens,
    fit,
    fit_report,
    map_reduce,
    policy_for,
    split_text,
    window_tokens,
)

CTX = 2048


def words(n: int, tag: str = "w") -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


# --- estimate ------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 3, 4, 31, 32, 33, 100, 1000, 4095])
def test_estimate_formula(n):
    expected = 0 if n == 0 else math.ceil(math.ceil(n / 3.2) * 1.1)
    assert estimate_tokens("a" * n) == expected


def test_estimate_messages_adds_overhead():
    msgs = [{"role": "system", "content": "a" * 32}, {"role": "user", "content": ""}]
    assert estimate_messages(msgs) == 11 + 2 * MESSAGE_OVERHEAD_TOKENS


# --- registry ------------------------------------------------------------


def test_registry_entries():
    assert set(TASK_POLICIES) >= {
        "chat", "narrative", "structured", "live_recap", "live_draft", "npc_chat", "lookup_answer",
    }
    assert policy_for("live_draft").policy == pb.MAP_REDUCE
    assert policy_for("chat").policy == pb.DROP_OLDEST
    assert policy_for("npc_chat").policy == pb.DROP_OLDEST
    assert policy_for("lookup_answer").policy == pb.TRUNCATE_TAIL
    for p in TASK_POLICIES.values():
        assert p.policy in pb.POLICIES
        assert 0 < p.reserved_output < get_settings().ollama_context_length


def test_window_is_context_minus_reserve():
    assert window_tokens("chat") == get_settings().ollama_context_length - policy_for("chat").reserved_output
    assert window_tokens("chat", 2048) == 2048 - policy_for("chat").reserved_output


def test_default_context_length():
    assert get_settings().ollama_context_length == 4096


@pytest.mark.parametrize("call", [
    lambda: policy_for("nope"),
    lambda: window_tokens("nope"),
    lambda: fit("nope", PromptParts()),
])
def test_unknown_task(call):
    with pytest.raises(ValueError):
        call()


def test_bad_policy_rejected():
    with pytest.raises(ValueError):
        pb.TaskPolicy("drop_newest", 100)


# --- fit -----------------------------------------------------------------


def test_everything_fits_in_layout_order():
    parts = PromptParts(
        system="SYS",
        instructions="INSTR",
        required=["REQ1", "REQ2"],
        optional=["OPT1", "OPT2"],
        history=[{"role": "user", "content": "H1"}, {"role": "assistant", "content": "H2"}],
    )
    r = fit_report("chat", parts, context_length=CTX)
    assert r.messages == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "H1"},
        {"role": "assistant", "content": "H2"},
        {"role": "user", "content": "REQ1\n\nREQ2\n\nOPT1\n\nOPT2\n\nINSTR"},
    ]
    assert (r.dropped_history, r.dropped_optional) == (0, 0)
    assert r.tokens == estimate_messages(r.messages)
    assert r.budget == window_tokens("chat", CTX)
    assert fit("chat", parts, context_length=CTX) == r.messages


def test_empty_system_omitted():
    msgs = fit("chat", PromptParts(instructions="Hi"), context_length=CTX)
    assert msgs == [{"role": "user", "content": "Hi"}]


def test_history_over_drops_oldest(caplog):
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn{i} " + words(40)}
               for i in range(40)]
    parts = PromptParts(system="SYS", instructions="Answer.", history=history)
    with caplog.at_level(logging.INFO, logger=pb.__name__):
        r = fit_report("chat", parts, context_length=CTX)
    assert 0 < r.dropped_history < 40
    assert r.dropped_optional == 0
    kept = r.messages[1:-1]
    assert kept == history[r.dropped_history:]  # newest kept, in order
    assert r.tokens <= r.budget
    # Dropping one fewer would not have fit: the trim is minimal.
    assert pb.estimate_messages(pb._assemble(parts, r.dropped_history - 1, 0)) > r.budget
    logged = [json.loads(rec.getMessage()) for rec in caplog.records]
    trims = [e for e in logged if e["event"] == "prompt_budget_trimmed"]
    assert trims and trims[0]["task"] == "chat" and trims[0]["dropped_history"] == r.dropped_history
    assert "turn" not in caplog.text  # counts, never prompt text


def test_drop_oldest_then_optional():
    parts = PromptParts(
        instructions="Q",
        optional=[words(400, "a"), words(400, "b")],
        history=[{"role": "user", "content": words(50)}],
    )
    r = fit_report("chat", parts, context_length=CTX)
    assert r.dropped_history == 1
    assert r.dropped_optional >= 1
    assert r.tokens <= r.budget


def test_optional_over_drops_tail():
    snippets = [f"snippet{i}: " + words(60) for i in range(30)]
    parts = PromptParts(system="Ground every answer.", instructions="Answer from the snippets.",
                        required=["Q: who?"], optional=snippets,
                        history=[{"role": "user", "content": "earlier"}])
    r = fit_report("lookup_answer", parts, context_length=CTX)
    assert 0 < r.dropped_optional < 30
    assert r.dropped_history == 0  # truncate_tail drops optional first
    final = r.messages[-1]["content"]
    kept = 30 - r.dropped_optional
    assert all(f"snippet{i}:" in final for i in range(kept))  # most relevant kept
    assert f"snippet{kept}:" not in final
    assert final.startswith("Q: who?") and final.endswith("Answer from the snippets.")


def test_truncate_tail_then_history():
    parts = PromptParts(
        instructions="Q",
        optional=[words(50)],
        history=[{"role": "user", "content": words(500, "a")}, {"role": "user", "content": words(500, "b")}],
    )
    r = fit_report("lookup_answer", parts, context_length=CTX)
    assert r.dropped_optional == 1
    assert r.dropped_history >= 1


def test_required_over_raises():
    parts = PromptParts(required=[words(2000)], optional=["x"], history=[{"role": "user", "content": "y"}])
    with pytest.raises(PromptBudgetError) as exc:
        fit("chat", parts, context_length=CTX)
    assert exc.value.code == "prompt_too_large"


def test_map_reduce_task_over_raises():
    parts = PromptParts(instructions="Draft.", optional=[words(2000)])
    with pytest.raises(PromptBudgetError, match="map_reduce"):
        fit("live_draft", parts, context_length=CTX)


def test_map_reduce_task_that_fits_drops_nothing():
    parts = PromptParts(instructions="Draft.", optional=["a", "b"], history=[{"role": "user", "content": "h"}])
    r = fit_report("live_draft", parts, context_length=CTX)
    assert (r.dropped_history, r.dropped_optional) == (0, 0)


# --- split_text ----------------------------------------------------------


@pytest.mark.parametrize("text", [
    "\n\n".join(words(80, f"p{i}_") for i in range(20)),  # paragraphs
    "\n".join(words(80, f"l{i}_") for i in range(20)),    # lines only
    words(2000),                                           # words only
    "x" * 5000,                                            # no boundaries at all
    "short",
    "para one.\n\n\n  \nline a\nline b " + "y" * 900,      # mixed
])
def test_split_text_loses_nothing(text):
    chunks = split_text(text, 100)
    assert "".join(chunks) == text
    assert all(0 < estimate_tokens(c) <= 100 for c in chunks)


def test_split_text_prefers_paragraphs():
    paras = [words(20, f"p{i}_") for i in range(10)]
    chunks = split_text("\n\n".join(paras), estimate_tokens(paras[0] + "\n\n") + 1)
    assert [c.rstrip("\n") for c in chunks] == paras


def test_split_text_edges():
    assert split_text("", 100) == []
    with pytest.raises(ValueError):
        split_text("abc", 1)


# --- map_reduce ----------------------------------------------------------


async def test_big_input_reaches_map_and_recurses():
    window = window_tokens("live_draft")
    text = "\n\n".join(words(60, f"p{i}_") for i in range(window // 10)) + "\n\nSENTINEL_END"
    assert estimate_tokens(text) > 3 * window
    chunks = split_text(text, window // 2)
    mapped: list[str] = []
    reduce_inputs: list[list[str]] = []

    async def map_fn(chunk: str) -> str:
        mapped.append(chunk)
        # Keep the sentinel visible, otherwise shrink by half.
        return chunk[: len(chunk) // 2] + (" SENTINEL_END" if "SENTINEL_END" in chunk else "")

    async def reduce_fn(batch: list[str]) -> str:
        reduce_inputs.append(batch)
        joined = "\n\n".join(batch)
        assert estimate_tokens(joined) <= window  # every reduce input fits
        return joined[: len(joined) // 4] + (" SENTINEL_END" if "SENTINEL_END" in joined else "")

    out = await map_reduce(chunks, map_fn, reduce_fn, task="live_draft")
    assert mapped == chunks  # every chunk, in order
    assert "SENTINEL_END" in mapped[-1]
    assert len(reduce_inputs) > 2  # intermediate rounds, then the final reduce
    assert "SENTINEL_END" in out


async def test_small_input_single_reduce():
    calls = []
    out = await map_reduce(["a", "b"], lambda c: c.upper(), lambda b: calls.append(b) or "+".join(b),
                           task="live_draft")
    assert out == "A+B"
    assert calls == [["A", "B"]]


async def test_no_progress_raises():
    window = window_tokens("live_draft")
    chunks = [words(int(window * 0.3)) for _ in range(4)]  # ~0.6 window each

    async def reduce_fn(batch):
        return "\n\n".join(batch)  # as big as its input

    with pytest.raises(PromptBudgetError, match="shrink"):
        await map_reduce(chunks, lambda c: c, reduce_fn, task="live_draft")


async def test_single_oversized_result_raises():
    window = window_tokens("live_draft")
    with pytest.raises(PromptBudgetError):
        await map_reduce(["x"], lambda c: "y" * (window * 4), lambda b: "z", task="live_draft")


async def test_overhead_shrinks_batches():
    window = window_tokens("live_draft")
    results = [words(int(window * 0.1)) for _ in range(4)]  # fits one window, not with overhead
    batches = []

    def reduce_fn(batch):
        batches.append(len(batch))
        return "s"

    await map_reduce(results, lambda c: c, reduce_fn, task="live_draft", overhead_tokens=window // 2)
    assert batches[0] < 4


async def test_map_reduce_requires_map_reduce_policy():
    with pytest.raises(ValueError):
        await map_reduce(["a"], lambda c: c, lambda b: "".join(b), task="chat")
    with pytest.raises(ValueError):
        await map_reduce([], lambda c: c, lambda b: "".join(b), task="live_draft")
    with pytest.raises(ValueError):
        await map_reduce(["a"], lambda c: c, lambda b: "".join(b), task="nope")
