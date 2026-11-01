"""E0-Access.10: grant changes bump `access_epoch`, publish `access:` after
commit and close open streams; cache keys depend on who is asking.

The I/O matrix of the spec: the mutators (role change, removal, revocation,
lazy expiry, Campaign delete) with their epoch bump and after-commit
publish, rollback and no-op cases; `grant_watch` (message, poll, immediate
poll, missing grant, Share Link, fail closed); the Chronicler stream closed
mid-stream on a demotion or a removal, with and without Valkey; a removed
Member's still-valid JWT; the cache key scheme and the racing write; the
Job worker; and the AST guards (only app/access/ builds `cache:` keys or
names `access:` channels).
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.access import (
    MEMBER_VIEW, audience_ctx, cache_key, cached_json, campaign_grants_removed,
    change_member_role, ctx_for, ctx_for_share, grant_channel, grant_watch, invalidate_campaign_cache,
    publish_grant_change, remove_member, resolve_share_token, revoke_share_token, share_ctx,
)
from app.access import cache as access_cache
from app.access import grants
from app.access.policy import NotFound
from app.core import valkey_client
from app.db.models import Campaign, Genre
from app.db.models.campaign_member import CampaignMember
from app.db.models.chat import ChatSession
from app.db.models.share_token import CampaignShareToken
from app.domain.enums import CampaignRole
from app.services import llm_provider
from tests.ev4.fixtures import bearer, create_user, make_member
from tests.test_party_retrieval import _fake_llm_for, fake_embed, fake_valkey  # noqa: F401  (autouse fakes)

BACKEND = Path(__file__).resolve().parents[2]
NOT_FOUND = {"detail": "Not found"}
MISSING = "00000000-0000-4000-8000-000000000000"
VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")


# ── Fixtures and helpers ───────────────────────────────────────────────────

@pytest.fixture
def no_valkey():
    previous = valkey_client.set_valkey(None)
    yield
    valkey_client.set_valkey(previous)


@pytest.fixture
async def valkey():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    previous = valkey_client.set_valkey(client)
    yield client
    valkey_client.set_valkey(previous)
    await client.aclose()


@pytest.fixture
def published(monkeypatch):
    """Record every after-commit publish as (campaign_id, grant_id)."""
    calls: list[tuple] = []

    async def record(campaign_id, grant_id):
        calls.append((campaign_id, grant_id))

    monkeypatch.setattr(grants, "publish_grant_change", record)
    return calls


@pytest.fixture
def fast_poll(monkeypatch):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 0.05)


async def _campaign(db) -> tuple[Campaign, object]:
    owner = await create_user(db, "grants_owner")
    c = Campaign(user_id=owner.id, name="Grants", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c, owner


async def _member_row(db, campaign_id, user_id) -> CampaignMember | None:
    return (await db.execute(
        sa.select(CampaignMember).where(CampaignMember.campaign_id == campaign_id, CampaignMember.user_id == user_id)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def _member(db, campaign: Campaign, role: str = "player"):
    user = await make_member(db, role=role, campaign_id=campaign.id)
    return user, await _member_row(db, campaign.id, user.id)


async def _token(db, campaign: Campaign, owner, *, kind="read_only", expires_at=None, updated_at=None):
    token = CampaignShareToken(campaign_id=campaign.id, created_by_user_id=owner.id,
                               token=secrets.token_urlsafe(24), kind=kind)
    db.add(token)
    await db.commit()
    if expires_at is not None or updated_at is not None:
        await db.execute(sa.update(CampaignShareToken).where(CampaignShareToken.id == token.id)
                         .values(expires_at=expires_at, updated_at=updated_at or sa.func.now()))
        await db.commit()
    await db.refresh(token)
    return token


async def _fresh(db, model, row_id):
    return await db.get(model, row_id, populate_existing=True)


async def _not_fired(task: asyncio.Task, seconds: float = 0.3) -> None:
    await asyncio.sleep(seconds)
    assert not task.done(), task.result() if not task.cancelled() else "cancelled"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── Mutators: epoch bump and after-commit publish ──────────────────────────

async def test_role_change_bumps_the_epoch_and_publishes_after_commit(db, published):
    c, _ = await _campaign(db)
    _, m = await _member(db, c, "co_gm")
    assert await change_member_role(db, m, CampaignRole.PLAYER) is True
    assert m.access_epoch == 1 and published == []  # not before the commit
    await db.commit()
    assert published == [(c.id, m.id)]
    row = await _fresh(db, CampaignMember, m.id)
    assert (row.role, row.access_epoch) == (CampaignRole.PLAYER, 1)


async def test_same_role_is_a_no_op(db, published):
    c, _ = await _campaign(db)
    _, m = await _member(db, c, "player")
    assert await change_member_role(db, m, "player") is False
    await db.commit()
    assert published == [] and (await _fresh(db, CampaignMember, m.id)).access_epoch == 0
    with pytest.raises(ValueError):
        await change_member_role(db, m, "owner")


async def test_rollback_discards_the_publish(db, published):
    c, _ = await _campaign(db)
    user, m = await _member(db, c, "co_gm")
    campaign_id, user_id = c.id, user.id
    await change_member_role(db, m, "player")
    await db.rollback()
    assert published == []
    m = await _member_row(db, campaign_id, user_id)
    assert (m.role, m.access_epoch) == (CampaignRole.CO_GM, 0)
    # A savepoint rolled back discards its change; the outer commit publishes nothing.
    async with db.begin_nested() as sp:
        await change_member_role(db, m, "player")
        await sp.rollback()
    await db.commit()
    assert published == []


async def test_remove_member_deletes_the_grant_and_publishes(db, published):
    c, _ = await _campaign(db)
    user, m = await _member(db, c, "player")
    grant_id = m.id
    await remove_member(db, m)
    await db.commit()
    assert published == [(c.id, grant_id)]
    assert await _member_row(db, c.id, user.id) is None


async def test_revoke_bumps_once_and_publishes(db, published):
    c, owner = await _campaign(db)
    t = await _token(db, c, owner)
    assert await revoke_share_token(db, t) is True
    await db.commit()
    assert published == [(c.id, t.id)]
    t = await _fresh(db, CampaignShareToken, t.id)
    assert t.revoked and t.access_epoch == 1
    assert await revoke_share_token(db, t) is False  # already revoked: nothing changes
    await db.commit()
    assert published == [(c.id, t.id)] and (await _fresh(db, CampaignShareToken, t.id)).access_epoch == 1


async def test_expired_token_is_bumped_once_lazily(db, published):
    c, owner = await _campaign(db)
    now = datetime.now(timezone.utc)
    t = await _token(db, c, owner, expires_at=now - timedelta(minutes=1), updated_at=now - timedelta(hours=1))
    for _ in range(3):
        with pytest.raises(NotFound):
            await resolve_share_token(db, t.token)
    assert published == [(c.id, t.id)]  # once
    t = await _fresh(db, CampaignShareToken, t.id)
    assert t.access_epoch == 1 and t.updated_at > t.expires_at and not t.revoked


async def test_live_unknown_and_revoked_tokens_are_never_bumped(db, published):
    c, owner = await _campaign(db)
    live = await _token(db, c, owner, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    assert (await resolve_share_token(db, live.token)).id == live.id
    revoked = await _token(db, c, owner, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                           updated_at=datetime.now(timezone.utc) - timedelta(hours=1))
    revoked.revoked = True
    await db.commit()
    await db.execute(sa.update(CampaignShareToken).where(CampaignShareToken.id == revoked.id)
                     .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=1)))
    await db.commit()
    for token in (revoked.token, "no-such-token"):
        with pytest.raises(NotFound):
            await resolve_share_token(db, token)
    assert published == []
    assert (await _fresh(db, CampaignShareToken, revoked.id)).access_epoch == 0


async def test_a_share_token_miss_never_commits_the_callers_session(db, published):
    c, owner = await _campaign(db)
    now = datetime.now(timezone.utc)
    expired = await _token(db, c, owner, expires_at=now - timedelta(minutes=1), updated_at=now - timedelta(hours=1))
    campaign_id, owner_id, expired_id, expired_token = c.id, owner.id, expired.id, expired.token
    for token in ("no-such-token", expired_token):
        pending_id = uuid.uuid4()
        db.add(Campaign(id=pending_id, user_id=owner_id, name="Pending", genre=Genre.fantasy))
        with pytest.raises(NotFound):
            await resolve_share_token(db, token)
        await db.rollback()  # the pending row was never committed by the miss
        assert await db.get(Campaign, pending_id) is None
    assert published == [(campaign_id, expired_id)]  # the bump still committed, in its own session


async def test_a_failing_expiry_bump_is_still_the_404(db, monkeypatch, caplog):
    async def boom(*a, **kw):
        raise ConnectionError("db down")

    monkeypatch.setattr(db, "execute", boom)
    assert await grants.bump_expired_share_token(db, "whatever") is False
    assert "share_expiry_bump_failed" in caplog.text


async def test_share_ctx_carries_the_token_id(db):
    c, owner = await _campaign(db)
    t = await _token(db, c, owner)
    ctx = await share_ctx(db, t.token)
    assert ctx.grant_id == t.id == ctx_for_share(t).grant_id and ctx.access_epoch == 0


async def test_campaign_delete_publishes_every_grant_and_the_owner(db, client, published):
    c, owner = await _campaign(db)
    _, m1 = await _member(db, c, "player")
    _, m2 = await _member(db, c, "co_gm")
    t = await _token(db, c, owner)
    r = await client.delete(f"/api/campaigns/{c.id}", headers=bearer(owner))
    assert r.status_code == 204, r.text
    assert sorted(published, key=str) == sorted([(c.id, m1.id), (c.id, m2.id), (c.id, t.id), (c.id, None)], key=str)


async def test_campaign_grants_removed_rolls_back_with_the_delete(db, published):
    c, _ = await _campaign(db)
    await _member(db, c, "player")
    await campaign_grants_removed(db, c.id)
    await db.rollback()
    assert published == []


async def test_publish_goes_to_the_grant_channel(db, valkey):
    c, _ = await _campaign(db)
    _, m = await _member(db, c, "co_gm")
    pubsub = valkey.pubsub()
    await pubsub.subscribe(grant_channel(c.id, m.id), grant_channel(c.id, None))
    await change_member_role(db, m, "player")
    await db.commit()
    got = []
    for _ in range(20):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg:
            got.append(msg["channel"])
            break
    assert got == [f"access:{c.id}:{m.id}"]
    assert grant_channel(c.id, None) == f"access:{c.id}:owner"
    await pubsub.aclose()


async def test_publish_without_valkey_or_with_a_failing_one_never_raises(no_valkey, caplog, monkeypatch):
    await publish_grant_change(uuid.uuid4(), uuid.uuid4())  # no client: a no-op

    class Hung:
        async def publish(self, *a):
            await asyncio.sleep(30)

    monkeypatch.setattr(grants, "PUBLISH_TIMEOUT_S", 0.05)
    valkey_client.set_valkey(Hung())
    await asyncio.wait_for(publish_grant_change(uuid.uuid4(), uuid.uuid4()), 2)  # times out, logged
    assert "grant_publish_failed" in caplog.text
    caplog.clear()

    class Down:
        async def publish(self, *a):
            raise ConnectionError("down")

    valkey_client.set_valkey(Down())
    await publish_grant_change(uuid.uuid4(), uuid.uuid4())
    assert "grant_publish_failed" in caplog.text


# ── grant_watch ────────────────────────────────────────────────────────────

async def test_watch_fires_on_the_access_message(db, valkey, monkeypatch):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)  # only the message can fire it in time
    c, _ = await _campaign(db)
    user, m = await _member(db, c, "player")
    ctx = await ctx_for(db, user.id, c.id)
    task = asyncio.ensure_future(grant_watch(ctx, bind=db.bind))
    await asyncio.sleep(0.2)  # subscribed, first poll done
    assert not task.done()
    await valkey.publish(grant_channel(c.id, uuid.uuid4()), "changed")  # another grant: ignored
    await asyncio.sleep(0.1)
    assert not task.done()
    await publish_grant_change(c.id, m.id)
    assert await asyncio.wait_for(task, 2) == "message"


async def test_watch_polls_without_valkey(db, no_valkey, fast_poll):
    c, _ = await _campaign(db)
    user, m = await _member(db, c, "co_gm")
    ctx = await ctx_for(db, user.id, c.id)
    task = asyncio.ensure_future(grant_watch(ctx, bind=db.bind))
    await asyncio.sleep(0.15)
    assert not task.done()
    await change_member_role(db, m, "player")
    await db.commit()
    assert await asyncio.wait_for(task, 2) == "changed"


async def test_watch_polls_immediately(db, no_valkey, monkeypatch):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)
    c, _ = await _campaign(db)
    user, m = await _member(db, c, "player")
    stale = await ctx_for(db, user.id, c.id)
    m.access_epoch = 5
    await db.commit()
    assert await asyncio.wait_for(grant_watch(stale, bind=db.bind), 2) == "changed"


async def test_watch_treats_a_missing_grant_as_changed(db, no_valkey, fast_poll):
    c, owner = await _campaign(db)
    user, m = await _member(db, c, "player")
    ctx = await ctx_for(db, user.id, c.id)
    owner_ctx = await ctx_for(db, owner.id, c.id)
    task = asyncio.ensure_future(grant_watch(ctx, bind=db.bind))
    await asyncio.sleep(0.1)
    await remove_member(db, m)
    await db.commit()
    assert await asyncio.wait_for(task, 2) == "changed"
    # The Owner's ctx changes only when the Campaign goes.
    owner_task = asyncio.ensure_future(grant_watch(owner_ctx, bind=db.bind))
    await _not_fired(owner_task, 0.2)


async def test_watch_unchanged_never_fires(db, no_valkey, fast_poll):
    c, owner = await _campaign(db)
    user, _ = await _member(db, c, "player")
    t = await _token(db, c, owner)
    ctxs = [await ctx_for(db, user.id, c.id), await ctx_for(db, owner.id, c.id), await share_ctx(db, t.token)]
    await _not_fired(asyncio.ensure_future(grant_watch(*ctxs, bind=db.bind)))


@pytest.mark.parametrize("change", ["revoke", "expire", "epoch", "delete"])
async def test_watch_share_link(db, no_valkey, fast_poll, change):
    c, owner = await _campaign(db)
    t = await _token(db, c, owner)
    ctx = await share_ctx(db, t.token)
    task = asyncio.ensure_future(grant_watch(ctx, bind=db.bind))
    await asyncio.sleep(0.1)
    assert not task.done()
    if change == "revoke":
        await revoke_share_token(db, t)
    elif change == "expire":
        t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "epoch":
        t.access_epoch = 3
    else:
        await db.delete(t)
    await db.commit()
    assert await asyncio.wait_for(task, 2) == "changed"


async def test_watch_fails_closed_when_the_poll_cannot_run(db, no_valkey):
    c, _ = await _campaign(db)
    user, _ = await _member(db, c, "player")
    ctx = await ctx_for(db, user.id, c.id)
    dead = create_async_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/nowhere_test")
    try:
        assert await asyncio.wait_for(grant_watch(ctx, bind=dead), 10) == "poll_failed"
    finally:
        await dead.dispose()


async def test_watch_rejects_what_it_cannot_follow(db):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    with pytest.raises(ValueError):
        await grant_watch()
    with pytest.raises(ValueError):
        await grant_watch(audience_ctx(c.id, MEMBER_VIEW, by=gm))  # reduced: no grant of its own
    with pytest.raises(ValueError):
        await grant_watch(gm.as_system("merge"))


# ── The Chronicler stream ──────────────────────────────────────────────────

def _scripted_stream(monkeypatch, during):
    """stream_messages yields one delta, runs `during()` (the grant change,
    committed in its own session), then would yield "AFTER" ten seconds
    later. Records whether the generator was closed."""
    state = {"closed": False, "after": False}

    async def fake(messages, config=None, **kwargs):
        try:
            yield "Before the change. "
            await during()
            await asyncio.sleep(10)
            state["after"] = True
            yield "AFTER"
        finally:
            state["closed"] = True

    monkeypatch.setattr(llm_provider, "stream_messages", fake)
    return state


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


async def _change_in_own_session(db, fn):
    async with AsyncSession(bind=db.bind, expire_on_commit=False) as s:
        await fn(s)
        await s.commit()


def _chat_body(campaign_id, **extra) -> dict:
    body = {"message": "Tell me about the lich.", **extra}
    if campaign_id:
        body["campaign_id"] = str(campaign_id)
    return body


async def _stream_closed(db, client, monkeypatch, user, campaign_id, during, **extra):
    state = _scripted_stream(monkeypatch, during)
    body = _chat_body(campaign_id, **extra)
    r = await asyncio.wait_for(client.post("/api/chat/stream", headers=bearer(user), json=body), 8)
    assert r.status_code == 200, r.text
    events = _events(r.text)
    assert [e for e, _ in events] == ["meta", "delta", "error"], events
    assert events[1][1] == {"text": "Before the change. "}
    assert events[2][1] == NOT_FOUND and "AFTER" not in r.text
    assert state["closed"] and not state["after"]  # the upstream generator was closed
    session = await db.get(ChatSession, uuid.UUID(events[0][1]["session_id"]), populate_existing=True)
    assert session is None or (session.messages == [] and session.message_count == 0)  # nothing persisted
    return events


@pytest.fixture(params=["valkey", "poll"])
async def transport(request, monkeypatch):
    """valkey: only the access: message can close the stream in time (30 s
    poll). poll: no Valkey client, a 50 ms poll."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True) if request.param == "valkey" else None
    previous = valkey_client.set_valkey(client)
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30 if client is not None else 0.05)
    yield request.param
    valkey_client.set_valkey(previous)
    if client is not None:
        await client.aclose()


