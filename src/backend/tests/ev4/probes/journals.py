"""EV-4 probes for api/routes/journals.py (E0-Access.4): list, get, tag
attach/detach, delete and the generate write response."""
from __future__ import annotations

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_category, add_entry, add_tag, assert_same_answer, authenticated, is_gm_of_a, link, outsider,
    row_count,
)
from tests.ev4.registry import ev4_probe

ACTORS = ("anon_share", "player", "cross_gm_player", "co_gm")


async def _party_entry_with_hidden_refs(ev4):
    """A Party entry in A (plain narrative, canary Shorthand) tagged with a
    Shorthand-only tag (canary name) and a manual tag whose category is GM
    (canary category name)."""
    entry = await add_entry(ev4, visibility="party", canary=False)
    await add_tag(ev4, entry, source_field="shorthand")
    hidden_cat = await add_category(ev4, visibility="gm")
    await add_tag(ev4, entry, source_field="manual", name="Pelor", category_id=hidden_cat)
    return entry


@ev4_probe("GET", "/api/journals/", actors=ACTORS)
async def probe_list_journals(ev4, actor):
    a = ev4.a.campaign_id
    entry = await _party_entry_with_hidden_refs(ev4)
    await add_entry(ev4, visibility="gm")
    await add_entry(ev4, visibility="private")
    hidden = await outsider(ev4)
    if not authenticated(actor):
        await assert_hidden_equals_missing(actor, f"/api/journals/?campaign_id={hidden.campaign_id}",
                                           f"/api/journals/?campaign_id={MISSING}")
        return
    assert_no_canary(actor, await actor.get(f"/api/journals/?campaign_id={a}"))
    assert_no_canary(actor, await actor.get("/api/journals/"))
    await assert_hidden_equals_missing(actor, f"/api/journals/?campaign_id={hidden.campaign_id}",
                                       f"/api/journals/?campaign_id={MISSING}")
    if is_gm_of_a(ev4, actor):
        return
    url = f"/api/journals/?campaign_id={a}"
    await assert_hidden_field_equals_unset(actor, url, "items.shorthand")
    shorthand_tag = await add_tag(ev4, await add_entry(ev4, visibility="party", canary=False),
                                  source_field="shorthand")
    await assert_hidden_equals_missing(actor, f"{url}&tag_id={shorthand_tag}", f"{url}&tag_id={MISSING}")
    # Across Campaigns too (no campaign_id: the role-map path).
    await assert_hidden_equals_missing(actor, f"/api/journals/?tag_id={shorthand_tag}",
                                       f"/api/journals/?tag_id={MISSING}")

    async def gm_only_change():
        await add_entry(ev4, visibility="gm")
        await add_entry(ev4, visibility="private")
        await link(ev4, ev4.a.ids["journal_entries"][0], shorthand_tag, source_field="shorthand")
        await add_tag(ev4, entry, source_field="shorthand")

    await assert_counts_and_ranking_unchanged(actor, [url, "/api/journals/"], gm_only_change)


@ev4_probe("GET", "/api/journals/{journal_id}", actors=ACTORS)
async def probe_get_journal(ev4, actor):
    entry = await _party_entry_with_hidden_refs(ev4)
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}",
                                       f"/api/journals/{MISSING}")
    if not authenticated(actor) or is_gm_of_a(ev4, actor):
        assert_no_canary(actor, await actor.get(f"/api/journals/{entry}"))
        return
    for vis in ("gm", "private"):
        await assert_hidden_equals_missing(actor, f"/api/journals/{await add_entry(ev4, visibility=vis)}",
                                           f"/api/journals/{MISSING}")
    r = await actor.get(f"/api/journals/{entry}")
    assert r.status_code == 200, r.text
    assert_no_canary(actor, r)
    await assert_hidden_field_equals_unset(actor, f"/api/journals/{entry}", "shorthand")
    # Reference removal: the Shorthand tag is gone, the hidden category is null.
    await assert_hidden_field_equals_unset(actor, f"/api/journals/{entry}", "tags.custom_category")
    assert [t["name"].split()[0] for t in r.json()["tags"]] == ["Pelor"]


@ev4_probe("POST", "/api/journals/{journal_id}/tags")
async def probe_attach_tag(ev4, actor):
    body = {"name": "Bree", "tag_type": "location"}
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}/tags",
                                       f"/api/journals/{MISSING}/tags", method="POST", json=body)
    if not authenticated(actor):
        return
    gm_entry = await add_entry(ev4, visibility="gm")
    await assert_hidden_equals_missing(actor, f"/api/journals/{gm_entry}/tags", f"/api/journals/{MISSING}/tags",
                                       method="POST", json=body)
    # A hidden category is a missing one.
    party = ev4.a.ids["journal_entries"][0]
    hidden_cat = await add_category(ev4, visibility="gm")
    r_hidden = await actor.post(f"/api/journals/{party}/tags", json={"name": "Bree", "custom_category_id": str(hidden_cat)})
    r_missing = await actor.post(f"/api/journals/{party}/tags", json={"name": "Bree", "custom_category_id": MISSING})
    assert_same_answer(actor, r_hidden, r_missing, "tag category")
    # The write response on a visible entry is projected.
    r = await actor.post(f"/api/journals/{party}/tags", json=body)
    assert r.status_code == 201, r.text
    assert_no_canary(actor, r)


@ev4_probe("DELETE", "/api/journals/{journal_id}/tags/{tag_id}")
async def probe_detach_tag(ev4, actor):
    entry = await add_entry(ev4, visibility="party", canary=False)
    shorthand_tag = await add_tag(ev4, entry, source_field="shorthand")
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}/tags/{MISSING}",
                                       f"/api/journals/{MISSING}/tags/{MISSING}", method="DELETE")
    # A Shorthand-only link is missing to a Player (and nothing is deleted).
    await assert_hidden_equals_missing(actor, f"/api/journals/{entry}/tags/{shorthand_tag}",
                                       f"/api/journals/{entry}/tags/{MISSING}", method="DELETE")
    from app.db.models.tag import JournalTag
    assert await row_count(ev4, JournalTag, JournalTag.journal_id == entry, JournalTag.tag_id == shorthand_tag) == 1


@ev4_probe("DELETE", "/api/journals/{journal_id}")
async def probe_delete_journal(ev4, actor):
    from app.db.models.journal import JournalEntry

    gm_entry = await add_entry(ev4, visibility="gm")
    party_by_gm = ev4.a.ids["journal_entries"][0]
    hidden = await outsider(ev4)
    for target in (gm_entry, party_by_gm, hidden.ids["journal_entries"][0]):
        # Hidden, or visible but not the caller's to delete: the same 404.
        await assert_hidden_equals_missing(actor, f"/api/journals/{target}", f"/api/journals/{MISSING}",
                                           method="DELETE")
        assert await row_count(ev4, JournalEntry, JournalEntry.id == target) == 1


@ev4_probe("POST", "/api/journals/generate")
async def probe_generate_journal(ev4, actor):
    hidden = await outsider(ev4)

    def body(campaign_id):
        return {"notes": "n", "campaign_id": str(campaign_id), "entry_hash": "h" * 64, "narrative": "A narrative."}

    r_hidden = await actor.post("/api/journals/generate", json=body(hidden.campaign_id))
    r_missing = await actor.post("/api/journals/generate", json=body(MISSING))
    assert_same_answer(actor, r_hidden, r_missing, "Campaign")
