"""EV-4 probes for api/routes/quests.py, the adapter over `entities`
(E0-WorldCore.6).

Campaign A's seeded Quest gets its GM-only Entity (the F3 id and legacy id,
canary gm_notes). For a non-GM it, a deleted Quest, an outsider Campaign's
Quest and a missing id answer alike on every item route; the list is `[]`
and does not move when the GM writes something GM-only; a published Quest
with its status hidden reads like an unset one (`active`). A Player write
answers like a missing one and writes nothing; a GM gets the legacy shape.
"""
from __future__ import annotations

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_quest, assert_same_answer, authenticated, entity_rows, is_gm_of_a, outsider, publish, world_quest,
)
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

WRITERS = (*DEFAULT_ACTORS, "co_gm")


async def _hidden_ids(ev4):
    """Quest ids hidden from every non-GM-of-A actor: A's copied Quest (by
    legacy and by Entity id), a deleted Quest, and an outsider Campaign's."""
    from app.access import ctx_for
    from app.domain import legacy_world as lw
    from app.services.world_service import apply_change

    legacy_id = await world_quest(ev4)
    gone = await add_quest(ev4)
    await publish(ev4, gone)
    await apply_change(ev4.db, await ctx_for(ev4.db, ev4.a.owner_id, ev4.a.campaign_id),
                       {"op": "delete_entity", "entity_id": gone})
    await ev4.db.commit()
    other = await outsider(ev4)
    return [legacy_id, lw.legacy_entity_id("quest", legacy_id), gone, await world_quest(ev4, other)]


@ev4_probe("GET", "/api/quests/", actors=(*DEFAULT_ACTORS, "player_2"))
async def probe_list_quests(ev4, actor):
    a = ev4.a.campaign_id
    await world_quest(ev4)
    hidden = await outsider(ev4)
    await world_quest(ev4, hidden)
    await assert_hidden_equals_missing(actor, f"/api/quests/?campaign_id={hidden.campaign_id}",
                                       f"/api/quests/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"/api/quests/?campaign_id={a}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    await assert_counts_and_ranking_unchanged(actor, f"/api/quests/?campaign_id={a}", lambda: add_quest(ev4))
    from app.access import ctx_for
    from app.services.world_service import apply_change

    gm = await ctx_for(ev4.db, ev4.a.owner_id, a)
    shown = (await apply_change(ev4.db, gm, {"op": "create_entity", "type": "quest", "name": "Lost bell",
                                             "status": "failed"})).entity_id
    await ev4.db.commit()
    await publish(ev4, shown)
    await publish(ev4, shown, "status", "gm")
    r = await actor.get(f"/api/quests/?campaign_id={a}")
    assert_no_canary(actor, r)
    body = r.json()
    assert [b["id"] for b in body] == [str(shown)] and set(body[0]) == {
        "id", "campaign_id", "title", "description", "status"}, body
    await assert_hidden_field_equals_unset(actor, f"/api/quests/{shown}", "status", unset="active")


@ev4_probe("GET", "/api/quests/{quest_id}")
async def probe_get_quest(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}")


@ev4_probe("PUT", "/api/quests/{quest_id}", actors=WRITERS)
async def probe_update_quest(ev4, actor):
    ids = await _hidden_ids(ev4)
    if is_gm_of_a(ev4, actor):
        r = await actor.put(f"/api/quests/{ids[0]}", json={"title": "Renamed", "status": "completed"})
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["id"] == str(ids[0]), r.text
        assert (r.json()["title"], r.json()["status"]) == ("Renamed", "completed")
        return
    before = await entity_rows(ev4)
    for quest in ids:
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}", method="PUT",
                                           json={"title": "Renamed", "notes": "x"})
    assert await entity_rows(ev4) == before


@ev4_probe("DELETE", "/api/quests/{quest_id}", actors=WRITERS)
async def probe_delete_quest(ev4, actor):
    ids = await _hidden_ids(ev4)
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"/api/quests/{ids[0]}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        assert (await actor.get(f"/api/quests/{ids[0]}")).status_code == 404
        return
    before = await entity_rows(ev4)
    for quest in ids:
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}", method="DELETE")
    assert await entity_rows(ev4) == before


@ev4_probe("POST", "/api/quests/", actors=WRITERS)
async def probe_create_quest(ev4, actor):
    a = ev4.a.campaign_id
    body = {"title": "Heist", "notes": "secret"}
    if is_gm_of_a(ev4, actor):
        r = await actor.post("/api/quests/", json={**body, "campaign_id": str(a)})
        assert_no_canary(actor, r)
        assert r.status_code == 201 and r.json()["status"] == "active", r.text
        return
    before = await entity_rows(ev4)
    r_hidden = await actor.post("/api/quests/", json={**body, "campaign_id": str(a)})
    r_missing = await actor.post("/api/quests/", json={**body, "campaign_id": MISSING})
    assert_same_answer(actor, r_hidden, r_missing, "Quest create")
    assert await entity_rows(ev4) == before


@ev4_probe("GET", "/api/quests/{quest_id}/entries")
async def probe_quest_entries(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}/entries", f"/api/quests/{MISSING}/entries")


@ev4_probe("POST", "/api/quests/{quest_id}/generate")
async def probe_generate_quest_description(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}/generate",
                                           f"/api/quests/{MISSING}/generate", method="POST")
