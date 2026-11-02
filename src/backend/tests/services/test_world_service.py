"""E0-WorldCore.3: world_service.apply_change, history and revert.

Every op, the story's I/O matrix (callers, errors, Quests, ENTITY_REF,
revert, superseded, set_visibility through the writer, the merge primitive,
rollback), idempotency, atomicity, `canon_changed` after commit only, and the
as_system grep test. Rows are committed (each test seeds its own Campaign).
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import ValidationError

import app.access.visibility as vis
import app.hooks.world as world_hooks
import app.services.world_service as ws
from app.access import (
    MEMBER_VIEW, REGISTRY, NotFound, VisibilityError, audience_ctx, ctx_for, scoped_get, set_visibility, share_ctx,
)
from app.core import hooks
from app.core.hooks import HookEvent, HookPayload
from app.db.models import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, QuestStep, RelationshipType,
)
from app.domain.enums import Visibility
from app.hooks import HANDLERS
from app.schemas.entities import (
    CANON_CHANGE_TYPES, AddAlias, AddMention, AddQuestStep, AddRelationship, CanonNote, ConfirmMention, CreateEntity,
    DeleteEntity, EndRelationship, Merge, RemoveAlias, RemoveMention, Revert, SetKind, SetStatus, SourceDeleted,
    UpdateField, UpdateQuestStep, UpdateRelationship,
)
from app.schemas.sources import RecordRef
from app.services.world_service import CanonChangeError, apply_change, revert_change
from tests.ev4.fixtures import ev4  # noqa: F401  (registers the fixture)

REPO = Path(__file__).resolve().parents[4]


# ── Fixtures and helpers ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def events(monkeypatch):
    """Only a recorder handles canon_changed; every hook task done before teardown."""
    monkeypatch.setattr(hooks, "_HANDLERS", {})
    seen: list[HookPayload] = []

    async def record(hdb, event, payload):
        seen.append(payload)

    hooks.register_handler(HookEvent.CANON_CHANGED, record)
    yield seen
    await hooks.drain()


@pytest.fixture
def stale(monkeypatch):
    """Records every mark_dependents_stale ref."""
    refs: list = []

    async def marker(db, ref):
        refs.append(ref)

    monkeypatch.setattr(vis, "_STALE_MARKERS", [marker])
    return refs


@pytest_asyncio.fixture
async def gm(ev4, db):
    return await ctx_for(db, ev4.a.owner_id, ev4.a.campaign_id)


async def _player(ev4, db):
    return await ctx_for(db, (await ev4.actor("player")).user_id, ev4.a.campaign_id)


async def _get(db, model, row_id):
    return (await db.execute(sa.select(model).where(model.id == row_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


async def _changes(db, entity_id) -> list[EntityChange]:
    return list((await db.execute(sa.select(EntityChange).where(EntityChange.entity_id == entity_id)
                                  .order_by(EntityChange.created_at, EntityChange.id)
                                  .execution_options(populate_existing=True))).scalars().all())


async def _counts(db, campaign_id) -> dict[str, int]:
    out = {}
    for model in (Entity, EntityAlias, EntityMention, EntityRelationship, QuestStep, EntityChange):
        out[model.__tablename__] = (await db.execute(
            sa.select(sa.func.count()).select_from(model).where(model.campaign_id == campaign_id))).scalar_one()
    return out


async def _create(db, ctx, **kw) -> Entity:
    kw.setdefault("type", "character")
    if kw["type"] == "character":
        kw.setdefault("kind", "npc")
    kw.setdefault("name", f"N{uuid.uuid4().hex[:6]}")
    change = await apply_change(db, ctx, CreateEntity(**kw))
    return await _get(db, Entity, change.entity_id)


async def _rel_type(db, campaign_id) -> RelationshipType:
    rt = RelationshipType(campaign_id=campaign_id, key=f"ally_{uuid.uuid4().hex[:6]}", label="Ally of",
                          inverse_label="Ally of")
    db.add(rt)
    await db.flush()
    return rt


def _entry(ev4) -> uuid.UUID:
    return ev4.a.ids["journal_entries"][0]


# ── Schemas ────────────────────────────────────────────────────────────────

def test_canon_change_has_the_19_public_ops():
    ops = {t.model_fields["op"].default for t in CANON_CHANGE_TYPES}
    from app.domain.enums import EntityChangeOp
    assert ops == {o.value for o in EntityChangeOp} - {"migrated"} and len(ops) == 19
    for t in CANON_CHANGE_TYPES:
        assert {"source_journal_id", "proposal_id", "canon_note_id", "quote"} <= set(t.model_fields)
        assert not {"visibility", "field_visibility", "visibility_floor"} & set(t.model_fields)


@pytest.mark.parametrize("field", ["visibility", "field_visibility", "field_visibility.description",
                                   "visibility_floor", "status", "kind", "id", "attributes", "attributes."])
def test_update_field_refuses_other_fields(field):
    with pytest.raises(ValidationError):
        UpdateField(entity_id=uuid.uuid4(), field=field, value="x")


# ── Callers ────────────────────────────────────────────────────────────────

async def test_gm_create(db, ev4, gm, events):
    a = ev4.a.campaign_id
    change = await apply_change(db, gm, CreateEntity(type="character", kind="npc", name="Mira"))
    assert events == []
    await db.commit()
    await hooks.drain()
    entity = await _get(db, Entity, change.entity_id)
    assert (entity.visibility, entity.status, entity.kind, entity.created_by_user_id) == (
        "gm", "unknown", "npc", gm.user_id)
    rows = await _changes(db, entity.id)
    assert [(r.op, r.field, r.actor_user_id) for r in rows] == [("create_entity", None, gm.user_id)]
    assert rows[0].new_value["name"] == "Mira"
    assert [(p.campaign_id, p.refs, p.actor_ctx) for p in events] == [(a, [entity.id], gm)]


async def test_co_gm_may_write(db, ev4, events):
    co = await ctx_for(db, (await ev4.actor("co_gm")).user_id, ev4.a.campaign_id)
    entity = await _create(db, co, name="Co")
    assert (await _changes(db, entity.id))[0].actor_user_id == co.user_id


async def test_non_gm_ctxs_write_nothing(db, ev4, gm, events):
    a = ev4.a.campaign_id
    entity = await _create(db, gm)
    await db.commit()
    await hooks.drain()
    events.clear()
    before = await _counts(db, a)
    ctxs = [await _player(ev4, db), await share_ctx(db, ev4.a.share_token), audience_ctx(a, MEMBER_VIEW, by=gm)]
    for ctx in ctxs:
        for change in (CreateEntity(type="item", name="X"), SetStatus(entity_id=entity.id, status="deceased"),
                       DeleteEntity(entity_id=entity.id)):
            with pytest.raises(NotFound):
                await apply_change(db, ctx, change)
        with pytest.raises(NotFound):
            await revert_change(db, ctx, (await _changes(db, entity.id))[0].id)
        with pytest.raises(NotFound):
            await set_visibility(db, ctx, RecordRef(kind="entity", id=entity.id), "party")
    await db.commit()
    await hooks.drain()
    assert await _counts(db, a) == before and events == []


async def test_system_ctx_only_for_its_ops(db, ev4, gm):
    entity = await _create(db, gm)
    other = await _create(db, gm)
    entry_deleted, merge = gm.as_system("entry_deleted"), gm.as_system("merge")
    for ctx, change in [
        (entry_deleted, UpdateField(entity_id=entity.id, field="name", value="Y")),
        (entry_deleted, Merge(entity_id=entity.id, survivor_id=other.id)),
        (merge, SetStatus(entity_id=entity.id, status="alive")),
        (merge, RemoveMention(mention_id=uuid.uuid4())),
        (merge, Revert(change_id=uuid.uuid4())),
        (gm, Merge(entity_id=entity.id, survivor_id=other.id)),  # a user ctx never merges
        (gm, SourceDeleted(entity_id=entity.id, source_journal_id=_entry(ev4))),
    ]:
        with pytest.raises(NotFound):
            await apply_change(db, ctx, change)
    assert (await _get(db, Entity, entity.id)).name != "Y"
    assert (await _get(db, Entity, entity.id)).merged_into_id is None


async def test_a_dict_and_the_writer_token(db, ev4, gm):
    entity = await _create(db, gm)
    row = await apply_change(db, gm, {"op": "update_field", "entity_id": str(entity.id), "field": "name",
                                      "value": "Dict"})
    assert row.op == "update_field" and (await _get(db, Entity, entity.id)).name == "Dict"
    with pytest.raises(CanonChangeError) as err:
        await apply_change(db, gm, {"op": "update_field", "entity_id": str(entity.id), "field": "visibility",
                                    "value": "party"})
    assert err.value.code == "invalid"
    forged = ws._VisibilityChange(Entity, entity.id, "visibility", Visibility.PARTY)
    for token in (None, object()):
        with pytest.raises(CanonChangeError):
            await apply_change(db, gm, forged, _token=token)
    assert (await _get(db, Entity, entity.id)).visibility == "gm"


# ── Errors ─────────────────────────────────────────────────────────────────

async def _code(coro) -> str:
    with pytest.raises(CanonChangeError) as err:
        await coro
    return err.value.code


async def test_error_codes_write_nothing(db, ev4, gm, events):
    a = ev4.a.campaign_id
    entity = await _create(db, gm)
    gone = await _create(db, gm)
    absorbed = await _create(db, gm)
    await apply_change(db, gm, DeleteEntity(entity_id=gone.id))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=entity.id))
    cross = await ev4.actor("cross_gm_player")
    b_gm = await ctx_for(db, cross.user_id, ev4.b.campaign_id)
    foreign = await _create(db, b_gm)
    item = await _create(db, gm, type="item")
    await db.commit()
    await hooks.drain()
    events.clear()
    before = await _counts(db, a)
    assert await _code(apply_change(db, gm, SetStatus(entity_id=entity.id, status="zombie"))) == "invalid_status"
    assert await _code(apply_change(db, gm, CreateEntity(type="quest", name="Q", status="dead"))) == "invalid_status"
    assert await _code(apply_change(db, gm, SetStatus(entity_id=foreign.id, status="alive"))) == "not_found"
    assert await _code(apply_change(db, gm, SetStatus(entity_id=uuid.uuid4(), status="alive"))) == "not_found"
    assert await _code(apply_change(db, gm, SetStatus(entity_id=absorbed.id, status="alive"))) == "merged"
    assert await _code(apply_change(db, gm, SetStatus(entity_id=gone.id, status="alive"))) == "deleted"
    assert await _code(apply_change(db, gm, UpdateField(entity_id=entity.id, field="attributes.wings",
                                                        value="x"))) == "invalid"
    assert await _code(apply_change(db, gm, UpdateField(entity_id=entity.id, field="name", value=""))) == "invalid"
    assert await _code(apply_change(db, gm, SetKind(entity_id=item.id, kind="pc"))) == "invalid"
    assert await _counts(db, a) == before  # each error rolled its savepoint back
    entity_id = entity.id
    await db.commit()
    assert await _counts(db, a) == before
    # And for B's GM, A's Entity is just as missing.
    assert await _code(apply_change(db, b_gm, DeleteEntity(entity_id=entity_id))) == "not_found"
    await db.commit()
    await hooks.drain()
    assert events == []


async def test_a_failed_change_keeps_the_earlier_ones(db, ev4, gm):
    entity = await _create(db, gm)
    await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="kept"))
    with pytest.raises(CanonChangeError):
        await apply_change(db, gm, AddRelationship(entity_id=entity.id, target_entity_id=(await _create(db, gm)).id,
                                                   relationship_type_id=uuid.uuid4()))
    await db.commit()
    assert (await _get(db, Entity, entity.id)).description == "kept"
    assert [r.op for r in await _changes(db, entity.id)] == ["create_entity", "update_field"]


async def test_a_constraint_error_is_invalid_and_writes_nothing(db, ev4, gm):
    cross = await ev4.actor("cross_gm_player")
    b_gm = await ctx_for(db, cross.user_id, ev4.b.campaign_id)
    foreign = await _create(db, b_gm)
    # The id is another Campaign's: scoped_select cannot see it, the insert's PK refuses it.
    assert await _code(apply_change(db, gm, CreateEntity(entity_id=foreign.id, type="item", name="X"))) == "invalid"
    await db.commit()
    assert (await _get(db, Entity, foreign.id)).campaign_id == ev4.b.campaign_id


async def test_rollback_writes_no_row_and_no_event(db, ev4, gm, events):
    a = ev4.a.campaign_id
    await db.commit()
    before = await _counts(db, a)
    await apply_change(db, gm, CreateEntity(type="item", name="Lost"))
    await db.rollback()
    await db.commit()
    await hooks.drain()
    assert await _counts(db, a) == before and events == []


# ── Field ops and Quests ───────────────────────────────────────────────────

async def test_update_field_and_kind(db, ev4, gm):
    entity = await _create(db, gm)
    for field, value in [("name", "Mira Vale"), ("description", "Tall"), ("gm_notes", "secret"),
                         ("attributes.species", "elf")]:
        row = await apply_change(db, gm, UpdateField(entity_id=entity.id, field=field, value=value))
        assert (row.op, row.field, row.new_value) == ("update_field", field, value)
    await apply_change(db, gm, UpdateField(entity_id=entity.id, field="attributes.species", value=None))
    kind = await apply_change(db, gm, SetKind(entity_id=entity.id, kind="pc"))
    e = await _get(db, Entity, entity.id)
    assert (e.name, e.description, e.gm_notes, e.attributes, e.kind) == ("Mira Vale", "Tall", "secret", {}, "pc")
    assert (kind.field, kind.old_value, kind.new_value) == ("kind", "npc", "pc")


@pytest.mark.parametrize("value", [3, "yesterday", "2026-01-01T10:00:00"])
async def test_datetime_attribute_needs_a_timezone(db, ev4, gm, value):
    quest = await _create(db, gm, type="quest")
    assert await _code(apply_change(db, gm, UpdateField(entity_id=quest.id, field="attributes.completed_at",
                                                        value=value))) == "invalid"


async def test_quest_completes_and_reopens(db, ev4, gm):
    quest = await _create(db, gm, type="quest", name="Find the bell")
    assert quest.status == "active" and "completed_at" not in quest.attributes
    done = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="completed"))
    stamped = (await _get(db, Entity, quest.id)).attributes["completed_at"]
    assert datetime.fromisoformat(stamped).tzinfo is not None
    assert (done.field, done.old_value, done.new_value) == (
        "status", {"status": "active", "completed_at": None}, {"status": "completed", "completed_at": stamped})
    back = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="active"))
    assert "completed_at" not in (await _get(db, Entity, quest.id)).attributes
    assert back.old_value == {"status": "completed", "completed_at": stamped}
    assert back.new_value == {"status": "active", "completed_at": None}
    # Reverting the reopen restores the exact stamp.
    await revert_change(db, gm, back.id)
    e = await _get(db, Entity, quest.id)
    assert (e.status, e.attributes["completed_at"]) == ("completed", stamped)
    plain = await apply_change(db, gm, SetStatus(entity_id=(await _create(db, gm)).id, status="deceased"))
    assert (plain.old_value, plain.new_value) == ("unknown", "deceased")


async def test_entity_refs(db, ev4, gm):
    item = await _create(db, gm, type="item")
    place = await _create(db, gm, type="location")
    holder = await _create(db, gm)
    cross = await ev4.actor("cross_gm_player")
    foreign = await _create(db, await ctx_for(db, cross.user_id, ev4.b.campaign_id))
    for bad in (place.id, foreign.id, uuid.uuid4(), "not-a-uuid"):
        assert await _code(apply_change(db, gm, UpdateField(entity_id=item.id, field="attributes.holder_entity_id",
                                                            value=str(bad)))) == "invalid"
    row = await apply_change(db, gm, UpdateField(entity_id=item.id, field="attributes.holder_entity_id",
                                                 value=str(holder.id).upper()))
    assert row.new_value == str(holder.id)
    assert (await _get(db, Entity, item.id)).attributes == {"holder_entity_id": str(holder.id)}
    assert await _code(apply_change(db, gm, CreateEntity(type="item", name="X",
                                                         attributes={"location_entity_id": str(holder.id)}))) \
        == "invalid"
    await apply_change(db, gm, DeleteEntity(entity_id=place.id))
    assert await _code(apply_change(db, gm, UpdateField(entity_id=item.id, field="attributes.location_entity_id",
                                                        value=str(place.id)))) == "invalid"


# ── Aliases, relationships, steps, Mentions, delete, notes ─────────────────

async def test_aliases(db, ev4, gm, stale):
    entity = await _create(db, gm)
    first = await apply_change(db, gm, AddAlias(entity_id=entity.id, alias="The  Grey"))
    again = await apply_change(db, gm, AddAlias(entity_id=entity.id, alias="the grey"))
    assert again.id == first.id and (first.field, first.new_value) == ("aliases", {"alias": "The Grey"})
    aliases = (await db.execute(sa.select(EntityAlias).where(EntityAlias.entity_id == entity.id))).scalars().all()
    assert [(a.alias, a.normalized_alias) for a in aliases] == [("The Grey", "the grey")]
    assert stale == []
    removed = await apply_change(db, gm, RemoveAlias(entity_id=entity.id, alias="THE GREY"))
    assert (removed.op, removed.field, removed.old_value["alias"]) == ("remove_alias", "aliases", "The Grey")
    assert stale == [RecordRef(kind="entity_field", id=entity.id)]
    assert await _code(apply_change(db, gm, RemoveAlias(entity_id=entity.id, alias="x"))) == "not_found"
    await revert_change(db, gm, removed.id)
    assert (await db.execute(sa.select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id))).scalar_one() \
        == "The Grey"


async def test_relationships(db, ev4, gm):
    a = ev4.a.campaign_id
    src, tgt = await _create(db, gm), await _create(db, gm)
    rt, rt2 = await _rel_type(db, a), await _rel_type(db, a)
    added = await apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=tgt.id,
                                                       relationship_type_id=rt.id, note="old friends"))
    assert (added.entity_id, added.field) == (src.id, None)
    edge_id = uuid.UUID(added.new_value["relationship_id"])
    edge = await _get(db, EntityRelationship, edge_id)
    assert (edge.visibility, edge.source_entity_id, edge.target_entity_id) == ("gm", src.id, tgt.id)
    assert await _code(apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=src.id,
                                                            relationship_type_id=rt.id))) == "invalid"
    upd = await apply_change(db, gm, UpdateRelationship(relationship_id=edge_id, note="rivals",
                                                        relationship_type_id=rt2.id))
    assert upd.old_value == {"relationship_id": str(edge_id), "relationship_type_id": str(rt.id),
                             "note": "old friends"}
    ended = await apply_change(db, gm, EndRelationship(relationship_id=edge_id))
    assert (await apply_change(db, gm, EndRelationship(relationship_id=edge_id))).id == ended.id
    assert (await _get(db, EntityRelationship, edge_id)).ended_at is not None
    await revert_change(db, gm, ended.id)
    await revert_change(db, gm, upd.id)
    edge = await _get(db, EntityRelationship, edge_id)
    assert (edge.ended_at, edge.note, edge.relationship_type_id) == (None, "old friends", rt.id)
    await revert_change(db, gm, added.id)
    assert await _get(db, EntityRelationship, edge_id) is None


async def test_quest_steps(db, ev4, gm, stale):
    quest = await _create(db, gm, type="quest")
    first = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="Ask around"))
    second = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="Ring the bell"))
    assert [first.new_value["position"], second.new_value["position"]] == [0, 1]
    assert first.field == "quest_steps"
    step_id = uuid.UUID(second.new_value["step_id"])
    upd = await apply_change(db, gm, UpdateQuestStep(step_id=step_id, done=True))
    step = await _get(db, QuestStep, step_id)
    assert step.done and step.done_at is not None
    assert await _code(apply_change(db, gm, AddQuestStep(entity_id=(await _create(db, gm)).id, text="x"))) \
        == "invalid"
    await revert_change(db, gm, upd.id)
    step = await _get(db, QuestStep, step_id)
    assert (step.done, step.done_at) == (False, None)
    await revert_change(db, gm, second.id)
    assert await _get(db, QuestStep, step_id) is None
    assert stale == [RecordRef(kind="entity_field", id=quest.id)]


async def test_mentions(db, ev4, gm, stale):
    entity = await _create(db, gm)
    added = await apply_change(db, gm, AddMention(entity_id=entity.id, journal_id=_entry(ev4), quote="Mira",
                                                  span_start=0, span_end=4))
    assert (await apply_change(db, gm, AddMention(entity_id=entity.id, journal_id=_entry(ev4), quote="Mira",
                                                  span_start=0, span_end=4))).id == added.id
    assert added.field is None
    mention_id = uuid.UUID(added.new_value["mention_id"])
    m = await _get(db, EntityMention, mention_id)
    assert (m.quote, m.origin, m.confirmed, m.source_field) == ("Mira", "manual", False, "narrative")
    confirmed = await apply_change(db, gm, ConfirmMention(mention_id=mention_id))
    assert (await apply_change(db, gm, ConfirmMention(mention_id=mention_id))).id == confirmed.id
    assert await _code(apply_change(db, gm, AddMention(entity_id=entity.id, journal_id=uuid.uuid4()))) == "not_found"
    removed = await apply_change(db, gm, RemoveMention(mention_id=mention_id))
    assert await _get(db, EntityMention, mention_id) is None
    assert stale == [RecordRef(kind="entity_field", id=entity.id)]
    await revert_change(db, gm, removed.id)
    m = await _get(db, EntityMention, mention_id)
    assert (m.quote, m.confirmed, m.span_end) == ("Mira", True, 4)


async def test_journal_delete_ops_under_entry_deleted(db, ev4, gm):
    entity = await _create(db, gm)
    entry = _entry(ev4)
    sourced = await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="From it",
                                                     source_journal_id=entry))
    added = await apply_change(db, gm, AddMention(entity_id=entity.id, journal_id=entry))
    system = gm.as_system("entry_deleted")
    await apply_change(db, system, RemoveMention(mention_id=uuid.UUID(added.new_value["mention_id"])))
    flagged = await apply_change(db, system, SourceDeleted(entity_id=entity.id, source_journal_id=entry))
    assert (flagged.op, flagged.field, flagged.new_value["flagged"]) == ("source_deleted", None, 1)
    assert (await _get(db, EntityChange, sourced.id)).source_deleted_at is not None
    # Canon stays as it is.
    assert (await _get(db, Entity, entity.id)).description == "From it"
    assert await _code(revert_change(db, gm, flagged.id)) == "not_revertible"
    with pytest.raises(ValidationError):
        SourceDeleted(entity_id=entity.id)


async def test_delete_and_canon_note(db, ev4, gm, stale):
    entity = await _create(db, gm)
    note = await apply_change(db, gm, CanonNote(entity_id=entity.id, note="Retcon: twins", canon_note_id=uuid.uuid4()))
    assert (note.op, note.field, note.canon_note_id is not None) == ("canon_note", None, True)
    deleted = await apply_change(db, gm, DeleteEntity(entity_id=entity.id))
    assert (deleted.field, (await _get(db, Entity, entity.id)).deleted_at is not None) == (None, True)
    assert stale == [RecordRef(kind="entity_field", id=entity.id)]
    await revert_change(db, gm, deleted.id)
    assert (await _get(db, Entity, entity.id)).deleted_at is None


# ── Revert ─────────────────────────────────────────────────────────────────

async def test_revert_update_field(db, ev4, gm):
    entity = await _create(db, gm, description="Old")
    change = await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="New",
                                                    proposal_id=uuid.uuid4()))
    undo = await revert_change(db, gm, change.id)
    assert (await _get(db, Entity, entity.id)).description == "Old"
    assert (undo.op, undo.field, undo.reverted_change_id, undo.old_value, undo.new_value) == (
        "revert", "description", change.id, "New", "Old")
    # A revert of the revert re-applies the change.
    await revert_change(db, gm, undo.id)
    assert (await _get(db, Entity, entity.id)).description == "New"


async def test_superseded_unless_forced(db, ev4, gm):
    entity = await _create(db, gm, description="A")
    first = await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="B"))
    await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="C"))
    count = len(await _changes(db, entity.id))
    assert await _code(revert_change(db, gm, first.id)) == "superseded"
    assert len(await _changes(db, entity.id)) == count
    await revert_change(db, gm, first.id, force=True)
    assert (await _get(db, Entity, entity.id)).description == "A"


async def test_revert_create_merge_and_visibility(db, ev4, gm, stale):
    entity = await _create(db, gm)
    create = (await _changes(db, entity.id))[0]
    survivor = await _create(db, gm)
    vis_row_entity = await _create(db, gm)
    await set_visibility(db, gm, RecordRef(kind="entity", id=vis_row_entity.id), "party")
    vis_row = [r for r in await _changes(db, vis_row_entity.id) if r.field == "visibility"][0]
    assert await _code(revert_change(db, gm, vis_row.id)) == "not_revertible"
    merge = await apply_change(db, gm.as_system("merge"), Merge(entity_id=entity.id, survivor_id=survivor.id))
    assert await _code(revert_change(db, gm, merge.id)) == "not_revertible"
    assert await _code(revert_change(db, gm, uuid.uuid4())) == "not_found"
    fresh = await _create(db, gm)
    await revert_change(db, gm, (await _changes(db, fresh.id))[0].id)
    assert (await _get(db, Entity, fresh.id)).deleted_at is not None
    assert RecordRef(kind="entity_field", id=fresh.id) in stale
    assert create.op == "create_entity"


# ── Idempotency ────────────────────────────────────────────────────────────

async def test_create_with_an_entity_id_and_proposal_repeats(db, ev4, gm, events):
    eid, proposal = uuid.uuid4(), uuid.uuid4()
    first = await apply_change(db, gm, CreateEntity(entity_id=eid, type="faction", name="Guild"))
    assert (await apply_change(db, gm, CreateEntity(entity_id=eid, type="faction", name="Guild"))).id == first.id
    p1 = await apply_change(db, gm, SetStatus(entity_id=eid, status="disbanded", proposal_id=proposal))
    assert (await apply_change(db, gm, SetStatus(entity_id=eid, status="disbanded", proposal_id=proposal))).id == p1.id
    c1 = await apply_change(db, gm, CreateEntity(type="item", name="Bell", proposal_id=proposal))
    assert (await apply_change(db, gm, CreateEntity(type="item", name="Bell", proposal_id=proposal))).id == c1.id
    other = await apply_change(db, gm, CreateEntity(type="item", name="Rope", proposal_id=proposal))
    assert other.id != c1.id
    # Same proposal, same op and Entity, different target edges: both are written.
    rt = await _rel_type(db, ev4.a.campaign_id)
    t1, t2 = await _create(db, gm), await _create(db, gm)
    e1 = await apply_change(db, gm, AddRelationship(entity_id=eid, target_entity_id=t1.id, relationship_type_id=rt.id,
                                                    proposal_id=proposal))
    e2 = await apply_change(db, gm, AddRelationship(entity_id=eid, target_entity_id=t2.id, relationship_type_id=rt.id,
                                                    proposal_id=proposal))
    assert e1.id != e2.id
    assert (await apply_change(db, gm, AddRelationship(entity_id=eid, target_entity_id=t2.id,
                                                       relationship_type_id=rt.id, proposal_id=proposal))).id == e2.id
    await db.commit()
    await hooks.drain()
    ops = [r.op for r in await _changes(db, eid)]
    assert ops == ["create_entity", "set_status", "add_relationship", "add_relationship"]


# ── set_visibility through the writer ──────────────────────────────────────

async def test_set_visibility_entity_and_field(db, ev4, gm, events):
    entity = await _create(db, gm, description="Tall")
    assert REGISTRY[Entity].writer is ws._visibility_writer
    assert REGISTRY[EntityRelationship].writer is ws._visibility_writer
    await db.commit()
    await hooks.drain()
    events.clear()
    body = await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id), "party")
    assert body.visibility == "party"
    await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id, field="description"), "gm")
    await db.commit()
    await hooks.drain()
    e = await _get(db, Entity, entity.id)
    assert (e.visibility, e.field_visibility) == ("party", {"description": "gm"})
    rows = [r for r in await _changes(db, entity.id) if r.op == "update_field"]
    assert [(r.field, r.old_value, r.new_value) for r in rows] == [
        ("visibility", "gm", "party"), ("field_visibility.description", None, "gm")]
    assert len(events) == 2
    player = await _player(ev4, db)
    shown = await scoped_get(db, Entity, player, entity.id)
    assert shown.id == entity.id
    with pytest.raises(VisibilityError):
        await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id, field="name"), "gm")
    with pytest.raises(VisibilityError):
        await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id, field="visibility_floor"), "gm")


async def test_set_visibility_relationship(db, ev4, gm):
    src, tgt = await _create(db, gm), await _create(db, gm)
    rt = await _rel_type(db, ev4.a.campaign_id)
    added = await apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=tgt.id,
                                                       relationship_type_id=rt.id))
    edge_id = uuid.UUID(added.new_value["relationship_id"])
    await set_visibility(db, gm, RecordRef(kind="entity_relationship", id=edge_id), "party")
    assert (await _get(db, EntityRelationship, edge_id)).visibility == "party"
    row = (await _changes(db, src.id))[-1]
    assert (row.op, row.field, row.new_value) == (
        "update_relationship", None, {"relationship_id": str(edge_id), "visibility": "party"})
    with pytest.raises(VisibilityError):
        await set_visibility(db, gm, RecordRef(kind="entity_relationship", id=edge_id, field="visibility_floor"), "gm")
    assert (await _get(db, EntityRelationship, edge_id)).visibility_floor is None


# ── Merge ──────────────────────────────────────────────────────────────────

async def test_merge_primitive(db, ev4, gm, stale, events):
    a = ev4.a.campaign_id
    survivor = await _create(db, gm, name="Mira")
    absorbed = await _create(db, gm, name="Old Mira")  # GM-only
    third = await _create(db, gm)
    await set_visibility(db, gm, RecordRef(kind="entity", id=survivor.id), "party")
    await apply_change(db, gm, AddAlias(entity_id=absorbed.id, alias="Grey Lady"))
    await apply_change(db, gm, AddAlias(entity_id=absorbed.id, alias="Shared"))
    await apply_change(db, gm, AddAlias(entity_id=survivor.id, alias="shared"))
    mention = await apply_change(db, gm, AddMention(entity_id=absorbed.id, journal_id=_entry(ev4)))
    rt = await _rel_type(db, a)
    out_edge = await apply_change(db, gm, AddRelationship(entity_id=absorbed.id, target_entity_id=third.id,
                                                          relationship_type_id=rt.id))
    loop = await apply_change(db, gm, AddRelationship(entity_id=absorbed.id, target_entity_id=survivor.id,
                                                      relationship_type_id=rt.id))
    await db.commit()
    await hooks.drain()
    stale.clear()
    events.clear()
    history_before = len(await _changes(db, absorbed.id))

    row = await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=survivor.id))
    await db.commit()
    await hooks.drain()
    assert (row.op, row.entity_id, row.field) == ("merge", survivor.id, None)
    assert (await _get(db, Entity, absorbed.id)).merged_into_id == survivor.id
    aliases = {a.alias: a for a in (await db.execute(sa.select(EntityAlias).where(
        EntityAlias.entity_id == survivor.id).execution_options(populate_existing=True))).scalars()}
    assert set(aliases) == {"shared", "Grey Lady", "Old Mira"}
    assert aliases["shared"].visibility_floor is None
    assert aliases["Grey Lady"].visibility_floor == aliases["Old Mira"].visibility_floor == "gm"
    m = await _get(db, EntityMention, uuid.UUID(mention.new_value["mention_id"]))
    assert (m.entity_id, m.visibility_floor) == (survivor.id, "gm")
    edge = await _get(db, EntityRelationship, uuid.UUID(out_edge.new_value["relationship_id"]))
    assert (edge.source_entity_id, edge.visibility_floor) == (survivor.id, "gm")
    assert await _get(db, EntityRelationship, uuid.UUID(loop.new_value["relationship_id"])) is None
    assert row.new_value["moved"]["self_loops_dropped"] == 1
    assert {r.id for r in stale} == {survivor.id, absorbed.id}
    # History stays on the absorbed Entity.
    assert len(await _changes(db, absorbed.id)) == history_before
    assert events and set(events[0].refs) >= {survivor.id, absorbed.id}
    # The Player sees the survivor's own alias, not the floored ones.
    player = await _player(ev4, db)
    seen = (await db.execute(ws.scoped_select(EntityAlias, player))).scalars().all()
    assert {a.alias for a in seen} == {"shared"}
    assert await _code(apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id,
                                                                     survivor_id=survivor.id))) == "merged"
    assert await _code(apply_change(db, gm.as_system("merge"), Merge(
        entity_id=third.id, survivor_id=(await _create(db, gm, type="item")).id))) == "invalid"


async def test_merge_moves_quest_steps_only_when_safe(db, ev4, gm):
    party_survivor = await _create(db, gm, type="quest")
    await set_visibility(db, gm, RecordRef(kind="entity", id=party_survivor.id), "party")
    gm_quest = await _create(db, gm, type="quest")
    step = await apply_change(db, gm, AddQuestStep(entity_id=gm_quest.id, text="secret step"))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=gm_quest.id, survivor_id=party_survivor.id))
    assert (await _get(db, QuestStep, uuid.UUID(step.new_value["step_id"]))).quest_entity_id == gm_quest.id
    gm_survivor = await _create(db, gm, type="quest")
    other = await _create(db, gm, type="quest")
    moved = await apply_change(db, gm, AddQuestStep(entity_id=other.id, text="moves"))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=other.id, survivor_id=gm_survivor.id))
    assert (await _get(db, QuestStep, uuid.UUID(moved.new_value["step_id"]))).quest_entity_id == gm_survivor.id


# ── Deleted / merged Entities are GM-only ──────────────────────────────────

async def test_deleted_and_merged_entities_are_gm_only(db, ev4, gm):
    player = await _player(ev4, db)
    gone, kept, absorbed = await _create(db, gm), await _create(db, gm), await _create(db, gm)
    for e in (gone, kept, absorbed):
        await set_visibility(db, gm, RecordRef(kind="entity", id=e.id), "party")
    await apply_change(db, gm, AddAlias(entity_id=gone.id, alias="ghost"))
    await apply_change(db, gm, DeleteEntity(entity_id=gone.id))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=kept.id))
    await db.commit()
    for e in (gone, absorbed):
        with pytest.raises(NotFound):
            await scoped_get(db, Entity, player, e.id)
        assert (await scoped_get(db, Entity, gm, e.id)).id == e.id
    assert (await scoped_get(db, Entity, player, kept.id)).id == kept.id
    aliases = (await db.execute(ws.scoped_select(EntityAlias, player))).scalars().all()
    assert "ghost" not in {a.alias for a in aliases}


# ── canon_changed ──────────────────────────────────────────────────────────

def test_the_handler_is_registered():
    assert (HookEvent.CANON_CHANGED, world_hooks.on_canon_changed) in HANDLERS


@pytest_asyncio.fixture
async def fake_valkey():
    """A fakeredis client behind core.pubsub (E0-Jobs.6), for the real publish path."""
    import fakeredis

    from app.core import pubsub, valkey_client
    client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    previous = valkey_client.set_valkey(client)
    yield client
    valkey_client.set_valkey(previous)
    pubsub._TRAILING.clear()
    await client.aclose()


async def _listen(fake_valkey, campaign_id):
    """Collect `campaign:{id}:events` messages in a task; returns (items, task)."""
    from app.core.pubsub import campaign_events_channel, listen_campaign_events
    items: list = []

    async def run():
        async for item in listen_campaign_events(campaign_id):
            items.append(item)

    task = asyncio.ensure_future(run())
    channel = campaign_events_channel(campaign_id)
    for _ in range(200):
        if dict(await fake_valkey.pubsub_numsub(channel)).get(channel, 0):
            break
        await asyncio.sleep(0.01)
    else:  # pragma: no cover
        raise AssertionError("listener never subscribed")
    return items, task


async def _settle(items, n, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while len(items) < n and loop.time() < end:
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.1)  # anything extra would arrive now


async def test_canon_changed_publishes_one_event_per_entity_after_commit(db, ev4, gm, fake_valkey):
    a = ev4.a.campaign_id
    hooks.load_handlers()
    assert world_hooks.on_canon_changed in hooks.handlers_for(HookEvent.CANON_CHANGED)
    items, task = await _listen(fake_valkey, a)
    try:
        e1 = await _create(db, gm, name="Mira")
        e2 = await _create(db, gm, type="location", name="Harbor")
        await hooks.drain()
        await asyncio.sleep(0.05)
        assert items == []  # nothing before the commit
        await db.commit()
        await hooks.drain()
        await _settle(items, 2)
        assert sorted(items, key=lambda i: i[1]["id"]) == sorted(
            [("invalidate", {"domain": "entities", "id": str(e1.id)}),
             ("invalidate", {"domain": "entities", "id": str(e2.id)})], key=lambda i: i[1]["id"])

        items.clear()
        await apply_change(db, gm, CreateEntity(type="item", name="Lost"))
        await db.rollback()
        await hooks.drain()
        await _settle(items, 1, timeout=0.3)
        assert items == []  # a rolled-back change publishes nothing
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def test_the_handler_publishes_each_entity_once(monkeypatch):
    sent = []

    async def publish(campaign_id, domain, id):  # noqa: A002
        sent.append((campaign_id, domain, id))

    cid, e1, e2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(world_hooks, "publish_campaign_event", publish)
    await world_hooks.on_canon_changed(None, HookEvent.CANON_CHANGED, HookPayload(cid, [e1, e2, e1], None))
    assert sent == [(cid, "entities", e1), (cid, "entities", e2)]


async def test_one_failed_publish_does_not_stop_the_others(monkeypatch, caplog):
    sent = []

    async def publish(campaign_id, domain, id):  # noqa: A002
        if not sent:
            sent.append("boom")
            raise RuntimeError("valkey down SECRET")
        sent.append(id)

    cid, e1, e2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(world_hooks, "publish_campaign_event", publish)
    await world_hooks.on_canon_changed(None, HookEvent.CANON_CHANGED, HookPayload(cid, [e1, e2], None))
    assert sent == ["boom", e2]
    logged = [r.getMessage() for r in caplog.records if "canon_changed_publish_failed" in r.getMessage()]
    assert len(logged) == 1 and str(cid) in logged[0] and "RuntimeError" in logged[0]
    assert str(e1) not in logged[0] and "SECRET" not in logged[0]


# ── Review fixes ───────────────────────────────────────────────────────────

async def test_revert_of_a_removed_row_marks_stale(db, ev4, gm, stale):
    src, tgt = await _create(db, gm), await _create(db, gm)
    rt = await _rel_type(db, ev4.a.campaign_id)
    edge = await apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=tgt.id,
                                                      relationship_type_id=rt.id))
    mention = await apply_change(db, gm, AddMention(entity_id=src.id, journal_id=_entry(ev4)))
    alias = await apply_change(db, gm, AddAlias(entity_id=tgt.id, alias="Twin"))
    assert stale == []
    await revert_change(db, gm, edge.id)
    assert {r.id for r in stale} == {src.id, tgt.id}
    stale.clear()
    await revert_change(db, gm, mention.id)
    assert stale == [RecordRef(kind="entity_field", id=src.id)]
    stale.clear()
    await revert_change(db, gm, alias.id)
    assert stale == [RecordRef(kind="entity_field", id=tgt.id)]


async def test_revert_of_row_updates_superseded_unless_forced(db, ev4, gm):
    src, tgt = await _create(db, gm), await _create(db, gm)
    rt = await _rel_type(db, ev4.a.campaign_id)
    added = await apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=tgt.id,
                                                       relationship_type_id=rt.id, note="a"))
    edge_id = uuid.UUID(added.new_value["relationship_id"])
    first = await apply_change(db, gm, UpdateRelationship(relationship_id=edge_id, note="b"))
    await apply_change(db, gm, UpdateRelationship(relationship_id=edge_id, note="c"))
    assert await _code(revert_change(db, gm, first.id)) == "superseded"
    assert await _code(revert_change(db, gm, added.id)) == "superseded"  # edited since it was added
    await revert_change(db, gm, first.id, force=True)
    assert (await _get(db, EntityRelationship, edge_id)).note == "a"

    quest = await _create(db, gm, type="quest")
    step = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="one"))
    step_id = uuid.UUID(step.new_value["step_id"])
    s1 = await apply_change(db, gm, UpdateQuestStep(step_id=step_id, text="two"))
    await apply_change(db, gm, UpdateQuestStep(step_id=step_id, text="three"))
    assert await _code(revert_change(db, gm, s1.id)) == "superseded"
    assert await _code(revert_change(db, gm, step.id)) == "superseded"
    await revert_change(db, gm, s1.id, force=True)
    assert (await _get(db, QuestStep, step_id)).text == "one"


async def test_revert_of_an_update_whose_row_is_gone_is_superseded(db, ev4, gm):
    quest = await _create(db, gm, type="quest")
    step = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="one"))
    step_id = uuid.UUID(step.new_value["step_id"])
    upd = await apply_change(db, gm, UpdateQuestStep(step_id=step_id, done=True))
    await revert_change(db, gm, step.id, force=True)  # the step is gone
    for force in (False, True):
        assert await _code(revert_change(db, gm, upd.id, force=force)) == "superseded"


async def test_state_made_elsewhere_is_invalid_not_a_stray_row(db, ev4, gm):
    a = ev4.a.campaign_id
    entity, other = await _create(db, gm), await _create(db, gm)
    rt = await _rel_type(db, a)
    # Rows a migration or merge made: no add_alias / add_mention / end row for them.
    db.add(EntityAlias(campaign_id=a, entity_id=entity.id, alias="Old", normalized_alias="old"))
    mention = EntityMention(campaign_id=a, journal_id=_entry(ev4), entity_id=entity.id, source_field="narrative",
                            origin="migration", confirmed=True)
    edge = EntityRelationship(campaign_id=a, source_entity_id=entity.id, target_entity_id=other.id,
                              relationship_type_id=rt.id, ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db.add_all([mention, edge])
    await db.flush()
    before = await _counts(db, a)
    for change in (AddAlias(entity_id=entity.id, alias="OLD"),
                   AddMention(entity_id=entity.id, journal_id=_entry(ev4)),
                   ConfirmMention(mention_id=mention.id),
                   EndRelationship(relationship_id=edge.id)):
        assert await _code(apply_change(db, gm, change)) == "invalid"
    assert await _counts(db, a) == before
    assert (await _get(db, EntityRelationship, edge.id)).ended_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_create_with_an_existing_id_must_match(db, ev4, gm):
    eid = uuid.uuid4()
    await apply_change(db, gm, CreateEntity(entity_id=eid, type="faction", name="Guild"))
    for change in (CreateEntity(entity_id=eid, type="item", name="Guild"),
                   CreateEntity(entity_id=eid, type="faction", name="Other")):
        assert await _code(apply_change(db, gm, change)) == "invalid"
    await apply_change(db, gm, DeleteEntity(entity_id=eid))
    assert await _code(apply_change(db, gm, CreateEntity(entity_id=eid, type="faction", name="Guild"))) == "invalid"
    with pytest.raises(ValidationError):
        CreateEntity(type="item", name="   ")
    with pytest.raises(ValidationError):
        AddQuestStep(entity_id=eid, text="x", position=2**31)
    with pytest.raises(ValidationError):
        AddMention(entity_id=eid, journal_id=eid, span_start=0, span_end=2**31)


async def test_proposal_repeats_of_delete_and_merge(db, ev4, gm):
    proposal = uuid.uuid4()
    entity = await _create(db, gm)
    first = await apply_change(db, gm, DeleteEntity(entity_id=entity.id, proposal_id=proposal))
    assert (await apply_change(db, gm, DeleteEntity(entity_id=entity.id, proposal_id=proposal))).id == first.id
    survivor, a1, a2 = await _create(db, gm), await _create(db, gm), await _create(db, gm)
    merge = gm.as_system("merge")
    m1 = await apply_change(db, merge, Merge(entity_id=a1.id, survivor_id=survivor.id, proposal_id=proposal))
    assert (await apply_change(db, merge, Merge(entity_id=a1.id, survivor_id=survivor.id,
                                                proposal_id=proposal))).id == m1.id
    m2 = await apply_change(db, merge, Merge(entity_id=a2.id, survivor_id=survivor.id, proposal_id=proposal))
    assert m2.id != m1.id and (await _get(db, Entity, a2.id)).merged_into_id == survivor.id


async def test_a_different_value_under_the_same_proposal_is_written(db, ev4, gm):
    proposal = uuid.uuid4()
    entity = await _create(db, gm)
    d1 = await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="one",
                                                proposal_id=proposal))
    d2 = await apply_change(db, gm, UpdateField(entity_id=entity.id, field="description", value="two",
                                                proposal_id=proposal))
    assert d1.id != d2.id and (await _get(db, Entity, entity.id)).description == "two"
    quest = await _create(db, gm, type="quest")
    s1 = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="completed", proposal_id=proposal))
    assert (await apply_change(db, gm, SetStatus(entity_id=quest.id, status="completed",
                                                 proposal_id=proposal))).id == s1.id
    n1 = await apply_change(db, gm, CanonNote(entity_id=entity.id, note="a", proposal_id=proposal))
    n2 = await apply_change(db, gm, CanonNote(entity_id=entity.id, note="b", proposal_id=proposal))
    assert n1.id != n2.id
    assert (await apply_change(db, gm, CanonNote(entity_id=entity.id, note="b", proposal_id=proposal))).id == n2.id


async def test_a_player_with_a_malformed_change_gets_not_found(db, ev4, gm):
    player = await _player(ev4, db)
    for bad in ({"op": "nope"}, {"op": "update_field", "field": "visibility"}, "garbage"):
        with pytest.raises(NotFound):
            await apply_change(db, player, bad)
    with pytest.raises(NotFound):
        await apply_change(db, await share_ctx(db, ev4.a.share_token), {"op": "nope"})


async def test_set_visibility_on_a_deleted_or_merged_entity(db, ev4, gm):
    gone, absorbed, survivor = await _create(db, gm), await _create(db, gm), await _create(db, gm)
    await apply_change(db, gm, DeleteEntity(entity_id=gone.id))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=survivor.id))
    for e in (gone, absorbed):
        await set_visibility(db, gm, RecordRef(kind="entity", id=e.id), "party")
        assert (await _get(db, Entity, e.id)).visibility == "party"
    # Still GM-only to a Player: deleted and merged rows are GM whatever their Visibility.
    player = await _player(ev4, db)
    with pytest.raises(NotFound):
        await scoped_get(db, Entity, player, gone.id)


async def test_naive_datetimes_are_utc(db, ev4, gm):
    src, tgt = await _create(db, gm), await _create(db, gm)
    rt = await _rel_type(db, ev4.a.campaign_id)
    row = await apply_change(db, gm, AddRelationship(entity_id=src.id, target_entity_id=tgt.id,
                                                     relationship_type_id=rt.id,
                                                     started_at=datetime(2026, 3, 1, 12, 0)))
    assert row.new_value["started_at"] == "2026-03-01T12:00:00+00:00"


async def test_source_deleted_records_the_field_and_value(db, ev4, gm):
    entity = await _create(db, gm, description="From it")
    row = await apply_change(db, gm.as_system("entry_deleted"), SourceDeleted(
        entity_id=entity.id, field="description", source_journal_id=_entry(ev4)))
    assert row.new_value == {"journal_id": str(_entry(ev4)), "field": "description", "current_value": "From it",
                             "flagged": 0}


# ── The as_system grep test ────────────────────────────────────────────────

def _as_system_refs(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [n.lineno for n in ast.walk(tree)
            if (isinstance(n, ast.Attribute) and n.attr == "as_system") or (isinstance(n, ast.Name)
                                                                           and n.id == "as_system")]


def test_world_service_builds_no_system_ctx():
    """Only E0-WorldCore.9's merge wrapper may build as_system("merge") here;
    this story builds none (the tests do). CI-8 and its Visibility gate pass."""
    spec = importlib.util.spec_from_file_location("csq_wc3", REPO / "scripts" / "check_scoped_queries.py")
    csq = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, csq)  # dataclasses look their module up
    spec.loader.exec_module(csq)
    assert csq.check() == [] and csq.check_visibility_writes() == []
    app_dir = REPO / "src" / "backend" / "app"
    assert _as_system_refs(app_dir / "services" / "world_service.py") == []
    users = {p.relative_to(app_dir.parent).as_posix() for p in app_dir.rglob("*.py") if _as_system_refs(p)}
    assert users <= {"app/access/context.py", "app/services/journal_service.py"}


# ── Adversarial review: gaps and probes ────────────────────────────────────

async def test_two_steps_under_one_proposal_both_apply(db, ev4, gm):
    proposal = uuid.uuid4()
    quest = await _create(db, gm, type="quest")
    s1 = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="one", proposal_id=proposal))
    s2 = await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="two", proposal_id=proposal))
    assert s1.id != s2.id
    assert (await apply_change(db, gm, AddQuestStep(entity_id=quest.id, text="two", proposal_id=proposal))).id == s2.id
    steps = (await db.execute(sa.select(QuestStep.text).where(QuestStep.quest_entity_id == quest.id))).scalars().all()
    assert sorted(steps) == ["one", "two"]


async def test_entry_deleted_ctx_cannot_revert_add_or_delete(db, ev4, gm):
    entity = await _create(db, gm)
    create = (await _changes(db, entity.id))[0]
    system = gm.as_system("entry_deleted")
    before = await _counts(db, ev4.a.campaign_id)
    for change in (Revert(change_id=create.id), AddMention(entity_id=entity.id, journal_id=_entry(ev4)),
                   DeleteEntity(entity_id=entity.id), ConfirmMention(mention_id=uuid.uuid4())):
        with pytest.raises(NotFound):
            await apply_change(db, system, change)
    assert await _counts(db, ev4.a.campaign_id) == before


async def _floored(db, ev4, gm):
    """A Party survivor holding a `gm`-floored alias and Mention from a GM-only absorbed Entity."""
    survivor, absorbed = await _create(db, gm), await _create(db, gm)
    await set_visibility(db, gm, RecordRef(kind="entity", id=survivor.id), "party")
    await apply_change(db, gm, AddAlias(entity_id=absorbed.id, alias="Grey Lady"))
    mention = await apply_change(db, gm, AddMention(entity_id=absorbed.id, journal_id=_entry(ev4)))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=survivor.id))
    return survivor, uuid.UUID(mention.new_value["mention_id"])


async def test_reverting_a_floored_remove_restores_the_floor(db, ev4, gm):
    survivor, mention_id = await _floored(db, ev4, gm)
    alias = await apply_change(db, gm, RemoveAlias(entity_id=survivor.id, alias="Grey Lady"))
    mention = await apply_change(db, gm, RemoveMention(mention_id=mention_id))
    await revert_change(db, gm, alias.id)
    await revert_change(db, gm, mention.id)
    row = (await db.execute(sa.select(EntityAlias).where(EntityAlias.entity_id == survivor.id,
                                                         EntityAlias.normalized_alias == "grey lady")
                            .execution_options(populate_existing=True))).scalar_one()
    assert row.visibility_floor == "gm"
    assert (await _get(db, EntityMention, mention_id)).visibility_floor == "gm"
    player = await _player(ev4, db)
    assert "Grey Lady" not in {a.alias for a in (await db.execute(ws.scoped_select(EntityAlias, player))).scalars()}


async def test_a_floored_remove_alias_repeats_under_its_proposal(db, ev4, gm):
    survivor, _ = await _floored(db, ev4, gm)
    proposal = uuid.uuid4()
    first = await apply_change(db, gm, RemoveAlias(entity_id=survivor.id, alias="Grey Lady", proposal_id=proposal))
    assert first.field is None  # floored: its history stays GM
    again = await apply_change(db, gm, RemoveAlias(entity_id=survivor.id, alias="Grey Lady", proposal_id=proposal))
    assert again.id == first.id


async def test_an_entity_ref_repeat_matches_its_canonical_id(db, ev4, gm):
    item, holder = await _create(db, gm, type="item"), await _create(db, gm)
    proposal = uuid.uuid4()
    change = UpdateField(entity_id=item.id, field="attributes.holder_entity_id", value=str(holder.id).upper(),
                         proposal_id=proposal)
    first = await apply_change(db, gm, change)
    assert (await apply_change(db, gm, change)).id == first.id
    assert [r.op for r in await _changes(db, item.id)] == ["create_entity", "update_field"]


async def test_concurrent_applies_of_one_proposal_write_once(db, ev4, gm):
    """Two sessions apply the same approved proposal at once (E1 replay)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    await db.commit()
    proposal, eid = uuid.uuid4(), uuid.uuid4()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    for change in (CreateEntity(type="item", name="Bell", proposal_id=proposal),
                   CreateEntity(entity_id=eid, type="item", name="Rope", proposal_id=proposal)):
        async with factory() as s1, factory() as s2:
            first = await apply_change(s1, gm, change)
            second = asyncio.create_task(apply_change(s2, gm, change))
            await asyncio.sleep(0.3)  # s2 is now waiting (or done)
            await s1.commit()
            again = await second
            await s2.commit()
            assert again.id == first.id
    names = (await db.execute(sa.select(Entity.name).where(Entity.campaign_id == ev4.a.campaign_id,
                                                           Entity.name.in_(["Bell", "Rope"])))).scalars().all()
    assert sorted(names) == ["Bell", "Rope"]


