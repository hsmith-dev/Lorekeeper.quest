import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.access import role_map
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.source import SourceDocument
from app.db.models.feedback import Feedback
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackResponse,
    FeedbackAdminResponse,
    FeedbackContextResponse,
)
from app.api.deps import get_current_user, require_admin

router = APIRouter()


@router.post("/", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    # Feedback stays submittable whatever campaign_id says, but the pointer
    # (which lets the admin inbox pull that Campaign's content) is kept only
    # for a Campaign the submitter can reach now (Owner or any Member, via
    # the access layer). A Campaign they cannot reach is dropped exactly like
    # one that does not exist (EV-4, E0-QA.13): before this, a hidden id
    # answered 201 while a missing one failed the foreign key (a 500), so the
    # endpoint told anyone which Campaign ids exist. The check reads the
    # caller's whole Role map (the same two queries whatever id was sent),
    # so neither the answer nor its timing depends on whether a Campaign the
    # caller cannot reach exists.
    user_id = user.id
    reachable = await role_map(db, user)
    campaign_id = body.campaign_id if body.campaign_id in reachable else None

    def row(cid):
        return Feedback(user_id=user_id, campaign_id=cid, category=body.category, message=body.message.strip())

    feedback = row(campaign_id)
    db.add(feedback)
    try:
        await db.commit()
    except IntegrityError:
        if campaign_id is None:
            raise
        # The Campaign was deleted between the check and the insert: keep
        # the feedback, without the pointer (the FK is SET NULL on delete
        # anyway).
        await db.rollback()
        feedback = row(None)
        db.add(feedback)
        await db.commit()
    await db.refresh(feedback)
    return feedback


@router.get("/", response_model=list[FeedbackAdminResponse])
async def list_feedback(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[FeedbackAdminResponse]:
    result = await db.execute(
        select(Feedback, User.email, User.display_name, Campaign.name)
        .join(User, Feedback.user_id == User.id)
        .outerjoin(Campaign, Feedback.campaign_id == Campaign.id)
        .order_by(Feedback.created_at.desc())
    )
    return [
        FeedbackAdminResponse(
            id=fb.id,
            category=fb.category,
            message=fb.message,
            campaign_id=fb.campaign_id,
            created_at=fb.created_at,
            user_email=email,
            user_display_name=display_name,
            campaign_name=campaign_name,
        )
        for fb, email, display_name, campaign_name in result.all()
    ]


@router.get("/{feedback_id}/context", response_model=FeedbackContextResponse)
async def get_feedback_context(
    feedback_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FeedbackContextResponse:
    feedback = await db.get(Feedback, feedback_id)
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if not feedback.campaign_id:
        raise HTTPException(status_code=404, detail="This feedback isn't linked to a campaign")

    campaign = await db.get(Campaign, feedback.campaign_id)
    if not campaign:
        # Campaign was deleted after the feedback was submitted — campaign_id
        # is SET NULL on delete, but a request racing that exact moment (or a
        # stale client) could still land here.
        raise HTTPException(status_code=404, detail="The linked campaign no longer exists")

    entries_result = await db.execute(
        select(JournalEntry.narrative)
        .where(JournalEntry.campaign_id == campaign.id)
        .order_by(JournalEntry.created_at.desc())
        .limit(10)
    )
    npcs_result = await db.execute(
        select(NpcEntry.name).where(NpcEntry.campaign_id == campaign.id).order_by(NpcEntry.updated_at.desc()).limit(20)
    )
    quests_result = await db.execute(
        select(Quest.title).where(Quest.campaign_id == campaign.id).order_by(Quest.created_at.desc()).limit(20)
    )
    sources_result = await db.execute(
        select(SourceDocument.title).where(SourceDocument.campaign_id == campaign.id).limit(20)
    )

    return FeedbackContextResponse(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_genre=campaign.genre.value,
        campaign_description=campaign.description,
        recent_journal_narratives=list(entries_result.scalars().all()),
        npc_names=list(npcs_result.scalars().all()),
        quest_titles=list(quests_result.scalars().all()),
        source_document_titles=list(sources_result.scalars().all()),
    )
