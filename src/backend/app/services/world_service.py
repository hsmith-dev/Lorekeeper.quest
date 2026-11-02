"""The one Canon write path (E0-WorldCore.3, AD-10, AD-13).

    change = await apply_change(db, ctx, SetStatus(entity_id=e.id, status="deceased"))
    undo = await revert_change(db, ctx, change.id)            # CanonChangeError("superseded") if touched since
    await db.commit()                                         # canon_changed runs after this

`apply_change(db, ctx, change)` is the only writer of `entities`,
`entity_aliases`, `entity_mentions`, `entity_relationships` and `quest_steps`.
`change` is a `CanonChange` (app/schemas/entities.py), or a dict of one.

**Who.** A writable GM user ctx may use every op except `merge`,
`source_deleted` and `migrated`. A system ctx is accepted only for `as_system("merge")` with
`merge`, and `as_system("entry_deleted")` with `remove_mention` or
`source_deleted`. Every other ctx (a Player, anon, a reduced ctx, a system ctx
with the wrong op) gets `not_found()` and nothing is written. Every row
written also passes `access.write.can_write` (E0-Access.6, when present) and
this module's own rule (a GM ctx of the row's Campaign).

**What.** In one savepoint each change validates its targets (looked up
through `scoped_select`), writes the owning table, appends exactly one
`entity_changes` row, marks the dependents of narrowing changes stale
(`access.mark_dependents_stale`, `RecordRef(kind="entity_field", id=entity)`)
and emits `canon_changed {campaign_id, refs: [entity ids], actor_ctx}`, which
the hook dispatcher delivers after the root commit (a rollback drops it). Any
error writes nothing: `CanonChangeError(code)` with code `not_found`
(missing, or another Campaign's), `merged`, `deleted`, `invalid_status`,
`invalid` (a bad field or value), `superseded` or `not_revertible`.

**History `field`** decides who may read the row (the registry's
`parent_field` rule): an Entity field uses its own name (`name`,
`description`, `status`, `kind`, `attributes.<key>`, `gm_notes`, `aliases`,
`quest_steps`); relationship, Mention, create, delete, merge and canon-note
rows use NULL, which is always GM; `field_visibility.<key>` rows are GM.

**Idempotent** (no new row; the earlier change is returned): re-adding an
alias or a Mention, confirming a confirmed Mention, ending an ended
Relationship (when no earlier row of that op made the state, e.g. it came
from the migration or a merge, the repeat is `invalid` and writes nothing),
`create_entity` with the `entity_id` of a live Entity of the same type and
name, and any op repeated with the same `proposal_id`, op, Entity, field and
payload (the same new value, note or target row).

**Quests.** `set_status` into a `closed_success` status stamps
`attributes.completed_at` (UTC ISO 8601); leaving it clears the stamp. A
Quest's status rows hold `{status, completed_at}`.

**Visibility.** `apply_change` never takes a Visibility value from a
CanonChange. `access.set_visibility` reaches it through the registry writer
registered below (kinds `entity` and `entity_relationship`), with a private
token: an Entity change is one `update_field` row (`visibility` or
`field_visibility.<key>`), an edge change one `update_relationship` row. A
`visibility_floor` path is 422. The only literal `visibility_floor` write is
the merge branch of `apply_change` (scripts/check_scoped_queries.py). The
only other floor value written is a revert of `remove_alias` /
`remove_mention`: it re-creates the row with its earlier `visibility_floor`
(a constructor restore), so a floored row never comes back unfloored.

**Revert.** `revert_change(db, ctx, change_id, force=False)` applies the
inverse through `apply_change(op=revert)`: one `revert` row with
`reverted_change_id`. A field change whose field no longer holds the row's
`new_value` (or a row change whose row is gone or changed) is `superseded`
unless `force=True`. Reverting `create_entity` soft-deletes the Entity.
`merge`, Visibility changes, `migrated`, `source_deleted`, `canon_note` and
reverts of non-field changes are `not_revertible`.

**Merge primitive** (`op=merge`, E0-WorldCore.9's wrapper calls it under
`as_system("merge")`): the absorbed Entity's aliases, Mentions and edges move
to the survivor, floored `gm`/`private` when the absorbed Entity is not
`party` (an existing floor that is already restrictive is kept); its name
becomes a survivor alias; self-loops are dropped; Quest steps move only when
that cannot widen them; `merged_into_id` is set and both are marked stale. Its
history stays on the absorbed Entity (moving it could widen GM-only history);
the one `merge` row is on the survivor.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Callable

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.access import (
    GM, CampaignContext, SystemReason, VisibilityError, mark_dependents_stale, not_found, register_visibility_kind,
    register_writer, registration, scoped_select,
)
from app.core.hooks import HookEvent, emit
from app.db.models.entity import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, QuestStep, RelationshipType,
)
from app.db.models.journal import JournalEntry
from app.domain import entity_types as et
from app.domain.enums import EntityChangeOp as Op
from app.domain.enums import EntityType, Visibility
from app.schemas.entities import (
    ATTRIBUTES_PREFIX, UPDATABLE_FIELDS, AddAlias, AddMention, AddQuestStep, AddRelationship, CanonNote,
    ConfirmMention, CreateEntity, DeleteEntity, EndRelationship, Merge, RemoveAlias, RemoveMention, Revert,
    SetKind, SetStatus, SourceDeleted, UpdateField, UpdateQuestStep, UpdateRelationship, parse_canon_change,
)
from app.schemas.sources import RecordRef

try:  # E0-Access.6's single write gate, once it is merged.
    from app.access.write import can_write as _can_write
except ImportError:  # pragma: no cover - depends on the merge order
    _can_write = None

logger = logging.getLogger(__name__)

STALE_KIND = "entity_field"  # derived_sources.ref_kind of an Entity's fields
DOMAIN = "entities"  # the campaign-events domain canon_changed publishes

# Fields a set_visibility call may hide on an Entity (field_visibility.<key>).
HIDEABLE_FIELDS = frozenset({"status", "description", "attributes"})
# Status and kind have their own ops; every other field-based row is update_field.
_FIELD_OPS = frozenset({Op.UPDATE_FIELD, Op.SET_STATUS, Op.SET_KIND})
_NOT_REVERTIBLE = frozenset({Op.MERGE, Op.MIGRATED, Op.SOURCE_DELETED, Op.CANON_NOTE})
_VISIBILITY_PREFIX = "field_visibility."
_VISIBILITY = "visibility"

# A system ctx may run only these ops (RC-6).
_SYSTEM_OPS: dict[SystemReason, frozenset[Op]] = {
    SystemReason.MERGE: frozenset({Op.MERGE}),
    SystemReason.ENTRY_DELETED: frozenset({Op.REMOVE_MENTION, Op.SOURCE_DELETED}),
}
_SYSTEM_ONLY = frozenset({Op.MERGE, Op.SOURCE_DELETED, Op.MIGRATED})


class CanonChangeError(Exception):
    """A change that cannot be applied; nothing was written."""

    CODES = frozenset({"invalid_status", "not_found", "merged", "deleted", "superseded", "not_revertible",
                       "invalid"})

    def __init__(self, code: str, detail: str | None = None) -> None:
        if code not in self.CODES:
            raise ValueError(f"CanonChangeError: unknown code {code!r}")
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


# ── Small helpers ──────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:  # a naive value is UTC, never the server's local time
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _json(value: Any) -> Any:
    """`value` as JSONB-ready data (UUIDs and datetimes as ISO strings)."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "value") and isinstance(getattr(value, "value"), str):  # a StrEnum
        return str(value.value)
    return value


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _alias_key(alias: str) -> str:
    """The stored `normalized_alias`: whitespace collapsed, casefolded.
    (E0-WorldCore.4's normalize_name replaces it.)"""
    return " ".join(alias.split()).casefold()


