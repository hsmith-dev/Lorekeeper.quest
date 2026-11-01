"""EV-4 (E0-WorldCore.2): the F3-world copy exposes nothing.

The canary Campaign's NPCs and Quests (their notes hold canaries) are copied
by the F3-world revision's own data steps, then each copied Entity gets an
alias, a narrative Mention, a quest step and an edge, all through the
registry's defaults (GM-only). Through `scoped_select` / `scoped_get` and
`project`, none of the copied Entities or the rows that hang off them is
visible to a Player, a Share Link holder or a Player who is GM of another
Campaign; a hidden id answers exactly like a missing one. The gm_owner sees
all of it (positive control), canaries included.
"""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from sqlalchemy.orm import selectinload

from app.access import (
    REGISTRY, NotFound, audience_of, ctx_for, project, project_all, scoped_get, scoped_select, share_ctx,
)
from app.access import registry as access_registry
from app.db.models import (
    Entity, EntityAlias, EntityChange, EntityMention, EntityRelationship, JournalEntry, QuestStep, RelationshipType,
)
from app.domain.enums import MentionOrigin, MentionSourceField
from tests.ev4.families import canary_hits

BACKEND_DIR = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "f3_world_revision_ev4", BACKEND_DIR / "migrations" / "versions" / "03c0b504f1d1_f3_world_entities_legacy_copy.py")
f3_world = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f3_world)

WORLD_MODELS = (Entity, EntityAlias, EntityMention, EntityRelationship, QuestStep, EntityChange)
NON_GM = ("player", "anon_share", "cross_gm_player")


async def _copy(db) -> None:
    await db.run_sync(lambda session: f3_world.apply_data_steps(session.connection()))
    await db.commit()


async def _hang_rows_off(db, campaign_id: uuid.UUID, entities: list[Entity]) -> None:
    """One alias, Mention, step and edge per copied Entity, all at their defaults."""
    entry_id = (await db.execute(sa.select(JournalEntry.id).where(JournalEntry.campaign_id == campaign_id)
                                 .limit(1))).scalar_one()
    rel_type = (await db.execute(sa.select(RelationshipType).where(RelationshipType.campaign_id == campaign_id,
                                                                   RelationshipType.key == "ally_of"))).scalar_one()
    for e in entities:
        db.add(EntityAlias(campaign_id=campaign_id, entity_id=e.id, alias=f"{e.name} alias",
                           normalized_alias=f"{e.id}"))
        db.add(EntityMention(campaign_id=campaign_id, journal_id=entry_id, entity_id=e.id, quote=e.name,
                             source_field=MentionSourceField.NARRATIVE, origin=MentionOrigin.MIGRATION))
        if e.type == "quest":
            db.add(QuestStep(campaign_id=campaign_id, quest_entity_id=e.id, position=0, text="Ask around"))
    db.add(EntityRelationship(campaign_id=campaign_id, source_entity_id=entities[0].id,
                              target_entity_id=entities[-1].id, relationship_type_id=rel_type.id))
    await db.commit()


async def _visible(db, ctx, model) -> list:
    return list((await db.execute(scoped_select(model, ctx))).scalars().all())


@pytest.fixture
async def world(ev4, db):
    await _copy(db)
    a = ev4.a.campaign_id
    copied = list((await db.execute(sa.select(Entity).where(Entity.campaign_id == a)
                                    .order_by(Entity.type, Entity.name))).scalars().all())
    assert {e.legacy_npc_id for e in copied if e.legacy_npc_id} == set(ev4.a.ids["npcs"])
    assert {e.legacy_quest_id for e in copied if e.legacy_quest_id} == set(ev4.a.ids["quests"])
    await _hang_rows_off(db, a, copied)
    return copied


async def _ctx(ev4, db, name: str):
    actor = await ev4.actor(name)
    if name == "anon_share":
        return actor, await share_ctx(db, actor.share_token)
    return actor, await ctx_for(db, actor.user_id, ev4.a.campaign_id)


async def test_gm_owner_sees_the_copied_world(ev4, db, world):
    actor, ctx = await _ctx(ev4, db, "gm_owner")
    entities = await _visible(db, ctx, Entity)
    assert {e.id for e in entities} == {e.id for e in world}
    assert all(e.visibility == "gm" and e.field_visibility == {} for e in entities)
    for model in WORLD_MODELS:
        assert await _visible(db, ctx, model), model.__name__
    body = json.dumps([b.model_dump(mode="json") for b in await project_all(db, entities, ctx)])
    # The legacy notes (canaries) came over as gm_notes, and the GM may see them.
    assert ev4.a.canary("NPCNOTES").token in body and ev4.a.canary("QUESTNOTES").token in body
    assert canary_hits(actor, body) == []


