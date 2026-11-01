"""The access registry (AD-12, AD-13): one declaration per model of how its
Audience is computed, and the two predicates generated from it.

    stmt = scoped_select(JournalEntry, ctx).order_by(JournalEntry.created_at)
    row = await scoped_get(db, SessionPlan, ctx, plan_id)   # not_found() if hidden or missing

Each model registers exactly one class:

  * `stored(column="visibility", owner_field="user_id", kind_field=None,
    field_visibility=None, writer=None)`: the row carries its Visibility.
    `column=None` means every row is Owner(owner_field) (chat sessions).
    `writer` (E0-Access.9) is the function `set_visibility` writes through.
  * `derived(derive_from=[...])`: the row's Audience comes from other rows,
    through `parent(...)` links (the most restrictive parent, plus a
    `field=` rule such as `journal_tags.source_field`), or through
    `reached_through(...)` (any one visible child is enough: tags).
  * `always_gm(owner_field=None)`: GM only (npcs and quests until F3-world,
    Decision B1-D4). With `owner_field`, a non-GM Owner(u) ctx also reads
    the rows whose owner_field = u (jobs: a Player sees the Jobs they
    started). A global table (no `campaign_id`: data_backfills,
    derived_sources) may register always_gm; `scoped_select` refuses it.
  * `derived_from_sources()`: the row's Audience is the most restrictive of
    the rows its `derived_sources` name (stored_files, E0-Jobs.1). See
    "Derived from sources" below.
  * `membership(audience)`: a constant Audience for a membership-scoped
    table of the ctx's Campaign; management rules stay in the routes.

`visible_clause(Model, ctx)` (SQL) and `audience_of(obj)` (Python) are both
read from the same registration; tests/access/test_registry_property.py
(CI-11) proves they agree. `scoped_select` adds the Campaign scope.

`DERIVED_REGISTRY` lists derived types (file or not: E0-Jobs' derived
files, E4's `live_recap`), each `{derived_type, derive_from: [ref_kind, ...]}`;
`audience_of` on such an object is the most restrictive Audience of its
`derived_sources` (GM when it has none).

Derived from sources (stored_files): the file's `kind` is its derived type
in DERIVED_REGISTRY, and its sources are the `derived_sources` rows with
`derived_type = kind`, `derived_id = id`. Each `ref_kind` resolves to a
model through SOURCE_KIND_MODELS (`register_source_kind`). For a non-GM the
file is visible only when it is not stale, its kind is registered, its
`audience_owner_id` is NULL or the viewer, it has at least one source, and
every source is allowed by the type's `derive_from`, has a model, is a row
of the same Campaign that the viewer may see, and does not come from an
always-GM `ref_field`. Anything else fails closed (GM only).

At import, every mapped table with a `campaign_id` column (plus `tags` and
`journal_tags`) must be registered or listed in `UNSCOPED` with a reason;
otherwise importing this module raises RuntimeError.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import app.db.models  # noqa: F401  (every model is mapped before the completeness check)
from app.access.audience import (
    GM_AUDIENCE, MEMBERS, PUBLIC, ALWAYS_GM_FIELDS, AnyOf, Audience, AudienceLevel, covers, field_audience,
    most_restrictive, owner, stored_audience,
)
from app.access.policy import not_found
from app.db.base import Base
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.character_sheet import CharacterSheet, CharacterSheetTemplate
from app.db.models.chat import ChatSession
from app.db.models.job import DataBackfill, Job
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.session_plan import SessionPlan
from app.db.models.share_token import CampaignShareToken
from app.db.models.shorthand import ShorthandTerm
from app.db.models.source import SourceChunk, SourceDocument
from app.db.models.stored_file import DerivedSource, StoredFile
from app.db.models.tag import JournalTag, Tag
from app.db.models.tag_category import TagCategory
from app.domain.enums import EntryKind, Visibility

if TYPE_CHECKING:  # pragma: no cover
    from app.access.context import CampaignContext


class UnregisteredModel(LookupError):
    """A model with no access registration was used where one is required."""


# ── Registration classes ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Stored:
    column: str | None = "visibility"
    owner_field: str = "user_id"
    kind_field: str | None = None
    # A JSONB column of per-field Visibilities; E0-WorldCore turns it on for
    # `entities`. Field level only: it never changes the row's Audience.
    field_visibility: str | None = None
    gm_fields: tuple[str, ...] = ()
    # E0-Access.9: the one function that writes this model's Visibility
    # columns, `writer(db, ctx, row, field, value)` (sync or async), where
    # `field` is "visibility", "visibility_floor" or "field_visibility.<key>".
    # `set_visibility` calls it instead of setting the column itself
    # (E0-WorldCore registers `world_service.apply_change` for Canon tables).
    writer: Callable[..., Any] | None = None


@dataclass(frozen=True)
class Parent:
    """The row derives from `model` through `fk` (its column) = `model.<remote>`.
    `attr` is the relationship that loads the parent object, if any."""

    model: type
    fk: str
    remote: str = "id"
    attr: str | None = None


@dataclass(frozen=True)
class ReachedThrough:
    """The row is visible through any visible `child` whose `fk` = this row's `remote`."""

    child: type
    fk: str
    remote: str = "id"


