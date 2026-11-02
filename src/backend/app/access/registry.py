"""The access registry (AD-12, AD-13): one declaration per model of how its
Audience is computed, and the two predicates generated from it.

    stmt = scoped_select(JournalEntry, ctx).order_by(JournalEntry.created_at)
    row = await scoped_get(db, SessionPlan, ctx, plan_id)   # not_found() if hidden or missing

Each model registers exactly one class:

  * `stored(column="visibility", owner_field="user_id", kind_field=None,
    field_visibility=None, writer=None, floor=None, narrowed_by=(), gm_when=())`: the
    row carries its Visibility. `column=None` means every row is
    Owner(owner_field) (chat sessions). `owner_field=None` means the row has
    no author: `private` is then GM (entity_relationships). `writer`
    (E0-Access.9) is the function `set_visibility` writes through. `floor`
    is a nullable Visibility column that narrows the row further (the merge
    `visibility_floor`, AD-10); `narrowed_by` are `parent(...)` links whose
    Audiences narrow it too (an edge is never wider than either endpoint).
    `gm_when` are nullable columns any of which, set, makes the row GM
    (a soft-deleted or merged Entity). `register_writer(model, fn)` sets
    `writer` after the fact (world_service registers `apply_change`'s).
  * `derived(derive_from=[...], field=None, floor=None, field_rule="audience")`:
    the row's Audience comes from other rows, through `parent(...)` links
    (the most restrictive parent, plus a `field=` rule such as
    `journal_tags.source_field`, plus a `floor`), or through
    `reached_through(...)` (any one visible child is enough: tags). With
    `field_rule="parent_field"` the `field` column names a field of the
    first parent instead (entity_changes.field): an always-GM field, one of
    the parent's gm_fields, its `field_visibility` (or a key of it) and
    `visibility_floor` are GM; otherwise the parent's
    `field_visibility[field]` and `field_visibility[<field up to its first
    '.'>]`, when set, narrow the row. A NULL field is GM unless the row's
    `op_field` is in `public_null_ops`. A derived row with
    a NULL parent link (an orphan: entity_mentions.journal_id after its
    entry was deleted) is GM.
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

import dataclasses
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import app.db.models  # noqa: F401  (every model is mapped before the completeness check)
from app.access.audience import (
    GM_AUDIENCE, MEMBERS, PUBLIC, ALWAYS_GM_FIELDS, AnyOf, Audience, AudienceLevel, covers, field_audience,
    most_restrictive, owner, stored_audience, visible_to,
)
from app.access.policy import not_found
from app.db.base import Base
from app.db.models.campaign import Campaign
from app.db.models.campaign_member import CampaignMember
from app.db.models.character_sheet import CharacterSheet, CharacterSheetTemplate
from app.db.models.chat import ChatSession
from app.db.models.entity import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, QuestStep, RelationshipType,
)
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


FIELD_RULE_AUDIENCE = "audience"
FIELD_RULE_PARENT_FIELD = "parent_field"
VISIBILITY_FLOOR = "visibility_floor"


# ── Registration classes ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Parent:
    """The row derives from `model` through `fk` (its column) = `model.<remote>`.
    `attr` is the relationship that loads the parent object, if any."""

    model: type
    fk: str
    remote: str = "id"
    attr: str | None = None


@dataclass(frozen=True)
class Stored:
    column: str | None = "visibility"
    owner_field: str | None = "user_id"
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
    # A writer must not call `mark_dependents_stale` itself: set_visibility
    # does that once, after the writer returns.
    writer: Callable[..., Any] | None = None
    # A nullable Visibility column that narrows the row (NULL: no narrowing).
    floor: str | None = None
    # Parents whose Audiences narrow the row (entity_relationships: both endpoints).
    narrowed_by: tuple[Parent, ...] = ()
    # Nullable columns any of which, when set, makes the row GM whatever its
    # Visibility (entities: a soft-deleted or merged-away Entity, E0-WorldCore.3).
    gm_when: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.column is None and self.owner_field is None:
            raise ValueError("stored: column=None (every row is its Owner's) needs an owner_field")
        if any(not isinstance(link, Parent) for link in self.narrowed_by):
            raise ValueError("stored: narrowed_by takes parent(...) links")
        if any(not isinstance(name, str) or not name for name in self.gm_when):
            raise ValueError("stored: gm_when takes column names")
        if self.gm_when and self.column is None:
            raise ValueError("stored: gm_when needs a Visibility column")


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
    # A nullable Visibility column that narrows the row (NULL: no narrowing).
    floor: str | None = None
    # How `field` narrows: "audience" (field_audience of its value) or
    # "parent_field" (it names a field of the first parent; module docstring).
    field_rule: str = FIELD_RULE_AUDIENCE
    # parent_field only: a NULL `field` (a whole-row snapshot) is GM unless the
    # row's `op_field` is one of `public_null_ops` (entity_changes: migrated).
    op_field: str | None = None
    public_null_ops: tuple[str, ...] = ()
    # parent_field only: keys inside the row's JSON values (at any depth) that
    # carry another field of the parent, as (key, parent field) pairs. A Quest
    # status row holds `completed_at`, which is `attributes.completed_at`.
    # `access.project` drops such a key for a viewer that field's Audience
    # does not cover (`hidden_value_keys`), so a history row never shows a
    # value the viewer cannot see on the parent itself.
    value_fields: tuple[tuple[str, str], ...] = ()
    # parent_field only: a row whose `field` is X also carries parent field Y,
    # as (X, Y) pairs. A completion stamp reveals a Quest's status, so an
    # `attributes.completed_at` row's values are redacted for a viewer who may
    # not see `status` (the Entity projection drops completed_at likewise).
    field_requires: tuple[tuple[str, str], ...] = ()
    # parent_field only: keys inside the row's JSON values (at any depth) that
    # only a GM sees, whatever the field (provenance: a `source_deleted` row's
    # `journal_id`, which the Party schema leaves out as `source_journal_id`).
    gm_value_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.derive_from:
            raise ValueError("derived: derive_from needs at least one link")
        kinds = {type(link) for link in self.derive_from}
        if len(kinds) > 1:
            raise ValueError("derived: links are all parent(...) or all reached_through(...)")
        if self.field_rule not in (FIELD_RULE_AUDIENCE, FIELD_RULE_PARENT_FIELD):
            raise ValueError(f"derived: unknown field_rule {self.field_rule!r}")
        if self.field_rule == FIELD_RULE_PARENT_FIELD and (
                self.field is None or not isinstance(self.derive_from[0], Parent)):
            raise ValueError("derived: field_rule='parent_field' needs a field and a parent(...) link")
        if self.floor is not None and not isinstance(self.derive_from[0], Parent):
            raise ValueError("derived: a floor needs parent(...) links")
        if (self.value_fields or self.field_requires or self.gm_value_keys) and \
                self.field_rule != FIELD_RULE_PARENT_FIELD:
            raise ValueError("derived: value_fields, field_requires and gm_value_keys need field_rule='parent_field'")


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


def stored(column: str | None = "visibility", owner_field: str | None = "user_id", kind_field: str | None = None,
           field_visibility: str | None = None, *, gm_fields: Iterable[str] = (),
           writer: Callable[..., Any] | None = None, floor: str | None = None,
           narrowed_by: Sequence[Parent] = (), gm_when: Iterable[str] = ()) -> Stored:
    return Stored(column, owner_field, kind_field, field_visibility, tuple(gm_fields), writer, floor,
                  tuple(narrowed_by), tuple(gm_when))


def parent(model: type, fk: str, *, remote: str = "id", attr: str | None = None) -> Parent:
    return Parent(model, fk, remote, attr)


def reached_through(child: type, fk: str, *, remote: str = "id") -> ReachedThrough:
    return ReachedThrough(child, fk, remote)


def derived(derive_from: Sequence[Parent | ReachedThrough], *, field: str | None = None,
            gm_fields: Iterable[str] = (), floor: str | None = None,
            field_rule: str = FIELD_RULE_AUDIENCE, op_field: str | None = None,
            public_null_ops: Iterable[str] = (), value_fields: Mapping[str, str] | None = None,
            field_requires: Mapping[str, str] | None = None, gm_value_keys: Iterable[str] = ()) -> Derived:
    return Derived(tuple(derive_from), field, tuple(gm_fields), floor, field_rule, op_field,
                   tuple(public_null_ops), tuple(sorted((value_fields or {}).items())),
                   tuple(sorted((field_requires or {}).items())), tuple(gm_value_keys))


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
    # E0-WorldCore.2 (F3-world). Every copied Entity starts GM. A soft-deleted
    # or merged-away Entity is GM only (E0-WorldCore.3), and so is every row
    # derived from or narrowed by it. world_service registers its writer.
    Entity: stored(owner_field="created_by_user_id", field_visibility="field_visibility", gm_fields=("gm_notes",),
                   gm_when=("deleted_at", "merged_into_id")),
    # An edge is never wider than either endpoint (FR-25), nor than its merge floor.
    EntityRelationship: stored(owner_field=None, floor=VISIBILITY_FLOOR, narrowed_by=[
        parent(Entity, "source_entity_id", attr="source_entity"),
        parent(Entity, "target_entity_id", attr="target_entity"),
    ]),
    # A Campaign's relationship vocabulary, like character_sheet_templates.
    RelationshipType: membership(PUBLIC),
    EntityAlias: derived([parent(Entity, "entity_id", attr="entity")], floor=VISIBILITY_FLOOR),
    QuestStep: derived([parent(Entity, "quest_entity_id", attr="quest")]),
    # AD-12: most_restrictive(entry, entity, field_aud(source_field), visibility_floor).
    EntityMention: derived([parent(JournalEntry, "journal_id", attr="journal"),
                            parent(Entity, "entity_id", attr="entity")],
                           field="source_field", floor=VISIBILITY_FLOOR),
    # The Entity's Audience, narrowed by the changed field's own Visibility.
    # A change with no field (create, delete, merge snapshots may hold gm_notes)
    # is GM, except the content-free `migrated` row.
    EntityChange: derived([parent(Entity, "entity_id", attr="entity")], field="field",
                          field_rule=FIELD_RULE_PARENT_FIELD, op_field="op", public_null_ops=("migrated",),
                          # A Quest's status rows hold {status, completed_at} (E0-WorldCore.3).
                          value_fields={"completed_at": "attributes.completed_at"},
                          field_requires={"attributes.completed_at": "status"},
                          # source_deleted rows: which entry (GM provenance).
                          gm_value_keys=("journal_id",)),
}

# Tables with a campaign_id that are not Campaign content, with the reason.
UNSCOPED: dict[str, str] = {
    "feedback": "operator feedback, read by user_id (and by admins), not Campaign content",
}


def register_writer(model: type, fn: Callable[..., Any]) -> Stored:
    """Make `fn` the `writer` of a stored model's Visibility columns (the
    function `set_visibility` writes through, E0-Access.9). Registering the
    same function again is a no-op; a different one raises ValueError, and so
    does a model that is not `stored` with a Visibility column."""
    reg = registration(model)
    if not isinstance(reg, Stored) or reg.column is None:
        raise ValueError(f"register_writer: {getattr(model, '__name__', model)!r} is not a stored model with a "
                         "Visibility column")
    if not callable(fn):
        raise TypeError("register_writer: fn must be callable")
    if reg.writer is not None:
        if reg.writer is fn:
            return reg
        raise ValueError(f"register_writer: {model.__name__} already has the writer {reg.writer!r}")
    updated = dataclasses.replace(reg, writer=fn)
    REGISTRY[model] = updated
    return updated


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


def _vis_clause(vis, owner_col, kind_col, viewer: Audience):
    """SQL twin of `covers(stored_audience(vis, owner, kind), viewer)` for a
    non-GM viewer (`vis` may be any text expression; NULL is hidden)."""
    level = viewer.level
    if level is AudienceLevel.OWNER:
        if owner_col is None:
            return vis == Visibility.PARTY.value
        return sa.or_(vis == Visibility.PARTY.value,
                      sa.and_(vis == Visibility.PRIVATE.value, owner_col == viewer.user_id))
    if level is AudienceLevel.MEMBERS or kind_col is None:
        return vis == Visibility.PARTY.value
    # Public
    return sa.and_(vis == Visibility.PARTY.value, kind_col == EntryKind.GM.value)


def _floor_clause(model: type, floor: str | None, viewer: Audience):
    """A floor narrows like a stored Visibility with no owner: only `party`
    (or NULL, no floor) is wider than GM."""
    if floor is None or viewer.level is AudienceLevel.GM:
        return sa.true()
    col = _col(model, floor)
    return sa.or_(col.is_(None), col == Visibility.PARTY.value)


def _parent_exists(model: type, link: Parent, ctx: "CampaignContext", extra: Sequence[Any] = ()):
    target = link.model
    scope = scope_column(target)
    where = [_col(target, link.remote) == _col(model, link.fk)]
    if scope is not None:
        where.append(scope == ctx.campaign_id)
    where.append(visible_clause(target, ctx))
    where.extend(extra)
    return sa.exists().where(*where)


def _stored_clause(model: type, reg: Stored, ctx: "CampaignContext"):
    viewer = ctx.audience
    level = viewer.level
    if level is AudienceLevel.GM:
        return sa.true()
    owner_col = _col(model, reg.owner_field) if reg.owner_field is not None else None
    if reg.column is None:  # every row is Owner(owner)
        return owner_col == viewer.user_id if level is AudienceLevel.OWNER else sa.false()
    kind_col = _col(model, reg.kind_field) if reg.kind_field is not None else None
    base = _vis_clause(_col(model, reg.column), owner_col, kind_col, viewer)
    if reg.gm_when:
        base = sa.and_(base, *[_col(model, name).is_(None) for name in reg.gm_when])
    if reg.floor is None and not reg.narrowed_by:
        return base
    return sa.and_(base, _floor_clause(model, reg.floor, viewer),
                   *[_parent_exists(model, link, ctx) for link in reg.narrowed_by])


def _field_clause(model: type, reg: Derived, viewer: Audience):
    if reg.field is None or viewer.level is AudienceLevel.GM or reg.field_rule != FIELD_RULE_AUDIENCE:
        return sa.true()
    col = _col(model, reg.field)
    return sa.or_(col.is_(None), col.notin_(_gm_valued_fields()))


def _parent_gm_change_fields(reg: Stored) -> list[str]:
    """Field names whose changes are GM whatever the parent's Visibility."""
    names = set(ALWAYS_GM_FIELDS) | set(reg.gm_fields) | {VISIBILITY_FLOOR}
    if reg.field_visibility:
        names.add(reg.field_visibility)
    return sorted(names)


