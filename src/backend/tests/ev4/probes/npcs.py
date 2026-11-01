"""EV-4 probes for api/routes/npcs.py (E0-Access.4). NPCs are always_gm
until F3-world (Decision B1-D4): a Player lists none, and every item route
and a create answer a hidden NPC exactly like a missing one, writing
nothing."""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, add_npc, assert_same_answer, authenticated, outsider, row_count
from tests.ev4.registry import ev4_probe


async def _hidden_ids(ev4):
    """NPC ids hidden from every non-GM-of-A actor: A's seeded NPC and an outsider Campaign's."""
    return [ev4.a.ids["npcs"][0], (await outsider(ev4)).ids["npcs"][0]]


@ev4_probe("GET", "/api/npcs/")
async def probe_list_npcs(ev4, actor):
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/npcs/?campaign_id={hidden.campaign_id}",
                                       f"/api/npcs/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"/api/npcs/?campaign_id={a}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    await assert_counts_and_ranking_unchanged(actor, f"/api/npcs/?campaign_id={a}", lambda: add_npc(ev4))


@ev4_probe("GET", "/api/npcs/{npc_id}")
async def probe_get_npc(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}")


@ev4_probe("PUT", "/api/npcs/{npc_id}")
async def probe_update_npc(ev4, actor):
    from app.db.models.npc import NpcEntry

    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}", method="PUT",
                                           json={"name": "Renamed", "notes": "x"})
        assert await row_count(ev4, NpcEntry, NpcEntry.id == npc, NpcEntry.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/npcs/{npc_id}")
async def probe_delete_npc(ev4, actor):
    from app.db.models.npc import NpcEntry

    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}", f"/api/npcs/{MISSING}", method="DELETE")
        assert await row_count(ev4, NpcEntry, NpcEntry.id == npc) == 1


@ev4_probe("POST", "/api/npcs/")
async def probe_create_npc(ev4, actor):
    from app.db.models.npc import NpcEntry

    a = ev4.a.campaign_id
    before = await row_count(ev4, NpcEntry, NpcEntry.campaign_id == a)
    body = {"name": "Spy", "notes": "secret"}
    r_hidden = await actor.post("/api/npcs/", json={**body, "campaign_id": str(a)})
    r_missing = await actor.post("/api/npcs/", json={**body, "campaign_id": MISSING})
    # A Player cannot see the new (GM-only) NPC: refused like a missing Campaign, before writing.
    assert_same_answer(actor, r_hidden, r_missing, "NPC create")
    assert await row_count(ev4, NpcEntry, NpcEntry.campaign_id == a) == before


@ev4_probe("GET", "/api/npcs/{npc_id}/entries")
async def probe_npc_entries(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}/entries", f"/api/npcs/{MISSING}/entries")


@ev4_probe("POST", "/api/npcs/{npc_id}/generate")
async def probe_generate_npc_bio(ev4, actor):
    for npc in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/npcs/{npc}/generate", f"/api/npcs/{MISSING}/generate",
                                           method="POST")
