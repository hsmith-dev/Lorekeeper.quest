"""HTTP surface of the `stt` sidecar.

  GET  /healthz        200 {"status":"ok"} when the baked model.bin is present,
                       else 503 {"status":"model_missing"} (Docker healthcheck)
  GET  /v1/status      {models: [{name, kind, state}], compute_type, device, rss_bytes}
  POST /v1/transcribe  multipart `file` (+ optional form `initial_prompt`);
                       `?format=pcm16` marks the file as raw s16le 16 kHz mono
                       -> {text, language, segments: [{start_ms, end_ms, text}], rtf}

The model loads lazily on the first transcription and is dropped again after
STT_IDLE_UNLOAD_S without use, so an idle sidecar costs little memory. The
transcribe route is a plain `def`: FastAPI runs it in its threadpool and the
LazyModelSlot lock does the serialising.
"""

from __future__ import annotations

import os
import resource
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from stt_service.config import MAX_PROMPT_CHARS, MODEL_NAME, SAMPLE_RATE, Config, load_config
from stt_service.models import (
    AudioDecodeError,
    Decoder,
    FasterWhisperModel,
    LazyModelSlot,
    ModelUnavailable,
    SpeechModel,
    Transcription,
    decode_container,
    pcm16_to_float32,
)


class SegmentOut(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class TranscribeResponse(BaseModel):
    text: str
    language: str | None
    segments: list[SegmentOut]
    rtf: float


class ModelStatus(BaseModel):
    name: str
    kind: str
    state: str


class StatusResponse(BaseModel):
    models: list[ModelStatus]
    compute_type: str
    device: str
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


def unload_interval(idle_s: float) -> float:
    """How often the idle unloader looks: min(30 s, idle_s / 4)."""
    return min(30.0, idle_s / 4)


def create_app(
    config: Config | None = None,
    model_factory: Callable[[Config], SpeechModel] | None = None,
    decoder: Decoder | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    cfg = config or load_config()
    make_model = model_factory or FasterWhisperModel
    decode = decoder or decode_container
    slot = LazyModelSlot(MODEL_NAME, "stt", lambda: make_model(cfg), clock=clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        thread = None
        if cfg.idle_unload_s > 0:
            interval = unload_interval(cfg.idle_unload_s)

            def unloader() -> None:
                while not stop.wait(interval):
                    slot.unload_if_idle(clock(), cfg.idle_unload_s)

            thread = threading.Thread(target=unloader, name="stt-idle-unloader", daemon=True)
            thread.start()
        app.state.unloader = thread
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                thread.join(timeout=5)

    app = FastAPI(title="Lorekeeper stt sidecar", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.slot = slot
    app.state.config = cfg
    app.state.unloader = None

    @app.get("/healthz")
    def healthz():
        if (Path(cfg.model_path) / "model.bin").is_file():
            return {"status": "ok"}
        return JSONResponse(status_code=503, content={"status": "model_missing"})

    @app.get("/v1/status", response_model=StatusResponse)
    def status():
        return StatusResponse(
            models=[ModelStatus(name=slot.name, kind=slot.kind, state=slot.state)],
            compute_type=cfg.compute_type,
            device=cfg.device,
            rss_bytes=rss_bytes(),
        )

    @app.post("/v1/transcribe", response_model=TranscribeResponse)
    def transcribe(
        file: UploadFile = File(...),
        initial_prompt: str | None = Form(None, max_length=MAX_PROMPT_CHARS),
        format: Literal["pcm16"] | None = Query(None),
    ):
        data = file.file.read(cfg.max_upload_bytes + 1)
        if len(data) > cfg.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"audio exceeds {cfg.max_upload_bytes} bytes")
        try:
            samples = pcm16_to_float32(data) if format == "pcm16" else decode(data)
        except AudioDecodeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        if samples.size == 0:  # a valid container with no audio: nothing to transcribe
            return TranscribeResponse(text="", language=None, segments=[], rtf=0.0)
        prompt = initial_prompt or None

        def infer(model: SpeechModel) -> tuple[Transcription, float]:
            start = clock()
            result = model.transcribe(samples, prompt)
            return result, clock() - start

        try:
            result, elapsed = slot.run(infer)
        except ModelUnavailable as exc:
            raise HTTPException(status_code=503, detail="speech model unavailable") from exc
        duration_s = len(samples) / SAMPLE_RATE
        rtf = round(elapsed / duration_s, 4) if duration_s else 0.0
        return TranscribeResponse(
            text=result.text,
            language=result.language,
            segments=[SegmentOut(start_ms=s.start_ms, end_ms=s.end_ms, text=s.text) for s in result.segments],
            rtf=rtf,
        )

    return app


# Building the app loads nothing (the model loads on first use), so importing
# this module stays cheap. uvicorn serves "stt_service.app:app".
app = create_app()