def _parent_field_clause(model: type, reg: Derived, target: type, viewer: Audience):
    """`field_rule="parent_field"`, inside the first parent's EXISTS (SQL
    twin of `_parent_field_audience`)."""
    if viewer.level is AudienceLevel.GM:
        return sa.true()
    preg = registration(target)
    if not isinstance(preg, Stored):
        raise TypeError(f"{model.__name__}: field_rule='parent_field' needs a stored parent")
    f = _col(model, reg.field)
    # "attributes.region" is also narrowed by "attributes" (its part before the first '.').
    head = sa.func.split_part(f, ".", 1)
    gm_names = _parent_gm_change_fields(preg)
    allowed = [f.notin_(gm_names), head.notin_(gm_names)]
    if preg.field_visibility:
        allowed.append(sa.not_(f.startswith(preg.field_visibility + ".", autoescape=True)))
        owner_col = _col(target, preg.owner_field) if preg.owner_field is not None else None
        kind_col = _col(target, preg.kind_field) if preg.kind_field is not None else None
        for key in (f, head):
            per_field = _col(target, preg.field_visibility).op("->>")(key)
            allowed.append(sa.or_(per_field.is_(None), _vis_clause(per_field, owner_col, kind_col, viewer)))
    if reg.op_field is not None and reg.public_null_ops:
        null_ok = _col(model, reg.op_field).in_(list(reg.public_null_ops))
    else:
        null_ok = sa.false()
    return sa.or_(sa.and_(f.is_(None), null_ok), sa.and_(f.isnot(None), *allowed))


