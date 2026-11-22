"""The legacy NPC and Quest routes as adapters over `entities` (E0-WorldCore.6).

`/api/npcs/*` and `/api/quests/*` keep their paths and legacy response shapes
(NpcGMResponse / QuestGMResponse, and the Party pair), but every read is a
`scoped_select` of `Entity` and every write one or more
`world_service.apply_change` calls committed together. The legacy tables
`npcs`/`quests` are frozen (AD-18) and never read or written here.

Ids: a GM sees an Entity copied from a legacy row under its `legacy_npc_id`
/ `legacy_quest_id` (the id the old pages and links hold) and any other
Entity under its Entity id; every item route accepts either id. A non-GM
(a Player, a GM in member preview) always gets Entity ids: the Party body is
built from the projected `EntityPartyResponse` only, so it never holds
`gm_notes`, a legacy id or a timestamp, and a hidden field reads as unset.

An NPC is a live Character or Faction, a Quest a live Quest; anything else
(a Location, an Item, a deleted or merged Entity, another Campaign's, one ctx
cannot see) is the one `not_found()`. The value maps are
app/domain/legacy_world.py's. A write only sends the fields whose legacy
view would change (a `missing` Character sent `status: unknown` stays
`missing`); changing an NPC between a Character and a Faction is
`422 {"detail", "code": "invalid"}` and writes nothing.
"""
from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.access import LITE, CampaignContext, not_found, project_all, scoped_select
from app.db.models.entity import Entity, EntityMention
from app.db.models.journal import JournalEntry
from app.db.models.tag import Tag
from app.domain import legacy_world as lw
from app.schemas.entities import EntityGMResponse
from app.schemas.npc import NpcGMResponse, NpcPartyResponse
from app.schemas.quest import QuestGMResponse, QuestPartyResponse
from app.services.world_service import CanonChangeError

ENTRIES_LIMIT = 20
_TYPES = {"npc": lw.NPC_TYPES, "quest": lw.QUEST_TYPES}


def _types(kind: str) -> list[str]:
    return sorted(_TYPES[kind])


def live_entities(ctx: CampaignContext, kind: str) -> sa.Select:
    """ctx's live Entities that the legacy `kind` ("npc" or "quest") route serves."""
    return scoped_select(Entity, ctx).where(
        Entity.type.in_(_types(kind)), Entity.deleted_at.is_(None), Entity.merged_into_id.is_(None))


async def legacy_entity(db: AsyncSession, ctx: CampaignContext, row_id: uuid.UUID, kind: str, *,
                        lock: bool = False) -> Entity:
    """The live NPC/Quest Entity `row_id` names for ctx: its Entity id, or its
    legacy id (an Entity-id match wins); otherwise the one `not_found()`.
    `lock` takes the row `FOR UPDATE` (a write computing its changes from it)."""
    legacy = Entity.legacy_npc_id if kind == "npc" else Entity.legacy_quest_id
    stmt = live_entities(ctx, kind).where(sa.or_(Entity.id == row_id, legacy == row_id))
    if lock:
        stmt = stmt.with_for_update()
    rows = list((await db.execute(stmt.execution_options(populate_existing=True))).scalars().all())
    if not rows:
        not_found()
    return next((e for e in rows if e.id == row_id), rows[0])


# ── Response shapes ────────────────────────────────────────────────────────

def _legacy_id(entity: Entity, kind: str) -> uuid.UUID:
    legacy = entity.legacy_npc_id if kind == "npc" else entity.legacy_quest_id
    return legacy or entity.id


def as_npc(projected: Any, entity: Entity) -> NpcGMResponse | NpcPartyResponse:
    """The legacy NPC shape of one projected Entity (GM schema for a GM body)."""
    common = {"campaign_id": projected.campaign_id, "name": projected.name,
              "role": lw.npc_role_out(projected.type.value, projected.kind.value if projected.kind else None),
              "status": lw.npc_status_out(projected.type.value, projected.status),
              "description": projected.description}
    if isinstance(projected, EntityGMResponse):
        return NpcGMResponse(id=_legacy_id(entity, "npc"), notes=projected.gm_notes,
                             created_at=projected.created_at, updated_at=projected.updated_at, **common)
    return NpcPartyResponse(id=projected.id, **common)


def as_quest(projected: Any, entity: Entity) -> QuestGMResponse | QuestPartyResponse:
    """The legacy Quest shape of one projected Entity (GM schema for a GM body)."""
    common = {"campaign_id": projected.campaign_id, "title": projected.name,
              "description": projected.description, "status": lw.quest_status_out(projected.status)}
    if isinstance(projected, EntityGMResponse):
        return QuestGMResponse(id=_legacy_id(entity, "quest"), notes=projected.gm_notes,
                               created_at=projected.created_at, updated_at=projected.updated_at, **common)
    return QuestPartyResponse(id=projected.id, **common)


