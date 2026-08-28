from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
import uuid

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.journal import JournalEntry
from app.db.models.campaign import Campaign
from app.db.models.tag import Tag, JournalTag
from app.db.models.tag_category import TagCategory
from app.schemas.journal import (
    GenerateRequest,
    GenerateDraftRequest,
    GenerateDraftResponse,
    JournalResponse,
    JournalListResponse,
    AutocompleteRequest,
    AutocompleteResponse,
    RecapRequest,
    RecapResponse,
    SessionSummaryRequest,
    SessionSummaryResponse,
)
from app.schemas.tag import TagAttachRequest, TagResponse, TagCategoryRef
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access, accessible_campaign_ids
from app.services.journal_service import create_journal_entry, generate_draft_narrative
from app.services.dedup_service import check_hash
from app.services.chat_service import autocomplete_notes, generate_session_recap, summarize_session_transcript
from app.services.embedding_service import embed
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service

router = APIRouter()


@router.post("/generate-draft", response_model=GenerateDraftResponse)
async def generate_journal_draft(
    body: GenerateDraftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> GenerateDraftResponse:
    """Generate a narrative WITHOUT saving anything — the first half of the
    interactive flow (draft → user reviews/edits → POST /generate persists
    it). Nothing here touches the journal_entries table or the dedup hash
    store; a user can generate several drafts for the same notes without
    creating duplicate-entry noise, and a draft they never save leaves no
    trace."""
    await get_campaign_with_access(db, body.campaign_id, user)
    narrative = await generate_draft_narrative(db, user.id, body.campaign_id, body.notes, config)
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, body.notes, narrative)
    return GenerateDraftResponse(narrative=narrative)


@router.post("/generate", response_model=JournalResponse, status_code=201)
async def generate_journal(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JournalResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    if await check_hash(body.entry_hash):
        raise HTTPException(status_code=409, detail="Duplicate entry detected")

    # Only resolve an LLM config (and only meter it) when a narrative still
    # needs to be generated here — the normal path now supplies one already
    # generated (and reviewed) via /generate-draft, in which case saving is a
    # pure DB write with no LLM call and no reason to require one, even from
    # a BYO-key user who hasn't configured a personal key.
    config: LLMConfig | None = None
    if body.narrative is None:
        config = await get_user_llm_config(user=user, db=db)

    entry = await create_journal_entry(
        db=db,
        user_id=user.id,
        campaign_id=body.campaign_id,
        notes=body.notes,
        entry_hash=body.entry_hash,
        session_date=body.session_date,
        config=config,
        narrative=body.narrative,
    )
    if body.narrative is None and is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, body.notes, entry.narrative)
    return entry