def _derived_clause(model: type, reg: Derived, ctx: "CampaignContext"):
    clauses = []
    own_scope = scope_column(model) is not None
    for i, link in enumerate(reg.derive_from):
        if isinstance(link, Parent):
            extra = []
            if i == 0 and reg.field_rule == FIELD_RULE_PARENT_FIELD:
                extra.append(_parent_field_clause(model, reg, link.model, ctx.audience))
            clause = _parent_exists(model, link, ctx, extra)
            fk = _col(model, link.fk)
            if ctx.audience.level is AudienceLevel.GM and own_scope and sa.inspect(model).columns[link.fk].nullable:
                # An orphan (its parent deleted, fk SET NULL) is GM: a GM still sees it.
                clause = sa.or_(fk.is_(None), clause)
            clauses.append(clause)
        else:
            child = link.child
            clauses.append(sa.exists().where(_col(child, link.fk) == _col(model, link.remote),
                                             visible_clause(child, ctx)))
    combined = sa.and_(*clauses) if isinstance(reg.derive_from[0], Parent) else sa.or_(*clauses)
    return sa.and_(combined, _field_clause(model, reg, ctx.audience), _floor_clause(model, reg.floor, ctx.audience))


def visible_clause(model: type, ctx: "CampaignContext"):
    """The SQL predicate "this row's Audience covers ctx.audience" for
    `model` (no Campaign scope for models with their own campaign column;
    derived models are scoped through their parents)."""
    reg = registration(model)
    viewer = ctx.audience
    if isinstance(reg, Stored):
        return _stored_clause(model, reg, ctx)
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
        owner_id = getattr(obj, reg.owner_field) if reg.owner_field is not None else None
        if reg.column is None:
            return owner(owner_id) if owner_id is not None else GM_AUDIENCE
        kind = getattr(obj, reg.kind_field) if reg.kind_field else None
        return narrowed_audience(obj, reg, stored_audience(getattr(obj, reg.column), owner_id, kind), parents)
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
    given = _given_parents(obj, links, parents)
    auds: list[Audience] = []
    for g in given:
        if g is None:
            return GM_AUDIENCE  # an orphan is nobody's
        auds.append(_one_audience(g))
    if reg.field is not None:
        if reg.field_rule == FIELD_RULE_PARENT_FIELD:
            auds.append(_parent_field_audience(obj, reg, links[0].model, given[0]))
        else:
            auds.append(field_audience(getattr(obj, reg.field)))
    if reg.floor is not None:
        auds.append(floor_audience(getattr(obj, reg.floor)))
    return most_restrictive(auds)


