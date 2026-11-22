"""The Entity API (E0-WorldCore.5), mounted at /api/entities.

    GET    /?campaign_id=&type=&status=&q=&visibility=&limit=&offset=   list (Party read)
    POST   /                                                          create (GM)
    POST   /visibility                                                bulk Visibility (GM)
    GET    /mentions?journal_id=                                      an entry's Mentions (Party read)
    GET    /{entity_id}                                               one Entity (Party read)
    PATCH  /{entity_id}                                               edit fields (GM)
    DELETE /{entity_id}                                               soft delete (GM)
    POST   /{entity_id}/aliases                                       add an alias (GM)
    DELETE /{entity_id}/aliases/{alias_id}                            remove an alias (GM)
    POST   /{entity_id}/steps                                         add a Quest step (GM)
    PATCH  /{entity_id}/steps/{step_id}                               edit a Quest step (GM)
    GET    /{entity_id}/history                                       history, newest first (Party read)
    POST   /{entity_id}/history/{change_id}/revert                    revert one change (GM)
    POST   /{entity_id}/visibility                                    the Entity's or one field's Visibility (GM)
    GET    /{entity_id}/mentions?confirmed=&page=                     the Entity's Mentions, newest first (Party read)
    POST   /{entity_id}/mentions/{mention_id}/confirm                 confirm a suggested Mention (GM)
    DELETE /{entity_id}/mentions/{mention_id}                         remove a Mention (GM)

Every Canon write goes through `world_service.apply_change` / `revert_change`,
every Visibility write through `access.set_visibility(_many)`, every read
through `scoped_select` / `scoped_get`, and every body through
`access.project_all`: a GM gets the GM schema, a Player (or a GM in member
preview) the Party schema, with hidden fields rendered as unset, hidden
aliases as `[]` and no id of an Entity the viewer may not see.

Hidden, deleted or merged (for a non-GM), missing, another Campaign's and
Player-forbidden all answer the one `404 {"detail":"Not found"}`. A Player
reaches no write route at all (`gm` ctx dependencies), so nothing is written.
Canon errors: `superseded`, `deleted`, `merged` are 409 and `invalid`,
`invalid_status`, `not_revertible` 422, each `{"detail", "code"}`;
`not_found` is the uniform 404. A duplicate create (the same
`normalize_name` as a live Entity of the type that ctx can see) is
`409 {"detail", "code": "duplicate", "existing_id"}`. The `visibility`
filter applies for a GM only (a non-GM's is ignored). Any error rolls the session back.

Filters on the list are applied to what the viewer sees: `status` matches the
rendered status (a hidden status reads as the type's default), so a filter
never reveals a hidden value. `q` ranks by `world_service.candidates`
(score >= 0.6, at most 100), otherwise the order is `lower(name), id`.

Mentions (E0-WorldCore.7): suggested Mentions (`confirmed = false`) are GM
only. A non-GM ctx (a Player, or a GM in member preview) gets only confirmed
rows the binding audience formula allows (`scoped_select(EntityMention)`),
whatever `confirmed=` it sends. Each item carries `entry_title` (from
`access.resolve_sources`), `entity_name` and `entity_type` (the projected
Entity). A Mention of another Entity, a hidden or other-Campaign entry and a
hidden Entity are all the uniform 404.
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    GM, CampaignContext, ctx_for_request, not_found, project_all, require_campaign, require_campaign_for,
    resolve_sources, role_map_for_request, scoped_get, scoped_select, scoped_select_multi, set_visibility,
    set_visibility_many,
)
from app.api.deps import PARTY_READ, get_current_user
from app.db.models.entity import Entity, EntityAlias, EntityChange, EntityMention, QuestStep
from app.db.models.journal import JournalEntry
from app.db.models.user import User
from app.db.session import get_db
from app.domain.enums import EntityType, EntryKind, Visibility
from app.schemas.entities import (
    MAX_PAGE, AliasCreate, BulkEntityVisibilityRequest, ConfirmMention, EntityAliasGMResponse,
    EntityChangeGMResponse, EntityCreate, EntityGMResponse, EntityHistoryGMResponse, EntityListGMResponse,
    EntityMentionGMResponse, EntityMentionListGMResponse, EntityPatch, EntityVisibilityRequest,
    EntryMentionsGMResponse, QuestStepGMResponse, RemoveMention, RevertRequest, StepCreate, StepPatch,
    UpdatedResponse,
)
from app.schemas.sources import RecordRef, SourceKind, SourceRef
from app.services.world_service import CanonChangeError, apply_change, candidates, normalize_name, revert_change

router = APIRouter()

_GM_OR_PARTY = "GM: the GM schema; Player or member preview: the Party schema."
_read_ctx = require_campaign_for(Entity, "entity_id", "player")
_gm_ctx = require_campaign_for(Entity, "entity_id", "gm")

KIND = "entity"  # the Visibility kind world_service registers
MIN_SCORE = 0.6
MAX_MATCHES = 100
PAGE_SIZE = 20  # an Entity's Mention list
_CONFLICT_CODES = frozenset({"superseded", "deleted", "merged"})


# ── Errors and transactions ────────────────────────────────────────────────

def _canon_error(exc: CanonChangeError) -> JSONResponse:
    if exc.code == "not_found":
        not_found()
    status = 409 if exc.code in _CONFLICT_CODES else 422
    return JSONResponse(status_code=status, content={"detail": exc.detail, "code": exc.code})


async def _write(db: AsyncSession, work: Callable[[], Awaitable[Any]]) -> Any:
    """Run `work()` and commit; on a CanonChangeError roll back and answer
    with its mapped status, on any other error roll back and re-raise."""
    try:
        result = await work()
        await db.commit()
    except CanonChangeError as exc:
        await db.rollback()
        return _canon_error(exc)
    except Exception:
        await db.rollback()
        raise
    return result


# ── Projection with the per-Entity extras ──────────────────────────────────

async def _rows(db: AsyncSession, stmt) -> list[Any]:
    return list((await db.execute(stmt.execution_options(populate_existing=True))).scalars().all())


async def _project_entities(db: AsyncSession, ctx: CampaignContext, entities: list[Entity]) -> list[Any]:
    """Each Entity projected for ctx with its visible aliases, Quest steps and
    confirmed Mention count (all through scoped_select and project_all)."""
    if not entities:
        return []
    ids = [e.id for e in entities]
    aliases = await _rows(db, scoped_select(EntityAlias, ctx).where(EntityAlias.entity_id.in_(ids))
                          .order_by(EntityAlias.alias, EntityAlias.id))
    steps = await _rows(db, scoped_select(QuestStep, ctx).where(QuestStep.quest_entity_id.in_(ids))
                        .order_by(QuestStep.position, QuestStep.id))
    counts_stmt = (scoped_select(EntityMention, ctx)
                   .where(EntityMention.entity_id.in_(ids), EntityMention.confirmed.is_(True))
                   .with_only_columns(EntityMention.entity_id, func.count(EntityMention.id))
                   .group_by(EntityMention.entity_id))
    counts = {eid: int(n) for eid, n in (await db.execute(counts_stmt)).all()}
    by_entity: dict[uuid.UUID, dict[str, list[Any]]] = {i: {"aliases": [], "steps": []} for i in ids}
    for row, body in zip(aliases, await project_all(db, aliases, ctx)):
        by_entity[row.entity_id]["aliases"].append(body)
    for row, body in zip(steps, await project_all(db, steps, ctx)):
        by_entity[row.quest_entity_id]["steps"].append(body)
    return await project_all(db, entities, ctx, extra=lambda e: {
        "aliases": by_entity[e.id]["aliases"], "steps": by_entity[e.id]["steps"],
        "mention_count": counts.get(e.id, 0)})


async def _entity_body(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID) -> Any:
    entity = await scoped_get(db, Entity, ctx, entity_id)
    await db.refresh(entity)
    return (await _project_entities(db, ctx, [entity]))[0]


def _page(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ── Mention bodies (E0-WorldCore.7) ────────────────────────────────────────

def _entry_ref(entry: Any) -> SourceRef:
    kind = SourceKind.JOURNAL if entry.kind == EntryKind.GM.value else SourceKind.PLAYER_JOURNAL
    return SourceRef(kind=kind, id=entry.id, field="narrative")


async def _entries(db: AsyncSession, ctx: CampaignContext, ids: set[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """The entries among `ids` ctx may see (id, kind, session_date, created_at only)."""
    if not ids:
        return {}
    stmt = (scoped_select(JournalEntry, ctx).where(JournalEntry.id.in_(sorted(ids, key=str)))
            .with_only_columns(JournalEntry.id, JournalEntry.kind, JournalEntry.session_date, JournalEntry.created_at))
    return {row.id: row for row in (await db.execute(stmt)).all()}


async def _mention_bodies(db: AsyncSession, ctx: CampaignContext, mentions: list[EntityMention],
                          entries: dict[uuid.UUID, Any]) -> list[Any]:
    """Each Mention projected for ctx with its entry title (resolve_sources)
    and its Entity's projected name and type."""
    if not mentions:
        return []
    shown = {m.journal_id for m in mentions if m.journal_id in entries}
    refs = [_entry_ref(entries[j]) for j in sorted(shown, key=str)]
    titles = {r.ref.id: r.title for r in await resolve_sources(db, refs, ctx)} if refs else {}
    ids = sorted({m.entity_id for m in mentions}, key=str)
    entities = await _rows(db, scoped_select(Entity, ctx).where(Entity.id.in_(ids)))
    named = {e.id: body for e, body in zip(entities, await project_all(db, entities, ctx))}

    def extra(m: EntityMention) -> dict[str, Any]:
        body = named.get(m.entity_id)
        return {"entry_title": titles.get(m.journal_id) if m.journal_id is not None else None,
                "entity_name": body.name if body is not None else None,
                "entity_type": body.type if body is not None else None}

    return await project_all(db, mentions, ctx, extra=extra)


