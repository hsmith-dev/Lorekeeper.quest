import asyncio
import io
import logging
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_model = None
_executor = ThreadPoolExecutor(max_workers=1)


def _load_model():
    global _model
    if _model is not None:
        return
    import whisper
    logger.info("Loading Whisper 'base' model...")
    _model = whisper.load_model("base")
    logger.info("Whisper loaded.")


def _transcribe(audio_bytes: bytes, ext: str) -> str:
    _load_model()
    import whisper
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = whisper.transcribe(_model, tmp_path, fp16=False)
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)


async def transcribe_audio(audio_bytes: bytes, ext: str = ".webm") -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _transcribe, audio_bytes, ext)
