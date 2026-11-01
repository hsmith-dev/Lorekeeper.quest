"""Client for the `ml` sidecar (src/services/ml): embeddings and NER.

    client = get_ml_client()
    vectors = await client.embed(["text a", "text b"])   # 384-d unit vectors
    ents = await client.ner("Borin Stonebeard reached Waterdeep.")

Failure contract:
  - connect error, timeout, or a 5xx            -> ModelServiceUnavailable
  - 4xx, a malformed body, wrong model/dim, or a
    vector count that differs from the texts     -> ModelServiceError
The client never retries (see app/clients/errors.py).

Nothing calls this yet: embedding_service / nlp_service move over in
E0-Platform.6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.clients.errors import ModelServiceError, ModelServiceUnavailable
from app.core.config import Settings, get_settings
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL


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
    state: str


@dataclass(frozen=True)
class MLStatus:
    models: list[ModelState]
    rss_bytes: int


class MLClientProtocol(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def ner(self, text: str) -> list[NamedEntity]: ...
    async def status(self) -> MLStatus: ...


class MLClient:
    """HTTP client. Opens a short-lived httpx.AsyncClient per call, so one
    instance is safe to share across event loops and workers."""

    def __init__(self, base_url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport

    async def _request(self, method: str, path: str, json: Any = None) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s, transport=self._transport
            ) as http:
                resp = await http.request(method, path, json=json)
        except httpx.TimeoutException as exc:
            raise ModelServiceUnavailable(f"ml sidecar timed out after {self.timeout_s}s on {path}") from exc
        except httpx.TransportError as exc:
            raise ModelServiceUnavailable(f"ml sidecar unreachable at {self.base_url}: {exc!r}") from exc

        if resp.status_code >= 500:
            raise ModelServiceUnavailable(
                f"ml sidecar returned {resp.status_code} on {path}", status_code=resp.status_code
            )
        if resp.status_code >= 400:
            raise ModelServiceError(
                f"ml sidecar rejected {path} with {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ModelServiceError(f"ml sidecar returned non-JSON on {path}",
                                    status_code=resp.status_code) from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = await self._request("POST", "/v1/embed", {"texts": list(texts)})
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

    async def status(self) -> MLStatus:
        body = await self._request("GET", "/v1/status")
        try:
            return MLStatus(
                models=[ModelState(name=m["name"], kind=m["kind"], state=m["state"]) for m in body["models"]],
                rss_bytes=int(body["rss_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelServiceError("ml /v1/status: malformed response") from exc


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