async def test_an_outer_rollback_drops_canon_changed(db, ev4, gm, events):
    await db.commit()
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            await apply_change(db, gm, CreateEntity(type="item", name="Undone"))
            raise RuntimeError
    await db.commit()
    await hooks.drain()
    assert events == []


async def test_revert_of_a_revert_and_after_a_merge(db, ev4, gm):
    quest = await _create(db, gm, type="quest")
    done = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="completed"))
    stamp = (await _get(db, Entity, quest.id)).attributes["completed_at"]
    undo = await revert_change(db, gm, done.id)
    assert "completed_at" not in ((await _get(db, Entity, quest.id)).attributes or {})
    redo = await revert_change(db, gm, undo.id)
    q = await _get(db, Entity, quest.id)
    assert (q.attributes["completed_at"], redo.new_value["completed_at"]) == (stamp, stamp)
    assert await _code(revert_change(db, gm, undo.id)) == "superseded"  # redo changed it since
    survivor, absorbed = await _create(db, gm), await _create(db, gm)
    edit = await apply_change(db, gm, UpdateField(entity_id=absorbed.id, field="description", value="x"))
    await apply_change(db, gm.as_system("merge"), Merge(entity_id=absorbed.id, survivor_id=survivor.id))
    for force in (False, True):
        assert await _code(revert_change(db, gm, edit.id, force=force)) == "merged"


