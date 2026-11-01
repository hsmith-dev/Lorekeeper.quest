"""CampaignContext and how a request (or a worker) gets one (AD-13, RC-6).

    @router.get("/{campaign_id}/thing")
    async def thing(ctx: CampaignContext = Depends(require_campaign("gm"))): ...

    @router.get("/{journal_id}")
    async def entry(ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id", "player"))): ...

`require_campaign` takes `campaign_id` like any FastAPI parameter: from the
path when the route template has `{campaign_id}`, else from the query string
(collection routes). `require_campaign_for` reads the row id from the path,
loads the row and checks the Role in the row's Campaign. Every denial is the
one `not_found()`.

Workers, hook handlers and the backfill runner have no request: they call
`ctx_for(db, user_id, campaign_id)`, which rebuilds the ctx `require_campaign`
would build for that user now.

Cross-Campaign lists use `role_map(db, user)` and
`scoped_select_multi(Model, role_map)`. Until the registry predicate lands
(E0-Access.3) only membership is applied.
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import Audience, ctx_audience
from app.access.identity import get_current_user
from app.access.policy import (
    ACTOR_SYSTEM, ACTOR_USER, GM, ROLES, Role, SystemReason, check_min_role, ctx_role, meets, not_found,
)
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.user import User
from app.db.session import get_db


@dataclass(frozen=True)
class CampaignContext:
    """Who is asking, in which Campaign, with which Role.

    `grant_id` is the `campaign_members.id` (None for the Owner and for anon),
    `access_epoch` is copied from that grant (0 for the Owner). `actor` is
    "user" for every ctx a request or `ctx_for` builds; only `as_system`
    produces "system".
    """

    campaign_id: uuid.UUID
    user_id: uuid.UUID | None
    role: Role
    is_owner: bool
    audience: Audience
    grant_id: uuid.UUID | None = None
    access_epoch: int = 0
    actor: str = ACTOR_USER
    system_reason: SystemReason | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"CampaignContext: unknown role {self.role!r}")
        if self.is_owner and self.role != GM:
            raise ValueError("CampaignContext: the Owner's role is gm")

    @property
    def is_gm(self) -> bool:
        return self.role == GM

    @property
    def is_system(self) -> bool:
        return self.actor == ACTOR_SYSTEM

    def as_system(self, reason: SystemReason | str) -> "CampaignContext":
        """A GM-level system ctx for the same Campaign and user, for the two
        writes that must see every row (RC-6). `reason` must be a
        SystemReason; anything else raises ValueError. Allowed call sites are
        fixed by scripts/check_scoped_queries.py."""
        try:
            why = SystemReason(reason)
        except ValueError:
            raise ValueError(
                f"as_system: reason must be one of {[r.value for r in SystemReason]}, got {reason!r}"
            ) from None
        return dataclasses.replace(
            self, role=GM, audience=ctx_audience(GM, self.user_id), actor=ACTOR_SYSTEM, system_reason=why,
        )


# ── Resolution ─────────────────────────────────────────────────────────────

def _user_id(user: User | uuid.UUID) -> uuid.UUID:
    return user if isinstance(user, uuid.UUID) else user.id


def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


async def _resolve(db: AsyncSession, user_id: uuid.UUID, campaign_id: uuid.UUID) -> CampaignContext | None:
    """The user's ctx in `campaign_id` now, or None (no such Campaign, or the
    user is neither its Owner nor a Member)."""
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None:
        return None
    if campaign.user_id == user_id:
        return CampaignContext(
            campaign_id=campaign_id, user_id=user_id, role=GM, is_owner=True,
            audience=ctx_audience(GM, user_id), grant_id=None, access_epoch=0,
        )
    member = (await db.execute(
        sa.select(CampaignMember).where(
            CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if member is None:
        return None
    role = ctx_role(member.role)
    return CampaignContext(
        campaign_id=campaign_id, user_id=user_id, role=role, is_owner=False,
        audience=ctx_audience(role, user_id), grant_id=member.id, access_epoch=member.access_epoch or 0,
    )


async def ctx_for(db: AsyncSession, user_id: User | uuid.UUID, campaign_id: uuid.UUID | str) -> CampaignContext:
    """The ctx `require_campaign` would build for this user now (current Role,
    grant_id, access_epoch). Raises `not_found()` when the user is no longer
    the Owner or a Member, or the Campaign is gone."""
    cid = _parse_uuid(campaign_id)
    if cid is None:
        not_found()
    ctx = await _resolve(db, _user_id(user_id), cid)
    if ctx is None:
        not_found()
    return ctx


# ── Request dependencies ───────────────────────────────────────────────────

_require_cache: dict[str, Any] = {}
_require_for_cache: dict[tuple[type, str, str], Any] = {}


def require_campaign(min_role: str = "player"):
    """FastAPI dependency: the caller's ctx in `campaign_id` (path parameter
    when the route has `{campaign_id}`, else a query parameter), with at least
    `min_role` (player < gm < owner). Never returns a system ctx."""
    min_role = check_min_role(min_role)
    if min_role in _require_cache:
        return _require_cache[min_role]

    async def dependency(
        campaign_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CampaignContext:
        ctx = await ctx_for(db, user.id, campaign_id)
        if not meets(ctx, min_role):
            not_found()
        return ctx

    dependency.__name__ = f"require_campaign_{min_role}"
    dependency.__qualname__ = dependency.__name__
    _require_cache[min_role] = dependency
    return dependency


def require_campaign_for(model: type, id_param: str, min_role: str = "player"):
    """FastAPI dependency for item routes: load `model` by the path parameter
    `id_param`, then the caller's ctx in that row's Campaign with at least
    `min_role`. A missing row, a non-UUID id and too low a Role are the same
    `not_found()`."""
    min_role = check_min_role(min_role)
    if not hasattr(model, "campaign_id"):
        raise TypeError(f"require_campaign_for: {getattr(model, '__name__', model)!r} has no campaign_id")
    if not isinstance(id_param, str) or not id_param:
        raise ValueError("require_campaign_for: id_param must be the route's path parameter name")
    key = (model, id_param, min_role)
    if key in _require_for_cache:
        return _require_for_cache[key]

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CampaignContext:
        row_id = _parse_uuid(request.path_params.get(id_param))
        if row_id is None:
            not_found()
        row = await db.get(model, row_id)
        campaign_id = getattr(row, "campaign_id", None) if row is not None else None
        if campaign_id is None:
            not_found()
        ctx = await _resolve(db, user.id, campaign_id)
        if ctx is None or not meets(ctx, min_role):
            not_found()
        return ctx

    dependency.__name__ = f"require_{getattr(model, '__name__', 'model')}_{id_param}_{min_role}"
    dependency.__qualname__ = dependency.__name__
    _require_for_cache[key] = dependency
    return dependency


# ── Cross-Campaign lists ───────────────────────────────────────────────────

async def role_map(db: AsyncSession, user: User | uuid.UUID) -> dict[uuid.UUID, Role]:
    """{campaign_id: ctx Role} for every Campaign the user owns (gm) or is a
    Member of (co_gm -> gm, player -> player). Ownership wins."""
    uid = _user_id(user)
    out: dict[uuid.UUID, Role] = {}
    members = await db.execute(
        sa.select(CampaignMember.campaign_id, CampaignMember.role).where(CampaignMember.user_id == uid)
    )
    for campaign_id, stored in members.all():
        out[campaign_id] = ctx_role(stored)
    owned = await db.execute(sa.select(Campaign.id).where(Campaign.user_id == uid))
    for campaign_id in owned.scalars().all():
        out[campaign_id] = GM
    return out


def scoped_select_multi(model: type, roles: Mapping[uuid.UUID, str]) -> sa.Select:
    """`select(model)` limited to rows of the Campaigns in `roles` (a
    `role_map`). An empty map selects nothing. E0-Access.3 adds the per-row
    registry predicate for each Campaign's Role."""
    if not hasattr(model, "campaign_id"):
        raise TypeError(f"scoped_select_multi: {getattr(model, '__name__', model)!r} has no campaign_id")
    stmt = sa.select(model)
    if not roles:
        return stmt.where(sa.false())
    return stmt.where(model.campaign_id.in_(list(roles)))