def _restrictive_floor(value: Any) -> bool:
    return value is not None and str(value) != Visibility.PARTY.value


def _is_field_based(name: str | None) -> bool:
    return name is not None and (name in UPDATABLE_FIELDS or name in ("status", "kind")
                                 or name.startswith(ATTRIBUTES_PREFIX))


def _is_visibility_row(row: EntityChange) -> bool:
    if row.field is not None and (row.field == _VISIBILITY or row.field.startswith(_VISIBILITY_PREFIX)):
        return True
    for value in (row.old_value, row.new_value):
        if isinstance(value, dict) and _VISIBILITY in value:
            return True
    return False


def _gate(ctx: CampaignContext, row: Any) -> None:
    """The module's own rule (a GM ctx of the row's Campaign), then can_write."""
    if ctx.role != GM or getattr(row, "campaign_id", None) != ctx.campaign_id:
        not_found()
    if _can_write is not None:
        _can_write(ctx, row)


def _check_ctx(ctx: Any) -> None:
    """The ctx shape every op needs, checked before the change is even parsed."""
    if (not isinstance(ctx, CampaignContext) or ctx.role != GM or ctx.read_only or ctx.user_id is None):
        not_found()


def _check_caller(ctx: Any, op: Op) -> None:
    _check_ctx(ctx)
    if ctx.is_system:
        if op not in _SYSTEM_OPS.get(ctx.system_reason, frozenset()):
            not_found()
    elif op in _SYSTEM_ONLY:
        not_found()


# ── The run: one change's bookkeeping ──────────────────────────────────────

@dataclass
class _Run:
    db: AsyncSession
    ctx: CampaignContext
    change: Any
    refs: list[uuid.UUID] = dc_field(default_factory=list)
    stale: list[uuid.UUID] = dc_field(default_factory=list)
    written: bool = False

    def ref(self, *ids: uuid.UUID) -> None:
        for i in ids:
            if i not in self.refs:
                self.refs.append(i)

    def narrow(self, *ids: uuid.UUID) -> None:
        for i in ids:
            if i not in self.stale:
                self.stale.append(i)

    async def first(self, stmt: sa.Select) -> Any:
        return (await self.db.execute(stmt.execution_options(populate_existing=True))).scalars().first()

    async def all(self, stmt: sa.Select) -> list[Any]:
        return list((await self.db.execute(stmt.execution_options(populate_existing=True))).scalars().all())

    def add(self, row: Any) -> Any:
        _gate(self.ctx, row)
        self.db.add(row)
        return row

    def touch(self, row: Any) -> Any:
        _gate(self.ctx, row)
        return row

    async def delete(self, row: Any) -> None:
        _gate(self.ctx, row)
        await self.db.delete(row)

    def history(self, entity_id: uuid.UUID, op: Op, field: str | None, old: Any, new: Any, *,
                reverted: uuid.UUID | None = None) -> EntityChange:
        c = self.change
        row = EntityChange(
            id=uuid.uuid4(), campaign_id=self.ctx.campaign_id, entity_id=entity_id, op=op.value, field=field,
            old_value=_json(old), new_value=_json(new),
            source_journal_id=getattr(c, "source_journal_id", None), proposal_id=getattr(c, "proposal_id", None),
            canon_note_id=getattr(c, "canon_note_id", None), actor_user_id=self.ctx.user_id,
            reverted_change_id=reverted,
            # The clock, not now() (the transaction's start): changes of one transaction keep their order.
            created_at=_now(),
        )
        self.add(row)
        self.written = True
        self.ref(entity_id)
        return row


# ── Lookups (all through scoped_select) ────────────────────────────────────

async def _entity(run: _Run, entity_id: Any, *, allow_deleted: bool = False, allow_merged: bool = False) -> Entity:
    row = await run.first(scoped_select(Entity, run.ctx).where(Entity.id == entity_id).with_for_update())
    if row is None:
        raise CanonChangeError("not_found", "No such Entity")
    if row.merged_into_id is not None and not allow_merged:
        raise CanonChangeError("merged", "This Entity was merged into another")
    if row.deleted_at is not None and not allow_deleted:
        raise CanonChangeError("deleted", "This Entity was deleted")
    return row


async def _row(run: _Run, model: type, row_id: Any, what: str) -> Any:
    row = await run.first(scoped_select(model, run.ctx).where(model.id == row_id).with_for_update())
    if row is None:
        raise CanonChangeError("not_found", f"No such {what}")
    return row


async def _journal(run: _Run, journal_id: Any) -> JournalEntry:
    row = await run.first(scoped_select(JournalEntry, run.ctx).where(JournalEntry.id == journal_id))
    if row is None:
        raise CanonChangeError("not_found", "No such journal entry")
    return row


async def _check_source(run: _Run) -> None:
    source = getattr(run.change, "source_journal_id", None)
    if source is not None:
        await _journal(run, source)


async def _repeat(run: _Run, op: Op, entity_id: uuid.UUID | None, field: str | None,
                  match: Callable[[EntityChange], bool] | None = None) -> EntityChange | None:
    """The earlier change of the same proposal, op, Entity and field (and `match`)."""
    proposal = getattr(run.change, "proposal_id", None)
    if proposal is None:
        return None
    stmt = scoped_select(EntityChange, run.ctx).where(
        EntityChange.proposal_id == proposal, EntityChange.op == op.value,
        EntityChange.field.is_not_distinct_from(field))
    if entity_id is not None:
        stmt = stmt.where(EntityChange.entity_id == entity_id)
    for row in await run.all(stmt.order_by(EntityChange.created_at, EntityChange.id)):
        if match is None or match(row):
            return row
    return None


async def _earlier(run: _Run, entity_id: uuid.UUID, ops: tuple[Op, ...],
                   match: Callable[[EntityChange], bool]) -> EntityChange | None:
    """The newest change of `entity_id` with one of `ops` that `match`es, else None."""
    rows = await run.all(scoped_select(EntityChange, run.ctx).where(
        EntityChange.entity_id == entity_id, EntityChange.op.in_([o.value for o in ops]))
        .order_by(EntityChange.created_at.desc(), EntityChange.id.desc()))
    for row in rows:
        if match(row):
            return row
    return None


