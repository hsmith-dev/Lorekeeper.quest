from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, case, false, or_, select, func
from sqlalchemy.orm import selectinload
import uuid

from app.core.limiter import limiter, user_or_ip
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
    JournalGMListResponse,
    AutocompleteRequest,
    AutocompleteResponse,
    RecapRequest,
    RecapResponse,
    SessionSummaryRequest,
    SessionSummaryResponse,
)
from app.schemas.tag import TagAttachRequest, TagGMResponse
from app.access import (
    GM, CampaignContext, ctx_for, ctx_for_request, not_found, project, project_all, require_campaign_for, role_ctx, role_map,
    scoped_get, scoped_select, scoped_select_multi, visible_clause,
)
from app.api.deps import get_current_user, get_user_llm_config, get_campaign_with_access
from app.services.journal_service import create_journal_entry, generate_draft_narrative
from app.services.dedup_service import check_hash
from app.services.chat_service import autocomplete_notes, generate_session_recap, summarize_session_transcript
from app.services import embedding_service
from app.services.retrieval_service import index_party_fields
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service

router = APIRouter()

# Routes whose body differs by Role return access.project output with
# response_model=None (FastAPI must not coerce a Party body into the GM
# schema); `responses=` keeps the GM schema in the OpenAPI docs.
_GM_OR_PARTY = "GM: the GM schema; Player or member preview: the Party schema (no `shorthand`)."
_ENTRY_TAGS = selectinload(JournalEntry.tags).selectinload(Tag.custom_category)


