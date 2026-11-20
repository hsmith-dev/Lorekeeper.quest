"""Campaign Members routes, mounted under /api/campaigns (E0-Access).

E0-Access.2: `GET /{campaign_id}/me`, the caller's own Role, read by the
frontend's `useCampaignRole`. Any Member or the Owner gets it; anyone else
gets the one `404 {"detail":"Not found"}`.

E0-Access.12, Members management (Owner only, `require_campaign("owner")`):

    GET    /{campaign_id}/members                 the Owner row (member_id null), then Members by joined_at
    PATCH  /{campaign_id}/members/{member_id}     {role: "co_gm" | "player"}
    DELETE /{campaign_id}/members/{member_id}     ?delete_entries=true also deletes their entries

A non-owner, another Campaign's member id, the Owner's user id and a junk id
are all the one 404. Role and membership change only through
app/access/grants.py (`change_member_role`, `remove_member`): the epoch bump,
the after-commit `access:` publish and the `role` invalidation happen there,
and a co_gm → player demotion archives the Member's chat sessions there.

Account gate (app/api/deps.py, E0-Access.6): `/me` is a Party read
(openapi_extra=PARTY_READ), open to a Player with no paid account; the
management routes need one.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.access import (
    CampaignContext, can_write, change_member_role, display_role, remove_member, require_campaign, scoped_get,
    scoped_select,
)
from app.api.deps import PARTY_READ
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.journal import JournalEntry
from app.db.models.user import User
from app.db.session import get_db
from app.domain.enums import CampaignRole
from app.schemas.members import CampaignRoleResponse, MemberResponse, MemberRoleUpdate

router = APIRouter()

_owner = require_campaign("owner")


@router.get("/{campaign_id}/me", response_model=CampaignRoleResponse, openapi_extra=PARTY_READ)
async def get_my_campaign_role(
    ctx: CampaignContext = Depends(require_campaign("player", preview=False)),
) -> CampaignRoleResponse:
    return CampaignRoleResponse(
        campaign_id=ctx.campaign_id,
        role=ctx.role,
        is_owner=ctx.is_owner,
        display_role=display_role(ctx),
    )


def _member_row(member: CampaignMember, user: User) -> MemberResponse:
    return MemberResponse(
        member_id=member.id, user_id=member.user_id, display_name=user.display_name,
        role=CampaignRole(member.role).value, joined_at=member.created_at,
    )


@router.get("/{campaign_id}/members", response_model=list[MemberResponse])
async def list_campaign_members(
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> list[MemberResponse]:
    """The Owner first (`member_id: null`, `role: "owner"`, joined when the
    Campaign was created), then every Member by when they joined."""
    campaign = await scoped_get(db, Campaign, ctx, ctx.campaign_id, options=[selectinload(Campaign.user)])
    result = await db.execute(
        scoped_select(CampaignMember, ctx)
        .add_columns(User)
        .join(User, CampaignMember.user_id == User.id)
        .order_by(CampaignMember.created_at, CampaignMember.id)
    )
    owner = MemberResponse(
        member_id=None, user_id=campaign.user_id, display_name=campaign.user.display_name,
        role="owner", joined_at=campaign.created_at,
    )
    return [owner, *(_member_row(member, user) for member, user in result.all())]


@router.patch("/{campaign_id}/members/{member_id}", response_model=MemberResponse)
async def change_campaign_member_role(
    member_id: str,
    body: MemberRoleUpdate,
    ctx: CampaignContext = Depends(_owner),
    db: AsyncSession = Depends(get_db),
) -> MemberResponse:
    """Set a Member's Role. The same Role changes nothing (no epoch bump, no
    publish); a demotion from co_gm archives their chat sessions."""
    member = await scoped_get(db, CampaignMember, ctx, member_id, options=[selectinload(CampaignMember.user)])
    can_write(ctx, member)
    if await change_member_role(db, member, body.role):
        response = _member_row(member, member.user)
        await db.commit()
        return response
    return _member_row(member, member.user)


@router.delete("/{campaign_id}/members/{member_id}", status_code=204)
async def remove_campaign_member(
    member_id: str,
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
    can_write(ctx, member)
    if delete_entries:
        entries_result = await db.execute(
            scoped_select(JournalEntry, ctx).where(JournalEntry.user_id == member.user_id)
        )
        for entry in entries_result.scalars().all():
            can_write(ctx, entry)
            await db.delete(entry)
    # E0-Access.10: the grant is gone; open streams close on the publish.
    await remove_member(db, member)
    await db.commit()
