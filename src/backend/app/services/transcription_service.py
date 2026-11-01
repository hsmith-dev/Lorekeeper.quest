"""Speech-to-text, served by the `stt` sidecar (src/services/stt).

A thin async wrapper over app/clients/stt.py: no model, thread pool or temp
file lives in the backend any more (E0-Platform.5). Errors are the client's
ModelServiceError / ModelServiceUnavailable; callers map them.
"""

from __future__ import annotations

from typing import Literal

from app.clients import stt


async def transcribe(audio: bytes, *, initial_prompt: str | None = None,
                     format: Literal["pcm16"] | None = None) -> str:
    """The transcript text, stripped ("" for silence)."""
    result = await stt.transcribe(audio, initial_prompt=initial_prompt, format=format)
    return result.text.strip()