def _already(what: str) -> CanonChangeError:
    """The state already holds but no earlier change of this op made it (a migration or merge did)."""
    return CanonChangeError("invalid", f"{what} already")


def _val(row: EntityChange, side: str, key: str) -> Any:
    value = row.new_value if side == "new" else row.old_value
    return value.get(key) if isinstance(value, dict) else None


# ── Field reads and writes (update_field, set_status, set_kind, revert) ────

def _read_field(entity: Entity, name: str) -> Any:
    """A field's current value, as its history rows hold it."""
    if name == "status" and entity.type == EntityType.QUEST.value:
        return {"status": entity.status, "completed_at": (entity.attributes or {}).get("completed_at")}
    if name.startswith(ATTRIBUTES_PREFIX):
        return _json((entity.attributes or {}).get(name[len(ATTRIBUTES_PREFIX):]))
    return _json(getattr(entity, name))


async def _check_ref(run: _Run, entity: Entity | None, entity_type: str, key: str, value: Any) -> None:
    """An ENTITY_REF attribute names a live Entity of this Campaign and an allowed type."""
    a = et.attribute(entity_type, key)
    if a.value_kind is not et.ValueKind.ENTITY_REF or value is None:
        return
    target = await run.first(scoped_select(Entity, run.ctx).where(Entity.id == uuid.UUID(str(value))))
    if (target is None or target.deleted_at is not None or target.merged_into_id is not None
            or target.type not in {t.value for t in a.target_types}
            or (entity is not None and target.id == entity.id)):
        raise CanonChangeError("invalid", f"{key} must name a live {'/'.join(t.value for t in a.target_types)} "
                                          "of this Campaign")


async def _checked_attributes(run: _Run, entity: Entity | None, entity_type: str,
                              attrs: dict[str, Any]) -> dict[str, Any]:
    try:
        checked = et.validate_attributes(entity_type, attrs)
    except ValueError as exc:
        raise CanonChangeError("invalid", str(exc)) from None
    for key, value in checked.items():
        await _check_ref(run, entity, entity_type, key, value)
    return checked


def _status(entity_type: str, status: Any) -> str:
    try:
        return et.validate_status(entity_type, status)
    except et.InvalidStatusError as exc:
        raise CanonChangeError("invalid_status", str(exc)) from None


def _quest_stamp(entity: Entity, new_status: str, attrs: dict[str, Any]) -> None:
    """Into closed_success: stamp completed_at (kept when already completed); out of it: clear it."""
    if et.status_category(entity.type, new_status) is et.StatusCategory.CLOSED_SUCCESS:
        was_success = (entity.status in et.statuses(entity.type)
                       and et.status_category(entity.type, entity.status) is et.StatusCategory.CLOSED_SUCCESS)
        if not (was_success and attrs.get("completed_at")):
            attrs["completed_at"] = _iso(_now())
    else:
        attrs.pop("completed_at", None)


async def _write_field(run: _Run, entity: Entity, name: str, value: Any, *, restore: bool = False) -> None:
    """Set one field-based value. `restore` writes a recorded Quest status dict as is."""
    if name == "status":
        attrs = dict(entity.attributes or {})
        if entity.type == EntityType.QUEST.value:
            if restore:
                recorded = value if isinstance(value, dict) else {"status": value, "completed_at": None}
                status = _status(entity.type, recorded.get("status"))
                if recorded.get("completed_at"):
                    attrs["completed_at"] = recorded["completed_at"]
                else:
                    attrs.pop("completed_at", None)
            else:
                status = _status(entity.type, value)
                _quest_stamp(entity, status, attrs)
            entity.attributes = attrs
        else:
            status = _status(entity.type, value)
        entity.status = status
    elif name == "kind":
        try:
            entity.kind = et.validate_kind(entity.type, value)
        except ValueError as exc:
            raise CanonChangeError("invalid", str(exc)) from None
    elif name == "name":
        if not isinstance(value, str) or not value.strip():
            raise CanonChangeError("invalid", "name must be non-empty text")
        entity.name = value
    elif name in ("description", "gm_notes"):
        if value is not None and not isinstance(value, str):
            raise CanonChangeError("invalid", f"{name} must be text")
        setattr(entity, name, value)
    elif name.startswith(ATTRIBUTES_PREFIX):
        key = name[len(ATTRIBUTES_PREFIX):]
        checked = await _checked_attributes(run, entity, entity.type, {key: value})
        attrs = dict(entity.attributes or {})
        if checked[key] is None:
            attrs.pop(key, None)
        else:
            attrs[key] = checked[key]
        entity.attributes = attrs
    else:
        raise CanonChangeError("invalid", f"{name!r} cannot be set")
    run.touch(entity)


# ── The ops ────────────────────────────────────────────────────────────────

def _snapshot(entity: Entity) -> dict[str, Any]:
    return {"type": entity.type, "kind": entity.kind, "name": entity.name, "description": entity.description,
            "status": entity.status, "attributes": dict(entity.attributes or {}), "gm_notes": entity.gm_notes}


async def _create_entity(run: _Run, c: CreateEntity) -> EntityChange:
    if c.entity_id is not None:
        existing = await run.first(scoped_select(Entity, run.ctx).where(Entity.id == c.entity_id))
        if existing is not None:
            same = (existing.type == c.type.value and existing.name == c.name and existing.deleted_at is None
                    and existing.merged_into_id is None)
            earlier = await _earlier(run, existing.id, (Op.CREATE_ENTITY,), lambda r: True) if same else None
            if earlier is not None:
                return earlier
            raise CanonChangeError("invalid", "This Entity id is taken")
    else:
        repeat = await _repeat(run, Op.CREATE_ENTITY, None, None,
                               lambda r: _val(r, "new", "name") == c.name and _val(r, "new", "type") == c.type.value)
        if repeat is not None:
            return repeat
    type_ = c.type.value
    try:
        kind = et.validate_kind(type_, c.kind)
    except ValueError as exc:
        raise CanonChangeError("invalid", str(exc)) from None
    status = _status(type_, c.status if c.status is not None else et.default_status(type_))
    attrs = await _checked_attributes(run, None, type_, dict(c.attributes))
    attrs = {k: v for k, v in attrs.items() if v is not None}
    if type_ == EntityType.QUEST.value:
        if et.status_category(type_, status) is et.StatusCategory.CLOSED_SUCCESS:
            attrs.setdefault("completed_at", _iso(_now()))
        else:
            attrs.pop("completed_at", None)
    entity = run.add(Entity(
        id=c.entity_id or uuid.uuid4(), campaign_id=run.ctx.campaign_id, type=type_,
        kind=kind.value if kind is not None else None, name=c.name, description=c.description, status=status,
        attributes=attrs, gm_notes=c.gm_notes, created_by_user_id=run.ctx.user_id,
    ))
    await run.db.flush()
    return run.history(entity.id, Op.CREATE_ENTITY, None, None, _snapshot(entity))


