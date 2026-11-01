"""Party projections (E0-Access.4, AD-13): the only way a registered row
becomes a response body.

    entry = await scoped_get(db, JournalEntry, ctx, journal_id, options=[selectinload(...)])
    return (await project_all(db, [entry], ctx))[0]

`PROJECTIONS` maps each model (or `(model, variant)`) to its
`<X>GMResponse` / `<X>PartyResponse` pair from `app/schemas/<domain>.py`. A
GM ctx gets the GM schema; a Player (or the member preview) the Party
schema; anon (a Share Link) the anon schema, which is the Party schema
unless one is named (Campaign: `PublicCampaignResponse`).

`project(obj, ctx)`, in order:

  1. registration (an unregistered model raises `UnregisteredModel`);
  2. row visibility: a row of another Campaign, or whose Audience does not
     cover ctx (stored / always_gm / membership), is `not_found()`. Derived
     rows (tags) are trusted from the scoped query that loaded them;
  3. the schema for ctx's Role;
  4. the schema's fields read from the row;
  5. pruning: an entry's tag whose `journal_tags` link ctx may not see
     (`source_field=shorthand`) is dropped; a tag's `custom_category` ctx may
     not see (hidden, or of another Campaign) is None; a field hidden by
     `field_visibility` renders as the schema default (None when none);
  6. `extra` fields (counts, `is_owner`, `share_kind`) merged, then validated.

`project_all(db, rows, ctx)` takes one ctx or a `role_map` (a per-row
`role_ctx` by the row's Campaign) and preloads the `journal_tags` links of
entries, so `project` stays sync. `project` on a non-GM entry with tags and
no `links=` raises: a programming error, never a silent leak.

At import, every Party (and anon) schema is checked to carry no GM field:
none of the model's `gm_fields`, no always-GM field (`shorthand`,
`gm_notes`, `voice_notes`) and no `field_visibility`, at any depth, and no
nested GM schema.
"""
from __future__ import annotations

import typing
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import ALWAYS_GM_FIELDS, stored_audience, visible_to
from app.access.context import CampaignContext, role_ctx
from app.access.policy import ANON, GM, PLAYER, not_found
from app.access.registry import (
    Derived, Stored, UnregisteredModel, audience_of, gm_fields, registration, scope_column,
)
from app.db.models.campaign import Campaign
from app.db.models.character_sheet import CharacterSheet, CharacterSheetTemplate
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.tag import JournalTag, Tag
from app.schemas.campaign import CampaignGMResponse, CampaignPartyResponse
from app.schemas.character_sheet import (
    CharacterSheetGMResponse, CharacterSheetPartyResponse, TemplateGMResponse, TemplatePartyResponse,
)
from app.schemas.journal import JournalGMResponse, JournalLiteResponse, JournalPartyResponse
from app.schemas.npc import NpcGMResponse, NpcPartyResponse
from app.schemas.quest import QuestGMResponse, QuestPartyResponse
from app.schemas.share import PublicCampaignResponse
from app.schemas.tag import (
    TagGMResponse, TagPartyResponse, TagWithCountGMResponse, TagWithCountPartyResponse,
)

FIELD_VISIBILITY = "field_visibility"


@dataclass(frozen=True)
class Projection:
    gm: type[BaseModel]
    party: type[BaseModel]
    anon: type[BaseModel] | None = None  # None: anon gets the Party schema

    def for_role(self, role: str) -> type[BaseModel]:
        if role == GM:
            return self.gm
        if role == ANON:
            return self.anon or self.party
        if role == PLAYER:
            return self.party
        raise ValueError(f"project: unknown role {role!r}")


WITH_COUNT = "with_count"
# An entry in an NPC/Quest entry list: the GM gets the lite GM row, a
# non-GM the Party entry (E0-Access.7 serves it there).
LITE = "lite"