async def _projected_history(db, ctx, entity_id) -> list[dict]:
    from app.access import project_all
    rows = (await db.execute(ws.scoped_select(EntityChange, ctx).where(EntityChange.entity_id == entity_id)
                             .order_by(EntityChange.created_at, EntityChange.id)
                             .execution_options(populate_existing=True))).scalars().all()
    return [b.model_dump(mode="json") for b in await project_all(db, rows, ctx)]


async def test_a_quest_status_row_does_not_carry_a_hidden_attribute(db, ev4, gm):
    """Party Quest, attributes hidden: its status rows must not show completed_at to a Player."""
    quest = await _create(db, gm, type="quest", status="completed")
    await set_visibility(db, gm, RecordRef(kind="entity", id=quest.id), "party")
    await set_visibility(db, gm, RecordRef(kind="entity", id=quest.id, field="attributes"), "gm")
    secret = "1999-12-31T23:59:00+00:00"
    await apply_change(db, gm, UpdateField(entity_id=quest.id, field="attributes.completed_at", value=secret))
    status = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="active"))
    undo = await revert_change(db, gm, status.id)  # a revert row carries it too
    await db.commit()
    player = await _player(ev4, db)
    seen = await _projected_history(db, player, quest.id)
    assert secret not in repr(seen)
    by_id = {r["id"]: r for r in seen}
    # The status itself is still shown; only the hidden attribute is dropped.
    assert by_id[str(status.id)]["old_value"] == {"status": "completed"}
    assert by_id[str(status.id)]["new_value"] == {"status": "active"}
    assert by_id[str(undo.id)]["new_value"] == {"status": "completed"}
    assert all(r["field"] != "attributes.completed_at" for r in seen)  # that row is GM (attributes hidden)
    # The GM sees every value.
    assert secret in repr(await _projected_history(db, gm, quest.id))