@router.post("/generate-draft", response_model=GenerateDraftResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def generate_journal_draft(
    request: Request,
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
    await llm_config_service.meter(db, user, config, body.notes, narrative)
    return GenerateDraftResponse(narrative=narrative)


@router.post("/generate", response_model=None, status_code=201,
             responses={201: {"model": JournalResponse, "description": _GM_OR_PARTY}})
@limiter.limit("20/minute", key_func=user_or_ip)
async def generate_journal(
    request: Request,
    body: GenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    if await check_hash(body.campaign_id, user.id, body.entry_hash):
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
    if body.narrative is None:
        await llm_config_service.meter(db, user, config, body.notes, entry.narrative)
    # The write response is projected like a read (AR-26).
    return (await project_all(db, [entry], ctx))[0]


@router.get("/", response_model=None,
            responses={200: {"model": JournalGMListResponse, "description": _GM_OR_PARTY}})
async def list_journals(
    request: Request,
    campaign_id: uuid.UUID | None = None,
    search: str | None = None,
    tag_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Entries of one Campaign, or (no `campaign_id`) of every Campaign the
    user owns or belongs to, each row projected by the caller's Role in its
    own Campaign (access.project: a non-GM row never carries Shorthand). In a
    Campaign where the caller is GM every entry is listed and `search`
    matches and ranks on `narrative_tsv` (Shorthand + Narrative). Elsewhere
    only entries visible to them are listed and `search` uses `party_tsv`
    (Narrative only), so a Shorthand-only word never changes what they find
    or its order (E0-Access.7). `total` counts visible rows only."""
    if campaign_id:
        ctx = await ctx_for_request(request, db, user, campaign_id)
        ctxs = [ctx]
        links = scoped_select(JournalTag, ctx)
        scope = ctx
    else:
        # No specific campaign: everything across every campaign this user can
        # see (owned or joined), each row by the user's Role in its own
        # Campaign (no preview: that narrows one Campaign).
        roles = await role_map(db, user)
        ctxs = [role_ctx(roles, cid) for cid in roles]
        links = scoped_select_multi(JournalTag, roles)
        scope = roles
    gm_ids = [c.campaign_id for c in ctxs if c.role == GM]
    party_ctxs = [c for c in ctxs if c.role != GM]

    tsq = func.plainto_tsquery("english", search) if search else None
    in_gm = JournalEntry.campaign_id.in_(gm_ids) if gm_ids else false()
    gm_branch = and_(in_gm, JournalEntry.narrative_tsv.op("@@")(tsq)) if search else in_gm
    party_branches = []
    for c in party_ctxs:
        branch = and_(JournalEntry.campaign_id == c.campaign_id, visible_clause(JournalEntry, c))
        if search:
            branch = and_(branch, JournalEntry.party_tsv.op("@@")(tsq))
        party_branches.append(branch)
    query = select(JournalEntry).where(or_(gm_branch, *party_branches) if party_branches else gm_branch)

    query = query.options(_ENTRY_TAGS)
    if search:
        if party_ctxs:
            rank = case(
                (in_gm, func.ts_rank(JournalEntry.narrative_tsv, tsq)),
                else_=func.ts_rank(JournalEntry.party_tsv, tsq),
            )
        else:
            rank = func.ts_rank(JournalEntry.narrative_tsv, tsq)
        # Ties break by row, so a hidden row can never shuffle equal-ranked
        # visible ones.
        query = query.order_by(rank.desc(), JournalEntry.created_at.desc(), JournalEntry.id)
    else:
        query = query.order_by(JournalEntry.created_at.desc(), JournalEntry.id)
    if tag_id:
        # Only links the caller may see: a tag found only in the Shorthand
        # matches nothing for a Player.
        visible_links = links.where(JournalTag.tag_id == tag_id).with_only_columns(JournalTag.journal_id)
        query = query.where(JournalEntry.id.in_(visible_links))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()

    return {"items": await project_all(db, items, scope), "total": total, "page": page, "limit": limit}


@router.get("/{journal_id}", response_model=None,
            responses={200: {"model": JournalResponse, "description": _GM_OR_PARTY}})
async def get_journal(
    journal_id: uuid.UUID,
    ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id")),
    db: AsyncSession = Depends(get_db),
):
    entry = await scoped_get(db, JournalEntry, ctx, journal_id, options=[_ENTRY_TAGS])
    return (await project_all(db, [entry], ctx))[0]


@router.post("/{journal_id}/tags", response_model=None, status_code=201,
             responses={201: {"model": TagGMResponse, "description": _GM_OR_PARTY}})
async def attach_tag(
    journal_id: uuid.UUID,
    body: TagAttachRequest,
    ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id")),
    db: AsyncSession = Depends(get_db),
):
    entry = await scoped_get(db, JournalEntry, ctx, journal_id)
    name = body.name.strip().title()[:200]
    if not name:
        raise HTTPException(status_code=422, detail="Tag name cannot be empty.")

    if body.custom_category_id:
        # A hidden category is a missing one.
        await scoped_get(db, TagCategory, ctx, body.custom_category_id)

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
        select(JournalTag).where(JournalTag.journal_id == entry.id, JournalTag.tag_id == tag.id)
    )
    if not link_exists.scalar_one_or_none():
        db.add(JournalTag(journal_id=entry.id, tag_id=tag.id))
        await db.commit()

    await db.refresh(tag, attribute_names=["custom_category"])
    return project(tag, ctx)


@router.delete("/{journal_id}/tags/{tag_id}", status_code=204)
async def detach_tag(
    journal_id: uuid.UUID,
    tag_id: uuid.UUID,
    ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id")),
    db: AsyncSession = Depends(get_db),
) -> None:
    entry = await scoped_get(db, JournalEntry, ctx, journal_id)
    # A link the caller may not see (a Shorthand tag, for a Player) is missing.
    result = await db.execute(
        scoped_select(JournalTag, ctx).where(JournalTag.journal_id == entry.id, JournalTag.tag_id == tag_id)
    )
    link = result.scalar_one_or_none()
    if not link:
        not_found()
    await db.delete(link)
    await db.commit()


@router.post("/autocomplete", response_model=AutocompleteResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def autocomplete_journal_notes(
    request: Request,
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
    await llm_config_service.meter(db, user, config, body.text, suggestion)
    return AutocompleteResponse(suggestion=suggestion)


@router.post("/recap", response_model=RecapResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def recap_campaign_session(
    request: Request,
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
    await llm_config_service.meter(db, user, config, recap)
    return RecapResponse(recap=recap)


@router.post("/summarize-session", response_model=SessionSummaryResponse)
@limiter.limit("20/minute", key_func=user_or_ip)
async def summarize_session(
    request: Request,
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
    await llm_config_service.meter(db, user, config, suggested_notes)
    return SessionSummaryResponse(suggested_notes=suggested_notes)


@router.post("/reindex")
async def reindex_journal_embeddings(
    campaign_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate vector embeddings for all journal entries in a campaign.
    GM only: the count covers every row, hidden ones included."""
    ctx = await ctx_for(db, user.id, campaign_id)
    if ctx.role != GM:
        not_found()
    entries_result = await db.execute(
        select(JournalEntry).where(JournalEntry.campaign_id == campaign_id)
    )
    entries = list(entries_result.scalars().all())
    for entry in entries:
        text = f"{entry.shorthand} {entry.narrative}"
        entry.embedding = embedding_service.embed(text)
        await index_party_fields(db, entry)
    await db.commit()
    return {"reindexed": len(entries)}


@router.delete("/{journal_id}", status_code=204)
async def delete_journal(
    journal_id: uuid.UUID,
    ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id")),
    db: AsyncSession = Depends(get_db),
) -> None:
    entry = await scoped_get(db, JournalEntry, ctx, journal_id)
    # Anyone with access can delete their own entry; only the campaign owner can
    # delete someone else's (the Player write rules arrive with E0-Access.6's
    # can_write). Every denial is the one 404, never a 403.
    if entry.user_id != ctx.user_id and not ctx.is_owner:
        not_found()
    await db.delete(entry)
    await db.commit()
