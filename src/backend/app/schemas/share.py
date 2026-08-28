import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.db.models.campaign import Genre

_VALID_KINDS = {"read_only", "collaborate"}


class ShareTokenCreate(BaseModel):
    kind: str = "read_only"

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
        return v


class ShareTokenResponse(BaseModel):
    id: uuid.UUID
    token: str
    kind: str
    revoked: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicCampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    genre: Genre
    description: str | None
    share_kind: str


class JoinCampaignResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    already_member: bool


class CampaignMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}