@dataclass(frozen=True)
class Derived:
    derive_from: tuple[Parent | ReachedThrough, ...]
    # A column on the row whose value narrows it through `field_audience`
    # (journal_tags.source_field: a Shorthand tag is GM).
    field: str | None = None
    gm_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.derive_from:
            raise ValueError("derived: derive_from needs at least one link")
        kinds = {type(link) for link in self.derive_from}
        if len(kinds) > 1:
            raise ValueError("derived: links are all parent(...) or all reached_through(...)")


@dataclass(frozen=True)
class AlwaysGM:
    gm_fields: tuple[str, ...] = ()
    # A non-GM Owner(u) ctx reads the rows whose owner_field = u.
    owner_field: str | None = None


@dataclass(frozen=True)
class DerivedFromSources:
    """The Audience comes from the row's `derived_sources` (stored_files)."""

    id_field: str = "id"
    kind_field: str = "kind"
    stale_field: str = "stale"
    owner_field: str = "audience_owner_id"
    gm_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Membership:
    audience: Audience
    gm_fields: tuple[str, ...] = ()


Registration = Stored | Derived | AlwaysGM | Membership | DerivedFromSources


def stored(column: str | None = "visibility", owner_field: str = "user_id", kind_field: str | None = None,
           field_visibility: str | None = None, *, gm_fields: Iterable[str] = (),
           writer: Callable[..., Any] | None = None) -> Stored:
    return Stored(column, owner_field, kind_field, field_visibility, tuple(gm_fields), writer)


def parent(model: type, fk: str, *, remote: str = "id", attr: str | None = None) -> Parent:
    return Parent(model, fk, remote, attr)


def reached_through(child: type, fk: str, *, remote: str = "id") -> ReachedThrough:
    return ReachedThrough(child, fk, remote)


def derived(derive_from: Sequence[Parent | ReachedThrough], *, field: str | None = None,
            gm_fields: Iterable[str] = ()) -> Derived:
    return Derived(tuple(derive_from), field, tuple(gm_fields))


def always_gm(*, owner_field: str | None = None, gm_fields: Iterable[str] = ()) -> AlwaysGM:
    return AlwaysGM(tuple(gm_fields), owner_field)


def derived_from_sources(*, gm_fields: Iterable[str] = ()) -> DerivedFromSources:
    return DerivedFromSources(gm_fields=tuple(gm_fields))


def membership(audience: Audience, *, gm_fields: Iterable[str] = ()) -> Membership:
    if audience.level is AudienceLevel.OWNER:
        raise ValueError("membership: a constant Audience cannot be Owner(u)")
    return Membership(audience, tuple(gm_fields))


# ── The registry ───────────────────────────────────────────────────────────

REGISTRY: dict[type, Registration] = {
    JournalEntry: stored(kind_field="kind", gm_fields=("shorthand",)),
    CharacterSheet: stored(owner_field="created_by_user_id"),
    SessionPlan: stored(),
    SourceDocument: stored(),
    SourceChunk: derived([parent(SourceDocument, "source_document_id", attr="document")]),
    ShorthandTerm: stored(),
    TagCategory: stored(owner_field="created_by_user_id"),
    JournalTag: derived([parent(JournalEntry, "journal_id")], field="source_field"),
    Tag: derived([reached_through(JournalTag, "tag_id")]),
    ChatSession: stored(column=None),
    NpcEntry: always_gm(gm_fields=("notes",)),
    Quest: always_gm(gm_fields=("notes",)),
    # E0-Jobs.1 (F2-jobs-files).
    Job: always_gm(owner_field="created_by"),
    StoredFile: derived_from_sources(),
    # Global (no campaign_id): never read through scoped_select.
    DerivedSource: always_gm(),
    DataBackfill: always_gm(),
    Campaign: membership(PUBLIC),
    CampaignMember: membership(MEMBERS),
    CampaignShareToken: membership(GM_AUDIENCE),
    # The layout every sheet viewer needs.
    CharacterSheetTemplate: membership(PUBLIC),
}

