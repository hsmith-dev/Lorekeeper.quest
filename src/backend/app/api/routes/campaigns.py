import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
from app.api.deps import get_current_user, get_campaign_with_access, get_user_llm_config
from app.services.export_service import build_campaign_markdown, build_campaign_pdf
from app.services.chat_service import generate_campaign_concept
from app.services.llm_provider import LLMConfig, is_hosted_default
from app.services import billing_service

router = APIRouter()


async def _get_owned_campaign(db: AsyncSession, campaign_id: uuid.UUID, user: User) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


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
    if is_hosted_default(config):
        await billing_service.record_hosted_usage(db, user, description)
    return CampaignConceptResponse(name=name, description=description)


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignResponse]:
    owned = (await db.execute(select(Campaign).where(Campaign.user_id == user.id))).scalars().all()
    member_result = await db.execute(
        select(Campaign)
        .join(CampaignMember, CampaignMember.campaign_id == Campaign.id)
        .where(CampaignMember.user_id == user.id)
        # Eager-load the owner so we can surface "Shared by <name>" without an
        # extra round trip per row — joined campaigns are the whole point of
        # this endpoint, not a rare edge case, so N+1 here is worth avoiding.
        .options(selectinload(Campaign.user))
    )
    joined = member_result.scalars().all()

    return [
        CampaignResponse.model_validate(c, from_attributes=True).model_copy(update={"is_owner": True})
        for c in owned
    ] + [
        CampaignResponse.model_validate(c, from_attributes=True).model_copy(
            update={"is_owner": False, "owner_display_name": c.user.display_name}
        )
        for c in joined
    ]


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    body: CampaignUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/{campaign_id}/export")
async def export_campaign(
    campaign_id: uuid.UUID,
    format: str = Query("pdf", pattern="^(pdf|markdown)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.campaign_id == campaign_id, JournalEntry.user_id == user.id)
        .order_by(JournalEntry.session_date.asc().nullslast(), JournalEntry.created_at.asc())
    )
    entries = list(entries_result.scalars().all())

    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in campaign.name).strip().replace(" ", "_") or "campaign"

    if format == "markdown":
        content = build_campaign_markdown(campaign, entries)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
        )

    content = build_campaign_pdf(campaign, entries)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )


