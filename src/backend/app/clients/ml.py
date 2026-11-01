"""Client for the `ml` sidecar (src/services/ml): embeddings, NER, NLI, OCR.

    client = get_ml_client()
    vectors = await client.embed(["text a", "text b"])   # 384-d unit vectors
    ents = await client.ner("Borin Stonebeard reached Waterdeep.")
    scores = await client.nli([("Mira died.", "Mira greeted the party.")])
    text = await client.ocr(png_bytes)

Failure contract:
  - connect error, timeout, or a 5xx            -> ModelServiceUnavailable
    (including 503 ml_budget: the sidecar could not fit a lazy model in its
    resident budget; the detail names the sidecar's error code)
  - 4xx, a malformed body, wrong model/dim, or a
    vector / score count that differs from the input -> ModelServiceError
The client never retries (see app/clients/errors.py).

NLI and OCR load on their first request in the sidecar, so that request can
take a few seconds longer. Nothing calls this yet: embedding_service /
nlp_service / vision_service move over in E0-Platform.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.clients.errors import ModelServiceError, ModelServiceUnavailable
from app.core.config import Settings, get_settings
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL

# The sidecar rejects larger /v1/embed bodies with 422 (ml_service/config.py
# MAX_EMBED_TEXTS); embed() splits longer lists into batches of this size.
MAX_EMBED_TEXTS = 256
# Same for /v1/nli pairs (ml_service/config.py MAX_NLI_PAIRS).
MAX_NLI_PAIRS = 256
NLI_LABELS = ("entailment", "neutral", "contradiction")


@dataclass(frozen=True)
class NliScores:
    """Softmax over the three NLI labels for one (premise, hypothesis) pair;
    the three sum to 1. No threshold is applied here: that is the caller's."""

    entailment: float
    neutral: float
    contradiction: float


@dataclass(frozen=True)
class NamedEntity:
    """A span of the request text: text[start:end] == self.text.

    label is the raw spaCy label (PERSON, GPE, LOC, FAC, ORG, ...) or the
    sidecar Matcher's ITEM / QUEST; mapping to TagType is the caller's job."""

    text: str
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class ModelState:
    name: str
    kind: str
    state: str  # not_loaded | loading | loaded | failed
    lazy: bool = False
    cost_mb: int | None = None


@dataclass(frozen=True)
class MLStatus:
    models: list[ModelState]
    rss_bytes: int
    resident_budget_mb: int | None = None
    lazy_resident_mb: int | None = None


class MLClientProtocol(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def ner(self, text: str) -> list[NamedEntity]: ...
    async def nli(self, pairs: list[tuple[str, str]]) -> list[NliScores]: ...
    async def ocr(self, image: bytes, filename: str = "image") -> str: ...
    async def status(self) -> MLStatus: ...


def _error_suffix(resp: httpx.Response) -> str:
    """" (ml_budget: ml budget exceeded)" from a sidecar {detail, code} body;
    otherwise the start of the raw text."""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("code"), str):
        return f" ({body['code']}: {str(body.get('detail', ''))[:200]})"
    text = resp.text[:200]
    return f": {text}" if text else ""


