import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.journal import JournalEntry
from app.db.models.quest import Quest, QuestStatus
from app.db.models.npc import NpcEntry
from app.db.models.session_plan import SessionPlan
from app.schemas.session_plan import (
    SessionPlanGenerateRequest,
    SessionPlanGenerateResponse,
    SessionPlanCreate,
    SessionPlanUpdate,
    SessionPlanResponse,
)
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.chat_service import generate_session_plan
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service

router = APIRouter()


async def _get_accessible_plan(db: AsyncSession, plan_id: uuid.UUID, user: User) -> SessionPlan:
    plan = await db.get(SessionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Session plan not found")
    await get_campaign_with_access(db, plan.campaign_id, user)
    return plan


@router.post("/generate", response_model=SessionPlanGenerateResponse)
async def generate_plan_draft(
    body: SessionPlanGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> SessionPlanGenerateResponse:
    """Draft a session plan from campaign context — WITHOUT saving anything,
    same pattern as journal narrative drafts: generate, let the GM review and
    edit, then POST / to actually persist it."""
    campaign = await get_campaign_with_access(db, body.campaign_id, user)

    entries_result = await db.execute(
        select(JournalEntry.shorthand)
        .where(JournalEntry.campaign_id == body.campaign_id)
        .order_by(JournalEntry.created_at.desc())
        .limit(8)
    )
    recent_entries = [{"shorthand": r} for r in entries_result.scalars().all()]

    quests_result = await db.execute(
        select(Quest.title)
        .where(Quest.campaign_id == body.campaign_id, Quest.status == QuestStatus.active)
        .order_by(Quest.created_at.desc())
        .limit(10)
    )
    open_quests = list(quests_result.scalars().all())

    npcs_result = await db.execute(
        select(NpcEntry.name)
        .where(NpcEntry.campaign_id == body.campaign_id)
        .order_by(NpcEntry.updated_at.desc())
        .limit(15)
    )
    npcs = list(npcs_result.scalars().all())

    content = await generate_session_plan(
        campaign_name=campaign.name,
        genre=campaign.genre.value,
        recent_entries=recent_entries,
        open_quests=open_quests,
        npcs=npcs,
        focus=body.focus,
        config=config,
    )
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, content)
    return SessionPlanGenerateResponse(content=content)


@router.post("/", response_model=SessionPlanResponse, status_code=201)
async def create_session_plan(
    body: SessionPlanCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionPlanResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    # Field(max_length=200) on the schema already guarantees this fits the
    # title column — .strip() here is just whitespace trimming, not a safety net.
    plan = SessionPlan(user_id=user.id, campaign_id=body.campaign_id, title=body.title.strip(), content=body.content)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/", response_model=list[SessionPlanResponse])
async def list_session_plans(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionPlanResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(SessionPlan).where(SessionPlan.campaign_id == campaign_id).order_by(SessionPlan.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{plan_id}", response_model=SessionPlanResponse)
async def get_session_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionPlanResponse:
    return await _get_accessible_plan(db, plan_id, user)


@router.put("/{plan_id}", response_model=SessionPlanResponse)
async def update_session_plan(
    plan_id: uuid.UUID,
    body: SessionPlanUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionPlanResponse:
    plan = await _get_accessible_plan(db, plan_id, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=204)
async def delete_session_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    plan = await _get_accessible_plan(db, plan_id, user)
    await db.delete(plan)
    await db.commit()
