"""Unified LLM provider — routes completions to KoboldCpp, OpenAI, Anthropic, or Gemini.

Platform-LLM calls (the operator's own Ollama/KoboldCpp, see
uses_platform_llm) go through the priority gate in app/core/llm_gate.py and
always name the one fixed local model (model_for), so Ollama never reloads
between tasks. BYOK calls (any other provider, or kobold at the user's own
URL) bypass the gate and keep their own model. Per-call `num_ctx`, `num_gpu`
and `keep_alive` options are stripped for every provider: they would make
Ollama reload the model.

detect_backend(api_url) tells Ollama from KoboldCpp/other OpenAI-compatible
servers with one cached `GET /api/version` probe, so callers can skip
KoboldCpp-only endpoints (ai_service.generate_narrative's native attempt)
that would only 404 on Ollama.

complete_structured(messages, schema, config, *, task, ...) returns a
validated instance of a flat pydantic schema (app/schemas/llm). It enforces
the schema per backend (Ollama `format`; strict `response_format` for
KoboldCpp/openai/custom, prompted again on a 4xx; prompted JSON for
anthropic/gemini), checks every reply with model_validate_json, runs at most
two repair turns quoting the errors, then raises StructuredOutputError. One
gate slot covers the first call and its repairs; each attempt logs one
`structured_attempt` JSON line, and structured_stats counts outcomes per task.
"""

import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import LLMConfigError, LLMUnavailable, PromptBudgetError, StructuredOutputError
from app.core.llm_gate import GateClass, Slot
from app.schemas.llm import flat_json_schema, flatness_problems
from app.services.prompt_budget import TASK_POLICIES, estimate_messages, estimate_tokens

# Tests swap in an httpx.MockTransport here; None = real network.
_transport: httpx.AsyncBaseTransport | None = None

# Options that change how Ollama loads the model. Any one of them differing
# between calls forces a reload, so they are never sent per call.
LOCAL_ONLY_OPTIONS = frozenset({"num_ctx", "num_gpu", "keep_alive"})


def _client(timeout: float) -> httpx.AsyncClient:
    if _transport is not None:
        return httpx.AsyncClient(timeout=timeout, transport=_transport)
    return httpx.AsyncClient(timeout=timeout)


BACKEND_OLLAMA = "ollama"
BACKEND_OPENAI_COMPAT = "openai_compat"

# Answered probes, keyed by base URL without a trailing "/". Lives for the
# process; a probe that got no answer is never stored (see detect_backend).
_backend_cache: dict[str, str] = {}

DETECT_TIMEOUT_S = 3.0


async def detect_backend(api_url: str | None) -> str:
    """BACKEND_OLLAMA if `GET {api_url}/api/version` answers 2xx with a JSON
    object holding a string "version" (Ollama's shape), else
    BACKEND_OPENAI_COMPAT. Empty/None api_url = settings.kobold_url.

    Any answered probe (404, HTML from KoboldCpp, ...) is cached for the
    process. A transport error, a timeout or a 5xx answer (e.g. a proxy's 502
    while Ollama is still starting) returns BACKEND_OPENAI_COMPAT without
    caching it, so an Ollama that was still starting is detected on a later
    call. Never touches the gate and never raises."""
    base = (api_url or get_settings().kobold_url).rstrip("/")
    cached = _backend_cache.get(base)
    if cached is not None:
        return cached
    try:
        async with _client(DETECT_TIMEOUT_S) as client:
            r = await client.get(f"{base}/api/version")
    except Exception:
        # Down, timed out, or a broken handler: no answer, so don't cache.
        return BACKEND_OPENAI_COMPAT
    if r.status_code >= 500:
        # Server-side trouble, not an answer about what the backend is.
        return BACKEND_OPENAI_COMPAT
    result = BACKEND_OPENAI_COMPAT
    if r.is_success:
        try:
            body = r.json()
        except Exception:
            body = None
        if isinstance(body, dict) and isinstance(body.get("version"), str):
            result = BACKEND_OLLAMA
    _backend_cache[base] = result
    return result


