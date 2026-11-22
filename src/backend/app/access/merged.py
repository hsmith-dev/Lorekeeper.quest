"""Old Entity ids after a merge (E0-WorldCore.9, FR-17).

    entity = await resolve_merged(db, ctx, entity_id)   # the survivor, or not_found()

A merge keeps the absorbed Entity's row with `merged_into_id` set to the
survivor, and the registry makes that row GM-only (`gm_when`). A link to the
old id must still resolve to the survivor, without telling a Player anything
the merge hid:

  * an id that was never merged is just `scoped_get` (a GM sees a deleted
    Entity as before; anyone else gets the one 404 for what they cannot see);
  * otherwise `merged_into_id` is followed within ctx's Campaign, at most
    `MAX_HOPS` hops, with a cycle guard. A GM may follow any hop. Anyone else
    may follow a hop only from a row that is not deleted, whose stored
    `visibility` is `party`, and whose newest `merge` row (on its survivor,
    `new_value.absorbed_id` = the row) recorded no floor, i.e. it was `party`
    when merged. The stored column alone is not enough: a GM can change a
    merged-away row's Visibility afterwards. Anything else fails closed;
  * the row reached must be live (not deleted, not merged) and pass
    `scoped_get` for ctx.

Anything else is `not_found()`, exactly like a missing id. The raw selects
here read only ids and the two columns the hop rule needs; the final row is
read through `scoped_get`.
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.context import CampaignContext
from app.access.policy import GM, not_found
from app.access.registry import scoped_get
from app.db.models.entity import Entity, EntityChange

MAX_HOPS = 16
_PARTY = "party"


def _uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        not_found()


async def _hop(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID) -> Any:
    stmt = (sa.select(Entity.id, Entity.merged_into_id, Entity.visibility, Entity.deleted_at)
            .where(Entity.campaign_id == ctx.campaign_id, Entity.id == entity_id))
    return (await db.execute(stmt)).first()


async def _party_at_merge(db: AsyncSession, ctx: CampaignContext, row: Any) -> bool:
    """The newest `merge` row of `row` into its survivor recorded no floor:
    the absorbed Entity was `party` when it was merged (its stored column
    can be changed afterwards, the merge row cannot)."""
    stmt = (sa.select(EntityChange.new_value["floor"].astext.label("floor"))
            .where(EntityChange.campaign_id == ctx.campaign_id, EntityChange.op == "merge",
                   EntityChange.entity_id == row.merged_into_id,
                   EntityChange.new_value["absorbed_id"].astext == str(row.id))
            .order_by(EntityChange.created_at.desc(), EntityChange.id.desc()).limit(1))
    found = (await db.execute(stmt)).first()
    return found is not None and found.floor is None


async def resolve_merged(db: AsyncSession, ctx: CampaignContext, entity_id: Any) -> Entity:
    """The Entity `entity_id` names for ctx: itself, or the survivor it was
    merged into (module docstring). `not_found()` when ctx may not follow it."""
    if not isinstance(ctx, CampaignContext):
        not_found()
    current = _uuid(entity_id)
    row = await _hop(db, ctx, current)
    if row is None or row.merged_into_id is None:
        return await scoped_get(db, Entity, ctx, current)
    seen: set[uuid.UUID] = set()
    hops = 0
    while row.merged_into_id is not None:
        if row.id in seen or hops >= MAX_HOPS:
            not_found()
        seen.add(row.id)
        if ctx.role != GM and not (str(getattr(row.visibility, "value", row.visibility)) == _PARTY
                                   and row.deleted_at is None and await _party_at_merge(db, ctx, row)):
            not_found()
        hops += 1
        row = await _hop(db, ctx, row.merged_into_id)
        if row is None:
            not_found()
    if row.deleted_at is not None:
        not_found()
    return await scoped_get(db, Entity, ctx, row.id)


__all__ = ["MAX_HOPS", "resolve_merged"]
