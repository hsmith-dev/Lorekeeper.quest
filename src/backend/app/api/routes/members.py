"""Campaign Members routes, mounted under /api/campaigns (E0-Access).

E0-Access.2: `GET /{campaign_id}/me`, the caller's own Role, read by the
frontend's `useCampaignRole`. Any Member or the Owner gets it; anyone else
gets the one `404 {"detail":"Not found"}`. E0-Access.12 adds the Members
management routes here.

Account gate (app/api/deps.py, E0-Access.6): `/me` is a Party read
(openapi_extra=PARTY_READ), open to a Player with no paid account.
"""
from fastapi import APIRouter, Depends

from app.access import CampaignContext, display_role, require_campaign
from app.api.deps import PARTY_READ
from app.schemas.members import CampaignRoleResponse

router = APIRouter()


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