PROJECTIONS: dict[type | tuple[type, str], Projection] = {
    JournalEntry: Projection(JournalGMResponse, JournalPartyResponse),
    (JournalEntry, LITE): Projection(JournalLiteResponse, JournalPartyResponse),
    Tag: Projection(TagGMResponse, TagPartyResponse),
    (Tag, WITH_COUNT): Projection(TagWithCountGMResponse, TagWithCountPartyResponse),
    NpcEntry: Projection(NpcGMResponse, NpcPartyResponse),
    Quest: Projection(QuestGMResponse, QuestPartyResponse),
    CharacterSheet: Projection(CharacterSheetGMResponse, CharacterSheetPartyResponse),
    CharacterSheetTemplate: Projection(TemplateGMResponse, TemplatePartyResponse),
    Campaign: Projection(CampaignGMResponse, CampaignPartyResponse, anon=PublicCampaignResponse),
}


def _key_model(key: type | tuple[type, str]) -> type:
    return key[0] if isinstance(key, tuple) else key


def projection_for(model: type, variant: str | None = None) -> Projection:
    key: type | tuple[type, str] = (model, variant) if variant else model
    try:
        return PROJECTIONS[key]
    except KeyError:
        registration(model)  # UnregisteredModel first, if that is the problem
        raise UnregisteredModel(
            f"{model.__name__!r}{f' ({variant})' if variant else ''} has no projection (app/access/projection.py)"
        ) from None


def schema_for(model: type, ctx: CampaignContext, variant: str | None = None) -> type[BaseModel]:
    """The response schema ctx gets for `model`."""
    return projection_for(model, variant).for_role(ctx.role)


# ── Row visibility ─────────────────────────────────────────────────────────

def _row_campaign(obj: Any) -> uuid.UUID | None:
    if isinstance(obj, Campaign):
        return obj.id
    return getattr(obj, "campaign_id", None)


def _check_row(obj: Any, ctx: CampaignContext) -> None:
    """`not_found()` unless `obj` is in ctx's Campaign and its Audience covers
    ctx. Derived rows (tags) are trusted from the scoped query that loaded them."""
    model = type(obj)
    reg = registration(model)
    if isinstance(reg, Derived):
        return
    if scope_column(model) is not None and _row_campaign(obj) != ctx.campaign_id:
        not_found()
    if not visible_to(audience_of(obj), ctx):
        not_found()


def _column_default(model: type, name: str) -> Any:
    col = sa.inspect(model).columns.get(name)
    default = getattr(col, "default", None) if col is not None else None
    arg = getattr(default, "arg", None)
    return None if callable(arg) else arg


def check_create(obj: Any, ctx: CampaignContext) -> None:
    """Refuse (`not_found()`) a create whose new row ctx could not see, before
    anything is written: `obj` is the transient row, its unset Visibility
    columns read as their column defaults. Derived rows follow their parents."""
    model = type(obj)
    reg = registration(model)
    if isinstance(reg, Derived):
        return
    if scope_column(model) is not None and _row_campaign(obj) != ctx.campaign_id:
        not_found()
    if isinstance(reg, Stored) and reg.column is not None:
        vis = getattr(obj, reg.column) or _column_default(model, reg.column)
        kind = None
        if reg.kind_field:
            kind = getattr(obj, reg.kind_field) or _column_default(model, reg.kind_field)
        aud = stored_audience(vis, getattr(obj, reg.owner_field), kind)
    else:
        aud = audience_of(obj)
    if not visible_to(aud, ctx):
        not_found()


# ── Projection ─────────────────────────────────────────────────────────────

def _field_default(schema: type[BaseModel], name: str) -> Any:
    field = schema.model_fields[name]
    if field.is_required():
        return None
    return field.get_default(call_default_factory=True)


def _read(obj: Any, schema: type[BaseModel], skip: Iterable[str]) -> dict[str, Any]:
    skip = set(skip)
    try:
        state = sa.inspect(obj)
    except sa.exc.NoInspectionAvailable:
        state = None
    unloaded = set(state.unloaded) if state is not None else set()
    relationships = set(state.mapper.relationships.keys()) if state is not None else set()
    data: dict[str, Any] = {}
    for name in schema.model_fields:
        if name in skip:
            continue
        if name in relationships and name in unloaded:
            raise RuntimeError(f"project: {type(obj).__name__}.{name} is not loaded; load it with the query "
                               "(selectinload) before projecting")
        if hasattr(obj, name):
            data[name] = getattr(obj, name)
    return data


