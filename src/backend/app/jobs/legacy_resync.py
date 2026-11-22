"""`backfill.legacy_resync`: re-copy what the old NPC/Quest pages changed
after the F3-world copy (E0-WorldCore.6), once per Campaign.

Until E0-WorldCore.6 the legacy routes kept writing `npcs`/`quests` after
F3-world copied them into `entities`; from this release they are adapters
over `entities` and the legacy tables are frozen. The `data_backfills` row
`legacy_resync_v1` (revision 9c4fbee4bdd1) runs this kind once per Campaign
as its Owner (app/jobs/backfill.py). Every write goes through
`world_service.apply_change`, so each is a normal, revertible history row.

A cursor Job (`run_cursor`), one item per step, cursor `{"phase", "after"}`:

* `entity`: each Entity with a legacy id, by id. The Entity is locked
  (`FOR UPDATE`) first; a deleted or merged one is skipped. Its legacy row L
  is compared field by field (`name`/`title`, `description`, `gm_notes`
  (`notes`), `status` mapped exactly like F3, `kind` (Characters), and the
  type: role faction <-> character). For a field f with
  `legacy = map(L.f) != current = E.f`, and `rows` the Entity's history rows
  of field f (any op, oldest first):
    - no rows (the World never touched f): apply it, but only when the
      Entity is GM-only or f is `gm_notes` (privacy first, OD-1 A);
    - else `base = rows[0].old_value` (a status row may hold `{status, ...}`):
      `legacy == base` means the old page did not change f (nothing to do);
      otherwise both sides changed it and the World wins.
  Every legacy change not applied (both sides, a published Entity, a type
  change, a value apply_change refuses) goes into one GM-only `canon_note`
  per Entity: "Old NPC page edit not applied (World version kept): ...". A
  Quest moved into `completed` also gets `attributes.completed_at` =
  L.updated_at, as F3 does. L gone: `delete_entity` when the Entity's only
  history is its `migrated` row, otherwise a `canon_note` saying so.
* `npc`, `quest`: each legacy row no Entity holds the legacy id of (a row
  created on the old page after the copy), by id: a GM-only Entity with the
  F3 id `md5('f3-world:<kind>:' || id)`, the legacy id and the F3 mapping.

Idempotent: each step's writes and its cursor commit together; a re-run
finds `legacy == current`, an existing identical `canon_note` (checked
before writing) or the deterministic create id, and writes nothing. Legacy
rows are only read, never locked or changed (no writer of them remains).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, scoped_select
from app.db.models.entity import Entity, EntityChange
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.domain import legacy_world as lw
from app.domain.enums import JobQueue
from app.jobs.backfill import CursorStep, register_backfill, run_cursor
from app.jobs.registry import JobKind, register
from app.services.world_service import CanonChangeError, apply_change

logger = logging.getLogger(__name__)

KIND = "backfill.legacy_resync"
BACKFILL_NAME = "legacy_resync_v1"
PHASES = ("entity", "npc", "quest")
_PAGE = {"npc": "NPC", "quest": "Quest"}

LEGACY_RESYNC = register(JobKind(
    name=KIND, queue=JobQueue.BACKFILL, timeout_s=120, handler="app.jobs.legacy_resync:handle",
    resources=frozenset(), live_safe=True, result_audience="gm",
))
register_backfill(BACKFILL_NAME, KIND)


def _v(value: Any) -> Any:
    """An enum member's value (legacy columns are PG enums), else the value."""
    return getattr(value, "value", value)


