"""E0-Jobs.6: app/core/sse.py (`sse_response`, the one SSE pattern).

The spec's I/O matrix: headers, framing, the 15 s ping, the close watch
(`access_changed` then the end within 2 s; a failed watch ends it silently),
a client disconnect (the listener's subscription and the watch both gone),
a slow client (bounded queue, bounded send) and the fail-closed registration.

The end-to-end tests run an in-process uvicorn on 127.0.0.1 (stopped in
teardown) with a real HTTP client. Most use a fake close watch; the ones
taking the `db` fixture use the real `grant_watch` that app.access registers
(the AC: a test route returning `sse_response(listen_jobs(cid), ctx=ctx)`).
Pub/sub runs on fakeredis and, with VALKEY_TEST_URL (CI), a real Valkey.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
import uuid

import fakeredis
import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

import app.access  # noqa: F401  (registers grant_watch as the close watch)
from app.core import pubsub, sse, valkey_client
from app.core.pubsub import jobs_channel, listen_jobs, publish_job
from app.core.sse import format_event, sse_response

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")


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


class FakeWatch:
    """A close watch the test fires by hand."""

    def __init__(self):
        self.fire = asyncio.Event()
        self.reason = "message"
        self.error: BaseException | None = None
        self.started = 0
        self.cancelled = 0
        self.calls: list[tuple] = []

    async def __call__(self, ctx, *, bind=None):
        self.started += 1
        self.calls.append((ctx, bind))
        try:
            await self.fire.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        if self.error is not None:
            raise self.error
        return self.reason


@pytest.fixture
def watch(monkeypatch):
    fake = FakeWatch()
    monkeypatch.setattr(sse, "_close_watch", (fake, None))
    return fake


@pytest_asyncio.fixture
async def serve():
    """Start an app on an in-process uvicorn (127.0.0.1, a free port);
    every server is stopped in teardown."""
    running = []

    async def start(application) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(application, lifespan="off", log_level="warning",
                                               timeout_graceful_shutdown=1))
        task = asyncio.ensure_future(server.serve(sockets=[sock]))
        running.append((server, task, sock))
        deadline = time.monotonic() + 5
        while not server.started:
            if task.done() or time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not start")
            await asyncio.sleep(0.01)
        return f"http://127.0.0.1:{sock.getsockname()[1]}"

    yield start
    for server, task, sock in running:
        server.should_exit = True
        server.force_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            sock.close()


def stream_app(gen_factory, ctx, bind=None) -> FastAPI:
    application = FastAPI()

    @application.get("/stream")
    async def stream():
        return sse_response(gen_factory(), ctx=ctx, bind=bind)

    return application


class Reader:
    """Reads SSE frames from an open httpx stream into a queue."""

    def __init__(self, response: httpx.Response):
        self.response = response
        self.frames: asyncio.Queue = asyncio.Queue()
        self.ended = asyncio.Event()
        self.task = asyncio.ensure_future(self._run())

    async def _run(self):
        event, data = None, []
        try:
            async for line in self.response.aiter_lines():
                if line == "":
                    if event is not None:
                        await self.frames.put((event, json.loads("\n".join(data)) if data else None))
                    event, data = None, []
                elif line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: "):
                    data.append(line[len("data: "):])
        except (httpx.HTTPError, asyncio.CancelledError):
            pass
        finally:
            self.ended.set()

    async def next(self, timeout=2.0, skip_pings=True):
        while True:
            frame = await asyncio.wait_for(self.frames.get(), timeout)
            if not (skip_pings and frame[0] == "ping"):
                return frame

    async def close(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass


async def numsub(client, channel: str) -> int:
    result = await client.pubsub_numsub(channel)
    return int(result[0][1]) if result else 0


async def wait_until(cond, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        value = cond()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


async def _zero(client, channel):
    return await numsub(client, channel) == 0


def job(job_id, status="running"):
    return {"job_id": job_id, "kind": "system.noop", "status": status}


class Recorder:
    """An ASGI `send` that records what goes out; `block_after` blocks
    every body send after that many."""

    def __init__(self, block_after: int | None = None, delay: float = 0):
        self.messages: list[dict] = []
        self.block_after = block_after
        self.delay = delay

    async def __call__(self, message):
        if message["type"] == "http.response.body" and message.get("more_body"):
            bodies = sum(1 for m in self.messages if m["type"] == "http.response.body")
            if self.block_after is not None and bodies >= self.block_after:
                await asyncio.Event().wait()
            if self.delay:
                await asyncio.sleep(self.delay)
        self.messages.append(message)

    def events(self) -> list[str]:
        out = []
        for m in self.messages:
            if m["type"] == "http.response.body" and m.get("body"):
                out.append(m["body"].decode().split("\n", 1)[0].removeprefix("event: "))
        return out

    @property
    def ended(self) -> bool:
        return bool(self.messages) and self.messages[-1] == {"type": "http.response.body", "body": b"",
                                                             "more_body": False}


async def idle():
    await asyncio.Event().wait()
    yield ("never", None)


# ── Unit: framing, headers, registration ───────────────────────────────────

def test_format_event():
    assert format_event("job", {"a": 1}) == 'event: job\ndata: {"a":1}\n\n'
    assert format_event("note", "two\nlines") == "event: note\ndata: two\ndata: lines\n\n"
    assert format_event("ping", {}) == "event: ping\ndata: {}\n\n"
    for bad in ("", "a\nb", "a:b", None):
        with pytest.raises(ValueError):
            format_event(bad, {})


def test_headers(watch):
    response = sse_response(idle(), ctx=object())
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    extra = sse_response(idle(), ctx=object(), headers={"X-Extra": "1", "Cache-Control": "public"})
    assert extra.headers["x-extra"] == "1" and extra.headers["cache-control"] == "no-cache"


def test_fails_closed_without_a_close_watch(monkeypatch):
    monkeypatch.setattr(sse, "_close_watch", None)
    with pytest.raises(RuntimeError):
        sse_response(idle(), ctx=object())


def test_app_access_registers_grant_watch():
    from app.access import grant_watch
    from app.access.grants import _check_watchable

    assert sse._close_watch == (grant_watch, _check_watchable)
    sse.register_close_watch(grant_watch, check=_check_watchable)  # same one again: a no-op
    with pytest.raises(ValueError):
        sse.register_close_watch(lambda ctx, bind=None: None)


def test_the_check_rejects_an_unwatchable_ctx():
    with pytest.raises((TypeError, ValueError)):
        sse_response(idle(), ctx=object())  # the real check: not a CampaignContext
    with pytest.raises(ValueError):
        sse_response(idle(), ctx=None)


# ── Unit: the stream loop (a recording `send`) ─────────────────────────────

async def test_pings_every_interval_and_the_watch_ends_it(watch, monkeypatch):
    monkeypatch.setattr(sse, "SSE_PING_S", 0.1)
    send = Recorder()
    response = sse_response(idle(), ctx="ctx", bind="bind")
    task = asyncio.ensure_future(response.stream_response(send))
    await asyncio.sleep(0.35)
    started = time.monotonic()
    watch.fire.set()
    await asyncio.wait_for(task, 2)
    assert time.monotonic() - started < 2
    events = send.events()
    assert events.count("ping") >= 2 and events[-1] == "access_changed"
    assert json.loads(send.messages[-2]["body"].decode().split("data: ", 1)[1]) == {"detail": "Not found"}
    assert send.ended and watch.calls == [("ctx", "bind")]


@pytest.mark.parametrize("how", ["poll_failed", "raises"])
async def test_a_failed_watch_ends_the_stream_without_access_changed(watch, how):
    if how == "raises":
        watch.error = RuntimeError("db down")
    else:
        watch.reason = "poll_failed"
    send = Recorder()
    task = asyncio.ensure_future(sse_response(idle(), ctx="ctx").stream_response(send))
    await asyncio.sleep(0.05)
    watch.fire.set()
    await asyncio.wait_for(task, 2)
    assert "access_changed" not in send.events() and send.ended


async def test_items_are_framed_and_bad_ones_skipped(watch):
    async def gen():
        yield ("job", {"n": 1})
        yield format_event("custom", {"n": 2})
        yield 42  # not an item: skipped, logged
        yield "half a frame"  # skipped too
        yield ("job", {"n": 3})

    send = Recorder()
    await asyncio.wait_for(sse_response(gen(), ctx="ctx").stream_response(send), 2)
    assert send.events() == ["job", "custom", "job"] and send.ended
    assert watch.cancelled == 1  # the watch goes with the stream


async def test_a_full_queue_ends_the_stream(watch, monkeypatch):
    monkeypatch.setattr(sse, "SSE_QUEUE_MAX", 8)
    pulled = 0

    async def fast():
        nonlocal pulled
        while True:
            pulled += 1
            yield ("job", {"n": pulled})

    send = Recorder(delay=0.05)  # slow, but every send completes
    response = sse_response(fast(), ctx="ctx")
    await asyncio.wait_for(response.stream_response(send), 3)
    assert response.overflowed
    assert pulled <= 8 + 2  # pulled items are bounded by the queue
    assert len(send.events()) <= 8 + 1 and send.ended


async def test_a_blocked_send_aborts_the_stream(watch, monkeypatch):
    monkeypatch.setattr(sse, "SSE_QUEUE_MAX", 1000)  # the send timeout ends it, not the queue
    monkeypatch.setattr(sse, "SEND_TIMEOUT_S", 0.2)
    pulled = 0

    async def steady():
        nonlocal pulled
        while True:
            pulled += 1
            yield ("job", {"n": pulled})
            await asyncio.sleep(0.01)

    send = Recorder(block_after=2)
    started = time.monotonic()
    response = sse_response(steady(), ctx="ctx")
    await asyncio.wait_for(response.stream_response(send), 3)
    assert time.monotonic() - started < 1.5
    assert not response.overflowed and pulled < 100
    assert not send.ended  # aborted: nothing more is sent to a stuck client
    assert watch.cancelled == 1


async def test_the_watch_interrupts_a_blocked_send(watch, monkeypatch):
    monkeypatch.setattr(sse, "SEND_TIMEOUT_S", 30)

    async def one():
        yield ("job", {"n": 1})
        await asyncio.Event().wait()

    send = Recorder(block_after=0)
    task = asyncio.ensure_future(sse_response(one(), ctx="ctx").stream_response(send))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    watch.fire.set()
    await asyncio.wait_for(task, 2)
    assert time.monotonic() - started < 1


# ── End to end: in-process uvicorn ─────────────────────────────────────────

async def test_stream_delivers_job_events_and_closes_on_the_watch(valkey, watch, serve):
    cid = uuid.uuid4()
    base = await serve(stream_app(lambda: listen_jobs(cid), ctx="ctx"))
    async with httpx.AsyncClient(timeout=5) as client:
        async with client.stream("GET", f"{base}/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["cache-control"] == "no-cache"
            reader = Reader(response)
            await wait_until(lambda: numsub(valkey, jobs_channel(cid)))
            jid = uuid.uuid4()
            await publish_job(cid, job(jid))
            event, data = await reader.next()
            assert event == "job" and data["job_id"] == str(jid) and data["status"] == "running"
            started = time.monotonic()
            watch.fire.set()
            assert await reader.next() == ("access_changed", {"detail": "Not found"})
            await asyncio.wait_for(reader.ended.wait(), 2)
            assert time.monotonic() - started < 2
            await reader.close()
    await wait_until(lambda: _zero(valkey, jobs_channel(cid)))


async def test_a_disconnect_unsubscribes_and_stops_the_watch(valkey, watch, serve):
    cid = uuid.uuid4()
    base = await serve(stream_app(lambda: listen_jobs(cid), ctx="ctx"))
    async with httpx.AsyncClient(timeout=5) as client:
        async with client.stream("GET", f"{base}/stream") as response:
            reader = Reader(response)
            await wait_until(lambda: numsub(valkey, jobs_channel(cid)))
            await reader.close()
    # The client is gone: within 2 s the subscription and the watch are too.
    await wait_until(lambda: _zero(valkey, jobs_channel(cid)), timeout=2)
    await wait_until(lambda: watch.cancelled == 1, timeout=2)


async def test_no_valkey_the_stream_still_pings_and_closes(watch, serve, monkeypatch):
    monkeypatch.setattr(sse, "SSE_PING_S", 0.1)
    previous = valkey_client.set_valkey(None)
    try:
        cid = uuid.uuid4()
        base = await serve(stream_app(lambda: listen_jobs(cid), ctx="ctx"))
        async with httpx.AsyncClient(timeout=5) as client:
            async with client.stream("GET", f"{base}/stream") as response:
                reader = Reader(response)
                # The listener ended at once (no Valkey): the stream ends with it.
                await asyncio.wait_for(reader.ended.wait(), 2)
                await reader.close()
    finally:
        valkey_client.set_valkey(previous)


# ── End to end with the real grant_watch (database) ────────────────────────

async def _campaign_and_player(db):
    from app.access import ctx_for
    from app.db.models import Campaign, Genre
    from tests.ev4.fixtures import create_user, make_member

    owner = await create_user(db, "sse_owner")
    c = Campaign(user_id=owner.id, name="SSE", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    user = await make_member(db, role="player", campaign_id=c.id)
    ctx = await ctx_for(db, user.id, c.id)
    return c, ctx


async def test_grant_change_closes_the_job_stream(db, valkey, serve, monkeypatch):
    import sqlalchemy as sa

    from app.access import change_member_role, grant_channel, grants
    from app.db.models.campaign_member import CampaignMember

    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)  # only the access message can close it in time
    c, ctx = await _campaign_and_player(db)
    channel = grant_channel(c.id, ctx.grant_id)
    base = await serve(stream_app(lambda: listen_jobs(c.id), ctx=ctx, bind=db.bind))
    async with httpx.AsyncClient(timeout=5) as client:
        async with client.stream("GET", f"{base}/stream") as response:
            reader = Reader(response)
            await wait_until(lambda: numsub(valkey, jobs_channel(c.id)))
            await wait_until(lambda: numsub(valkey, channel))
            jid = uuid.uuid4()
            await publish_job(c.id, job(jid, "done"))
            event, data = await reader.next()
            assert event == "job" and data["job_id"] == str(jid)
            # A real grant change (E0-Access.10): the Player is promoted, the
            # epoch bumps and access:{campaign_id}:{grant_id} goes out after commit.
            member = await db.scalar(sa.select(CampaignMember).where(
                CampaignMember.campaign_id == c.id, CampaignMember.user_id == ctx.user_id))
            started = time.monotonic()
            assert await change_member_role(db, member, "co_gm")
            await db.commit()
            assert await reader.next() == ("access_changed", {"detail": "Not found"})
            await asyncio.wait_for(reader.ended.wait(), 2)
            assert time.monotonic() - started < 2
            await reader.close()
    await wait_until(lambda: _zero(valkey, jobs_channel(c.id)))
    await wait_until(lambda: _zero(valkey, channel))


async def test_disconnect_leaves_no_subscriber(db, valkey, serve, monkeypatch):
    from app.access import grant_channel, grants

    monkeypatch.setattr(grants, "GRANT_POLL_S", 30)
    c, ctx = await _campaign_and_player(db)
    channel = grant_channel(c.id, ctx.grant_id)
    base = await serve(stream_app(lambda: listen_jobs(c.id), ctx=ctx, bind=db.bind))
    async with httpx.AsyncClient(timeout=5) as client:
        async with client.stream("GET", f"{base}/stream") as response:
            reader = Reader(response)
            await wait_until(lambda: numsub(valkey, jobs_channel(c.id)))
            await wait_until(lambda: numsub(valkey, channel))
            await reader.close()
    # PUBSUB NUMSUB 0 for both channels within the 2 s cleanup bound.
    await wait_until(lambda: _zero(valkey, jobs_channel(c.id)), timeout=2)
    await wait_until(lambda: _zero(valkey, channel), timeout=2)
    if isinstance(valkey, aioredis.Redis) and not isinstance(valkey, fakeredis.FakeAsyncRedis):
        # Real Valkey: no connection is left in subscriber mode (CLIENT LIST sub/psub).
        async def no_subscriber_clients():
            clients = await valkey.client_list()
            return not [cl for cl in clients if int(cl.get("sub", 0)) or int(cl.get("psub", 0))]
        await wait_until(no_subscriber_clients, timeout=2)
