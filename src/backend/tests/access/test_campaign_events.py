"""E0-Access.11: the Campaign events route and who receives which invalidation.

The spec's I/O matrix: the Audience filter (`deliverable`: GM, Player,
preview, hidden/visible/foreign ids, always-GM and unknown domains, broadcast
domains, junk, a failed check), the two publishers (`visibility` after a
set_visibility commit, `role` after a grant change commit; nothing on
rollback), and `GET /api/campaigns/{id}/events` end to end on an in-process
uvicorn (127.0.0.1, stopped in teardown): headers, `subscribed` first, the
filter per viewer, preview, the grant watch, no Valkey, the 404s and the
limiter. Plus the nginx location. Pub/sub runs on fakeredis and, with
VALKEY_TEST_URL (CI), a real Valkey.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date

import fakeredis
import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import MEMBER_VIEW, audience_ctx, change_member_role, ctx_for, set_visibility
from app.access import events as access_events
from app.access.events import BROADCAST_DOMAINS, EventCheckFailed, deliverable, register_event_domain
from app.core import pubsub, valkey_client
from app.core.limiter import limiter, user_or_ip
from app.db.models import Entity, JournalEntry
from app.db.models.campaign_member import CampaignMember
from app.db.session import get_db
from app.schemas.sources import RecordRef
from tests.ev4.fixtures import bearer, create_user, make_member
from tests.test_sse import Reader, serve  # noqa: F401  (the uvicorn fixture)

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")
NOT_FOUND = {"detail": "Not found"}
MISSING = "00000000-0000-4000-8000-000000000000"


# ── Fixtures and helpers ───────────────────────────────────────────────────

@pytest_asyncio.fixture(params=["fake", "real"])
async def valkey(request):
    if request.param == "fake":
        client = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    else:
        if not VALKEY_TEST_URL:
            pytest.skip("VALKEY_TEST_URL not set")
        client = aioredis.from_url(VALKEY_TEST_URL, decode_responses=True)
    previous = valkey_client.set_valkey(client)
    yield client
    valkey_client.set_valkey(previous)
    pubsub._TRAILING.clear()
    await client.aclose()


@pytest.fixture
def no_valkey():
    previous = valkey_client.set_valkey(None)
    yield
    valkey_client.set_valkey(previous)


@pytest.fixture
def published(monkeypatch):
    """Record every publish_campaign_event as (campaign_id, domain, id)."""
    calls: list[tuple] = []

    async def record(campaign_id, domain, id=None):  # noqa: A002
        calls.append((campaign_id, domain, id))

    monkeypatch.setattr(pubsub, "publish_campaign_event", record)
    return calls


class World:
    """A Campaign with an Owner, a Player, a co-GM and an outsider, and a
    hidden and a visible row of each keyed domain (committed)."""

    async def build(self, db: AsyncSession) -> "World":
        from app.db.models import Campaign, Genre

        self.db = db
        self.owner = await create_user(db, "events_owner")
        self.cid = uuid.uuid4()
        db.add(Campaign(id=self.cid, user_id=self.owner.id, name="Events", genre=Genre("fantasy")))
        await db.commit()
        self.player = await make_member(db, role="player", campaign_id=self.cid, label="events_player")
        self.co_gm = await make_member(db, role="gm", campaign_id=self.cid, label="events_cogm")
        self.outsider = await create_user(db, "events_outsider")
        self.hidden_entity = await self.entity("gm")
        self.party_entity = await self.entity("party")
        self.hidden_entry = await self.entry("gm")
        self.party_entry = await self.entry("party")
        other_owner = await create_user(db, "events_other")
        self.other_cid = uuid.uuid4()
        db.add(Campaign(id=self.other_cid, user_id=other_owner.id, name="Other", genre=Genre("fantasy")))
        await db.commit()
        self.foreign_entity = await self.entity("party", campaign_id=self.other_cid)
        return self

    async def entity(self, visibility: str, campaign_id: uuid.UUID | None = None) -> uuid.UUID:
        row = Entity(id=uuid.uuid4(), campaign_id=campaign_id or self.cid, type="character", kind="npc",
                     status="alive", name=f"E-{visibility}", visibility=visibility, field_visibility={},
                     created_by_user_id=self.owner.id)
        self.db.add(row)
        await self.db.commit()
        return row.id

    async def entry(self, visibility: str) -> uuid.UUID:
        row = JournalEntry(id=uuid.uuid4(), user_id=self.owner.id, campaign_id=self.cid, shorthand="sh",
                           narrative=f"N-{visibility}", entry_hash=uuid.uuid4().hex, session_date=date(2026, 3, 1),
                           kind="gm", visibility=visibility)
        self.db.add(row)
        await self.db.commit()
        return row.id

    async def ctx(self, user):
        return await ctx_for(self.db, user.id, self.cid)


@pytest_asyncio.fixture
async def world(db) -> World:
    return await World().build(db)


def inv(domain, id=None, **extra):  # noqa: A002
    return {"domain": domain, "id": None if id is None else str(id), **extra}


# ── The filter ─────────────────────────────────────────────────────────────

async def test_gm_receives_every_well_formed_invalidation(world):
    gm = await world.ctx(world.owner)
    co_gm = await world.ctx(world.co_gm)
    for ctx in (gm, co_gm):
        assert await deliverable(world.db, ctx, inv("entities", world.hidden_entity)) == inv(
            "entities", world.hidden_entity)
        assert await deliverable(world.db, ctx, inv("npcs", uuid.uuid4())) is not None
        assert await deliverable(world.db, ctx, inv("secret_thing", None)) == inv("secret_thing")


async def test_player_never_receives_a_hidden_id(world):
    player = await world.ctx(world.player)
    for domain, hidden in (("entities", world.hidden_entity), ("journal", world.hidden_entry)):
        assert await deliverable(world.db, player, inv(domain, hidden)) is None
    # Another Campaign's row (visible there) is not this Campaign's key.
    assert await deliverable(world.db, player, inv("entities", world.foreign_entity)) is None
    # A deleted / unknown id answers like a hidden one.
    assert await deliverable(world.db, player, inv("entities", uuid.uuid4())) is None


async def test_player_receives_a_visible_id(world):
    player = await world.ctx(world.player)
    assert await deliverable(world.db, player, inv("entities", world.party_entity)) == inv(
        "entities", world.party_entity)
    assert await deliverable(world.db, player, inv("journal", world.party_entry)) == inv(
        "journal", world.party_entry)


async def test_preview_filters_as_the_member_view(world):
    preview = audience_ctx(world.cid, MEMBER_VIEW, by=await world.ctx(world.owner))
    assert await deliverable(world.db, preview, inv("entities", world.hidden_entity)) is None
    assert await deliverable(world.db, preview, inv("entities", world.party_entity)) is not None
    assert await deliverable(world.db, preview, inv("npcs")) is None
    assert await deliverable(world.db, preview, inv("secret_thing")) is None


async def test_always_gm_and_unknown_domains_reach_no_player(world):
    player = await world.ctx(world.player)
    for data in (inv("npcs"), inv("npcs", uuid.uuid4()), inv("quests"), inv("secret_thing"),
                 inv("secret_thing", uuid.uuid4())):
        assert await deliverable(world.db, player, data) is None, data


async def test_unkeyed_events_of_a_readable_domain_reach_players(world):
    player = await world.ctx(world.player)
    for domain in ("entities", "journal", "relationships", "character_sheets", "session_plans", "sources"):
        assert await deliverable(None, player, inv(domain)) == inv(domain)


async def test_broadcast_domains_reach_everyone_without_an_id(world):
    assert BROADCAST_DOMAINS == {"visibility", "role"}
    for user in (world.owner, world.player):
        ctx = await world.ctx(user)
        for domain in BROADCAST_DOMAINS:
            assert await deliverable(None, ctx, inv(domain, world.hidden_entity)) == inv(domain)


async def test_junk_reaches_nobody_and_extra_keys_are_dropped(world):
    gm, player = await world.ctx(world.owner), await world.ctx(world.player)
    for junk in (None, "entities", [], {}, {"domain": ""}, {"domain": 7}, {"id": str(uuid.uuid4())},
                 {"domain": "entities", "id": 12}, {"domain": "entities", "id": "not-a-uuid"}):
        for ctx in (gm, player):
            assert await deliverable(world.db, ctx, junk) is None, (junk, ctx.role)
    leaky = inv("entities", world.party_entity, name="Secret", gm_notes="x")
    assert await deliverable(world.db, player, leaky) == inv("entities", world.party_entity)
    assert await deliverable(world.db, gm, leaky) == inv("entities", world.party_entity)


async def test_a_check_that_cannot_run_fails_loudly(world):
    player = await world.ctx(world.player)
    with pytest.raises(EventCheckFailed):
        await deliverable(None, player, inv("entities", world.party_entity))

    class Broken:
        async def execute(self, *a, **k):
            raise RuntimeError("db down")

    with pytest.raises(EventCheckFailed):
        await deliverable(Broken(), player, inv("entities", world.party_entity))


def test_register_event_domain_guards():
    assert {"entities", "relationships", "journal"} <= set(access_events.event_domains())
    assert register_event_domain("entities", Entity).model is Entity  # same model: a no-op
    with pytest.raises(ValueError):
        register_event_domain("entities", JournalEntry)
    with pytest.raises(ValueError):
        register_event_domain("visibility", Entity)
    with pytest.raises(ValueError):
        register_event_domain("", Entity)


# ── Publishers ─────────────────────────────────────────────────────────────

async def test_set_visibility_publishes_one_unkeyed_visibility_after_commit(world, published):
    gm = await world.ctx(world.owner)
    await set_visibility(world.db, gm, RecordRef(kind="journal", id=world.hidden_entry), "party")
    await set_visibility(world.db, gm, RecordRef(kind="journal", id=world.party_entry), "gm")
    assert published == []  # not before the commit
    await world.db.commit()
    assert published == [(world.cid, "visibility", None)]


async def test_set_visibility_rolled_back_publishes_nothing(world, published):
    gm = await world.ctx(world.owner)
    await set_visibility(world.db, gm, RecordRef(kind="journal", id=world.hidden_entry), "party")
    await world.db.rollback()
    assert published == []


async def _member_row(world, user) -> CampaignMember:
    return (await world.db.execute(sa.select(CampaignMember).where(
        CampaignMember.campaign_id == world.cid, CampaignMember.user_id == user.id))).scalar_one()


async def test_grant_change_publishes_one_unkeyed_role_after_commit(world, published, no_valkey):
    member = await _member_row(world, world.player)
    assert await change_member_role(world.db, member, "co_gm")
    co = await _member_row(world, world.co_gm)
    assert await change_member_role(world.db, co, "player")
    assert published == []
    await world.db.commit()
    assert published == [(world.cid, "role", None)]


async def test_grant_change_rolled_back_publishes_nothing(world, published, no_valkey):
    member = await _member_row(world, world.player)
    await change_member_role(world.db, member, "co_gm")
    await world.db.rollback()
    assert published == []


async def test_role_and_visibility_go_through_the_real_channel(world, valkey):
    """The unkeyed publishes land on campaign:{id}:events (the B2 contract)."""
    got = []
    listener = pubsub.listen_campaign_events(world.cid, announce=True)

    async def run():
        async for item in listener:
            got.append(item)

    task = asyncio.ensure_future(run())
    try:
        await _until(lambda: got)
        gm = await world.ctx(world.owner)
        await set_visibility(world.db, gm, RecordRef(kind="journal", id=world.hidden_entry), "party")
        await world.db.commit()
        member = await _member_row(world, world.player)
        await change_member_role(world.db, member, "co_gm")
        await world.db.commit()
        await _until(lambda: len(got) >= 3)
        assert got == [("subscribed", {}), ("invalidate", inv("visibility")), ("invalidate", inv("role"))]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _until(cond, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


# ── The route, end to end ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def base_url(serve, db):  # noqa: F811
    from app.main import app

    limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield await serve(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _raw(client, cid, data) -> None:
    await client.publish(pubsub.campaign_events_channel(cid), json.dumps({"event": "invalidate", "data": data}))


async def _numsub(client, channel) -> int:
    result = await client.pubsub_numsub(channel)
    return int(result[0][1]) if result else 0


async def _frames_until_marker(base_url, world, valkey, headers, *, extra=()) -> tuple[httpx.Response, list]:
    """Open the stream, publish every probe event then a visible marker,
    and return the frames up to (and including) the marker."""
    marker = inv("entities", world.party_entity)
    events = [inv("entities", world.hidden_entity), inv("journal", world.hidden_entry), inv("npcs"),
              inv("npcs", uuid.uuid4()), inv("secret_thing", uuid.uuid4()), inv("entities", "not-a-uuid"),
              inv("entities", world.foreign_entity), inv("visibility", world.hidden_entity), *extra]
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        async with http.stream("GET", f"/api/campaigns/{world.cid}/events", headers=headers) as resp:
            assert resp.status_code == 200, await resp.aread()
            reader = Reader(resp)
            first = await asyncio.wait_for(reader.frames.get(), 5)
            assert first == ("subscribed", {})
            for data in events:
                await _raw(valkey, world.cid, data)
            await valkey.publish(pubsub.campaign_events_channel(world.cid), "not json")
            await _raw(valkey, world.cid, marker)
            frames = []
            while True:
                frame = await asyncio.wait_for(reader.frames.get(), 5)
                if frame[0] == "ping":
                    continue
                frames.append(frame)
                if frame == ("invalidate", marker):
                    break
            reader.task.cancel()
            return resp, frames


async def test_player_stream_headers_subscribed_first_and_filtered(base_url, world, valkey):
    resp, frames = await _frames_until_marker(base_url, world, valkey, bearer(world.player))
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-accel-buffering"] == "no"
    assert resp.headers["cache-control"] == "no-cache"
    assert "Authorization" in resp.headers["vary"] and "X-Lorekeeper-Preview" in resp.headers["vary"]
    assert frames == [("invalidate", inv("visibility")), ("invalidate", inv("entities", world.party_entity))]
    text = json.dumps(frames)
    for hidden in (world.hidden_entity, world.hidden_entry, world.foreign_entity):
        assert str(hidden) not in text
    assert "npcs" not in text and "secret_thing" not in text


async def test_gm_stream_receives_every_well_formed_key(base_url, world, valkey):
    _resp, frames = await _frames_until_marker(base_url, world, valkey, bearer(world.owner))
    domains = [f[1]["domain"] for f in frames]
    assert ("invalidate", inv("entities", world.hidden_entity)) in frames
    assert ("invalidate", inv("journal", world.hidden_entry)) in frames
    assert {"npcs", "secret_thing", "visibility"} <= set(domains)
    assert ("invalidate", inv("visibility")) in frames  # broadcast: never an id
    assert "not-a-uuid" not in json.dumps(frames)


async def test_gm_in_preview_is_filtered_as_the_member_view(base_url, world, valkey):
    headers = {**bearer(world.co_gm), "X-Lorekeeper-Preview": "member"}
    _resp, frames = await _frames_until_marker(base_url, world, valkey, headers)
    assert frames == [("invalidate", inv("visibility")), ("invalidate", inv("entities", world.party_entity))]


async def test_preview_header_on_a_player_changes_nothing(base_url, world, valkey):
    headers = {**bearer(world.player), "X-Lorekeeper-Preview": "member"}
    _resp, frames = await _frames_until_marker(base_url, world, valkey, headers)
    assert frames == [("invalidate", inv("visibility")), ("invalidate", inv("entities", world.party_entity))]


async def test_demoted_mid_stream_gets_access_changed_then_the_end(base_url, world, valkey):
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        async with http.stream("GET", f"/api/campaigns/{world.cid}/events", headers=bearer(world.co_gm)) as resp:
            reader = Reader(resp)
            assert await asyncio.wait_for(reader.frames.get(), 5) == ("subscribed", {})
            async with AsyncSession(bind=world.db.bind, expire_on_commit=False) as own:
                member = (await own.execute(sa.select(CampaignMember).where(
                    CampaignMember.campaign_id == world.cid,
                    CampaignMember.user_id == world.co_gm.id))).scalar_one()
                await change_member_role(own, member, "player")
                await own.commit()
            seen = []
            while True:
                frame = await asyncio.wait_for(reader.frames.get(), 5)
                seen.append(frame)
                if frame[0] == "access_changed":
                    break
            assert seen[-1] == ("access_changed", NOT_FOUND)
            await asyncio.wait_for(reader.ended.wait(), 5)
    # Reconnecting now reads as the Player they became.
    _resp, frames = await _frames_until_marker(base_url, world, valkey, bearer(world.co_gm))
    assert ("invalidate", inv("entities", world.hidden_entity)) not in frames


async def test_no_valkey_ends_the_stream_without_subscribed(base_url, world, no_valkey):
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        resp = await http.get(f"/api/campaigns/{world.cid}/events", headers=bearer(world.player))
    assert resp.status_code == 200
    assert "event: subscribed" not in resp.text and "event: invalidate" not in resp.text


async def test_outsiders_get_the_one_404(client, world, no_valkey):
    missing = await client.get(f"/api/campaigns/{MISSING}/events", headers=bearer(world.outsider))
    hidden = await client.get(f"/api/campaigns/{world.cid}/events", headers=bearer(world.outsider))
    bad = await client.get("/api/campaigns/not-a-uuid/events", headers=bearer(world.outsider))
    for r in (missing, hidden, bad):
        assert r.status_code == 404 and r.json() == NOT_FOUND, r.text
    anon = await client.get(f"/api/campaigns/{world.cid}/events")
    anon_missing = await client.get(f"/api/campaigns/{MISSING}/events")
    assert anon.status_code == anon_missing.status_code and anon.json() == anon_missing.json()
    assert anon.status_code in (401, 403, 404)


def test_route_is_limited_per_user():
    import app.main  # noqa: F401

    lims = limiter._route_limits["app.api.routes.events.campaign_events"]
    assert all(lim.key_func is user_or_ip for lim in lims)
    assert [(lim.limit.amount, lim.limit.get_expiry()) for lim in lims] == [(30, 60)]


# ── nginx ──────────────────────────────────────────────────────────────────

def test_nginx_streams_the_route_unbuffered_for_an_hour():
    from tests.ev4.routes import resolve_route

    loc = resolve_route("/api/campaigns/{campaign_id}/events")
    assert loc is not None and loc.uri.startswith("^/api/campaigns/"), loc
    directives = {d.name: d.args for d in loc.directives}
    assert directives["proxy_buffering"] == ["off"]
    assert directives["proxy_read_timeout"] == ["1h"]
    assert directives["limit_req"][0] == "zone=api"
    assert directives["proxy_pass"] == ["http://backend"]
    assert "include" not in directives  # proxy_common.conf would duplicate proxy_read_timeout
    assert "proxy_ignore_headers" not in directives  # X-Accel-Buffering stays honoured
    # Other Campaign routes stay in the generic location.
    assert resolve_route("/api/campaigns/{campaign_id}/me").uri == "/api/"
    assert resolve_route("/api/campaigns/{campaign_id}/events/x").uri == "/api/"
