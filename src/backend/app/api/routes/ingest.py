import logging
import re
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.clients.errors import ModelServiceError, ModelServiceUnavailable
from app.core.limiter import limiter, user_or_ip
from app.db.models.user import User
from app.services.vision_service import extract_notes_from_image
from app.services.transcription_service import transcribe

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mp4", "audio/mpeg", "audio/x-m4a"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
_MAX_AUDIO_BYTES = 25 * 1024 * 1024   # 25 MB
_UNTRANSCRIBABLE = "Could not transcribe audio. Try speaking more clearly."

# Discord timestamp/header patterns to strip
_DISCORD_HEADER = re.compile(
    r"^.{2,40}\s*[—\-]\s*(Today|Yesterday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+\d{1,2}:\d{2}\s*(AM|PM)?\s*$",
    re.IGNORECASE,
)
_DISCORD_BOT_LINE = re.compile(r"^\[.*\]$")
_DISCORD_REACTION = re.compile(r"^:\w+:\s*\d*$")


class IngestImageResponse(BaseModel):
    extracted_text: str


class IngestVoiceResponse(BaseModel):
    transcribed_text: str


class DiscordIngestRequest(BaseModel):
    text: str


class DiscordIngestResponse(BaseModel):
    cleaned_text: str


@router.post("/image", response_model=IngestImageResponse)
@limiter.limit("10/minute", key_func=user_or_ip)
async def ingest_image(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> IngestImageResponse:
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Upload a JPEG, PNG, WebP, or GIF.",
        )
    contents = await file.read()
    if len(contents) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit.")
    try:
        text = await extract_notes_from_image(contents, file.filename or "image")
    except ModelServiceUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Text recognition is unavailable right now. Try again in a minute.",
        )
    except ModelServiceError as exc:
        if exc.status_code == 413:
            raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit.")
        text = ""  # 422: empty or undecodable image, same answer as no text
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from this image. Try a clearer photo.",
        )
    return IngestImageResponse(extracted_text=text)


@router.post("/voice", response_model=IngestVoiceResponse)
@limiter.limit("10/minute", key_func=user_or_ip)
async def ingest_voice(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> IngestVoiceResponse:
    content_type = (file.content_type or "").lower()
    if not any(t in content_type for t in ("audio", "webm", "ogg", "wav", "mp4", "mpeg")):
        raise HTTPException(status_code=415, detail="Unsupported audio type.")
    contents = await file.read()
    if len(contents) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio exceeds 25 MB limit.")
    if not contents:
        raise HTTPException(status_code=422, detail=_UNTRANSCRIBABLE)
    # The stt sidecar sniffs the container itself, so no extension is passed.
    try:
        text = await transcribe(contents)
    except ModelServiceError as exc:
        # Never log the audio or the sidecar's echo of it: type and status only.
        logger.warning("Voice transcription failed for user %s: %s (status %s)",
                       user.id, type(exc).__name__, exc.status_code)
        rejected = (not isinstance(exc, ModelServiceUnavailable)
                    and exc.status_code is not None and 400 <= exc.status_code < 500)
        if rejected:  # the sidecar could not read this audio
            raise HTTPException(status_code=422, detail=_UNTRANSCRIBABLE) from exc
        raise HTTPException(status_code=503, detail="Speech model unavailable") from exc
    if not text:
        raise HTTPException(status_code=422, detail=_UNTRANSCRIBABLE)
    return IngestVoiceResponse(transcribed_text=text)


@router.post("/discord", response_model=DiscordIngestResponse)
async def ingest_discord(
    body: DiscordIngestRequest,
    user: User = Depends(get_current_user),
) -> DiscordIngestResponse:
    """Strip Discord message headers and return cleaned session notes."""
    lines = body.text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _DISCORD_HEADER.match(stripped):
            continue
        if _DISCORD_BOT_LINE.match(stripped):
            continue
        if _DISCORD_REACTION.match(stripped):
            continue
        kept.append(stripped)
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="No usable text found. Paste raw Discord chat export.")
    return DiscordIngestResponse(cleaned_text=cleaned)
