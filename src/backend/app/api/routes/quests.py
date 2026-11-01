import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app.access import (
    GM, LITE,
    CampaignContext, check_create, ctx_for_request, project, project_all, require_campaign, require_campaign_for,
    scoped_get, scoped_select,
)
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.quest import Quest
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag
from app.schemas.quest import QuestCreate, QuestUpdate, QuestGMResponse, QuestSuggestResponse
from app.schemas.journal import JournalLiteResponse
from app.api.deps import get_current_user, get_user_llm_config
from app.services.chat_service import suggest_quests, generate_quest_description
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service

router = APIRouter()

# Quests are always_gm until F3-world (Decision B1-D4): a Player (or a GM in
# member preview) lists none and gets the one 404 for every item route and
# for a create. Bodies go through access.project (response_model=None:
# FastAPI must not coerce a Party body into the GM schema).
_GM_OR_PARTY = "GM: QuestGMResponse; Player or member preview: QuestPartyResponse (no `notes`)."
_quest_ctx = require_campaign_for(Quest, "quest_id")


async def _get_accessible_quest(db: AsyncSession, quest_id: uuid.UUID, ctx: CampaignContext) -> Quest:
    """The quest `quest_id` if ctx (the caller's ctx in the quest's own
    Campaign, from `require_campaign_for`) may see it; else the one
    `not_found()` (hidden and missing are the same)."""
    return await scoped_get(db, Quest, ctx, quest_id)


async def _visible_quest(quest_id: uuid.UUID, ctx: CampaignContext = Depends(_quest_ctx),
                         db: AsyncSession = Depends(get_db)) -> Quest:
    """As a dependency, so a hidden quest is the 404 before any later
    dependency (the LLM config's 402) can answer differently."""
    return await _get_accessible_quest(db, quest_id, ctx)


@router.get("/", response_model=None,
            responses={200: {"model": list[QuestGMResponse], "description": _GM_OR_PARTY}})
async def list_quests(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        scoped_select(Quest, ctx).order_by(Quest.status, Quest.created_at.desc())
    )
    return await project_all(db, result.scalars().all(), ctx)


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def create_quest(
    request: Request,
    body: QuestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    quest = Quest(user_id=user.id, **body.model_dump())
    check_create(quest, ctx)  # a row the caller could not see is refused before writing
    db.add(quest)
    await db.commit()
    await db.refresh(quest)
    return project(quest, ctx)


@router.put("/{quest_id}", response_model=None,
            responses={200: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def update_quest(
    quest_id: uuid.UUID,
    body: QuestUpdate,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
):
    quest = await _get_accessible_quest(db, quest_id, ctx)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(quest, field, value)
    await db.commit()
    await db.refresh(quest)
    # The write response is projected like a read (AR-26).
    return project(quest, ctx)


@router.delete("/{quest_id}", status_code=204)
async def delete_quest(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
) -> None:
    quest = await _get_accessible_quest(db, quest_id, ctx)
    await db.delete(quest)
    await db.commit()


@router.get("/{quest_id}", response_model=None,
            responses={200: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def get_quest(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
):
    return project(await _get_accessible_quest(db, quest_id, ctx), ctx)


@router.get("/{quest_id}/entries", response_model=None,
            responses={200: {"model": list[JournalLiteResponse], "description": _GM_OR_PARTY}})
async def get_quest_entries(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Entries mentioning this Quest by title, among the entries visible to
    ctx. A GM matches the Shorthand or the Narrative and gets lite GM rows;
    anyone else matches the Narrative only and gets Party entries, so a
    Shorthand-only mention never shows up or reorders their list (E0-Access.7)."""
    quest = await _get_accessible_quest(db, quest_id, ctx)
    needle = f"%{quest.title}%"
    match = (or_(JournalEntry.shorthand.ilike(needle), JournalEntry.narrative.ilike(needle))
             if ctx.role == GM else JournalEntry.narrative.ilike(needle))
    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(match)
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(20)
    )
    return await project_all(db, entries_result.scalars().all(), ctx, variant=LITE)


@router.post("/{quest_id}/generate")
async def generate_quest_description_route(
    quest_id: uuid.UUID,
    quest: Quest = Depends(_visible_quest),
    ctx: CampaignContext = Depends(_quest_ctx),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(
            or_(
                JournalEntry.shorthand.ilike(f"%{quest.title}%"),
                JournalEntry.narrative.ilike(f"%{quest.title}%"),
            ),
        )
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(10)
    )
    rows = list(entries_result.scalars().all())
    entries_data = [{"shorthand": e.shorthand} for e in rows]
    desc = await generate_quest_description(
        quest.title,
        entries_data,
        campaign.name if campaign else None,
        campaign.genre.value if campaign else None,
        config=config,
    )
    await llm_config_service.meter(db, user, config, desc)
    return {"description": desc}


@router.post("/suggest", response_model=QuestSuggestResponse)
async def suggest_quests_from_journals(
    ctx: CampaignContext = Depends(require_campaign("gm")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> QuestSuggestResponse:
    """Quest ideas from recent Shorthand (`campaign_id` query parameter). GM
    only: Shorthand is GM content and Quests are always_gm."""
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)

    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx).with_only_columns(JournalEntry.shorthand)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(8)
    )
    rows = entries_result.all()
    if not rows:
        raise HTTPException(status_code=422, detail="No journal entries found for this campaign.")

    entries_data = [{"shorthand": r.shorthand} for r in rows]
    suggestions = await suggest_quests(entries_data, campaign.name, campaign.genre.value, config=config)
    await llm_config_service.meter(db, user, config, "\n".join(suggestions))
    return QuestSuggestResponse(suggestions=suggestions)
