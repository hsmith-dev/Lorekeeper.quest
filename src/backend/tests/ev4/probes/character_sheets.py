"""EV-4 probes for api/routes/character_sheets.py (E0-Access.4). The seeded
sheet is visibility gm (canary name and data): absent from lists and from
template counts, and answered like a missing sheet by id."""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, add_sheet, assert_same_answer, authenticated, outsider, row_count
from tests.ev4.registry import ev4_probe

BASE = "/api/character-sheets"


async def _hidden_sheets(ev4):
    return [ev4.a.ids["character_sheets"][0], await add_sheet(ev4, visibility="private"),
            (await outsider(ev4)).ids["character_sheets"][0]]


@ev4_probe("GET", "/api/character-sheets/")
async def probe_list_sheets(ev4, actor):
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/?campaign_id={hidden.campaign_id}",
                                       f"{BASE}/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    r = await actor.get(f"{BASE}/?campaign_id={a}")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    await assert_counts_and_ranking_unchanged(actor, f"{BASE}/?campaign_id={a}", lambda: add_sheet(ev4))


@ev4_probe("GET", "/api/character-sheets/{sheet_id}")
async def probe_get_sheet(ev4, actor):
    for sheet in await _hidden_sheets(ev4):
        await assert_hidden_equals_missing(actor, f"{BASE}/{sheet}", f"{BASE}/{MISSING}")


@ev4_probe("PATCH", "/api/character-sheets/{sheet_id}")
async def probe_update_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    for sheet in await _hidden_sheets(ev4):
        await assert_hidden_equals_missing(actor, f"{BASE}/{sheet}", f"{BASE}/{MISSING}", method="PATCH",
                                           json={"name": "Renamed"})
        assert await row_count(ev4, CharacterSheet, CharacterSheet.id == sheet, CharacterSheet.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/character-sheets/{sheet_id}")
async def probe_delete_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    for sheet in await _hidden_sheets(ev4):
        await assert_hidden_equals_missing(actor, f"{BASE}/{sheet}", f"{BASE}/{MISSING}", method="DELETE")
        assert await row_count(ev4, CharacterSheet, CharacterSheet.id == sheet) == 1


@ev4_probe("POST", "/api/character-sheets/")
async def probe_create_sheet(ev4, actor):
    hidden = await outsider(ev4)
    a = str(ev4.a.campaign_id)
    r_hidden = await actor.post(f"{BASE}/", json={"campaign_id": a, "template_id": str(
        hidden.ids["character_sheet_templates"][0]), "name": "Pip"})
    r_missing = await actor.post(f"{BASE}/", json={"campaign_id": a, "template_id": MISSING, "name": "Pip"})
    assert_same_answer(actor, r_hidden, r_missing, "template")


@ev4_probe("GET", "/api/character-sheets/templates")
async def probe_list_templates(ev4, actor):
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/templates?campaign_id={hidden.campaign_id}",
                                       f"{BASE}/templates?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    url = f"{BASE}/templates?campaign_id={a}"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    # character_count counts only sheets the caller sees (the seeded one is gm).
    assert [t["character_count"] for t in r.json()] == [0], r.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: add_sheet(ev4))


@ev4_probe("POST", "/api/character-sheets/templates")
async def probe_create_template(ev4, actor):
    hidden = await outsider(ev4)
    r_hidden = await actor.post(f"{BASE}/templates", json={"campaign_id": str(hidden.campaign_id), "name": "T"})
    r_missing = await actor.post(f"{BASE}/templates", json={"campaign_id": MISSING, "name": "T"})
    assert_same_answer(actor, r_hidden, r_missing, "Campaign")


@ev4_probe("PATCH", "/api/character-sheets/templates/{template_id}")
async def probe_update_template(ev4, actor):
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{hidden.ids['character_sheet_templates'][0]}",
                                       f"{BASE}/templates/{MISSING}", method="PATCH", json={"name": "Renamed"})
    if not authenticated(actor):
        return
    # The write response counts only visible sheets.
    r = await actor.patch(f"{BASE}/templates/{ev4.a.ids['character_sheet_templates'][0]}", json={"name": "Adventurer"})
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json()["character_count"] == 0, r.text


@ev4_probe("DELETE", "/api/character-sheets/templates/{template_id}")
async def probe_delete_template(ev4, actor):
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{hidden.ids['character_sheet_templates'][0]}",
                                       f"{BASE}/templates/{MISSING}", method="DELETE")
