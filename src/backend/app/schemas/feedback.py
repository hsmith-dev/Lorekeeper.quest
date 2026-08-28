from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from app.db.models.feedback import FeedbackCategory

# Generous but bounded — feedback is free text, not a novel; guards against
# the same silent-500-on-oversized-input class of bug fixed elsewhere in
# this app (journal narratives, session plan titles, etc.).
_MESSAGE_MAX_LENGTH = 5000


class FeedbackCreate(BaseModel):
    category: FeedbackCategory = FeedbackCategory.other
    message: str = Field(..., min_length=1, max_length=_MESSAGE_MAX_LENGTH)
    # Optional — lets the submitter point at which campaign this is about,
    # so an admin reviewing it can pull that campaign's actual content (see
    # GET /api/feedback/{id}/context) instead of guessing from the message
    # text alone. Ownership isn't checked against the submitter — a
    # collaborator on someone else's shared campaign can still reference it.
    campaign_id: uuid.UUID | None = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    category: FeedbackCategory
    message: str
    campaign_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackAdminResponse(FeedbackResponse):
    """Same as FeedbackResponse but with who-submitted-it and
    what-campaign-it's-about denormalized in, since the admin inbox list
    (GET /api/feedback) needs to show those without a second round-trip per
    row."""

    user_email: str
    user_display_name: str
    campaign_name: str | None


class FeedbackContextResponse(BaseModel):
    """The 'resources' half of a feedback item — the linked campaign's
    actual content, gathered in one call so an admin can research a
    model-quality complaint without manually hopping through campaign/
    journal/NPC/quest/source pages. None of these are exhaustive dumps —
    each is capped, matching how session_plan_service gathers context for
    AI generation, since this is for a human to skim, not a full export
    (campaigns.py's PDF/Markdown export already covers that case)."""

    campaign_id: uuid.UUID
    campaign_name: str
    campaign_genre: str
    campaign_description: str | None
    recent_journal_narratives: list[str]
    npc_names: list[str]
    quest_titles: list[str]
    source_document_titles: list[str]
