import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, cast, Date
import uuid

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag, JournalTag, TagType
from app.db.models.tag_category import TagCategory
from app.db.models.share_token import CampaignShareToken
from app.schemas.campaign import (
    CampaignCreate, CampaignUpdate, CampaignResponse,
    CampaignAnalytics, WeeklyCount, TagCount,
    CampaignConceptRequest, CampaignConceptResponse,
)
from app.db.models.campaign_member import CampaignMember
from app.schemas.share import ShareTokenResponse, ShareTokenCreate, CampaignMemberResponse
from app.schemas.tag_category import TagCategoryCreate, TagCategoryResponse
from app.access import (
    CampaignContext, check_create, project, project_all, require_campaign, role_map_for_request, scoped_get,
    scoped_select,
)
from app.api.deps import get_current_user, get_user_llm_config
from app.services.export_service import build_campaign_markdown, build_campaign_pdf
from app.services.chat_service import generate_campaign_concept
from app.services.llm_provider import LLMConfig
from app.services import llm_config_service

router = APIRouter()

# E0-Access.5: every Campaign route checks the caller's Role in this Campaign
# through require_campaign. Management (PATCH / DELETE the Campaign, Share
# Links, members) is Owner-only; authoring and GM reads (export, analytics,
# tag-category writes) need `gm` (Owner or Co-GM); Party reads need `player`.
# Every denial is the one 404 {"detail": "Not found"}.
_owner = require_campaign("owner")
_gm = require_campaign("gm")
_player = require_campaign("player")


@router.post("/", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = Campaign(**body.model_dump(), user_id=user.id)
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/generate-concept", response_model=CampaignConceptResponse)
async def generate_campaign_concept_route(
    body: CampaignConceptRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    config: LLMConfig = Depends(get_user_llm_config),
) -> CampaignConceptResponse:
    """Homebrew campaign generator — drafts a name + premise, doesn't create
    anything. The New Campaign form pre-fills with this and the user edits it
    like any other AI draft before actually submitting POST /."""
    name, description = await generate_campaign_concept(body.genre.value, body.prompt, config=config)
    await llm_config_service.meter(db, user, config, description)
    return CampaignConceptResponse(name=name, description=description)


_GM_OR_PARTY = "GM (Owner, Co-GM): CampaignGMResponse; Player or member preview: CampaignPartyResponse."


def _campaign_extra(campaign: Campaign, is_owner: bool) -> dict:
    # owner_display_name only for is_owner=False rows: lets the UI show
    # "Shared by <name>" so two campaigns with the same name (yours and one
    # someone shared with you) are still distinguishable at a glance.
    return {"is_owner": is_owner, "owner_display_name": None if is_owner else campaign.user.display_name}


@router.get("/", response_model=None,
            responses={200: {"model": list[CampaignResponse], "description": _GM_OR_PARTY}})
async def list_campaigns(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every Campaign the user owns or is a Member of, owned first, each
    projected for the user's Role in it (E0-Access.4), preview included (a
    GM previewing gets the Party projection of their GM Campaigns)."""
    roles = await role_map_for_request(request, db, user)
    if not roles:
        return []
    # The ids are the caller's own role_map (baselined: Campaign has no
    # campaign_id column for scoped_select_multi).
    campaigns = (await db.execute(
        select(Campaign).where(Campaign.id.in_(list(roles))).order_by(Campaign.created_at)
        # Eager-load the owner so we can surface "Shared by <name>" without an
        # extra round trip per row — joined campaigns are the whole point of
        # this endpoint, not a rare edge case, so N+1 here is worth avoiding.
        .options(selectinload(Campaign.user))
    )).scalars().all()
    owned = [c for c in campaigns if c.user_id == user.id]
    joined = [c for c in campaigns if c.user_id != user.id]
    return await project_all(db, owned + joined, roles, extra=lambda c: _campaign_extra(c, c.user_id == user.id))


@router.get("/{campaign_id}", response_model=None,
            responses={200: {"model": CampaignResponse, "description": _GM_OR_PARTY}})
async def get_campaign(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    """One Campaign the caller owns or is a Member of; anyone else gets the
    one 404, like a Campaign that does not exist."""
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id, options=[selectinload(Campaign.user)])
    return project(campaign, ctx, extra=_campaign_extra(campaign, ctx.is_owner))


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    body: CampaignUpdate,
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/{campaign_id}/export")
async def export_campaign(
    format: str = Query("pdf", pattern="^(pdf|markdown)$"),
    ctx: CampaignContext = Depends(_gm),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The caller's own entries of the Campaign as PDF or Markdown. GM only
    (Owner or Co-GM); E0-Access.13 widens it to every Member's entries,
    scoped by Role."""
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)

    entries_result = await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(JournalEntry.user_id == ctx.user_id)
        .order_by(JournalEntry.session_date.asc().nullslast(), JournalEntry.created_at.asc(), JournalEntry.id)
    )
    entries = list(entries_result.scalars().all())

    # ASCII only: HTTP headers are Latin-1, so a name like "Ōkami" made the response a 500.
    safe_name = "".join(
        c if (c.isascii() and c.isalnum()) or c in " -_" else "" for c in campaign.name
    ).strip().replace(" ", "_") or "campaign"

    if format == "markdown":
        content = build_campaign_markdown(campaign, entries)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
        )

    # WeasyPrint layout is CPU-bound: keep it off the event loop.
    content = await run_in_threadpool(build_campaign_pdf, campaign, entries)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )


@router.get("/{campaign_id}/analytics", response_model=CampaignAnalytics)
async def get_campaign_analytics(
    ctx: CampaignContext = Depends(_gm),
    db: AsyncSession = Depends(get_db),
) -> CampaignAnalytics:
    """Stats over the caller's own entries of the Campaign. GM only (Owner or
    Co-GM); E0-Access.13 widens it to every Member, scoped by Role."""
    own = scoped_select(JournalEntry, ctx).where(JournalEntry.user_id == ctx.user_id)

    totals_result = await db.execute(
        own.with_only_columns(func.count(JournalEntry.id), func.avg(func.length(JournalEntry.narrative)))
    )
    total_entries, avg_length = totals_result.one()

    effective_date = func.coalesce(JournalEntry.session_date, cast(JournalEntry.created_at, Date))
    week_start = func.date_trunc("week", effective_date)
    weekly_result = await db.execute(
        own.with_only_columns(week_start, func.count(JournalEntry.id))
        .group_by(week_start)
        .order_by(week_start)
    )
    entries_per_week = [
        WeeklyCount(week_start=w.date().isoformat(), count=c) for w, c in weekly_result.all()
    ]

    own_ids = own.with_only_columns(JournalEntry.id)

    async def top_tags(tag_type: TagType, limit: int = 5) -> list[TagCount]:
        # Links visible to ctx, on the caller's own entries.
        tags_result = await db.execute(
            scoped_select(JournalTag, ctx)
            .join(Tag, Tag.id == JournalTag.tag_id)
            .where(JournalTag.journal_id.in_(own_ids), Tag.tag_type == tag_type)
            .with_only_columns(Tag.name, func.count(JournalTag.journal_id))
            .group_by(Tag.id, Tag.name)
            .order_by(func.count(JournalTag.journal_id).desc(), Tag.name)
            .limit(limit)
        )
        return [TagCount(name=name, count=count) for name, count in tags_result.all()]

    return CampaignAnalytics(
        total_entries=total_entries or 0,
        avg_entry_length=round(float(avg_length), 1) if avg_length else 0.0,
        entries_per_week=entries_per_week,
        top_characters=await top_tags(TagType.character),
        top_quests=await top_tags(TagType.quest),
    )