async def test_a_completion_stamp_row_does_not_reveal_a_hidden_status(db, ev4, gm):
    """Party Quest, status hidden, attributes shown: an attributes.completed_at row reveals the status."""
    quest = await _create(db, gm, type="quest")
    await set_visibility(db, gm, RecordRef(kind="entity", id=quest.id), "party")
    await set_visibility(db, gm, RecordRef(kind="entity", id=quest.id, field="status"), "gm")
    stamp = "2001-02-03T04:05:06+00:00"
    edit = await apply_change(db, gm, UpdateField(entity_id=quest.id, field="attributes.completed_at", value=stamp))
    other = await apply_change(db, gm, UpdateField(entity_id=quest.id, field="attributes.reward", value="Gold"))
    await db.commit()
    player = await _player(ev4, db)
    by_id = {r["id"]: r for r in await _projected_history(db, player, quest.id)}
    assert (by_id[str(edit.id)]["old_value"], by_id[str(edit.id)]["new_value"]) == (None, None)
    assert by_id[str(other.id)]["new_value"] == "Gold"  # other attributes are untouched
    assert stamp not in repr(by_id)
    gm_view = {r["id"]: r for r in await _projected_history(db, gm, quest.id)}
    assert gm_view[str(edit.id)]["new_value"] == stamp


