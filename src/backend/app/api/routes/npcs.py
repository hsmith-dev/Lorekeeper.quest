"""The legacy NPC routes, an adapter over `entities` (E0-WorldCore.6).

Same paths and legacy shapes as before; an NPC is now a live Character or
Faction Entity (app/api/routes/_legacy_world.py has the rules: ids, value
maps, Party bodies, writes). Every write goes through
`world_service.apply_change` and commits once; `npcs` is frozen (AD-18).
"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, ctx_for_request, require_campaign, require_campaign_for_entity, scoped_get, \
    scoped_select
from app.api.deps import PARTY_READ, get_current_user, get_user_llm_config
from app.api.routes import _legacy_world as legacy
from app.api.routes.entities import _write
from app.clients.errors import ModelServiceError
from app.db.models.campaign import Campaign
from app.db.models.entity import Entity
from app.db.models.journal import JournalEntry
from app.db.models.tag import TagType
from app.db.models.user import User
from app.db.session import get_db
from app.domain import legacy_world as lw
from app.schemas.journal import JournalLiteResponse
from app.schemas.npc import NpcCreate, NpcExtractResponse, NpcGMResponse, NpcUpdate
from app.services import llm_config_service
from app.services.chat_service import generate_npc_bio
from app.services.llm_provider import LLMConfig
from app.services.nlp_service import extract_tags
from app.services.world_service import apply_change

logger = logging.getLogger(__name__)

router = APIRouter()

KIND = "npc"

# NPC extract reads at most this much of the newest entries: en_core_web_trf
# on a CPU-only box gets through roughly this in well under ML_NER_TIMEOUT_S,
# and the sidecar keeps working on (and holding its NER lock for) a request
# the client has given up on, so a smaller batch beats a timeout.
NPC_EXTRACT_MAX_CHARS = 20_000

# Bodies are built from access.project output (response_model=None: FastAPI
# must not coerce a Party body into the GM schema). A Player sees only
# published NPCs (migrated ones start GM-only, OD-1 A).
_GM_OR_PARTY = ("GM: NpcGMResponse; Player or member preview: NpcPartyResponse (Entity id, no `notes`, "
                "no timestamps).")
_npc_ctx = require_campaign_for_entity("npc_id", "player", legacy=KIND)
# E0-Access.6: writes and generation declare `gm` in the NPC's own Campaign,
# so a Player gets the missing-row 404 before any LLM config is resolved or
# any usage metered. Account gate (app/api/deps.py): the list, the item and
# its entries are Party reads (openapi_extra=PARTY_READ).
_npc_gm = require_campaign_for_entity("npc_id", "gm", legacy=KIND)


async def _visible_npc(npc_id: uuid.UUID, ctx: CampaignContext = Depends(_npc_gm),
                       db: AsyncSession = Depends(get_db)) -> Entity:
    """As a dependency, so a hidden NPC is the 404 before any later
    dependency (the LLM config's 402) can answer differently."""
    return await legacy.legacy_entity(db, ctx, npc_id, KIND)


async def _body(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID):
    entity = await legacy.legacy_entity(db, ctx, entity_id, KIND)
    return (await legacy.legacy_bodies(db, ctx, [entity], KIND))[0]


@router.get("/", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": list[NpcGMResponse], "description": _GM_OR_PARTY}})
async def list_npcs(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    rows = list((await db.execute(legacy.live_entities(ctx, KIND).order_by(*legacy.by_name()))).scalars().all())
    return await legacy.legacy_bodies(db, ctx, rows, KIND)


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def create_npc(
    request: Request,
    body: NpcCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    change = legacy.npc_create(body.model_dump(mode="json"))

    async def work():
        return await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _body(db, ctx, result.entity_id)


@router.put("/{npc_id}", response_model=None,
            responses={200: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def update_npc(
    npc_id: uuid.UUID,
    body: NpcUpdate,
    ctx: CampaignContext = Depends(_npc_gm),
    db: AsyncSession = Depends(get_db),
):
    entity = await legacy.legacy_entity(db, ctx, npc_id, KIND)
    entity_id = entity.id
    fields = body.model_dump(exclude_none=True, mode="json")

    async def work():
        for change in legacy.npc_writes(entity, fields):
            await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    # The write response is projected like a read (AR-26).
    return await _body(db, ctx, entity_id)


@router.delete("/{npc_id}", status_code=204)
async def delete_npc(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_gm),
    db: AsyncSession = Depends(get_db),
):
    entity = await legacy.legacy_entity(db, ctx, npc_id, KIND)
    entity_id = entity.id

    async def work():
        return await apply_change(db, ctx, {"op": "delete_entity", "entity_id": entity_id})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return Response(status_code=204)


@router.get("/{npc_id}", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def get_npc(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
):
    return await _body(db, ctx, npc_id)


@router.get("/{npc_id}/entries", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": list[JournalLiteResponse], "description": _GM_OR_PARTY}})
async def get_npc_entries(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The entries with a confirmed Mention of this NPC that ctx may see (the
    Mention's Audience and the entry's), newest first, at most 20, lite rows."""
    entity = await legacy.legacy_entity(db, ctx, npc_id, KIND)
    return await legacy.confirmed_entries(db, ctx, entity)


@router.post("/{npc_id}/generate")
async def generate_npc_bio_route(
    npc_id: uuid.UUID,
    npc: Entity = Depends(_visible_npc),
    ctx: CampaignContext = Depends(_npc_gm),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    name, role = npc.name, lw.npc_role_out(npc.type, npc.kind)
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(or_(JournalEntry.shorthand.ilike(f"%{name}%"), JournalEntry.narrative.ilike(f"%{name}%")))
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(10)
    )
    entries_data = [{"shorthand": e.shorthand} for e in entries_result.scalars().all()]
    bio = await generate_npc_bio(
        name, role, entries_data,
        campaign.name if campaign else None,
        campaign.genre.value if campaign else None,
        config=config,
    )
    await llm_config_service.meter(db, user, config, bio)
    return {"description": bio}


@router.post("/extract", response_model=NpcExtractResponse)
async def extract_npcs_from_journals(
    ctx: CampaignContext = Depends(require_campaign("gm")),
    db: AsyncSession = Depends(get_db),
) -> NpcExtractResponse:
    """Run NER (the ml sidecar's spaCy) over recent journal entries (`campaign_id` query
    parameter) and return PERSON names not yet a live Character or Faction.
    GM only: it reads Shorthand and GM-only Entities."""
    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx).with_only_columns(JournalEntry.shorthand, JournalEntry.narrative)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(15)
    )
    rows = entries_result.all()
    if not rows:
        return NpcExtractResponse(suggestions=[])

    # Newest first (the query order), stopping before the cap; at least the
    # newest entry, cut to the cap.
    parts: list[str] = []
    used = 0
    for r in rows:
        part = f"{r.shorthand} {r.narrative}"
        if parts and used + len(part) + 1 > NPC_EXTRACT_MAX_CHARS:
            break
        parts.append(part)
        used += len(part) + 1
    combined = " ".join(parts)[:NPC_EXTRACT_MAX_CHARS]
    try:
        tags = await extract_tags(combined)
    except ModelServiceError as exc:
        logger.warning("NPC extract failed, ml sidecar: %s", exc)
        raise HTTPException(status_code=503, detail="NER model unavailable")
    names = [t.name for t in tags if t.tag_type == TagType.character]

    # Exclude the names of the Campaign's live Characters and Factions.
    existing_result = await db.execute(legacy.live_entities(ctx, KIND).with_only_columns(Entity.name))
    existing = {n.lower() for (n,) in existing_result.all()}
    suggestions = [n for n in names if n.lower() not in existing]

    return NpcExtractResponse(suggestions=suggestions[:20])
