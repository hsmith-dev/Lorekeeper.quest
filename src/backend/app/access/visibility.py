"""`set_visibility`, the only Visibility writer (E0-Access.9, AD-13, AR-13).

    entry = await set_visibility(db, ctx, RecordRef(kind="journal", id=entry_id), Visibility.GM)
    n = await set_visibility_many(db, ctx, items, Visibility.PARTY)     # all-or-nothing
    await db.commit()                                                  # listeners, then the cache

Nothing else under src/backend/app writes a `visibility`, `field_visibility`
or `visibility_floor` column (scripts/check_scoped_queries.py, CI-8). The one
exception is the `visibility_floor` write in `world_service.apply_change` for
a merge.

**Who.** Only a writable GM user ctx may change Visibility. A Player, anon,
read-only (`audience_ctx`, preview) or system ctx gets `not_found()`.

**What.** A ref (`RecordRef`, or a `SourceRef`) names a Visibility kind
(`register_visibility_kind`) and a row id. The kind maps to a registered
`stored` model with a Visibility column, and the row must be in
`ctx.campaign_id` and match the kind's `where` (journal: `kind = 'gm'`,
player_journal: `kind = 'player'`). Anything else is `not_found()`, the same
answer as a missing row. An `always_gm` model, an always-GM field
(`ALWAYS_GM_FIELDS`) or one of the model's `gm_fields` raises
`VisibilityError` 422 `always_gm`.

**Fields.** `field` (the keyword, else the ref's own `field`):

  * None (or the Visibility column's name) sets the stored column;
  * "visibility_floor" sets that column, on a model that has one;
  * on a model with `field_visibility`, any other column sets
    `field_visibility[field]` (a new dict, so JSONB change tracking sees it);
  * anything else is 422 `no_field_visibility` (`unknown_field` for a
    name that is not a column of a model with field visibility).

A registry `writer` receives the field as "visibility", "visibility_floor"
or "field_visibility.<key>" and does the write itself.

**Order of work.** The write runs first. Next comes
`mark_dependents_stale(db, [ref])`, which calls every stale marker
`(db, ref)` in registration order inside the caller's transaction. After
the root transaction commits, each listener is called once per Campaign
with `(campaign_id, refs, actor_ctx)`, and then every `cache:{campaign_id}:*`
key is deleted from Valkey. On rollback (of the root transaction, or of the
savepoint the change was made in), the listeners and cache work for it are
discarded. A listener or cache failure is logged, never raised: the change
has already committed.
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import sqlalchemy as sa
from fastapi import Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction, selectinload
from sqlalchemy.util.concurrency import await_only, in_greenlet

from app.access.audience import ALWAYS_GM_FIELDS
from app.access.context import CampaignContext
from app.access.policy import GM, not_found
from app.access.projection import project_all
from app.access.registry import AlwaysGM, Stored, registration, scope_column, scoped_select
from app.db.models.character_sheet import CharacterSheet
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.session_plan import SessionPlan
from app.db.models.shorthand import ShorthandTerm
from app.db.models.source import SourceDocument
from app.db.models.tag import Tag
from app.db.models.tag_category import TagCategory
from app.domain.enums import EntryKind, Visibility
from app.schemas import visibility as visibility_schemas
from app.schemas.sources import RecordRef, SourceRef

logger = logging.getLogger(__name__)

VISIBILITY_FLOOR = "visibility_floor"
FIELD_PREFIX = "field_visibility."
PENDING_KEY = "lorekeeper.access.visibility_changed"
CACHE_SCAN_COUNT = 500


# ── Errors ─────────────────────────────────────────────────────────────────

class VisibilityError(Exception):
    """A GM asked for a change that can never be made: 422 `{"detail", "code"}`
    (rendered by `visibility_exception_handler`, registered in app/main.py)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def always_gm_error() -> VisibilityError:
    return VisibilityError("always_gm", "This is always GM-only")


async def visibility_exception_handler(request: Request, exc: VisibilityError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code})


# ── The kind map ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class VisibilityKind:
    kind: str
    model: type
    where: Any = None              # an SQL predicate narrowing which rows are this kind
    options: tuple[Any, ...] = ()  # loader options the projection needs


_KINDS: dict[str, VisibilityKind] = {}