async def legacy_bodies(db: AsyncSession, ctx: CampaignContext, entities: list[Entity], kind: str) -> list[Any]:
    """Each Entity projected for ctx (`project_all`), then in its legacy shape."""
    shape = as_npc if kind == "npc" else as_quest
    return [shape(p, e) for e, p in zip(entities, await project_all(db, entities, ctx))]


# ── Writes ─────────────────────────────────────────────────────────────────

def npc_writes(entity: Entity, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """The CanonChanges a legacy NPC body (`exclude_none`, JSON values) means for
    `entity`, skipping every field whose legacy view would not change."""
    out: list[dict[str, Any]] = []
    eid = entity.id
    role = fields.get("role")
    if role is not None:
        if lw.npc_type(role) != entity.type:
            raise CanonChangeError("invalid", "An NPC cannot change between a character and a faction")
        if entity.type == lw.CHARACTER and lw.npc_role_out(entity.type, entity.kind) != role:
            out.append({"op": "set_kind", "entity_id": eid, "kind": lw.npc_kind(role)})
    for legacy_name, name in (("name", "name"), ("description", "description"), ("notes", "gm_notes")):
        if legacy_name in fields and fields[legacy_name] != getattr(entity, name):
            out.append({"op": "update_field", "entity_id": eid, "field": name, "value": fields[legacy_name]})
    status = fields.get("status")
    if status is not None and lw.npc_status_out(entity.type, entity.status) != status:
        out.append({"op": "set_status", "entity_id": eid, "status": lw.npc_status_in(entity.type, status)})
    return out


def quest_writes(entity: Entity, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """As `npc_writes`, for a legacy Quest body."""
    out: list[dict[str, Any]] = []
    eid = entity.id
    for legacy_name, name in (("title", "name"), ("description", "description"), ("notes", "gm_notes")):
        if legacy_name in fields and fields[legacy_name] != getattr(entity, name):
            out.append({"op": "update_field", "entity_id": eid, "field": name, "value": fields[legacy_name]})
    status = fields.get("status")
    if status is not None and lw.quest_status_out(entity.status) != status:
        out.append({"op": "set_status", "entity_id": eid, "status": lw.quest_status_in(status)})
    return out


def npc_create(fields: dict[str, Any]) -> dict[str, Any]:
    """The `create_entity` change of a legacy NPC create body (JSON values)."""
    role = fields.get("role") or "npc"
    entity_type = lw.npc_type(role)
    return {"op": "create_entity", "type": entity_type, "kind": lw.npc_kind(role), "name": fields["name"],
            "description": fields.get("description"), "gm_notes": fields.get("notes"),
            "status": lw.npc_status_in(entity_type, fields.get("status") or "unknown")}


def quest_create(fields: dict[str, Any]) -> dict[str, Any]:
    """The `create_entity` change of a legacy Quest create body (JSON values)."""
    return {"op": "create_entity", "type": lw.QUEST, "name": fields["title"],
            "description": fields.get("description"), "gm_notes": fields.get("notes"),
            "status": lw.quest_status_in(fields.get("status") or "active")}


# ── Entries ────────────────────────────────────────────────────────────────

async def confirmed_entries(db: AsyncSession, ctx: CampaignContext, entity: Entity) -> list[Any]:
    """The journal entries holding a confirmed Mention of `entity` that ctx may
    see (the Mention's own Audience, then the entry's), newest first, at most
    ENTRIES_LIMIT, as lite rows. No name matching."""
    mentioned = (scoped_select(EntityMention, ctx)
                 .where(EntityMention.entity_id == entity.id, EntityMention.confirmed.is_(True),
                        EntityMention.journal_id.is_not(None))
                 .with_only_columns(EntityMention.journal_id))
    rows = (await db.execute(
        scoped_select(JournalEntry, ctx)
        .where(JournalEntry.id.in_(mentioned))
        .options(selectinload(JournalEntry.tags).selectinload(Tag.custom_category))
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id)
        .limit(ENTRIES_LIMIT)
    )).scalars().all()
    return await project_all(db, list(rows), ctx, variant=LITE)


def by_name() -> tuple[Any, ...]:
    return (func.lower(Entity.name), Entity.id)


__all__ = [
    "ENTRIES_LIMIT", "as_npc", "as_quest", "by_name", "confirmed_entries", "legacy_bodies", "legacy_entity",
    "live_entities", "npc_create", "npc_writes", "quest_create", "quest_writes",
]
