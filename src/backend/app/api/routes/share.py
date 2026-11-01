import uuid
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.access import (
    COLLABORATE, ctx_for_share, not_found, project, project_all, resolve_share_token, scoped_get, scoped_select,
    share_ctx,
)
from app.core.limiter import limiter
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.schemas.share import (
    PublicCampaignResponse,
    JoinCampaignResponse,
    PublicJournalListResponse,
    PublicJournalResponse,
    PublicNpcResponse,
    PublicQuestResponse,
)
from app.api.deps import get_current_user, require_active_account
from app.domain.enums import CampaignRole

router = APIRouter()

# Read-only share links are anonymous and player-facing (E0-Access.4): a
# token resolves through access.share_ctx to an anon ctx (Public Audience),
# rows come from scoped_select / scoped_get, and every body goes through
# access.project (the Public* schemas are the anon Party projections). An
# unknown, revoked, expired or wrong-kind token, and a hidden or missing
# row, are all the one 404 {"detail":"Not found"}.

_ENTRY_TAGS = selectinload(JournalEntry.tags).selectinload(Tag.custom_category)


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
    share = await resolve_share_token(db, token, kind=None)
    ctx = ctx_for_share(share)
    campaign = await scoped_get(db, Campaign, ctx, share.campaign_id)
    return project(campaign, ctx, extra={"share_kind": share.kind})


@router.get("/{token}/journals", response_model=PublicJournalListResponse)
@limiter.limit("30/minute")
async def get_shared_journals(
    request: Request,
    token: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> PublicJournalListResponse:
    ctx = await share_ctx(db, token)
    query = (
        scoped_select(JournalEntry, ctx)
        .options(_ENTRY_TAGS)
        .order_by(JournalEntry.session_date.desc().nullslast(), JournalEntry.created_at.desc())
    )
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.offset((page - 1) * limit).limit(limit)
    items = (await db.execute(query)).scalars().all()
    return PublicJournalListResponse(items=await project_all(db, items, ctx), total=total, page=page, limit=limit)


@router.get("/{token}/journals/{journal_id}", response_model=PublicJournalResponse)
@limiter.limit("30/minute")
async def get_shared_journal(
    request: Request,
    token: str,
    journal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicJournalResponse:
    ctx = await share_ctx(db, token)
    entry = await scoped_get(db, JournalEntry, ctx, journal_id, options=[_ENTRY_TAGS])
    return (await project_all(db, [entry], ctx))[0]


@router.get("/{token}/npcs", response_model=list[PublicNpcResponse])
@limiter.limit("30/minute")
async def get_shared_npcs(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> list[PublicNpcResponse]:
    # NPCs are always_gm until F3-world (Decision B1-D4): an empty list.
    ctx = await share_ctx(db, token)
    rows = (await db.execute(scoped_select(NpcEntry, ctx).order_by(NpcEntry.name))).scalars().all()
    return await project_all(db, rows, ctx)


@router.get("/{token}/quests", response_model=list[PublicQuestResponse])
@limiter.limit("30/minute")
async def get_shared_quests(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> list[PublicQuestResponse]:
    # Quests are always_gm until F3-world (Decision B1-D4): an empty list.
    ctx = await share_ctx(db, token)
    rows = (await db.execute(scoped_select(Quest, ctx).order_by(Quest.title))).scalars().all()
    return await project_all(db, rows, ctx)


@router.post("/{token}/join", response_model=JoinCampaignResponse)
@limiter.limit("10/minute")
async def join_campaign(
    request: Request,
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JoinCampaignResponse:
    """Redeem a 'collaborate' share link. Needs a signed-in account (never
    anonymous). E0-Access.6: a link granting Player (or a legacy link with no
    Role, which grants Player) may be redeemed without a paid or granted
    account, since a Player only uses Party reads; a link granting any other
    Role (co_gm) still needs one (`require_active_account`, the 402
    account-gate). A revoked or expired link is the same 404 as an unknown
    one, checked before the account."""
    share = await resolve_share_token(db, token, COLLABORATE)
    if share.role is not None and CampaignRole(share.role) is not CampaignRole.PLAYER:
        await require_active_account(user)
    campaign = await db.get(Campaign, share.campaign_id)
    if campaign is None:
        not_found()

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