@router.get("/{campaign_id}/share", response_model=list[ShareTokenResponse])
async def list_share_tokens(
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> list[ShareTokenResponse]:
    result = await db.execute(
        scoped_select(CampaignShareToken, ctx)
        .order_by(CampaignShareToken.created_at.desc(), CampaignShareToken.id)
    )
    return list(result.scalars().all())


@router.post("/{campaign_id}/share", response_model=ShareTokenResponse, status_code=201)
async def create_share_token(
    body: ShareTokenCreate,
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    token = CampaignShareToken(
        campaign_id=ctx.campaign_id,
        created_by_user_id=ctx.user_id,
        token=secrets.token_urlsafe(24),
        kind=body.kind,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


@router.delete("/{campaign_id}/share/{token_id}", status_code=204)
async def revoke_share_token(
    token_id: uuid.UUID,
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await scoped_get(db, CampaignShareToken, ctx, token_id)
    token.revoked = True
    await db.commit()


@router.get("/{campaign_id}/members", response_model=list[CampaignMemberResponse])
async def list_campaign_members(
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignMemberResponse]:
    result = await db.execute(
        scoped_select(CampaignMember, ctx)
        .add_columns(User)
        .join(User, CampaignMember.user_id == User.id)
        .order_by(CampaignMember.created_at, CampaignMember.id)
    )
    return [
        CampaignMemberResponse(
            id=member.id, user_id=member.user_id,
            display_name=member_user.display_name, email=member_user.email,
            created_at=member.created_at,
        )
        for member, member_user in result.all()
    ]


@router.delete("/{campaign_id}/members/{member_id}", status_code=204)
async def remove_campaign_member(
    member_id: uuid.UUID,
    delete_entries: bool = Query(
        False,
        description=(
            "False (default): revoke this member's access; their journal "
            "entries stay in the campaign, visible to the DM and remaining "
            "members. True: also permanently delete every entry they wrote "
            "in this campaign."
        ),
    ),
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    member = await scoped_get(db, CampaignMember, ctx, member_id)
    if delete_entries:
        entries_result = await db.execute(
            scoped_select(JournalEntry, ctx).where(JournalEntry.user_id == member.user_id)
        )
        for entry in entries_result.scalars().all():
            await db.delete(entry)
    await db.delete(member)
    await db.commit()


@router.post("/{campaign_id}/leave", status_code=204)
async def leave_campaign(
    ctx: CampaignContext = Depends(_player),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Self-service counterpart to remove_campaign_member above — a
    collaborator removing themselves rather than the owner removing them.
    Always keeps the leaving member's existing entries (same default as an
    owner-initiated removal); there's no self-service "and delete my entries
    too" option here since that's a much bigger action to expose without a
    confirmation flow, and the owner can already do it via Remove + Delete
    Entries in Settings → Sharing if it's ever actually wanted. Anyone who
    is neither the Owner nor a Member gets the one 404."""
    if ctx.is_owner:
        # Only the Owner can reach this (they know the Campaign exists).
        raise HTTPException(
            status_code=400,
            detail="You own this campaign — delete it instead of leaving it.",
        )
    member = await scoped_get(db, CampaignMember, ctx, ctx.grant_id)
    await db.delete(member)
    await db.commit()


@router.get("/{campaign_id}/tag-categories", response_model=list[TagCategoryResponse])
async def list_tag_categories(
    ctx: CampaignContext = Depends(_player),
    db: AsyncSession = Depends(get_db),
):
    """The categories the caller may see (a hidden one is absent)."""
    result = await db.execute(scoped_select(TagCategory, ctx).order_by(TagCategory.name, TagCategory.id))
    return await project_all(db, result.scalars().all(), ctx)


@router.post("/{campaign_id}/tag-categories", response_model=TagCategoryResponse, status_code=201)
async def create_tag_category(
    body: TagCategoryCreate,
    ctx: CampaignContext = Depends(_gm),
    db: AsyncSession = Depends(get_db),
):
    name = body.name.strip()[:50]
    if not name:
        raise HTTPException(status_code=422, detail="Category name cannot be empty.")

    existing = await db.execute(scoped_select(TagCategory, ctx).where(TagCategory.name.ilike(name)))
    if found := existing.scalars().first():
        return project(found, ctx)

    category = TagCategory(campaign_id=ctx.campaign_id, created_by_user_id=ctx.user_id, name=name)
    check_create(category, ctx)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return project(category, ctx)


@router.delete("/{campaign_id}/tag-categories/{category_id}", status_code=204)
async def delete_tag_category(
    category_id: uuid.UUID,
    ctx: CampaignContext = Depends(_gm),
    db: AsyncSession = Depends(get_db),
) -> None:
    category = await scoped_get(db, TagCategory, ctx, category_id)
    await db.delete(category)
    await db.commit()


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> None:
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id)
    await db.delete(campaign)
    await db.commit()