async def test_demotion_mid_stream_closes_the_co_gm_stream(db, client, monkeypatch, transport):
    c, owner = await _campaign(db)
    co_gm, m = await _member(db, c, "co_gm")
    await _fake_llm_for(db, co_gm)

    async def demote():
        async def fn(s):
            await change_member_role(s, await s.get(CampaignMember, m.id), "player")
        await _change_in_own_session(db, fn)

    await _stream_closed(db, client, monkeypatch, co_gm, c.id, demote)
    # The next request answers per the new grant.
    r = await client.get(f"/api/campaigns/{c.id}/me", headers=bearer(co_gm))
    assert r.status_code == 200 and r.json()["role"] == "player"
    r = await client.get(f"/api/campaigns/{c.id}/analytics", headers=bearer(co_gm))  # gm-only
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


async def test_removal_mid_stream_closes_the_player_stream(db, client, monkeypatch, valkey):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)
    c, _ = await _campaign(db)
    player, m = await _member(db, c, "player")
    await _fake_llm_for(db, player)

    async def remove():
        async def fn(s):
            await remove_member(s, await s.get(CampaignMember, m.id))
        await _change_in_own_session(db, fn)

    await _stream_closed(db, client, monkeypatch, player, c.id, remove)
    missing = await client.get(f"/api/campaigns/{MISSING}", headers=bearer(player))
    for url in (f"/api/campaigns/{c.id}", f"/api/campaigns/{c.id}/me", f"/api/campaigns/{c.id}/tag-categories"):
        r = await client.get(url, headers=bearer(player))
        assert (r.status_code, r.json()) == (404, NOT_FOUND) == (missing.status_code, missing.json())


