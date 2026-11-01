import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.db.models.campaign import Genre
from app.schemas.journal import JournalPartyListResponse, JournalPartyResponse
from app.schemas.npc import NpcPartyResponse
from app.schemas.quest import QuestPartyResponse
from app.schemas.tag import TagCategoryPartyRef, TagPartyResponse

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
    """The anon (Share Link) projection of a Campaign (E0-Access.4)."""

    id: uuid.UUID
    name: str
    genre: Genre
    description: str | None
    share_kind: str

    model_config = {"from_attributes": True}


# --- Public (read-only share link) response schemas -------------------------
# Anonymous share-link viewers are players/audience, not the GM. Since
# E0-Access.4 these are the Party projections (app/schemas/<domain>.py,
# returned through app.access.project for an anon ctx); the E0a names stay as
# aliases so share output keys are unchanged. The Party schemas are
# allow-lists: a field reaches a share viewer only if it is named there, so a
# column added to a model later stays private by default. GM-private data
# deliberately left out:
#   - JournalEntry.shorthand: the GM's raw session notes the narrative is
#     generated from (asides, spoilers); `narrative` is the player-facing
#     chronicle.
#   - NpcEntry.notes / Quest.notes: free-text GM notes (secrets, motives,
#     planned twists). NPCs and Quests are always_gm until F3-world anyway
#     (Decision B1-D4), so the share lists are empty.
#   - Session plans, source documents, character sheets and the shorthand
#     glossary: no share endpoint exposes them at all.

PublicTagCategoryRef = TagCategoryPartyRef
PublicTagResponse = TagPartyResponse
PublicJournalResponse = JournalPartyResponse
PublicJournalListResponse = JournalPartyListResponse
PublicNpcResponse = NpcPartyResponse
PublicQuestResponse = QuestPartyResponse


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
