"""EV-4 probes for api/routes/campaigns.py: GET / and GET /{campaign_id}
(E0-Access.4), and every other Campaign route (E0-Access.5).

E0-Access.5 roles: management (PATCH / DELETE the Campaign, Share Links,
members) is Owner-only; export, analytics and tag-category writes need
`gm` (Owner or Co-GM); the tag-category list and leave need `player`. A
caller below the route's Role gets the one 404, byte-identical to a missing
Campaign, and nothing changes. None of the probe actors owns Campaign A.
"""
from __future__ import annotations

import sqlalchemy as sa

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import MISSING, add_category, authenticated, is_gm_of_a, outsider, row_count
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe

WITH_CO_GM = (*DEFAULT_ACTORS, "co_gm")
BASE = "/api/campaigns"


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


async def _campaign_route(ev4, actor, method: str, suffix: str = "", *, allowed: bool,
                          hidden_suffix: str | None = None, **kwargs):
    """Another Campaign answers like a missing one for everyone. In A, an
    `allowed` actor succeeds (no canary it may not see); anyone else gets
    the missing-Campaign answer. Returns A's response when allowed."""
    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}{hidden_suffix or suffix}",
                                       f"{BASE}/{MISSING}{suffix}", method=method, **kwargs)
    if not allowed:
        await assert_hidden_equals_missing(actor, f"{BASE}/{a}{suffix}", f"{BASE}/{MISSING}{suffix}", method=method,
                                           **kwargs)
        return None
    r = await actor.request(method, f"{BASE}/{a}{suffix}", **kwargs)
    assert r.status_code < 300, r.text
    assert_no_canary(actor, r)
    return r


# ── Owner-only management ──────────────────────────────────────────────────

@ev4_probe("PATCH", "/api/campaigns/{campaign_id}", actors=WITH_CO_GM)
async def probe_update_campaign(ev4, actor):
    from app.db.models.campaign import Campaign

    await _campaign_route(ev4, actor, "PATCH", allowed=False, json={"name": "Renamed"})
    assert await row_count(ev4, Campaign, Campaign.id == ev4.a.campaign_id, Campaign.name == "Renamed") == 0


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}", actors=WITH_CO_GM)
async def probe_delete_campaign(ev4, actor):
    from app.db.models.campaign import Campaign

    await _campaign_route(ev4, actor, "DELETE", allowed=False)
    assert await row_count(ev4, Campaign, Campaign.id == ev4.a.campaign_id) == 1


@ev4_probe("GET", "/api/campaigns/{campaign_id}/share", actors=WITH_CO_GM)
async def probe_list_share_tokens(ev4, actor):
    await _campaign_route(ev4, actor, "GET", "/share", allowed=False)


@ev4_probe("POST", "/api/campaigns/{campaign_id}/share", actors=WITH_CO_GM)
async def probe_create_share_token(ev4, actor):
    from app.db.models.share_token import CampaignShareToken

    a = ev4.a.campaign_id
    before = await row_count(ev4, CampaignShareToken, CampaignShareToken.campaign_id == a)
    await _campaign_route(ev4, actor, "POST", "/share", allowed=False, json={"kind": "read_only"})
    assert await row_count(ev4, CampaignShareToken, CampaignShareToken.campaign_id == a) == before


async def _token_id(ev4, campaign_id):
    from app.db.models.share_token import CampaignShareToken

    return (await ev4.db.execute(sa.select(CampaignShareToken.id).where(
        CampaignShareToken.campaign_id == campaign_id).limit(1))).scalar_one()


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/share/{token_id}", actors=WITH_CO_GM)
async def probe_revoke_share_token(ev4, actor):
    from app.db.models.share_token import CampaignShareToken

    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}/share/{await _token_id(ev4, hidden.campaign_id)}",
                                       f"{BASE}/{MISSING}/share/{MISSING}", method="DELETE")
    token = await _token_id(ev4, ev4.a.campaign_id)
    await assert_hidden_equals_missing(actor, f"{BASE}/{ev4.a.campaign_id}/share/{token}",
                                       f"{BASE}/{MISSING}/share/{MISSING}", method="DELETE")
    assert await row_count(ev4, CampaignShareToken, CampaignShareToken.id == token,
                           CampaignShareToken.revoked.is_(False)) == 1