async def test_campaignless_stream_watches_the_co_gm_grants(db, client, monkeypatch, no_valkey):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 0.05)
    c, _ = await _campaign(db)
    co_gm, m = await _member(db, c, "co_gm")
    await _fake_llm_for(db, co_gm)

    async def demote():
        async def fn(s):
            await change_member_role(s, await s.get(CampaignMember, m.id), "player")
        await _change_in_own_session(db, fn)

    await _stream_closed(db, client, monkeypatch, co_gm, None, demote)


async def test_campaign_delete_mid_stream_closes_the_stream(db, client, monkeypatch, valkey):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)  # the owner channel's message closes it
    c, owner = await _campaign(db)
    await _fake_llm_for(db, owner)
    # A committed session: the request inserts nothing that would lock the Campaign row.
    existing = ChatSession(user_id=owner.id, campaign_id=c.id, title="Lich", messages=[], message_count=0)
    db.add(existing)
    await db.commit()

    async def delete_campaign():
        async def fn(s):
            await campaign_grants_removed(s, c.id)
            await s.delete(await s.get(Campaign, c.id))
        await _change_in_own_session(db, fn)

    await _stream_closed(db, client, monkeypatch, owner, c.id, delete_campaign, session_id=str(existing.id))


async def _demote_or_remove(db, member_id, change: str) -> None:
    async def fn(s):
        member = await s.get(CampaignMember, member_id)
        if change == "demote":
            await change_member_role(s, member, "player")
        else:
            await remove_member(s, member)
    await _change_in_own_session(db, fn)