async def _field_change(run: _Run, op: Op, entity_id: uuid.UUID, name: str, value: Any) -> EntityChange:
    entity = await _entity(run, entity_id)
    requested = _json(value)
    if name.startswith(ATTRIBUTES_PREFIX):  # as stored: an ENTITY_REF is its canonical id
        key = name[len(ATTRIBUTES_PREFIX):]
        try:
            requested = _json(et.validate_attributes(entity.type, {key: value})[key])
        except ValueError:
            pass  # _write_field reports it
    repeat = await _repeat(run, op, entity.id, name, lambda r: (
        r.new_value == requested or (isinstance(r.new_value, dict) and r.new_value.get("status") == requested)))
    if repeat is not None:
        return repeat
    old = _read_field(entity, name)
    await _write_field(run, entity, name, value)
    return run.history(entity.id, op, name, old, _read_field(entity, name))


async def _update_field(run: _Run, c: UpdateField) -> EntityChange:
    return await _field_change(run, Op.UPDATE_FIELD, c.entity_id, c.field, c.value)


async def _set_status(run: _Run, c: SetStatus) -> EntityChange:
    return await _field_change(run, Op.SET_STATUS, c.entity_id, "status", c.status)


async def _set_kind(run: _Run, c: SetKind) -> EntityChange:
    return await _field_change(run, Op.SET_KIND, c.entity_id, "kind", c.kind.value)


async def _aliases(run: _Run, entity_id: uuid.UUID) -> list[EntityAlias]:
    return await run.all(scoped_select(EntityAlias, run.ctx).where(EntityAlias.entity_id == entity_id))


def _alias_matches(key: str, side: str) -> Callable[[EntityChange], bool]:
    return lambda r: isinstance(_val(r, side, "alias"), str) and _alias_key(_val(r, side, "alias")) == key


async def _add_alias(run: _Run, c: AddAlias) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    alias = " ".join(c.alias.split())
    key = _alias_key(alias)
    if not key:
        raise CanonChangeError("invalid", "An alias needs text")
    repeat = await _repeat(run, Op.ADD_ALIAS, entity.id, "aliases", _alias_matches(key, "new"))
    if repeat is not None:
        return repeat
    if any(a.normalized_alias == key for a in await _aliases(run, entity.id)):
        earlier = await _earlier(run, entity.id, (Op.ADD_ALIAS,), _alias_matches(key, "new"))
        if earlier is not None:
            return earlier
        raise _already("This alias exists")
    run.add(EntityAlias(campaign_id=run.ctx.campaign_id, entity_id=entity.id, alias=alias, normalized_alias=key))
    return run.history(entity.id, Op.ADD_ALIAS, "aliases", None, {"alias": alias})


async def _remove_alias(run: _Run, c: RemoveAlias) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    key = _alias_key(c.alias)
    # A floored remove wrote field NULL (below), so a repeat looks under both.
    repeat = (await _repeat(run, Op.REMOVE_ALIAS, entity.id, "aliases", _alias_matches(key, "old"))
              or await _repeat(run, Op.REMOVE_ALIAS, entity.id, None, _alias_matches(key, "old")))
    if repeat is not None:
        return repeat
    row = next((a for a in await _aliases(run, entity.id) if a.normalized_alias == key), None)
    if row is None:
        raise CanonChangeError("not_found", "No such alias")
    floor = row.visibility_floor
    await run.delete(row)
    run.narrow(entity.id)
    # A floored alias (from a merge) keeps its history GM: field NULL.
    return run.history(entity.id, Op.REMOVE_ALIAS, None if _restrictive_floor(floor) else "aliases",
                       {"alias": row.alias, "visibility_floor": _json(floor)}, None)


async def _relationship_type(run: _Run, type_id: uuid.UUID) -> RelationshipType:
    row = await run.first(scoped_select(RelationshipType, run.ctx).where(RelationshipType.id == type_id))
    if row is None:
        raise CanonChangeError("not_found", "No such relationship type")
    return row


def _edge_values(edge: EntityRelationship, names: tuple[str, ...]) -> dict[str, Any]:
    return {"relationship_id": edge.id, **{n: getattr(edge, n) for n in names}}


_EDGE_FIELDS = ("relationship_type_id", "note", "started_at")


async def _add_relationship(run: _Run, c: AddRelationship) -> EntityChange:
    source = await _entity(run, c.entity_id)
    target = await _entity(run, c.target_entity_id)
    if source.id == target.id:
        raise CanonChangeError("invalid", "A relationship needs two Entities")
    rel_type = await _relationship_type(run, c.relationship_type_id)
    repeat = await _repeat(run, Op.ADD_RELATIONSHIP, source.id, None, lambda r: (
        _val(r, "new", "target_entity_id") == str(target.id)
        and _val(r, "new", "relationship_type_id") == str(rel_type.id)))
    if repeat is not None:
        return repeat
    edge = run.add(EntityRelationship(
        id=uuid.uuid4(), campaign_id=run.ctx.campaign_id, source_entity_id=source.id, target_entity_id=target.id,
        relationship_type_id=rel_type.id, note=c.note, started_at=c.started_at,
        source_journal_id=c.source_journal_id,
    ))
    run.ref(target.id)
    return run.history(source.id, Op.ADD_RELATIONSHIP, None, None,
                       {"target_entity_id": target.id, **_edge_values(edge, _EDGE_FIELDS)})


async def _edge(run: _Run, edge_id: uuid.UUID) -> EntityRelationship:
    edge = await _row(run, EntityRelationship, edge_id, "relationship")
    await _entity(run, edge.source_entity_id)
    await _entity(run, edge.target_entity_id)
    run.ref(edge.target_entity_id)
    return edge


def _same_edge(edge_id: uuid.UUID) -> Callable[[EntityChange], bool]:
    return lambda r: _val(r, "new", "relationship_id") == str(edge_id) or _val(r, "old", "relationship_id") == str(
        edge_id)


async def _update_relationship(run: _Run, c: UpdateRelationship) -> EntityChange:
    edge = await _edge(run, c.relationship_id)
    names = tuple(n for n in _EDGE_FIELDS if n in c.model_fields_set)
    repeat = await _repeat(run, Op.UPDATE_RELATIONSHIP, edge.source_entity_id, None, _same_edge(edge.id))
    if repeat is not None:
        return repeat
    if "relationship_type_id" in names:
        await _relationship_type(run, c.relationship_type_id)
    old = _edge_values(edge, names)
    for name in names:
        setattr(edge, name, getattr(c, name))
    run.touch(edge)
    return run.history(edge.source_entity_id, Op.UPDATE_RELATIONSHIP, None, old, _edge_values(edge, names))


