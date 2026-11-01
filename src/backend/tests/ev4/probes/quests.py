"""EV-4 probes for api/routes/quests.py (E0-Access.4). Quests are always_gm
until F3-world (Decision B1-D4): a Player lists none, and every item route
and a create answer a hidden Quest exactly like a missing one, writing
nothing."""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, add_quest, assert_same_answer, authenticated, outsider, row_count
from tests.ev4.registry import ev4_probe


async def _hidden_ids(ev4):
    """Quest ids hidden from every non-GM-of-A actor: A's seeded Quest and an outsider Campaign's."""
    return [ev4.a.ids["quests"][0], (await outsider(ev4)).ids["quests"][0]]


@ev4_probe("GET", "/api/quests/")
async def probe_list_quests(ev4, actor):
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/quests/?campaign_id={hidden.campaign_id}",
                                       f"/api/quests/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"/api/quests/?campaign_id={a}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    await assert_counts_and_ranking_unchanged(actor, f"/api/quests/?campaign_id={a}", lambda: add_quest(ev4))


@ev4_probe("GET", "/api/quests/{quest_id}")
async def probe_get_quest(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}")


@ev4_probe("PUT", "/api/quests/{quest_id}")
async def probe_update_quest(ev4, actor):
    from app.db.models.quest import Quest

    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}", method="PUT",
                                           json={"title": "Renamed", "notes": "x"})
        assert await row_count(ev4, Quest, Quest.id == quest, Quest.title == "Renamed") == 0


@ev4_probe("DELETE", "/api/quests/{quest_id}")
async def probe_delete_quest(ev4, actor):
    from app.db.models.quest import Quest

    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}", f"/api/quests/{MISSING}", method="DELETE")
        assert await row_count(ev4, Quest, Quest.id == quest) == 1


@ev4_probe("POST", "/api/quests/")
async def probe_create_quest(ev4, actor):
    from app.db.models.quest import Quest

    a = ev4.a.campaign_id
    before = await row_count(ev4, Quest, Quest.campaign_id == a)
    body = {"title": "Heist", "notes": "secret"}
    r_hidden = await actor.post("/api/quests/", json={**body, "campaign_id": str(a)})
    r_missing = await actor.post("/api/quests/", json={**body, "campaign_id": MISSING})
    # A Player cannot see the new (GM-only) Quest: refused like a missing Campaign, before writing.
    assert_same_answer(actor, r_hidden, r_missing, "Quest create")
    assert await row_count(ev4, Quest, Quest.campaign_id == a) == before


@ev4_probe("GET", "/api/quests/{quest_id}/entries")
async def probe_quest_entries(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}/entries", f"/api/quests/{MISSING}/entries")


@ev4_probe("POST", "/api/quests/{quest_id}/generate")
async def probe_generate_quest_description(ev4, actor):
    for quest in await _hidden_ids(ev4):
        await assert_hidden_equals_missing(actor, f"/api/quests/{quest}/generate",
                                           f"/api/quests/{MISSING}/generate", method="POST")