def _no_llm_call(monkeypatch) -> list:
    calls = []

    async def fake(messages, config=None, **kwargs):
        calls.append(1)
        yield "MUST-NOT-STREAM"

    monkeypatch.setattr(llm_provider, "stream_messages", fake)
    return calls


@pytest.mark.parametrize("change", ["demote", "remove"])
async def test_grant_change_before_the_stream_starts_sends_only_the_error(db, client, monkeypatch, no_valkey,
                                                                           change):
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)  # only the start-of-stream check can catch it
    c, _ = await _campaign(db)
    co_gm, m = await _member(db, c, "co_gm")
    await _fake_llm_for(db, co_gm)
    calls = _no_llm_call(monkeypatch)
    real_reserve = llm_provider.reserve_slot

    async def reserve_after_change(cfg, *a, **kw):  # after _prepare_chat and the ctx it built
        await _demote_or_remove(db, m.id, change)
        return await real_reserve(cfg, *a, **kw)

    monkeypatch.setattr(llm_provider, "reserve_slot", reserve_after_change)
    r = await client.post("/api/chat/stream", headers=bearer(co_gm), json=_chat_body(c.id))
    assert r.status_code == 200, r.text
    assert _events(r.text) == [("error", NOT_FOUND)] and calls == []


@pytest.mark.parametrize("change", ["demote", "remove"])
async def test_campaignless_grant_lost_after_prep_sends_only_the_error(db, client, monkeypatch, no_valkey, change):
    from app.api.routes import chat as chat_routes

    c, _ = await _campaign(db)
    co_gm, m = await _member(db, c, "co_gm")
    await _fake_llm_for(db, co_gm)
    calls = _no_llm_call(monkeypatch)
    real_prepare = chat_routes._prepare_chat

    async def prepare_then_change(*args, **kwargs):  # the role map said gm; the grant is gone or demoted now
        prep = await real_prepare(*args, **kwargs)
        await _demote_or_remove(db, m.id, change)
        return prep

    monkeypatch.setattr(chat_routes, "_prepare_chat", prepare_then_change)
    r = await client.post("/api/chat/stream", headers=bearer(co_gm), json=_chat_body(None))
    assert r.status_code == 200, r.text
    assert _events(r.text) == [("error", NOT_FOUND)] and calls == []