async def _end_relationship(run: _Run, c: EndRelationship) -> EntityChange:
    edge = await _edge(run, c.relationship_id)
    repeat = await _repeat(run, Op.END_RELATIONSHIP, edge.source_entity_id, None, _same_edge(edge.id))
    if repeat is not None:
        return repeat
    if edge.ended_at is not None:
        earlier = await _earlier(run, edge.source_entity_id, (Op.END_RELATIONSHIP,), _same_edge(edge.id))
        if earlier is not None:
            return earlier
        raise _already("This relationship has ended")
    old = _edge_values(edge, ("ended_at",))
    edge.ended_at = c.ended_at or _now()
    run.touch(edge)
    return run.history(edge.source_entity_id, Op.END_RELATIONSHIP, None, old, _edge_values(edge, ("ended_at",)))


def _step_values(step: QuestStep, names: tuple[str, ...]) -> dict[str, Any]:
    return {"step_id": step.id, **{n: getattr(step, n) for n in names}}


_STEP_FIELDS = ("text", "done", "position")


async def _quest(run: _Run, entity_id: uuid.UUID) -> Entity:
    quest = await _entity(run, entity_id)
    if quest.type != EntityType.QUEST.value:
        raise CanonChangeError("invalid", "Only a Quest has steps")
    return quest


async def _add_quest_step(run: _Run, c: AddQuestStep) -> EntityChange:
    quest = await _quest(run, c.entity_id)
    repeat = await _repeat(run, Op.ADD_QUEST_STEP, quest.id, "quest_steps", lambda r: _val(r, "new", "text") == c.text)
    if repeat is not None:
        return repeat
    position = c.position
    if position is None:
        steps = await run.all(scoped_select(QuestStep, run.ctx).where(QuestStep.quest_entity_id == quest.id))
        position = max((s.position for s in steps), default=-1) + 1
    step = run.add(QuestStep(
        id=uuid.uuid4(), campaign_id=run.ctx.campaign_id, quest_entity_id=quest.id, position=position, text=c.text,
        done=c.done, done_at=_now() if c.done else None, source_journal_id=c.source_journal_id,
    ))
    return run.history(quest.id, Op.ADD_QUEST_STEP, "quest_steps", None, _step_values(step, _STEP_FIELDS))


async def _step(run: _Run, step_id: uuid.UUID) -> tuple[QuestStep, Entity]:
    step = await _row(run, QuestStep, step_id, "quest step")
    return step, await _quest(run, step.quest_entity_id)


def _set_step(step: QuestStep, values: dict[str, Any]) -> None:
    for name, value in values.items():
        if name == "done":
            if bool(value) and not step.done:
                step.done_at = _now()
            elif not value:
                step.done_at = None
            step.done = bool(value)
        elif name in ("text", "position"):
            setattr(step, name, value)


async def _update_quest_step(run: _Run, c: UpdateQuestStep) -> EntityChange:
    step, quest = await _step(run, c.step_id)
    names = tuple(n for n in _STEP_FIELDS if n in c.model_fields_set)
    repeat = await _repeat(run, Op.UPDATE_QUEST_STEP, quest.id, "quest_steps",
                           lambda r: _val(r, "new", "step_id") == str(step.id))
    if repeat is not None:
        return repeat
    old = _step_values(step, names)
    _set_step(step, {n: getattr(c, n) for n in names})
    run.touch(step)
    return run.history(quest.id, Op.UPDATE_QUEST_STEP, "quest_steps", old, _step_values(step, names))


_MENTION_FIELDS = ("journal_id", "source_field", "span_start", "span_end", "confirmed")


def _mention_values(m: EntityMention, names: tuple[str, ...] = _MENTION_FIELDS) -> dict[str, Any]:
    return {"mention_id": m.id, **{n: getattr(m, n) for n in names}}


def _same_mention(mention_id: uuid.UUID) -> Callable[[EntityChange], bool]:
    return lambda r: (_val(r, "new", "mention_id") == str(mention_id)
                      or _val(r, "old", "mention_id") == str(mention_id))


async def _add_mention(run: _Run, c: AddMention) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    entry = await _journal(run, c.journal_id)
    existing = await run.first(scoped_select(EntityMention, run.ctx).where(
        EntityMention.entity_id == entity.id, EntityMention.journal_id == entry.id,
        EntityMention.source_field == c.source_field.value,
        EntityMention.span_start.is_not_distinct_from(c.span_start),
        EntityMention.span_end.is_not_distinct_from(c.span_end),
        EntityMention.quote.is_not_distinct_from(c.quote)))
    if existing is not None:
        earlier = await _earlier(run, entity.id, (Op.ADD_MENTION,), _same_mention(existing.id))
        if earlier is not None:
            return earlier
        raise _already("This Mention exists")
    mention = run.add(EntityMention(
        id=uuid.uuid4(), campaign_id=run.ctx.campaign_id, journal_id=entry.id, entity_id=entity.id, quote=c.quote,
        source_field=c.source_field.value, origin=c.origin.value, confirmed=c.confirmed, span_start=c.span_start,
        span_end=c.span_end,
    ))
    return run.history(entity.id, Op.ADD_MENTION, None, None, _mention_values(mention))


async def _mention(run: _Run, mention_id: uuid.UUID, *, allow_gone_entity: bool = False) -> EntityMention:
    mention = await _row(run, EntityMention, mention_id, "Mention")
    await _entity(run, mention.entity_id, allow_deleted=allow_gone_entity, allow_merged=allow_gone_entity)
    return mention


async def _confirm_mention(run: _Run, c: ConfirmMention) -> EntityChange:
    mention = await _mention(run, c.mention_id)
    repeat = await _repeat(run, Op.CONFIRM_MENTION, mention.entity_id, None, _same_mention(mention.id))
    if repeat is not None:
        return repeat
    if mention.confirmed:
        earlier = await _earlier(run, mention.entity_id, (Op.CONFIRM_MENTION, Op.ADD_MENTION),
                                 _same_mention(mention.id))
        if earlier is not None:
            return earlier
        raise _already("This Mention is confirmed")
    mention.confirmed = True
    run.touch(mention)
    return run.history(mention.entity_id, Op.CONFIRM_MENTION, None, _mention_values(mention, ()) | {
        "confirmed": False}, _mention_values(mention, ("confirmed",)))


async def _remove_mention(run: _Run, c: RemoveMention) -> EntityChange:
    # Journal delete (entry_deleted) removes the Mentions of deleted/merged Entities too.
    mention = await _mention(run, c.mention_id, allow_gone_entity=run.ctx.is_system)
    repeat = await _repeat(run, Op.REMOVE_MENTION, mention.entity_id, None, _same_mention(mention.id))
    if repeat is not None:
        return repeat
    old = _mention_values(mention) | {"quote": mention.quote, "origin": mention.origin,
                                      "visibility_floor": _json(mention.visibility_floor)}
    await run.delete(mention)
    run.narrow(mention.entity_id)
    return run.history(mention.entity_id, Op.REMOVE_MENTION, None, old, None)


