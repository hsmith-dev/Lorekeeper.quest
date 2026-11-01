"""EV-4 (E0-WorldCore.3): world history written by apply_change exposes nothing.

The GM writes through `world_service.apply_change` and `set_visibility`: a
GM-only Entity with canaries in its fields and history, a Party Entity whose
description is hidden and then changed, whose gm_notes change, and which
gains a relationship and a Mention, and a Party Entity that is then deleted.
Through `scoped_select` and `project_all`, a Player, a Share Link holder and
a Player who is GM of another Campaign see none of the GM-only history and no
canary; they do see the Party Entity's public field changes (the control),
and the GM sees every canary.
"""
from __future__ import annotations

import json
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app.access import ctx_for, project_all, scoped_select, set_visibility, share_ctx
from app.db.models import Entity, EntityChange, RelationshipType
from app.schemas.entities import (
    AddMention, AddQuestStep, AddRelationship, CreateEntity, DeleteEntity, Merge, SetStatus, SourceDeleted,
    UpdateField, UpdateQuestStep,
)
from app.schemas.sources import RecordRef
from app.services.world_service import apply_change, revert_change
from tests.ev4.families import canary_hits
from tests.ev4.fixtures import mint_canary

NON_GM = ("player", "anon_share", "cross_gm_player")
# History a non-GM may read on a Party Entity: its public fields only.
PUBLIC_FIELDS = {"name", "status", "visibility", "attributes.goals"}


async def _ctx(ev4, db, name: str):
    actor = await ev4.actor(name)
    if name == "anon_share":
        return actor, await share_ctx(db, actor.share_token)
    return actor, await ctx_for(db, actor.user_id, ev4.a.campaign_id)


async def _history(db, ctx) -> list[EntityChange]:
    stmt = scoped_select(EntityChange, ctx).options(selectinload(EntityChange.entity))
    return list((await db.execute(stmt.execution_options(populate_existing=True))).scalars().all())


async def _body(db, ctx, rows) -> str:
    return json.dumps([b.model_dump(mode="json") for b in await project_all(db, rows, ctx)])


@pytest.fixture
async def world(ev4, db):
    a = ev4.a.campaign_id
    gm = await ctx_for(db, ev4.a.owner_id, a)
    c = {k: mint_canary(k, a).token for k in ("WCGMDESC", "WCGMNOTES", "WCGMEDIT", "WCHIDDEN", "WCPNOTES",
                                              "WCRELNOTE", "WCDELDESC", "WCMERGED", "WCSTEP", "WCSTEP2",
                                              "WCREVERT")}

    async def create(**kw) -> uuid.UUID:
        return (await apply_change(db, gm, CreateEntity(**kw))).entity_id

    secret = await create(type="character", kind="npc", name="Hidden one", description=c["WCGMDESC"],
                          gm_notes=c["WCGMNOTES"])
    await apply_change(db, gm, UpdateField(entity_id=secret, field="description", value=c["WCGMEDIT"]))
    await apply_change(db, gm, SetStatus(entity_id=secret, status="deceased"))

    party = await create(type="character", kind="npc", name="Mira")
    friend = await create(type="faction", name="The Guild")
    gone = await create(type="item", name="Bell", description=c["WCDELDESC"])
    for eid in (party, friend, gone):
        await set_visibility(db, gm, RecordRef(kind="entity", id=eid), "party")
    await set_visibility(db, gm, RecordRef(kind="entity", id=party, field="description"), "gm")
    await apply_change(db, gm, UpdateField(entity_id=party, field="description", value=c["WCHIDDEN"]))
    await apply_change(db, gm, UpdateField(entity_id=party, field="gm_notes", value=c["WCPNOTES"]))
    await apply_change(db, gm, UpdateField(entity_id=party, field="name", value="Mira Vale"))
    await apply_change(db, gm, UpdateField(entity_id=party, field="attributes.goals", value="Find the bell"))
    rt = RelationshipType(campaign_id=a, key="ally_of_wc3", label="Ally of", inverse_label="Ally of")
    db.add(rt)
    await db.flush()
    await apply_change(db, gm, AddRelationship(entity_id=party, target_entity_id=friend, relationship_type_id=rt.id,
                                               note=c["WCRELNOTE"]))
    await apply_change(db, gm, AddMention(entity_id=party, journal_id=ev4.a.ids["journal_entries"][0]))
    await apply_change(db, gm, DeleteEntity(entity_id=gone))

    # A merge into the Party Entity: its one row (field NULL) is on the survivor.
    shadow = await create(type="character", kind="npc", name=c["WCMERGED"])
    merge = await apply_change(db, gm.as_system("merge"), Merge(entity_id=shadow, survivor_id=party))
    # Steps of a GM-only Quest.
    quest = await create(type="quest", name="Secret quest")
    step = await apply_change(db, gm, AddQuestStep(entity_id=quest, text=c["WCSTEP"]))
    await apply_change(db, gm, UpdateQuestStep(step_id=uuid.UUID(step.new_value["step_id"]), text=c["WCSTEP2"]))
    # A revert of a change to the hidden description.
    hidden_edit = await apply_change(db, gm, UpdateField(entity_id=party, field="description", value=c["WCREVERT"]))
    revert = await revert_change(db, gm, hidden_edit.id)
    # Status hidden, then changed.
    await set_visibility(db, gm, RecordRef(kind="entity", id=party, field="status"), "gm")
    status = await apply_change(db, gm, SetStatus(entity_id=party, status="deceased"))
    # The journal entry is going away (field NULL).
    source = await apply_change(db, gm.as_system("entry_deleted"), SourceDeleted(
        entity_id=party, source_journal_id=ev4.a.ids["journal_entries"][0]))
    await db.commit()
    probes = {"merge": merge.id, "step": step.id, "revert": revert.id, "status": status.id, "source": source.id}
    return {"secret": secret, "party": party, "friend": friend, "gone": gone, "canaries": c, "gm": gm,
            "probes": probes, "quest": quest}


