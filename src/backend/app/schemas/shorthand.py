from pydantic import BaseModel, Field
import uuid
from datetime import datetime

# Matches shorthand_terms.term's String(50) column.
_TERM_MAX_LENGTH = 50


class ShorthandCreate(BaseModel):
    campaign_id: uuid.UUID
    term: str = Field(..., min_length=1, max_length=_TERM_MAX_LENGTH)
    meaning: str = Field(..., min_length=1)
    usage: str | None = None


class ShorthandUpdate(BaseModel):
    term: str | None = Field(None, max_length=_TERM_MAX_LENGTH)
    meaning: str | None = None
    usage: str | None = None


class ShorthandGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    term: str
    meaning: str
    usage: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ShorthandPartyResponse(ShorthandGMResponse):
    """A term a non-GM may see (its Visibility covers them). No GM-only
    fields today, so the same keys as the GM schema (access.project)."""


ShorthandResponse = ShorthandGMResponse
