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
`scoped_select_multi(Model, role_map)`: rows of GM Campaigns unfiltered, rows
of Player Campaigns through the registry predicate for that Player.

Reduced ctxs (E0-Access.3) come only from `audience_ctx(campaign_id, target,
by=ctx)`, with target `ANON_VIEW`, `MEMBER_VIEW` or `as_user(user_id)`. They
are `read_only=True`; scripts/check_scoped_queries.py fails CI on any
`read_only=` outside app/access/. A GM request carrying
`X-Lorekeeper-Preview: member` is narrowed to the member view by
`require_campaign` (preview only narrows; a write in preview is 404).
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

import sqlalchemy as sa
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import MEMBERS, PUBLIC, Audience, AudienceLevel, covers, ctx_audience, owner
from app.access.identity import get_current_user
from app.access.policy import (
    ACTOR_SYSTEM, ACTOR_USER, ANON, GM, PLAYER, ROLES, Role, SystemReason, check_min_role, ctx_role, meets,
    not_found,
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
    produces "system". `read_only` marks a reduced ctx (`audience_ctx`): it
    reads with a narrower Audience and may write nothing.

    Shapes (checked here): gm → GM Audience; player → Owner(user_id), or no
    user + Members + read_only (the member view); anon → no user + Public +
    read_only.
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
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"CampaignContext: unknown role {self.role!r}")
        if self.is_owner and self.role != GM:
            raise ValueError("CampaignContext: the Owner's role is gm")
        if self.actor not in (ACTOR_USER, ACTOR_SYSTEM):
            raise ValueError(f"CampaignContext: unknown actor {self.actor!r}")
        if (self.actor == ACTOR_SYSTEM) != (self.system_reason is not None):
            raise ValueError("CampaignContext: a system ctx needs a system_reason, and only a system ctx has one")
        if self.actor == ACTOR_SYSTEM and (self.role != GM or self.user_id is None):
            raise ValueError("CampaignContext: a system ctx is a GM ctx of a real user")
        if self.actor == ACTOR_SYSTEM and self.read_only:
            raise ValueError("CampaignContext: a system ctx is never read-only")
        if not isinstance(self.audience, Audience):
            raise ValueError("CampaignContext: audience must be an Audience")
        if self.role == GM:
            if self.audience.level is not AudienceLevel.GM:
                raise ValueError("CampaignContext: a gm ctx has the GM Audience")
        elif self.role == PLAYER:
            own = self.user_id is not None and self.audience == owner(self.user_id)
            member_view = self.user_id is None and self.audience == MEMBERS and self.read_only
            if not (own or member_view):
                raise ValueError("CampaignContext: a player ctx has Audience Owner(user_id), "
                                 "or no user, Members and read_only (the member view)")
        elif self.role == ANON:
            if self.user_id is not None or self.audience != PUBLIC or not self.read_only:
                raise ValueError("CampaignContext: an anon ctx has no user, the Public Audience and read_only")

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
        if self.actor != ACTOR_USER or self.user_id is None or self.role == ANON or self.read_only:
            raise ValueError("as_system: needs a user's request ctx (not anon, not reduced, not already system)")
        try:
            why = SystemReason(reason)
        except ValueError:
            raise ValueError(
                f"as_system: reason must be one of {[r.value for r in SystemReason]}, got {reason!r}"
            ) from None
        return dataclasses.replace(
            self, role=GM, audience=ctx_audience(GM, self.user_id), actor=ACTOR_SYSTEM, system_reason=why,
        )


# ── Reduced ctxs: audience_ctx ─────────────────────────────────────────────

ANON_VIEW = "anon"      # what a read-only Share Link viewer sees (Public)
MEMBER_VIEW = "member"  # what any Member sees, owning nothing (Members)


@dataclass(frozen=True)
class AsUser:
    """`audience_ctx` target: what one user sees as a Player (Owner(user_id))."""

    user_id: uuid.UUID


def as_user(user_id: uuid.UUID | str) -> AsUser:
    uid = _parse_uuid(user_id)
    if uid is None:
        raise ValueError(f"as_user: not a user id: {user_id!r}")
    return AsUser(uid)