async def _delete_entity(run: _Run, c: DeleteEntity) -> EntityChange:
    entity = await _entity(run, c.entity_id, allow_deleted=True, allow_merged=True)
    repeat = await _repeat(run, Op.DELETE_ENTITY, entity.id, None)
    if repeat is not None:
        return repeat
    await _entity(run, entity.id)  # now the liveness checks
    entity.deleted_at = _now()
    run.touch(entity)
    run.narrow(entity.id)
    return run.history(entity.id, Op.DELETE_ENTITY, None, {"deleted_at": None}, {"deleted_at": entity.deleted_at})


async def _source_deleted(run: _Run, c: SourceDeleted) -> EntityChange:
    entity = await _entity(run, c.entity_id, allow_deleted=True, allow_merged=True)
    journal_id = c.source_journal_id
    repeat = await _repeat(run, Op.SOURCE_DELETED, entity.id, c.field,
                           lambda r: _val(r, "new", "journal_id") == str(journal_id))
    if repeat is not None:
        return repeat
    now = _now()
    changes = sa.update(EntityChange).where(
        EntityChange.campaign_id == run.ctx.campaign_id, EntityChange.entity_id == entity.id,
        EntityChange.source_journal_id == journal_id, EntityChange.source_deleted_at.is_(None))
    if c.field is not None:
        changes = changes.where(EntityChange.field == c.field)
    flagged = (await run.db.execute(changes.values(source_deleted_at=now))).rowcount or 0
    if c.field is None:
        for model, column in ((QuestStep, QuestStep.quest_entity_id),
                              (EntityRelationship, EntityRelationship.source_entity_id),
                              (EntityRelationship, EntityRelationship.target_entity_id)):
            result = await run.db.execute(sa.update(model).where(
                model.campaign_id == run.ctx.campaign_id, column == entity.id, model.source_journal_id == journal_id,
                model.source_deleted_at.is_(None)).values(source_deleted_at=now))
            flagged += result.rowcount or 0
    current = _read_field(entity, c.field) if _is_field_based(c.field) else None
    return run.history(entity.id, Op.SOURCE_DELETED, c.field, None,
                       {"journal_id": journal_id, "field": c.field, "current_value": current, "flagged": flagged})


async def _canon_note(run: _Run, c: CanonNote) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    repeat = await _repeat(run, Op.CANON_NOTE, entity.id, None, lambda r: _val(r, "new", "note") == c.note)
    if repeat is not None:
        return repeat
    return run.history(entity.id, Op.CANON_NOTE, None, None, {"note": c.note})


# ── Merge (the primitive; the floors are written in apply_change) ──────────

@dataclass
class _MergePlan:
    change: EntityChange
    floors: list[tuple[Any, str]]


async def _merge(run: _Run, c: Merge) -> _MergePlan | EntityChange:
    absorbed = await _entity(run, c.entity_id, allow_deleted=True, allow_merged=True)
    survivor = await _entity(run, c.survivor_id, allow_deleted=True, allow_merged=True)
    repeat = await _repeat(run, Op.MERGE, survivor.id, None,
                           lambda r: _val(r, "new", "absorbed_id") == str(absorbed.id))
    if repeat is not None:
        return repeat
    absorbed = await _entity(run, absorbed.id)  # now the liveness checks
    survivor = await _entity(run, survivor.id)
    if absorbed.id == survivor.id:
        raise CanonChangeError("invalid", "An Entity cannot be merged into itself")
    if absorbed.type != survivor.type:
        raise CanonChangeError("invalid", "Only Entities of the same type merge")
    floor = None if absorbed.visibility == Visibility.PARTY.value else str(absorbed.visibility)
    floors: list[tuple[Any, str]] = []

    def floored(row: Any) -> None:
        if floor is not None and not _restrictive_floor(row.visibility_floor):
            floors.append((row, floor))

    keys = {a.normalized_alias for a in await _aliases(run, survivor.id)}
    moved = {"aliases": 0, "mentions": 0, "relationships": 0, "self_loops_dropped": 0, "quest_steps": 0}
    for alias in await _aliases(run, absorbed.id):
        if alias.normalized_alias in keys:
            await run.delete(alias)
            continue
        alias.entity_id = survivor.id
        run.touch(alias)
        floored(alias)
        keys.add(alias.normalized_alias)
        moved["aliases"] += 1
    name_key = _alias_key(absorbed.name)
    if name_key and name_key not in keys and name_key != _alias_key(survivor.name):
        floored(run.add(EntityAlias(campaign_id=run.ctx.campaign_id, entity_id=survivor.id,
                                    alias=" ".join(absorbed.name.split()), normalized_alias=name_key)))
    for mention in await run.all(scoped_select(EntityMention, run.ctx).where(EntityMention.entity_id == absorbed.id)):
        mention.entity_id = survivor.id
        run.touch(mention)
        floored(mention)
        moved["mentions"] += 1
    edges = await run.all(scoped_select(EntityRelationship, run.ctx).where(sa.or_(
        EntityRelationship.source_entity_id == absorbed.id, EntityRelationship.target_entity_id == absorbed.id)))
    for edge in edges:
        if edge.source_entity_id == absorbed.id:
            edge.source_entity_id = survivor.id
        if edge.target_entity_id == absorbed.id:
            edge.target_entity_id = survivor.id
        if edge.source_entity_id == edge.target_entity_id:
            await run.delete(edge)
            moved["self_loops_dropped"] += 1
            continue
        run.touch(edge)
        floored(edge)
        run.ref(edge.source_entity_id, edge.target_entity_id)
        moved["relationships"] += 1
    # Steps have no floor: they move only when that cannot widen them.
    if absorbed.visibility == Visibility.PARTY.value or survivor.visibility != Visibility.PARTY.value:
        for step in await run.all(scoped_select(QuestStep, run.ctx).where(QuestStep.quest_entity_id == absorbed.id)):
            step.quest_entity_id = survivor.id
            run.touch(step)
            moved["quest_steps"] += 1
    absorbed.merged_into_id = survivor.id
    run.touch(absorbed)
    run.narrow(survivor.id, absorbed.id)
    run.ref(absorbed.id)
    row = run.history(survivor.id, Op.MERGE, None, None,
                      {"absorbed_id": absorbed.id, "floor": floor, "moved": moved})
    return _MergePlan(row, floors)


# ── Visibility (only through the registry writer) ──────────────────────────

_TOKEN = object()


@dataclass(frozen=True)
class _VisibilityChange:
    """set_visibility's write, handed to apply_change by `_visibility_writer`."""

    model: type
    row_id: uuid.UUID
    path: str
    value: Visibility

    @property
    def op(self) -> str:
        return (Op.UPDATE_FIELD if self.model is Entity else Op.UPDATE_RELATIONSHIP).value