@router.get("/", response_model=JournalListResponse)
async def list_journals(
    campaign_id: uuid.UUID | None = None,
    search: str | None = None,
    tag_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JournalListResponse:
    if campaign_id:
        await get_campaign_with_access(db, campaign_id, user)
        scope = JournalEntry.campaign_id == campaign_id
    else:
        # No specific campaign: everything across every campaign this user can
        # see (owned or joined), not just entries they personally authored —
        # a collaborator's entries are as much "yours to read" as your own.
        scope = JournalEntry.campaign_id.in_(await accessible_campaign_ids(db, user))

    query = (
        select(JournalEntry)
        .where(scope)
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
    )
    if search:
        query = query.where(
            JournalEntry.narrative_tsv.op("@@")(func.plainto_tsquery("english", search))
        ).order_by(
            func.ts_rank(JournalEntry.narrative_tsv, func.plainto_tsquery("english", search)).desc()
        )
    if tag_id:
        from app.db.models.tag import JournalTag
        query = query.join(JournalTag).where(JournalTag.tag_id == tag_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return JournalListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/{journal_id}", response_model=JournalResponse)
async def get_journal(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JournalResponse:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == journal_id, JournalEntry.campaign_id.in_(await accessible_campaign_ids(db, user)))
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return entry


async def _get_accessible_entry(db: AsyncSession, journal_id: uuid.UUID, user: User) -> JournalEntry:
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == journal_id, JournalEntry.campaign_id.in_(await accessible_campaign_ids(db, user)))
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    return entry


@router.post("/{journal_id}/tags", response_model=TagResponse, status_code=201)
async def attach_tag(
    journal_id: uuid.UUID,
    body: TagAttachRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagResponse:
    entry = await _get_accessible_entry(db, journal_id, user)
    name = body.name.strip().title()[:200]
    if not name:
        raise HTTPException(status_code=422, detail="Tag name cannot be empty.")

    category = None
    if body.custom_category_id:
        category_result = await db.execute(
            select(TagCategory).where(
                TagCategory.id == body.custom_category_id, TagCategory.campaign_id == entry.campaign_id
            )
        )
        category = category_result.scalar_one_or_none()
        if not category:
            raise HTTPException(status_code=404, detail="Tag category not found for this campaign.")

    tag_filter = (
        (Tag.custom_category_id == body.custom_category_id) if body.custom_category_id
        else (Tag.tag_type == body.tag_type)
    )
    existing = await db.execute(select(Tag).where(Tag.name == name, tag_filter))
    tag = existing.scalar_one_or_none()
    if not tag:
        tag = Tag(name=name, tag_type=body.tag_type, custom_category_id=body.custom_category_id)
        db.add(tag)
        await db.flush()

    link_exists = await db.execute(
        select(JournalTag).where(JournalTag.journal_id == journal_id, JournalTag.tag_id == tag.id)
    )
    if not link_exists.scalar_one_or_none():
        db.add(JournalTag(journal_id=journal_id, tag_id=tag.id))
        await db.commit()

    return TagResponse(
        id=tag.id, name=tag.name, tag_type=tag.tag_type,
        custom_category=TagCategoryRef.model_validate(category) if category else None,
    )


@router.delete("/{journal_id}/tags/{tag_id}", status_code=204)
async def detach_tag(
    journal_id: uuid.UUID,
    tag_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_accessible_entry(db, journal_id, user)
    result = await db.execute(
        select(JournalTag).where(JournalTag.journal_id == journal_id, JournalTag.tag_id == tag_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Tag is not attached to this entry.")
    await db.delete(link)
    await db.commit()


@router.post("/autocomplete", response_model=AutocompleteResponse)
async def autocomplete_journal_notes(
    body: AutocompleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> AutocompleteResponse:
    campaign_name: str | None = None
    genre: str | None = None
    if body.campaign_id:
        result = await db.execute(
            select(Campaign).where(Campaign.id == body.campaign_id, Campaign.user_id == user.id)
        )
        campaign = result.scalar_one_or_none()
        if campaign:
            campaign_name = campaign.name
            genre = campaign.genre.value
    suggestion = await autocomplete_notes(body.text, campaign_name, genre, config=config)
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, body.text, suggestion)
    return AutocompleteResponse(suggestion=suggestion)


@router.post("/recap", response_model=RecapResponse)
async def recap_campaign_session(
    body: RecapRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> RecapResponse:
    campaign = await get_campaign_with_access(db, body.campaign_id, user)

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.campaign_id == body.campaign_id)
        .order_by(JournalEntry.created_at.desc())
        .limit(10)
    )
    entries = list(reversed(entries_result.scalars().all()))
    if not entries:
        raise HTTPException(status_code=422, detail="No journal entries found for this campaign.")

    entries_data = [{"shorthand": e.shorthand, "narrative": e.narrative} for e in entries]
    recap = await generate_session_recap(entries_data, campaign.name, campaign.genre.value, config=config)
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, recap)
    return RecapResponse(recap=recap)


@router.post("/summarize-session", response_model=SessionSummaryResponse)
async def summarize_session(
    body: SessionSummaryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> SessionSummaryResponse:
    campaign = await get_campaign_with_access(db, body.campaign_id, user)

    if not body.transcript.strip():
        raise HTTPException(status_code=422, detail="Transcript is empty.")

    suggested_notes = await summarize_session_transcript(
        body.transcript, campaign.name, campaign.genre.value, config=config
    )
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, suggested_notes)
    return SessionSummaryResponse(suggested_notes=suggested_notes)


@router.post("/reindex")
async def reindex_journal_embeddings(
    campaign_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate vector embeddings for all journal entries in a campaign."""
    await get_campaign_with_access(db, campaign_id, user)
    entries_result = await db.execute(
        select(JournalEntry).where(JournalEntry.campaign_id == campaign_id)
    )
    entries = list(entries_result.scalars().all())
    for entry in entries:
        text = f"{entry.shorthand} {entry.narrative}"
        entry.embedding = embed(text)
    await db.commit()
    return {"reindexed": len(entries)}


@router.delete("/{journal_id}", status_code=204)
async def delete_journal(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == journal_id, JournalEntry.campaign_id.in_(await accessible_campaign_ids(db, user)))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    # Anyone with access can delete their own entry; only the campaign owner can
    # delete someone else's (matches the minimal Party Mode permission model —
    # no per-entry edit permissions, no roles beyond owner/member).
    if entry.user_id != user.id:
        campaign_result = await db.execute(select(Campaign).where(Campaign.id == entry.campaign_id))
        campaign = campaign_result.scalar_one_or_none()
        if not campaign or campaign.user_id != user.id:
            raise HTTPException(status_code=403, detail="Only the entry's author or the campaign owner can delete it.")
    await db.delete(entry)
    await db.commit()
