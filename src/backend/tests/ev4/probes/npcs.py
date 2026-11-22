"""EV-4 probes for api/routes/npcs.py, the adapter over `entities`
(E0-WorldCore.6).

Campaign A's seeded NPC gets its GM-only Entity (the F3 id and legacy id,
canary gm_notes), as the F3-world copy gives it. For a non-GM it, a deleted
Entity, an outsider Campaign's NPC and a missing id answer alike on every
item route; the list is `[]` and does not move when the GM writes something
GM-only; a published Character with its status hidden reads exactly like one
whose status is unset. A Player write answers like a missing one and writes
nothing; a GM (the Owner, a Co-GM) gets the legacy shape.
"""
from __future__ import annotations

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_npc, assert_same_answer, authenticated, entity_rows, is_gm_of_a, outsider, publish, world_npc,
)
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

WRITERS = (*DEFAULT_ACTORS, "co_gm")


async def _hidden_ids(ev4):
    """NPC ids hidden from every non-GM-of-A actor: A's copied NPC (by legacy
    and by Entity id), a deleted Character, and an outsider Campaign's NPC."""
    from app.access import ctx_for
    from app.domain import legacy_world as lw
    from app.services.world_service import apply_change

    legacy_id = await world_npc(ev4)
    gone = await add_npc(ev4)
    await publish(ev4, gone)
    await apply_change(ev4.db, await ctx_for(ev4.db, ev4.a.owner_id, ev4.a.campaign_id),
                       {"op": "delete_entity", "entity_id": gone})
    await ev4.db.commit()
    other = await outsider(ev4)
    return [legacy_id, lw.legacy_entity_id("npc", legacy_id), gone, await world_npc(ev4, other)]


@ev4_probe("GET", "/api/npcs/", actors=(*DEFAULT_ACTORS, "player_2"))
async def probe_list_npcs(ev4, actor):
    a = ev4.a.campaign_id
    await world_npc(ev4)
    hidden = await outsider(ev4)
    await world_npc(ev4, hidden)
    await assert_hidden_equals_missing(actor, f"/api/npcs/?campaign_id={hidden.campaign_id}",
                                       f"/api/npcs/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"/api/npcs/?campaign_id={a}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    await assert_counts_and_ranking_unchanged(actor, f"/api/npcs/?campaign_id={a}", lambda: add_npc(ev4))
    # Published Characters: one with its status hidden reads like one whose status is unset.
    from app.access import ctx_for
    from app.services.world_service import apply_change

    gm = await ctx_for(ev4.db, ev4.a.owner_id, a)
    shown = (await apply_change(ev4.db, gm, {"op": "create_entity", "type": "character", "kind": "npc",
                                             "name": "Quiet One", "status": "deceased"})).entity_id
    await ev4.db.commit()
    await publish(ev4, shown)
    await publish(ev4, shown, "status", "gm")
    r = await actor.get(f"/api/npcs/?campaign_id={a}")
    assert_no_canary(actor, r)
    body = r.json()
    assert [b["id"] for b in body] == [str(shown)] and set(body[0]) == {
        "id", "campaign_id", "name", "role", "status", "description"}, body
    await assert_hidden_field_equals_unset(actor, f"/api/npcs/{shown}", "status", unset="unknown")


@ev4_probe("GET", "/api/npcs/{npc_id}")
async def probe_get_npc(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}")


@ev4_probe("PUT", "/api/npcs/{npc_id}", actors=WRITERS)
async def probe_update_npc(ev4, actor):
    ids = await _hidden_ids(ev4)
    if is_gm_of_a(ev4, actor):
        r = await actor.put(f"/api/npcs/{ids[0]}", json={"name": "Renamed", "status": "dead"})
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["id"] == str(ids[0]), r.text
        assert (r.json()["name"], r.json()["status"]) == ("Renamed", "dead")
        return
    before = await entity_rows(ev4)
    for npc in ids:
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}", method="PUT",
                                           json={"name": "Renamed", "notes": "x"})
    assert await entity_rows(ev4) == before


@ev4_probe("DELETE", "/api/npcs/{npc_id}", actors=WRITERS)
async def probe_delete_npc(ev4, actor):
    ids = await _hidden_ids(ev4)
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"/api/npcs/{ids[0]}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        assert (await actor.get(f"/api/npcs/{ids[0]}")).status_code == 404
        return
    before = await entity_rows(ev4)
    for npc in ids:
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}", method="DELETE")
    assert await entity_rows(ev4) == before


@ev4_probe("POST", "/api/npcs/", actors=WRITERS)
async def probe_create_npc(ev4, actor):
    a = ev4.a.campaign_id
    body = {"name": "Spy", "notes": "secret", "role": "faction", "status": "dead"}
    if is_gm_of_a(ev4, actor):
        r = await actor.post("/api/npcs/", json={**body, "campaign_id": str(a)})
        assert_no_canary(actor, r)
        assert r.status_code == 201, r.text
        assert (r.json()["role"], r.json()["status"], r.json()["notes"]) == ("faction", "dead", "secret")
        return
    before = await entity_rows(ev4)
    r_hidden = await actor.post("/api/npcs/", json={**body, "campaign_id": str(a)})
    r_missing = await actor.post("/api/npcs/", json={**body, "campaign_id": MISSING})
    # A Player cannot create: refused like a missing Campaign, before writing.
    assert_same_answer(actor, r_hidden, r_missing, "NPC create")
    assert await entity_rows(ev4) == before


@ev4_probe("GET", "/api/npcs/{npc_id}/entries")
async def probe_npc_entries(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}/entries", f"/api/npcs/{MISSING}/entries")


@ev4_probe("POST", "/api/npcs/{npc_id}/generate")
async def probe_generate_npc_bio(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}/generate", f"/api/npcs/{MISSING}/generate",
                                           method="POST")
