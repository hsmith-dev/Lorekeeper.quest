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


class NpcResponse(BaseModel):
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


class NpcExtractResponse(BaseModel):
    suggestions: list[str]