def _iso(value: datetime) -> str:
    """ISO 8601 UTC like the F3 copy: 2026-01-15T18:30:00.000000Z."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ── Cursor ─────────────────────────────────────────────────────────────────

def _phase_stmt(ctx: CampaignContext, phase: str) -> tuple[sa.Select, Any]:
    if phase == "entity":
        return (scoped_select(Entity, ctx).with_only_columns(Entity.id)
                .where(sa.or_(Entity.legacy_npc_id.is_not(None), Entity.legacy_quest_id.is_not(None))), Entity.id)
    model, column = (NpcEntry, Entity.legacy_npc_id) if phase == "npc" else (Quest, Entity.legacy_quest_id)
    # Every Entity counts, deleted ones too: a deleted Entity's legacy row is never re-created.
    held = scoped_select(Entity, ctx).with_only_columns(column).where(column.is_not(None))
    return scoped_select(model, ctx).with_only_columns(model.id).where(model.id.not_in(held)), model.id


async def _next_id(db: AsyncSession, ctx: CampaignContext, phase: str, after: str | None) -> uuid.UUID | None:
    stmt, col = _phase_stmt(ctx, phase)
    if after is not None:
        stmt = stmt.where(col > uuid.UUID(after))
    return (await db.execute(stmt.order_by(col).limit(1))).scalar_one_or_none()


async def _count(db: AsyncSession, ctx: CampaignContext, phase: str, after: str | None) -> int:
    stmt, col = _phase_stmt(ctx, phase)
    if after is not None:
        stmt = stmt.where(col > uuid.UUID(after))
    return int((await db.execute(sa.select(sa.func.count()).select_from(stmt.subquery()))).scalar_one())


async def handle(job: Any, ctx: CampaignContext, db: AsyncSession) -> None:
    """One step: the next copied Entity, then the next uncopied NPC, then Quest."""
    done = int((job.payload or {}).get("done") or 0)

    async def select_next(db: AsyncSession, ctx: CampaignContext, cursor: Any) -> CursorStep | None:
        phase = (cursor or {}).get("phase", PHASES[0])
        after = (cursor or {}).get("after")
        start = PHASES.index(phase) if phase in PHASES else 0
        for i, p in enumerate(PHASES[start:], start):
            item = await _next_id(db, ctx, p, after if p == phase else None)
            if item is None:
                continue
            remaining = await _count(db, ctx, p, None if p != phase else after)
            for later in PHASES[i + 1:]:
                remaining += await _count(db, ctx, later, None)
            return CursorStep(item=(p, item), cursor={"phase": p, "after": str(item)}, total=done + remaining)
        return None

    async def process(db: AsyncSession, ctx: CampaignContext, item: tuple[str, uuid.UUID]) -> None:
        phase, item_id = item
        if phase == "entity":
            await resync_entity(db, ctx, item_id)
        else:
            await copy_legacy_row(db, ctx, phase, item_id)

    await run_cursor(job, ctx, db, select_next=select_next, process_one=process)


# ── One copied Entity ──────────────────────────────────────────────────────

async def _history(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID) -> list[EntityChange]:
    return list((await db.execute(
        scoped_select(EntityChange, ctx).where(EntityChange.entity_id == entity_id)
        .order_by(EntityChange.created_at, EntityChange.id).execution_options(populate_existing=True)
    )).scalars().all())


async def _note(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID, note: str,
                history: list[EntityChange]) -> None:
    """A GM-only canon_note, unless the Entity already has this exact note."""
    for row in history:
        if row.op == "canon_note" and isinstance(row.new_value, dict) and row.new_value.get("note") == note:
            return
    await apply_change(db, ctx, {"op": "canon_note", "entity_id": entity_id, "note": note})


def _quote(value: Any) -> str:
    if value is None:
        return "(empty)"
    return "'" + str(value) + "'"


def _fields(kind: str, entity: Entity, row: Any) -> list[tuple[str, str, Any, Any, Any]]:
    """(entity field, legacy field name, legacy value mapped, current value, legacy value as shown)."""
    if kind == "npc":
        role, status = _v(row.role), _v(row.status)
        out = [("name", "name", row.name, entity.name, _quote(row.name)),
               ("description", "description", row.description, entity.description, _quote(row.description)),
               ("gm_notes", "notes", row.notes, entity.gm_notes, _quote(row.notes)),
               ("status", "status", lw.npc_status_in(entity.type, status), entity.status, status)]
        if entity.type == lw.CHARACTER and lw.npc_type(role) == lw.CHARACTER:
            out.append(("kind", "role", lw.npc_kind(role), entity.kind, role))
        return out
    status = _v(row.status)
    return [("name", "title", row.title, entity.name, _quote(row.title)),
            ("description", "description", row.description, entity.description, _quote(row.description)),
            ("gm_notes", "notes", row.notes, entity.gm_notes, _quote(row.notes)),
            ("status", "status", lw.quest_status_in(status), entity.status, status)]


def _base(row: EntityChange, name: str) -> Any:
    old = row.old_value
    if name == "status" and isinstance(old, dict):
        return old.get("status")
    return old


def _change(entity_id: uuid.UUID, name: str, value: Any) -> dict[str, Any]:
    if name == "status":
        return {"op": "set_status", "entity_id": entity_id, "status": value}
    if name == "kind":
        return {"op": "set_kind", "entity_id": entity_id, "kind": value}
    return {"op": "update_field", "entity_id": entity_id, "field": name, "value": value}


async def resync_entity(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID) -> None:
    """The Design Notes rule for one copied Entity (module docstring)."""
    entity = (await db.execute(scoped_select(Entity, ctx).where(Entity.id == entity_id).with_for_update()
                               .execution_options(populate_existing=True))).scalars().first()
    if entity is None or entity.deleted_at is not None or entity.merged_into_id is not None:
        return
    kind = "npc" if entity.legacy_npc_id is not None else "quest"
    page = _PAGE[kind]
    if kind == "npc":
        source = (await db.execute(scoped_select(NpcEntry, ctx).where(NpcEntry.id == entity.legacy_npc_id)
                                   .execution_options(populate_existing=True))).scalars().first()
    else:
        source = (await db.execute(scoped_select(Quest, ctx).where(Quest.id == entity.legacy_quest_id)
                                   .execution_options(populate_existing=True))).scalars().first()
    history = await _history(db, ctx, entity.id)

    if source is None:
        if history and all(r.op == "migrated" for r in history):
            await apply_change(db, ctx, {"op": "delete_entity", "entity_id": entity.id})
        else:
            await _note(db, ctx, entity.id,
                        f"Deleted on the old {page} page; kept because it was changed in World", history)
        return

    gm_only = str(_v(entity.visibility)) == "gm"
    by_field: dict[str, list[EntityChange]] = {}
    for row in history:
        if row.field is not None:
            by_field.setdefault(row.field, []).append(row)

    apply: list[tuple[str, Any, str, Any]] = []
    kept: list[str] = []
    if kind == "npc" and lw.npc_type(_v(source.role)) != entity.type:
        kept.append(f"role = {_v(source.role)}")
    for name, legacy_name, legacy, current, shown in _fields(kind, entity, source):
        if legacy == current:
            continue
        rows = by_field.get(name, [])
        if rows:
            if legacy != _base(rows[0], name):
                kept.append(f"{legacy_name} = {shown}")  # both sides changed it: the World wins
            continue
        if gm_only or name == "gm_notes":
            apply.append((name, legacy, legacy_name, shown))
        else:
            kept.append(f"{legacy_name} = {shown}")

    for name, legacy, legacy_name, shown in apply:
        try:
            await apply_change(db, ctx, _change(entity.id, name, legacy))
        except CanonChangeError as exc:
            logger.warning("legacy resync: %s %s field %s not applied (%s)", page, entity.id, name, exc.code)
            kept.append(f"{legacy_name} = {shown}")
            continue
        if kind == "quest" and name == "status" and legacy == "completed":
            completed_at = _iso(source.updated_at)
            try:
                await apply_change(db, ctx, {"op": "update_field", "entity_id": entity.id,
                                             "field": "attributes.completed_at", "value": completed_at})
            except CanonChangeError as exc:
                logger.warning("legacy resync: Quest %s completed_at not applied (%s)", entity.id, exc.code)
                kept.append(f"completed_at = {_quote(completed_at)}")
    if kept:
        note = f"Old {page} page edit not applied (World version kept): " + "; ".join(kept)
        await _note(db, ctx, entity.id, note, await _history(db, ctx, entity.id))


# ── One legacy row with no Entity ──────────────────────────────────────────

async def copy_legacy_row(db: AsyncSession, ctx: CampaignContext, kind: str, legacy_id: uuid.UUID) -> None:
    """A GM-only Entity for a legacy row created on the old page after the copy."""
    entity_id = lw.legacy_entity_id(kind, legacy_id)
    if kind == "npc":
        source = (await db.execute(scoped_select(NpcEntry, ctx).where(NpcEntry.id == legacy_id))).scalars().first()
        if source is None:
            return
        role = _v(source.role)
        entity_type = lw.npc_type(role)
        change = {"op": "create_entity", "entity_id": entity_id, "legacy_npc_id": legacy_id, "type": entity_type,
                  "kind": lw.npc_kind(role), "name": source.name, "description": source.description,
                  "gm_notes": source.notes, "status": lw.npc_status_in(entity_type, _v(source.status))}
    else:
        source = (await db.execute(scoped_select(Quest, ctx).where(Quest.id == legacy_id))).scalars().first()
        if source is None:
            return
        status = lw.quest_status_in(_v(source.status))
        change = {"op": "create_entity", "entity_id": entity_id, "legacy_quest_id": legacy_id, "type": lw.QUEST,
                  "name": source.title, "description": source.description, "gm_notes": source.notes,
                  "status": status,
                  "attributes": {"completed_at": _iso(source.updated_at)} if status == "completed" else {}}
    try:
        await apply_change(db, ctx, change)
    except CanonChangeError as exc:
        # e.g. a blank legacy name: the row stays on the (frozen) old table only.
        logger.warning("legacy resync: %s %s not copied (%s: %s)", kind, legacy_id, exc.code, exc.detail)


__all__ = ["BACKFILL_NAME", "KIND", "LEGACY_RESYNC", "PHASES", "copy_legacy_row", "handle", "resync_entity"]
