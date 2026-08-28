import re
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.limiter import limiter
from app.db.models.user import User
from app.services.vision_service import extract_notes_from_image
from app.services.transcription_service import transcribe_audio

router = APIRouter()

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mp4", "audio/mpeg", "audio/x-m4a"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
_MAX_AUDIO_BYTES = 25 * 1024 * 1024   # 25 MB

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
@limiter.limit("10/minute")
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
    text = await extract_notes_from_image(contents)
    if not text:
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from this image. Try a clearer photo.",
        )
    return IngestImageResponse(extracted_text=text)


@router.post("/voice", response_model=IngestVoiceResponse)
@limiter.limit("10/minute")
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
    # Determine file extension from content type
    ext_map = {"ogg": ".ogg", "wav": ".wav", "mp4": ".mp4", "mpeg": ".mp3", "m4a": ".m4a"}
    ext = next((v for k, v in ext_map.items() if k in content_type), ".webm")
    text = await transcribe_audio(contents, ext)
    if not text:
        raise HTTPException(status_code=422, detail="Could not transcribe audio. Try speaking more clearly.")
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