@ev4_probe("GET", "/api/campaigns/{campaign_id}/members", actors=WITH_CO_GM)
async def probe_list_members(ev4, actor):
    await _campaign_route(ev4, actor, "GET", "/members", allowed=False)


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/members/{member_id}", actors=WITH_CO_GM)
async def probe_remove_member(ev4, actor):
    from app.db.models.campaign_member import CampaignMember

    victim = await ev4.make_member("player", label="victim")
    member = (await ev4.db.execute(sa.select(CampaignMember.id).where(
        CampaignMember.campaign_id == ev4.a.campaign_id, CampaignMember.user_id == victim.id))).scalar_one()
    await assert_hidden_equals_missing(actor, f"{BASE}/{ev4.a.campaign_id}/members/{member}",
                                       f"{BASE}/{MISSING}/members/{MISSING}", method="DELETE")
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}/members/{member}",
                                       f"{BASE}/{MISSING}/members/{MISSING}", method="DELETE")
    assert await row_count(ev4, CampaignMember, CampaignMember.id == member) == 1


# ── GM reads ───────────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/campaigns/{campaign_id}/export", actors=WITH_CO_GM)
async def probe_export_campaign(ev4, actor):
    await _campaign_route(ev4, actor, "GET", "/export?format=markdown", allowed=is_gm_of_a(ev4, actor))


@ev4_probe("GET", "/api/campaigns/{campaign_id}/analytics", actors=WITH_CO_GM)
async def probe_campaign_analytics(ev4, actor):
    await _campaign_route(ev4, actor, "GET", "/analytics", allowed=is_gm_of_a(ev4, actor))


# ── Tag categories ─────────────────────────────────────────────────────────

@ev4_probe("GET", "/api/campaigns/{campaign_id}/tag-categories", actors=WITH_CO_GM)
async def probe_list_tag_categories(ev4, actor):
    await add_category(ev4, visibility="gm")
    party = await add_category(ev4, visibility="party")
    r = await _campaign_route(ev4, actor, "GET", "/tag-categories", allowed=authenticated(actor))
    if r is None:
        return
    assert str(party) in {c["id"] for c in r.json()}, r.text
    if not is_gm_of_a(ev4, actor):
        await assert_counts_and_ranking_unchanged(actor, f"{BASE}/{ev4.a.campaign_id}/tag-categories",
                                                  lambda: add_category(ev4, visibility="gm"))


@ev4_probe("POST", "/api/campaigns/{campaign_id}/tag-categories", actors=WITH_CO_GM)
async def probe_create_tag_category(ev4, actor):
    from app.db.models.tag_category import TagCategory

    a = ev4.a.campaign_id
    before = await row_count(ev4, TagCategory, TagCategory.campaign_id == a)
    gm = is_gm_of_a(ev4, actor)
    await _campaign_route(ev4, actor, "POST", "/tag-categories", allowed=gm, json={"name": "Deities"})
    if not gm:
        assert await row_count(ev4, TagCategory, TagCategory.campaign_id == a) == before


@ev4_probe("DELETE", "/api/campaigns/{campaign_id}/tag-categories/{category_id}", actors=WITH_CO_GM)
async def probe_delete_tag_category(ev4, actor):
    from app.db.models.tag_category import TagCategory

    a = ev4.a.campaign_id
    hidden = await outsider(ev4)
    missing = f"{BASE}/{MISSING}/tag-categories/{MISSING}"
    gm_cat, party_cat = await add_category(ev4, visibility="gm"), await add_category(ev4, visibility="party")
    # Another Campaign's id under A, and A's id under another Campaign.
    await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}/tag-categories/{party_cat}", missing,
                                       method="DELETE")
    if is_gm_of_a(ev4, actor):
        r = await actor.delete(f"{BASE}/{a}/tag-categories/{party_cat}")
        assert r.status_code == 204, r.text
        return
    for cat in (gm_cat, party_cat):
        await assert_hidden_equals_missing(actor, f"{BASE}/{a}/tag-categories/{cat}", missing, method="DELETE")
        assert await row_count(ev4, TagCategory, TagCategory.id == cat) == 1


# ── Leave ──────────────────────────────────────────────────────────────────

@ev4_probe("POST", "/api/campaigns/{campaign_id}/leave", actors=WITH_CO_GM)
async def probe_leave_campaign(ev4, actor):
    hidden = await outsider(ev4)
    await assert_hidden_equals_missing(actor, f"{BASE}/{hidden.campaign_id}/leave", f"{BASE}/{MISSING}/leave",
                                       method="POST")
    if not authenticated(actor):
        return
    r = await actor.post(f"{BASE}/{ev4.a.campaign_id}/leave")
    assert r.status_code == 204, r.text
    # Gone: A now answers like a missing Campaign.
    await assert_hidden_equals_missing(actor, f"{BASE}/{ev4.a.campaign_id}", f"{BASE}/{MISSING}")