@dataclass
class LLMConfig:
    provider: str = "kobold"   # "kobold" | "openai" | "anthropic" | "gemini" | "custom"
    api_url: str | None = None  # base URL for kobold / custom / openai-compat
    api_key: str | None = None
    model: str | None = None
    temperature: float = 0.72
    max_tokens: int = 800


def get_default_config() -> LLMConfig:
    s = get_settings()
    return LLMConfig(
        provider="kobold",
        api_url=s.kobold_url,
        model=s.kobold_model,
        temperature=s.kobold_temperature,
        max_tokens=s.kobold_max_length,
    )


def is_hosted_default(cfg: LLMConfig) -> bool:
    """True if cfg is the platform's own hosted model (what
    app/api/deps.py::get_user_llm_config hands back to a subscriber who hasn't
    configured a personal provider) rather than a user-supplied one. Route
    handlers that generate text with a config from get_user_llm_config check
    this before calling billing_service.record_hosted_usage — BYO-key usage
    never counts against a subscription's quota."""
    default = get_default_config()
    return cfg.provider == default.provider and cfg.api_url == default.api_url


def uses_platform_llm(cfg: LLMConfig) -> bool:
    """True if cfg runs on the platform's own local LLM (provider kobold at
    KOBOLD_URL, or with no URL, which defaults there): the calls the gate
    orders and the fixed model applies to. Unlike is_hosted_default this
    ignores a trailing "/" and treats an empty URL as the platform's."""
    if cfg.provider != "kobold":
        return False
    if not cfg.api_url:
        return True
    return cfg.api_url.rstrip("/") == get_settings().kobold_url.rstrip("/")


def model_for(task: str | None, cfg: LLMConfig) -> str | None:
    """The model a call names. Platform LLM: settings.local_llm_model for
    every task, so Ollama keeps one model resident. The one exception is a
    `narrative` call on the "base" variant (the resolver sets cfg.model to
    kobold_base_model): it names that model and accepts the reload. Any other
    cfg.model (the default config always fills in kobold_model) is ignored.
    BYOK: cfg.model, unchanged (None lets the provider branch pick its own
    default)."""
    if uses_platform_llm(cfg):
        s = get_settings()
        if task == "narrative" and cfg.model and cfg.model == s.kobold_base_model:
            return s.kobold_base_model
        return s.local_llm_model
    return cfg.model


def strip_local_options(options: dict | None) -> dict:
    """Copy of options without num_ctx/num_gpu/keep_alive (LOCAL_ONLY_OPTIONS)."""
    return {k: v for k, v in (options or {}).items() if k not in LOCAL_ONLY_OPTIONS}


@asynccontextmanager
async def gated(cfg: LLMConfig, gate_class: GateClass | str | None = None) -> AsyncIterator[None]:
    """Hold a gate slot for the block when cfg is the platform LLM; a no-op
    for BYOK (never touches Redis). Reentrant, so wrapping a block that also
    calls complete_messages takes one slot, not two."""
    if uses_platform_llm(cfg):
        async with llm_gate.llm_slot(gate_class):
            yield
    else:
        yield


async def reserve_slot(cfg: LLMConfig, gate_class: GateClass | str | None = None) -> Slot:
    """Acquire a slot up front, for SSE routes: call it before building the
    StreamingResponse so LLMBusy is a normal 503, then run the stream inside
    `with slot.held():` and `await slot.release()` in its finally. A no-op
    Slot for BYOK."""
    if not uses_platform_llm(cfg):
        return Slot()
    return await llm_gate.acquire(gate_class)


