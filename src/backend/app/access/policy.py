"""Role policy: how a stored Role becomes a ctx Role, the min_role order, and
the one 404 (AD-13, AR-23).

Vocabulary (epics.md, E0-Access):
  * stored `campaign_members.role` is `app.domain.enums.CampaignRole`
    {co_gm, player}; the Owner (`Campaign.user_id`) has no member row;
  * `CampaignContext.role` is one of {gm, player, anon}: Owner -> gm with
    `is_owner=True`, co_gm -> gm, player -> player, a read-only Share Link ->
    anon (built only by the share routes and `audience_ctx`, E0-Access.3);
  * `require_campaign(min_role)` orders player < gm < owner.

Too low a Role, no membership, a missing Campaign and a missing or invalid row
id all answer the same `404 {"detail":"Not found"}` through `not_found()`.
"""
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal, NoReturn

from fastapi import HTTPException, status

from app.domain.enums import CampaignRole

if TYPE_CHECKING:  # pragma: no cover
    from app.access.context import CampaignContext

# ── ctx Roles ──────────────────────────────────────────────────────────────

GM = "gm"
PLAYER = "player"
ANON = "anon"
OWNER = "owner"  # a min_role only; never a ctx Role (the Owner is gm + is_owner)

Role = Literal["gm", "player", "anon"]
MinRole = Literal["player", "gm", "owner"]

ROLES: frozenset[str] = frozenset({GM, PLAYER, ANON})
MIN_ROLES: tuple[str, ...] = (PLAYER, GM, OWNER)  # ascending
_MIN_RANK = {r: i for i, r in enumerate(MIN_ROLES)}

# `actor` on a CampaignContext.
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"

NOT_FOUND_DETAIL = "Not found"


class SystemReason(StrEnum):
    """The only reasons a ctx may be raised to a system ctx (RC-6). Each has
    exactly one allowed call site, enforced by scripts/check_scoped_queries.py."""

    ENTRY_DELETED = "entry_deleted"  # journal_service.delete_journal_entry (E0-Journal.3)
    MERGE = "merge"                  # world_service.merge_entities (E0-WorldCore.9)


# ── The one 404 ────────────────────────────────────────────────────────────

class NotFound(HTTPException):
    """The single denial: `404 {"detail":"Not found"}`. An HTTPException, so
    the existing `except HTTPException` callers keep working."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)


def not_found() -> NoReturn:
    """Raise the one 404. It raises itself, so `not_found()` and
    `raise not_found()` both work."""
    raise NotFound()


# ── Role arithmetic ────────────────────────────────────────────────────────

def ctx_role(stored: CampaignRole | str) -> Role:
    """The ctx Role a stored member Role grants: co_gm -> gm, player -> player."""
    value = CampaignRole(stored)  # ValueError on anything outside the enum
    return GM if value is CampaignRole.CO_GM else PLAYER


def check_min_role(min_role: str) -> MinRole:
    if min_role not in _MIN_RANK:
        raise ValueError(f"min_role must be one of {list(MIN_ROLES)}, got {min_role!r}")
    return min_role  # type: ignore[return-value]


def rank(ctx: "CampaignContext") -> int:
    """player 0, gm 1, owner 2; anon (and anything unknown) -1."""
    if ctx.role == GM:
        return _MIN_RANK[OWNER] if ctx.is_owner else _MIN_RANK[GM]
    if ctx.role == PLAYER:
        return _MIN_RANK[PLAYER]
    return -1


def meets(ctx: "CampaignContext", min_role: str) -> bool:
    """True when ctx's Role is at least `min_role` (player < gm < owner)."""
    return rank(ctx) >= _MIN_RANK[check_min_role(min_role)]


def display_role(ctx: "CampaignContext") -> Literal["Owner", "Co-GM", "Player"]:
    """The label the UI shows: Owner, Co-GM or Player."""
    if ctx.role == GM:
        return "Owner" if ctx.is_owner else "Co-GM"
    return "Player"
