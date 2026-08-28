from pydantic import BaseModel, field_validator
import uuid
from datetime import datetime, date
from app.schemas.tag import TagResponse


class GenerateRequest(BaseModel):
    notes: str
    campaign_id: uuid.UUID
    session_date: date | None = None
    entry_hash: str
    # If set — the normal interactive path now — this is the (possibly
    # user-edited) narrative from a prior POST /generate-draft call, and
    # gets saved as-is with no further LLM call. If omitted, the narrative is
    # generated here in one step (kept for callers that skip the preview,
    # e.g. the offline sync queue).
    narrative: str | None = None

    @field_validator("narrative")
    @classmethod
    def blank_narrative_means_not_supplied(cls, v: str | None) -> str | None:
        """A blank/whitespace-only narrative is treated the same as omitting
        the field entirely — falls through to server-side generation in the
        route — rather than being saved as a blank journal entry. The
        frontend's Save button already disables on empty text, but the API
        itself shouldn't rely on that; this is the same rule enforced
        server-side too."""
        return v if v and v.strip() else None


class GenerateDraftRequest(BaseModel):
    notes: str
    campaign_id: uuid.UUID


class GenerateDraftResponse(BaseModel):
    narrative: str


class JournalResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    shorthand: str
    narrative: str
    session_date: date | None
    tags: list[TagResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class JournalListResponse(BaseModel):
    items: list[JournalResponse]
    total: int
    page: int
    limit: int


class JournalLiteResponse(BaseModel):
    id: uuid.UUID
    shorthand: str
    session_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AutocompleteRequest(BaseModel):
    text: str
    campaign_id: uuid.UUID | None = None


class AutocompleteResponse(BaseModel):
    suggestion: str


class RecapRequest(BaseModel):
    campaign_id: uuid.UUID


class RecapResponse(BaseModel):
    recap: str


class SessionSummaryRequest(BaseModel):
    campaign_id: uuid.UUID
    transcript: str


class SessionSummaryResponse(BaseModel):
    suggested_notes: str
