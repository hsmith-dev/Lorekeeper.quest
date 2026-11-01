"""EV-4 probes for api/routes/tags.py (E0-Access.4): a tag found only in GM
content is absent, counts cover only visible links, and a hidden category
renders as unset."""
from __future__ import annotations

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, add_category, add_entry, add_tag, authenticated, link, outsider, previewing,
)
from tests.ev4.registry import ev4_probe


@ev4_probe("GET", "/api/tags/")
async def probe_list_tags(ev4, actor):
    a = ev4.a.campaign_id
    party = await add_entry(ev4, visibility="party", canary=False)
    visible_tag = await add_tag(ev4, party, source_field="manual", name="Bree")
    await add_tag(ev4, party, source_field="shorthand")             # Shorthand-only: absent
    await add_tag(ev4, await add_entry(ev4, visibility="gm"))       # only on a GM entry: absent
    await add_tag(ev4, party, source_field="narrative", name="Pelor",
                  category_id=await add_category(ev4, visibility="gm"))  # hidden category: null
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/tags/?campaign_id={hidden.campaign_id}",
                                       f"/api/tags/?campaign_id={MISSING}")
    if not authenticated(actor):
        return
    url = f"/api/tags/?campaign_id={a}"
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert_no_canary(actor, await actor.get("/api/tags/"))
    if "gm" in actor.grants.values():
        # E0-Access.5: previewing, a Shorthand-only tag of the actor's own GM
        # Campaign is absent from the cross-Campaign list.
        if ev4.b is not None:
            await add_tag(ev4, ev4.b.ids["journal_entries"][0], source_field="shorthand",
                          campaign_id=ev4.b.campaign_id)
        pv = previewing(actor)
        assert_no_canary(pv, await pv.get("/api/tags/"))
    assert sorted(t["name"].split()[0] for t in r.json()) == ["Bree", "Pelor"], r.text
    await assert_hidden_field_equals_unset(actor, url, "custom_category")

    async def gm_only_change():
        # A hidden link to a visible tag must not move its count.
        await link(ev4, await add_entry(ev4, visibility="gm"), visible_tag)
        await link(ev4, ev4.a.ids["journal_entries"][0], visible_tag, source_field="shorthand")

    await assert_counts_and_ranking_unchanged(actor, [url, "/api/tags/"], gm_only_change)