async def test_gm_sees_every_change_and_canary(ev4, db, world):
    rows = await _history(db, world["gm"])
    body = await _body(db, world["gm"], rows)
    for token in world["canaries"].values():
        assert token in body
    assert {r.entity_id for r in rows} >= {world["secret"], world["party"], world["gone"]}


@pytest.mark.parametrize("name", NON_GM)
async def test_non_gm_sees_no_gm_only_history(ev4, db, world, name):
    actor, ctx = await _ctx(ev4, db, name)
    rows = await _history(db, ctx)
    for r in rows:
        assert r.entity_id in (world["party"], world["friend"]), (name, r.op, r.field)
        assert r.field in PUBLIC_FIELDS, (name, r.op, r.field)
    # The control: the Party Entity's public changes are there.
    assert {r.field for r in rows if r.entity_id == world["party"]} >= {"name", "attributes.goals"}
    # The probes: a merge row on the Party survivor, a GM-only Quest's step rows, a revert of a
    # hidden-field change, set_status with the status hidden, source_deleted with field NULL.
    ids = {r.id for r in rows}
    assert not ids & set(world["probes"].values()), name
    assert not [r for r in rows if r.entity_id == world["quest"] or r.op in (
        "merge", "add_quest_step", "update_quest_step", "revert", "set_status", "source_deleted")], name
    body = await _body(db, ctx, rows)
    assert canary_hits(actor, body) == []
    for token in world["canaries"].values():
        assert token not in body
    entities = list((await db.execute(scoped_select(Entity, ctx))).scalars().all())
    assert {e.id for e in entities} == {world["party"], world["friend"]}
    assert canary_hits(actor, await _body(db, ctx, entities)) == []


async def test_gm_of_another_campaign_sees_nothing_of_a(ev4, db, world):
    actor = await ev4.actor("cross_gm_player")
    own = await ctx_for(db, actor.user_id, ev4.b.campaign_id)
    assert all(r.campaign_id == ev4.b.campaign_id for r in await _history(db, own))
    raw = (await db.execute(sa.select(sa.func.count()).select_from(EntityChange).where(
        EntityChange.campaign_id == ev4.a.campaign_id))).scalar_one()
    assert raw > 0
