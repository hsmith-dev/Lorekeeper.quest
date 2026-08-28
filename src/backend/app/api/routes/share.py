import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.limiter import limiter
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.share_token import CampaignShareToken
from app.schemas.share import PublicCampaignResponse, JoinCampaignResponse
from app.schemas.journal import JournalListResponse, JournalResponse
from app.schemas.npc import NpcResponse
from app.schemas.quest import QuestResponse
from app.api.deps import require_active_account

router = APIRouter()


async def _resolve_token(db: AsyncSession, token: str, kind: str | None = None) -> CampaignShareToken:
    query = select(CampaignShareToken).where(CampaignShareToken.token == token)
    if kind is not None:
        query = query.where(CampaignShareToken.kind == kind)
    result = await db.execute(query)
    share = result.scalar_one_or_none()
    if not share or share.revoked:
        raise HTTPException(status_code=404, detail="This link is invalid or has been revoked.")
    return share


@router.get("/{token}", response_model=PublicCampaignResponse)
@limiter.limit("30/minute")
async def get_shared_campaign(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> PublicCampaignResponse:
    # Either kind resolves here — this only returns non-sensitive campaign
    # metadata, used both for the read-only view and to preview a collaborate
    # invite ("You've been invited to join X") before the user commits to it.
    share = await _resolve_token(db, token)
    result = await db.execute(select(Campaign).where(Campaign.id == share.campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return PublicCampaignResponse(
        id=campaign.id, name=campaign.name, genre=campaign.genre,
        description=campaign.description, share_kind=share.kind,
    )


@router.get("/{token}/journals", response_model=JournalListResponse)
@limiter.limit("30/minute")
async def get_shared_journals(
    request: Request,
    token: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> JournalListResponse:
    share = await _resolve_token(db, token, "read_only")
    query = (
        select(JournalEntry)
        .where(JournalEntry.campaign_id == share.campaign_id)
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
        .order_by(JournalEntry.session_date.desc().nullslast(), JournalEntry.created_at.desc())
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * limit).limit(limit)
    items = (await db.execute(query)).scalars().all()
    return JournalListResponse(items=items, total=total, page=page, limit=limit)


@router.get("/{token}/journals/{journal_id}", response_model=JournalResponse)
@limiter.limit("30/minute")
async def get_shared_journal(
    request: Request,
    token: str,
    journal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JournalResponse:
    share = await _resolve_token(db, token, "read_only")
    result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.id == journal_id, JournalEntry.campaign_id == share.campaign_id)
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.get("/{token}/npcs", response_model=list[NpcResponse])
@limiter.limit("30/minute")
async def get_shared_npcs(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> list[NpcResponse]:
    share = await _resolve_token(db, token, "read_only")
    result = await db.execute(
        select(NpcEntry).where(NpcEntry.campaign_id == share.campaign_id).order_by(NpcEntry.name)
    )
    return list(result.scalars().all())


@router.get("/{token}/quests", response_model=list[QuestResponse])
@limiter.limit("30/minute")
async def get_shared_quests(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> list[QuestResponse]:
    share = await _resolve_token(db, token, "read_only")
    result = await db.execute(
        select(Quest).where(Quest.campaign_id == share.campaign_id).order_by(Quest.title)
    )
    return list(result.scalars().all())


@router.post("/{token}/join", response_model=JoinCampaignResponse)
@limiter.limit("10/minute")
async def join_campaign(
    request: Request,
    token: str,
    user: User = Depends(require_active_account),
    db: AsyncSession = Depends(get_db),
) -> JoinCampaignResponse:
    """Redeem a 'collaborate' share link. Requires an account with access
    granted — unlike the read-only endpoints above, this grants real write
    access, so anonymous (or not-yet-paid) redemption isn't an option."""
    share = await _resolve_token(db, token, "collaborate")
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == share.campaign_id))
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.user_id == user.id:
        return JoinCampaignResponse(campaign_id=campaign.id, campaign_name=campaign.name, already_member=True)

    existing = await db.execute(
        select(CampaignMember).where(
            CampaignMember.campaign_id == campaign.id, CampaignMember.user_id == user.id
        )
    )
    if existing.scalar_one_or_none():
        return JoinCampaignResponse(campaign_id=campaign.id, campaign_name=campaign.name, already_member=True)

    db.add(CampaignMember(campaign_id=campaign.id, user_id=user.id))
    await db.commit()
    return JoinCampaignResponse(campaign_id=campaign.id, campaign_name=campaign.name, already_member=False)