def register_visibility_kind(kind: str, model: type, *, where: Any = None,
                             options: Sequence[Any] = ()) -> VisibilityKind:
    """Make `kind` a target of `set_visibility` and of the bulk route: refs
    of this kind name `model.id`, narrowed by `where`. `model` must be
    registered and Campaign-scoped. An `always_gm` model may be registered
    (its refs then answer 422 `always_gm`). Registering a different model
    for a kind that has one raises ValueError; the same one is a no-op."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("register_visibility_kind: kind must be a non-empty string")
    registration(model)  # UnregisteredModel for an unregistered model
    if scope_column(model) is None or not hasattr(model, "id"):
        raise ValueError(f"register_visibility_kind: {model.__name__} needs a Campaign scope and an `id` column")
    entry = VisibilityKind(kind, model, where, tuple(options))
    existing = _KINDS.get(kind)
    if existing is not None:
        if existing.model is model:
            return existing
        raise ValueError(f"register_visibility_kind: {kind!r} is already {existing.model.__name__}")
    _KINDS[kind] = entry
    visibility_schemas.VISIBILITY_KINDS.add(kind)
    return entry


def visibility_kinds() -> list[str]:
    return sorted(_KINDS)


# ── Extension points ───────────────────────────────────────────────────────

StaleMarker = Callable[[AsyncSession, Any], Any]
VisibilityListener = Callable[[uuid.UUID, list, CampaignContext], Any]

_STALE_MARKERS: list[StaleMarker] = []
_LISTENERS: list[VisibilityListener] = []


def register_stale_marker(fn: StaleMarker) -> StaleMarker:
    """Call `fn(db, ref)` (sync or async) for every ref whose dependents must
    go stale, inside the caller's transaction (E0-Jobs: `derived_sources`).
    Registering the same function twice is a no-op."""
    if fn not in _STALE_MARKERS:
        _STALE_MARKERS.append(fn)
    return fn


def register_visibility_listener(fn: VisibilityListener) -> VisibilityListener:
    """Call `fn(campaign_id, refs, actor_ctx)` (sync or async) once per
    Campaign after a Visibility change commits (E0-Journal: the
    `visibility_changed` hook). Never called for a rolled-back change.

    It runs after the commit, so it must not use the request's session
    (that transaction is over): open its own, or enqueue a Job. `actor_ctx`
    is the ctx of the first change made in that Campaign in the committed
    transaction; `refs` are every distinct ref changed there, in order.
    Registering the same function twice is a no-op."""
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)
    return fn


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def mark_dependents_stale(db: AsyncSession, refs: Iterable[Any]) -> None:
    """Run every registered stale marker for each ref, in registration order,
    inside the caller's transaction (RC-11). The only staleness entry point
    code outside app/access/ may call (`world_service.apply_change`). A
    marker's error propagates: the caller's transaction must not commit a
    change whose dependents were not marked."""
    for ref in refs:
        for marker in list(_STALE_MARKERS):
            await _maybe_await(marker(db, ref))


# ── The writer ─────────────────────────────────────────────────────────────

def _check_writer(ctx: Any) -> None:
    if (not isinstance(ctx, CampaignContext) or ctx.role != GM or ctx.read_only or ctx.is_system
            or ctx.user_id is None):
        not_found()


def _record_ref(ref: Any, field: str | None) -> RecordRef:
    if isinstance(ref, SourceRef):
        kind, row_id, own_field = ref.kind.value, ref.id, ref.field
    elif isinstance(ref, RecordRef):
        kind, row_id, own_field = ref.kind, ref.id, ref.field
    elif isinstance(ref, Mapping):
        parsed = RecordRef.model_validate(dict(ref))
        kind, row_id, own_field = parsed.kind, parsed.id, parsed.field
    else:
        raise TypeError(f"set_visibility: ref must be a RecordRef or a SourceRef, got {type(ref).__name__}")
    return RecordRef(kind=str(kind), id=row_id, field=field if field is not None else own_field)


def field_path(columns: Iterable[str], reg: Stored, field: str | None) -> str:
    """Where a change to `field` lands, as a writer receives it: "visibility"
    (the stored column, whatever its name), "visibility_floor" or
    "field_visibility.<key>". Raises VisibilityError for a field that can
    never be set. `columns` are the model's column names."""
    columns = set(columns)
    if field is None or field == reg.column:
        return "visibility"
    if field in ALWAYS_GM_FIELDS or field in reg.gm_fields:
        raise always_gm_error()
    if field == VISIBILITY_FLOOR and VISIBILITY_FLOOR in columns:
        return VISIBILITY_FLOOR
    if not reg.field_visibility:
        raise VisibilityError("no_field_visibility", "This record has no field-level visibility")
    if field not in columns or field in {reg.field_visibility, VISIBILITY_FLOOR}:
        raise VisibilityError("unknown_field", "This record has no such field")
    return FIELD_PREFIX + field


