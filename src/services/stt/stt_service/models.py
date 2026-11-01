"""Speech model interface, the real faster-whisper model, the audio decoders,
and the lazily loaded slot the app serves.

faster_whisper / ctranslate2 are imported only inside FasterWhisperModel, never
at module import time. PyAV (`av`) is never installed or imported: container
audio is decoded by the `ffmpeg` CLI in a subprocess (decode_container).
"""

from __future__ import annotations

import gc
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

from stt_service.config import SAMPLE_RATE, Config

FFMPEG_BIN = os.environ.get("STT_FFMPEG_BIN") or "ffmpeg"
# A 25 MB upload decodes in seconds; this only stops a pathological file from
# holding a request thread forever.
DECODE_TIMEOUT_S = float(os.environ.get("STT_DECODE_TIMEOUT_S") or 120)


class AudioDecodeError(ValueError):
    """The upload is not audio we can decode (the app answers 422)."""


class ModelUnavailable(RuntimeError):
    """The speech model could not be loaded (the app answers 503)."""


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None
    segments: list[Segment] = field(default_factory=list)


class SpeechModel(Protocol):
    def transcribe(self, audio: np.ndarray, initial_prompt: str | None) -> Transcription:
        """audio: mono float32 at SAMPLE_RATE, in [-1, 1]."""


class Decoder(Protocol):
    def __call__(self, data: bytes) -> np.ndarray:
        """Container bytes (webm/ogg/wav/mp3/mp4) -> mono float32 at SAMPLE_RATE."""


class FasterWhisperModel:
    """faster-whisper (CTranslate2) from the directory baked at image build."""

    def __init__(self, cfg: Config):
        from stt_service.whisper_loader import whisper_model_class

        WhisperModel = whisper_model_class()  # faster_whisper without PyAV
        # A directory path is used as is: no hub lookup, no download.
        self._model = WhisperModel(
            cfg.model_path,
            device=cfg.device,
            compute_type=cfg.compute_type,
            cpu_threads=cfg.cpu_threads,
        )
        self._language = cfg.language
        self._beam_size = cfg.beam_size

    def transcribe(self, audio: np.ndarray, initial_prompt: str | None) -> Transcription:
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=self._beam_size,
            initial_prompt=initial_prompt,
            vad_filter=False,
        )
        raw = list(segments)  # a generator: decoding happens while it is consumed
        return Transcription(
            # Same as openai-whisper's result["text"].strip().
            text="".join(s.text for s in raw).strip(),
            language=getattr(info, "language", None),
            segments=[Segment(round(s.start * 1000), round(s.end * 1000), s.text.strip()) for s in raw],
        )


def ffmpeg_decode_command(src: str, ffmpeg: str = FFMPEG_BIN) -> list[str]:
    """argv for: any container/codec -> raw float32 little-endian, 16 kHz mono, on stdout."""
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "0",
        "-i", src,
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]


def decode_container(data: bytes, *, run=subprocess.run, ffmpeg: str = FFMPEG_BIN,
                     timeout_s: float = DECODE_TIMEOUT_S) -> np.ndarray:
    """Container bytes (webm/ogg/wav/mp3/mp4...) -> 16 kHz mono float32.

    Decoding runs in the `ffmpeg` CLI, a separate process, never in-process:
    the FFmpeg libraries (GPL-linked in Debian, as in PyAV's wheels) are never
    loaded into this Python process (licences: mere aggregation). The upload
    goes through a temp file, not stdin, because MP4/M4A needs a seekable input
    (the moov atom is often at the end).
    """
    if not data:
        raise AudioDecodeError("empty audio")
    with tempfile.NamedTemporaryFile(prefix="stt-", suffix=".bin") as f:
        f.write(data)
        f.flush()
        try:
            proc = run(ffmpeg_decode_command(f.name, ffmpeg), capture_output=True, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            raise AudioDecodeError(f"decoding took longer than {timeout_s:g}s") from exc
        except OSError as exc:  # ffmpeg missing: a broken image, not a bad upload
            raise RuntimeError(f"cannot run {ffmpeg}: {exc}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise AudioDecodeError("could not decode audio" + (f": {err[-1][:200]}" if err else ""))
    out = proc.stdout or b""
    usable = len(out) - len(out) % 4
    return np.frombuffer(out[:usable], dtype="<f4").astype(np.float32, copy=True)


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """Raw little-endian signed 16-bit mono at 16 kHz -> float32 in [-1, 1)."""
    if not data:
        raise AudioDecodeError("empty audio")
    if len(data) % 2:
        raise AudioDecodeError("pcm16 audio must be an even number of bytes")
    return np.frombuffer(data, "<i2").astype(np.float32) / 32768


class LazyModelSlot:
    """The served model: loaded on first use, dropped again when idle.

    The lock serialises loading, inference and unloading, so two requests
    never run the same CTranslate2 model at once and the idle unloader never
    drops a model mid-request. After a failed load the next run() tries again.
    """

    def __init__(self, name: str, kind: str, loader: Callable[[], SpeechModel],
                 clock: Callable[[], float] = time.monotonic):
        self.name = name
        self._clock = clock
        self.kind = kind
        self._loader = loader
        self._model: SpeechModel | None = None
        self.state = "not_loaded"  # not_loaded | loading | loaded | failed
        self.error: str | None = None
        self.last_used: float | None = None
        self.lock = threading.Lock()

    def _ensure_loaded(self) -> SpeechModel:
        # Caller holds self.lock.
        if self._model is None:
            self.state = "loading"
            try:
                self._model = self._loader()
            except Exception as exc:
                self.state = "failed"
                self.error = f"{type(exc).__name__}: {exc}"
                raise ModelUnavailable(self.error) from exc
            self.state = "loaded"
            self.error = None
        return self._model

    def run(self, fn: Callable[[SpeechModel], object]) -> object:
        with self.lock:
            model = self._ensure_loaded()
            self.last_used = self._clock()
            try:
                return fn(model)
            finally:
                # Stamped again on the way out, so a long inference (or a long
                # wait for the lock) never counts as idle time.
                self.last_used = self._clock()

    def unload_if_idle(self, now: float, idle_s: float) -> bool:
        """Drop the model if unused for idle_s seconds. Never waits on a
        request in flight: if the lock is held, the model is in use."""
        if idle_s <= 0 or not self.lock.acquire(blocking=False):
            return False
        try:
            if self._model is None or self.last_used is None or now - self.last_used < idle_s:
                return False
            self._model = None
            self.state = "not_loaded"
        finally:
            self.lock.release()
        gc.collect()  # CTranslate2 frees its buffers when the Python object goes
        return True
