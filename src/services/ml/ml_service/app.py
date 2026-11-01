"""HTTP surface of the `ml` sidecar.

  GET  /healthz    200 once every model is loaded, else 503 (Docker healthcheck)
  GET  /v1/status  {models: [{name, kind, state}], rss_bytes}
  POST /v1/embed   {texts: [str] (<= 256)} -> {model, dim, vectors}
  POST /v1/ner     {text: str} -> {ents: [{text, label, start, end}]}

Models load in the lifespan, before uvicorn accepts connections, so a
running container is a loaded one. Routes are plain `def`, so FastAPI runs
them in its threadpool and the per-model locks in ModelSlot do the
serialising.
"""

from __future__ import annotations

import os
import resource
import sys
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ml_service.config import MAX_EMBED_TEXTS, Config, load_config
from ml_service.models import (
    Embedder,
    ModelSlot,
    NerModel,
    SentenceTransformerEmbedder,
    SpacyNer,
)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., max_length=MAX_EMBED_TEXTS)


class EmbedResponse(BaseModel):
    model: str
    dim: int
    vectors: list[list[float]]


class NerRequest(BaseModel):
    text: str


class EntityOut(BaseModel):
    text: str
    label: str
    start: int
    end: int


class NerResponse(BaseModel):
    ents: list[EntityOut]


class ModelStatus(BaseModel):
    name: str
    kind: str
    state: str


class StatusResponse(BaseModel):
    models: list[ModelStatus]
    rss_bytes: int


def rss_bytes() -> int:
    """Current resident set size; peak RSS where /proc is unavailable."""
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is bytes on macOS, KiB on Linux and the BSDs.
        return int(peak if sys.platform == "darwin" else peak * 1024)


def create_app(
    config: Config | None = None,
    embedder_factory: Callable[[Config], Embedder] | None = None,
    ner_factory: Callable[[Config], NerModel] | None = None,
) -> FastAPI:
    cfg = config or load_config()
    make_embedder = embedder_factory or (
        lambda c: SentenceTransformerEmbedder(c.embed_model_path, c.embed_batch_size)
    )
    make_ner = ner_factory or (lambda c: SpacyNer(c.ner_model_name))

    embed_slot = ModelSlot(cfg.embed_model_name, "embedding", lambda: make_embedder(cfg))
    ner_slot = ModelSlot(cfg.ner_model_name, "ner", lambda: make_ner(cfg))
    slots = [embed_slot, ner_slot]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for slot in slots:
            slot.load()  # fail fast: a sidecar that cannot load its models never turns healthy
        yield

    app = FastAPI(title="Lorekeeper ml sidecar", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.slots = slots

    @app.get("/healthz")
    def healthz():
        if all(s.state == "loaded" for s in slots):
            return {"status": "ok"}
        return JSONResponse(status_code=503, content={"status": "loading"})

    @app.get("/v1/status", response_model=StatusResponse)
    def status():
        return StatusResponse(
            models=[ModelStatus(name=s.name, kind=s.kind, state=s.state) for s in slots],
            rss_bytes=rss_bytes(),
        )

    @app.post("/v1/embed", response_model=EmbedResponse)
    def embed(req: EmbedRequest):
        vectors = embed_slot.run(lambda m: m.encode(req.texts)) if req.texts else []
        return EmbedResponse(model=cfg.embed_model_name, dim=cfg.embed_dim, vectors=vectors)

    @app.post("/v1/ner", response_model=NerResponse)
    def ner(req: NerRequest):
        ents = ner_slot.run(lambda m: m.extract(req.text))
        return NerResponse(ents=[EntityOut(text=e.text, label=e.label, start=e.start, end=e.end)
                                 for e in ents])

    return app


# Building the app loads nothing (models load in the lifespan), so importing
# this module stays cheap. uvicorn serves "ml_service.app:app".
app = create_app()
