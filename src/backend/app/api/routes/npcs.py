import uuid
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.access import (
    GM, LITE,
    CampaignContext, check_create, ctx_for_request, project, project_all, require_campaign, require_campaign_for,
    scoped_get, scoped_select,
)
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.npc import NpcEntry
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag
from app.schemas.npc import NpcCreate, NpcUpdate, NpcGMResponse, NpcExtractResponse
from app.schemas.journal import JournalLiteResponse
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.nlp_service import extract_tags
from app.services.chat_service import generate_npc_bio
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service
from app.db.models.tag import TagType

router = APIRouter()

# NPCs are always_gm until F3-world (Decision B1-D4): a Player (or a GM in
# member preview) lists none and gets the one 404 for every item route and
# for a create. Bodies go through access.project (response_model=None:
# FastAPI must not coerce a Party body into the GM schema).
_GM_OR_PARTY = "GM: NpcGMResponse; Player or member preview: NpcPartyResponse (no `notes`)."
_npc_ctx = require_campaign_for(NpcEntry, "npc_id")


async def _get_accessible_npc(db: AsyncSession, npc_id: uuid.UUID, ctx: CampaignContext) -> NpcEntry:
    """The NPC `npc_id` if ctx (the caller's ctx in the NPC's own Campaign,
    from `require_campaign_for`) may see it; else the one `not_found()`
    (hidden and missing are the same)."""
    return await scoped_get(db, NpcEntry, ctx, npc_id)


async def _visible_npc(npc_id: uuid.UUID, ctx: CampaignContext = Depends(_npc_ctx),
                       db: AsyncSession = Depends(get_db)) -> NpcEntry:
    """As a dependency, so a hidden NPC is the 404 before any later
    dependency (the LLM config's 402) can answer differently."""
    return await _get_accessible_npc(db, npc_id, ctx)


@router.get("/", response_model=None,
            responses={200: {"model": list[NpcGMResponse], "description": _GM_OR_PARTY}})
async def list_npcs(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(scoped_select(NpcEntry, ctx).order_by(NpcEntry.name))
    return await project_all(db, result.scalars().all(), ctx)


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def create_npc(
    request: Request,
    body: NpcCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    npc = NpcEntry(user_id=user.id, **body.model_dump())
    check_create(npc, ctx)  # a row the caller could not see is refused before writing
    db.add(npc)
    await db.commit()
    await db.refresh(npc)
    return project(npc, ctx)


@router.put("/{npc_id}", response_model=None,
            responses={200: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def update_npc(
    npc_id: uuid.UUID,
    body: NpcUpdate,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
):
    npc = await _get_accessible_npc(db, npc_id, ctx)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(npc, field, value)
    await db.commit()
    await db.refresh(npc)
    # The write response is projected like a read (AR-26).
    return project(npc, ctx)


@router.delete("/{npc_id}", status_code=204)
async def delete_npc(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
) -> None:
    npc = await _get_accessible_npc(db, npc_id, ctx)
    await db.delete(npc)
    await db.commit()


@router.get("/{npc_id}", response_model=None,
            responses={200: {"model": NpcGMResponse, "description": _GM_OR_PARTY}})
async def get_npc(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
):
    return project(await _get_accessible_npc(db, npc_id, ctx), ctx)


@router.get("/{npc_id}/entries", response_model=None,
            responses={200: {"model": list[JournalLiteResponse], "description": _GM_OR_PARTY}})
async def get_npc_entries(
    npc_id: uuid.UUID,
    ctx: CampaignContext = Depends(_npc_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Entries mentioning this NPC by name, among the entries visible to
    ctx. A GM matches the Shorthand or the Narrative and gets lite GM rows;
    anyone else matches the Narrative only and gets Party entries, so a
    Shorthand-only mention never shows up or reorders their list (E0-Access.7)."""
    npc = await _get_accessible_npc(db, npc_id, ctx)
    needle = f"%{npc.name}%"
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


@router.post("/{npc_id}/generate")
async def generate_npc_bio_route(
    npc_id: uuid.UUID,
    npc: NpcEntry = Depends(_visible_npc),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    campaign = await db.get(Campaign, npc.campaign_id)
    entries_result = await db.execute(
        select(JournalEntry)
        .where(
            JournalEntry.campaign_id == npc.campaign_id,
            or_(
                JournalEntry.shorthand.ilike(f"%{npc.name}%"),
                JournalEntry.narrative.ilike(f"%{npc.name}%"),
            ),
        )
        .order_by(JournalEntry.created_at.desc())
        .limit(10)
    )
    rows = list(entries_result.scalars().all())
    entries_data = [{"shorthand": e.shorthand} for e in rows]
    bio = await generate_npc_bio(
        npc.name,
        npc.role.value,
        entries_data,
        campaign.name if campaign else None,
        campaign.genre.value if campaign else None,
        config=config,
    )
    await llm_config_service.meter(db, user, config, bio)
    return {"description": bio}


@router.post("/extract", response_model=NpcExtractResponse)
async def extract_npcs_from_journals(
    campaign_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NpcExtractResponse:
    """Run spaCy NER over recent journal entries and return PERSON entity names."""
    await get_campaign_with_access(db, campaign_id, user)
    entries_result = await db.execute(
        select(JournalEntry.shorthand, JournalEntry.narrative)
        .where(JournalEntry.campaign_id == campaign_id)
        .order_by(JournalEntry.created_at.desc())
        .limit(15)
    )
    rows = entries_result.all()
    if not rows:
        return NpcExtractResponse(suggestions=[])

    combined = " ".join(f"{r.shorthand} {r.narrative}" for r in rows)
    tags = extract_tags(combined)
    names = [t.name for t in tags if t.tag_type == TagType.character]

    # Exclude names already in the wiki for this campaign
    existing_result = await db.execute(
        select(NpcEntry.name).where(NpcEntry.campaign_id == campaign_id)
    )
    existing = {n.lower() for (n,) in existing_result.all()}
    suggestions = [n for n in names if n.lower() not in existing]

    return NpcExtractResponse(suggestions=suggestions[:20])
