"""EV-4 probes for api/routes/share.py (E0-Access.4). Any actor holding
Campaign A's read-only token reads as anon (the Public Audience); a revoked,
expired, unknown or wrong-kind token is the same 404."""
from __future__ import annotations

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_hidden_field_equals_unset,
    assert_no_canary,
)
from tests.ev4.probes._support import (
    MISSING, UNKNOWN_TOKEN, add_entry, add_share_token, add_tag, link, outsider,
)
from tests.ev4.registry import ev4_probe

ACTORS = ("anon_share", "anonymous", "player", "cross_gm_player")


async def _dead_tokens(ev4) -> list[str]:
    return [await add_share_token(ev4, revoked=True), await add_share_token(ev4, expired=True)]


@ev4_probe("GET", "/api/share/{token}", actors=ACTORS)
async def probe_shared_campaign(ev4, actor):
    token = ev4.a.share_token
    r = await actor.get(f"/api/share/{token}")
    assert r.status_code == 200, r.text
    assert_no_canary(actor, r)
    for dead in await _dead_tokens(ev4):
        await assert_hidden_equals_missing(actor, f"/api/share/{dead}", f"/api/share/{UNKNOWN_TOKEN}")


@ev4_probe("GET", "/api/share/{token}/journals", actors=ACTORS)
async def probe_shared_journals(ev4, actor):
    token = ev4.a.share_token
    url = f"/api/share/{token}/journals"
    party = await add_entry(ev4, visibility="party", canary=False)
    await add_tag(ev4, party, source_field="shorthand")
    await add_entry(ev4, visibility="party", kind="player", author=ev4.a.owner_id)  # Members, not Public
    await add_entry(ev4, visibility="gm")
    assert_no_canary(actor, await actor.get(url))
    await assert_hidden_field_equals_unset(actor, url, "items.shorthand")
    for dead in await _dead_tokens(ev4) + [await add_share_token(ev4, kind="collaborate")]:
        await assert_hidden_equals_missing(actor, f"/api/share/{dead}/journals",
                                           f"/api/share/{UNKNOWN_TOKEN}/journals")

    async def gm_only_change():
        await add_entry(ev4, visibility="gm")
        await add_entry(ev4, visibility="private")
        await add_entry(ev4, visibility="party", kind="player")
        await add_tag(ev4, party, source_field="shorthand")

    await assert_counts_and_ranking_unchanged(actor, url, gm_only_change)


@ev4_probe("GET", "/api/share/{token}/journals/{journal_id}", actors=ACTORS)
async def probe_shared_journal(ev4, actor):
    token = ev4.a.share_token
    missing = f"/api/share/{token}/journals/{MISSING}"
    hidden_campaign = await outsider(ev4)
    for entry in (await add_entry(ev4, visibility="gm"), await add_entry(ev4, visibility="private"),
                  await add_entry(ev4, visibility="party", kind="player"),
                  hidden_campaign.ids["journal_entries"][0]):
        await assert_hidden_equals_missing(actor, f"/api/share/{token}/journals/{entry}", missing)
    party = ev4.a.ids["journal_entries"][0]
    await link(ev4, party, await add_tag(ev4, await add_entry(ev4, visibility="gm")), source_field="shorthand")
    r = await actor.get(f"/api/share/{token}/journals/{party}")
    assert r.status_code == 200, r.text
    assert_no_canary(actor, r)
    await assert_hidden_field_equals_unset(actor, f"/api/share/{token}/journals/{party}", "shorthand")
    collaborate = await add_share_token(ev4, kind="collaborate")
    await assert_hidden_equals_missing(actor, f"/api/share/{collaborate}/journals/{party}",
                                       f"/api/share/{UNKNOWN_TOKEN}/journals/{party}")


@ev4_probe("GET", "/api/share/{token}/npcs", actors=ACTORS)
async def probe_shared_npcs(ev4, actor):
    r = await actor.get(f"/api/share/{ev4.a.share_token}/npcs")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    for dead in await _dead_tokens(ev4):
        await assert_hidden_equals_missing(actor, f"/api/share/{dead}/npcs", f"/api/share/{UNKNOWN_TOKEN}/npcs")


@ev4_probe("GET", "/api/share/{token}/quests", actors=ACTORS)
async def probe_shared_quests(ev4, actor):
    r = await actor.get(f"/api/share/{ev4.a.share_token}/quests")
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json() == [], r.text
    for dead in await _dead_tokens(ev4):
        await assert_hidden_equals_missing(actor, f"/api/share/{dead}/quests", f"/api/share/{UNKNOWN_TOKEN}/quests")


@ev4_probe("POST", "/api/share/{token}/join")
async def probe_join(ev4, actor):
    # A revoked or expired collaborate link, and a read-only one, join nothing.
    dead = [await add_share_token(ev4, kind="collaborate", revoked=True),
            await add_share_token(ev4, kind="collaborate", expired=True), ev4.a.share_token]
    for token in dead:
        await assert_hidden_equals_missing(actor, f"/api/share/{token}/join", f"/api/share/{UNKNOWN_TOKEN}/join",
                                           method="POST")