def audience_ctx(campaign_id: uuid.UUID | str, target: str | AsUser, *, by: CampaignContext) -> CampaignContext:
    """The only reduced-ctx constructor (E7 preview, E8 Player edition, E9
    per-recipient stats). Returns a read-only ctx in `campaign_id` reading as
    `target`: ANON_VIEW (role anon, Public), MEMBER_VIEW (role player, Members,
    no user) or `as_user(u)` (role player, Owner(u), user u).

    It may only narrow `by`: the result's Audience must cover `by.audience`
    (a GM may build any; a Player anon, member or themself; anon only anon),
    and `campaign_id` must be `by`'s. Anything else is `not_found()`."""
    cid = _parse_uuid(campaign_id)
    if cid is None or cid != by.campaign_id:
        not_found()
    if isinstance(target, AsUser):
        role, user_id, audience = PLAYER, target.user_id, owner(target.user_id)
    elif target == ANON_VIEW:
        role, user_id, audience = ANON, None, PUBLIC
    elif target == MEMBER_VIEW:
        role, user_id, audience = PLAYER, None, MEMBERS
    else:
        raise ValueError(f"audience_ctx: target must be ANON_VIEW, MEMBER_VIEW or as_user(...), got {target!r}")
    if not covers(audience, by.audience):
        not_found()
    return CampaignContext(
        campaign_id=cid, user_id=user_id, role=role, is_owner=False, audience=audience,
        grant_id=None, access_epoch=by.access_epoch, read_only=True,
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
    # populate_existing: a long-lived (worker) session must see the grant as
    # it is now, not as its identity map last loaded it.
    campaign = await db.get(Campaign, campaign_id, populate_existing=True)
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
        ).execution_options(populate_existing=True)
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

_require_cache: dict[tuple[str, bool], Any] = {}
_require_for_cache: dict[tuple[type, str, str, bool], Any] = {}

PREVIEW_HEADER = "X-Lorekeeper-Preview"
PREVIEW_MEMBER = "member"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _narrow_for_preview(request: Request, ctx: CampaignContext) -> CampaignContext:
    """RC-7: a GM request with `X-Lorekeeper-Preview: member` (exactly) reads
    as the member view; in preview any non-safe method is 404. Any other value,
    and the header on a Player or anon ctx, changes nothing (it only narrows)."""
    if ctx.role != GM or request.headers.get(PREVIEW_HEADER) != PREVIEW_MEMBER:
        return ctx
    narrowed = audience_ctx(ctx.campaign_id, MEMBER_VIEW, by=ctx)
    if request.method.upper() not in SAFE_METHODS:
        not_found()
    return narrowed