async def _entity_mention(db: AsyncSession, ctx: CampaignContext, entity_id: uuid.UUID,
                          mention_id: uuid.UUID) -> EntityMention:
    """One of this Entity's Mentions (another Entity's is the uniform 404)."""
    row = (await db.execute(scoped_select(EntityMention, ctx).where(
        EntityMention.id == mention_id, EntityMention.entity_id == entity_id))).scalars().first()
    if row is None:
        not_found()
    return row


# ── Collection ─────────────────────────────────────────────────────────────

@router.get("/", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": EntityListGMResponse, "description": _GM_OR_PARTY}})
async def list_entities(
    entity_type: EntityType | None = Query(None, alias="type"),
    status: str | None = Query(None, max_length=32),
    q: str | None = Query(None, max_length=200),
    visibility: Visibility | None = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    stmt = scoped_select(Entity, ctx).where(Entity.deleted_at.is_(None), Entity.merged_into_id.is_(None))
    if entity_type is not None:
        stmt = stmt.where(Entity.type == entity_type.value)
    if visibility is not None and ctx.role == GM:  # ignored otherwise: the Party schema has no Visibility
        stmt = stmt.where(Entity.visibility == visibility.value)
    if q is None and (status is None or ctx.role == GM):
        if status is not None:
            stmt = stmt.where(Entity.status == status)
        total = (await db.execute(stmt.with_only_columns(func.count(Entity.id)))).scalar_one()
        page = await _rows(db, stmt.order_by(func.lower(Entity.name), Entity.id).offset(offset).limit(limit))
        return _page(await _project_entities(db, ctx, page), total, limit, offset)

    # q, or a non-GM status filter: rank or filter in Python, on what ctx sees.
    if q is not None:
        found = [c for c in await candidates(db, ctx, q, type=entity_type, limit=MAX_MATCHES) if c.score >= MIN_SCORE]
        rank = {c.entity_id: (-c.score, c.name.lower(), str(c.entity_id)) for c in found}
        rows = await _rows(db, stmt.where(Entity.id.in_(list(rank)))) if rank else []
        rows.sort(key=lambda e: rank[e.id])
    else:
        rows = await _rows(db, stmt.order_by(func.lower(Entity.name), Entity.id))
    if status is not None:
        if ctx.role == GM:
            rows = [e for e in rows if e.status == status]
        else:  # the rendered status: a hidden one reads as the type's default
            rows = [e for e, body in zip(rows, await project_all(db, rows, ctx)) if body.status == status]
    page = rows[offset:offset + limit]
    return _page(await _project_entities(db, ctx, page), len(rows), limit, offset)


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": EntityGMResponse, "description": "The new Entity (GM schema)."},
                        409: {"description": "An Entity of this type with this name exists (`existing_id`)."}})
