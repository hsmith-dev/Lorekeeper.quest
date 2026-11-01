"""EV-4 probes for api/routes/journals.py (E0-Access.4): list, get, tag
attach/detach, delete and the generate write response. E0-Access.5: tag
attach / detach and delete need `gm` in the entry's Campaign (a Player gets
the missing-entry 404 even on a visible entry); a Co-GM may."""
from __future__ import annotations

import sqlalchemy as sa

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_category, add_entry, add_tag, assert_same_answer, authenticated, is_gm_of_a, link, outsider,
    previewing, row_count,
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
    if "gm" in actor.grants.values():
        # E0-Access.5: previewing, every GM Campaign (A for co_gm, B for
        # cross_gm_player) reads as the member view, across Campaigns too.
        pv = previewing(actor)
        assert_no_canary(pv, await pv.get("/api/journals/?limit=100"))
        assert_no_canary(pv, await pv.get(f"/api/journals/?campaign_id={a}"))
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


@ev4_probe("POST", "/api/journals/{journal_id}/tags", actors=ACTORS)
async def probe_attach_tag(ev4, actor):
    from app.db.models.tag import JournalTag

    body = {"name": "Bree", "tag_type": "location"}
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}/tags",
                                       f"/api/journals/{MISSING}/tags", method="POST", json=body)
    if not authenticated(actor):
        return
    party = await add_entry(ev4, visibility="party", canary=False)
    hidden_cat = await add_category(ev4, visibility="gm")
    if not is_gm_of_a(ev4, actor):
        # gm only: a hidden and a visible entry both answer like a missing one.
        for entry in (await add_entry(ev4, visibility="gm"), party):
            await assert_hidden_equals_missing(actor, f"/api/journals/{entry}/tags", f"/api/journals/{MISSING}/tags",
                                               method="POST", json=body)
        assert await row_count(ev4, JournalTag, JournalTag.journal_id == party) == 0
        return
    # A GM (Co-GM): a category of another Campaign is a missing one.
    other_cat = await add_category(ev4, visibility="party")
    from app.db.models.tag_category import TagCategory
    await ev4.db.execute(sa.update(TagCategory).where(TagCategory.id == other_cat)
                         .values(campaign_id=hidden.campaign_id))
    await ev4.db.commit()
    r_hidden = await actor.post(f"/api/journals/{party}/tags", json={"name": "Bree", "custom_category_id": str(other_cat)})
    r_missing = await actor.post(f"/api/journals/{party}/tags", json={"name": "Bree", "custom_category_id": MISSING})
    assert_same_answer(actor, r_hidden, r_missing, "tag category")
    r = await actor.post(f"/api/journals/{party}/tags", json={"name": "Bree", "custom_category_id": str(hidden_cat)})
    assert r.status_code == 201, r.text
    r = await actor.post(f"/api/journals/{party}/tags", json=body)
    assert r.status_code == 201, r.text
    assert_no_canary(actor, r)


@ev4_probe("DELETE", "/api/journals/{journal_id}/tags/{tag_id}", actors=ACTORS)
async def probe_detach_tag(ev4, actor):
    from app.db.models.tag import JournalTag

    entry = await add_entry(ev4, visibility="party", canary=False)
    shorthand_tag = await add_tag(ev4, entry, source_field="shorthand")
    manual_tag = await add_tag(ev4, entry, source_field="manual", name="Bree")
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}/tags/{MISSING}",
                                       f"/api/journals/{MISSING}/tags/{MISSING}", method="DELETE")
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"/api/journals/{entry}/tags/{shorthand_tag}")
        assert r.status_code == 204, r.text
        return
    # gm only: a Shorthand-only link and a visible manual one both answer
    # like a missing link, and nothing is deleted.
    for tag in (shorthand_tag, manual_tag):
        await assert_hidden_equals_missing(actor, f"/api/journals/{entry}/tags/{tag}",
                                           f"/api/journals/{entry}/tags/{MISSING}", method="DELETE")
        assert await row_count(ev4, JournalTag, JournalTag.journal_id == entry, JournalTag.tag_id == tag) == 1


@ev4_probe("DELETE", "/api/journals/{journal_id}", actors=ACTORS)
async def probe_delete_journal(ev4, actor):
    from app.db.models.journal import JournalEntry

    gm_entry = await add_entry(ev4, visibility="gm")
    party_by_gm = ev4.a.ids["journal_entries"][0]
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/journals/{hidden.ids['journal_entries'][0]}",
                                       f"/api/journals/{MISSING}", method="DELETE")
    if is_gm_of_a(ev4, actor):
        assert (await actor.delete(f"/api/journals/{gm_entry}")).status_code == 204
        assert await row_count(ev4, JournalEntry, JournalEntry.id == gm_entry) == 0
        return
    own = await add_entry(ev4, visibility="party", kind="player", author=actor.user_id, canary=False) \
        if authenticated(actor) else party_by_gm
    for target in (gm_entry, party_by_gm, own):
        # Hidden, visible, or the caller's own: gm only, the same 404.
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
