"""EV-4 probes for api/routes/campaigns.py: GET / and GET /{campaign_id}
(E0-Access.4), and every other Campaign route (E0-Access.5).

E0-Access.5 roles: management (PATCH / DELETE the Campaign, Share Links,
members) is Owner-only; tag-category writes need `gm` (Owner or Co-GM);
export, analytics (E0-Access.13), the tag-category list and leave need
`player`. A caller below the route's Role gets the one 404, byte-identical
to a missing Campaign, and nothing changes. None of the probe actors owns
Campaign A.
"""
from __future__ import annotations

import io
import uuid

import sqlalchemy as sa

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary
from tests.ev4.probes._support import (
    MISSING, add_category, add_entry, add_tag, authenticated, is_gm_of_a, outsider, row_count,
)
from tests.ev4.registry import DEFAULT_ACTORS, ev4_probe
from tests.ev4.report import record_leak

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


# ── Export and analytics (E0-Access.13) ────────────────────────────────────
#
# Open to every Member of A, over every Member's entries scoped by Role. A
# non-GM's analytics and export must not move across two mutations: first
# another Player's Private entry plus a Shorthand-derived tag on a Party
# entry, then a GM-only entry with a canary tag. A GM's export and analytics
# do include the planted Private entry (and its Shorthand).

async def _plant_hidden(ev4, actor) -> uuid.UUID:
    """Another Player's Private entry and a Shorthand-derived tag on a seeded
    Party entry; returns the Private entry's id."""
    other = await ev4.actor("player_2" if actor.name != "player_2" else "player")
    private = await add_entry(ev4, visibility="private", kind="player", author=other.user_id)
    await add_tag(ev4, ev4.a.ids["journal_entries"][0], source_field="shorthand")
    return private


async def _add_gm_only_entry(ev4) -> None:
    entry = await add_entry(ev4, visibility="gm")
    await add_tag(ev4, entry, source_field="narrative")


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


async def _pdf_export_text(ev4, actor, label: str) -> str:
    """A's PDF export as extracted text (once per response), checked for canaries."""
    r = await actor.get(f"{BASE}/{ev4.a.campaign_id}/export?format=pdf")
    assert r.status_code == 200, r.text
    text = _pdf_text(r.content)
    assert_no_canary(actor, text, label=label)
    # A token wrapped across lines is still a leak.
    assert_no_canary(actor, text.replace("\n", ""), label=f"{label} (lines joined)")
    return text


@ev4_probe("GET", "/api/campaigns/{campaign_id}/export", actors=(*WITH_CO_GM, "anonymous"))
async def probe_export_campaign(ev4, actor):
    from app.db.models.journal import JournalEntry

    allowed = authenticated(actor)
    md = await _campaign_route(ev4, actor, "GET", "/export?format=markdown", allowed=allowed)
    if md is None:
        await _campaign_route(ev4, actor, "GET", "/export?format=pdf", allowed=False)
        return
    assert_no_canary(actor, md.content, label="markdown export")
    url = f"{BASE}/{ev4.a.campaign_id}/export?format=markdown"
    if is_gm_of_a(ev4, actor):
        # A GM's export covers every Member's entries, Private ones included,
        # with their Shorthand.
        private = await _plant_hidden(ev4, actor)
        narrative, shorthand = (await ev4.db.execute(sa.select(JournalEntry.narrative, JournalEntry.shorthand)
                                                     .where(JournalEntry.id == private))).one()
        md = await actor.get(url)
        assert md.status_code == 200, md.text
        assert narrative in md.text and f"*Notes: {shorthand}*" in md.text, md.text[:300]
        await _pdf_export_text(ev4, actor, "PDF export text")
        return
    assert "Notes:" not in md.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _plant_hidden(ev4, actor))
    before = await _pdf_export_text(ev4, actor, "PDF export text")
    assert "Notes:" not in before
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _add_gm_only_entry(ev4))
    after = await _pdf_export_text(ev4, actor, "PDF export text after a GM-only entry")
    if after != before:
        record_leak(f"EV-4 leak: a GM-only entry changed {actor.name}'s PDF export", [after[:300]])


@ev4_probe("GET", "/api/campaigns/{campaign_id}/analytics", actors=(*WITH_CO_GM, "anonymous"))
async def probe_campaign_analytics(ev4, actor):
    allowed = authenticated(actor)
    r = await _campaign_route(ev4, actor, "GET", "/analytics", allowed=allowed)
    if r is None:
        return
    url = f"{BASE}/{ev4.a.campaign_id}/analytics"
    if is_gm_of_a(ev4, actor):
        # A GM's totals count another Member's Private entry.
        before = r.json()["total_entries"]
        await _plant_hidden(ev4, actor)
        after = await actor.get(url)
        assert after.status_code == 200, after.text
        assert after.json()["total_entries"] == before + 1, after.json()
        return
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _plant_hidden(ev4, actor))
    await assert_counts_and_ranking_unchanged(actor, url, lambda: _add_gm_only_entry(ev4))


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