# Tables with a campaign_id that are not Campaign content, with the reason.
UNSCOPED: dict[str, str] = {
    "feedback": "operator feedback, read by user_id (and by admins), not Campaign content",
}


def registration(model: type) -> Registration:
    try:
        return REGISTRY[model]
    except (KeyError, TypeError):
        raise UnregisteredModel(
            f"{getattr(model, '__name__', model)!r} has no access registration (app/access/registry.py)"
        ) from None


def scope_column(model: type) -> Any | None:
    """The column a model is scoped to its Campaign by: `campaigns.id`, else
    `campaign_id`; None for models scoped through a parent (tags, journal_tags)."""
    if model is Campaign:
        return Campaign.id
    return getattr(model, "campaign_id", None)


# ── SQL: visible_clause ────────────────────────────────────────────────────

def _col(model: type, name: str):
    return getattr(model, name)


def _gm_valued_fields() -> list[str]:
    return sorted(ALWAYS_GM_FIELDS)


def _stored_clause(model: type, reg: Stored, viewer: Audience):
    level = viewer.level
    if level is AudienceLevel.GM:
        return sa.true()
    owner_col = _col(model, reg.owner_field)
    if reg.column is None:  # every row is Owner(owner)
        return owner_col == viewer.user_id if level is AudienceLevel.OWNER else sa.false()
    vis = _col(model, reg.column)
    if level is AudienceLevel.OWNER:
        return sa.or_(vis == Visibility.PARTY.value,
                      sa.and_(vis == Visibility.PRIVATE.value, owner_col == viewer.user_id))
    if level is AudienceLevel.MEMBERS:
        return vis == Visibility.PARTY.value
    # Public
    if reg.kind_field is None:
        return vis == Visibility.PARTY.value
    return sa.and_(vis == Visibility.PARTY.value, _col(model, reg.kind_field) == EntryKind.GM.value)


def _field_clause(model: type, reg: Derived, viewer: Audience):
    if reg.field is None or viewer.level is AudienceLevel.GM:
        return sa.true()
    col = _col(model, reg.field)
    return sa.or_(col.is_(None), col.notin_(_gm_valued_fields()))


def _derived_clause(model: type, reg: Derived, ctx: "CampaignContext"):
    clauses = []
    for link in reg.derive_from:
        if isinstance(link, Parent):
            target = link.model
            scope = scope_column(target)
            where = [_col(target, link.remote) == _col(model, link.fk)]
            if scope is not None:
                where.append(scope == ctx.campaign_id)
            where.append(visible_clause(target, ctx))
            clauses.append(sa.exists().where(*where))
        else:
            child = link.child
            clauses.append(sa.exists().where(_col(child, link.fk) == _col(model, link.remote),
                                             visible_clause(child, ctx)))
    combined = sa.and_(*clauses) if isinstance(reg.derive_from[0], Parent) else sa.or_(*clauses)
    return sa.and_(combined, _field_clause(model, reg, ctx.audience))


def visible_clause(model: type, ctx: "CampaignContext"):
    """The SQL predicate "this row's Audience covers ctx.audience" for
    `model` (no Campaign scope for models with their own campaign column;
    derived models are scoped through their parents)."""
    reg = registration(model)
    viewer = ctx.audience
    if isinstance(reg, Stored):
        return _stored_clause(model, reg, viewer)
    if isinstance(reg, Derived):
        return _derived_clause(model, reg, ctx)
    if isinstance(reg, AlwaysGM):
        if viewer.level is AudienceLevel.GM:
            return sa.true()
        if reg.owner_field is not None and viewer.level is AudienceLevel.OWNER:
            return _col(model, reg.owner_field) == viewer.user_id
        return sa.false()
    if isinstance(reg, Membership):
        return sa.true() if covers(reg.audience, viewer) else sa.false()
    if isinstance(reg, DerivedFromSources):
        return _sources_clause(model, reg, ctx)
    raise TypeError(f"unknown registration {reg!r}")  # pragma: no cover


