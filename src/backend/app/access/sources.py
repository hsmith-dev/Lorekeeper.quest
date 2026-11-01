"""Citations (E0-Access.8, AD-13, RC-10): which `SourceRef`s a ctx may see,
and the only place a `ResolvedSource` is built.

    refs = [SourceRef(kind=SourceKind.JOURNAL, id=entry.id, field="narrative")]
    shown = await visible_refs(db, refs, ctx)        # the refs ctx may see, in order
    cited = await resolve_sources(db, refs, ctx)     # ResolvedSource for each of them

Each `SourceKind` gets one resolver, `register_resolver(kind, fn, model=,
where=)`: `model` is the registered model whose rows the refs name (its
`id`), `where` an optional SQL predicate narrowing which rows are that kind
(journal: `kind = 'gm'`), and `fn(row, ref)` returns `(title, quote)` for a
row that has already passed the visibility check here. A resolver never
decides visibility, so it can never hand back a row ctx cannot see.

A ref is visible to a ctx when, in order:

  1. its kind has a resolver (else it is dropped, and `resolver_missing` is
     logged once per kind);
  2. its row exists and is one ctx may see (`scoped_select`, or
     `scoped_select_multi` for a `RoleMap`) and matches the resolver's `where`;
  3. its field is one ctx may see: for a GM any field of the model, or the
     whole record (`field=None`); for anyone else never an always-GM field or
     one of the model's `gm_fields`, never `field=None` on a model that has
     any (the whole record includes them), and never a field hidden by the
     row's `field_visibility`. An unknown field is dropped for everyone.

`ctx` is a `CampaignContext` or a `RoleMap` (a campaign-less chat: each row
is checked with the Role the map gives in the row's own Campaign). Results
keep the input order and drop duplicates.

`message_refs(msg)` reads a stored chat message's refs: None for a legacy
message (no `refs` key), which only a GM ctx may see.

Layer: like the rest of app.access, this imports schemas, db and core only.
"""
from __future__ import annotations

import inspect
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import ALWAYS_GM_FIELDS, stored_audience, visible_to
from app.access.context import CampaignContext, RoleMap, role_ctx, scoped_select_multi
from app.access.policy import GM, NotFound
from app.access.registry import SOURCE_KIND_MODELS, Stored, gm_fields, registration, scope_column, scoped_select
from app.db.models.journal import JournalEntry
from app.domain.enums import EntryKind
from app.schemas.sources import ResolvedSource, SourceKind, SourceRef

logger = logging.getLogger(__name__)

# The longest quote a built-in resolver returns (the chat snippet length).
QUOTE_MAX = 200

ResolverFn = Callable[[Any, SourceRef], Any]
Scope = CampaignContext | RoleMap


@dataclass(frozen=True)
class Resolver:
    kind: SourceKind
    fn: ResolverFn
    model: type
    where: Any = None


_RESOLVERS: dict[SourceKind, Resolver] = {}
_MISSING_LOGGED: set[str] = set()


def _kind(kind: SourceKind | str) -> SourceKind:
    try:
        return SourceKind(kind)
    except ValueError:
        raise ValueError(f"register_resolver: {kind!r} is not a SourceKind") from None


def register_resolver(kind: SourceKind | str, fn: ResolverFn, *, model: type | None = None,
                      where: Any = None) -> ResolverFn:
    """Register `fn(row, ref) -> (title, quote)` for refs of `kind`. `model`
    (default: `SOURCE_KIND_MODELS[kind]`) is the registered, Campaign-scoped
    model whose `id` a ref of this kind names; `where` an optional SQL
    predicate on it. Registering a different resolver for a kind that has
    one raises ValueError; re-registering the same one is a no-op."""
    key = _kind(kind)
    model = model if model is not None else SOURCE_KIND_MODELS.get(key.value)
    if model is None:
        raise ValueError(f"register_resolver: {key.value!r} needs model= (no SOURCE_KIND_MODELS entry)")
    registration(model)  # UnregisteredModel for an unregistered model
    if scope_column(model) is None or not hasattr(model, "id"):
        raise ValueError(f"register_resolver: {model.__name__} needs a Campaign scope and an `id` column")
    existing = _RESOLVERS.get(key)
    if existing is not None:
        if existing.fn is fn and existing.model is model:
            return fn
        raise ValueError(f"register_resolver: {key.value!r} already has a resolver ({existing.fn.__qualname__})")
    _RESOLVERS[key] = Resolver(key, fn, model, where)
    return fn


def registered_resolvers() -> list[str]:
    return sorted(k.value for k in _RESOLVERS)


def _log_missing(kind: str) -> None:
    if kind in _MISSING_LOGGED:
        return
    _MISSING_LOGGED.add(kind)
    logger.warning(json.dumps({"event": "resolver_missing", "kind": kind}))


def _dedupe(refs: Iterable[SourceRef]) -> list[SourceRef]:
    out: list[SourceRef] = []
    seen: set[SourceRef] = set()
    for ref in refs:
        if not isinstance(ref, SourceRef):
            ref = SourceRef.model_validate(ref)
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def _row_ctx(scope: Scope, row: Any) -> CampaignContext | None:
    if isinstance(scope, CampaignContext):
        return scope
    try:
        return role_ctx(scope, getattr(row, "campaign_id", None))
    except NotFound:
        return None