def _target(ref: RecordRef) -> tuple[VisibilityKind, Stored, str]:
    entry = _KINDS.get(ref.kind)
    if entry is None:
        not_found()
    reg = registration(entry.model)
    if isinstance(reg, AlwaysGM):
        raise always_gm_error()
    if not isinstance(reg, Stored) or reg.column is None:
        not_found()
    return entry, reg, field_path(sa.inspect(entry.model).columns.keys(), reg, ref.field)


def _select(entry: VisibilityKind, ctx: CampaignContext, row_id: uuid.UUID) -> sa.Select:
    stmt = scoped_select(entry.model, ctx).where(entry.model.id == row_id)
    if entry.where is not None:
        stmt = stmt.where(entry.where)
    if entry.options:
        stmt = stmt.options(*entry.options)
    return stmt


async def _write(db: AsyncSession, ctx: CampaignContext, entry: VisibilityKind, reg: Stored, row: Any,
                 path: str, value: Visibility) -> None:
    if reg.writer is not None:
        await _maybe_await(reg.writer(db, ctx, row, path, value))
    elif path == "visibility":
        setattr(row, reg.column, value)
    elif path == VISIBILITY_FLOOR:
        setattr(row, VISIBILITY_FLOOR, value)
    else:
        key = path[len(FIELD_PREFIX):]
        per_field = dict(getattr(row, reg.field_visibility, None) or {})
        per_field[key] = value.value
        setattr(row, reg.field_visibility, per_field)  # a new dict: JSONB change tracking sees it
    await db.flush()


async def _apply(db: AsyncSession, ctx: CampaignContext, ref: RecordRef, value: Visibility) -> tuple[Any, VisibilityKind]:
    entry, reg, path = _target(ref)
    row = (await db.execute(_select(entry, ctx, ref.id))).scalars().first()
    if row is None or getattr(row, "campaign_id", None) != ctx.campaign_id:
        not_found()
    await _write(db, ctx, entry, reg, row, path, value)
    await mark_dependents_stale(db, [ref])
    _record_pending(db.sync_session, ctx, ref)
    return row, entry


async def set_visibility(db: AsyncSession, ctx: CampaignContext, ref: RecordRef | SourceRef,
                         value: Visibility | str, *, field: str | None = None) -> Any:
    """Change the Visibility of one record (or one field of it, see the
    module docstring) and return the record projected for ctx. Does not
    commit: the listeners and cache invalidation run when the caller does."""
    _check_writer(ctx)
    value = Visibility(value)
    rec = _record_ref(ref, field)
    row, entry = await _apply(db, ctx, rec, value)
    # Reload (server-side onupdate columns, a writer's own UPDATE) before projecting.
    stmt = _select(entry, ctx, rec.id).execution_options(populate_existing=True)
    row = (await db.execute(stmt)).scalars().one()
    return (await project_all(db, [row], ctx))[0]


def dedupe_targets(refs: Iterable[RecordRef | SourceRef]) -> list[RecordRef]:
    """The refs, in order, with one per write target `(kind, id, path)`:
    `field=None` and `field="visibility"` are the same column, and a
    SourceRef and a RecordRef for one row are one item. Raises not_found()
    or VisibilityError for a bad kind or field."""
    distinct: list[RecordRef] = []
    seen: set[tuple[str, uuid.UUID, str]] = set()
    for ref in refs:
        rec = _record_ref(ref, None)
        _entry, _reg, path = _target(rec)
        key = (rec.kind, rec.id, path)
        if key not in seen:
            seen.add(key)
            distinct.append(rec)
    return distinct


async def set_visibility_many(db: AsyncSession, ctx: CampaignContext, refs: Iterable[RecordRef | SourceRef],
                              value: Visibility | str) -> int:
    """Set every ref (deduplicated) to `value`, all-or-nothing: the first
    `not_found()` or VisibilityError rolls back every item written here (a
    savepoint) and propagates. Returns the number of distinct items written,
    unchanged values included. Does not commit."""
    _check_writer(ctx)
    value = Visibility(value)
    distinct = dedupe_targets(refs)  # refuses a bad kind or field before writing anything
    async with db.begin_nested():
        for rec in distinct:
            await _apply(db, ctx, rec, value)
    return len(distinct)


# ── After commit: listeners, then the cache ────────────────────────────────