def _category_visible(category: Any, ctx: CampaignContext) -> bool:
    """A tag's custom category is served only when it is ctx's Campaign's
    and ctx may see it."""
    if getattr(category, "campaign_id", None) != ctx.campaign_id:
        return False
    return visible_to(audience_of(category), ctx)


def _project_tag(tag: Tag, ctx: CampaignContext, schema: type[BaseModel] | None = None,
                 extra: Mapping[str, Any] | None = None) -> BaseModel:
    schema = schema or schema_for(Tag, ctx)
    data = _read(tag, schema, skip=("custom_category", *(extra or {})))
    category = tag.custom_category if "custom_category" in schema.model_fields else None
    if "custom_category" in schema.model_fields:
        data["custom_category"] = category if category is not None and _category_visible(category, ctx) else None
    data.update(extra or {})
    return schema.model_validate(data, from_attributes=True)


def _apply_field_visibility(obj: Any, reg: Any, schema: type[BaseModel], data: dict[str, Any],
                            ctx: CampaignContext) -> None:
    if not isinstance(reg, Stored) or not reg.field_visibility:
        return
    per_field = getattr(obj, reg.field_visibility, None) or {}
    owner_id = getattr(obj, reg.owner_field, None)
    kind = getattr(obj, reg.kind_field) if reg.kind_field else None
    for name, vis in dict(per_field).items():
        if name not in schema.model_fields or vis is None:
            continue
        if not visible_to(stored_audience(vis, owner_id, kind), ctx):
            data[name] = _field_default(schema, name)


def project(obj: Any, ctx: CampaignContext, *, variant: str | None = None,
            extra: Mapping[str, Any] | None = None, links: Mapping[uuid.UUID, JournalTag] | None = None) -> BaseModel:
    """`obj` as the response schema for ctx (see the module docstring for the
    order). `links` ({tag_id: JournalTag}) are an entry's tag links, needed
    for a non-GM entry with tags (`project_all` loads them)."""
    if not isinstance(ctx, CampaignContext):
        raise TypeError(f"project: ctx must be a CampaignContext, got {type(ctx).__name__} (use project_all "
                        "for a role_map)")
    model = type(obj)
    reg = registration(model)
    _check_row(obj, ctx)
    schema = schema_for(model, ctx, variant)
    extra = dict(extra or {})
    unknown = sorted(set(extra) - set(schema.model_fields))
    if unknown:
        raise ValueError(f"project: {schema.__name__} has no field(s) {unknown}")
    if model is Tag:
        return _project_tag(obj, ctx, schema, extra)

    data = _read(obj, schema, skip=(*extra, "tags") if model is JournalEntry else extra)
    if model is JournalEntry and "tags" in schema.model_fields:
        tags = list(obj.tags)
        if ctx.role != GM:
            if tags and links is None:
                raise RuntimeError("project: a non-GM JournalEntry with tags needs its journal_tags links "
                                   "(use project_all, or pass links=)")
            kept = []
            for tag in tags:
                link = (links or {}).get(tag.id)
                if link is not None and visible_to(audience_of(link, parents=[obj]), ctx):
                    kept.append(tag)
            tags = kept
        data["tags"] = [_project_tag(t, ctx) for t in tags]
    _apply_field_visibility(obj, reg, schema, data, ctx)
    data.update(extra)
    return schema.model_validate(data, from_attributes=True)


def _ctx_for_row(ctx: CampaignContext | Mapping[uuid.UUID, str], row: Any) -> CampaignContext:
    if isinstance(ctx, CampaignContext):
        return ctx
    roles = ctx
    cid = _row_campaign(row)
    if cid is None and isinstance(row, Tag) and row.custom_category is not None:
        cid = row.custom_category.campaign_id
    if cid is None or cid not in roles:
        if not isinstance(row, Tag) or not roles:
            not_found()
        # A tag (global) seen through several Campaigns: any one of them,
        # preferring a Player Campaign (the narrower schema). A category of
        # another Campaign is dropped by _category_visible.
        cid = sorted(roles, key=lambda c: (roles[c] != PLAYER, str(c)))[0]
    return role_ctx(roles, cid)