async def test_unchanged_stream_completes_and_persists(db, client, monkeypatch, valkey):
    from app.api.routes import chat as chat_routes

    c, _ = await _campaign(db)
    player, _ = await _member(db, c, "player")
    await _fake_llm_for(db, player)
    watch_state = {"started": False, "cancelled": False}
    real_watch = chat_routes.grant_watch

    async def recording_watch(*ctxs, **kwargs):
        watch_state["started"] = True
        try:
            return await real_watch(*ctxs, **kwargs)
        except asyncio.CancelledError:
            watch_state["cancelled"] = True
            raise

    monkeypatch.setattr(chat_routes, "grant_watch", recording_watch)

    async def fake(messages, config=None, **kwargs):
        for part in ("One ", "two."):
            await asyncio.sleep(0.05)
            yield part

    monkeypatch.setattr(llm_provider, "stream_messages", fake)
    r = await client.post("/api/chat/stream", headers=bearer(player),
                          json={"message": "Hello", "campaign_id": str(c.id)})
    events = _events(r.text)
    assert [e for e, _ in events] == ["meta", "delta", "delta", "done"] and events[-1][1] == {"reply": "One two."}
    assert watch_state == {"started": True, "cancelled": True}  # the watch ends with the stream


async def test_a_failing_watch_closes_the_stream_and_is_logged(db, client, monkeypatch, no_valkey, caplog):
    from app.api.routes import chat as chat_routes

    c, _ = await _campaign(db)
    player, _ = await _member(db, c, "player")
    await _fake_llm_for(db, player)

    async def broken_watch(*ctxs, **kwargs):
        raise RuntimeError("watch broke")

    async def fake(messages, config=None, **kwargs):
        yield "first "
        await asyncio.sleep(10)
        yield "AFTER"

    monkeypatch.setattr(chat_routes, "grant_watch", broken_watch)
    monkeypatch.setattr(llm_provider, "stream_messages", fake)
    r = await asyncio.wait_for(client.post("/api/chat/stream", headers=bearer(player), json=_chat_body(c.id)), 8)
    assert [e for e, _ in _events(r.text)][-1] == "error" and "AFTER" not in r.text
    assert "grant_watch_failed" in caplog.text