async def _visibility(run: _Run, c: _VisibilityChange) -> EntityChange:
    value = Visibility(c.value).value
    if c.model is Entity:
        entity = await _entity(run, c.row_id, allow_deleted=True, allow_merged=True)
        reg = registration(Entity)
        if c.path == _VISIBILITY:
            old = entity.visibility
            setattr(entity, reg.column, value)
        elif c.path.startswith(_VISIBILITY_PREFIX) and c.path[len(_VISIBILITY_PREFIX):] in HIDEABLE_FIELDS:
            key = c.path[len(_VISIBILITY_PREFIX):]
            per_field = dict(getattr(entity, reg.field_visibility) or {})
            old = per_field.get(key)
            per_field[key] = value
            setattr(entity, reg.field_visibility, per_field)  # a new dict: JSONB change tracking sees it
        else:
            raise VisibilityError("unknown_field", "This field cannot be hidden")
        run.touch(entity)
        return run.history(entity.id, Op.UPDATE_FIELD, c.path, _json(old), value)
    if c.path != _VISIBILITY:
        raise VisibilityError("merge_only", "Only a merge sets this")
    edge = await _edge(run, c.row_id)
    reg = registration(EntityRelationship)
    old = getattr(edge, reg.column)
    setattr(edge, reg.column, value)
    run.touch(edge)
    # Field NULL: an edge's Audience is not its source Entity's.
    return run.history(edge.source_entity_id, Op.UPDATE_RELATIONSHIP, None,
                       {"relationship_id": edge.id, _VISIBILITY: _json(old)},
                       {"relationship_id": edge.id, _VISIBILITY: value})


async def _visibility_writer(db: AsyncSession, ctx: CampaignContext, row: Any, path: str, value: Any) -> None:
    """The registry `writer` of `entities` and `entity_relationships`."""
    await apply_change(db, ctx, _VisibilityChange(type(row), row.id, path, Visibility(value)), _token=_TOKEN)


# ── Revert ─────────────────────────────────────────────────────────────────

def _superseded(force: bool) -> None:
    if not force:
        raise CanonChangeError("superseded", "A later change touched this")


async def _gone_is_superseded(lookup: Any) -> Any:
    """A target row that is gone is `superseded` (with force too: nothing to restore)."""
    try:
        return await lookup
    except CanonChangeError as exc:
        if exc.code == "not_found":
            raise CanonChangeError("superseded", "That row is gone") from None
        raise


async def _revert(run: _Run, c: Revert) -> EntityChange:
    target = await run.first(scoped_select(EntityChange, run.ctx).where(EntityChange.id == c.change_id))
    if target is None:
        raise CanonChangeError("not_found", "No such change")
    op = Op(target.op)
    if op in _NOT_REVERTIBLE or _is_visibility_row(target) or (op is Op.REVERT and not _is_field_based(target.field)):
        raise CanonChangeError("not_revertible", "This change cannot be reverted")
    repeat = await _repeat(run, Op.REVERT, target.entity_id, target.field,
                           lambda r: r.reverted_change_id == target.id)
    if repeat is not None:
        return repeat

    def done(old: Any, new: Any, entity_id: uuid.UUID = target.entity_id) -> EntityChange:
        return run.history(entity_id, Op.REVERT, target.field, old, new, reverted=target.id)

    if op in _FIELD_OPS or op is Op.REVERT:
        entity = await _entity(run, target.entity_id)
        current = _read_field(entity, target.field)
        if current != target.new_value:
            _superseded(c.force)
        await _write_field(run, entity, target.field, target.old_value, restore=True)
        return done(current, _read_field(entity, target.field))

    if op is Op.CREATE_ENTITY:
        entity = await _entity(run, target.entity_id, allow_deleted=True)
        if entity.deleted_at is not None:
            raise CanonChangeError("superseded", "This Entity is already deleted")
        entity.deleted_at = _now()
        run.touch(entity)
        run.narrow(entity.id)
        return done({"deleted_at": None}, {"deleted_at": entity.deleted_at})

    if op is Op.DELETE_ENTITY:
        entity = await _entity(run, target.entity_id, allow_deleted=True)
        if entity.deleted_at is None:
            raise CanonChangeError("superseded", "This Entity is not deleted")
        old = {"deleted_at": entity.deleted_at}
        entity.deleted_at = None
        run.touch(entity)
        return done(old, {"deleted_at": None})

    entity = await _entity(run, target.entity_id)
    if op is Op.ADD_ALIAS:
        key = _alias_key(str(_val(target, "new", "alias") or ""))
        row = next((a for a in await _aliases(run, entity.id) if a.normalized_alias == key), None)
        if row is None:
            raise CanonChangeError("superseded", "That alias is already gone")
        await run.delete(row)
        run.narrow(entity.id)
        return done({"alias": row.alias, "visibility_floor": _json(row.visibility_floor)}, None)
    if op is Op.REMOVE_ALIAS:
        alias = str(_val(target, "old", "alias") or "")
        key = _alias_key(alias)
        if not key or any(a.normalized_alias == key for a in await _aliases(run, entity.id)):
            raise CanonChangeError("superseded", "That alias is back already")
        run.add(EntityAlias(campaign_id=run.ctx.campaign_id, entity_id=entity.id, alias=alias, normalized_alias=key,
                            visibility_floor=_val(target, "old", "visibility_floor")))
        return done(None, {"alias": alias})
    if op is Op.ADD_RELATIONSHIP:
        edge = await run.first(scoped_select(EntityRelationship, run.ctx).where(
            EntityRelationship.id == uuid.UUID(str(_val(target, "new", "relationship_id")))))
        if edge is None:
            raise CanonChangeError("superseded", "That relationship is already gone")
        old = {"target_entity_id": edge.target_entity_id, **_edge_values(edge, _EDGE_FIELDS)}
        if _json(old) != target.new_value or edge.ended_at is not None:
            _superseded(c.force)
        await run.delete(edge)
        run.ref(edge.target_entity_id)
        run.narrow(edge.source_entity_id, edge.target_entity_id)
        return done(old, None)
    if op in (Op.UPDATE_RELATIONSHIP, Op.END_RELATIONSHIP):
        edge = await _gone_is_superseded(_edge(run, uuid.UUID(str(_val(target, "new", "relationship_id")))))
        names = tuple(k for k in (target.old_value or {}) if k != "relationship_id")
        if _json(_edge_values(edge, names)) != target.new_value:
            _superseded(c.force)
        current = _edge_values(edge, names)
        for name in names:
            raw = target.old_value[name]
            if name in ("started_at", "ended_at"):
                raw = _parse_dt(raw)
            elif name == "relationship_type_id" and raw is not None:
                raw = (await _relationship_type(run, uuid.UUID(str(raw)))).id
            setattr(edge, name, raw)
        run.touch(edge)
        return done(current, _edge_values(edge, names))
    if op is Op.ADD_QUEST_STEP:
        step = await run.first(scoped_select(QuestStep, run.ctx).where(
            QuestStep.id == uuid.UUID(str(_val(target, "new", "step_id")))))
        if step is None:
            raise CanonChangeError("superseded", "That step is already gone")
        old = _step_values(step, _STEP_FIELDS)
        if _json(old) != target.new_value:
            _superseded(c.force)
        await run.delete(step)
        run.narrow(entity.id)
        return done(old, None)
    if op is Op.UPDATE_QUEST_STEP:
        step, _quest_row = await _gone_is_superseded(_step(run, uuid.UUID(str(_val(target, "new", "step_id")))))
        names = tuple(k for k in (target.old_value or {}) if k != "step_id")
        if _json(_step_values(step, names)) != target.new_value:
            _superseded(c.force)
        current = _step_values(step, names)
        _set_step(step, {n: target.old_value[n] for n in names})
        run.touch(step)
        return done(current, _step_values(step, names))
    if op is Op.ADD_MENTION:
        mention = await run.first(scoped_select(EntityMention, run.ctx).where(
            EntityMention.id == uuid.UUID(str(_val(target, "new", "mention_id")))))
        if mention is None:
            raise CanonChangeError("superseded", "That Mention is already gone")
        old = _mention_values(mention)
        if _json(old) != target.new_value:
            _superseded(c.force)
        await run.delete(mention)
        run.narrow(mention.entity_id)
        return done(old, None)
    if op is Op.CONFIRM_MENTION:
        mention = await _gone_is_superseded(_mention(run, uuid.UUID(str(_val(target, "new", "mention_id")))))
        if not mention.confirmed:
            raise CanonChangeError("superseded", "That Mention is not confirmed")
        mention.confirmed = False
        run.touch(mention)
        return done(_mention_values(mention, ()) | {"confirmed": True}, _mention_values(mention, ("confirmed",)))
    if op is Op.REMOVE_MENTION:
        old = target.old_value or {}
        mention_id = uuid.UUID(str(old.get("mention_id")))
        if await run.first(scoped_select(EntityMention, run.ctx).where(EntityMention.id == mention_id)) is not None:
            raise CanonChangeError("superseded", "That Mention is back already")
        journal_id = old.get("journal_id")
        if journal_id is not None:
            try:
                await _journal(run, journal_id)
            except CanonChangeError:
                raise CanonChangeError("not_revertible", "Its journal entry is gone") from None
        mention = run.add(EntityMention(
            id=mention_id, campaign_id=run.ctx.campaign_id, journal_id=journal_id, entity_id=entity.id,
            quote=old.get("quote"), source_field=old.get("source_field"), origin=old.get("origin"),
            confirmed=bool(old.get("confirmed")), span_start=old.get("span_start"), span_end=old.get("span_end"),
            visibility_floor=old.get("visibility_floor"),
        ))
        return done(None, _mention_values(mention))
    raise CanonChangeError("not_revertible", "This change cannot be reverted")  # pragma: no cover


