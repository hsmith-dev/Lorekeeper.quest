from pydantic import BaseModel, Field
import uuid
from datetime import datetime

# Matches session_plans.title's String(200) column — enforced here so a
# too-long title fails with a clean 422 instead of a raw DB length-constraint
# error (which happened on update but not create: create silently truncated
# via .strip()[:200] in the route, update didn't guard at all).
_TITLE_MAX_LENGTH = 200


class SessionPlanGenerateRequest(BaseModel):
    campaign_id: uuid.UUID
    focus: str | None = None


class SessionPlanGenerateResponse(BaseModel):
    content: str


class SessionPlanCreate(BaseModel):
    campaign_id: uuid.UUID
    title: str = Field(..., max_length=_TITLE_MAX_LENGTH)
    content: str


class SessionPlanUpdate(BaseModel):
    title: str | None = Field(None, max_length=_TITLE_MAX_LENGTH)
    content: str | None = None


class SessionPlanResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
