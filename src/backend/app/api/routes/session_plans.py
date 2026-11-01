import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    CampaignContext, check_create, ctx_for_request, project, project_all, require_campaign, require_campaign_for,
    scoped_get, scoped_select,
)
from app.core.limiter import limiter, user_or_ip
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
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
from app.api.deps import get_current_user, get_user_llm_config
from app.services.chat_service import generate_session_plan
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service

router = APIRouter()

# Session plans are GM prep (E0-Access.5): GMs of the plan's Campaign (Owner
# or Co-GM) write them; a Player reads only plans whose Visibility covers
# them. Every denial, and a hidden plan, is the one 404.
_plan_player = require_campaign_for(SessionPlan, "plan_id", "player")
_plan_gm = require_campaign_for(SessionPlan, "plan_id", "gm")


@router.post("/generate", response_model=SessionPlanGenerateResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def generate_plan_draft(
    request: Request,
    body: SessionPlanGenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> SessionPlanGenerateResponse:
    """Draft a session plan from campaign context — WITHOUT saving anything,
    same pattern as journal narrative drafts: generate, let the GM review and
    edit, then POST / to actually persist it. GM only: the draft is built
    from Shorthand, NPCs and Quests (GM content)."""
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)

    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx).with_only_columns(JournalEntry.shorthand)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(8)
    )
    recent_entries = [{"shorthand": r} for r in entries_result.scalars().all()]

    quests_result = await db.execute(
        scoped_select(Quest, ctx).with_only_columns(Quest.title)
        .where(Quest.status == QuestStatus.active)
        .order_by(Quest.created_at.desc(), Quest.id)
        .limit(10)
    )
    open_quests = list(quests_result.scalars().all())

    npcs_result = await db.execute(
        scoped_select(NpcEntry, ctx).with_only_columns(NpcEntry.name)
        .order_by(NpcEntry.updated_at.desc(), NpcEntry.id)
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
    await llm_config_service.meter(db, user, config, content)
    return SessionPlanGenerateResponse(content=content)


@router.post("/", response_model=SessionPlanResponse, status_code=201)
async def create_session_plan(
    request: Request,
    body: SessionPlanCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    # Field(max_length=200) on the schema already guarantees this fits the
    # title column — .strip() here is just whitespace trimming, not a safety net.
    plan = SessionPlan(user_id=user.id, campaign_id=body.campaign_id, title=body.title.strip(), content=body.content)
    check_create(plan, ctx)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return project(plan, ctx)


@router.get("/", response_model=list[SessionPlanResponse])
async def list_session_plans(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        scoped_select(SessionPlan, ctx).order_by(SessionPlan.created_at.desc(), SessionPlan.id)
    )
    return await project_all(db, result.scalars().all(), ctx)


@router.get("/{plan_id}", response_model=SessionPlanResponse)
async def get_session_plan(
    plan_id: uuid.UUID,
    ctx: CampaignContext = Depends(_plan_player),
    db: AsyncSession = Depends(get_db),
):
    return project(await scoped_get(db, SessionPlan, ctx, plan_id), ctx)


@router.put("/{plan_id}", response_model=SessionPlanResponse)
async def update_session_plan(
    plan_id: uuid.UUID,
    body: SessionPlanUpdate,
    ctx: CampaignContext = Depends(_plan_gm),
    db: AsyncSession = Depends(get_db),
):
    plan = await scoped_get(db, SessionPlan, ctx, plan_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(plan, field, value)
    await db.commit()
    await db.refresh(plan)
    return project(plan, ctx)


@router.delete("/{plan_id}", status_code=204)
async def delete_session_plan(
    plan_id: uuid.UUID,
    ctx: CampaignContext = Depends(_plan_gm),
    db: AsyncSession = Depends(get_db),
) -> None:
    plan = await scoped_get(db, SessionPlan, ctx, plan_id)
    await db.delete(plan)
    await db.commit()
