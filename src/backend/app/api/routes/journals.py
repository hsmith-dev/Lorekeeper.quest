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
    GM, CampaignContext, ctx_for_request, not_found, project, project_all, require_campaign, require_campaign_for,
    role_ctx, role_map_for_request, scoped_get, scoped_select, scoped_select_multi,
)
from app.api.deps import get_current_user, get_user_llm_config
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
# E0-Access.5: tag attach / detach and delete need `gm` in the entry's own
# Campaign (Player Journal deletes arrive with E7 through can_write).
_entry_gm = require_campaign_for(JournalEntry, "journal_id", "gm")


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
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    # A non-GM's draft gets no GM-only context (glossary, source canon).
    narrative = await generate_draft_narrative(db, user.id, body.campaign_id, body.notes, config,
                                               gm_context=ctx.is_gm)
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
        gm_context=ctx.is_gm,
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
    or its order (E0-Access.7). `total` counts visible rows only. The
    preview header narrows both forms: a GM previewing reads every GM
    Campaign as the member view (E0-Access.5)."""
    if campaign_id:
        ctx = await ctx_for_request(request, db, user, campaign_id)
        ctxs = [ctx]
        query = scoped_select(JournalEntry, ctx)
        links = scoped_select(JournalTag, ctx)
        scope = ctx
    else:
        # No specific campaign: everything across every campaign this user can
        # see (owned or joined), each row by the user's Role in its own
        # Campaign (previewing: GM Campaigns as the member view).
        roles = await role_map_for_request(request, db, user)
        ctxs = [role_ctx(roles, cid) for cid in roles]
        query = scoped_select_multi(JournalEntry, roles)
        links = scoped_select_multi(JournalTag, roles)
        scope = roles
    gm_ids = [c.campaign_id for c in ctxs if c.role == GM]
    has_party = any(c.role != GM for c in ctxs)

    in_gm = JournalEntry.campaign_id.in_(gm_ids) if gm_ids else false()
    if search:
        tsq = func.plainto_tsquery("english", search)
        # GM Campaigns match on narrative_tsv (Shorthand + Narrative), the
        # others on party_tsv (Narrative only).
        query = query.where(or_(
            and_(in_gm, JournalEntry.narrative_tsv.op("@@")(tsq)),
            and_(~in_gm, JournalEntry.party_tsv.op("@@")(tsq)) if has_party else false(),
        ))

    query = query.options(_ENTRY_TAGS)
    if search:
        if has_party:
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
    ctx: CampaignContext = Depends(_entry_gm),
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
    # Tags are global, unique by (name, type): the lookup is by name, never
    # by Campaign (baselined in scripts/scoped_queries_baseline.txt).
    existing = await db.execute(select(Tag).where(Tag.name == name, tag_filter))
    tag = existing.scalar_one_or_none()
    if not tag:
        tag = Tag(name=name, tag_type=body.tag_type, custom_category_id=body.custom_category_id)
        db.add(tag)
        await db.flush()

    link_exists = await db.execute(
        scoped_select(JournalTag, ctx).where(JournalTag.journal_id == entry.id, JournalTag.tag_id == tag.id)
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
    ctx: CampaignContext = Depends(_entry_gm),
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
    """With `campaign_id`, the Campaign's name and genre steer the
    suggestion; that needs `gm` there (Owner or Co-GM; anyone else gets the
    one 404). Without it, no Campaign context."""
    campaign_name: str | None = None
    genre: str | None = None
    if body.campaign_id:
        ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
        campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
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
    # GM only: the recap is built from Shorthand (GM content).
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)

    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
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
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)

    if not body.transcript.strip():
        raise HTTPException(status_code=422, detail="Transcript is empty.")

    suggested_notes = await summarize_session_transcript(
        body.transcript, campaign.name, campaign.genre.value, config=config
    )
    await llm_config_service.meter(db, user, config, suggested_notes)
    return SessionSummaryResponse(suggested_notes=suggested_notes)


@router.post("/reindex")
async def reindex_journal_embeddings(
    ctx: CampaignContext = Depends(require_campaign("gm")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Regenerate vector embeddings for all journal entries in a campaign
    (`campaign_id` query parameter). GM only: the count covers every row,
    hidden ones included."""
    entries_result = await db.execute(scoped_select(JournalEntry, ctx))
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
    ctx: CampaignContext = Depends(_entry_gm),
    db: AsyncSession = Depends(get_db),
) -> None:
    # A GM of the entry's Campaign (Owner or Co-GM) may delete any entry
    # there; anyone else gets the one 404 (Player Journal deletes arrive with
    # E7 through can_write).
    entry = await scoped_get(db, JournalEntry, ctx, journal_id)
    await db.delete(entry)
    await db.commit()