class MLClient:
    """HTTP client. Opens a short-lived httpx.AsyncClient per call, so one
    instance is safe to share across event loops and workers."""

    def __init__(self, base_url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    async def _request(self, method: str, path: str, json: Any = None, files: Any = None) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
            ) as http:
                resp = await http.request(method, path, json=json, files=files)
        except httpx.TimeoutException as exc:
            raise ModelServiceUnavailable(f"ml sidecar timed out after {self.timeout_s}s on {path}") from exc
        except httpx.TransportError as exc:
            raise ModelServiceUnavailable(f"ml sidecar unreachable at {self.base_url}: {exc!r}") from exc
        except httpx.HTTPError as exc:  # DecodingError, TooManyRedirects, ...: still typed
            raise ModelServiceError(f"ml sidecar request to {path} failed: {exc!r}") from exc

        if resp.status_code >= 500:
            raise ModelServiceUnavailable(
                f"ml sidecar returned {resp.status_code} on {path}{_error_suffix(resp)}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise ModelServiceError(
                f"ml sidecar rejected {path} with {resp.status_code}{_error_suffix(resp)}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ModelServiceError(f"ml sidecar returned non-JSON on {path}",
                                    status_code=resp.status_code) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Vectors in input order; batches of MAX_EMBED_TEXTS per request."""
        texts = list(texts)
        vectors: list[list[float]] = []
        for i in range(0, len(texts), MAX_EMBED_TEXTS):
            vectors.extend(await self._embed_batch(texts[i:i + MAX_EMBED_TEXTS]))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = await self._request("POST", "/v1/embed", {"texts": texts})
        if not isinstance(body, dict):
            raise ModelServiceError("ml /v1/embed: response is not an object")
        if body.get("model") != EMBEDDING_MODEL:
            raise ModelServiceError(f"ml /v1/embed: model {body.get('model')!r}, expected {EMBEDDING_MODEL!r}")
        if body.get("dim") != EMBEDDING_DIM:
            raise ModelServiceError(f"ml /v1/embed: dim {body.get('dim')!r}, expected {EMBEDDING_DIM}")
        vectors = body.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            got = len(vectors) if isinstance(vectors, list) else type(vectors).__name__
            raise ModelServiceError(f"ml /v1/embed: {got} vectors for {len(texts)} texts")
        for v in vectors:
            if not isinstance(v, list) or len(v) != EMBEDDING_DIM:
                raise ModelServiceError(f"ml /v1/embed: a vector is not {EMBEDDING_DIM}-d")
        return vectors

    async def ner(self, text: str) -> list[NamedEntity]:
        body = await self._request("POST", "/v1/ner", {"text": text})
        try:
            return [NamedEntity(text=str(e["text"]), label=str(e["label"]),
                                start=int(e["start"]), end=int(e["end"]))
                    for e in body["ents"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelServiceError("ml /v1/ner: malformed response") from exc

    async def nli(self, pairs: list[tuple[str, str]]) -> list[NliScores]:
        """Scores in input order; batches of MAX_NLI_PAIRS per request.

        The sidecar accepts up to 4000 chars per side, but each pair (premise +
        hypothesis) is silently truncated to the model's 512-token window, so
        send sentence-sized texts."""
        pairs = [(str(p), str(h)) for p, h in pairs]
        scores: list[NliScores] = []
        for i in range(0, len(pairs), MAX_NLI_PAIRS):
            scores.extend(await self._nli_batch(pairs[i:i + MAX_NLI_PAIRS]))
        return scores

    async def _nli_batch(self, pairs: list[tuple[str, str]]) -> list[NliScores]:
        body = await self._request(
            "POST", "/v1/nli", {"pairs": [{"premise": p, "hypothesis": h} for p, h in pairs]}
        )
        raw = body.get("scores") if isinstance(body, dict) else None
        if not isinstance(raw, list) or len(raw) != len(pairs):
            got = len(raw) if isinstance(raw, list) else type(raw).__name__
            raise ModelServiceError(f"ml /v1/nli: {got} scores for {len(pairs)} pairs")
        out = []
        for s in raw:
            if not isinstance(s, dict) or set(s) != set(NLI_LABELS) or not all(
                isinstance(s[k], (int, float)) and not isinstance(s[k], bool) for k in NLI_LABELS
            ):
                raise ModelServiceError(f"ml /v1/nli: a score is not {{{', '.join(NLI_LABELS)}}} numbers")
            out.append(NliScores(**{k: float(s[k]) for k in NLI_LABELS}))
        return out

    async def ocr(self, image: bytes, filename: str = "image") -> str:
        """The image's text (stripped non-empty lines joined with "\\n").
        An empty or undecodable image is a 422 from the sidecar, so a
        ModelServiceError; over 10 MiB is a 413, likewise."""
        body = await self._request(
            "POST", "/v1/ocr", files={"file": (filename, bytes(image), "application/octet-stream")}
        )
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise ModelServiceError("ml /v1/ocr: response has no `text` string")
        return text

    async def status(self) -> MLStatus:
        body = await self._request("GET", "/v1/status")
        try:
            return MLStatus(
                models=[ModelState(name=m["name"], kind=m["kind"], state=m["state"],
                                   lazy=bool(m.get("lazy", False)),
                                   cost_mb=None if m.get("cost_mb") is None else int(m["cost_mb"]))
                        for m in body["models"]],
                rss_bytes=int(body["rss_bytes"]),
                resident_budget_mb=_opt_int(body.get("resident_budget_mb")),
                lazy_resident_mb=_opt_int(body.get("lazy_resident_mb")),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ModelServiceError("ml /v1/status: malformed response") from exc


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


_clients: dict[tuple[str, float], MLClient] = {}


def get_ml_client(settings: Settings | None = None) -> MLClientProtocol:
    """The process's ML client: FakeMLClient under ENVIRONMENT=test, else
    an MLClient for settings.ml_url / settings.ml_timeout_s."""
    s = settings or get_settings()
    if s.environment == "test":
        from app.clients.fakes import FakeMLClient

        return FakeMLClient()
    key = (s.ml_url, float(s.ml_timeout_s))
    if key not in _clients:
        _clients[key] = MLClient(s.ml_url, s.ml_timeout_s)
    return _clients[key]