# ── Routes: removed JWT, revocation ────────────────────────────────────────

async def test_removed_member_with_a_valid_jwt_gets_404_everywhere(db, client, published):
    c, owner = await _campaign(db)
    player, m = await _member(db, c, "player")
    r = await client.get(f"/api/campaigns/{c.id}", headers=bearer(player))
    assert r.status_code == 200, r.text
    r = await client.delete(f"/api/campaigns/{c.id}/members/{m.id}", headers=bearer(owner))
    assert r.status_code == 204, r.text
    assert published == [(c.id, m.id)]
    for path in ("", "/me", "/tag-categories"):
        hidden = await client.get(f"/api/campaigns/{c.id}{path}", headers=bearer(player))
        missing = await client.get(f"/api/campaigns/{MISSING}{path}", headers=bearer(player))
        assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json()) == (404, NOT_FOUND)
    r = await client.post(f"/api/campaigns/{c.id}/leave", headers=bearer(player))
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


async def test_leave_removes_the_grant_and_publishes(db, client, published):
    c, _ = await _campaign(db)
    player, m = await _member(db, c, "player")
    r = await client.post(f"/api/campaigns/{c.id}/leave", headers=bearer(player))
    assert r.status_code == 204, r.text
    assert published == [(c.id, m.id)]


