"""E0-Jobs.6: app/core/pubsub.py (the only publisher) and the `job` events
(app/jobs/events.py).

The spec's I/O matrix: the three channels and their listeners, the progress
and unkeyed-invalidation throttles (leading + trailing), bad messages, no
Valkey and Valkey errors; the `job` event after every commit that changes a
Job row (not after a rollback), and a worker run publishing `running` then
`done`. The pub/sub tests run against fakeredis and, when VALKEY_TEST_URL is
set (CI), a real Valkey. The AST guard: no publish or subscribe in app/
outside app/core/pubsub.py (and app/access/grants.py, AD-13's channel).
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

import fakeredis
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.core import pubsub, valkey_client
from app.core.pubsub import (
    campaign_events_channel, jobs_channel, listen_campaign_events, listen_jobs, listen_live, live_channel,
    publish_campaign_event, publish_job, publish_live,
)

BACKEND = Path(__file__).resolve().parents[1]
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


@pytest.fixture
def no_valkey():
    previous = valkey_client.set_valkey(None)
    yield
    valkey_client.set_valkey(previous)


@pytest.fixture
def fast_windows(monkeypatch):
    monkeypatch.setattr(pubsub, "JOB_PROGRESS_WINDOW_S", 0.3)
    monkeypatch.setattr(pubsub, "CAMPAIGN_EVENT_WINDOW_S", 0.3)


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


class Collector:
    """Runs one listener in a task and keeps what it yields."""

    def __init__(self, gen):
        self.gen = gen
        self.items: list[tuple[str, object]] = []
        self.ended = False
        self.task = asyncio.ensure_future(self._run())

    async def _run(self):
        try:
            async for item in self.gen:
                self.items.append(item)
        finally:
            self.ended = True

    async def subscribed(self, client, channel):
        await wait_until(lambda: numsub(client, channel))

    async def close(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass


def job_data(job_id, status="running", progress=None, **kw):
    return {"job_id": job_id, "kind": "system.noop", "status": status, "progress": progress, **kw}


# ── The AST guard ──────────────────────────────────────────────────────────

ALLOWED = {Path("core/pubsub.py"), Path("access/grants.py")}
PUBSUB_ATTRS = {"publish", "spublish", "subscribe", "psubscribe", "ssubscribe", "pubsub"}
PUBSUB_COMMANDS = {"PUBLISH", "SPUBLISH", "SUBSCRIBE", "PSUBSCRIBE", "SSUBSCRIBE"}


def _pubsub_calls(root: Path) -> list[str]:
    """Every `.publish(`/`.subscribe(`/`.pubsub(` call (and every
    PUBLISH/SUBSCRIBE command literal) under `root`, outside ALLOWED."""
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel in ALLOWED:
            continue
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in PUBSUB_ATTRS):
                found.append(f"{rel}:{node.lineno}: .{node.func.attr}(")
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value.strip().upper() in PUBSUB_COMMANDS):
                found.append(f"{rel}:{node.lineno}: {node.value!r}")
    return found


def test_only_core_pubsub_publishes_or_subscribes():
    assert _pubsub_calls(BACKEND / "app") == []


def test_the_guard_catches_a_publish_outside_pubsub(tmp_path):
    for rel in ALLOWED:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("async def f(c):\n    await c.publish('x', 'y')\n")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "bad.py").write_text(
        "async def f(c):\n"
        "    await c.publish('jobs:x', '{}')\n"
        "    p = c.pubsub()\n"
        "    await p.subscribe('x')\n"
        "    await c.execute_command('PUBLISH', 'x', 'y')\n"
        "    await c.spublish('x', 'y')\n")
    found = _pubsub_calls(tmp_path)
    assert len(found) == 5 and all(f.startswith("services/bad.py") for f in found)


def test_exactly_three_channels():
    cid = uuid.uuid4()
    assert set(pubsub.CHANNELS) == {"jobs", "campaign_events", "live"}
    assert jobs_channel(cid) == f"jobs:{cid}"
    assert campaign_events_channel(cid) == f"campaign:{cid}:events"
    assert live_channel(cid) == f"live:{cid}:out"


# ── Publish and listen ─────────────────────────────────────────────────────

async def test_publish_job_reaches_listen_jobs(valkey):
    cid, jid = uuid.uuid4(), uuid.uuid4()
    other = Collector(listen_jobs(uuid.uuid4()))
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    await publish_job(cid, {**job_data(jid, "done", 1.0), "secret": "dropped"})
    await wait_until(lambda: got.items)
    event, data = got.items[0]
    assert event == "job"
    assert data == {"job_id": str(jid), "kind": "system.noop", "status": "done", "progress": 1.0, "stage": None,
                    "eta_seconds": None, "error_code": None, "error_message": None, "result_ref": None}
    await asyncio.sleep(0.05)
    assert other.items == []
    await got.close()
    await other.close()


async def test_campaign_events_and_live(valkey):
    cid, ref, live = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = Collector(listen_campaign_events(cid))
    lives = Collector(listen_live(live))
    await events.subscribed(valkey, campaign_events_channel(cid))
    await lives.subscribed(valkey, live_channel(live))
    await publish_campaign_event(cid, "entities", ref)
    await publish_live(live, {"type": "caption", "text": "hi"})
    await wait_until(lambda: events.items and lives.items)
    assert events.items == [("invalidate", {"domain": "entities", "id": str(ref)})]
    assert lives.items == [("live", {"type": "caption", "text": "hi"})]
    with pytest.raises(ValueError):
        await publish_campaign_event(cid, "", None)
    await events.close()
    await lives.close()


async def test_keyed_campaign_events_are_not_throttled(valkey, fast_windows):
    cid = uuid.uuid4()
    got = Collector(listen_campaign_events(cid))
    await got.subscribed(valkey, campaign_events_channel(cid))
    refs = [uuid.uuid4() for _ in range(3)]
    for ref in refs:
        await publish_campaign_event(cid, "entities", ref)
    await wait_until(lambda: len(got.items) == 3)
    assert [d["id"] for _e, d in got.items] == [str(r) for r in refs]
    await got.close()


async def test_bad_json_is_skipped_and_logged(valkey, caplog):
    cid = uuid.uuid4()
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    caplog.set_level(logging.WARNING, logger="app.core.pubsub")
    await valkey.publish(jobs_channel(cid), "not json")
    await valkey.publish(jobs_channel(cid), json.dumps({"data": {}}))  # no event name
    await publish_job(cid, job_data(uuid.uuid4()))
    await wait_until(lambda: got.items)
    assert len(got.items) == 1 and not got.ended
    assert "pubsub_bad_message" in caplog.text
    await got.close()


async def test_closing_a_listener_unsubscribes(valkey):
    cid = uuid.uuid4()
    gen = listen_jobs(cid)
    first = asyncio.ensure_future(anext(gen))
    await wait_until(lambda: numsub(valkey, jobs_channel(cid)))
    await publish_job(cid, job_data(uuid.uuid4()))
    assert (await asyncio.wait_for(first, 2))[0] == "job"
    await gen.aclose()
    await wait_until(lambda: _zero(valkey, jobs_channel(cid)))


async def _zero(client, channel):
    return await numsub(client, channel) == 0


async def test_cancelling_a_listener_unsubscribes(valkey):
    cid = uuid.uuid4()
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    await got.close()
    await wait_until(lambda: _zero(valkey, jobs_channel(cid)))


# ── Throttles ──────────────────────────────────────────────────────────────

async def test_progress_burst_is_one_now_and_one_trailing(valkey, fast_windows):
    cid, jid = uuid.uuid4(), uuid.uuid4()
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    for i in range(5):
        await publish_job(cid, job_data(jid, progress=i / 10), progress_only=True)
    await wait_until(lambda: got.items)
    assert [d["progress"] for _e, d in got.items] == [0.0]  # the leading edge, at once
    await wait_until(lambda: len(got.items) == 2, timeout=2)
    assert got.items[1][1]["progress"] == 0.4  # the trailing edge keeps the latest
    await asyncio.sleep(0.5)
    assert len(got.items) == 2
    await got.close()


async def test_status_changes_are_never_throttled_and_drop_the_trailing_progress(valkey, fast_windows):
    cid, jid = uuid.uuid4(), uuid.uuid4()
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    await publish_job(cid, job_data(jid, progress=0.1), progress_only=True)
    await publish_job(cid, job_data(jid, progress=0.2), progress_only=True)  # trailing, pending
    await publish_job(cid, job_data(jid, "done", 1.0))
    await publish_job(cid, job_data(jid, "done", 1.0))
    await wait_until(lambda: len(got.items) == 3)
    await asyncio.sleep(0.5)  # past the window: the trailing progress was dropped
    assert [(d["status"], d["progress"]) for _e, d in got.items] == [("running", 0.1), ("done", 1.0),
                                                                     ("done", 1.0)]
    await got.close()


async def test_progress_throttle_is_per_job(valkey, monkeypatch):
    monkeypatch.setattr(pubsub, "JOB_PROGRESS_WINDOW_S", 30)  # a trailing edge could not arrive in time
    cid = uuid.uuid4()
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    await publish_job(cid, job_data(uuid.uuid4(), progress=0.1), progress_only=True)
    await publish_job(cid, job_data(uuid.uuid4(), progress=0.1), progress_only=True)
    await wait_until(lambda: len(got.items) == 2, timeout=2)
    await got.close()


async def test_a_trail_is_dropped_when_another_process_takes_the_next_window(valkey):
    cid, jid = uuid.uuid4(), uuid.uuid4()
    key = f"{pubsub.THROTTLE_PREFIX}:job:{jid}"
    got = Collector(listen_jobs(cid))
    await got.subscribed(valkey, jobs_channel(cid))
    await valkey.set(key, "1", px=300)  # another process's window
    await publish_job(cid, job_data(jid, progress=0.1), progress_only=True)  # a trail, waiting
    assert key in pubsub._TRAILING
    await asyncio.sleep(0.15)
    await valkey.delete(key)  # that window ends ...
    await valkey.set(key, "1", px=5000)  # ... and the other process takes the next one first
    await asyncio.sleep(0.5)  # the trail woke, lost the acquire and was dropped
    assert got.items == [] and key not in pubsub._TRAILING
    await got.close()


async def test_unkeyed_invalidation_burst_is_one_now_and_one_at_window_end(valkey, fast_windows):
    cid = uuid.uuid4()
    got = Collector(listen_campaign_events(cid))
    await got.subscribed(valkey, campaign_events_channel(cid))
    started = time.monotonic()
    for _ in range(3):
        await publish_campaign_event(cid, "visibility", None)
    await publish_campaign_event(cid, "entities", None)  # another domain: its own window
    await wait_until(lambda: len(got.items) == 2)
    assert sorted(d["domain"] for _e, d in got.items) == ["entities", "visibility"]
    await wait_until(lambda: len(got.items) == 3, timeout=2)
    assert got.items[2] == ("invalidate", {"domain": "visibility", "id": None})
    assert time.monotonic() - started >= 0.25  # at the window's end, not before
    await asyncio.sleep(0.5)
    assert len(got.items) == 3
    await got.close()


async def test_flush_pending_sends_the_trailing_publish_now(valkey, monkeypatch):
    monkeypatch.setattr(pubsub, "CAMPAIGN_EVENT_WINDOW_S", 30)
    cid = uuid.uuid4()
    got = Collector(listen_campaign_events(cid))
    await got.subscribed(valkey, campaign_events_channel(cid))
    await publish_campaign_event(cid, "visibility", None)
    await publish_campaign_event(cid, "visibility", None)
    await wait_until(lambda: len(got.items) == 1)
    await pubsub.flush_pending()
    await wait_until(lambda: len(got.items) == 2, timeout=1)
    assert pubsub._TRAILING == {}
    await got.close()


# ── No Valkey, Valkey errors ───────────────────────────────────────────────

async def test_no_valkey_publish_is_a_noop_and_listen_ends(no_valkey, caplog):
    caplog.set_level(logging.DEBUG, logger="app.core.pubsub")
    cid = uuid.uuid4()
    await publish_job(cid, job_data(uuid.uuid4()))
    await publish_job(cid, job_data(uuid.uuid4()), progress_only=True)
    await publish_campaign_event(cid, "visibility", None)
    await publish_live(cid, {"x": 1})
    assert [item async for item in listen_jobs(cid)] == []
    assert "pubsub_listen_skipped" in caplog.text


async def test_publish_errors_are_logged_never_raised(monkeypatch, caplog):
    class Hung:
        async def publish(self, *a):
            await asyncio.sleep(10)

        async def set(self, *a, **kw):
            await asyncio.sleep(10)

    class Down:
        async def publish(self, *a):
            raise ConnectionError("down")

        async def set(self, *a, **kw):
            raise ConnectionError("down")

        def pubsub(self):
            raise ConnectionError("down")

    monkeypatch.setattr(pubsub, "PUBLISH_TIMEOUT_S", 0.05)
    previous = valkey_client.set_valkey(Hung())
    try:
        cid = uuid.uuid4()
        await asyncio.wait_for(publish_job(cid, job_data(uuid.uuid4())), 1)
        assert "pubsub_publish_failed" in caplog.text
        await asyncio.wait_for(publish_job(cid, job_data(uuid.uuid4()), progress_only=True), 1)
        assert "pubsub_throttle_failed" in caplog.text
        caplog.clear()
        valkey_client.set_valkey(Down())
        await publish_live(cid, {"x": 1})
        await publish_campaign_event(cid, "visibility", None)
        assert "pubsub_publish_failed" in caplog.text and "pubsub_throttle_failed" in caplog.text
        assert [item async for item in listen_jobs(cid)] == []  # ends, logged
        assert "pubsub_subscribe_failed" in caplog.text
    finally:
        valkey_client.set_valkey(previous)


# ── `job` events after commit (database) ───────────────────────────────────

async def _campaign(db):
    from app.db.models import Campaign, Genre
    from tests.ev4.fixtures import create_user

    owner = await create_user(db, "pubsub_owner")
    c = Campaign(user_id=owner.id, name="PubSub", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c


def _job_row(c, kind="system.noop"):
    from app.db.models import Job
    from app.jobs import registry

    return Job(campaign_id=c.id, kind=kind, queue=registry.get_kind(kind).queue,
               idempotency_key=f"test:{uuid.uuid4().hex}", ctx_kind="gm", ctx_user_id=c.user_id,
               created_by=c.user_id, payload={})


async def report_twice(job, ctx, db):
    await job.report(0.25, "Reading", 30)
    await job.report(0.5, "Writing", 10)


def _register_report_kind():
    from app.domain.enums import JobQueue
    from app.jobs.registry import KINDS, JobKind, register

    if "test_ps.report" not in KINDS:
        register(JobKind(name="test_ps.report", queue=JobQueue.INTERACTIVE, timeout_s=5,
                         handler=f"{__name__}:report_twice"))


async def test_job_change_publishes_after_commit_only(db, valkey):
    import app.jobs  # noqa: F401  (installs the listeners)
    from app.domain.enums import JobStatus

    c = await _campaign(db)
    got = Collector(listen_jobs(c.id))
    await got.subscribed(valkey, jobs_channel(c.id))
    row = _job_row(c)
    db.add(row)
    await db.flush()
    await asyncio.sleep(0.1)
    assert got.items == []  # flushed, not committed
    await db.commit()
    await wait_until(lambda: got.items)
    assert got.items[0][1]["status"] == "queued" and got.items[0][1]["job_id"] == str(row.id)

    # Rollback: nothing.
    job_id, model = row.id, type(row)
    row.status = JobStatus.CANCELLED
    await db.flush()
    await db.rollback()
    # A savepoint rolled back inside a committed transaction: nothing either.
    row = await db.get(model, job_id, populate_existing=True)
    savepoint = await db.begin_nested()
    row.stage = "inside"
    await db.flush()
    await savepoint.rollback()
    await db.commit()
    await asyncio.sleep(0.2)
    assert len(got.items) == 1

    # A field the event does not carry (heartbeat_at): nothing.
    from datetime import datetime, timezone

    row.heartbeat_at = datetime.now(timezone.utc)
    await db.commit()
    await asyncio.sleep(0.2)
    assert len(got.items) == 1

    row.status = JobStatus.CANCELLED
    await db.commit()
    await wait_until(lambda: len(got.items) == 2)
    assert got.items[1][1]["status"] == "cancelled"
    await got.close()


async def test_no_valkey_skips_the_job_event_select(db, no_valkey, monkeypatch, caplog):
    import app.jobs  # noqa: F401
    from app.jobs import events

    def boom(_bind):
        raise AssertionError("no SELECT without Valkey")

    monkeypatch.setattr(events, "_session_factory", boom)
    c = await _campaign(db)
    db.add(_job_row(c))
    await db.commit()
    assert "after-commit callback failed" not in caplog.text


async def test_orm_writes_choose_status_or_progress_events(db, valkey, monkeypatch):
    """With a 30 s window and the throttle key held, only a status event
    can arrive in time: a misclassified ORM change would show."""
    import app.jobs  # noqa: F401
    from app.domain.enums import JobStatus

    monkeypatch.setattr(pubsub, "JOB_PROGRESS_WINDOW_S", 30)
    c = await _campaign(db)
    got = Collector(listen_jobs(c.id))
    await got.subscribed(valkey, jobs_channel(c.id))
    row = _job_row(c)
    db.add(row)
    await db.commit()
    await wait_until(lambda: got.items)  # queued: a new row is a status event
    key = f"{pubsub.THROTTLE_PREFIX}:job:{row.id}"
    await valkey.set(key, "1", px=30_000)

    row.stage = "Reading"
    await db.commit()
    await asyncio.sleep(0.5)
    assert len(got.items) == 1  # progress-only: throttled
    assert key in pubsub._TRAILING

    row.status = JobStatus.CANCELLED
    await db.commit()
    await wait_until(lambda: len(got.items) == 2, timeout=0.5)
    assert got.items[1][1]["status"] == "cancelled" and got.items[1][1]["stage"] == "Reading"
    assert key not in pubsub._TRAILING  # the pending progress was dropped
    await asyncio.sleep(0.2)
    assert len(got.items) == 2
    await got.close()


async def test_a_reaper_pass_publishes_the_requeue(db, monkeypatch):
    import fakeredis as fr
    from datetime import datetime, timedelta, timezone

    import sqlalchemy as sa

    import app.jobs  # noqa: F401
    from app.core.config import get_settings
    from app.db.models import Job
    from app.domain.enums import JobStatus
    from app.jobs import worker
    from tests.conftest import TEST_DB_URL

    calls: list[tuple] = []

    async def record(campaign_id, event, *, progress_only=False):
        calls.append((campaign_id, dict(event), progress_only))

    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    monkeypatch.setattr(worker.aioredis, "from_url", lambda *a, **kw: fr.FakeAsyncRedis(decode_responses=True))
    monkeypatch.setattr(pubsub, "publish_job", record)
    c = await _campaign(db)
    now = datetime.now(timezone.utc)
    row = _job_row(c)
    row.status, row.attempts, row.worker_id = JobStatus.RUNNING, 1, "gone-worker"
    row.started_at, row.heartbeat_at = now - timedelta(seconds=100), now - timedelta(seconds=61)
    db.add(row)
    await db.commit()
    await db.execute(sa.update(Job).where(Job.id == row.id).values(created_at=now - timedelta(seconds=600)))
    await db.commit()
    calls.clear()

    reaper = worker.Reaper("x", connection=fr.FakeRedis(server=fr.FakeServer()))
    assert await asyncio.to_thread(reaper.tick) is not None
    mine = [(e, p) for cid, e, p in calls if e["job_id"] == str(row.id)]
    assert any(e["status"] == "queued" and e["error_code"] == "interrupted" and not p for e, p in mine), calls


async def test_a_worker_run_publishes_running_then_done(db, valkey, fast_windows):
    import app.jobs  # noqa: F401
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.domain.enums import JobStatus
    from app.jobs.worker import run_job

    _register_report_kind()
    c = await _campaign(db)
    got = Collector(listen_jobs(c.id))
    await got.subscribed(valkey, jobs_channel(c.id))
    row = _job_row(c, "test_ps.report")
    db.add(row)
    await db.commit()
    await wait_until(lambda: got.items)  # queued
    status = await run_job(row.id, async_sessionmaker(db.bind, expire_on_commit=False), "ps-worker:1")
    assert status == JobStatus.DONE
    await wait_until(lambda: got.items and got.items[-1][1]["status"] == "done")
    await asyncio.sleep(0.5)  # past the progress window: nothing trails the done
    statuses = [d["status"] for _e, d in got.items]
    assert statuses[0] == "queued" and statuses[1] == "running" and statuses[-1] == "done"
    running = got.items[1][1]
    assert running["job_id"] == str(row.id) and running["kind"] == "test_ps.report"
    assert set(running) == set(pubsub.JOB_EVENT_FIELDS)
    progress = [d for _e, d in got.items[2:-1]]
    assert progress and progress[0]["progress"] == 0.25 and progress[0]["stage"] == "Reading"
    assert all(d["status"] == "running" for d in progress)
    done = got.items[-1][1]
    assert done["progress"] == 1.0 and done["error_code"] is None
    await got.close()
