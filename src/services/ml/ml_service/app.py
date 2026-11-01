"""HTTP surface of the `ml` sidecar.

  GET  /healthz    200 once every resident model is loaded, else 503 (Docker healthcheck)
  GET  /v1/status  {models: [{name, kind, state, lazy, cost_mb}],
                    resident_budget_mb, lazy_resident_mb, rss_bytes}
  POST /v1/embed   {texts: [str] (<= 256)} -> {model, dim, vectors}
  POST /v1/ner     {text: str (<= 100k chars)} -> {ents: [{text, label, start, end}]}
  POST /v1/nli     {pairs: [{premise, hypothesis}] (<= 256, each side <= 4000 chars)}
                   -> {scores: [{entailment, neutral, contradiction}]}
                   Each pair (premise + hypothesis) is silently truncated to the
                   model's 512-token window, so send sentence-sized texts.
  POST /v1/ocr     multipart `file` (<= 10 MiB) -> {text}

The resident models (embeddings, NER) load in the lifespan, before uvicorn
accepts connections, so a running container has them. NLI and OCR are lazy:
each loads on its first request, under the resident-memory budget in
budget.py (503 {"code": "ml_budget"} when it cannot fit). Routes are plain
`def`, so FastAPI runs them in its threadpool and the per-model locks do the
serialising.
"""

from __future__ import annotations

import os
import resource
import sys
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ml_service.budget import BudgetExceeded, LazySlot, ModelLoadFailed, ResidentBudget
from ml_service.config import (
    MAX_EMBED_TEXTS,
    MAX_NER_CHARS,
    MAX_NLI_CHARS,
    MAX_NLI_PAIRS,
    MAX_OCR_BYTES,
    Config,
    load_config,
)
from ml_service.models import (
    NLI_LABELS,
    Embedder,
    InvalidImage,
    ModelSlot,
    NerModel,
    NliModel,
    OcrModel,
    RapidOcrReader,
    SentenceTransformerEmbedder,
    SpacyNer,
    TransformersNli,
)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., max_length=MAX_EMBED_TEXTS)


class EmbedResponse(BaseModel):
    model: str
    dim: int
    vectors: list[list[float]]


class NerRequest(BaseModel):
    text: str = Field(..., max_length=MAX_NER_CHARS)


class EntityOut(BaseModel):
    text: str
    label: str
    start: int
    end: int


class NerResponse(BaseModel):
    ents: list[EntityOut]


class NliPair(BaseModel):
    premise: str = Field(..., max_length=MAX_NLI_CHARS)
    hypothesis: str = Field(..., max_length=MAX_NLI_CHARS)


class NliRequest(BaseModel):
    pairs: list[NliPair] = Field(..., max_length=MAX_NLI_PAIRS)


class NliScore(BaseModel):
    entailment: float
    neutral: float
    contradiction: float


class NliResponse(BaseModel):
    scores: list[NliScore]


class OcrResponse(BaseModel):
    text: str


class ModelStatus(BaseModel):
    name: str
    kind: str
    state: str  # not_loaded | loading | loaded | failed
    lazy: bool
    cost_mb: int | None  # declared budget cost; None for resident models


