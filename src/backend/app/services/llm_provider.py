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
"""

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
import httpx
from fastapi import HTTPException
from app.core import llm_gate
from app.core.config import get_settings
from app.core.llm_gate import GateClass, Slot

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
    process. A transport error or timeout returns BACKEND_OPENAI_COMPAT
    without caching it, so an Ollama that was still starting is detected on
    a later call. Never touches the gate and never raises."""
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