@dataclass(frozen=True)
class _Pending:
    campaign_id: uuid.UUID
    ref: RecordRef
    ctx: CampaignContext
    transaction: SessionTransaction | None


def _record_pending(session: Session, ctx: CampaignContext, ref: RecordRef) -> None:
    txn = session.get_nested_transaction() or session.get_transaction()
    session.info.setdefault(PENDING_KEY, []).append(_Pending(ctx.campaign_id, ref, ctx, txn))


def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


def _by_campaign(pending: Sequence[_Pending]) -> list[tuple[uuid.UUID, list[RecordRef], CampaignContext]]:
    groups: dict[uuid.UUID, tuple[list[RecordRef], CampaignContext]] = {}
    for p in pending:
        refs, _ctx = groups.setdefault(p.campaign_id, ([], p.ctx))
        if p.ref not in refs:
            refs.append(p.ref)
    return [(cid, refs, ctx) for cid, (refs, ctx) in groups.items()]


async def invalidate_campaign_cache(campaign_id: uuid.UUID) -> None:
    """Delete every `cache:{campaign_id}:*` key (the E0-Access.10 key
    scheme). No Valkey client (tests, scripts) means nothing is cached. A
    Valkey error is logged, never raised."""
    from app.core.valkey_client import get_valkey

    try:
        client = get_valkey()
    except RuntimeError:
        return
    try:
        batch: list[str] = []
        async for key in client.scan_iter(match=f"cache:{campaign_id}:*", count=CACHE_SCAN_COUNT):
            batch.append(key)
            if len(batch) >= CACHE_SCAN_COUNT:
                await client.unlink(*batch)
                batch = []
        if batch:
            await client.unlink(*batch)
    except Exception:
        logger.warning(json.dumps({"event": "visibility_cache_invalidate_failed", "campaign_id": str(campaign_id)}),
                       exc_info=True)


async def dispatch(pending: Sequence[_Pending]) -> None:
    """Listeners (each once per Campaign), then the cache. Never raises."""
    groups = _by_campaign(pending)
    for campaign_id, refs, ctx in groups:
        for listener in list(_LISTENERS):
            try:
                await _maybe_await(listener(campaign_id, list(refs), ctx))
            except Exception:
                logger.exception(json.dumps({"event": "visibility_listener_failed", "campaign_id": str(campaign_id),
                                             "listener": getattr(listener, "__qualname__", repr(listener))}))
    for campaign_id, _refs, _ctx in groups:
        try:
            await invalidate_campaign_cache(campaign_id)
        except Exception:
            logger.exception("visibility cache invalidation failed")


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop(PENDING_KEY, None)
        return
    pending = session.info.get(PENDING_KEY)
    if pending:
        session.info[PENDING_KEY] = [p for p in pending if not _within(p.transaction, previous_transaction)]


@event.listens_for(Session, "after_transaction_end")
def _clear_on_end(session: Session, transaction: SessionTransaction) -> None:
    # after_commit has already taken what it dispatches; a root transaction
    # that ends any other way (close() without commit) must leave nothing.
    if transaction.parent is None:
        session.info.pop(PENDING_KEY, None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint release: not durable yet
    pending = session.info.pop(PENDING_KEY, None)
    if not pending:
        return
    if not in_greenlet():
        logger.warning("visibility changes committed outside an AsyncSession: listeners and cache invalidation "
                       "were skipped")
        return
    try:
        await_only(dispatch(pending))
    except Exception:
        logger.exception("visibility dispatch after commit failed")


# ── Built-in kinds ─────────────────────────────────────────────────────────

_ENTRY_TAGS = selectinload(JournalEntry.tags).selectinload(Tag.custom_category)

register_visibility_kind("journal", JournalEntry, where=JournalEntry.kind == EntryKind.GM.value,
                         options=(_ENTRY_TAGS,))
register_visibility_kind("player_journal", JournalEntry, where=JournalEntry.kind == EntryKind.PLAYER.value,
                         options=(_ENTRY_TAGS,))
register_visibility_kind("character_sheet", CharacterSheet)
register_visibility_kind("session_plan", SessionPlan)
register_visibility_kind("source_document", SourceDocument)
register_visibility_kind("shorthand_term", ShorthandTerm)
register_visibility_kind("tag_category", TagCategory)
# Always GM until F3-world (B1-D4): a ref answers 422 always_gm.
register_visibility_kind("npc", NpcEntry)
register_visibility_kind("quest", Quest)