# ── Entry points ───────────────────────────────────────────────────────────

_HANDLERS: dict[Op, Callable[[_Run, Any], Any]] = {
    Op.CREATE_ENTITY: _create_entity,
    Op.UPDATE_FIELD: _update_field,
    Op.SET_STATUS: _set_status,
    Op.SET_KIND: _set_kind,
    Op.ADD_ALIAS: _add_alias,
    Op.REMOVE_ALIAS: _remove_alias,
    Op.ADD_RELATIONSHIP: _add_relationship,
    Op.UPDATE_RELATIONSHIP: _update_relationship,
    Op.END_RELATIONSHIP: _end_relationship,
    Op.ADD_QUEST_STEP: _add_quest_step,
    Op.UPDATE_QUEST_STEP: _update_quest_step,
    Op.ADD_MENTION: _add_mention,
    Op.CONFIRM_MENTION: _confirm_mention,
    Op.REMOVE_MENTION: _remove_mention,
    Op.DELETE_ENTITY: _delete_entity,
    Op.REVERT: _revert,
    Op.SOURCE_DELETED: _source_deleted,
    Op.CANON_NOTE: _canon_note,
}


async def apply_change(db: AsyncSession, ctx: CampaignContext, change: Any, *, _token: object = None) -> EntityChange:
    """Apply one CanonChange (or a dict of one) and return its history row
    (or, for an idempotent repeat, the earlier one). Does not commit. See the
    module docstring for who may call it and what it writes."""
    _check_ctx(ctx)  # a Player or anon gets the uniform 404 whatever it sent
    if isinstance(change, _VisibilityChange):
        if _token is not _TOKEN:
            raise CanonChangeError("invalid", "Visibility is changed only through access.set_visibility")
    else:
        try:
            change = parse_canon_change(change)
        except ValidationError as exc:
            raise CanonChangeError("invalid", str(exc.errors()[0].get("msg", "invalid change"))) from None
    op = Op(change.op)
    _check_caller(ctx, op)
    run = _Run(db, ctx, change)
    proposal = getattr(change, "proposal_id", None)
    if proposal is not None:
        # Held to the end of the transaction: a concurrent apply of the same
        # proposal waits here, then its _repeat sees this one's committed row.
        await db.execute(sa.select(sa.func.pg_advisory_xact_lock(
            sa.func.hashtextextended(f"canon_proposal:{proposal}", 0))))
    try:
        async with db.begin_nested():
            await _check_source(run)
            if isinstance(change, _VisibilityChange):
                result = await _visibility(run, change)
            elif op is Op.MERGE:
                plan = await _merge(run, change)
                if isinstance(plan, _MergePlan):
                    # The one literal visibility_floor write (AD-10, CI-8).
                    for row, floor in plan.floors:
                        row.visibility_floor = floor
                    result = plan.change
                else:
                    result = plan
            else:
                result = await _HANDLERS[op](run, change)
            await db.flush()
            if run.stale:
                await mark_dependents_stale(db, [RecordRef(kind=STALE_KIND, id=i) for i in run.stale])
            if run.written:
                emit(db, HookEvent.CANON_CHANGED, campaign_id=ctx.campaign_id, refs=list(run.refs), actor_ctx=ctx)
    except IntegrityError as exc:
        logger.info("apply_change refused by a constraint: %s", type(exc.orig).__name__ if exc.orig else "")
        raise CanonChangeError("invalid", "The change conflicts with the stored world") from None
    return result


async def revert_change(db: AsyncSession, ctx: CampaignContext, change_id: uuid.UUID, *,
                        force: bool = False) -> EntityChange:
    """Revert one change through `apply_change(op=revert)`; see the module docstring."""
    return await apply_change(db, ctx, Revert(change_id=change_id, force=force))


# ── Registrations ──────────────────────────────────────────────────────────

register_writer(Entity, _visibility_writer)
register_writer(EntityRelationship, _visibility_writer)
register_visibility_kind("entity", Entity)
register_visibility_kind("entity_relationship", EntityRelationship, options=(
    selectinload(EntityRelationship.source_entity), selectinload(EntityRelationship.target_entity)))


__all__ = ["CanonChangeError", "DOMAIN", "HIDEABLE_FIELDS", "STALE_KIND", "apply_change", "revert_change"]