def require_campaign(min_role: str = "player", *, preview: bool = True):
    """FastAPI dependency: the caller's ctx in `campaign_id` (path parameter
    when the route has `{campaign_id}`, else a query parameter), with at least
    `min_role` (player < gm < owner), checked on the ctx after any preview
    narrowing. `preview=False` opts out of the preview header (`/me`, which
    always reports the real Role). Never returns a system ctx."""
    min_role = check_min_role(min_role)
    key = (min_role, bool(preview))
    if key in _require_cache:
        return _require_cache[key]

    async def dependency(
        request: Request,
        campaign_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CampaignContext:
        ctx = await ctx_for(db, user.id, campaign_id)
        if preview:
            ctx = _narrow_for_preview(request, ctx)
        if not meets(ctx, min_role):
            not_found()
        return ctx

    dependency.__name__ = f"require_campaign_{min_role}" + ("" if preview else "_no_preview")
    dependency.__qualname__ = dependency.__name__
    _require_cache[key] = dependency
    return dependency


def require_campaign_for(model: type, id_param: str, min_role: str = "player", *, preview: bool = True):
    """FastAPI dependency for item routes: load `model` by the path parameter
    `id_param`, then the caller's ctx in that row's Campaign with at least
    `min_role`. A missing row, a non-UUID id and too low a Role are the same
    `not_found()`. The preview header narrows here as in `require_campaign`."""
    min_role = check_min_role(min_role)
    if not hasattr(model, "campaign_id"):
        raise TypeError(f"require_campaign_for: {getattr(model, '__name__', model)!r} has no campaign_id")
    if not isinstance(id_param, str) or not id_param:
        raise ValueError("require_campaign_for: id_param must be the route's path parameter name")
    key = (model, id_param, min_role, bool(preview))
    if key in _require_for_cache:
        return _require_for_cache[key]

    async def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CampaignContext:
        if id_param not in request.path_params:
            # A wiring bug (typo or a non-path id), not a denial: fail loudly.
            raise RuntimeError(f"require_campaign_for: route {request.url.path!r} has no path parameter {id_param!r}")
        row_id = _parse_uuid(request.path_params[id_param])
        if row_id is None:
            not_found()
        row = await db.get(model, row_id)
        campaign_id = getattr(row, "campaign_id", None) if row is not None else None
        if campaign_id is None:
            not_found()
        ctx = await _resolve(db, user.id, campaign_id)
        if ctx is None:
            not_found()
        if preview:
            ctx = _narrow_for_preview(request, ctx)
        if not meets(ctx, min_role):
            not_found()
        return ctx

    dependency.__name__ = (f"require_{getattr(model, '__name__', 'model')}_{id_param}_{min_role}"
                           + ("" if preview else "_no_preview"))
    dependency.__qualname__ = dependency.__name__
    _require_for_cache[key] = dependency
    return dependency


# ── Cross-Campaign lists ───────────────────────────────────────────────────

class RoleMap(dict):
    """{campaign_id: ctx Role}, carrying the `user_id` it was built for (so
    `scoped_select_multi` can filter Player Campaigns as that Player)."""

    def __init__(self, *args: Any, user_id: uuid.UUID | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.user_id = user_id


async def role_map(db: AsyncSession, user: User | uuid.UUID) -> RoleMap:
    """{campaign_id: ctx Role} for every Campaign the user owns (gm) or is a
    Member of (co_gm -> gm, player -> player). Ownership wins."""
    uid = _user_id(user)
    out = RoleMap(user_id=uid)
    members = await db.execute(
        sa.select(CampaignMember.campaign_id, CampaignMember.role).where(CampaignMember.user_id == uid)
    )
    for campaign_id, stored in members.all():
        out[campaign_id] = ctx_role(stored)
    owned = await db.execute(sa.select(Campaign.id).where(Campaign.user_id == uid))
    for campaign_id in owned.scalars().all():
        out[campaign_id] = GM
    return out


def scoped_select_multi(model: type, roles: Mapping[uuid.UUID, str], user_id: uuid.UUID | None = None) -> sa.Select:
    """`select(model)` of the rows, across the Campaigns in `roles` (a
    `role_map`), that the user may see: every row of a GM Campaign, and the
    rows of a Player Campaign that pass `visible_clause` for that Player. An
    empty map selects nothing. `user_id` defaults to `roles.user_id`."""
    from app.access import registry  # lazy: registry imports the whole models package

    if not hasattr(model, "campaign_id"):
        raise TypeError(f"scoped_select_multi: {getattr(model, '__name__', model)!r} has no campaign_id")
    reg = registry.registration(model)
    stmt = sa.select(model)
    if not roles:
        return stmt.where(sa.false())
    unknown = {role for role in roles.values() if role not in (GM, PLAYER)}
    if unknown:
        raise ValueError(f"scoped_select_multi: roles must be gm or player, got {sorted(unknown)}")
    gm_ids = [cid for cid, role in roles.items() if role == GM]
    player_ids = [cid for cid, role in roles.items() if role == PLAYER]
    uid = user_id if user_id is not None else getattr(roles, "user_id", None)
    if player_ids and uid is None:
        raise ValueError("scoped_select_multi: Player Campaigns need the user_id (a role_map carries it)")

    def player_ctx(cid: uuid.UUID) -> CampaignContext:
        return CampaignContext(campaign_id=cid, user_id=uid, role=PLAYER, is_owner=False, audience=owner(uid))

    def gm_ctx(cid: uuid.UUID) -> CampaignContext:
        return CampaignContext(campaign_id=cid, user_id=uid, role=GM, is_owner=False,
                               audience=ctx_audience(GM, uid))

    branches = []
    if isinstance(reg, (registry.Derived, registry.DerivedFromSources)):
        # A derived predicate is scoped to one Campaign (its parent EXISTS),
        # for GMs too: one branch per Campaign, exactly as scoped_select.
        for cid in gm_ids:
            branches.append(sa.and_(model.campaign_id == cid, registry.visible_clause(model, gm_ctx(cid))))
        for cid in player_ids:
            branches.append(sa.and_(model.campaign_id == cid, registry.visible_clause(model, player_ctx(cid))))
        return stmt.where(sa.or_(*branches))
    # Stored / always_gm / membership predicates do not depend on the Campaign
    # (and are true() for a GM).
    if gm_ids:
        branches.append(model.campaign_id.in_(gm_ids))
    if player_ids:
        branches.append(sa.and_(model.campaign_id.in_(player_ids),
                                registry.visible_clause(model, player_ctx(player_ids[0]))))
    return stmt.where(sa.or_(*branches))
