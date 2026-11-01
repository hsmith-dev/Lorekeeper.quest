"""EV-4 probes for api/routes/character_sheets.py (E0-Access.4). The seeded
sheet is visibility gm (canary name and data): absent from lists and from
template counts, and answered like a missing sheet by id.

E0-Access.6: every sheet and template write goes through access.can_write.
A Player may write only the sheet of their own linked PC, which no sheet is
until F3-world, so a Player's write on a visible sheet or template (and a
create) answers exactly like a missing one and changes nothing. A Co-GM
writes as before."""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import (
    MISSING, add_sheet, assert_same_answer, authenticated, is_gm_of_a, outsider, row_count,
)
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

BASE = "/api/character-sheets"
WITH_CO_GM = (*DEFAULT_ACTORS, "co_gm")


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


@ev4_probe("PATCH", "/api/character-sheets/{sheet_id}", actors=WITH_CO_GM)
async def probe_update_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    party = await add_sheet(ev4, visibility="party")
    if is_gm_of_a(ev4, actor):
        r = await actor.patch(f"{BASE}/{party}", json={"name": "Renamed"})
        assert r.status_code == 200, r.text
        assert_no_canary(actor, r)
        return
    # Hidden sheets, and (E0-Access.6) a visible Party sheet: like missing.
    for sheet in [*await _hidden_sheets(ev4), party]:
        await assert_hidden_equals_missing(actor, f"{BASE}/{sheet}", f"{BASE}/{MISSING}", method="PATCH",
                                           json={"name": "Renamed"})
        assert await row_count(ev4, CharacterSheet, CharacterSheet.id == sheet, CharacterSheet.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/character-sheets/{sheet_id}", actors=WITH_CO_GM)
async def probe_delete_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    party = await add_sheet(ev4, visibility="party")
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"{BASE}/{party}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        assert await row_count(ev4, CharacterSheet, CharacterSheet.id == party) == 0
        return
    for sheet in [*await _hidden_sheets(ev4), party]:
        await assert_hidden_equals_missing(actor, f"{BASE}/{sheet}", f"{BASE}/{MISSING}", method="DELETE")
        assert await row_count(ev4, CharacterSheet, CharacterSheet.id == sheet) == 1


@ev4_probe("POST", "/api/character-sheets/", actors=WITH_CO_GM)
async def probe_create_sheet(ev4, actor):
    from app.db.models.character_sheet import CharacterSheet

    hidden = await outsider(ev4)
    a = str(ev4.a.campaign_id)
    r_hidden = await actor.post(f"{BASE}/", json={"campaign_id": a, "template_id": str(
        hidden.ids["character_sheet_templates"][0]), "name": "Pip"})
    r_missing = await actor.post(f"{BASE}/", json={"campaign_id": a, "template_id": MISSING, "name": "Pip"})
    assert_same_answer(actor, r_hidden, r_missing, "template")
    template = str(ev4.a.ids["character_sheet_templates"][0])
    before = await row_count(ev4, CharacterSheet, CharacterSheet.campaign_id == ev4.a.campaign_id)
    r = await actor.post(f"{BASE}/", json={"campaign_id": a, "template_id": template, "name": "Pip"})
    if is_gm_of_a(ev4, actor):
        assert r.status_code == 201, r.text
        assert_no_canary(actor, r)
        return
    # E0-Access.6: a Player's create (a sheet they could see) is refused like a missing Campaign.
    r_missing = await actor.post(f"{BASE}/", json={"campaign_id": MISSING, "template_id": template, "name": "Pip"})
    assert_same_answer(actor, r, r_missing, "sheet create")
    assert await row_count(ev4, CharacterSheet, CharacterSheet.campaign_id == ev4.a.campaign_id) == before


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


@ev4_probe("POST", "/api/character-sheets/templates", actors=WITH_CO_GM)
async def probe_create_template(ev4, actor):
    from app.db.models.character_sheet import CharacterSheetTemplate

    hidden = await outsider(ev4)
    r_hidden = await actor.post(f"{BASE}/templates", json={"campaign_id": str(hidden.campaign_id), "name": "T"})
    r_missing = await actor.post(f"{BASE}/templates", json={"campaign_id": MISSING, "name": "T"})
    assert_same_answer(actor, r_hidden, r_missing, "Campaign")
    a = ev4.a.campaign_id
    before = await row_count(ev4, CharacterSheetTemplate, CharacterSheetTemplate.campaign_id == a)
    r = await actor.post(f"{BASE}/templates", json={"campaign_id": str(a), "name": "T"})
    if is_gm_of_a(ev4, actor):
        assert r.status_code == 201, r.text
        assert_no_canary(actor, r)
        return
    # E0-Access.6: a Player's template create is refused like a missing Campaign.
    assert_same_answer(actor, r, r_missing, "template create")
    assert await row_count(ev4, CharacterSheetTemplate, CharacterSheetTemplate.campaign_id == a) == before


@ev4_probe("PATCH", "/api/character-sheets/templates/{template_id}", actors=WITH_CO_GM)
async def probe_update_template(ev4, actor):
    from app.db.models.character_sheet import CharacterSheetTemplate

    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{hidden.ids['character_sheet_templates'][0]}",
                                       f"{BASE}/templates/{MISSING}", method="PATCH", json={"name": "Renamed"})
    template = ev4.a.ids["character_sheet_templates"][0]
    if is_gm_of_a(ev4, actor):
        r = await actor.patch(f"{BASE}/templates/{template}", json={"name": "Adventurer"})
        assert_no_canary(actor, r)
        assert r.status_code == 200, r.text
        return
    # E0-Access.6: a visible template is not a Player's to write: like missing, unchanged.
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{template}", f"{BASE}/templates/{MISSING}",
                                       method="PATCH", json={"name": "Renamed"})
    assert await row_count(ev4, CharacterSheetTemplate, CharacterSheetTemplate.name == "Renamed",
                           CharacterSheetTemplate.id == template) == 0


@ev4_probe("DELETE", "/api/character-sheets/templates/{template_id}", actors=WITH_CO_GM)
async def probe_delete_template(ev4, actor):
    from app.db.models.character_sheet import CharacterSheetTemplate

    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{hidden.ids['character_sheet_templates'][0]}",
                                       f"{BASE}/templates/{MISSING}", method="DELETE")
    template = ev4.a.ids["character_sheet_templates"][0]
    if is_gm_of_a(ev4, actor):
        # A GM sees every sheet of the template, so the cascade is allowed.
        r = await actor.delete(f"{BASE}/templates/{template}")
        assert_no_canary(actor, r)
        assert r.status_code == 204, r.text
        assert await row_count(ev4, CharacterSheetTemplate, CharacterSheetTemplate.id == template) == 0
        return
    # E0-Access.6: a visible template is not a Player's to delete.
    await assert_hidden_equals_missing(actor, f"{BASE}/templates/{template}", f"{BASE}/templates/{MISSING}",
                                       method="DELETE")
    assert await row_count(ev4, CharacterSheetTemplate, CharacterSheetTemplate.id == template) == 1
