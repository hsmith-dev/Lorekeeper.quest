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
     `field_visibility` renders as the schema default (None when none), and
     on an Entity as its unset value (`entity_types.party_view`: status the
     type's default, a hidden attribute key dropped);
  6. `extra` fields (counts, `is_owner`, `share_kind`) merged, then validated.

`project_all(db, rows, ctx)` takes one ctx or a `role_map` (a per-row
`role_ctx` by the row's Campaign) and preloads the `journal_tags` links of
entries, so `project` stays sync. `project` on a non-GM entry with tags and
no `links=` raises: a programming error, never a silent leak.

Chat sessions (E0-Access.8) are projected with `project_chat(db, session,
ctx | role_map, variant, extra)` (CHAT_META, CHAT_REPLY, CHAT_DETAIL): the
route passes one GM-shaped body as `extra`, and the Party schemas drop
`shorthand` and `system_prompt` and empty `canon_sources`. Stored messages
are redacted by `access.visible_refs` (`project(..., visible_refs=)`), and
`replay_history` gives the `{role, content}` turns that may go back into a
prompt. A campaign-less session (a `RoleMap`) gets the GM schema.

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
from app.access.context import CampaignContext, RoleMap, role_ctx
from app.access.policy import ANON, GM, PLAYER, not_found
from app.access.write import can_write
from app.domain import entity_types
from app.access.registry import (
    Derived, Stored, UnregisteredModel, audience_of, gm_fields, narrowed_audience, registration, scope_column,
)
from app.access.sources import message_refs, visible_refs as _visible_refs
from app.db.models.campaign import Campaign
from app.db.models.character_sheet import CharacterSheet, CharacterSheetTemplate
from app.db.models.chat import ChatSession
from app.db.models.entity import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, QuestStep, RelationshipType,
)
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry
from app.db.models.quest import Quest
from app.db.models.session_plan import SessionPlan
from app.db.models.shorthand import ShorthandTerm
from app.db.models.source import SourceDocument
from app.db.models.tag import JournalTag, Tag
from app.db.models.tag_category import TagCategory
from app.schemas.campaign import CampaignGMResponse, CampaignPartyResponse
from app.schemas.character_sheet import (
    CharacterSheetGMResponse, CharacterSheetPartyResponse, TemplateGMResponse, TemplatePartyResponse,
)
from app.schemas.chat import (
    ChatGMResponse, ChatMetaGM, ChatMetaParty, ChatPartyResponse, ChatSessionDetailGM, ChatSessionDetailParty,
)
from app.schemas.entities import (
    EntityAliasGMResponse, EntityAliasPartyResponse, EntityChangeGMResponse, EntityChangePartyResponse,
    EntityGMResponse, EntityMentionGMResponse, EntityMentionPartyResponse, EntityPartyResponse,
    EntityRelationshipGMResponse, EntityRelationshipPartyResponse, QuestStepGMResponse, QuestStepPartyResponse,
    RelationshipTypeGMResponse, RelationshipTypePartyResponse,
)
from app.schemas.journal import JournalGMResponse, JournalLiteResponse, JournalPartyResponse
from app.schemas.npc import NpcGMResponse, NpcPartyResponse
from app.schemas.quest import QuestGMResponse, QuestPartyResponse
from app.schemas.session_plan import SessionPlanGMResponse, SessionPlanPartyResponse
from app.schemas.share import PublicCampaignResponse
from app.schemas.sources import SourceRef
from app.schemas.shorthand import ShorthandGMResponse, ShorthandPartyResponse
from app.schemas.source import SourceDocumentGMResponse, SourceDocumentPartyResponse
from app.schemas.tag_category import TagCategoryGMResponse, TagCategoryPartyResponse
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
# The Chronicler (E0-Access.8): the SSE meta event, the blocking reply and a
# stored session, each built through project_chat.
CHAT_META = "chat_meta"
CHAT_REPLY = "chat_reply"
CHAT_DETAIL = "chat_detail"

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
    (ChatSession, CHAT_META): Projection(ChatMetaGM, ChatMetaParty),
    (ChatSession, CHAT_REPLY): Projection(ChatGMResponse, ChatPartyResponse),
    (ChatSession, CHAT_DETAIL): Projection(ChatSessionDetailGM, ChatSessionDetailParty),
    # E0-Access.5: GM authoring rows a non-GM may see when their Visibility
    # covers them (no GM-only fields yet).
    ShorthandTerm: Projection(ShorthandGMResponse, ShorthandPartyResponse),
    SessionPlan: Projection(SessionPlanGMResponse, SessionPlanPartyResponse),
    SourceDocument: Projection(SourceDocumentGMResponse, SourceDocumentPartyResponse),
    TagCategory: Projection(TagCategoryGMResponse, TagCategoryPartyResponse),
    # E0-WorldCore.2 (F3-world). An Entity's hidden fields render as unset
    # (_render_entity_unset).
    Entity: Projection(EntityGMResponse, EntityPartyResponse),
    EntityAlias: Projection(EntityAliasGMResponse, EntityAliasPartyResponse),
    EntityMention: Projection(EntityMentionGMResponse, EntityMentionPartyResponse),
    RelationshipType: Projection(RelationshipTypeGMResponse, RelationshipTypePartyResponse),
    EntityRelationship: Projection(EntityRelationshipGMResponse, EntityRelationshipPartyResponse),
    QuestStep: Projection(QuestStepGMResponse, QuestStepPartyResponse),
    EntityChange: Projection(EntityChangeGMResponse, EntityChangePartyResponse),
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
    ctx. Derived rows (tags) are trusted from the scoped query that loaded them.
    A stored row with `narrowed_by` parents (entity_relationships) needs those
    relationships loaded (selectinload) for audience_of."""
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
    columns read as their column defaults. Derived rows follow their parents
    for visibility. It ends with `can_write` (E0-Access.6): every create goes
    through the one write gate, so a reduced ctx, anon and a Player creating
    anything but their own Player Journal entry are refused here too."""
    model = type(obj)
    reg = registration(model)
    if isinstance(reg, Derived):
        can_write(ctx, obj)
        return
    if scope_column(model) is not None and _row_campaign(obj) != ctx.campaign_id:
        not_found()
    if isinstance(reg, Stored) and reg.column is not None:
        vis = getattr(obj, reg.column) or _column_default(model, reg.column)
        kind = None
        if reg.kind_field:
            kind = getattr(obj, reg.kind_field) or _column_default(model, reg.kind_field)
        aud = stored_audience(vis, getattr(obj, reg.owner_field) if reg.owner_field else None, kind)
        # The floor (its column default when unset) and the narrowing parents
        # (loaded relationships; unloaded raises) narrow a create too.
        aud = narrowed_audience(obj, reg, aud,
                                floor_value=_column_default(model, reg.floor) if reg.floor else None)
    else:
        aud = audience_of(obj)
    if not visible_to(aud, ctx):
        not_found()
    can_write(ctx, obj)


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
    owner_id = getattr(obj, reg.owner_field) if reg.owner_field else None
    kind = getattr(obj, reg.kind_field) if reg.kind_field else None
    hidden: list[str] = []
    for name, vis in dict(per_field).items():
        if vis is None:
            continue
        try:
            shown = visible_to(stored_audience(vis, owner_id, kind), ctx)
        except ValueError:  # not a Visibility: fail closed
            shown = False
        if not shown:
            hidden.append(str(name))
    if isinstance(obj, Entity):
        _render_entity_unset(obj, schema, data, hidden)
        return
    for name in hidden:
        if name in schema.model_fields:
            data[name] = _field_default(schema, name)


# Entity fields entity_types.party_unset renders (besides `attributes.<key>`).
_ENTITY_UNSET_FIELDS = frozenset({"status", "description", "aliases", "gm_notes"})
_ATTRIBUTES_PREFIX = "attributes."


def _render_entity_unset(obj: Entity, schema: type[BaseModel], data: dict[str, Any], hidden: list[str]) -> None:
    """A hidden Entity field renders exactly as unset (AD-13): status as the
    type's default, description None, a hidden attribute key dropped
    (entity_types.party_view). Any other optional hidden schema field gets the
    schema default; a required one (name, which is never hidden) is left as
    is. An attribute key the type does not define is dropped too, and a
    hidden status also drops `completed_at` (it would reveal the status)."""
    known = set(entity_types.attribute_keys(obj.type))
    registry_hidden = []
    drop_attrs = ["completed_at"] if "status" in hidden else []
    for name in hidden:
        if name in _ENTITY_UNSET_FIELDS:
            if name in data:
                registry_hidden.append(name)
        elif name.startswith(_ATTRIBUTES_PREFIX):
            key = name[len(_ATTRIBUTES_PREFIX):]
            if key in known:
                registry_hidden.append(name)
            else:
                drop_attrs.append(key)
        elif name in schema.model_fields and not schema.model_fields[name].is_required():
            data[name] = _field_default(schema, name)
    if "attributes" in data:
        attrs = data["attributes"]
        data["attributes"] = dict(attrs) if attrs is not None else {}
        for key in drop_attrs:
            data["attributes"].pop(key, None)
    elif any(n.startswith(_ATTRIBUTES_PREFIX) for n in registry_hidden):
        registry_hidden = [n for n in registry_hidden if not n.startswith(_ATTRIBUTES_PREFIX)]
    if registry_hidden:
        data.update(entity_types.party_view(obj.type, data, registry_hidden))


def project(obj: Any, ctx: CampaignContext, *, variant: str | None = None,
            extra: Mapping[str, Any] | None = None, links: Mapping[uuid.UUID, JournalTag] | None = None,
            visible_refs: Iterable[SourceRef] | None = None) -> BaseModel:
    """`obj` as the response schema for ctx (see the module docstring for the
    order). `links` ({tag_id: JournalTag}) are an entry's tag links, needed
    for a non-GM entry with tags (`project_all` loads them). `visible_refs`
    are the SourceRefs ctx may see among a chat session's messages
    (`project_chat` computes them): a message citing anything else is
    redacted (none given: every message with a ref is)."""
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

    if model is ChatSession and "messages" in schema.model_fields:
        raw = extra.pop("messages", None)
        extra["messages"] = redact_messages(obj.messages if raw is None else raw, visible_refs or (),
                                            legacy_visible=ctx.role == GM)
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


# ── Chat sessions (E0-Access.8) ────────────────────────────────────────────
#
# A stored message is `{role, content, refs: [SourceRef], grounded}`. On read
# and before replay, a message whose refs ctx can no longer all see is
# redacted (read) or left out (replay). A legacy message (no `refs` key, or
# malformed refs) is visible only to a GM ctx. An archived session is never
# replayed and is `not_found()` to a non-GM ctx.

REDACTED_NOTICE = "This message drew on something you can no longer see, so it is hidden."
REPLAY_ROLES = frozenset({"user", "assistant"})

ChatScope = CampaignContext | RoleMap


def _safe_refs(msg: Any) -> list[SourceRef] | None:
    """The message's refs; None for a legacy or malformed message."""
    try:
        return message_refs(msg)
    except ValueError:
        return None


def _all_refs(messages: Iterable[Any]) -> list[SourceRef]:
    out: list[SourceRef] = []
    for msg in messages or ():
        out.extend(_safe_refs(msg) or ())
    return out


def _message_visible(msg: Any, visible: set[SourceRef], legacy_visible: bool) -> bool:
    if not isinstance(msg, Mapping):
        return False
    refs = _safe_refs(msg)
    if refs is None:
        return legacy_visible
    return all(r in visible for r in refs)


def redact_messages(messages: Iterable[Any], visible: Iterable[SourceRef], *,
                    legacy_visible: bool) -> list[dict[str, Any]]:
    """Each stored message as a response message: as stored when all its refs
    are in `visible` (a legacy message when `legacy_visible`), else the
    redaction notice with no refs."""
    shown = set(visible)
    out: list[dict[str, Any]] = []
    for msg in messages or ():
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role", ""))
        if _message_visible(msg, shown, legacy_visible):
            out.append({"role": role, "content": str(msg.get("content") or ""), "refs": _safe_refs(msg) or [],
                        "grounded": msg.get("grounded"), "redacted": False})
        else:
            out.append({"role": role, "content": REDACTED_NOTICE, "refs": [], "grounded": None, "redacted": True})
    return out


def _roles_all_gm(roles: Mapping[uuid.UUID, str]) -> bool:
    return all(role == GM for role in roles.values())


def _chat_scope(session: ChatSession, ctx: ChatScope) -> tuple[ChatScope, bool]:
    """(the scope session's messages are checked with, whether legacy
    messages are visible). `not_found()` for a session that is not the
    user's, of another Campaign, or archived to a non-GM ctx."""
    if isinstance(ctx, CampaignContext):
        if session.user_id is None or session.user_id != ctx.user_id or session.campaign_id != ctx.campaign_id:
            not_found()
        if session.archived_at is not None and ctx.role != GM:
            not_found()
        return ctx, ctx.role == GM
    if not isinstance(ctx, Mapping):
        raise TypeError(f"project_chat: ctx must be a CampaignContext or a RoleMap, got {type(ctx).__name__}")
    if session.campaign_id is not None:
        # A Campaign's session through a role map: the Role in its Campaign.
        return _chat_scope(session, role_ctx(ctx, session.campaign_id))
    uid = getattr(ctx, "user_id", None)
    if uid is None or session.user_id != uid:
        not_found()
    all_gm = _roles_all_gm(ctx)
    if session.archived_at is not None and not all_gm:
        # An archived session whose Campaign is gone (campaign_id SET NULL)
        # stays archived: readable only while the user is a Player nowhere.
        not_found()
    # A campaign-less session is the user's own: the GM schema, its refs
    # checked by the Role in each cited row's Campaign; legacy messages only
    # while the user is a Player nowhere.
    return ctx, all_gm


def check_chat_session(session: ChatSession, ctx: ChatScope) -> None:
    """`not_found()` unless ctx may read `session` (its own, of ctx's
    Campaign, and not archived for a non-GM ctx)."""
    _chat_scope(session, ctx)


def _session_defaults(session: ChatSession, schema: type[BaseModel]) -> dict[str, Any]:
    out = {"id": str(session.id), "session_id": str(session.id),
           "campaign_id": str(session.campaign_id) if session.campaign_id else None}
    return {k: v for k, v in out.items() if k in schema.model_fields}


async def project_chat(db: AsyncSession, session: ChatSession, ctx: ChatScope, variant: str,
                       extra: Mapping[str, Any] | None = None) -> BaseModel:
    """`session` as ctx's chat schema for `variant` (CHAT_META, CHAT_REPLY,
    CHAT_DETAIL). `extra` is the GM-shaped body (the route builds one dict);
    the Party schemas drop `shorthand` and `system_prompt` and empty
    `canon_sources`. With a `RoleMap` (a campaign-less session, the user's
    own) the GM schema. Messages are redacted by what ctx may see now."""
    if not isinstance(session, ChatSession):
        raise TypeError(f"project_chat: expected a ChatSession, got {type(session).__name__}")
    scope, legacy_visible = _chat_scope(session, ctx)
    if isinstance(scope, CampaignContext):
        schema = schema_for(ChatSession, scope, variant)
    else:
        schema = projection_for(ChatSession, variant).gm
    data = {**_session_defaults(session, schema), **dict(extra or {})}
    visible: list[SourceRef] = []
    if "messages" in schema.model_fields:
        raw = data.get("messages")
        messages = session.messages if raw is None else raw
        data["messages"] = messages
        visible = await _visible_refs(db, _all_refs(messages), scope)
    if isinstance(scope, CampaignContext):
        return project(session, scope, variant=variant, extra=data, visible_refs=visible)
    unknown = sorted(set(data) - set(schema.model_fields))
    if unknown:
        raise ValueError(f"project_chat: {schema.__name__} has no field(s) {unknown}")
    if "messages" in data:
        data["messages"] = redact_messages(data["messages"], visible, legacy_visible=legacy_visible)
    body = _read(session, schema, skip=data)
    body.update(data)
    return schema.model_validate(body, from_attributes=True)


async def replay_history(db: AsyncSession, session: ChatSession | None, ctx: ChatScope) -> list[dict[str, str]]:
    """The session's messages that may go back into a prompt for ctx, as
    `{role, content}` only: none for an archived session, and none that
    ctx may not see (redacted or legacy). `not_found()` as `project_chat`."""
    if session is None:
        return []
    scope, legacy_visible = _chat_scope(session, ctx)
    if session.archived_at is not None:
        return []
    messages = list(session.messages or [])
    shown = set(await _visible_refs(db, _all_refs(messages), scope))
    return [
        {"role": str(m["role"]), "content": str(m.get("content") or "")}
        for m in messages
        if isinstance(m, Mapping) and m.get("role") in REPLAY_ROLES and _message_visible(m, shown, legacy_visible)
    ]


async def session_visible_text(db: AsyncSession, session: ChatSession, ctx: ChatScope) -> list[str]:
    """The message texts ctx may read in `session` (for search): redacted
    messages contribute nothing."""
    scope, legacy_visible = _chat_scope(session, ctx)
    messages = list(session.messages or [])
    shown = set(await _visible_refs(db, _all_refs(messages), scope))
    return [str(m.get("content") or "") for m in messages if _message_visible(m, shown, legacy_visible)]


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