async def test_revoke_route_bumps_publishes_and_kills_the_share_urls(db, client, published):
    c, owner = await _campaign(db)
    t = await _token(db, c, owner)
    r = await client.get(f"/api/share/{t.token}")
    assert r.status_code == 200, r.text
    r = await client.delete(f"/api/campaigns/{c.id}/share/{t.id}", headers=bearer(owner))
    assert r.status_code == 204, r.text
    assert published == [(c.id, t.id)]
    t = await _fresh(db, CampaignShareToken, t.id)
    assert t.revoked and t.access_epoch == 1
    for suffix in ("", "/journals"):
        dead = await client.get(f"/api/share/{t.token}{suffix}")
        unknown = await client.get(f"/api/share/no-such-token{suffix}")
        assert (dead.status_code, dead.json()) == (unknown.status_code, unknown.json()) == (404, NOT_FOUND)


# ── Cache keys ─────────────────────────────────────────────────────────────

async def test_cache_keys_depend_on_audience_and_epoch(db):
    c, owner = await _campaign(db)
    player, m = await _member(db, c, "player")
    gm = await ctx_for(db, owner.id, c.id)
    p = await ctx_for(db, player.id, c.id)
    member_view = audience_ctx(c.id, MEMBER_VIEW, by=gm)
    m.access_epoch = 1
    await db.commit()
    p_bumped = await ctx_for(db, player.id, c.id)
    keys = [cache_key(x, 7, "journals", "list") for x in (gm, p, member_view, p_bumped)]
    assert len(set(keys)) == 4
    assert all(k.startswith(f"cache:{c.id}:7:") for k in keys)
    assert keys[0] == f"cache:{c.id}:7:gm:0:journals:list"
    assert keys[1] == f"cache:{c.id}:7:owner.{player.id}:0:journals:list"
    assert keys[2] == f"cache:{c.id}:7:members:0:journals:list"
    assert keys[3] == f"cache:{c.id}:7:owner.{player.id}:1:journals:list"


async def test_cache_key_parts_are_escaped_so_they_never_collide(db):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    assert cache_key(gm, 1, "d", "a:b") != cache_key(gm, 1, "d", "a", "b")
    assert cache_key(gm, 1, "d:a", "b") != cache_key(gm, 1, "d", "a", "b")
    assert cache_key(gm, 1, "d", "a%3Ab") != cache_key(gm, 1, "d", "a:b")
    assert cache_key(gm, 1, "d", "a:b").endswith(":d:a%3Ab")


async def test_a_corrupt_cached_value_is_recomputed(db, valkey, caplog):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    gen = await access_cache.cache_generation(valkey, c.id)
    await valkey.set(cache_key(gm, gen, "x"), "{not json")
    assert await cached_json(gm, "x", compute=lambda: _value({"ok": 1})) == {"ok": 1}
    assert "cache_read_failed" in caplog.text
    assert await cached_json(gm, "x", compute=lambda: _value({"ok": 2})) == {"ok": 1}  # overwritten


async def test_cached_json_hits_and_invalidation_moves_the_generation(db, valkey):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    assert await cached_json(gm, "x", compute=compute) == {"n": 1}
    assert await cached_json(gm, "x", compute=compute) == {"n": 1}  # a hit
    gen_before = await valkey.get(f"cachegen:{c.id}")
    assert gen_before is not None
    await invalidate_campaign_cache(c.id)
    assert int(await valkey.get(f"cachegen:{c.id}")) == int(gen_before) + 1
    assert [k async for k in valkey.scan_iter(match=f"cache:{c.id}:*")] == []
    assert await cached_json(gm, "x", compute=compute) == {"n": 2}


