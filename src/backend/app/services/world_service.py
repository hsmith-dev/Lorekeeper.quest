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

**History `write_visibility`** (E0-WorldCore.5, owner decision round 4) is
the audience the row was written for, a registry floor on `entity_changes`.
After the op runs, each row it wrote is `party` only when its Entity was
loaded before the change and exists after it, and the row's field rule
(`audience_of(row, parents=[state], floor=False)`) is neither GM- nor
Owner-level for both the state just before and the state just after the
change; otherwise `gm` (fail closed). So a publish row (GM before) is `gm`,
an edit of a Party Entity's visible `name` is `party`, and an edit made
while `description` was hidden stays `gm` after it is un-hidden. A create
is `gm` (there is no before).

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
CanonChange. `HIDEABLE_FIELDS` are what `field_visibility.<key>` may hide:
`status`, `description`, `attributes` (the whole column) and `aliases`,
which also hides every alias row (the registry's `as_parent_field`) and the
alias history. `access.set_visibility` reaches it through the registry writer
registered below (kinds `entity` and `entity_relationship`), with a private
token: an Entity change is one `update_field` row (`visibility` or
`field_visibility.<key>`), an edge change one `update_relationship` row. A
`visibility_floor` path is 422. The only literal `visibility_floor` write is
in `apply_change`, for a handler result that is a `_MergePlan` (a merge, or a
merge's revert restoring the floors it replaced; scripts/check_scoped_queries.py).
The only other floor values written are constructor restores: a revert of
`remove_alias` / `remove_mention`, and a merge revert re-creating the rows the
merge deleted, each with its earlier `visibility_floor`, so a floored row
never comes back unfloored.

**Revert.** `revert_change(db, ctx, change_id, force=False)` applies the
inverse through `apply_change(op=revert)`: one `revert` row with
`reverted_change_id`. A field change whose field no longer holds the row's
`new_value` (or a row change whose row is gone or changed) is `superseded`
unless `force=True`. Reverting `create_entity` soft-deletes the Entity.
Reverting a `merge` (E0-WorldCore.9) un-merges it from the merge row's undo
record: `merged_into_id` back to NULL; the moved aliases, Mentions, edges
(with their old ends) and Quest steps back on the absorbed Entity with the
floors they had; the deleted duplicate aliases and self-loop edges re-created
with their ids and values; the added name alias deleted; the repointed
ENTITY_REF attributes put back; the survivor, the absorbed Entity and each
holder marked stale. A moved row that is gone or no longer on the survivor,
or a ref no longer naming the survivor, is `superseded` unless `force`
(which skips it); a merge reverted once already is `superseded` (its undo
record is stale), even with `force`; a survivor merged or deleted since is
`merged` / `deleted`. The revert row is on the survivor with field NULL (GM).
Visibility changes, `migrated`, `source_deleted`, `canon_note`, a merge
without an undo record and reverts of non-field changes are `not_revertible`.

**Names** (E0-WorldCore.4). Every alias key is `normalize_name(alias)`
(app/domain/names.py), recomputed from the stored surface form when compared;
"Brother Aldric" and "Aldric" are the same alias. The matchers
`match_names` and `candidates` (app/services/world_matching.py) are
re-exported here with `normalize_name` and `NAME_PREFIXES`.

**Merge primitive** (`op=merge`, under `as_system("merge")`): the pair is
locked in sorted-id order (ENTITY_REF holders are locked after it). The absorbed Entity's aliases, Mentions and edges move to the
survivor, floored `gm`/`private` when the absorbed Entity is not `party`;
a moved alias is floored by the stricter of that and the absorbed Entity's
`field_visibility.aliases` (an existing floor that is already restrictive is
kept). Its name becomes a survivor alias (floored like a Mention); duplicate
aliases and self-loops are dropped; Quest steps move only when that cannot
widen them. An ENTITY_REF attribute of another live Entity naming the
absorbed one is repointed to the survivor only when that cannot widen it
(the absorbed Entity was `party`, or the survivor is not), never to point an
Entity at itself; each holder is marked stale either way. The survivor's own
Visibility and fields are untouched and none of the absorbed Entity's field
values are copied. `merged_into_id` is set and both are marked stale. Its
history stays on the absorbed Entity (moving it could widen GM-only
history); the one `merge` row is on the survivor, field NULL (GM), and its
`new_value` holds `{absorbed_id, floor, moved, downgrades, warning, undo}`.

**The GM's merge** (E0-WorldCore.9): `merge_entities(db, ctx, survivor_id,
absorbed_id, *, preview=False)` (alias `merge`) is the only caller of
`as_system("merge")`: for a writable GM user ctx it runs one
`apply_change(op=merge)` and returns a `MergeResult{downgrades, moved_counts,
warning, ...}`; with `preview=True` it makes the same checks and returns the
same report plus the survivor's combined aliases, the Mention count and the
moved Relationships, and writes nothing. A merged-away id resolves to its
survivor through `access.resolve_merged` (the GET route and the
`entity_field` resolver).
"""
from __future__ import annotations

import json
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
    GM, AudienceLevel, CampaignContext, NotFound, SystemReason, VisibilityError, audience_of, mark_dependents_stale,
    not_found, project, register_resolver, register_visibility_kind, register_writer, registration, resolve_merged,
    scoped_select,
)
from app.access.projection import ENTITY_REF_KEYS, entity_ref_ids
from app.access.sources import QUOTE_MAX
from app.core.hooks import HookEvent, emit
from app.db.models.entity import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, QuestStep, RelationshipType,
)
from app.db.models.journal import JournalEntry
from app.domain import entity_types as et
from app.domain.names import NAME_PREFIXES, normalize_name
from app.domain.enums import EntityChangeOp as Op
from app.domain.enums import EntityType, Visibility
from app.schemas.entities import (
    ATTRIBUTES_PREFIX, UPDATABLE_FIELDS, AddAlias, AddMention, AddQuestStep, AddRelationship, CanonNote,
    ConfirmMention, CreateEntity, DeleteEntity, EndRelationship, Merge, RemoveAlias, RemoveMention, Revert,
    SetKind, SetStatus, SourceDeleted, UpdateField, UpdateQuestStep, UpdateRelationship, parse_canon_change,
)
from app.schemas.sources import RecordRef, SourceKind, SourceRef
from app.services.world_matching import NameCandidate, NameMatch, candidates, match_names

try:  # E0-Access.6's single write gate, once it is merged.
    from app.access.write import can_write as _can_write
except ImportError:  # pragma: no cover - depends on the merge order
    _can_write = None

logger = logging.getLogger(__name__)

STALE_KIND = "entity_field"  # derived_sources.ref_kind of an Entity's fields
DOMAIN = "entities"  # the campaign-events domain canon_changed publishes

# Fields a set_visibility call may hide on an Entity (field_visibility.<key>).
HIDEABLE_FIELDS = frozenset({"status", "description", "attributes", "aliases"})
# Status and kind have their own ops; every other field-based row is update_field.
_FIELD_OPS = frozenset({Op.UPDATE_FIELD, Op.SET_STATUS, Op.SET_KIND})
_NOT_REVERTIBLE = frozenset({Op.MIGRATED, Op.SOURCE_DELETED, Op.CANON_NOTE})
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
    # For write_visibility: each Entity as first loaded (a detached copy), the
    # live Entities after the op, and the history rows this run wrote.
    before: dict[uuid.UUID, Entity] = dc_field(default_factory=dict)
    after: dict[uuid.UUID, Entity] = dc_field(default_factory=dict)
    rows: list[EntityChange] = dc_field(default_factory=list)

    def loaded(self, entity: Entity) -> None:
        if entity.id not in self.before:
            self.before[entity.id] = _visibility_copy(entity)
        self.after[entity.id] = entity

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
            # GM until apply_change stamps it (_stamp_write_visibility).
            write_visibility=Visibility.GM.value,
        )
        self.add(row)
        self.rows.append(row)
        self.written = True
        self.ref(entity_id)
        return row


# ── Write-time visibility (E0-WorldCore.5) ─────────────────────────────────

def _visibility_copy(entity: Entity) -> Entity:
    """A detached copy of what an Entity's history-row Audience reads (never added to a session)."""
    return Entity(id=entity.id, campaign_id=entity.campaign_id, type=entity.type,
                  visibility=entity.visibility, field_visibility=dict(entity.field_visibility or {}),
                  created_by_user_id=entity.created_by_user_id, deleted_at=entity.deleted_at,
                  merged_into_id=entity.merged_into_id)


def _party_could_see(row: EntityChange, state: Entity) -> bool:
    aud = audience_of(row, parents=[state], floor=False)
    return aud.level not in (AudienceLevel.GM, AudienceLevel.OWNER)


def _stamp_write_visibility(run: _Run) -> None:
    """Each row this run wrote: `party` iff the Party could see its field both
    just before and just after the change, else `gm` (module docstring)."""
    for row in run.rows:
        before, after = run.before.get(row.entity_id), run.after.get(row.entity_id)
        party = (before is not None and after is not None
                 and _party_could_see(row, before) and _party_could_see(row, after))
        row.write_visibility = (Visibility.PARTY if party else Visibility.GM).value


# ── Lookups (all through scoped_select) ────────────────────────────────────

async def _entity(run: _Run, entity_id: Any, *, allow_deleted: bool = False, allow_merged: bool = False) -> Entity:
    row = await run.first(scoped_select(Entity, run.ctx).where(Entity.id == entity_id).with_for_update())
    if row is None:
        raise CanonChangeError("not_found", "No such Entity")
    run.loaded(row)
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
    run.after[entity.id] = entity  # no `before`: a create row is GM
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
    return lambda r: isinstance(_val(r, side, "alias"), str) and normalize_name(_val(r, side, "alias")) == key


async def _add_alias(run: _Run, c: AddAlias) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    alias = " ".join(c.alias.split())
    key = normalize_name(alias)
    if not key:
        raise CanonChangeError("invalid", "An alias needs text")
    repeat = await _repeat(run, Op.ADD_ALIAS, entity.id, "aliases", _alias_matches(key, "new"))
    if repeat is not None:
        return repeat
    if any(normalize_name(a.alias) == key for a in await _aliases(run, entity.id)):
        earlier = await _earlier(run, entity.id, (Op.ADD_ALIAS,), _alias_matches(key, "new"))
        if earlier is not None:
            return earlier
        raise _already("This alias exists")
    run.add(EntityAlias(campaign_id=run.ctx.campaign_id, entity_id=entity.id, alias=alias, normalized_alias=key))
    return run.history(entity.id, Op.ADD_ALIAS, "aliases", None, {"alias": alias})


async def _remove_alias(run: _Run, c: RemoveAlias) -> EntityChange:
    entity = await _entity(run, c.entity_id)
    key = normalize_name(c.alias)
    # A floored remove wrote field NULL (below), so a repeat looks under both.
    repeat = (await _repeat(run, Op.REMOVE_ALIAS, entity.id, "aliases", _alias_matches(key, "old"))
              or await _repeat(run, Op.REMOVE_ALIAS, entity.id, None, _alias_matches(key, "old")))
    if repeat is not None:
        return repeat
    row = next((a for a in await _aliases(run, entity.id) if normalize_name(a.alias) == key), None)
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
    """A handler result whose `visibility_floor` writes apply_change makes
    (a merge, and a merge's revert restoring the floors it replaced)."""

    change: EntityChange
    floors: list[tuple[Any, str | None]]


PARTY_WITH_GM_ONLY = "party_with_gm_only"  # MergeResult.warning
_FLOOR_RANK = {Visibility.PARTY.value: 0, Visibility.GM.value: 1, Visibility.PRIVATE.value: 2}


def _vis_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _stricter(*values: Any) -> str | None:
    """The most restrictive of some Visibility values as a floor (None: no floor)."""
    best, rank = None, 0
    for value in values:
        v = _vis_value(value)
        if v is None:
            continue
        r = _FLOOR_RANK.get(v, 1)
        if r > rank:
            best, rank = v, r
    return best


def _is_party(entity: Entity) -> bool:
    return _vis_value(entity.visibility) == Visibility.PARTY.value


def _aliases_hidden(entity: Entity) -> bool:
    return _restrictive_floor(_vis_value((entity.field_visibility or {}).get("aliases")))


def _ref_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value is not None else None
    except ValueError:
        return None


def _entity_ref_keys(entity_type: str) -> list[str]:
    """The ENTITY_REF attribute keys of one Entity type."""
    out = []
    for key in et.attribute_keys(entity_type):
        if key in ENTITY_REF_KEYS and et.attribute(entity_type, key).value_kind is et.ValueKind.ENTITY_REF:
            out.append(key)
    return out


def _check_live(entity: Entity) -> Entity:
    if entity.merged_into_id is not None:
        raise CanonChangeError("merged", "This Entity was merged into another")
    if entity.deleted_at is not None:
        raise CanonChangeError("deleted", "This Entity was deleted")
    return entity


async def _merge_pair(run: _Run, absorbed_id: uuid.UUID, survivor_id: uuid.UUID, *,
                      lock: bool = True) -> tuple[Entity, Entity]:
    """Both Entities, looked up (and with `lock`, locked FOR UPDATE) in
    sorted-id order: the pair is always locked in the same order."""
    rows: dict[uuid.UUID, Entity] = {}
    for entity_id in sorted({absorbed_id, survivor_id}):
        stmt = scoped_select(Entity, run.ctx).where(Entity.id == entity_id)
        row = await run.first(stmt.with_for_update() if lock else stmt)
        if row is None:
            raise CanonChangeError("not_found", "No such Entity")
        run.loaded(row)
        rows[entity_id] = row
    return rows[absorbed_id], rows[survivor_id]


def _check_mergeable(absorbed: Entity, survivor: Entity) -> None:
    _check_live(absorbed)
    _check_live(survivor)
    if absorbed.id == survivor.id:
        raise CanonChangeError("invalid", "An Entity cannot be merged into itself")
    if absorbed.type != survivor.type:
        raise CanonChangeError("invalid", "Only Entities of the same type merge")


@dataclass
class _MergeWork:
    """What a merge of `absorbed` into `survivor` does, read before anything
    is written (the merge executes it; a preview only reports it)."""

    absorbed: Entity
    survivor: Entity
    floor: str | None             # Mentions, edges and the name alias
    alias_floor: str | None       # moved aliases: also the absorbed `aliases` field
    move_aliases: list[EntityAlias]
    drop_aliases: list[EntityAlias]
    name_alias: str | None        # the absorbed name, when it becomes a survivor alias
    mentions: list[EntityMention]
    move_edges: list[tuple[EntityRelationship, uuid.UUID, uuid.UUID]]  # (edge, new source, new target)
    drop_edges: list[EntityRelationship]
    steps: list[QuestStep]
    ref_holders: list[Entity]     # live Entities with an ENTITY_REF naming the absorbed one
    repoint: list[tuple[Entity, str]]
    downgrades: list[dict[str, Any]]
    warning: str | None

    def moved(self) -> dict[str, int]:
        return {"aliases": len(self.move_aliases), "mentions": len(self.mentions),
                "relationships": len(self.move_edges), "self_loops_dropped": len(self.drop_edges),
                "quest_steps": len(self.steps), "attribute_refs": len(self.repoint),
                "attribute_refs_left": self.refs_left()}

    def refs_left(self) -> int:
        """Holder/key pairs naming the absorbed Entity that stay on its id (not safe to repoint)."""
        repointed = {(h.id, k) for h, k in self.repoint}
        return sum(1 for h in self.ref_holders for k in _entity_ref_keys(h.type)
                   if _ref_uuid((h.attributes or {}).get(k)) == self.absorbed.id and (h.id, k) not in repointed)


async def _merge_work(run: _Run, absorbed: Entity, survivor: Entity, *, lock: bool) -> _MergeWork:
    floor = None if _is_party(absorbed) else _vis_value(absorbed.visibility)
    alias_floor = _stricter(floor, (absorbed.field_visibility or {}).get("aliases"))

    keys = {normalize_name(a.alias) for a in await _aliases(run, survivor.id)}
    move_aliases, drop_aliases = [], []
    for alias in sorted(await _aliases(run, absorbed.id), key=lambda a: (a.alias, str(a.id))):
        alias_key = normalize_name(alias.alias)
        if alias_key in keys:
            drop_aliases.append(alias)
            continue
        move_aliases.append(alias)
        keys.add(alias_key)
    name_key = normalize_name(absorbed.name)
    name_alias = None
    if name_key and name_key not in keys and name_key != normalize_name(survivor.name):
        name_alias = " ".join(absorbed.name.split())

    mentions = await run.all(scoped_select(EntityMention, run.ctx).where(EntityMention.entity_id == absorbed.id)
                             .order_by(EntityMention.id))
    move_edges, drop_edges = [], []
    for edge in await run.all(scoped_select(EntityRelationship, run.ctx).where(sa.or_(
            EntityRelationship.source_entity_id == absorbed.id,
            EntityRelationship.target_entity_id == absorbed.id)).order_by(EntityRelationship.id)):
        source = survivor.id if edge.source_entity_id == absorbed.id else edge.source_entity_id
        target = survivor.id if edge.target_entity_id == absorbed.id else edge.target_entity_id
        if source == target:
            drop_edges.append(edge)
        else:
            move_edges.append((edge, source, target))
    # Steps have no floor: they move only when that cannot widen them.
    steps: list[QuestStep] = []
    if _is_party(absorbed) or not _is_party(survivor):
        steps = await run.all(scoped_select(QuestStep, run.ctx).where(QuestStep.quest_entity_id == absorbed.id)
                              .order_by(QuestStep.id))

    # ENTITY_REF attributes of other live Entities that name the absorbed one.
    holders: list[Entity] = []
    repoint: list[tuple[Entity, str]] = []
    if ENTITY_REF_KEYS:
        stmt = scoped_select(Entity, run.ctx).where(
            Entity.id != absorbed.id, Entity.deleted_at.is_(None), Entity.merged_into_id.is_(None),
            sa.or_(*[Entity.attributes[k].astext == str(absorbed.id) for k in sorted(ENTITY_REF_KEYS)]),
        ).order_by(Entity.id)
        # Repointing it cannot widen what the Party sees (the survivor's id is shown only where the absorbed one was).
        safe = _is_party(absorbed) or not _is_party(survivor)
        for holder in await run.all(stmt.with_for_update() if lock else stmt):
            keys_here = [k for k in _entity_ref_keys(holder.type)
                         if _ref_uuid((holder.attributes or {}).get(k)) == absorbed.id]
            if not keys_here:
                continue
            holders.append(holder)
            if safe and holder.id != survivor.id:  # never a ref of the survivor to itself
                repoint.extend((holder, k) for k in keys_here)

    # Downgrades (entity-level, MergeResult): the row's Party audience before vs on the survivor.
    downgrades: list[dict[str, Any]] = []

    def report(kind: str, row: Any, before: bool, after: bool, level: str | None) -> None:
        # A row already floored was never Party-visible on either side.
        if before != after and not _restrictive_floor(row.visibility_floor):
            downgrades.append({"kind": kind, "id": row.id, "from": Visibility.PARTY.value,
                               "to": level or Visibility.GM.value})

    alias_before = _is_party(absorbed) and not _aliases_hidden(absorbed)
    alias_after = _is_party(survivor) and not _aliases_hidden(survivor)
    for alias in move_aliases:
        report("alias", alias, alias_before, alias_after, alias_floor)
    for mention in mentions:
        report("mention", mention, _is_party(absorbed), _is_party(survivor), floor)
    for edge, _source, _target in move_edges:
        report("relationship", edge, _is_party(absorbed), _is_party(survivor), floor)
    warning = PARTY_WITH_GM_ONLY if _is_party(absorbed) != _is_party(survivor) else None
    return _MergeWork(absorbed, survivor, floor, alias_floor, move_aliases, drop_aliases, name_alias, mentions,
                      move_edges, drop_edges, steps, holders, repoint, downgrades, warning)


def _alias_record(alias: EntityAlias) -> dict[str, Any]:
    return {"id": alias.id, "alias": alias.alias, "normalized_alias": alias.normalized_alias,
            "visibility_floor": _json(alias.visibility_floor)}


def _edge_record(edge: EntityRelationship) -> dict[str, Any]:
    return {"id": edge.id, "source_entity_id": edge.source_entity_id, "target_entity_id": edge.target_entity_id,
            "relationship_type_id": edge.relationship_type_id, "note": edge.note,
            "visibility": _json(edge.visibility), "visibility_floor": _json(edge.visibility_floor),
            "source_journal_id": edge.source_journal_id, "source_deleted_at": edge.source_deleted_at,
            "started_at": edge.started_at, "ended_at": edge.ended_at}


async def _merge(run: _Run, c: Merge) -> _MergePlan | EntityChange:
    absorbed, survivor = await _merge_pair(run, c.entity_id, c.survivor_id)
    repeat = await _repeat(run, Op.MERGE, survivor.id, None,
                           lambda r: _val(r, "new", "absorbed_id") == str(absorbed.id))
    if repeat is not None:
        return repeat
    _check_mergeable(absorbed, survivor)  # now the liveness checks
    work = await _merge_work(run, absorbed, survivor, lock=True)
    floors: list[tuple[Any, str | None]] = []

    def floored(row: Any, floor: str | None) -> None:
        if floor is not None and not _restrictive_floor(row.visibility_floor):
            floors.append((row, floor))

    # The undo record (revert_change un-merges from it): each moved row with
    # its floor (and an edge with its ends) before the merge, the deleted rows
    # in full, the added name alias, the moved steps and the repointed refs.
    undo: dict[str, Any] = {"aliases": [], "mentions": [], "relationships": [], "dropped_aliases": [],
                            "dropped_relationships": [], "name_alias_id": None, "quest_steps": [],
                            "attribute_refs": []}
    for alias in work.drop_aliases:
        undo["dropped_aliases"].append(_alias_record(alias))
        await run.delete(alias)
    for alias in work.move_aliases:
        undo["aliases"].append({"id": alias.id, "floor": _json(alias.visibility_floor),
                                "normalized_alias": alias.normalized_alias})
        alias.entity_id = survivor.id
        alias.normalized_alias = normalize_name(alias.alias)
        run.touch(alias)
        floored(alias, work.alias_floor)
    if work.name_alias is not None:
        name_row = run.add(EntityAlias(id=uuid.uuid4(), campaign_id=run.ctx.campaign_id, entity_id=survivor.id,
                                       alias=work.name_alias, normalized_alias=normalize_name(work.name_alias)))
        floored(name_row, work.floor)
        undo["name_alias_id"] = name_row.id
    for mention in work.mentions:
        undo["mentions"].append({"id": mention.id, "floor": _json(mention.visibility_floor)})
        mention.entity_id = survivor.id
        run.touch(mention)
        floored(mention, work.floor)
    for edge in work.drop_edges:
        undo["dropped_relationships"].append(_edge_record(edge))
        await run.delete(edge)
    for edge, source, target in work.move_edges:
        undo["relationships"].append({"id": edge.id, "floor": _json(edge.visibility_floor),
                                      "source_entity_id": edge.source_entity_id,
                                      "target_entity_id": edge.target_entity_id})
        edge.source_entity_id, edge.target_entity_id = source, target
        run.touch(edge)
        floored(edge, work.floor)
        run.ref(source, target)
    for step in work.steps:
        undo["quest_steps"].append(step.id)
        step.quest_entity_id = survivor.id
        run.touch(step)
    for holder, key in work.repoint:
        attrs = dict(holder.attributes or {})
        attrs[key] = str(survivor.id)
        holder.attributes = attrs  # a new dict: JSONB change tracking sees it
        run.touch(holder)
        run.ref(holder.id)
        undo["attribute_refs"].append({"entity_id": holder.id, "key": key})
    absorbed.merged_into_id = survivor.id
    run.touch(absorbed)
    run.narrow(survivor.id, absorbed.id, *(h.id for h in work.ref_holders))
    run.ref(absorbed.id)
    row = run.history(survivor.id, Op.MERGE, None, None, {
        "absorbed_id": absorbed.id, "floor": work.floor, "moved": work.moved(), "downgrades": work.downgrades,
        "warning": work.warning, "undo": undo})
    return _MergePlan(row, floors)


async def _revert_merge(run: _Run, c: Revert, target: EntityChange) -> _MergePlan:
    """Un-merge from the merge row's undo record (module docstring, Revert)."""
    new = target.new_value if isinstance(target.new_value, dict) else {}
    undo = new.get("undo")
    absorbed_id = _ref_uuid(new.get("absorbed_id"))
    if not isinstance(undo, dict) or absorbed_id is None:
        raise CanonChangeError("not_revertible", "This merge has no undo record")
    # Reverted once already: its undo record is stale (the pair may have been merged again since).
    if await run.first(scoped_select(EntityChange, run.ctx).where(EntityChange.reverted_change_id == target.id)):
        raise CanonChangeError("superseded", "This merge was reverted already")
    absorbed, survivor = await _merge_pair(run, absorbed_id, target.entity_id)
    _check_live(survivor)  # merged or deleted since: `merged` / `deleted`
    if absorbed.merged_into_id != survivor.id:
        raise CanonChangeError("superseded", "This Entity is no longer merged into the survivor")
    floors: list[tuple[Any, str | None]] = []
    skipped = 0

    def touched() -> None:
        nonlocal skipped
        _superseded(c.force)  # force: skip it
        skipped += 1

    async def locked(model: type, row_id: Any) -> Any:
        rid = _ref_uuid(row_id)
        if rid is None:
            return None
        return await run.first(scoped_select(model, run.ctx).where(model.id == rid).with_for_update())

    for item in undo.get("aliases") or []:
        alias = await locked(EntityAlias, item.get("id"))
        if alias is None or alias.entity_id != survivor.id:
            touched()
            continue
        alias.entity_id = absorbed.id
        if item.get("normalized_alias"):
            alias.normalized_alias = item["normalized_alias"]
        run.touch(alias)
        floors.append((alias, item.get("floor")))
    for item in undo.get("mentions") or []:
        mention = await locked(EntityMention, item.get("id"))
        if mention is None or mention.entity_id != survivor.id:
            touched()
            continue
        mention.entity_id = absorbed.id
        run.touch(mention)
        floors.append((mention, item.get("floor")))
    for item in undo.get("relationships") or []:
        edge = await locked(EntityRelationship, item.get("id"))
        source, target_end = _ref_uuid(item.get("source_entity_id")), _ref_uuid(item.get("target_entity_id"))
        expected = (survivor.id if source == absorbed.id else source,
                    survivor.id if target_end == absorbed.id else target_end)
        if edge is None or (edge.source_entity_id, edge.target_entity_id) != expected:
            touched()
            continue
        edge.source_entity_id, edge.target_entity_id = source, target_end
        run.touch(edge)
        floors.append((edge, item.get("floor")))
        run.ref(source, target_end)
    for step_id in undo.get("quest_steps") or []:
        step = await locked(QuestStep, step_id)
        if step is None or step.quest_entity_id != survivor.id:
            touched()
            continue
        step.quest_entity_id = absorbed.id
        run.touch(step)
    name_alias = await locked(EntityAlias, undo.get("name_alias_id")) if undo.get("name_alias_id") else None
    if undo.get("name_alias_id"):
        if name_alias is None or name_alias.entity_id != survivor.id:
            touched()
        else:
            await run.delete(name_alias)
    absorbed_keys = {normalize_name(a.alias) for a in await _aliases(run, absorbed.id)}
    for item in undo.get("dropped_aliases") or []:
        key = normalize_name(str(item.get("alias") or ""))
        if not key or key in absorbed_keys or await locked(EntityAlias, item.get("id")) is not None:
            touched()
            continue
        # A constructor restore: the row comes back with the floor it had.
        run.add(EntityAlias(id=_ref_uuid(item.get("id")), campaign_id=run.ctx.campaign_id, entity_id=absorbed.id,
                            alias=item.get("alias"), normalized_alias=item.get("normalized_alias") or key,
                            visibility_floor=item.get("visibility_floor")))
        absorbed_keys.add(key)
    for item in undo.get("dropped_relationships") or []:
        if await locked(EntityRelationship, item.get("id")) is not None:
            touched()
            continue
        type_id = _ref_uuid(item.get("relationship_type_id"))
        rel_type = await run.first(scoped_select(RelationshipType, run.ctx).where(RelationshipType.id == type_id))
        if rel_type is None:
            touched()
            continue
        journal_id = _ref_uuid(item.get("source_journal_id"))
        if journal_id is not None and await run.first(
                scoped_select(JournalEntry, run.ctx).where(JournalEntry.id == journal_id)) is None:
            journal_id = None  # the entry is gone (SET NULL, like any edge of it)
        run.add(EntityRelationship(
            id=_ref_uuid(item.get("id")), campaign_id=run.ctx.campaign_id,
            source_entity_id=_ref_uuid(item.get("source_entity_id")),
            target_entity_id=_ref_uuid(item.get("target_entity_id")), relationship_type_id=rel_type.id,
            note=item.get("note"), visibility=item.get("visibility") or Visibility.GM.value,
            visibility_floor=item.get("visibility_floor"), source_journal_id=journal_id,
            source_deleted_at=_parse_dt(item.get("source_deleted_at")), started_at=_parse_dt(item.get("started_at")),
            ended_at=_parse_dt(item.get("ended_at")),
        ))
    holders: list[uuid.UUID] = []
    for item in undo.get("attribute_refs") or []:
        holder = await locked(Entity, item.get("entity_id"))
        key = item.get("key")
        if holder is None or not isinstance(key, str) or _ref_uuid((holder.attributes or {}).get(key)) != survivor.id:
            touched()
            continue
        attrs = dict(holder.attributes or {})
        attrs[key] = str(absorbed.id)
        holder.attributes = attrs
        run.touch(holder)
        run.ref(holder.id)
        holders.append(holder.id)
    absorbed.merged_into_id = None
    run.touch(absorbed)
    run.narrow(survivor.id, absorbed.id, *holders)
    run.ref(survivor.id, absorbed.id)
    row = run.history(survivor.id, Op.REVERT, None, {"absorbed_id": absorbed.id, "merged_into_id": survivor.id},
                      {"absorbed_id": absorbed.id, "merged_into_id": None, "skipped": skipped},
                      reverted=target.id)
    return _MergePlan(row, floors)


# ── The GM's merge (E0-WorldCore.9) ────────────────────────────────────────

@dataclass
class MergeResult:
    """What `merge_entities` did (or, with `preview`, would do).

    `downgrades` are `{kind, id, from, to}` for each moved alias, Mention or
    Relationship whose Party audience differs before the merge and on the
    survivor; `warning` is `"party_with_gm_only"` when exactly one of the two
    is `party`. `change_id` is the merge row (None for a preview). A preview
    also gives the survivor's `aliases` after the merge, the moved
    `mention_count` and the moved `relationships` (with their new ends)."""

    survivor_id: uuid.UUID
    absorbed_id: uuid.UUID
    change_id: uuid.UUID | None
    downgrades: list[dict[str, Any]]
    moved_counts: dict[str, int]
    warning: str | None
    aliases: list[str] | None = None
    mention_count: int | None = None
    relationships: list[dict[str, Any]] | None = None


def _merge_id(value: Any) -> uuid.UUID:
    found = _ref_uuid(value)
    if found is None:
        raise CanonChangeError("not_found", "No such Entity")
    return found


async def merge_entities(db: AsyncSession, ctx: CampaignContext, survivor_id: Any, absorbed_id: Any, *,
                         preview: bool = False) -> MergeResult:
    """Merge `absorbed_id` into `survivor_id` for a GM: one
    `apply_change(op=merge)` under `ctx.as_system("merge")`, or with
    `preview=True` the same checks and report with nothing written. Does
    not commit. Errors are apply_change's: `not_found` (missing, another
    Campaign's, or a non-GM ctx), `merged`, `deleted`, `invalid` (self or a
    type mismatch)."""
    _check_ctx(ctx)  # a Player, anon or reduced ctx: the uniform 404
    if ctx.is_system:
        not_found()
    survivor_uuid, absorbed_uuid = _merge_id(survivor_id), _merge_id(absorbed_id)
    if preview:
        run = _Run(db, ctx, Merge(entity_id=absorbed_uuid, survivor_id=survivor_uuid))
        absorbed, survivor = await _merge_pair(run, absorbed_uuid, survivor_uuid, lock=False)
        _check_mergeable(absorbed, survivor)
        work = await _merge_work(run, absorbed, survivor, lock=False)
        aliases = sorted({a.alias for a in await _aliases(run, survivor.id)} | {a.alias for a in work.move_aliases}
                         | ({work.name_alias} if work.name_alias else set()), key=lambda s: (s.lower(), s))
        return MergeResult(
            survivor_id=survivor.id, absorbed_id=absorbed.id, change_id=None, downgrades=work.downgrades,
            moved_counts=work.moved(), warning=work.warning, aliases=aliases, mention_count=len(work.mentions),
            relationships=[{"id": e.id, "source_entity_id": s, "target_entity_id": t,
                            "relationship_type_id": e.relationship_type_id} for e, s, t in work.move_edges])
    try:
        system = ctx.as_system("merge")
    except ValueError:
        not_found()
    row = await apply_change(db, system, Merge(entity_id=absorbed_uuid, survivor_id=survivor_uuid))
    new = row.new_value if isinstance(row.new_value, dict) else {}
    return MergeResult(
        survivor_id=row.entity_id, absorbed_id=absorbed_uuid, change_id=row.id,
        downgrades=list(new.get("downgrades") or []), moved_counts=dict(new.get("moved") or {}),
        warning=new.get("warning"))


merge = merge_entities  # the story's name for it


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


async def _revert(run: _Run, c: Revert) -> _MergePlan | EntityChange:
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
    if op is Op.MERGE:
        return await _revert_merge(run, c, target)

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
        key = normalize_name(str(_val(target, "new", "alias") or ""))
        row = next((a for a in await _aliases(run, entity.id) if normalize_name(a.alias) == key), None)
        if row is None:
            raise CanonChangeError("superseded", "That alias is already gone")
        await run.delete(row)
        run.narrow(entity.id)
        return done({"alias": row.alias, "visibility_floor": _json(row.visibility_floor)}, None)
    if op is Op.REMOVE_ALIAS:
        alias = str(_val(target, "old", "alias") or "")
        key = normalize_name(alias)
        if not key or any(normalize_name(a.alias) == key for a in await _aliases(run, entity.id)):
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
    Op.MERGE: _merge,
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
            else:
                result = await _HANDLERS[op](run, change)
            if isinstance(result, _MergePlan):
                # The one literal visibility_floor write (AD-10, CI-8): a
                # merge's floors, or a merge revert restoring the earlier ones.
                for row, floor in result.floors:
                    row.visibility_floor = floor
                result = result.change
            _stamp_write_visibility(run)
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


# ── The entity_field source resolver ───────────────────────────────────────

def _field_label(entity: Entity, name: str) -> str:
    if name.startswith(ATTRIBUTES_PREFIX):
        key = name[len(ATTRIBUTES_PREFIX):]
        try:
            return et.attribute(entity.type, key).label
        except ValueError:
            return key.replace("_", " ").capitalize()
    return name.replace("_", " ").capitalize()


def _quote_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


async def resolve_entity_field(entity: Entity, ref: SourceRef, ctx: CampaignContext,
                               db: AsyncSession) -> tuple[str, str] | None:
    """`SourceRef(kind="entity_field", id=<Entity>, field=...)` as `("<name> · <label>",
    quote)`. `access.resolve_sources` has already checked that ctx may see the
    Entity and the field; the quote is the field's value as `access.project`
    renders it for ctx (a hidden field as unset), truncated to QUOTE_MAX. None
    (the ref is dropped) for an `attributes.<key>` the Entity's type does not
    define and for one with no value in ctx's projection (unset, hidden, or an
    ENTITY_REF naming an Entity ctx may not see: indistinguishable).
    `field=None` (the whole record, GM only) quotes the description.
    A merged-away Entity (E0-WorldCore.9) is followed to its survivor
    (`access.resolve_merged`) for a GM only; the citation then carries the
    survivor's name and value. Anyone else's ref to it is dropped."""
    if entity.merged_into_id is not None:
        if ctx.role != GM:
            return None
        try:
            entity = await resolve_merged(db, ctx, entity.id)
        except NotFound:
            return None
    name = ref.field
    key = name[len(ATTRIBUTES_PREFIX):] if name is not None and name.startswith(ATTRIBUTES_PREFIX) else None
    if key is not None and key not in et.attribute_keys(entity.type):
        return None
    ids = entity_ref_ids(entity)
    visible = frozenset((await db.execute(scoped_select(Entity, ctx).where(Entity.id.in_(sorted(ids)))
                                          .with_only_columns(Entity.id))).scalars().all()) if ids else frozenset()
    body = project(entity, ctx, visible_entity_ids=visible).model_dump(mode="json")
    if name is None:
        return entity.name, _quote_text(body.get("description"))[:QUOTE_MAX]
    if key is not None:
        attrs = body.get("attributes") or {}
        if key not in attrs:
            # Unset, hidden, or a reference ctx may not see: all the same, no
            # citation (an empty-quote citation would tell them apart).
            return None
        value = attrs[key]
    else:
        value = body.get(name)
    return f"{entity.name} · {_field_label(entity, name)}", _quote_text(value)[:QUOTE_MAX]


# ── Registrations ──────────────────────────────────────────────────────────

register_writer(Entity, _visibility_writer)
register_writer(EntityRelationship, _visibility_writer)
register_visibility_kind("entity", Entity, fields=("aliases",))
register_visibility_kind("entity_relationship", EntityRelationship, options=(
    selectinload(EntityRelationship.source_entity), selectinload(EntityRelationship.target_entity)))
register_resolver(SourceKind.ENTITY_FIELD, resolve_entity_field, model=Entity, with_ctx=True)


__all__ = [
    "CanonChangeError", "DOMAIN", "HIDEABLE_FIELDS", "MergeResult", "NAME_PREFIXES", "NameCandidate", "NameMatch",
    "PARTY_WITH_GM_ONLY", "STALE_KIND", "apply_change", "candidates", "match_names", "merge", "merge_entities",
    "normalize_name", "resolve_entity_field", "revert_change",
]
