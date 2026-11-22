"""The legacy Quest routes, an adapter over `entities` (E0-WorldCore.6).

Same paths and legacy shapes as before; a Quest is now a live Quest Entity
(app/api/routes/_legacy_world.py has the rules: ids, Party bodies, writes).
Every write goes through `world_service.apply_change` and commits once;
`quests` is frozen (AD-18).

List order: a GM gets active, completed, failed, abandoned, then newest
first; anyone else the order of what they see (the rendered status, then
the name), so no hidden status or timestamp ranks a Party list.
"""
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import GM, CampaignContext, ctx_for_request, require_campaign, require_campaign_for_entity, \
    scoped_get, scoped_select
from app.api.deps import PARTY_READ, get_current_user, get_user_llm_config
from app.api.routes import _legacy_world as legacy
from app.api.routes.entities import _write
from app.db.models.campaign import Campaign
from app.db.models.entity import Entity
from app.db.models.journal import JournalEntry
from app.db.models.user import User
from app.db.session import get_db
from app.domain import legacy_world as lw
from app.schemas.journal import JournalLiteResponse
from app.schemas.quest import QuestCreate, QuestGMResponse, QuestSuggestResponse, QuestUpdate
from app.services import llm_config_service
from app.services.chat_service import generate_quest_description, suggest_quests
from app.services.llm_provider import LLMConfig
from app.services.world_service import apply_change

router = APIRouter()

KIND = "quest"

_GM_OR_PARTY = ("GM: QuestGMResponse; Player or member preview: QuestPartyResponse (Entity id, no `notes`, "
                "no timestamps).")
_quest_ctx = require_campaign_for_entity("quest_id", "player", legacy=KIND)
# E0-Access.6: writes and generation declare `gm` in the Quest's own Campaign,
# so a Player gets the missing-row 404 before any LLM config is resolved or
# any usage metered. Account gate (app/api/deps.py): the list, the item and
# its entries are Party reads (openapi_extra=PARTY_READ).
_quest_gm = require_campaign_for_entity("quest_id", "gm", legacy=KIND)

_STATUS_RANK = sa.case({s: i for i, s in enumerate(lw.QUEST_STATUSES)}, value=Entity.status,
                       else_=len(lw.QUEST_STATUSES))


async def _visible_quest(quest_id: uuid.UUID, ctx: CampaignContext = Depends(_quest_gm),
                         db: AsyncSession = Depends(get_db)) -> Entity:
    """As a dependency, so a hidden Quest is the 404 before any later
    dependency (the LLM config's 402) can answer differently."""
    return await legacy.legacy_entity(db, ctx, quest_id, KIND)


async def _body(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID):
    entity = await legacy.legacy_entity(db, ctx, entity_id, KIND)
    return (await legacy.legacy_bodies(db, ctx, [entity], KIND))[0]


@router.get("/", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": list[QuestGMResponse], "description": _GM_OR_PARTY}})
async def list_quests(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    stmt = legacy.live_entities(ctx, KIND)
    if ctx.role == GM:
        rows = list((await db.execute(
            stmt.order_by(_STATUS_RANK, Entity.created_at.desc(), Entity.id))).scalars().all())
        return await legacy.legacy_bodies(db, ctx, rows, KIND)
    rows = list((await db.execute(stmt.order_by(*legacy.by_name()))).scalars().all())
    bodies = await legacy.legacy_bodies(db, ctx, rows, KIND)
    return sorted(bodies, key=lambda b: (lw.quest_status_rank(b.status.value), b.title.lower(), str(b.id)))


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def create_quest(
    request: Request,
    body: QuestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    change = legacy.quest_create(body.model_dump(mode="json"))

    async def work():
        return await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _body(db, ctx, result.entity_id)


@router.put("/{quest_id}", response_model=None,
            responses={200: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def update_quest(
    quest_id: uuid.UUID,
    body: QuestUpdate,
    ctx: CampaignContext = Depends(_quest_gm),
    db: AsyncSession = Depends(get_db),
):
    entity = await legacy.legacy_entity(db, ctx, quest_id, KIND)
    entity_id = entity.id
    fields = body.model_dump(exclude_none=True, mode="json")

    async def work():
        for change in legacy.quest_writes(entity, fields):
            await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    # The write response is projected like a read (AR-26).
    return await _body(db, ctx, entity_id)


@router.delete("/{quest_id}", status_code=204)
async def delete_quest(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_gm),
    db: AsyncSession = Depends(get_db),
):
    entity = await legacy.legacy_entity(db, ctx, quest_id, KIND)
    entity_id = entity.id

    async def work():
        return await apply_change(db, ctx, {"op": "delete_entity", "entity_id": entity_id})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return Response(status_code=204)


@router.get("/{quest_id}", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": QuestGMResponse, "description": _GM_OR_PARTY}})
async def get_quest(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
):
    return await _body(db, ctx, quest_id)


@router.get("/{quest_id}/entries", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": list[JournalLiteResponse], "description": _GM_OR_PARTY}})
async def get_quest_entries(
    quest_id: uuid.UUID,
    ctx: CampaignContext = Depends(_quest_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The entries with a confirmed Mention of this Quest that ctx may see (the
    Mention's Audience and the entry's), newest first, at most 20, lite rows."""
    entity = await legacy.legacy_entity(db, ctx, quest_id, KIND)
    return await legacy.confirmed_entries(db, ctx, entity)


@router.post("/{quest_id}/generate")
async def generate_quest_description_route(
    quest_id: uuid.UUID,
    quest: Entity = Depends(_visible_quest),
    ctx: CampaignContext = Depends(_quest_gm),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    title = quest.name
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(or_(JournalEntry.shorthand.ilike(f"%{title}%"), JournalEntry.narrative.ilike(f"%{title}%")))
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(10)
    )
    entries_data = [{"shorthand": e.shorthand} for e in entries_result.scalars().all()]
    desc = await generate_quest_description(
        title, entries_data,
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
    only: Shorthand is GM content."""
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