async def _entry_links(db: AsyncSession, entries: Sequence[JournalEntry]) -> dict[uuid.UUID, dict[uuid.UUID, JournalTag]]:
    ids = [e.id for e in entries]
    out: dict[uuid.UUID, dict[uuid.UUID, JournalTag]] = {i: {} for i in ids}
    if not ids:
        return out
    rows = (await db.execute(sa.select(JournalTag).where(JournalTag.journal_id.in_(ids)))).scalars().all()
    for link in rows:
        out[link.journal_id][link.tag_id] = link
    return out


async def project_all(db: AsyncSession, rows: Iterable[Any], ctx: CampaignContext | Mapping[uuid.UUID, str], *,
                      variant: str | None = None,
                      extra: Callable[[Any], Mapping[str, Any]] | None = None) -> list[BaseModel]:
    """`project` over `rows` (in order) with one ctx, or with a `role_map`
    (each row by the Role in its own Campaign). Loads entries' tag links.
    `extra(row)` gives each row's extra fields."""
    rows = list(rows)
    if not rows:
        return []
    entries = [r for r in rows if isinstance(r, JournalEntry)]
    links = await _entry_links(db, entries) if entries else {}
    out = []
    for row in rows:
        row_ctx = _ctx_for_row(ctx, row)
        out.append(project(row, row_ctx, variant=variant, extra=extra(row) if extra else None,
                           links=links.get(row.id) if isinstance(row, JournalEntry) else None))
    return out


# ── Import-time check: Party schemas carry no GM field ─────────────────────

def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    out: list[type[BaseModel]] = []
    for arg in typing.get_args(annotation):
        out.extend(_nested_models(arg))
    return out


def _walk(schema: type[BaseModel], path: str, seen: set[type]) -> Iterable[tuple[str, str, type[BaseModel] | None]]:
    if schema in seen:
        return
    seen = seen | {schema}
    for name, field in schema.model_fields.items():
        nested = _nested_models(field.annotation)
        yield f"{path}.{name}", name, None
        for m in nested:
            yield f"{path}.{name}", name, m
            yield from _walk(m, f"{path}.{name}", seen)


def check_party_schemas(projections: Mapping[type | tuple[type, str], Projection] | None = None) -> None:
    """RuntimeError when a Party or anon schema names a GM field of its model,
    an always-GM field or `field_visibility` (at any depth), or nests a GM
    schema."""
    projections = PROJECTIONS if projections is None else projections
    gm_schemas = {p.gm for p in projections.values()}
    party_schemas = {p.party for p in projections.values()} | {p.anon for p in projections.values() if p.anon}
    problems: list[str] = []
    for key, proj in projections.items():
        model = _key_model(key)
        reg = registration(model)
        top_forbidden = set(gm_fields(model))
        if isinstance(reg, Stored) and reg.field_visibility:
            top_forbidden.add(reg.field_visibility)
        anywhere = set(ALWAYS_GM_FIELDS) | {FIELD_VISIBILITY}
        if proj.party is proj.gm or proj.anon is proj.gm:
            problems.append(f"{model.__name__}: the Party schema is the GM schema")
        for schema in {proj.party, proj.anon} - {None}:
            for name in top_forbidden & set(schema.model_fields):
                problems.append(f"{schema.__name__}.{name} is a GM field of {model.__name__}")
            for path, name, nested in _walk(schema, schema.__name__, set()):
                if nested is None and name in anywhere:
                    problems.append(f"{path} is a GM-only field")
                if nested is not None and nested in gm_schemas and nested not in party_schemas:
                    problems.append(f"{path} nests the GM schema {nested.__name__}")
    if problems:
        raise RuntimeError("app/access/projection.py: Party schemas must carry no GM field: "
                           + "; ".join(sorted(set(problems))))


check_party_schemas()