async def test_history_values_fail_closed_without_the_parent(db, ev4, gm):
    """project() with no loaded parent and none given drops the carried keys for a non-GM."""
    from app.access import project, registry as access_registry
    quest = await _create(db, gm, type="quest", status="completed")
    await set_visibility(db, gm, RecordRef(kind="entity", id=quest.id), "party")
    status = await apply_change(db, gm, SetStatus(entity_id=quest.id, status="active"))
    await db.commit()
    player = await _player(ev4, db)
    row = (await db.execute(ws.scoped_select(EntityChange, player).where(EntityChange.id == status.id)
                            .execution_options(populate_existing=True))).scalar_one()
    assert "entity" in sa.inspect(row).unloaded
    body = project(row, player).model_dump(mode="json")
    assert body["old_value"] == {"status": "completed"} and body["new_value"] == {"status": "active"}
    # Given the parent (attributes visible), completed_at is shown.
    parent = await _get(db, Entity, quest.id)
    assert "completed_at" in project(row, player, parent=parent).model_dump(mode="json")["old_value"]
    assert access_registry.hidden_value_keys(row, gm) == frozenset()
    assert access_registry.hidden_value_keys(row, player) == frozenset({"completed_at", "journal_id"})
    assert access_registry.hidden_value_keys(row, player, parent) == frozenset({"journal_id"})



async def test_a_source_deleted_row_hides_its_entry_from_a_player(db, ev4, gm):
    """A field-based source_deleted row is readable with its field, but its journal_id is GM provenance."""
    entity = await _create(db, gm, type="location", name="Harbor")
    await set_visibility(db, gm, RecordRef(kind="entity", id=entity.id), "party")
    journal_id = _entry(ev4)
    row = await apply_change(db, gm.as_system("entry_deleted"), SourceDeleted(
        entity_id=entity.id, source_journal_id=journal_id, field="description"))
    await db.commit()
    player = await _player(ev4, db)
    seen = {r["id"]: r for r in await _projected_history(db, player, entity.id)}
    assert str(row.id) in seen
    assert "journal_id" not in seen[str(row.id)]["new_value"]
    assert str(journal_id) not in repr(seen)
    gm_view = {r["id"]: r for r in await _projected_history(db, gm, entity.id)}
    assert gm_view[str(row.id)]["new_value"]["journal_id"] == str(journal_id)
