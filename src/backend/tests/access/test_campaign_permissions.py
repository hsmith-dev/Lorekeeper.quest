"""E0-Access.5: per-Campaign permission checks.

A user who is GM in one Campaign and Player in another gets each record by
their Role in the record's own Campaign; cross-Campaign lists honour the
preview header (narrow only); the routes moved off the deprecated helpers
check `owner` / `gm` / `player` through require_campaign, and every denial
is the one 404.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from starlette.requests import Request

from app.access import (
    GM, PLAYER, PREVIEW_HEADER, NotFound, role_ctx, role_map, role_map_for_request, scoped_select_multi,
)
from app.db.models import Campaign, JournalEntry, JournalTag, Tag, TagType
from app.db.models.session_plan import SessionPlan
from app.db.models.shorthand import ShorthandTerm
from tests.ev4.fixtures import ev4, mint_canary  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
RANDOM = "00000000-0000-4000-8000-000000000000"
PREVIEW = {PREVIEW_HEADER: "member"}


def _request(method: str = "GET", headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": method, "path": "/api/journals/", "headers": raw})


async def _entry(db, campaign_id, author, *, visibility="party", shorthand=None, narrative=None):
    e = JournalEntry(user_id=author, campaign_id=campaign_id, shorthand=shorthand or "s",
                     narrative=narrative or f"Plain {uuid.uuid4().hex}", entry_hash=uuid.uuid4().hex,
                     session_date=date(2026, 5, 1), visibility=visibility)
    db.add(e)
    await db.flush()
    return e


@pytest.fixture
async def cross(ev4, db):
    """cross_gm_player: Player in A, Owner (GM) of B. B has a party entry with
    a canary Shorthand (a searchable word) and a Shorthand-only tag, and a
    GM-only entry."""
    actor = await ev4.actor("cross_gm_player")
    b = ev4.b.campaign_id
    party_b = await _entry(db, b, actor.user_id, shorthand="zorblax the hidden word",
                           narrative="The party crossed the bridge.")
    gm_b = await _entry(db, b, actor.user_id, visibility="gm", narrative=mint_canary("XGMB", b).token)
    await db.execute(sa.update(JournalEntry).where(JournalEntry.id.in_([party_b.id, gm_b.id])).values(
        narrative_tsv=sa.func.to_tsvector("english", JournalEntry.shorthand + " " + JournalEntry.narrative),
        party_tsv=sa.func.to_tsvector("english", JournalEntry.narrative),
    ))
    tag = Tag(name=mint_canary("XTAGB", b).token, tag_type=TagType.character)
    db.add(tag)
    await db.flush()
    db.add(JournalTag(journal_id=party_b.id, tag_id=tag.id, source_field="shorthand"))
    await db.commit()
    return actor, party_b, gm_b, tag


# ── role_map_for_request / scoped_select_multi preview ─────────────────────

async def test_role_map_for_request_narrows_gm_campaigns_only_with_the_header(db, ev4, cross):
    actor, *_ = cross
    a, b = ev4.a.campaign_id, ev4.b.campaign_id
    plain = await role_map_for_request(_request(), db, actor.user_id)
    assert plain == {a: PLAYER, b: GM} and plain.preview is False
    assert role_ctx(plain, b).role == GM
    previewing = await role_map_for_request(_request(headers=PREVIEW), db, actor.user_id)
    assert previewing == plain and previewing.preview is True
    narrowed = role_ctx(previewing, b)
    assert narrowed.role == PLAYER and narrowed.user_id is None and narrowed.read_only
    # The Player Campaign is unchanged: preview only narrows, never widens.
    assert role_ctx(previewing, a) == role_ctx(plain, a)
    # Any other header value changes nothing.
    other = await role_map_for_request(_request(headers={PREVIEW_HEADER: "gm"}), db, actor.user_id)
    assert other.preview is False


async def test_role_map_for_request_ignores_the_header_without_a_gm_campaign(db, ev4):
    player = await ev4.actor("player")
    roles = await role_map_for_request(_request("POST", headers=PREVIEW), db, player.user_id)
    assert roles == {ev4.a.campaign_id: PLAYER} and roles.preview is False


async def test_role_map_for_request_refuses_a_write_in_preview(db, ev4, cross):
    actor, *_ = cross
    with pytest.raises(NotFound):
        await role_map_for_request(_request("POST", headers=PREVIEW), db, actor.user_id)


async def test_scoped_select_multi_in_preview_filters_gm_campaigns_as_members(db, ev4, cross):
    actor, party_b, gm_b, tag = cross
    plain = await role_map(db, actor.user_id)
    previewing = await role_map_for_request(_request(headers=PREVIEW), db, actor.user_id)

    async def entry_ids(roles):
        return {e.id for e in (await db.execute(scoped_select_multi(JournalEntry, roles))).scalars().all()}

    plain_rows, preview_rows = await entry_ids(plain), await entry_ids(previewing)
    assert {party_b.id, gm_b.id} <= plain_rows
    assert party_b.id in preview_rows and gm_b.id not in preview_rows
    assert preview_rows <= plain_rows
    links = (await db.execute(scoped_select_multi(JournalTag, previewing))).scalars().all()
    assert tag.id not in {link.tag_id for link in links}
    gm_links = (await db.execute(scoped_select_multi(JournalTag, plain))).scalars().all()
    assert tag.id in {link.tag_id for link in gm_links}


# ── Cross-Campaign lists over HTTP ─────────────────────────────────────────

async def test_journal_list_without_campaign_honours_preview(client, ev4, cross):
    actor, party_b, gm_b, _ = cross
    plain = (await client.get("/api/journals/?limit=100", headers=actor.headers)).json()["items"]
    by_id = {i["id"]: i for i in plain}
    assert str(gm_b.id) in by_id and "shorthand" in by_id[str(party_b.id)]
    r = await client.get("/api/journals/?limit=100", headers={**actor.headers, **PREVIEW})
    assert "X-Lorekeeper-Preview" in r.headers["vary"]
    previewed = r.json()
    by_id = {i["id"]: i for i in previewed["items"]}
    assert str(gm_b.id) not in by_id
    assert str(party_b.id) in by_id and "shorthand" not in by_id[str(party_b.id)]
    assert all("shorthand" not in i for i in previewed["items"])
    assert previewed["total"] == len(previewed["items"])


async def test_journal_search_without_campaign_honours_preview(client, cross):
    actor, party_b, *_ = cross
    url = "/api/journals/?search=zorblax"
    plain = (await client.get(url, headers=actor.headers)).json()
    assert [i["id"] for i in plain["items"]] == [str(party_b.id)]
    # Previewing, the Shorthand-only word matches nothing (party_tsv only).
    assert (await client.get(url, headers={**actor.headers, **PREVIEW})).json()["total"] == 0


async def test_tag_list_without_campaign_honours_preview(client, cross):
    actor, _, _, tag = cross
    plain = (await client.get("/api/tags/", headers=actor.headers)).json()
    assert str(tag.id) in {t["id"] for t in plain}
    previewed = (await client.get("/api/tags/", headers={**actor.headers, **PREVIEW})).json()
    assert str(tag.id) not in {t["id"] for t in previewed}


async def test_campaign_list_honours_preview(client, ev4, cross):
    actor, *_ = cross
    r = await client.get("/api/campaigns/", headers={**actor.headers, **PREVIEW})
    assert r.status_code == 200
    assert {c["id"] for c in r.json()} == {str(ev4.a.campaign_id), str(ev4.b.campaign_id)}


async def test_the_header_never_widens_a_player(client, ev4):
    player = await ev4.actor("player")
    for url in ("/api/journals/", "/api/tags/", f"/api/shorthand/?campaign_id={ev4.a.campaign_id}",
                f"/api/session-plans/?campaign_id={ev4.a.campaign_id}"):
        plain = await client.get(url, headers=player.headers)
        previewed = await client.get(url, headers={**player.headers, **PREVIEW})
        assert plain.status_code == previewed.status_code == 200, url
        assert plain.json() == previewed.json(), url


# ── Per-record Role: GM in B, Player in A ──────────────────────────────────

async def test_gm_in_one_campaign_is_a_player_in_the_other(client, db, ev4, cross):
    actor, party_b, *_ = cross
    a_entry = ev4.a.ids["journal_entries"][0]
    body = {"name": f"Bree {uuid.uuid4().hex[:6]}", "tag_type": "location"}
    # A: Player, so attach / delete are the one 404 (even on a visible entry).
    r = await client.post(f"/api/journals/{a_entry}/tags", json=body, headers=actor.headers)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    r = await client.delete(f"/api/journals/{a_entry}", headers=actor.headers)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == a_entry)) == 1
    # B: GM.
    r = await client.post(f"/api/journals/{party_b.id}/tags", json=body, headers=actor.headers)
    assert r.status_code == 201, r.text
    assert (await client.delete(f"/api/journals/{party_b.id}", headers=actor.headers)).status_code == 204


# ── Campaign routes: owner / gm / player ───────────────────────────────────

async def test_management_is_owner_only(client, db, ev4):
    a = ev4.a.campaign_id
    owner = (await ev4.actor("gm_owner")).headers
    for who in ("co_gm", "player"):
        h = (await ev4.actor(who)).headers
        for method, url, body in (("PATCH", f"/api/campaigns/{a}", {"name": "Hijacked"}),
                                  ("GET", f"/api/campaigns/{a}/share", None),
                                  ("POST", f"/api/campaigns/{a}/share", {"kind": "read_only"}),
                                  ("GET", f"/api/campaigns/{a}/members", None),
                                  ("DELETE", f"/api/campaigns/{a}", None)):
            r = await client.request(method, url, json=body, headers=h)
            assert r.status_code == 404 and r.json() == NOT_FOUND, (who, method, url)
    assert await db.scalar(sa.select(sa.func.count()).where(Campaign.id == a, Campaign.name == "Hijacked")) == 0
    r = await client.patch(f"/api/campaigns/{a}", json={"name": "Renamed"}, headers=owner)
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert (await client.get(f"/api/campaigns/{a}/members", headers=owner)).status_code == 200


async def test_export_and_analytics_need_gm(client, ev4):
    a = ev4.a.campaign_id
    for who, ok in (("gm_owner", True), ("co_gm", True), ("player", False)):
        h = (await ev4.actor(who)).headers
        for url in (f"/api/campaigns/{a}/export?format=markdown", f"/api/campaigns/{a}/analytics"):
            r = await client.get(url, headers=h)
            assert (r.status_code == 200) is ok, (who, url, r.status_code)
            if not ok:
                assert r.json() == NOT_FOUND
    # Preview narrows the GM below `gm`: the one 404.
    owner = {**(await ev4.actor("gm_owner")).headers, **PREVIEW}
    r = await client.get(f"/api/campaigns/{a}/analytics", headers=owner)
    assert r.status_code == 404 and r.json() == NOT_FOUND


async def test_analytics_counts_the_callers_own_entries(client, db, ev4):
    a = ev4.a.campaign_id
    owner = (await ev4.actor("gm_owner")).headers
    r = (await client.get(f"/api/campaigns/{a}/analytics", headers=owner)).json()
    assert r["total_entries"] == len(ev4.a.ids["journal_entries"])
    assert len(r["entries_per_week"]) >= 1


async def test_autocomplete_with_a_campaign_works_for_a_co_gm(client, ev4):
    from tests.ev4.probes.retrieval import use_fake_llm

    a = str(ev4.a.campaign_id)
    for who in ("co_gm", "player"):
        await use_fake_llm(ev4, await ev4.actor(who))
    co_gm = (await ev4.actor("co_gm")).headers
    r = await client.post("/api/journals/autocomplete", json={"text": "The party", "campaign_id": a}, headers=co_gm)
    assert r.status_code == 200, r.text
    player = (await ev4.actor("player")).headers
    r = await client.post("/api/journals/autocomplete", json={"text": "The party", "campaign_id": a}, headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    r = await client.post("/api/journals/autocomplete", json={"text": "The party"}, headers=player)
    assert r.status_code == 200, r.text


async def test_leave_campaign(client, db, ev4):
    a = ev4.a.campaign_id
    owner = (await ev4.actor("gm_owner")).headers
    r = await client.post(f"/api/campaigns/{a}/leave", headers=owner)
    assert r.status_code == 400
    player = await ev4.actor("player")
    assert (await client.post(f"/api/campaigns/{a}/leave", headers=player.headers)).status_code == 204
    r = await client.post(f"/api/campaigns/{a}/leave", headers=player.headers)
    assert r.status_code == 404 and r.json() == NOT_FOUND


async def test_tag_categories(client, db, ev4):
    a = ev4.a.campaign_id
    co_gm = (await ev4.actor("co_gm")).headers
    player = (await ev4.actor("player")).headers
    r = await client.post(f"/api/campaigns/{a}/tag-categories", json={"name": "Deities"}, headers=co_gm)
    assert r.status_code == 201, r.text
    cat = r.json()["id"]
    # Same name again: the existing category (case-insensitive).
    again = await client.post(f"/api/campaigns/{a}/tag-categories", json={"name": "deities"}, headers=co_gm)
    assert again.json()["id"] == cat
    r = await client.post(f"/api/campaigns/{a}/tag-categories", json={"name": "Mine"}, headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert cat in {c["id"] for c in (await client.get(f"/api/campaigns/{a}/tag-categories", headers=player)).json()}
    r = await client.delete(f"/api/campaigns/{a}/tag-categories/{cat}", headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert (await client.delete(f"/api/campaigns/{a}/tag-categories/{cat}", headers=co_gm)).status_code == 204


# ── Authoring routes ───────────────────────────────────────────────────────

async def test_shorthand_and_plans_are_gm_written_and_visibility_read(client, db, ev4):
    a = ev4.a.campaign_id
    co_gm = (await ev4.actor("co_gm")).headers
    player = (await ev4.actor("player")).headers
    r = await client.post("/api/shorthand/", json={"campaign_id": str(a), "term": "bbeg", "meaning": "big bad"},
                          headers=co_gm)
    assert r.status_code == 201, r.text
    term = r.json()["id"]
    r = await client.post("/api/session-plans/", json={"campaign_id": str(a), "title": "Next", "content": "x"},
                          headers=co_gm)
    assert r.status_code == 201, r.text
    plan = r.json()["id"]
    # New terms and plans are visibility gm: a Player lists neither.
    terms = (await client.get(f"/api/shorthand/?campaign_id={a}", headers=player)).json()
    plans = (await client.get(f"/api/session-plans/?campaign_id={a}", headers=player)).json()
    assert terms == [] and plans == []
    r = await client.get(f"/api/session-plans/{plan}", headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    # Made party-visible, a Player reads them but still cannot write them.
    await db.execute(sa.update(ShorthandTerm).where(ShorthandTerm.id == uuid.UUID(term)).values(visibility="party"))
    await db.execute(sa.update(SessionPlan).where(SessionPlan.id == uuid.UUID(plan)).values(visibility="party"))
    await db.commit()
    assert [t["id"] for t in (await client.get(f"/api/shorthand/?campaign_id={a}", headers=player)).json()] == [term]
    assert (await client.get(f"/api/session-plans/{plan}", headers=player)).status_code == 200
    for method, url, body in (("PUT", f"/api/shorthand/{term}", {"meaning": "x"}),
                              ("DELETE", f"/api/shorthand/{term}", None),
                              ("PUT", f"/api/session-plans/{plan}", {"content": "x"}),
                              ("DELETE", f"/api/session-plans/{plan}", None)):
        r = await client.request(method, url, json=body, headers=player)
        assert r.status_code == 404 and r.json() == NOT_FOUND, (method, url)
    assert (await client.put(f"/api/shorthand/{term}", json={"meaning": "edited"}, headers=co_gm)).json()["meaning"] \
        == "edited"
    assert (await client.delete(f"/api/session-plans/{plan}", headers=co_gm)).status_code == 204


async def test_single_campaign_reads_honour_preview(client, ev4):
    a = ev4.a.campaign_id
    owner = (await ev4.actor("gm_owner")).headers
    for url in (f"/api/shorthand/?campaign_id={a}", f"/api/session-plans/?campaign_id={a}",
                f"/api/sources/?campaign_id={a}"):
        assert (await client.get(url, headers=owner)).json() != [], url  # the seeded gm rows
        assert (await client.get(url, headers={**owner, **PREVIEW})).json() == [], url
    r = await client.post("/api/shorthand/", json={"campaign_id": str(a), "term": "t", "meaning": "m"},
                          headers={**owner, **PREVIEW})
    assert r.status_code == 404 and r.json() == NOT_FOUND


def test_accessible_campaign_ids_is_deleted():
    import app.api.deps as deps

    assert not hasattr(deps, "accessible_campaign_ids")


async def test_missing_campaign_is_the_one_404(client, ev4):
    owner = (await ev4.actor("gm_owner")).headers
    for method, url in (("GET", f"/api/campaigns/{RANDOM}/export"), ("PATCH", f"/api/campaigns/{RANDOM}"),
                        ("GET", f"/api/shorthand/?campaign_id={RANDOM}"), ("DELETE", f"/api/sources/{RANDOM}")):
        r = await client.request(method, url, json={} if method == "PATCH" else None, headers=owner)
        assert r.status_code == 404 and r.json() == NOT_FOUND, (method, url)
