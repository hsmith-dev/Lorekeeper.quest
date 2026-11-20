import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator
from app.db.models.campaign import Genre
from app.domain.enums import CampaignRole
from app.schemas.journal import JournalPartyListResponse, JournalPartyResponse
from app.schemas.npc import NpcPartyResponse
from app.schemas.quest import QuestPartyResponse
from app.schemas.tag import TagCategoryPartyRef, TagPartyResponse

_VALID_KINDS = {"read_only", "collaborate"}


class ShareTokenCreate(BaseModel):
    """A new Share Link (E0-Access.12). A collaborate link grants `role`
    (default player); a read-only link grants none (a role is 422).
    `expires_at`, when given, must be in the future (a naive time is UTC)."""

    kind: str = "read_only"
    role: Literal["co_gm", "player"] | None = None
    expires_at: datetime | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v

    @model_validator(mode="after")
    def role_for_kind(self) -> "ShareTokenCreate":
        if self.kind == "read_only":
            if self.role is not None:
                raise ValueError("a read_only link grants no role")
        elif self.role is None:
            self.role = "player"
        return self


class ShareTokenResponse(BaseModel):
    id: uuid.UUID
    token: str
    kind: str
    role: CampaignRole | None = None  # serialized as "co_gm" / "player"
    expires_at: datetime | None = None
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

