"""EV-4 probes for api/routes/campaigns.py GET / and GET /{campaign_id}
(E0-Access.4). The rest of campaigns.py is E0-Access.5's."""
from __future__ import annotations

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, authenticated, outsider
from tests.ev4.registry import ev4_probe


@ev4_probe("GET", "/api/campaigns/")
async def probe_list_campaigns(ev4, actor):
    r = await actor.get("/api/campaigns/")
    assert_no_canary(actor, r)
    if not authenticated(actor):
        return
    ids = {c["id"] for c in r.json()}
    assert str(ev4.a.campaign_id) in ids, r.text
    # Another user's Campaign is not listed, and adding one changes nothing.
    await assert_counts_and_ranking_unchanged(actor, "/api/campaigns/", lambda: outsider(ev4))


@ev4_probe("GET", "/api/campaigns/{campaign_id}",
           actors=("anon_share", "anonymous", "player", "co_gm", "cross_gm_player"))
async def probe_get_campaign(ev4, actor):
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"/api/campaigns/{hidden.campaign_id}", f"/api/campaigns/{MISSING}")
    r = await actor.get(f"/api/campaigns/{ev4.a.campaign_id}")
    assert_no_canary(actor, r)
    if authenticated(actor):
        assert r.status_code == 200 and r.json()["is_owner"] is False, r.text