@router.get("/{campaign_id}/analytics", response_model=CampaignAnalytics)
async def get_campaign_analytics(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignAnalytics:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    base_filter = (JournalEntry.campaign_id == campaign_id) & (JournalEntry.user_id == user.id)

    totals_result = await db.execute(
        select(func.count(JournalEntry.id), func.avg(func.length(JournalEntry.narrative)))
        .where(base_filter)
    )
    total_entries, avg_length = totals_result.one()

    effective_date = func.coalesce(JournalEntry.session_date, cast(JournalEntry.created_at, Date))
    week_start = func.date_trunc("week", effective_date)
    weekly_result = await db.execute(
        select(week_start, func.count(JournalEntry.id))
        .where(base_filter)
        .group_by(week_start)
        .order_by(week_start)
    )
    entries_per_week = [
        WeeklyCount(week_start=w.date().isoformat(), count=c) for w, c in weekly_result.all()
    ]

    async def top_tags(tag_type: TagType, limit: int = 5) -> list[TagCount]:
        tags_result = await db.execute(
            select(Tag.name, func.count(JournalTag.journal_id))
            .join(JournalTag, Tag.id == JournalTag.tag_id)
            .join(JournalEntry, JournalTag.journal_id == JournalEntry.id)
            .where(base_filter, Tag.tag_type == tag_type)
            .group_by(Tag.id)
            .order_by(func.count(JournalTag.journal_id).desc())
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
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ShareTokenResponse]:
    await _get_owned_campaign(db, campaign_id, user)
    result = await db.execute(
        select(CampaignShareToken)
        .where(CampaignShareToken.campaign_id == campaign_id)
        .order_by(CampaignShareToken.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("/{campaign_id}/share", response_model=ShareTokenResponse, status_code=201)
async def create_share_token(
    campaign_id: uuid.UUID,
    body: ShareTokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    await _get_owned_campaign(db, campaign_id, user)
    token = CampaignShareToken(
        campaign_id=campaign_id,
        created_by_user_id=user.id,
        token=secrets.token_urlsafe(24),
        kind=body.kind,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


@router.delete("/{campaign_id}/share/{token_id}", status_code=204)
async def revoke_share_token(
    campaign_id: uuid.UUID,
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_owned_campaign(db, campaign_id, user)
    result = await db.execute(
        select(CampaignShareToken).where(
            CampaignShareToken.id == token_id, CampaignShareToken.campaign_id == campaign_id
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Share link not found")
    token.revoked = True
    await db.commit()


@router.get("/{campaign_id}/members", response_model=list[CampaignMemberResponse])
async def list_campaign_members(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignMemberResponse]:
    await _get_owned_campaign(db, campaign_id, user)
    result = await db.execute(
        select(CampaignMember, User)
        .join(User, CampaignMember.user_id == User.id)
        .where(CampaignMember.campaign_id == campaign_id)
        .order_by(CampaignMember.created_at)
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
    campaign_id: uuid.UUID,
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_owned_campaign(db, campaign_id, user)
    result = await db.execute(
        select(CampaignMember).where(
            CampaignMember.id == member_id, CampaignMember.campaign_id == campaign_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if delete_entries:
        entries_result = await db.execute(
            select(JournalEntry).where(
                JournalEntry.campaign_id == campaign_id, JournalEntry.user_id == member.user_id
            )
        )
        for entry in entries_result.scalars().all():
            await db.delete(entry)
    await db.delete(member)
    await db.commit()


@router.post("/{campaign_id}/leave", status_code=204)
async def leave_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Self-service counterpart to remove_campaign_member above — a
    collaborator removing themselves rather than the owner removing them.
    Always keeps the leaving member's existing entries (same default as an
    owner-initiated removal); there's no self-service "and delete my entries
    too" option here since that's a much bigger action to expose without a
    confirmation flow, and the owner can already do it via Remove + Delete
    Entries in Settings → Sharing if it's ever actually wanted."""
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.user_id == user.id:
        raise HTTPException(
            status_code=400,
            detail="You own this campaign — delete it instead of leaving it.",
        )
    result = await db.execute(
        select(CampaignMember).where(
            CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user.id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="You're not a member of this campaign.")
    await db.delete(member)
    await db.commit()


@router.get("/{campaign_id}/tag-categories", response_model=list[TagCategoryResponse])
async def list_tag_categories(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TagCategoryResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(TagCategory).where(TagCategory.campaign_id == campaign_id).order_by(TagCategory.name)
    )
    return list(result.scalars().all())


@router.post("/{campaign_id}/tag-categories", response_model=TagCategoryResponse, status_code=201)
async def create_tag_category(
    campaign_id: uuid.UUID,
    body: TagCategoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagCategoryResponse:
    await get_campaign_with_access(db, campaign_id, user)
    name = body.name.strip()[:50]
    if not name:
        raise HTTPException(status_code=422, detail="Category name cannot be empty.")

    existing = await db.execute(
        select(TagCategory).where(TagCategory.campaign_id == campaign_id, TagCategory.name.ilike(name))
    )
    if found := existing.scalar_one_or_none():
        return found

    category = TagCategory(campaign_id=campaign_id, created_by_user_id=user.id, name=name)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.delete("/{campaign_id}/tag-categories/{category_id}", status_code=204)
async def delete_tag_category(
    campaign_id: uuid.UUID,
    category_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(TagCategory).where(TagCategory.id == category_id, TagCategory.campaign_id == campaign_id)
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Tag category not found")
    await db.delete(category)
    await db.commit()


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    await db.delete(campaign)
    await db.commit()