async def create_entity(
    request: Request,
    body: EntityCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    key = normalize_name(body.name)
    # One create per (Campaign, type, name) at a time: a double-submit waits
    # here, then sees the first one's committed row and gets the 409.
    await db.execute(sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(
        f"entity_name:{ctx.campaign_id}:{body.type.value}:{key}", 0))))
    live = await _rows(db, scoped_select(Entity, ctx).where(
        Entity.type == body.type.value, Entity.deleted_at.is_(None), Entity.merged_into_id.is_(None))
        .order_by(Entity.created_at, Entity.id))
    existing = next((e for e in live if normalize_name(e.name) == key), None)
    if existing is not None:
        existing_id = str(existing.id)  # read before the rollback expires the row
        await db.rollback()  # releases the lock
        return JSONResponse(status_code=409, content={"detail": "An Entity with this name exists",
                                                      "code": "duplicate", "existing_id": existing_id})
    change = {"op": "create_entity", **body.model_dump(exclude={"campaign_id"}, mode="json")}

    async def work():
        return await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _entity_body(db, ctx, result.entity_id)


@router.post("/visibility", response_model=UpdatedResponse)
async def bulk_entity_visibility(
    request: Request,
    body: BulkEntityVisibilityRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set every Entity in `entity_ids` (1..500) to `visibility`, all-or-nothing:
    one missing or another Campaign's id is the uniform 404 and writes nothing."""
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    refs = [RecordRef(kind=KIND, id=i) for i in body.entity_ids]

    async def work():
        return await set_visibility_many(db, ctx, refs, body.visibility)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return UpdatedResponse(updated=result)


# ── An entry's Mentions (declared before /{entity_id}) ─────────────────────

@router.get("/mentions", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": EntryMentionsGMResponse, "description": _GM_OR_PARTY}})
async def entry_mentions(
    request: Request,
    journal_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The Mentions of one entry, by `span_start` (nulls last), then the
    Entity's name, then id. Deleted and merged Entities are left out. A
    non-GM gets confirmed Mentions it may see only. A hidden, other-Campaign
    or missing entry is the uniform 404."""
    roles = await role_map_for_request(request, db, user)
    entry = (await db.execute(scoped_select_multi(JournalEntry, roles).where(JournalEntry.id == journal_id)
                              .with_only_columns(JournalEntry.id, JournalEntry.campaign_id))).first()
    if entry is None:
        not_found()
    ctx = await ctx_for_request(request, db, user, entry.campaign_id, "player")
    entries = await _entries(db, ctx, {entry.id})
    if entry.id not in entries:
        not_found()
    stmt = scoped_select(EntityMention, ctx).where(EntityMention.journal_id == journal_id)
    if ctx.role != GM:
        stmt = stmt.where(EntityMention.confirmed.is_(True))
    mentions = await _rows(db, stmt)
    ids = sorted({m.entity_id for m in mentions}, key=str)
    live = await _rows(db, scoped_select(Entity, ctx).where(
        Entity.id.in_(ids), Entity.deleted_at.is_(None), Entity.merged_into_id.is_(None))) if ids else []
    names = {e.id: body.name for e, body in zip(live, await project_all(db, live, ctx))}
    mentions = [m for m in mentions if m.entity_id in names]
    mentions.sort(key=lambda m: (m.span_start is None, m.span_start or 0, names[m.entity_id].lower(), str(m.id)))
    return {"items": await _mention_bodies(db, ctx, mentions, entries)}


# ── One Entity ─────────────────────────────────────────────────────────────

@router.get("/{entity_id}", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": EntityGMResponse, "description": _GM_OR_PARTY}})
async def get_entity(
    entity_id: uuid.UUID,
    ctx: CampaignContext = Depends(_read_ctx),
    db: AsyncSession = Depends(get_db),
):
    entity = await scoped_get(db, Entity, ctx, entity_id)
    return (await _project_entities(db, ctx, [entity]))[0]


def _patch_changes(entity_id: uuid.UUID, body: EntityPatch) -> list[dict[str, Any]]:
    given = body.model_fields_set
    out: list[dict[str, Any]] = []
    for name in ("name", "description", "gm_notes"):
        if name in given:
            out.append({"op": "update_field", "entity_id": entity_id, "field": name, "value": getattr(body, name)})
    if "status" in given:
        out.append({"op": "set_status", "entity_id": entity_id, "status": body.status})
    if "kind" in given:
        out.append({"op": "set_kind", "entity_id": entity_id, "kind": body.kind})
    for key, value in (body.attributes or {}).items():
        out.append({"op": "update_field", "entity_id": entity_id, "field": f"attributes.{key}", "value": value})
    return out


@router.patch("/{entity_id}", response_model=None,
              responses={200: {"model": EntityGMResponse, "description": "The Entity after every change (GM)."}})
async def update_entity(
    entity_id: uuid.UUID,
    body: EntityPatch,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Each given field is one CanonChange; all of them commit together, or none."""
    await scoped_get(db, Entity, ctx, entity_id)
    changes = _patch_changes(entity_id, body)

    async def work():
        for change in changes:
            await apply_change(db, ctx, change)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _entity_body(db, ctx, entity_id)


@router.delete("/{entity_id}", status_code=204)
async def delete_entity(
    entity_id: uuid.UUID,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    await scoped_get(db, Entity, ctx, entity_id)

    async def work():
        return await apply_change(db, ctx, {"op": "delete_entity", "entity_id": entity_id})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return Response(status_code=204)


# ── Aliases ────────────────────────────────────────────────────────────────

@router.post("/{entity_id}/aliases", response_model=None, status_code=201,
             responses={201: {"model": EntityAliasGMResponse, "description": "The alias (GM schema)."}})
async def add_alias(
    entity_id: uuid.UUID,
    body: AliasCreate,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    await scoped_get(db, Entity, ctx, entity_id)

    async def work():
        return await apply_change(db, ctx, {"op": "add_alias", "entity_id": entity_id, "alias": body.alias})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    key = normalize_name(body.alias)
    rows = [a for a in await _rows(db, scoped_select(EntityAlias, ctx).where(EntityAlias.entity_id == entity_id))
            if normalize_name(a.alias) == key]
    if not rows:  # pragma: no cover - apply_change just wrote or found it
        not_found()
    return (await project_all(db, rows[:1], ctx))[0]


@router.delete("/{entity_id}/aliases/{alias_id}", status_code=204)
async def remove_alias(
    entity_id: uuid.UUID,
    alias_id: uuid.UUID,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The alias must be one of this Entity's (another Entity's alias is the 404)."""
    row = (await db.execute(scoped_select(EntityAlias, ctx).where(
        EntityAlias.id == alias_id, EntityAlias.entity_id == entity_id))).scalars().first()
    if row is None:
        not_found()
    alias = row.alias

    async def work():
        return await apply_change(db, ctx, {"op": "remove_alias", "entity_id": entity_id, "alias": alias})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return Response(status_code=204)


# ── Quest steps ────────────────────────────────────────────────────────────

async def _step_body(db: AsyncSession, ctx: CampaignContext, step_id: Any) -> Any:
    step = await scoped_get(db, QuestStep, ctx, step_id)
    await db.refresh(step)
    return (await project_all(db, [step], ctx))[0]


@router.post("/{entity_id}/steps", response_model=None, status_code=201,
             responses={201: {"model": QuestStepGMResponse, "description": "The step (GM schema)."}})
async def add_step(
    entity_id: uuid.UUID,
    body: StepCreate,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """A step of a Quest; any other type is 422 `invalid`."""
    await scoped_get(db, Entity, ctx, entity_id)

    async def work():
        return await apply_change(db, ctx, {"op": "add_quest_step", "entity_id": entity_id,
                                            **body.model_dump(exclude_unset=True)})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _step_body(db, ctx, (result.new_value or {}).get("step_id"))


@router.patch("/{entity_id}/steps/{step_id}", response_model=None,
              responses={200: {"model": QuestStepGMResponse, "description": "The step (GM schema)."}})
async def update_step(
    entity_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepPatch,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The step must be one of this Quest's (else the 404)."""
    step = (await db.execute(scoped_select(QuestStep, ctx).where(
        QuestStep.id == step_id, QuestStep.quest_entity_id == entity_id))).scalars().first()
    if step is None:
        not_found()

    async def work():
        return await apply_change(db, ctx, {"op": "update_quest_step", "step_id": step_id,
                                            **body.model_dump(exclude_unset=True)})

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return await _step_body(db, ctx, step_id)


# ── History ────────────────────────────────────────────────────────────────

@router.get("/{entity_id}/history", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": EntityHistoryGMResponse, "description": _GM_OR_PARTY}})
async def entity_history(
    entity_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    ctx: CampaignContext = Depends(_read_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The rows ctx may read (registry rule plus the write-time floor), newest first."""
    await scoped_get(db, Entity, ctx, entity_id)
    stmt = scoped_select(EntityChange, ctx).where(EntityChange.entity_id == entity_id)
    total = (await db.execute(stmt.with_only_columns(func.count(EntityChange.id)))).scalar_one()
    rows = await _rows(db, stmt.order_by(EntityChange.created_at.desc(), EntityChange.id.desc())
                       .offset(offset).limit(limit))
    return _page(await project_all(db, rows, ctx), total, limit, offset)


@router.post("/{entity_id}/history/{change_id}/revert", response_model=None,
             responses={200: {"model": EntityChangeGMResponse, "description": "The revert row (GM schema)."}})
async def revert_entity_change(
    entity_id: uuid.UUID,
    change_id: uuid.UUID,
    body: RevertRequest,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The change must be one of this Entity's (else the 404). A later change to
    the same field is 409 `superseded` unless `force`."""
    target = (await db.execute(scoped_select(EntityChange, ctx).where(
        EntityChange.id == change_id, EntityChange.entity_id == entity_id))).scalars().first()
    if target is None:
        not_found()

    async def work():
        return await revert_change(db, ctx, change_id, force=body.force)

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    row = await scoped_get(db, EntityChange, ctx, result.id)
    await db.refresh(row)
    return (await project_all(db, [row], ctx))[0]


# ── Visibility ─────────────────────────────────────────────────────────────

@router.post("/{entity_id}/visibility", response_model=UpdatedResponse)
async def entity_visibility(
    entity_id: uuid.UUID,
    body: EntityVisibilityRequest,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The Entity's Visibility, or one field's (`description`, `status`,
    `attributes`, `aliases`); any other field is 422."""
    ref = RecordRef(kind=KIND, id=entity_id, field=body.field)

    async def work():
        await set_visibility(db, ctx, ref, body.visibility)
        return 1

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return UpdatedResponse(updated=result)


# ── Mentions (E0-WorldCore.7) ──────────────────────────────────────────────

def _key_date(entry: Any) -> Any:
    return entry.session_date if entry.session_date is not None else entry.created_at.date()


@router.get("/{entity_id}/mentions", response_model=None, openapi_extra=PARTY_READ,
            responses={200: {"model": EntityMentionListGMResponse, "description": _GM_OR_PARTY}})
async def entity_mentions(
    entity_id: uuid.UUID,
    confirmed: bool | None = None,
    page: int = Query(1, ge=1),
    ctx: CampaignContext = Depends(_read_ctx),
    db: AsyncSession = Depends(get_db),
):
    """The Entity's Mentions, newest Session first, PAGE_SIZE per page. A GM
    may filter on `confirmed`; a non-GM gets confirmed Mentions it may see only
    (`confirmed=false` is an empty page). Mentions without an entry (GM only)
    come last."""
    await scoped_get(db, Entity, ctx, entity_id)
    gm = ctx.role == GM
    if not gm and confirmed is False:
        return {"items": [], "total": 0, "page": page, "page_size": PAGE_SIZE}
    stmt = scoped_select(EntityMention, ctx).where(EntityMention.entity_id == entity_id)
    if not gm:
        stmt = stmt.where(EntityMention.confirmed.is_(True))
    elif confirmed is not None:
        stmt = stmt.where(EntityMention.confirmed.is_(confirmed))
    mentions = await _rows(db, stmt)
    entries = await _entries(db, ctx, {m.journal_id for m in mentions if m.journal_id is not None})
    # Fail closed: a Mention whose entry ctx cannot see is dropped.
    dated = [m for m in mentions if m.journal_id is not None and m.journal_id in entries]
    undated = [m for m in mentions if m.journal_id is None and gm]
    dated.sort(key=lambda m: (_key_date(entries[m.journal_id]), entries[m.journal_id].created_at, m.created_at,
                              str(m.id)), reverse=True)
    undated.sort(key=lambda m: (m.created_at, str(m.id)), reverse=True)
    ordered = dated + undated
    rows = ordered[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    return {"items": await _mention_bodies(db, ctx, rows, entries), "total": len(ordered), "page": page,
            "page_size": PAGE_SIZE}


@router.post("/{entity_id}/mentions/{mention_id}/confirm", response_model=None,
             responses={200: {"model": EntityMentionGMResponse, "description": "The confirmed Mention (GM schema)."}})
async def confirm_mention(
    entity_id: uuid.UUID,
    mention_id: uuid.UUID,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Confirm one of this Entity's Mentions: one `confirm_mention` history row.
    Confirming a Mention that is confirmed already (no earlier confirm) is 422
    `invalid`; a deleted or merged Entity is 409."""
    await _entity_mention(db, ctx, entity_id, mention_id)

    async def work():
        return await apply_change(db, ctx, ConfirmMention(mention_id=mention_id))

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    row = await scoped_get(db, EntityMention, ctx, mention_id)
    await db.refresh(row)
    entries = await _entries(db, ctx, {row.journal_id} if row.journal_id is not None else set())
    return (await _mention_bodies(db, ctx, [row], entries))[0]


@router.delete("/{entity_id}/mentions/{mention_id}", status_code=204)
async def remove_mention(
    entity_id: uuid.UUID,
    mention_id: uuid.UUID,
    ctx: CampaignContext = Depends(_gm_ctx),
    db: AsyncSession = Depends(get_db),
):
    """Remove one of this Entity's Mentions: one `remove_mention` history row.
    A removed migration suggestion is never suggested again."""
    await _entity_mention(db, ctx, entity_id, mention_id)

    async def work():
        return await apply_change(db, ctx, RemoveMention(mention_id=mention_id))

    result = await _write(db, work)
    if isinstance(result, Response):
        return result
    return Response(status_code=204)
