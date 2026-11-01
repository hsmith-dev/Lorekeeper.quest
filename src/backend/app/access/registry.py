"""The access registry (AD-12, AD-13): one declaration per model of how its
Audience is computed, and the two predicates generated from it.

    stmt = scoped_select(JournalEntry, ctx).order_by(JournalEntry.created_at)
    row = await scoped_get(db, SessionPlan, ctx, plan_id)   # not_found() if hidden or missing

Each model registers exactly one class:

  * `stored(column="visibility", owner_field="user_id", kind_field=None,
    field_visibility=None)`: the row carries its Visibility. `column=None`
    means every row is Owner(owner_field) (chat sessions).
  * `derived(derive_from=[...])`: the row's Audience comes from other rows,
    through `parent(...)` links (the most restrictive parent, plus a
    `field=` rule such as `journal_tags.source_field`), or through
    `reached_through(...)` (any one visible child is enough: tags).
  * `always_gm()`: GM only (npcs and quests until F3-world, Decision B1-D4).
  * `membership(audience)`: a constant Audience for a membership-scoped
    table of the ctx's Campaign; management rules stay in the routes.

`visible_clause(Model, ctx)` (SQL) and `audience_of(obj)` (Python) are both
read from the same registration; tests/access/test_registry_property.py
(CI-11) proves they agree. `scoped_select` adds the Campaign scope.

`DERIVED_REGISTRY` lists derived types (file or not: E0-Jobs' derived
files, E4's `live_recap`), each `{derived_type, derive_from: [ref_kind, ...]}`;
`audience_of` on such an object is the most restrictive Audience of its
`derived_sources` (GM when it has none).

At import, every mapped table with a `campaign_id` column (plus `tags` and
`journal_tags`) must be registered or listed in `UNSCOPED` with a reason;
otherwise importing this module raises RuntimeError.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.session_plan import SessionPlan
from app.db.models.share_token import CampaignShareToken
from app.db.models.shorthand import ShorthandTerm
from app.db.models.source import SourceChunk, SourceDocument
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


@dataclass(frozen=True)
class Membership:
    audience: Audience
    gm_fields: tuple[str, ...] = ()


Registration = Stored | Derived | AlwaysGM | Membership


def stored(column: str | None = "visibility", owner_field: str = "user_id", kind_field: str | None = None,
           field_visibility: str | None = None, *, gm_fields: Iterable[str] = ()) -> Stored:
    return Stored(column, owner_field, kind_field, field_visibility, tuple(gm_fields))


def parent(model: type, fk: str, *, remote: str = "id", attr: str | None = None) -> Parent:
    return Parent(model, fk, remote, attr)


def reached_through(child: type, fk: str, *, remote: str = "id") -> ReachedThrough:
    return ReachedThrough(child, fk, remote)


def derived(derive_from: Sequence[Parent | ReachedThrough], *, field: str | None = None,
            gm_fields: Iterable[str] = ()) -> Derived:
    return Derived(tuple(derive_from), field, tuple(gm_fields))


def always_gm(*, gm_fields: Iterable[str] = ()) -> AlwaysGM:
    return AlwaysGM(tuple(gm_fields))


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
        return sa.true() if viewer.level is AudienceLevel.GM else sa.false()
    if isinstance(reg, Membership):
        return sa.true() if covers(reg.audience, viewer) else sa.false()
    raise TypeError(f"unknown registration {reg!r}")  # pragma: no cover


def scoped_select(model: type, ctx: "CampaignContext") -> sa.Select:
    """`select(model)` of the rows of ctx's Campaign that ctx may see."""
    reg = registration(model)
    stmt = sa.select(model)
    scope = scope_column(model)
    if scope is not None:
        stmt = stmt.where(scope == ctx.campaign_id)
    elif not isinstance(reg, Derived):  # pragma: no cover - guarded by the import check
        raise UnregisteredModel(f"{model.__name__!r} has no Campaign scope")
    return stmt.where(visible_clause(model, ctx))


async def scoped_get(db: AsyncSession, model: type, ctx: "CampaignContext", row_id: Any) -> Any:
    """The row `row_id` of `model` if it is in ctx's Campaign and visible to
    ctx; else the one `not_found()` (hidden and missing are the same)."""
    pk = sa.inspect(model).primary_key
    if len(pk) != 1:
        raise TypeError(f"scoped_get: {model.__name__!r} has a composite primary key")
    if not isinstance(row_id, uuid.UUID):
        try:
            row_id = uuid.UUID(str(row_id))
        except (TypeError, ValueError, AttributeError):
            not_found()
    row = (await db.execute(scoped_select(model, ctx).where(pk[0] == row_id))).scalar_one_or_none()
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


def register_derived(derived_type: str, derive_from: Iterable[str]) -> DerivedType:
    entry = DerivedType(str(derived_type), tuple(derive_from))
    if not entry.derive_from:
        raise ValueError("register_derived: derive_from needs at least one ref_kind")
    if _derived_type(entry.derived_type, missing_ok=True) is not None:
        raise ValueError(f"register_derived: {entry.derived_type!r} is already registered")
    DERIVED_REGISTRY.append(entry)
    return entry


def _derived_type(name: str, *, missing_ok: bool = False) -> DerivedType | None:
    for raw in DERIVED_REGISTRY:
        entry = raw if isinstance(raw, DerivedType) else DerivedType(raw["derived_type"],
                                                                      tuple(raw["derive_from"]))
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
        return GM_AUDIENCE
    if isinstance(reg, Membership):
        return reg.audience
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
        if scope_column(model) is None and not isinstance(reg, Derived):
            raise RuntimeError(f"app/access/registry.py: {model.__name__} has no Campaign scope column")


_check_complete()
