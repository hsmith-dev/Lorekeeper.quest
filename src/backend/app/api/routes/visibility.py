"""Bulk Visibility, mounted under /api/campaigns (E0-Access.9, Decision B1-D6).

`POST /{campaign_id}/visibility` with `{items: [{kind, id, field?}], value}`
(1 to 500 items) sets every item to `value` in one transaction through
`access.set_visibility_many`, and answers `{updated: n}`. GM only (Owner or
Co-GM, not in preview). All-or-nothing: an item that is missing, in another
Campaign or of the wrong journal kind is the one 404, an always-GM target is
422 `always_gm`, and either rolls back every item. E7's bulk controls call
this route.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, require_campaign, set_visibility_many
from app.db.session import get_db
from app.schemas.visibility import BulkVisibilityRequest, BulkVisibilityResponse

router = APIRouter()


@router.post("/{campaign_id}/visibility", response_model=BulkVisibilityResponse)
async def bulk_set_visibility(
    body: BulkVisibilityRequest,
    ctx: CampaignContext = Depends(require_campaign("gm")),
    db: AsyncSession = Depends(get_db),
) -> BulkVisibilityResponse:
    try:
        updated = await set_visibility_many(db, ctx, body.items, body.value)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return BulkVisibilityResponse(updated=updated)
