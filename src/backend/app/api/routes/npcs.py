import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.npc import NpcEntry
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.schemas.npc import NpcCreate, NpcUpdate, NpcResponse, NpcExtractResponse
from app.schemas.journal import JournalLiteResponse
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.nlp_service import extract_tags
from app.services.chat_service import generate_npc_bio
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service
from app.db.models.tag import TagType

router = APIRouter()


async def _get_accessible_npc(db: AsyncSession, npc_id: uuid.UUID, user: User) -> NpcEntry:
    """Fetch an NPC and verify the requester has access to its campaign (owner or
    member) — NPCs are shared campaign knowledge, so any member may read/edit/
    delete them, unlike journal entries which stay author-scoped for deletion."""
    npc = await db.get(NpcEntry, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="Character not found")
    await get_campaign_with_access(db, npc.campaign_id, user)
    return npc


@router.get("/", response_model=list[NpcResponse])
async def list_npcs(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NpcResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(NpcEntry).where(NpcEntry.campaign_id == campaign_id).order_by(NpcEntry.name)
    )
    return list(result.scalars().all())


@router.post("/", response_model=NpcResponse, status_code=201)
async def create_npc(
    body: NpcCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NpcResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    npc = NpcEntry(user_id=user.id, **body.model_dump())
    db.add(npc)
    await db.commit()
    await db.refresh(npc)
    return npc


@router.put("/{npc_id}", response_model=NpcResponse)
async def update_npc(
    npc_id: uuid.UUID,
    body: NpcUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NpcResponse:
    npc = await _get_accessible_npc(db, npc_id, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(npc, field, value)
    await db.commit()
    await db.refresh(npc)
    return npc


@router.delete("/{npc_id}", status_code=204)
async def delete_npc(
    npc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    npc = await _get_accessible_npc(db, npc_id, user)
    await db.delete(npc)
    await db.commit()


@router.get("/{npc_id}", response_model=NpcResponse)
async def get_npc(
    npc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NpcResponse:
    return await _get_accessible_npc(db, npc_id, user)


@router.get("/{npc_id}/entries", response_model=list[JournalLiteResponse])
async def get_npc_entries(
    npc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[JournalLiteResponse]:
    npc = await _get_accessible_npc(db, npc_id, user)
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
        .limit(20)
    )
    return list(entries_result.scalars().all())


@router.post("/{npc_id}/generate")
async def generate_npc_bio_route(
    npc_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> dict:
    npc = await _get_accessible_npc(db, npc_id, user)
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
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, bio)
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