def scoped_select(model: type, ctx: "CampaignContext") -> sa.Select:
    """`select(model)` of the rows of ctx's Campaign that ctx may see."""
    reg = registration(model)
    stmt = sa.select(model)
    scope = scope_column(model)
    if scope is not None:
        stmt = stmt.where(scope == ctx.campaign_id)
    elif not isinstance(reg, Derived):  # a global always_gm table (derived_sources, data_backfills)
        raise UnregisteredModel(f"{model.__name__!r} has no Campaign scope")
    return stmt.where(visible_clause(model, ctx))


async def scoped_get(db: AsyncSession, model: type, ctx: "CampaignContext", row_id: Any, *,
                     options: Sequence[Any] = ()) -> Any:
    """The row `row_id` of `model` if it is in ctx's Campaign and visible to
    ctx; else the one `not_found()` (hidden and missing are the same).
    `options` are loader options for the select (e.g. `selectinload(...)`)."""
    pk = sa.inspect(model).primary_key
    if len(pk) != 1:
        raise TypeError(f"scoped_get: {model.__name__!r} has a composite primary key")
    if not isinstance(row_id, uuid.UUID):
        try:
            row_id = uuid.UUID(str(row_id))
        except (TypeError, ValueError, AttributeError):
            not_found()
    stmt = scoped_select(model, ctx).where(pk[0] == row_id)
    if options:
        stmt = stmt.options(*options)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        not_found()
    return row


async def owned_get(db: AsyncSession, model: type, user_id: uuid.UUID, row_id: Any) -> Any:
    """The row `row_id` of an owner-only stored model (`stored(column=None)`,
    e.g. chat_sessions: Audience Owner(author) always) if `user_id` owns it,
    in any Campaign or none; else the one `not_found()` (a bad id, a missing
    row and another user's are the same). The caller still checks the row's
    Campaign Role (the ctx it then reads the row with)."""
    reg = registration(model)
    if not isinstance(reg, Stored) or reg.column is not None:
        raise TypeError(f"owned_get: {model.__name__!r} is not an owner-only stored model")
    pk = sa.inspect(model).primary_key
    if len(pk) != 1:
        raise TypeError(f"owned_get: {model.__name__!r} has a composite primary key")
    if not isinstance(row_id, uuid.UUID):
        try:
            row_id = uuid.UUID(str(row_id))
        except (TypeError, ValueError, AttributeError):
            not_found()
    row = (await db.execute(
        sa.select(model).where(pk[0] == row_id, _col(model, reg.owner_field) == user_id)
    )).scalar_one_or_none()
    if row is None:
        not_found()
    return row


# ── Python: audience_of ────────────────────────────────────────────────────

@dataclass(frozen=True)
class DerivedType:
    derived_type: str
    derive_from: tuple[str, ...]


# Derived types (file or not), appended by E0-Jobs and feature epics, as
# dicts `{derived_type, derive_from: [ref_kind, ...]}` or DerivedType.
DERIVED_REGISTRY: list[DerivedType | dict] = []


def _normalize_derived(derived_type: Any, derive_from: Any) -> DerivedType:
    """One validated DerivedType: a non-empty str name and a non-empty list of
    str ref_kinds (a bare str is rejected, not split into characters)."""
    if not isinstance(derived_type, str) or not derived_type:
        raise TypeError(f"derived type: derived_type must be a non-empty str, got {derived_type!r}")
    if isinstance(derive_from, (str, bytes)) or not isinstance(derive_from, Iterable):
        raise TypeError(f"derived type {derived_type!r}: derive_from must be a list of ref_kinds, "
                        f"got {derive_from!r}")
    kinds = tuple(derive_from)
    if not kinds:
        raise ValueError(f"derived type {derived_type!r}: derive_from needs at least one ref_kind")
    for k in kinds:
        if not isinstance(k, str) or not k:
            raise TypeError(f"derived type {derived_type!r}: ref_kind must be a non-empty str, got {k!r}")
    return DerivedType(derived_type, kinds)