class StatusResponse(BaseModel):
    models: list[ModelStatus]
    resident_budget_mb: int
    lazy_resident_mb: int
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
    nli_factory: Callable[[Config], NliModel] | None = None,
    ocr_factory: Callable[[Config], OcrModel] | None = None,
) -> FastAPI:
    cfg = config or load_config()
    make_embedder = embedder_factory or (
        lambda c: SentenceTransformerEmbedder(c.embed_model_path, c.embed_batch_size)
    )
    make_ner = ner_factory or (lambda c: SpacyNer(c.ner_model_name))
    make_nli = nli_factory or (lambda c: TransformersNli(c.nli_model_path))
    make_ocr = ocr_factory or (lambda c: RapidOcrReader(c.ocr_model_dir))

    embed_slot = ModelSlot(cfg.embed_model_name, "embedding", lambda: make_embedder(cfg))
    ner_slot = ModelSlot(cfg.ner_model_name, "ner", lambda: make_ner(cfg))
    resident = [embed_slot, ner_slot]

    budget = ResidentBudget(cfg.resident_budget_mb)
    nli_slot = LazySlot(cfg.nli_model_name, "nli", lambda: make_nli(cfg), cfg.nli_cost_mb, budget)
    ocr_slot = LazySlot(cfg.ocr_model_name, "ocr", lambda: make_ocr(cfg), cfg.ocr_cost_mb, budget)
    slots = [*resident, nli_slot, ocr_slot]

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for slot in resident:
            slot.load()  # fail fast: a sidecar that cannot load its models never turns healthy
        yield

    app = FastAPI(title="Lorekeeper ml sidecar", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.slots = slots
    app.state.budget = budget

    @app.exception_handler(BudgetExceeded)
    def _budget_exceeded(request: Request, exc: BudgetExceeded):
        return JSONResponse(status_code=503, content={"detail": "ml budget exceeded", "code": "ml_budget"})

    @app.exception_handler(InvalidImage)
    def _invalid_image(request: Request, exc: InvalidImage):
        return JSONResponse(status_code=422, content={"detail": str(exc), "code": "invalid_image"})

    @app.exception_handler(ModelLoadFailed)
    def _load_failed(request: Request, exc: ModelLoadFailed):
        return JSONResponse(status_code=500, content={"detail": str(exc), "code": "ml_load_failed"})

    @app.get("/healthz")
    def healthz():
        # Resident models only: a lazy model that is not loaded (or failed to
        # load) is not a reason to restart the container.
        if all(s.state == "loaded" for s in resident):
            return {"status": "ok"}
        return JSONResponse(status_code=503, content={"status": "loading"})

    @app.get("/v1/status", response_model=StatusResponse)
    def status():
        return StatusResponse(
            models=[ModelStatus(name=s.name, kind=s.kind, state=s.state, lazy=s.lazy, cost_mb=s.cost_mb)
                    for s in slots],
            resident_budget_mb=budget.budget_mb,
            lazy_resident_mb=budget.resident_mb,
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

    @app.post("/v1/nli", response_model=NliResponse)
    def nli(req: NliRequest):
        if not req.pairs:
            return NliResponse(scores=[])  # the model is not loaded for nothing
        pairs = [(p.premise, p.hypothesis) for p in req.pairs]
        step = cfg.nli_batch_size

        def score_all(model: NliModel) -> list[dict[str, float]]:
            out: list[dict[str, float]] = []
            for i in range(0, len(pairs), step):
                chunk = pairs[i:i + step]
                scores = model.score(chunk)
                if len(scores) != len(chunk):
                    raise RuntimeError(f"NLI returned {len(scores)} scores for {len(chunk)} pairs")
                out.extend(scores)
            return out

        scores = nli_slot.run(score_all)
        return NliResponse(scores=[NliScore(**{k: float(s[k]) for k in NLI_LABELS}) for s in scores])

    @app.post("/v1/ocr", response_model=OcrResponse)
    def ocr(file: UploadFile = File(...)):
        data = file.file.read(MAX_OCR_BYTES + 1)
        if len(data) > MAX_OCR_BYTES:
            return JSONResponse(status_code=413,
                                content={"detail": f"image over {MAX_OCR_BYTES} bytes", "code": "too_large"})
        if not data:
            raise InvalidImage("empty upload")  # rejected before the model loads
        return OcrResponse(text=ocr_slot.run(lambda m: m.read(data)))

    return app


# Building the app loads nothing (resident models load in the lifespan, lazy
# ones on first use), so importing this module stays cheap. uvicorn serves "ml_service.app:app".
app = create_app()
