import uuid
from datetime import datetime
from pydantic import BaseModel


class TagCategoryCreate(BaseModel):
    name: str


class TagCategoryGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TagCategoryPartyResponse(TagCategoryGMResponse):
    """A category a non-GM may see (its Visibility covers them). No GM-only
    fields today, so the same keys as the GM schema (access.project)."""


TagCategoryResponse = TagCategoryGMResponse