def _derived_entry(raw: Any) -> DerivedType:
    """A DERIVED_REGISTRY entry (DerivedType or dict) as a validated DerivedType."""
    if isinstance(raw, DerivedType):
        return _normalize_derived(raw.derived_type, raw.derive_from)
    if isinstance(raw, Mapping):
        missing = {"derived_type", "derive_from"} - set(raw)
        if missing:
            raise ValueError(f"DERIVED_REGISTRY entry {dict(raw)!r} is missing {sorted(missing)}")
        return _normalize_derived(raw["derived_type"], raw["derive_from"])
    raise TypeError(f"DERIVED_REGISTRY entries are DerivedType or dict, got {raw!r}")


def register_derived(derived_type: str, derive_from: Iterable[str]) -> DerivedType:
    entry = _normalize_derived(derived_type, derive_from)
    if _derived_type(entry.derived_type, missing_ok=True) is not None:
        raise ValueError(f"register_derived: {entry.derived_type!r} is already registered")
    DERIVED_REGISTRY.append(entry)
    return entry


def _derived_type(name: str, *, missing_ok: bool = False) -> DerivedType | None:
    for raw in DERIVED_REGISTRY:
        entry = _derived_entry(raw)
        if entry.derived_type == name:
            return entry
    if missing_ok:
        return None
    raise ValueError(f"{name!r} is not in DERIVED_REGISTRY")


def _source_audience(source: Any) -> Audience:
    if isinstance(source, Audience):
        return source
    if hasattr(source, "audience") and isinstance(source.audience, Audience):
        return source.audience
    ref = getattr(source, "ref", source)
    aud = audience_of(ref)
    if isinstance(aud, AnyOf):
        raise ValueError("a derived source must resolve to one Audience")
    return aud


def _derived_type_audience(obj: Any, sources: Iterable[Any] | None) -> Audience:
    entry = _derived_type(getattr(obj, "derived_type"))
    sources = list(sources if sources is not None else getattr(obj, "derived_sources", None) or [])
    if not sources:
        return GM_AUDIENCE
    auds = []
    for s in sources:
        kind = getattr(s, "ref_kind", None) if not isinstance(s, Mapping) else s.get("ref_kind")
        if kind is not None and kind not in entry.derive_from:
            raise ValueError(f"{entry.derived_type!r} does not derive from ref_kind {kind!r} "
                             f"(derive_from: {list(entry.derive_from)})")
        if isinstance(s, Mapping):
            s = s.get("audience") or s.get("ref")
        auds.append(_source_audience(s))
    return most_restrictive(auds)


# ── Derived from sources (stored_files) ─────────────────────────────────────

# ref_kind -> the model whose `id` a derived_sources.ref_id names. Feature
# epics add theirs with register_source_kind (E0-WorldCore: `entity`, ...).
SOURCE_KIND_MODELS: dict[str, type] = {
    "journal": JournalEntry,
}


def register_source_kind(ref_kind: str, model: type) -> None:
    """Let `derived_sources.ref_kind = ref_kind` resolve to rows of `model`
    (a registered, Campaign-scoped model with an `id` key whose Audience
    needs no parents: stored, always_gm or membership)."""
    if not isinstance(ref_kind, str) or not ref_kind:
        raise TypeError(f"register_source_kind: ref_kind must be a non-empty str, got {ref_kind!r}")
    if ref_kind in SOURCE_KIND_MODELS:
        raise ValueError(f"register_source_kind: {ref_kind!r} is already registered")
    reg = registration(model)
    if isinstance(reg, (Derived, DerivedFromSources)):
        raise ValueError(f"register_source_kind: {model.__name__} is derived; its Audience needs its parents")
    if scope_column(model) is None:
        raise ValueError(f"register_source_kind: {model.__name__} has no Campaign scope")
    if not hasattr(model, "id"):
        raise ValueError(f"register_source_kind: {model.__name__} has no `id` column")
    SOURCE_KIND_MODELS[ref_kind] = model


def _source_gm_fields(src: type) -> list[str]:
    """The ref_field values that make a source GM: the always-GM fields plus
    the source model's own gm_fields."""
    return sorted(ALWAYS_GM_FIELDS | set(registration(src).gm_fields))


def _derived_types() -> list[DerivedType]:
    return [_derived_entry(raw) for raw in DERIVED_REGISTRY]


