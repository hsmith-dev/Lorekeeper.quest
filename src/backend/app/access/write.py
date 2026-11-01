"""The single write gate (E0-Access.6, AD-13, AR-13).

    entry = await scoped_get(db, JournalEntry, ctx, journal_id)
    can_write(ctx, entry)          # not_found() unless ctx may write it
    await db.delete(entry)

Every write route calls `can_write(ctx, row)` on the row it writes (a create
calls it through `check_create`, which ends with it). `may_write` is the
boolean form, for UI hints and branching that must not raise.

Rules, in order:

  * a reduced ctx (`read_only`: the preview header or any `audience_ctx`
    result) writes nothing;
  * anon (a read-only Share Link) writes nothing;
  * a row of another Campaign is never writable;
  * `gm` (Owner, Co-GM, and a system ctx, which is a GM ctx) may write any
    row of the Campaign;
  * `player` may write only
      - a `journal_entries` row with `kind=player` and `user_id = ctx.user_id`;
      - a `character_sheets` row whose `pc_entity_id` resolves to an Entity
        with `linked_user_id = ctx.user_id`. Until F3-world adds `entities`
        that check is always false (no query is made); E7 / F3 widen it here.

Every refusal is the one `not_found()` (never 403), so a write the caller may
not make answers exactly like a missing row.

A row with no `campaign_id` is writable only when its table is in
`_PARENT_SCOPED` (`journal_tags`: the route checked the parent entry with
`can_write` first). Any other unscoped row (a global `Tag`, shared across
Campaigns) is refused, for GMs too: fail closed.

Writes deliberately outside the gate:
  * `POST /api/campaigns/`: a new Campaign, so there is no ctx yet;
  * a Member leaving (`/leave`): their own grant, removed through grants.py;
  * chat sessions: owner rows, reached through `owned_get`;
  * source chunks: they follow their gated source document.

Whoever widens the Player rule (E7 Player Journals, F3 linked PCs) must call
`can_write` again after applying an update, not only before it: an update
could change `kind`, `user_id` or `pc_entity_id` and so move the row out of
what the Player may write.

It is sync and takes the loaded (or transient) row. It imports only the
policy and the ctx: rows are recognised by their table name, so this module
never pulls in the models package.
"""
from __future__ import annotations

from typing import Any

from app.access.context import CampaignContext
from app.access.policy import ANON, GM, PLAYER, not_found

_UNSCOPED = object()

_CAMPAIGNS = "campaigns"
_JOURNAL_ENTRIES = "journal_entries"
_CHARACTER_SHEETS = "character_sheets"
# Unscoped tables whose rows follow a parent the route already gated.
_PARENT_SCOPED = frozenset({"journal_tags"})
_PLAYER_KIND = "player"  # app.domain.enums.EntryKind.PLAYER (a StrEnum compares equal)


def _table(obj: Any) -> str | None:
    return getattr(type(obj), "__tablename__", None)


def _row_campaign(obj: Any) -> Any:
    """The Campaign `obj` belongs to: a Campaign's own id, else its
    `campaign_id`; `_UNSCOPED` for rows with no Campaign column (tags,
    journal_tags)."""
    if _table(obj) == _CAMPAIGNS:
        return getattr(obj, "id", None)
    if hasattr(type(obj), "campaign_id") or hasattr(obj, "campaign_id"):
        return getattr(obj, "campaign_id", None)
    return _UNSCOPED


def _player_may_write(ctx: CampaignContext, obj: Any) -> bool:
    if ctx.user_id is None:
        return False
    table = _table(obj)
    if table == _JOURNAL_ENTRIES:
        return getattr(obj, "kind", None) == _PLAYER_KIND and getattr(obj, "user_id", None) == ctx.user_id
    if table == _CHARACTER_SHEETS:
        # pc_entity_id -> entities.linked_user_id: no `entities` table until
        # F3-world, so no sheet is a Player's own linked PC yet.
        return False
    return False


def may_write(ctx: CampaignContext, obj: Any) -> bool:
    """True when ctx may write `obj` (see the module rules)."""
    if ctx.read_only or ctx.role == ANON:
        return False
    cid = _row_campaign(obj)
    if cid is _UNSCOPED:
        if _table(obj) not in _PARENT_SCOPED:
            return False
    elif cid != ctx.campaign_id:
        return False
    if ctx.role == GM:
        return True
    if ctx.role == PLAYER:
        return _player_may_write(ctx, obj)
    return False


def can_write(ctx: CampaignContext, obj: Any) -> None:
    """`not_found()` unless ctx may write `obj` (the single write gate)."""
    if not may_write(ctx, obj):
        not_found()
