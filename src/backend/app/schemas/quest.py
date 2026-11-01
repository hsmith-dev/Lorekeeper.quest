from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from app.db.models.quest import QuestStatus

# Matches quests.title's String(300) column — enforced here so a too-long
# title fails with a clean 422 instead of a raw DB length-constraint error.
_TITLE_MAX_LENGTH = 300


class QuestCreate(BaseModel):
    title: str = Field(..., max_length=_TITLE_MAX_LENGTH)
    description: str | None = None
    notes: str | None = None
    status: QuestStatus = QuestStatus.active
    campaign_id: uuid.UUID


class QuestUpdate(BaseModel):
    title: str | None = Field(None, max_length=_TITLE_MAX_LENGTH)
    description: str | None = None
    notes: str | None = None
    status: QuestStatus | None = None


# GM and Party projections (E0-Access.4), returned only through
# app.access.project. The Party schema has no `notes` (GM notes).

class QuestGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    description: str | None
    notes: str | None
    status: QuestStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    description: str | None
    status: QuestStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# The pre-E0-Access.4 name is the GM schema.
QuestResponse = QuestGMResponse


class QuestSuggestResponse(BaseModel):
    suggestions: list[str]
