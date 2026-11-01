"""Share Links (E0-Access.4): a read-only token resolves to an anon ctx.

    ctx = await share_ctx(db, token)          # anon, Public Audience, read_only
    rows = (await db.execute(scoped_select(JournalEntry, ctx))).scalars().all()

An unknown token, a revoked one, an expired one (`expires_at <= now()`) and
a token of the wrong kind (a collaborate link on a content route) are all
the one `not_found()`: a viewer cannot tell a dead link from one that never
existed. Only the share routes and `audience_ctx` build anon ctxs.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import PUBLIC
from app.access.context import CampaignContext
from app.access.policy import ANON, not_found
from app.db.models.share_token import CampaignShareToken

READ_ONLY = "read_only"
COLLABORATE = "collaborate"


async def resolve_share_token(db: AsyncSession, token: str, kind: str | None = READ_ONLY) -> CampaignShareToken:
    """The live share token `token` of `kind` (any kind when None), or
    `not_found()`: unknown, revoked, expired and wrong-kind tokens all answer
    the same."""
    if not isinstance(token, str) or not token:
        not_found()
    stmt = sa.select(CampaignShareToken).where(
        CampaignShareToken.token == token,
        CampaignShareToken.revoked.is_(False),
        sa.or_(CampaignShareToken.expires_at.is_(None), CampaignShareToken.expires_at > sa.func.now()),
    )
    if kind is not None:
        stmt = stmt.where(CampaignShareToken.kind == kind)
    share = (await db.execute(stmt)).scalar_one_or_none()
    if share is None:
        not_found()
    return share


def ctx_for_share(share: CampaignShareToken) -> CampaignContext:
    """The anon ctx (Public Audience, read-only, no user) a live share token
    grants in its Campaign."""
    return CampaignContext(
        campaign_id=share.campaign_id, user_id=None, role=ANON, is_owner=False, audience=PUBLIC,
        grant_id=None, access_epoch=share.access_epoch or 0, read_only=True,
    )


async def share_ctx(db: AsyncSession, token: str, *, kind: str | None = READ_ONLY) -> CampaignContext:
    """`resolve_share_token` then `ctx_for_share`: the anon ctx of a live
    read-only token (by default), or `not_found()`."""
    return ctx_for_share(await resolve_share_token(db, token, kind))