def narrowed_audience(obj: Any, reg: Stored, base: Audience, parents: Any = None, *,
                      floor_value: Any = None) -> Audience:
    """`base` (a stored row's own Audience) narrowed by its `floor` and its
    `narrowed_by` parents (from `parents=`, else the loaded relationships;
    an unloaded one raises ValueError). `floor_value` stands in for a floor
    column that is still None (check_create: its column default). Any `gm_when`
    column that is set makes it GM."""
    if any(getattr(obj, name, None) is not None for name in reg.gm_when):
        return GM_AUDIENCE
    if reg.floor is None and not reg.narrowed_by:
        return base
    auds = [base]
    if reg.floor:
        value = getattr(obj, reg.floor)
        auds.append(floor_audience(value if value is not None else floor_value))
    for g in _given_parents(obj, reg.narrowed_by, parents):
        if g is None:
            return GM_AUDIENCE  # an orphan is nobody's
        auds.append(_one_audience(g))
    return most_restrictive(auds)


def _given_parents(obj: Any, links: Sequence[Parent], parents: Any) -> list[Any]:
    """One parent (object, Audience or None) per link: from `parents=`, else
    from the loaded relationships."""
    if parents is None:
        if any(link.attr is None for link in links):
            raise ValueError(f"audience_of: {type(obj).__name__} has no parent relationship; pass parents=")
        return [_loaded(obj, link.attr) for link in links]
    given = list(parents) if isinstance(parents, (list, tuple)) else [parents]
    if len(given) != len(links):
        raise ValueError(f"audience_of: {type(obj).__name__} needs {len(links)} parent(s), got {len(given)}")
    return given