async def complete_messages(
    messages: list[dict],
    config: LLMConfig | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = 120,
    *,
    task: str | None = None,
    gate_class: GateClass | str | None = None,
    options: dict | None = None,
) -> str:
    """Send messages (OpenAI format) to configured provider and return completion text.

    task: picks the model via model_for ("narrative" keeps the user's variant).
    gate_class: priority for platform-LLM calls (default llm_gate.current_class).
    options: extra OpenAI-compatible payload fields (e.g. top_p), minus the
    model-reloading ones; ignored for anthropic/gemini. Raises errors.LLMBusy
    if no gate slot frees up in time."""
    cfg = config or get_default_config()
    mt = max_tokens if max_tokens is not None else cfg.max_tokens
    temp = temperature if temperature is not None else cfg.temperature
    opts = strip_local_options(options)

    async with gated(cfg, gate_class):
        if cfg.provider == "anthropic":
            return await _anthropic(messages, cfg, mt, temp, timeout)
        if cfg.provider == "gemini":
            return await _gemini(messages, cfg, mt, temp, timeout)
        return await _openai_compat(messages, cfg, mt, temp, timeout, task=task, options=opts)


# ---------------------------------------------------------------------------
# Structured output (E0-LLM.4)

logger = logging.getLogger(__name__)

STRUCTURED_MAX_ATTEMPTS = 3  # the first call + at most 2 repair turns
REPAIR_ERRORS_MAX_CHARS = 1000
LOG_ERRORS_MAX = 10  # validation errors (loc, type) per structured_attempt line
STRUCTURED_BUDGET_TASK = "structured"  # budget for a task not in TASK_POLICIES

# Enforcement modes; also the `backend` field of the structured_attempt log.
MODE_OLLAMA = "ollama"                           # /api/chat with format=<schema>
MODE_OPENAI_SCHEMA = "openai_compat"             # strict response_format json_schema
MODE_OPENAI_PROMPTED = "openai_compat_prompted"  # schema in the prompt only
MODE_ANTHROPIC = "anthropic"
MODE_GEMINI = "gemini"

# Per-task outcome counters of complete_structured, for the process:
# {task: {"first_try_valid": n, "valid_after_repair": n, "failed": n}}.
structured_stats: dict[str, dict[str, int]] = {}


def _bump_stat(task: str, key: str) -> None:
    counts = structured_stats.setdefault(
        task, {"first_try_valid": 0, "valid_after_repair": 0, "failed": 0}
    )
    counts[key] += 1


def _checked_schema(schema: type[BaseModel]) -> dict:
    js = flat_json_schema(schema)
    problems = flatness_problems(js)
    if problems:
        raise ValueError(
            f"{schema.__name__} is not a flat LLM schema (see app/schemas/llm): " + "; ".join(problems)
        )
    return js


def schema_prompt(schema: type[BaseModel]) -> str:
    """The instruction complete_structured adds to the final user turn: the
    flat JSON schema and "reply with only one JSON object"."""
    return (
        "Reply with only one JSON object that matches this JSON schema. "
        "No markdown, no explanation, no other text.\n"
        "JSON schema:\n" + json.dumps(flat_json_schema(schema), separators=(",", ":"))
    )


def _with_schema(messages: list[dict], instruction: str) -> list[dict]:
    """Copy of messages with instruction appended to the final user turn, or
    added as a new user turn. The caller's list and dicts are not touched."""
    out = [dict(m) for m in messages]
    last = out[-1] if out else None
    if last is not None and last.get("role") == "user" and isinstance(last.get("content"), str):
        last["content"] = f"{last['content']}\n\n{instruction}" if last["content"] else instruction
    else:
        out.append({"role": "user", "content": instruction})
    return out


