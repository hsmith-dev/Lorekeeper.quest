import uuid
from datetime import datetime
from pydantic import BaseModel


class TagCategoryCreate(BaseModel):
    name: str


class TagCategoryResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
