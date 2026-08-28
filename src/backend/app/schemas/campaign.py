from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from app.db.models.campaign import Genre

# Matches campaigns.name's String(200) column — enforced here so a too-long
# name fails with a clean 422 instead of a raw DB length-constraint error.
_NAME_MAX_LENGTH = 200


class CampaignCreate(BaseModel):
    name: str = Field(..., max_length=_NAME_MAX_LENGTH)
    genre: Genre = Genre.fantasy
    description: str | None = None


class CampaignConceptRequest(BaseModel):
    genre: Genre = Genre.fantasy
    prompt: str | None = None


class CampaignConceptResponse(BaseModel):
    name: str
    description: str


class CampaignUpdate(BaseModel):
    name: str | None = Field(None, max_length=_NAME_MAX_LENGTH)
    genre: Genre | None = None
    description: str | None = None


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    genre: Genre
    description: str | None
    created_at: datetime
    # True for the owner; False for a collaborator who joined via a 'collaborate'
    # share link. Not populated from the ORM object (Campaign has no such column) —
    # defaults to True for every existing owner-only call site, and list_campaigns
    # is the only place that sets it explicitly per-campaign.
    is_owner: bool = True
    # Only set for is_owner=False rows (see list_campaigns) — lets the UI show
    # "Shared by <name>" so two campaigns with the same name (yours and one
    # someone shared with you) are still distinguishable at a glance.
    owner_display_name: str | None = None

    model_config = {"from_attributes": True}


class WeeklyCount(BaseModel):
    week_start: str
    count: int


class TagCount(BaseModel):
    name: str
    count: int


class CampaignAnalytics(BaseModel):
    total_entries: int
    avg_entry_length: float
    entries_per_week: list[WeeklyCount]
    top_characters: list[TagCount]
    top_quests: list[TagCount]