def _sources_clause(model: type, reg: DerivedFromSources, ctx: "CampaignContext"):
    """SQL twin of `_sources_audience`. Every comparison is on a NOT NULL
    column or NULL-guarded, so `NOT ok(ds)` is never NULL (fail closed)."""
    viewer = ctx.audience
    if viewer.level is AudienceLevel.GM:
        return sa.true()
    ds = aliased(DerivedSource, name="ds")
    kind = _col(model, reg.kind_field)
    owner_col = _col(model, reg.owner_field)
    types = _derived_types()
    if viewer.level is AudienceLevel.OWNER:
        owner_ok = sa.or_(owner_col.is_(None), owner_col == viewer.user_id)
    else:
        owner_ok = owner_col.is_(None)

    branches = []
    for ref_kind, src in SOURCE_KIND_MODELS.items():
        allowed = [t.derived_type for t in types if ref_kind in t.derive_from]
        if not allowed:
            continue
        where = [_col(src, "id") == ds.ref_id]
        scope = scope_column(src)
        if scope is not None:
            where.append(scope == ctx.campaign_id)
        where.append(visible_clause(src, ctx))
        field_ok = sa.or_(ds.ref_field.is_(None), ds.ref_field.notin_(_source_gm_fields(src)))
        branches.append(sa.and_(ds.ref_kind == ref_kind, kind.in_(allowed), field_ok, sa.exists().where(*where)))
    ok = sa.or_(*branches) if branches else sa.false()

    link = sa.and_(ds.derived_type == kind, ds.derived_id == _col(model, reg.id_field))
    return sa.and_(
        sa.not_(_col(model, reg.stale_field)),
        kind.in_([t.derived_type for t in types]),
        owner_ok,
        sa.exists().where(link),
        sa.not_(sa.exists().where(link, sa.not_(ok))),
    )


def _source_row_audience(obj: Any, entry: DerivedType, source: Any, ref: Any) -> Audience | None:
    """The Audience one (derived_sources row, source row) pair contributes,
    or None when it cannot be resolved or is not allowed."""
    if source.ref_kind not in entry.derive_from:
        return None
    src = SOURCE_KIND_MODELS.get(source.ref_kind)
    if src is None or ref is None or not isinstance(ref, src) or ref.id != source.ref_id:
        return None
    scope = scope_column(src)
    if scope is not None and getattr(ref, scope.key) != getattr(obj, "campaign_id"):
        return None
    aud = audience_of(ref)
    if isinstance(aud, AnyOf):
        return None
    if source.ref_field is not None and str(source.ref_field) in _source_gm_fields(src):
        return GM_AUDIENCE
    return aud


def _sources_audience(obj: Any, reg: DerivedFromSources, parents: Any) -> Audience:
    """`parents` is the file's sources as `(derived_sources row, source row or
    None)` pairs. GM when the file is stale, its kind is unregistered, it has
    no sources, or any source is unresolvable or not allowed; else the most
    restrictive of the sources (with their ref_field) and Owner(audience_owner_id)."""
    if parents is None:
        raise ValueError(f"audience_of: {type(obj).__name__} needs parents=[(derived_source, source_row), ...]")
    pairs = list(parents) if isinstance(parents, (list, tuple)) else [parents]
    kind, row_id = getattr(obj, reg.kind_field), getattr(obj, reg.id_field)
    for pair in pairs:
        if not (isinstance(pair, tuple) and len(pair) == 2):
            raise TypeError(f"audience_of: expected (derived_source, source_row) pairs, got {pair!r}")
        if pair[0].derived_type != kind or pair[0].derived_id != row_id:
            raise ValueError(f"audience_of: {pair[0]!r} is not a source of this {type(obj).__name__}")
    entry = _derived_type(kind, missing_ok=True)
    if getattr(obj, reg.stale_field) or entry is None or not pairs:
        return GM_AUDIENCE
    auds: list[Audience] = []
    for source, ref in pairs:
        aud = _source_row_audience(obj, entry, source, ref)
        if aud is None:
            return GM_AUDIENCE
        auds.append(aud)
    owner_id = getattr(obj, reg.owner_field)
    if owner_id is not None:
        auds.append(owner(owner_id))
    return most_restrictive(auds)