def _one_audience(parent_obj: Any) -> Audience:
    aud = _as_audience(parent_obj)
    if isinstance(aud, AnyOf):
        raise ValueError("audience_of: a parent must resolve to one Audience")
    return aud


def floor_audience(value: Any) -> Audience:
    """The Audience a Visibility floor allows: NULL (no floor) and `party`
    are Public, `gm` and `private` (no owner) are GM."""
    if value is None:
        return PUBLIC
    return _safe_stored_audience(value, None, None)


def _safe_stored_audience(vis: Any, owner_id: Any, kind: Any) -> Audience:
    """stored_audience, GM for a value that is not a Visibility (fail closed)."""
    try:
        return stored_audience(vis, owner_id, kind)
    except ValueError:
        return GM_AUDIENCE


def _parent_field_audience(obj: Any, reg: Derived, parent_model: type, parent_obj: Any) -> Audience:
    """`field_rule="parent_field"`: the Audience the changed field allows."""
    if isinstance(parent_obj, (Audience, AnyOf)):
        raise ValueError(f"audience_of: {type(obj).__name__} needs its parent row (not an Audience) for its "
                         "field rule")
    preg = registration(parent_model)
    if not isinstance(preg, Stored):
        raise TypeError(f"{type(obj).__name__}: field_rule='parent_field' needs a stored parent")
    value = getattr(obj, reg.field)
    if value is None:
        op = getattr(obj, reg.op_field) if reg.op_field is not None else None
        return PUBLIC if op is not None and str(op) in reg.public_null_ops else GM_AUDIENCE
    return parent_field_audience(parent_model, parent_obj, str(value))


