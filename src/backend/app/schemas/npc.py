from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from app.db.models.npc import NpcRole, NpcStatus

# Matches npcs.name's String(200) column — enforced here so a too-long name
# fails with a clean 422 instead of a raw DB length-constraint error.
_NAME_MAX_LENGTH = 200


class NpcCreate(BaseModel):
    name: str = Field(..., max_length=_NAME_MAX_LENGTH)
    role: NpcRole = NpcRole.npc
    status: NpcStatus = NpcStatus.unknown
    description: str | None = None
    notes: str | None = None
    campaign_id: uuid.UUID


class NpcUpdate(BaseModel):
    name: str | None = Field(None, max_length=_NAME_MAX_LENGTH)
    role: NpcRole | None = None
    status: NpcStatus | None = None
    description: str | None = None
    notes: str | None = None


# GM and Party projections (E0-Access.4), returned only through
# app.access.project. The Party schema has no `notes` (GM notes).

class NpcGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    role: NpcRole
    status: NpcStatus
    description: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NpcPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    role: NpcRole
    status: NpcStatus
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# The pre-E0-Access.4 name is the GM schema.
NpcResponse = NpcGMResponse


class NpcExtractResponse(BaseModel):
    suggestions: list[str]