@pytest.mark.parametrize("name", NON_GM)
async def test_non_gm_sees_no_copied_row(ev4, db, world, name):
    actor, ctx = await _ctx(ev4, db, name)
    for model in WORLD_MODELS:
        rows = await _visible(db, ctx, model)
        assert rows == [], f"{name} sees {len(rows)} {model.__name__} row(s)"
    if name == "cross_gm_player":
        # As GM of their own Campaign B they still see nothing of A.
        own = await ctx_for(db, actor.user_id, ev4.b.campaign_id)
        for model in WORLD_MODELS:
            assert all(r.campaign_id == ev4.b.campaign_id for r in await _visible(db, own, model))
    # Hidden and missing answer the same.
    for e in world:
        with pytest.raises(NotFound) as hidden:
            await scoped_get(db, Entity, ctx, e.id)
        with pytest.raises(NotFound) as missing:
            await scoped_get(db, Entity, ctx, uuid.uuid4())
        assert (hidden.value.status_code, hidden.value.detail) == (missing.value.status_code, missing.value.detail)
    # The vocabulary is Campaign-public and carries no canary.
    types = await _visible(db, ctx, RelationshipType)
    body = json.dumps([b.model_dump(mode="json") for b in await project_all(db, types, ctx)])
    assert canary_hits(actor, body) == []


# ── Loaded relationships: project() and audience_of() without parents= ─────

def _loaders(model) -> list:
    reg = REGISTRY[model]
    links = reg.narrowed_by if isinstance(reg, access_registry.Stored) else reg.derive_from
    return [selectinload(getattr(model, link.attr)) for link in links]


def _parents(model, row) -> list:
    reg = REGISTRY[model]
    links = reg.narrowed_by if isinstance(reg, access_registry.Stored) else reg.derive_from
    return [getattr(row, link.attr) for link in links]


async def _loaded(db, ctx, model) -> list:
    db.expire_all()  # read what the raw UPDATEs wrote, parents included
    stmt = scoped_select(model, ctx).options(*_loaders(model))
    return list((await db.execute(stmt)).scalars().all())


LOADED_MODELS = (EntityRelationship, EntityAlias, EntityMention, QuestStep, EntityChange)


async def test_loaded_rows_project_and_narrow(ev4, db, world):
    a = ev4.a.campaign_id
    published, kept_gm = world[0], world[-1]
    assert published.id != kept_gm.id
    rel_type = (await db.execute(sa.select(RelationshipType).where(
        RelationshipType.campaign_id == a, RelationshipType.key == "related_to"))).scalar_one()
    floored = EntityRelationship(campaign_id=a, source_entity_id=published.id, target_entity_id=published.id,
                                 relationship_type_id=rel_type.id, visibility="party", visibility_floor="gm")
    shown = EntityRelationship(campaign_id=a, source_entity_id=published.id, target_entity_id=published.id,
                               relationship_type_id=rel_type.id, visibility="party")
    db.add_all([floored, shown])
    await db.commit()
    published_id, kept_gm_id, floored_id, shown_id = published.id, kept_gm.id, floored.id, shown.id
    # Publish one Entity and the edges (raw SQL: the test plays the GM's set_visibility).
    await db.execute(sa.text("UPDATE entities SET visibility = 'party' WHERE id = :id"), {"id": published_id})
    await db.execute(sa.text("UPDATE entity_relationships SET visibility = 'party' WHERE campaign_id = :c"),
                     {"c": a})
    await db.commit()
    hidden_edge_id = (await db.execute(sa.select(EntityRelationship.id).where(
        EntityRelationship.campaign_id == a, EntityRelationship.target_entity_id == kept_gm_id))).scalar_one()

    _, gm = await _ctx(ev4, db, "gm_owner")
    _, player = await _ctx(ev4, db, "player")
    for model in LOADED_MODELS:
        rows = await _loaded(db, gm, model)
        assert rows, model.__name__
        for row in rows:
            assert audience_of(row) == audience_of(row, parents=_parents(model, row)), model.__name__
            project(row, gm)  # every registered loader is enough to project

    edges = {r.id: r for r in await _loaded(db, gm, EntityRelationship)}
    assert {hidden_edge_id, floored_id, shown_id} <= set(edges)
    for edge_id in (hidden_edge_id, floored_id):  # a GM endpoint / a GM floor
        with pytest.raises(NotFound):
            project(edges[edge_id], player)
    project(edges[shown_id], player)
    seen = {r.id for r in await _loaded(db, player, EntityRelationship)}
    assert shown_id in seen
    assert hidden_edge_id not in seen and floored_id not in seen

    for model in (EntityAlias, EntityMention, EntityChange):
        rows = await _loaded(db, player, model)
        assert rows and all(_parents(model, r)[-1].id == published_id for r in rows), model.__name__
        for row in rows:
            assert audience_of(row) == audience_of(row, parents=_parents(model, row))
            project(row, player)
    assert await _loaded(db, player, QuestStep) == []  # its Quest stayed GM-only