def parent_field_audience(parent_model: type, parent_obj: Any, name: str) -> Audience:
    """The Audience that may see field `name` of `parent_obj` (a stored row
    with field visibility, e.g. an Entity): GM for an always-GM field, a
    gm_field, `field_visibility`/`visibility_floor` and their keys; otherwise
    narrowed by `field_visibility[name]` and `field_visibility[<name up to its
    first '.'>]`. The rule a `parent_field` history row is read by."""
    preg = registration(parent_model)
    if not isinstance(preg, Stored):
        raise TypeError(f"parent_field_audience: {parent_model.__name__} is not a stored model")
    head = name.split(".", 1)[0]
    gm_names = _parent_gm_change_fields(preg)
    if name in gm_names or head in gm_names:
        return GM_AUDIENCE
    if not preg.field_visibility:
        return PUBLIC
    if name.startswith(preg.field_visibility + "."):
        return GM_AUDIENCE
    per_field = getattr(parent_obj, preg.field_visibility, None) or {}
    if not isinstance(per_field, Mapping):
        per_field = {}
    owner_id = getattr(parent_obj, preg.owner_field) if preg.owner_field is not None else None
    kind = getattr(parent_obj, preg.kind_field) if preg.kind_field else None
    auds = [PUBLIC]
    for key in {name, head}:
        vis = per_field.get(key)
        if vis is not None:
            auds.append(_safe_stored_audience(vis, owner_id, kind))
    return most_restrictive(auds)


def hidden_row_values(obj: Any, ctx: "CampaignContext", parent_obj: Any = None) -> bool:
    """True when ctx may not see a derived row's values at all: its `field`
    has a `field_requires` partner field that ctx may not see on the parent
    (no parent row: True for a non-GM, fail closed). False for a GM ctx."""
    reg = REGISTRY.get(type(obj))
    if not isinstance(reg, Derived) or not reg.field_requires or ctx.audience.level is AudienceLevel.GM:
        return False
    name = getattr(obj, reg.field, None)
    partners = [other for field_name, other in reg.field_requires if field_name == name]
    if not partners:
        return False
    if parent_obj is None:
        return True
    parent_model = reg.derive_from[0].model
    return any(not visible_to(parent_field_audience(parent_model, parent_obj, other), ctx) for other in partners)


def hidden_value_keys(obj: Any, ctx: "CampaignContext", parent_obj: Any = None) -> frozenset[str]:
    """The keys inside a derived row's JSON values that ctx may not see: its
    `gm_value_keys`, and the `value_fields` keys whose parent field's Audience
    does not cover ctx. With no parent row (not loaded, not given), every
    value_fields key is hidden from a non-GM (fail closed). Empty for a GM
    ctx and for models without either option."""
    reg = REGISTRY.get(type(obj))
    if not isinstance(reg, Derived) or not (reg.value_fields or reg.gm_value_keys) \
            or ctx.audience.level is AudienceLevel.GM:
        return frozenset()
    hidden = set(reg.gm_value_keys)
    if parent_obj is None:
        return frozenset(hidden | {key for key, _field in reg.value_fields})
    parent_model = reg.derive_from[0].model
    hidden.update(key for key, field_name in reg.value_fields
                  if not visible_to(parent_field_audience(parent_model, parent_obj, field_name), ctx))
    return frozenset(hidden)


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
        if isinstance(reg, Derived) and reg.field_rule == FIELD_RULE_PARENT_FIELD and not isinstance(
                REGISTRY.get(reg.derive_from[0].model), Stored):
            raise RuntimeError(f"app/access/registry.py: {model.__name__}'s parent_field rule needs a stored parent")
        # A global table may only be always_gm; scoped_select refuses it.
        if scope_column(model) is None and not isinstance(reg, (Derived, AlwaysGM)):
            raise RuntimeError(f"app/access/registry.py: {model.__name__} has no Campaign scope column")


_check_complete()