async def test_a_write_racing_an_invalidation_is_never_served(db, valkey):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    values = iter([{"v": "stale"}, {"v": "fresh"}])

    async def racing():
        value = next(values)
        await invalidate_campaign_cache(c.id)  # a visibility change commits mid-compute
        return value

    assert await cached_json(gm, "x", compute=racing) == {"v": "stale"}

    async def fresh():
        return next(values)

    assert await cached_json(gm, "x", compute=fresh) == {"v": "fresh"}  # the stale value was not stored
    # A value written under a generation read before the invalidation is unreachable.
    old = await access_cache.cache_generation(valkey, c.id)
    await valkey.set(cache_key(gm, old, "y"), json.dumps({"v": "stale"}))
    await invalidate_campaign_cache(c.id)
    await valkey.set(cache_key(gm, old, "y"), json.dumps({"v": "stale"}))  # the late write
    assert await cached_json(gm, "y", compute=lambda: _value({"v": "new"})) == {"v": "new"}


async def _value(v):
    return v


async def test_generation_is_seeded_not_reset_to_zero(db, valkey):
    cid = uuid.uuid4()
    await invalidate_campaign_cache(cid)  # missing: seeded with time_ns, then incremented
    assert int(await valkey.get(f"cachegen:{cid}")) > 10 ** 15


async def test_cache_without_valkey_computes(db, no_valkey):
    c, owner = await _campaign(db)
    gm = await ctx_for(db, owner.id, c.id)
    assert await cached_json(gm, "x", compute=lambda: _value([1])) == [1]
    await invalidate_campaign_cache(c.id)  # no client: nothing cached, nothing raised


# ── Worker ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("change", ["demote", "remove"])
async def test_a_job_started_before_the_grant_change_fails_permission_changed(db, published, change):
    from tests.jobs.test_worker import _assert_permission_changed, _campaign as job_campaign, _job, _member as job_member

    c = await job_campaign(db)
    m = await job_member(db, c, CampaignRole.CO_GM)
    await db.commit()
    row = await _job(db, c, "test_w.record", user_id=m.user_id, ctx_kind="gm", access_epoch=m.access_epoch)
    if change == "demote":
        await change_member_role(db, m, "player")
    else:
        await remove_member(db, m)
    await db.commit()
    await _assert_permission_changed(db, row)


# ── AST guards ─────────────────────────────────────────────────────────────

def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _reserved_literals(root: Path) -> list[str]:
    """Every string literal under `root` (outside app/access/ and docstrings)
    that holds `cache:` or `access:`."""
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == "access":
            continue
        tree = ast.parse(path.read_text(), str(path))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
                    and ("cache:" in node.value or "access:" in node.value)):
                found.append(f"{rel}:{node.lineno}: {node.value!r}")
    return found


def test_only_app_access_builds_cache_keys_or_access_channels():
    assert _reserved_literals(BACKEND / "app") == []


def test_the_guard_catches_a_key_outside_app_access(tmp_path):
    (tmp_path / "access").mkdir()
    (tmp_path / "access" / "ok.py").write_text('KEY = "cache:x"\n')
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "bad.py").write_text(
        '"""Docstrings may say cache: freely."""\n'
        'def key(u):\n    return f"cache:journals:{u}"\n'
        'CHANNEL = "access:%s"\n')
    found = _reserved_literals(tmp_path)
    assert len(found) == 2 and all(f.startswith("services/bad.py") for f in found)


def test_the_dead_cache_service_is_gone():
    assert not (BACKEND / "app" / "services" / "cache_service.py").exists()


@pytest.mark.skipif(not VALKEY_TEST_URL, reason="VALKEY_TEST_URL not set")
async def test_watch_fires_on_a_real_valkey_message(db, monkeypatch):
    import redis.asyncio as aioredis

    client = aioredis.from_url(VALKEY_TEST_URL, decode_responses=True)
    previous = valkey_client.set_valkey(client)
    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)
    try:
        c, _ = await _campaign(db)
        user, m = await _member(db, c, "player")
        ctx = await ctx_for(db, user.id, c.id)
        task = asyncio.ensure_future(grant_watch(ctx, bind=db.bind))
        await asyncio.sleep(0.3)
        await change_member_role(db, m, "co_gm")
        await db.commit()
        assert await asyncio.wait_for(task, 3) == "message"
    finally:
        valkey_client.set_valkey(previous)
        await client.aclose()