def _loaded(obj: Any, attr: str) -> Any:
    state = sa.inspect(obj)
    if attr in state.unloaded:
        raise ValueError(f"audience_of: {type(obj).__name__}.{attr} is not loaded; pass parents=")
    return getattr(obj, attr)


def _as_audience(value: Any) -> Audience | AnyOf:
    if isinstance(value, (Audience, AnyOf)):
        return value
    return audience_of(value)


def audience_of(obj: Any, *, parents: Any = None) -> Audience | AnyOf:
    """The Audience of `obj` from its registration (the Python twin of
    `visible_clause`). Derived rows read their parents from `parents=`
    (objects or Audiences, one per `parent(...)` link, or the reaching
    children for `reached_through`) or from a loaded relationship."""
    reg = REGISTRY.get(type(obj))
    if reg is None:
        if hasattr(obj, "derived_type"):
            return _derived_type_audience(obj, parents)
        raise UnregisteredModel(f"{type(obj).__name__!r} has no access registration (app/access/registry.py)")
    if isinstance(reg, Stored):
        owner_id = getattr(obj, reg.owner_field)
        if reg.column is None:
            return owner(owner_id) if owner_id is not None else GM_AUDIENCE
        kind = getattr(obj, reg.kind_field) if reg.kind_field else None
        return stored_audience(getattr(obj, reg.column), owner_id, kind)
    if isinstance(reg, AlwaysGM):
        owner_id = getattr(obj, reg.owner_field) if reg.owner_field is not None else None
        return owner(owner_id) if owner_id is not None else GM_AUDIENCE
    if isinstance(reg, Membership):
        return reg.audience
    if isinstance(reg, DerivedFromSources):
        return _sources_audience(obj, reg, parents)
    # Derived
    links = reg.derive_from
    if isinstance(links[0], ReachedThrough):
        if parents is None:
            raise ValueError(f"audience_of: {type(obj).__name__} is reached through children; pass parents=")
        children = parents if isinstance(parents, (list, tuple)) else [parents]
        out: list[Audience] = []
        for c in children:
            aud = _as_audience(c)
            out.extend(aud.audiences if isinstance(aud, AnyOf) else [aud])
        return AnyOf(out)
    if parents is None:
        if any(link.attr is None for link in links):
            raise ValueError(f"audience_of: {type(obj).__name__} has no parent relationship; pass parents=")
        given = [_loaded(obj, link.attr) for link in links]
    else:
        given = list(parents) if isinstance(parents, (list, tuple)) else [parents]
        if len(given) != len(links):
            raise ValueError(f"audience_of: {type(obj).__name__} needs {len(links)} parent(s), got {len(given)}")
    auds: list[Audience] = []
    for g in given:
        if g is None:
            return GM_AUDIENCE  # an orphan is nobody's
        aud = _as_audience(g)
        if isinstance(aud, AnyOf):
            raise ValueError("audience_of: a parent must resolve to one Audience")
        auds.append(aud)
    if reg.field is not None:
        auds.append(field_audience(getattr(obj, reg.field)))
    return most_restrictive(auds)


def gm_fields(model: type) -> tuple[str, ...]:
    """The GM-only fields of `model` (for E0-Access.4's `project`)."""
    return registration(model).gm_fields


# ── Import-time completeness ───────────────────────────────────────────────

_REACHED_TABLES = frozenset({"tags", "journal_tags"})


def _check_complete() -> None:
    registered = {m.__tablename__ for m in REGISTRY}
    missing = []
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        name = table.name
        if name in registered or name in UNSCOPED:
            continue
        if "campaign_id" in table.c or name in _REACHED_TABLES:
            missing.append(name)
    stale = sorted(set(UNSCOPED) & registered)
    if missing or stale:
        raise RuntimeError(
            "app/access/registry.py: every Campaign-scoped table must be registered (stored / derived / "
            f"always_gm / membership) or listed in UNSCOPED with a reason. Unregistered: {sorted(missing)}; "
            f"both registered and UNSCOPED: {stale}"
        )
    for model, reg in REGISTRY.items():
        # A global table may only be always_gm; scoped_select refuses it.
        if scope_column(model) is None and not isinstance(reg, (Derived, AlwaysGM)):
            raise RuntimeError(f"app/access/registry.py: {model.__name__} has no Campaign scope column")


_check_complete()
