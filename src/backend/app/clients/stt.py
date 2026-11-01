"""Client for the `stt` sidecar (src/services/stt): faster-whisper speech-to-text.

    from app.clients import stt
    t = await stt.transcribe(webm_bytes, initial_prompt="Borin, Waterdeep")
    t = await stt.transcribe(pcm16_bytes, format="pcm16")   # raw s16le 16 kHz mono
    t.text, t.language, t.segments, t.rtf
    # stt.transcribe uses get_stt_client(); call that directly for status().

Both shapes go as one multipart request: the audio is always the `file` part
and `initial_prompt` a form field (a long glossary prompt never goes in the
URL); only the `format` query says the bytes are raw PCM16.

Failure contract (same as app/clients/ml.py):
  - connect error, timeout, or a 5xx     -> ModelServiceUnavailable
  - 4xx (status_code set), a malformed
    body, or another httpx error          -> ModelServiceError
The client never retries (see app/clients/errors.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.clients.errors import ModelServiceError, ModelServiceUnavailable
from app.clients.ml import ModelState
from app.core.config import Settings, get_settings

# Connecting is quick or not happening at all; only the read waits on the model.
_CONNECT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None
    segments: list[TranscriptSegment] = field(default_factory=list)
    rtf: float = 0.0  # processing time / audio duration (0 for empty audio)


@dataclass(frozen=True)
class STTStatus:
    models: list[ModelState]
    compute_type: str
    device: str
    rss_bytes: int


class STTClientProtocol(Protocol):
    async def transcribe(self, audio: bytes, *, initial_prompt: str | None = None,
                         format: Literal["pcm16"] | None = None) -> Transcript: ...
    async def status(self) -> STTStatus: ...


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class STTClient:
    """HTTP client. Opens a short-lived httpx.AsyncClient per call, so one
    instance is safe to share across event loops and workers."""

    def __init__(self, base_url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        timeout = httpx.Timeout(self.timeout_s, connect=min(_CONNECT_TIMEOUT_S, self.timeout_s))
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=timeout, transport=self._transport
            ) as http:
                resp = await http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ModelServiceUnavailable(f"stt sidecar timed out after {self.timeout_s}s on {path}") from exc
        except httpx.TransportError as exc:
            raise ModelServiceUnavailable(f"stt sidecar unreachable at {self.base_url}: {exc!r}") from exc
        except httpx.HTTPError as exc:  # DecodingError, TooManyRedirects, ...: still typed
            raise ModelServiceError(f"stt sidecar request to {path} failed: {exc!r}") from exc

        if resp.status_code >= 500:
            raise ModelServiceUnavailable(
                f"stt sidecar returned {resp.status_code} on {path}", status_code=resp.status_code
            )
        if resp.status_code >= 400:
            raise ModelServiceError(
                f"stt sidecar rejected {path} with {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ModelServiceError(f"stt sidecar returned non-JSON on {path}",
                                    status_code=resp.status_code) from exc

    async def transcribe(self, audio: bytes, *, initial_prompt: str | None = None,
                         format: Literal["pcm16"] | None = None) -> Transcript:
        kwargs: dict[str, Any] = {"files": {"file": ("audio", audio, "application/octet-stream")}}
        if initial_prompt is not None:
            kwargs["data"] = {"initial_prompt": initial_prompt}
        if format is not None:
            kwargs["params"] = {"format": format}
        body = await self._request("POST", "/v1/transcribe", **kwargs)
        return _parse_transcript(body)

    async def status(self) -> STTStatus:
        body = await self._request("GET", "/v1/status")
        try:
            models = [ModelState(name=m["name"], kind=m["kind"], state=m["state"]) for m in body["models"]]
            compute_type, device, rss = body["compute_type"], body["device"], body["rss_bytes"]
        except (KeyError, TypeError) as exc:
            raise ModelServiceError("stt /v1/status: malformed response") from exc
        if not (all(isinstance(x, str) for m in models for x in (m.name, m.kind, m.state))
                and isinstance(compute_type, str) and isinstance(device, str) and _is_int(rss)):
            raise ModelServiceError("stt /v1/status: malformed response")
        return STTStatus(models=models, compute_type=compute_type, device=device, rss_bytes=rss)


def _parse_transcript(body: Any) -> Transcript:
    bad = ModelServiceError("stt /v1/transcribe: malformed response")
    if not isinstance(body, dict):
        raise bad
    text, language, segments, rtf = (body.get(k) for k in ("text", "language", "segments", "rtf"))
    if not isinstance(text, str) or not (language is None or isinstance(language, str)):
        raise bad
    if not isinstance(segments, list) or not _is_number(rtf):
        raise bad
    out = []
    for s in segments:
        if not (isinstance(s, dict) and _is_int(s.get("start_ms")) and _is_int(s.get("end_ms"))
                and isinstance(s.get("text"), str)):
            raise bad
        out.append(TranscriptSegment(start_ms=s["start_ms"], end_ms=s["end_ms"], text=s["text"]))
    return Transcript(text=text, language=language, segments=out, rtf=float(rtf))


_clients: dict[tuple[str, float], STTClient] = {}


def get_stt_client(settings: Settings | None = None) -> STTClientProtocol:
    """The process's STT client: FakeSTTClient under ENVIRONMENT=test, else
    an STTClient for settings.stt_url / settings.stt_timeout_s."""
    s = settings or get_settings()
    if s.environment == "test":
        from app.clients.fakes import FakeSTTClient

        return FakeSTTClient()
    key = (s.stt_url, float(s.stt_timeout_s))
    if key not in _clients:
        _clients[key] = STTClient(s.stt_url, s.stt_timeout_s)
    return _clients[key]


async def transcribe(audio: bytes, *, initial_prompt: str | None = None,
                     format: Literal["pcm16"] | None = None) -> Transcript:
    """Transcribe with the process's client (get_stt_client()); same errors."""
    return await get_stt_client().transcribe(audio, initial_prompt=initial_prompt, format=format)