_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n?(.*?)\n?[ \t]*```", re.DOTALL)


def _json_candidate(text: str) -> str:
    """The reply with one surrounding markdown fence stripped, else the text
    from the first "{" to the last "}", else the reply itself."""
    s = text.strip()
    m = _FENCE_RE.fullmatch(s)
    if m:
        return m.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return s[start : end + 1]
    return s


def _validate(raw: str, schema: type[BaseModel]) -> tuple[BaseModel | None, list[dict]]:
    """(instance, []) if raw holds a valid object, else (None, [{loc, msg, type}])."""
    try:
        return schema.model_validate_json(_json_candidate(raw)), []
    except ValidationError as exc:
        return None, [
            {
                "loc": ".".join(str(p) for p in e.get("loc", ())) or "(root)",
                "msg": str(e.get("msg", "")),
                "type": str(e.get("type", "")),
            }
            for e in exc.errors(include_url=False, include_input=False)
        ]


def _error_lines(errors: list[dict]) -> str:
    text = "\n".join(f"{e['loc']}: {e['msg']}" for e in errors)
    if len(text) > REPAIR_ERRORS_MAX_CHARS:
        text = text[: REPAIR_ERRORS_MAX_CHARS - 3] + "..."
    return text


def _repair_messages(base: list[dict], raw: str, errors: list[dict], window: int | None) -> list[dict]:
    """base + the last bad output (assistant turn) + the errors (user turn).
    Only the latest output is echoed, so the prompt stays bounded. With a
    window (platform LLM) the echo is cut from the end, or dropped, so the
    prompt fits instead of Ollama front-truncating it; if even the errors
    alone don't fit, PromptBudgetError."""
    lines = _error_lines(errors)

    def ask(shown: str) -> dict:
        return {
            "role": "user",
            "content": (
                f"Your previous reply{shown} did not match the JSON schema. Validation errors:\n"
                f"{lines}\n\nReply with only the corrected JSON object, with no other text."
            ),
        }

    full = [*base, {"role": "assistant", "content": raw}, ask("")]
    if window is None or estimate_messages(full) <= window:
        return full
    # Longest prefix of raw that still fits (the estimate only grows with length).
    cut_ask = ask(" (cut short here)")
    fixed = estimate_messages([*base, {"role": "assistant", "content": ""}, cut_ask])
    lo, hi = 0, len(raw)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fixed + estimate_tokens(raw[:mid] + "...") <= window:
            lo = mid
        else:
            hi = mid - 1
    if lo > 0:
        return [*base, {"role": "assistant", "content": raw[:lo] + "..."}, cut_ask]
    dropped = [*base, ask(" (not shown)")]
    if estimate_messages(dropped) > window:
        raise PromptBudgetError(
            f"The repair prompt needs ~{estimate_messages(dropped)} tokens but the window is {window}."
        )
    return dropped


async def _prompted_sender(coro) -> str:
    """Await an existing sender (_openai_compat/_anthropic/_gemini): its 400
    (missing BYOK key) becomes LLMConfigError, its 503 and any transport
    error it lets through become LLMUnavailable."""
    try:
        return await coro
    except HTTPException as exc:
        if exc.status_code == 400:
            raise LLMConfigError(str(exc.detail)) from exc
        raise LLMUnavailable(str(exc.detail)) from exc
    except (httpx.HTTPError, AttributeError, TypeError) as exc:
        # AttributeError/TypeError: a reply shape the sender didn't expect
        # (e.g. `content: null`, which _openai_compat calls .strip() on).
        raise LLMUnavailable(f"AI model unavailable: {exc}") from exc


class _RejectedFormat(Exception):
    """A 4xx to a strict response_format request: retry it prompted."""


@dataclass
class _Structured:
    cfg: LLMConfig
    task: str
    json_schema: dict
    mode: str
    max_tokens: int
    timeout: float


def _auth_headers(cfg: LLMConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}


async def _send_ollama(st: _Structured, messages: list[dict]) -> str:
    s = get_settings()
    base = (st.cfg.api_url or s.kobold_url).rstrip("/")
    payload = {
        "model": model_for(st.task, st.cfg) or s.kobold_model,
        "messages": messages,
        "format": st.json_schema,
        "stream": False,
        "options": {"temperature": 0, "num_predict": st.max_tokens},
    }
    try:
        async with _client(st.timeout) as client:
            r = await client.post(f"{base}/api/chat", json=payload, headers=_auth_headers(st.cfg))
            r.raise_for_status()
            content = (r.json().get("message") or {}).get("content") or ""
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise LLMUnavailable(f"AI model unavailable: {exc}") from exc
    if not content.strip():
        raise LLMUnavailable("AI model unavailable: empty response from Ollama")
    return content


async def _send_openai_schema(st: _Structured, messages: list[dict]) -> str:
    base, model = _openai_compat_target(st.cfg, st.task)
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": st.max_tokens,
        "temperature": 0,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                # OpenAI allows [A-Za-z0-9_-]{1,64} here.
                "name": re.sub(r"[^A-Za-z0-9_-]", "_", st.task)[:64] or STRUCTURED_BUDGET_TASK,
                "schema": st.json_schema,
                "strict": True,
            },
        },
    }
    try:
        async with _client(st.timeout) as client:
            r = await client.post(f"{base}/v1/chat/completions", json=payload, headers=_auth_headers(st.cfg))
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"AI model unavailable: {exc}") from exc
    if 400 <= r.status_code < 500:
        raise _RejectedFormat(r.status_code)
    try:
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"] or ""
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMUnavailable(f"AI model unavailable: {exc}") from exc
    if not content.strip():
        raise LLMUnavailable("AI model unavailable: empty response from model")
    return content


async def _send_structured(st: _Structured, messages: list[dict]) -> str:
    """One attempt's reply text. A strict response_format refused with a 4xx
    is retried once as prompted JSON, and st.mode stays prompted after."""
    if st.mode == MODE_OLLAMA:
        return await _send_ollama(st, messages)
    if st.mode == MODE_OPENAI_SCHEMA:
        try:
            return await _send_openai_schema(st, messages)
        except _RejectedFormat as exc:
            logger.info(json.dumps({
                "event": "structured_response_format_rejected", "task": st.task, "status": exc.args[0],
            }))
            st.mode = MODE_OPENAI_PROMPTED
    if st.mode == MODE_ANTHROPIC:
        return await _prompted_sender(_anthropic(messages, st.cfg, st.max_tokens, 0, st.timeout))
    if st.mode == MODE_GEMINI:
        return await _prompted_sender(_gemini(messages, st.cfg, st.max_tokens, 0, st.timeout))
    return await _prompted_sender(_openai_compat(messages, st.cfg, st.max_tokens, 0, st.timeout, task=st.task))


async def _structured_mode(cfg: LLMConfig) -> str:
    if cfg.provider == "kobold":
        return MODE_OLLAMA if await detect_backend(cfg.api_url) == BACKEND_OLLAMA else MODE_OPENAI_SCHEMA
    if cfg.provider in ("openai", "custom"):
        return MODE_OPENAI_SCHEMA
    if cfg.provider == "anthropic":
        return MODE_ANTHROPIC
    if cfg.provider == "gemini":
        return MODE_GEMINI
    return MODE_OPENAI_PROMPTED


async def complete_structured(
    messages: list[dict],
    schema: type[BaseModel],
    config: LLMConfig | None = None,
    *,
    task: str = STRUCTURED_BUDGET_TASK,
    timeout: float = 120,
    gate_class: GateClass | str | None = None,
    max_tokens: int | None = None,
) -> BaseModel:
    """A validated `schema` instance from the model, at temperature 0.

    schema: a flat pydantic model (an app/schemas/llm FlatModel); ValueError
    before any request if its JSON schema isn't flat. The schema is restated
    in the final user turn of a copy of messages (schema_prompt) and enforced
    per backend: Ollama `format`; strict `response_format` for KoboldCpp,
    openai and custom (that attempt retried prompted on a 4xx, and prompted
    from then on); prompted JSON for anthropic, gemini and anything else.

    Every reply goes through schema.model_validate_json (after stripping a
    code fence, or chatter around the object). An invalid reply gets at most
    two repair turns quoting the errors, then StructuredOutputError
    (ai_output_unusable, attempts=3). For the platform LLM one gate slot
    (gate_class, default llm_gate.current_class) is held for the first call
    and every repair; BYOK never touches the gate.

    task: names the call in logs, stats and the json_schema, picks the model
    (model_for) and the prompt budget (its TASK_POLICIES entry, else
    "structured"). max_tokens defaults to that budget's reserved output; a
    larger one shrinks the prompt window to match.

    Raises PromptBudgetError (platform prompt over the window; no request),
    LLMBusy (no gate slot), LLMUnavailable (backend down, timeout, 5xx,
    empty reply, or a key-less openai call's 401), LLMConfigError (missing
    anthropic/gemini key). None of those is an attempt or triggers a repair.
    A repair prompt that can't fit the window ends the call early with
    StructuredOutputError (attempts = attempts made)."""
    cfg = config or get_default_config()
    json_schema = _checked_schema(schema)
    base = _with_schema(messages, schema_prompt(schema))

    budget_task = task if task in TASK_POLICIES else STRUCTURED_BUDGET_TASK
    reserved = TASK_POLICIES[budget_task].reserved_output
    mt = max_tokens if max_tokens is not None else reserved
    window: int | None = None
    if uses_platform_llm(cfg):
        # A max_tokens above the task's reserve shrinks the prompt window to match.
        window = get_settings().ollama_context_length - max(mt, reserved)
        needed = estimate_messages(base)
        if needed > window:
            raise PromptBudgetError(
                f"Structured prompt for {task!r} needs ~{needed} tokens but the window is {window}."
            )

    st = _Structured(cfg, task, json_schema, await _structured_mode(cfg), mt, timeout)
    errors: list[dict] = []
    async with gated(cfg, gate_class):
        prompt = base
        for attempt in range(1, STRUCTURED_MAX_ATTEMPTS + 1):
            started = time.monotonic()
            raw = await _send_structured(st, prompt)
            result, errors = _validate(raw, schema)
            line = {
                "event": "structured_attempt",
                "task": task,
                "attempt": attempt,
                "valid": result is not None,
                "backend": st.mode,
                "ms": round((time.monotonic() - started) * 1000),
            }
            if result is None:
                # Where and how it failed only: no msg, no input text.
                line["errors"] = [{"loc": e["loc"], "type": e["type"]} for e in errors[:LOG_ERRORS_MAX]]
            logger.info(json.dumps(line))
            if result is not None:
                _bump_stat(task, "first_try_valid" if attempt == 1 else "valid_after_repair")
                return result
            if attempt < STRUCTURED_MAX_ATTEMPTS:
                try:
                    prompt = _repair_messages(base, raw, errors, window)
                except PromptBudgetError as exc:
                    # Requests were already sent: the output is unusable, not the prompt.
                    _bump_stat(task, "failed")
                    raise StructuredOutputError(
                        "The AI's output was unusable, and a repair prompt would not fit. Please try again.",
                        attempts=attempt,
                        errors=errors,
                    ) from exc
    _bump_stat(task, "failed")
    raise StructuredOutputError(
        "The AI's output was unusable, even after asking it to fix it. Please try again.",
        attempts=STRUCTURED_MAX_ATTEMPTS,
        errors=errors,
    )


def _openai_compat_target(cfg: LLMConfig, task: str | None) -> tuple[str, str]:
    """(base URL, model) for an OpenAI-compatible provider."""
    if cfg.provider == "openai":
        return "https://api.openai.com", cfg.model or "gpt-4o-mini"
    if cfg.provider == "kobold":
        # "koboldcpp" used to be a safe placeholder here because real
        # KoboldCpp ignores the "model" field entirely. Ollama's OpenAI-compat
        # endpoint (the actual backend behind KOBOLD_URL on this deployment —
        # see config.py's kobold_model) does NOT ignore it: it 404s with
        # "model 'koboldcpp' not found" if the field doesn't match a real
        # model name. So a kobold config always names a real model: the fixed
        # local model for the platform (model_for), else the configured
        # default.
        base = (cfg.api_url or get_settings().kobold_url).rstrip("/")
        return base, model_for(task, cfg) or get_settings().kobold_model
    base = (cfg.api_url or "http://localhost:5001").rstrip("/")
    return base, cfg.model or "local-model"


async def stream_messages(
    messages: list[dict],
    config: LLMConfig | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = 120,
    *,
    task: str | None = None,
    gate_class: GateClass | str | None = None,
    options: dict | None = None,
):
    """Async generator of completion-text deltas. True token streaming for
    every OpenAI-compatible provider (the self-hosted Ollama default, OpenAI,
    custom endpoints); Anthropic/Gemini fall back to yielding the complete
    reply as one chunk — the streaming chat endpoint stays correct for every
    provider, just progressively rendered only where the wire format is the
    one we speak. Raises the same 503 HTTPException as complete_messages on
    failure (before the first chunk; mid-stream errors end the stream).

    task/gate_class/options as for complete_messages. For the platform LLM
    the whole upstream stream runs inside one gate slot, released when the
    stream ends or the generator is closed (client disconnect). SSE routes
    should reserve_slot() first so a busy gate is a 503, not a broken stream."""
    cfg = config or get_default_config()
    if cfg.provider not in ("kobold", "openai", "custom"):
        yield await complete_messages(
            messages, cfg, max_tokens, temperature, timeout,
            task=task, gate_class=gate_class, options=options,
        )
        return
    # A plain reserve/release, not gated(): held() would set the _held
    # contextvar inside this generator, leaking it into the consumer's
    # context between yields. Reentrancy still holds: reserve_slot returns a
    # no-op Slot when the caller already holds one.
    slot = await reserve_slot(cfg, gate_class)
    try:
        # aclosing: on an early close the upstream HTTP stream is shut before
        # the slot is released, not whenever the inner generator is collected.
        async with aclosing(_stream_openai_compat(
            messages, cfg, max_tokens, temperature, timeout,
            task=task, options=strip_local_options(options),
        )) as upstream:
            async for delta in upstream:
                yield delta
    finally:
        await slot.release()


async def _stream_openai_compat(
    messages: list[dict],
    cfg: LLMConfig,
    max_tokens: int | None,
    temperature: float | None,
    timeout: float,
    *,
    task: str | None,
    options: dict,
):
    mt = max_tokens if max_tokens is not None else cfg.max_tokens
    temp = temperature if temperature is not None else cfg.temperature
    base, model = _openai_compat_target(cfg, task)

    headers: dict[str, str] = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    # Explicit arguments win over same-named options.
    payload = {
        **options,
        "model": model,
        "messages": messages,
        "max_tokens": mt,
        "temperature": temp,
        "stream": True,
    }

    import json as _json
    got_any = False
    try:
        async with _client(timeout) as client:
            async with client.stream("POST", f"{base}/v1/chat/completions", json=payload, headers=headers) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = _json.loads(data)["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, ValueError):
                        continue
                    if delta:
                        got_any = True
                        yield delta
        if not got_any:
            raise ValueError("Empty response from model")
    except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
        if got_any:
            return  # partial reply already delivered — end quietly, don't 503 mid-stream
        raise HTTPException(status_code=503, detail=f"AI model unavailable: {exc}") from exc


# ---------------------------------------------------------------------------

async def _openai_compat(
    messages: list[dict],
    cfg: LLMConfig,
    max_tokens: int,
    temperature: float,
    timeout: float,
    *,
    task: str | None = None,
    options: dict | None = None,
) -> str:
    base, model = _openai_compat_target(cfg, task)

    headers: dict[str, str] = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    # Explicit arguments win over same-named options.
    payload = {
        **strip_local_options(options),
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,  # options must not turn this into an SSE response
    }

    try:
        async with _client(timeout) as client:
            r = await client.post(f"{base}/v1/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            if not content:
                raise ValueError("Empty response from model")
            return content
    except (httpx.TimeoutException, httpx.HTTPStatusError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"AI model unavailable: {exc}") from exc


async def _anthropic(
    messages: list[dict],
    cfg: LLMConfig,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> str:
    if not cfg.api_key:
        raise HTTPException(status_code=400, detail="Anthropic API key is required.")

    model = cfg.model or "claude-haiku-4-5-20251001"

    system_parts: list[str] = []
    conv_messages: list[dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            conv_messages.append(msg)

    if not conv_messages:
        conv_messages = [{"role": "user", "content": "Hello"}]

    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": conv_messages,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    headers = {
        "x-api-key": cfg.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with _client(timeout) as client:
            r = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            r.raise_for_status()
            content = r.json()["content"][0]["text"].strip()
            if not content:
                raise ValueError("Empty response")
            return content
    except (httpx.TimeoutException, httpx.HTTPStatusError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Anthropic API error: {exc}") from exc


async def _gemini(
    messages: list[dict],
    cfg: LLMConfig,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> str:
    if not cfg.api_key:
        raise HTTPException(status_code=400, detail="Gemini API key is required.")

    # Google retired the entire Gemini 1.5 line (shutdown completed Sept
    # 2025) — generateContent now 404s for gemini-1.5-flash/-pro with no
    # more specific error, which reads exactly like a bad key if you don't
    # know to check the model id. A pinned "gemini-2.5-flash" id *still*
    # 404'd for at least one real key even after that fix — Google's own
    # current quickstart (AI Studio's "Get API key" panel) points at the
    # "-latest" alias instead of a pinned version, so use that as the
    # default; keep this in sync with SettingsPage.tsx's PROVIDER_MODELS.
    model = cfg.model or "gemini-flash-latest"

    system_text: str | None = None
    contents: list[dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    try:
        async with _client(timeout) as client:
            # Header auth, not the ?key= query param — Google's own current
            # quickstart uses X-goog-api-key, and at least one real key 404'd
            # via the query param even against a model id confirmed to exist.
            # Newer keys appear to be scoped in a way the query-param path
            # doesn't resolve the same way; the header form is what Google's
            # own docs show right now, so match it exactly rather than guess.
            r = await client.post(
                url, json=payload, headers={"X-goog-api-key": cfg.api_key}
            )
            r.raise_for_status()
            candidate = r.json()["candidates"][0]
            # Confirmed live: when maxOutputTokens is too small for Gemini's
            # internal thinking pass to finish, "content" comes back as {}
            # with no "parts" key at all (finishReason "MAX_TOKENS") — not
            # empty text, an absent key. The blind ["parts"][0] index below
            # turned that into a bare, meaningless `KeyError: 'parts'`.
            # Surface what actually happened instead.
            parts = candidate.get("content", {}).get("parts")
            if not parts:
                if candidate.get("finishReason") == "MAX_TOKENS":
                    raise ValueError(
                        "Gemini used its entire token budget on internal "
                        "reasoning before producing any output — raise Max "
                        "Tokens in Settings."
                    )
                raise ValueError(f"No content in Gemini response (finishReason={candidate.get('finishReason')})")
            content = parts[0]["text"].strip()
            if not content:
                raise ValueError("Empty response")
            return content
    except (httpx.TimeoutException, httpx.HTTPStatusError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Gemini API error: {exc}") from exc


async def test_provider_connection(cfg: LLMConfig) -> str:
    """Send a trivial request; return the response text or raise HTTPException."""
    messages = [{"role": "user", "content": "Reply with only the word OK."}]
    # kobold (self-hosted or the platform's own Ollama) gets a much longer
    # timeout than a real API provider needs — a cold model load (first
    # request after a switch, e.g. Settings' Fine-Tuned/Base toggle) took
    # ~60s for a 7B Q4 model on the production ARM CPU host, confirmed live.
    # OLLAMA_KEEP_ALIVE (see docker-compose.prod.yml) keeps a model resident
    # afterward so this only bites on the first request to a given model,
    # but that first request is exactly what Test Connection usually is.
    timeout = 90 if cfg.provider == "kobold" else 15
    # Was 10 — reasoning models (confirmed live: Gemini's current
    # gemini-flash-latest, which now resolves to gemini-3.7-flash) spend
    # part of maxOutputTokens on an internal thinking pass before any
    # answer text, and thinkingConfig.thinkingBudget=0 does NOT suppress
    # this for that model (tested directly against the API: thoughtsToken-
    # Count stayed >0 regardless). At 10, thinking alone consumed the
    # entire budget and Gemini returned candidates[0].content as {} with no
    # "parts" key at all — not an empty string, an absent key — so parsing
    # crashed with a bare `KeyError: 'parts'` instead of a real error
    # message. 128 leaves headroom for a few dozen thinking tokens plus the
    # one-word answer on every provider we support, not just Gemini.
    # task="narrative": Test Connection checks the variant the user picked
    # (Fine-Tuned/Base), not the fixed local model.
    return await complete_messages(
        messages, cfg, max_tokens=128, temperature=0.1, timeout=timeout, task="narrative"
    )
