import uuid
from datetime import date, datetime
from pydantic import BaseModel, field_validator
from app.db.models.campaign import Genre
from app.db.models.npc import NpcRole, NpcStatus
from app.db.models.quest import QuestStatus
from app.schemas.tag import TagResponse

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


# --- Public (read-only share link) response schemas -------------------------
# Anonymous share-link viewers are players/audience, not the GM. These are
# allow-lists: a field reaches a share viewer only if it is named here, so a
# column added to a model later stays private by default. GM-private data
# deliberately left out:
#   - JournalEntry.shorthand: the GM's raw session notes the narrative is
#     generated from (asides, spoilers); `narrative` is the player-facing
#     chronicle.
#   - NpcEntry.notes / Quest.notes: free-text GM notes (secrets, motives,
#     planned twists), as opposed to the player-facing `description`.
#   - Session plans, source documents, character sheets and the shorthand
#     glossary: no share endpoint exposes them at all.
# The full roles/visibility model belongs to the player-portal feature; this
# only stops the existing share link leaking GM prep.


class PublicJournalResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    narrative: str
    session_date: date | None
    tags: list[TagResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class PublicJournalListResponse(BaseModel):
    items: list[PublicJournalResponse]
    total: int
    page: int
    limit: int


class PublicNpcResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    role: NpcRole
    status: NpcStatus
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublicQuestResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    description: str | None
    status: QuestStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
