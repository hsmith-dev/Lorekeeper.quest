"""Campaign events, mounted under /api/campaigns (E0-Access.11, AD-5).

`GET /{campaign_id}/events` (any Member, bearer header) is a server-sent
event stream of the Campaign's invalidations, filtered for the caller by
`access.campaign_event_stream`:

    event: subscribed       data: {}                      first, once the subscription is live
    event: invalidate       data: {"domain": "...", "id": "..." | null}
    event: ping             data: {}                      every 15 s
    event: access_changed   data: {"detail": "Not found"} then the stream ends

On every `subscribed` the client refetches the Campaign's data (there are no
event ids and no replay: reconnect, `subscribed`, refetch closes every gap).
The stream stands on the caller's real grant (`sse_response` closes it when
the grant changes); under `X-Lorekeeper-Preview: member` a GM's events are
filtered as the member view. Not a Member, a bad id or a missing Campaign is
the one 404. nginx: the `/api/campaigns/<id>/events` location in
locations.conf (generic zone, buffering off, 1 h read timeout).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, campaign_event_stream, require_campaign, stream_ctx
from app.core.limiter import limiter, user_or_ip
from app.core.sse import sse_response
from app.db.session import get_db

router = APIRouter()

EVENTS_RATE = "30/minute"


@router.get("/{campaign_id}/events", response_model=None, responses={
    200: {"content": {"text/event-stream": {}}, "description": "The Campaign's invalidations (SSE)"},
})
@limiter.limit(EVENTS_RATE, key_func=user_or_ip)
async def campaign_events(
    request: Request,
    ctx: CampaignContext = Depends(require_campaign("player", preview=False)),
    db: AsyncSession = Depends(get_db),
):
    filter_ctx = stream_ctx(request, ctx)
    bind = db.bind
    # The request session would otherwise be held (idle) for the whole stream.
    await db.close()
    return sse_response(campaign_event_stream(filter_ctx, bind=bind), ctx=ctx, bind=bind)