def field_visible(model: type, row: Any, field: str | None, ctx: CampaignContext) -> bool:
    """True when `ctx` may see `field` of `row` (a row it may already see);
    `field=None` is the whole record."""
    if field is not None and field not in sa.inspect(model).columns:
        return False  # unknown field: fail closed
    if ctx.role == GM:
        return True
    reg = registration(model)
    hidden = set(ALWAYS_GM_FIELDS) | set(gm_fields(model))
    per_field = reg.field_visibility if isinstance(reg, Stored) else None
    if field is None:
        # The whole record includes every GM field, and every field-level
        # Visibility: only a model with neither is whole-record visible.
        return not (hidden & set(sa.inspect(model).columns.keys())) and per_field is None
    if field in hidden:
        return False
    if per_field:
        vis = (getattr(row, per_field, None) or {}).get(field)
        if vis is not None:
            kind = getattr(row, reg.kind_field) if reg.kind_field else None
            if not visible_to(stored_audience(vis, getattr(row, reg.owner_field, None), kind), ctx):
                return False
    return True


async def _visible_rows(db: AsyncSession, refs: Iterable[SourceRef], scope: Scope) -> list[tuple[SourceRef, Any]]:
    """(ref, row) for each visible ref, in input order, deduped."""
    if not isinstance(scope, CampaignContext) and not isinstance(scope, Mapping):
        raise TypeError(f"visible_refs: ctx must be a CampaignContext or a RoleMap, got {type(scope).__name__}")
    refs = _dedupe(refs)
    by_kind: dict[SourceKind, set[uuid.UUID]] = {}
    for ref in refs:
        if ref.kind not in _RESOLVERS:
            _log_missing(ref.kind.value)
            continue
        by_kind.setdefault(ref.kind, set()).add(ref.id)
    rows: dict[tuple[SourceKind, uuid.UUID], Any] = {}
    for kind, ids in by_kind.items():
        res = _RESOLVERS[kind]
        model = res.model
        if isinstance(scope, CampaignContext):
            stmt = scoped_select(model, scope)
        else:
            stmt = scoped_select_multi(model, scope)
        stmt = stmt.where(model.id.in_(list(ids)))
        if res.where is not None:
            stmt = stmt.where(res.where)
        for row in (await db.execute(stmt)).scalars().all():
            rows[(kind, row.id)] = row
    out: list[tuple[SourceRef, Any]] = []
    for ref in refs:
        row = rows.get((ref.kind, ref.id))
        if row is None:
            continue
        row_ctx = _row_ctx(scope, row)
        if row_ctx is None or not field_visible(_RESOLVERS[ref.kind].model, row, ref.field, row_ctx):
            continue
        out.append((ref, row))
    return out


async def visible_refs(db: AsyncSession, refs: Iterable[SourceRef], ctx: Scope) -> list[SourceRef]:
    """The refs `ctx` may see (see the module docstring), in input order, deduped."""
    return [ref for ref, _ in await _visible_rows(db, refs, ctx)]


async def resolve_sources(db: AsyncSession, refs: Iterable[SourceRef], ctx: Scope) -> list[ResolvedSource]:
    """A `ResolvedSource` for each ref `ctx` may see, in input order, deduped.
    Visibility is checked before any resolver runs; a resolver that fails or
    returns nothing drops its ref (fail closed)."""
    out: list[ResolvedSource] = []
    for ref, row in await _visible_rows(db, refs, ctx):
        try:
            got = _RESOLVERS[ref.kind].fn(row, ref)
            if inspect.isawaitable(got):
                got = await got
            if not got:
                continue
            title, quote = got
        except Exception:
            logger.warning(json.dumps({"event": "resolver_failed", "kind": ref.kind.value}), exc_info=True)
            continue
        out.append(ResolvedSource(ref=ref, title=str(title), quote=str(quote or "")))
    return out


def message_refs(msg: Any) -> list[SourceRef] | None:
    """The refs of a stored chat message; None for a legacy message (no
    `refs` key). ValueError when `refs` is malformed."""
    if not isinstance(msg, Mapping) or "refs" not in msg:
        return None
    raw = msg["refs"]
    if not isinstance(raw, list):
        raise ValueError("message refs must be a list")
    try:
        return [r if isinstance(r, SourceRef) else SourceRef.model_validate(r) for r in raw]
    except Exception as exc:  # pydantic ValidationError
        raise ValueError(f"malformed message refs: {exc}") from None


# ── Built-in resolvers: journal entries ────────────────────────────────────

def _entry_title(entry: JournalEntry, label: str) -> str:
    return f"{label} · {entry.session_date.isoformat()}" if entry.session_date else label


def _entry_quote(entry: JournalEntry, ref: SourceRef) -> str:
    return str(getattr(entry, ref.field or "narrative", "") or "")[:QUOTE_MAX]


def resolve_journal(entry: JournalEntry, ref: SourceRef) -> tuple[str, str]:
    return _entry_title(entry, "Journal entry"), _entry_quote(entry, ref)


def resolve_player_journal(entry: JournalEntry, ref: SourceRef) -> tuple[str, str]:
    return _entry_title(entry, "Player journal"), _entry_quote(entry, ref)


register_resolver(SourceKind.JOURNAL, resolve_journal, model=JournalEntry,
                  where=JournalEntry.kind == EntryKind.GM.value)
register_resolver(SourceKind.PLAYER_JOURNAL, resolve_player_journal, model=JournalEntry,
                  where=JournalEntry.kind == EntryKind.PLAYER.value)
