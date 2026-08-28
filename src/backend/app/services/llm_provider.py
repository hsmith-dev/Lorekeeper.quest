"""Unified LLM provider — routes completions to KoboldCpp, OpenAI, Anthropic, or Gemini."""

from dataclasses import dataclass, field
import httpx
from fastapi import HTTPException
from app.core.config import get_settings


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


async def complete_messages(
    messages: list[dict],
    config: LLMConfig | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = 120,
) -> str:
    """Send messages (OpenAI format) to configured provider and return completion text."""
    cfg = config or get_default_config()
    mt = max_tokens if max_tokens is not None else cfg.max_tokens
    temp = temperature if temperature is not None else cfg.temperature

    if cfg.provider in ("kobold", "openai", "custom"):
        return await _openai_compat(messages, cfg, mt, temp, timeout)
    if cfg.provider == "anthropic":
        return await _anthropic(messages, cfg, mt, temp, timeout)
    if cfg.provider == "gemini":
        return await _gemini(messages, cfg, mt, temp, timeout)
    return await _openai_compat(messages, cfg, mt, temp, timeout)


# ---------------------------------------------------------------------------

async def _openai_compat(
    messages: list[dict],
    cfg: LLMConfig,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> str:
    if cfg.provider == "openai":
        base = "https://api.openai.com"
        model = cfg.model or "gpt-4o-mini"
    elif cfg.provider == "kobold":
        base = (cfg.api_url or get_settings().kobold_url).rstrip("/")
        # "koboldcpp" used to be a safe placeholder here because real
        # KoboldCpp ignores the "model" field entirely. Ollama's OpenAI-compat
        # endpoint (the actual backend behind KOBOLD_URL on this deployment —
        # see config.py's kobold_model) does NOT ignore it: it 404s with
        # "model 'koboldcpp' not found" if the field doesn't match a real
        # model name. Every caller that builds an LLMConfig(provider="kobold")
        # without an explicit model (e.g. Settings' Test Connection / Evaluate
        # routes when the user picked "Use Lorekeeper AI") was hitting this —
        # fall back to the configured default model instead of the old
        # KoboldCpp-only placeholder.
        model = cfg.model or get_settings().kobold_model
    else:
        base = (cfg.api_url or "http://localhost:5001").rstrip("/")
        model = cfg.model or "local-model"

    headers: dict[str, str] = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
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
        async with httpx.AsyncClient(timeout=timeout) as client:
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
        async with httpx.AsyncClient(timeout=timeout) as client:
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
    return await complete_messages(messages, cfg, max_tokens=128, temperature=0.1, timeout=timeout)
