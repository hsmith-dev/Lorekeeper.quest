"""E0-Jobs.4: the reaper and restart recovery.

Each test runs one reaper pass (`reap`) against rows it wrote, with RQ on
fakeredis or, as `real`, the CI Valkey (VALKEY_TEST_URL). A fixture first
cancels every other active Job in the shared test database, so a pass only
sees this test's rows. The last test kills a real forked work horse mid-Job.
"""
from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
import redis
import sqlalchemy as sa
from rq import Queue, Worker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.access.context import ctx_for
from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.db.models import Campaign, Genre, Job, User
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs import enqueue, outbox, registry, worker
from app.jobs.registry import JobKind, register
from app.jobs.worker import INTERRUPTED_MESSAGE, LorekeeperWorker, Reaper, reap, run_job

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")

RUNS: dict[uuid.UUID, int] = {}
FACTORY: dict[str, async_sessionmaker] = {}


async def count(job, ctx, db):
    RUNS[job.id] = RUNS.get(job.id, 0) + 1


async def taken_back(job, ctx, db):
    """Mid-run, the reaper judges this attempt dead and requeues the row."""
    db.add(User(email=f"r4-{job.id}@example.com", hashed_password="x", display_name="r"))
    await db.flush()
    async with FACTORY["f"]() as other:
        await other.execute(sa.update(Job).where(Job.id == job.id)
                            .values(status=JobStatus.QUEUED, worker_id=None, heartbeat_at=None))
        await other.commit()
    if job.payload.get("then") == "retryable":
        raise RuntimeError("late failure")
    if job.payload.get("then") == "terminal":
        raise StructuredOutputError("late", attempts=1, errors=[])


async def slow(job, ctx, db):
    await asyncio.sleep(1.5)


async def crash_once(job, ctx, db):
    """First attempt: say which process runs it, then hang (to be killed)."""
    if job.attempts == 1:
        await job.report(0.0, f"pid:{os.getpid()}")
        await asyncio.sleep(60)


register(JobKind(name="test_r.count", queue=JobQueue.INTERACTIVE, timeout_s=5, handler=f"{__name__}:count"))
register(JobKind(name="test_r.taken_back", queue=JobQueue.INTERACTIVE, timeout_s=5,
                 handler=f"{__name__}:taken_back"))
register(JobKind(name="test_r.slow", queue=JobQueue.INTERACTIVE, timeout_s=10, handler=f"{__name__}:slow"))
register(JobKind(name="test_r.crash_once", queue=JobQueue.INTERACTIVE, timeout_s=120,
                 handler=f"{__name__}:crash_once"))


# ── Fixtures and helpers ───────────────────────────────────────────────────

@pytest.fixture(params=["fake", "real"])
def conn(request, monkeypatch):
    """RQ's Valkey, eager off; after-commit pushes go here too."""
    if request.param == "fake":
        c = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    else:
        if not VALKEY_TEST_URL:
            pytest.skip("VALKEY_TEST_URL not set")
        c = redis.Redis.from_url(VALKEY_TEST_URL)
    _empty(c)
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(c)
    yield c
    outbox.set_connection(None)
    _empty(c)
    c.close()


def _empty(c) -> None:
    for q in JobQueue:
        Queue(q.value, connection=c).empty()
    c.delete(worker.REAPER_LOCK_KEY)


@pytest.fixture(autouse=True)
async def only_this_tests_jobs(db):
    await db.execute(sa.update(Job).where(Job.status.in_(["queued", "running"])).values(status="cancelled"))
    await db.commit()
    FACTORY["f"] = async_sessionmaker(db.bind, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _campaign(db) -> Campaign:
    owner = User(email=f"reaper-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                 display_name="owner", access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Reaper", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c


async def _job(db, c: Campaign, kind: str = "test_r.count", *, age_s: float = 0, **kw) -> Job:
    row = Job(campaign_id=c.id, kind=kind, queue=registry.get_kind(kind).queue,
              idempotency_key=f"test:{uuid.uuid4().hex}", ctx_kind="gm", ctx_user_id=c.user_id,
              created_by=c.user_id, access_epoch=0, **{"payload": {}, **kw})
    db.add(row)
    await db.commit()
    if age_s:
        await _age(db, row.id, age_s)
    return row


async def _age(db, job_id, seconds: float) -> None:
    await db.execute(sa.update(Job).where(Job.id == job_id)
                     .values(created_at=_now() - timedelta(seconds=seconds)))
    await db.commit()


async def _row(db, job_id) -> Job | None:
    return (await db.execute(
        sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()


def _factory(db) -> async_sessionmaker:
    return async_sessionmaker(db.bind, expire_on_commit=False)


def _queued(c, queue: JobQueue = JobQueue.INTERACTIVE) -> list[str]:
    return Queue(queue.value, connection=c).job_ids


class _InlineWorker(LorekeeperWorker):
    """LorekeeperWorker without the fork (so fakeredis is shared) and without
    signal handlers (it runs in a thread)."""

    from rq.timeouts import TimerDeathPenalty as death_penalty_class  # SIGALRM is main-thread only

    def _install_signal_handlers(self):
        pass

    def execute_job(self, job, queue):
        self.prepare_execution(job)
        self.perform_job(job, queue)
        from rq.worker import WorkerStatus

        self.set_state(WorkerStatus.IDLE)


def _drain(c, monkeypatch, worker_class=_InlineWorker) -> None:
    """Run every pushed message with a burst worker (in a thread: the test's
    event loop is busy, and `perform` runs its own)."""
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    w = worker_class([q.value for q in JobQueue], connection=c)
    t = threading.Thread(target=w.work, kwargs={"burst": True})
    t.start()
    t.join(60)
    assert not t.is_alive()


# ── Queued rows ────────────────────────────────────────────────────────────

async def test_lost_push_is_pushed_again_and_runs_once(db, conn, monkeypatch):
    c = await _campaign(db)
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, "test_r.count", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()
    assert _queued(conn) == [str(job_id)]
    conn.flushall()  # Valkey lost everything
    await _age(db, job_id, 61)

    result = await reap(_factory(db), conn)
    assert result.pushed == [job_id] and _queued(conn) == [str(job_id)]
    _drain(conn, monkeypatch)
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and RUNS[job_id] == 1
    assert (await reap(_factory(db), conn)).pushed == []
    assert await db.scalar(sa.select(sa.func.count()).select_from(Job)
                           .where(Job.idempotency_key == row.idempotency_key)) == 1


async def test_queued_row_rq_still_holds_is_not_pushed_twice(db, conn):
    c = await _campaign(db)
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, "test_r.count", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()
    await _age(db, job_id, 120)
    assert (await reap(_factory(db), conn)).pushed == []
    assert _queued(conn) == [str(job_id)]


async def test_young_queued_row_is_left_to_the_after_commit_push(db, conn):
    c = await _campaign(db)
    row = await _job(db, c, age_s=30)
    assert (await reap(_factory(db), conn)).pushed == []


async def test_retry_is_pushed_only_once_next_run_at_has_passed(db, conn, monkeypatch):
    c = await _campaign(db)
    due = _now() + timedelta(seconds=10)
    row = await _job(db, c, age_s=600, next_run_at=due, attempts=1, error_code=JobErrorCode.LLM_BUSY)
    assert (await reap(_factory(db), conn, now=due - timedelta(seconds=1))).pushed == []
    assert _queued(conn) == []
    assert (await reap(_factory(db), conn, now=due + timedelta(seconds=1))).pushed == [row.id]
    await db.execute(sa.update(Job).where(Job.id == row.id).values(next_run_at=_now()))
    await db.commit()
    _drain(conn, monkeypatch)
    r = await _row(db, row.id)
    assert r.status == JobStatus.DONE and r.attempts == 2


async def test_queued_row_a_live_worker_is_running_is_not_pushed(db, conn):
    c = await _campaign(db)
    row = await _job(db, c, age_s=120)
    w = Worker(["interactive"], connection=conn, name=f"live-{uuid.uuid4().hex[:8]}")
    w.register_birth()
    try:
        w.set_current_job_id(str(row.id))
        assert (await reap(_factory(db), conn)).pushed == []
    finally:
        w.register_death()


# ── Dependents ─────────────────────────────────────────────────────────────

async def test_dependent_waits_while_its_dependency_is_active(db, conn):
    c = await _campaign(db)
    dep = await _job(db, c, age_s=600, status=JobStatus.RUNNING, worker_id="w", heartbeat_at=_now())
    child = await _job(db, c, age_s=600, depends_on_job_id=dep.id)
    assert child.id not in (await reap(_factory(db), conn)).pushed


async def test_dependent_of_a_dependency_finished_by_raw_sql_is_pushed_once(db, conn, monkeypatch):
    c = await _campaign(db)
    dep = await _job(db, c, age_s=600)
    await db.execute(sa.update(Job).where(Job.id == dep.id).values(status="cancelled"))
    await db.commit()
    child = await _job(db, c, age_s=120, depends_on_job_id=dep.id)
    assert (await reap(_factory(db), conn)).pushed == [child.id]
    assert (await reap(_factory(db), conn)).pushed == []  # RQ holds it now
    assert _queued(conn) == [str(child.id)]
    _drain(conn, monkeypatch)
    assert (await _row(db, child.id)).status == JobStatus.DONE and RUNS[child.id] == 1


async def test_dependent_of_a_deleted_dependency_is_released(db, conn):
    c = await _campaign(db)
    dep = await _job(db, c, age_s=600)
    child = await _job(db, c, age_s=120, depends_on_job_id=dep.id)
    await db.execute(sa.delete(Job).where(Job.id == dep.id))
    await db.commit()
    assert (await _row(db, child.id)).depends_on_job_id is None
    assert (await reap(_factory(db), conn)).pushed == [child.id]


# ── Running rows ───────────────────────────────────────────────────────────

async def test_dead_attempt_with_attempts_left_is_requeued_and_run(db, conn, monkeypatch):
    c = await _campaign(db)
    row = await _job(db, c, age_s=600, status=JobStatus.RUNNING, attempts=1, worker_id="gone-worker",
                     started_at=_now() - timedelta(seconds=100), heartbeat_at=_now() - timedelta(seconds=61),
                     progress=0.4, stage="Reading")
    result = await reap(_factory(db), conn)
    assert result.requeued == [row.id] and result.pushed == [row.id]
    r = await _row(db, row.id)
    assert r.status == JobStatus.QUEUED and r.error_code == JobErrorCode.INTERRUPTED
    assert r.error_message == INTERRUPTED_MESSAGE
    assert r.worker_id is None and r.heartbeat_at is None and r.progress is None and r.stage is None
    _drain(conn, monkeypatch)
    r = await _row(db, row.id)
    assert r.status == JobStatus.DONE and r.attempts == 2 and r.error_code is None


async def test_dead_last_attempt_fails_interrupted_and_releases_dependents(db, conn):
    c = await _campaign(db)
    row = await _job(db, c, age_s=600, status=JobStatus.RUNNING, attempts=3, worker_id="gone-worker",
                     heartbeat_at=_now() - timedelta(seconds=90))
    child = await _job(db, c, depends_on_job_id=row.id)  # young: only the release can push it
    result = await reap(_factory(db), conn)
    assert result.failed == [row.id] and row.id not in result.pushed
    r = await _row(db, row.id)
    assert r.status == JobStatus.FAILED and r.error_code == JobErrorCode.INTERRUPTED
    assert r.error_message == "Interrupted by a restart" and r.finished_at is not None
    assert _queued(conn) == [str(child.id)]


async def test_running_row_with_a_fresh_heartbeat_is_left_alone(db, conn):
    c = await _campaign(db)
    row = await _job(db, c, age_s=600, status=JobStatus.RUNNING, attempts=1, worker_id="gone-worker",
                     heartbeat_at=_now() - timedelta(seconds=30))
    assert not await reap(_factory(db), conn)
    assert (await _row(db, row.id)).status == JobStatus.RUNNING


async def test_stale_row_its_live_worker_is_still_running_is_left_alone(db, conn):
    c = await _campaign(db)
    name = f"live-{uuid.uuid4().hex[:8]}"
    row = await _job(db, c, age_s=600, status=JobStatus.RUNNING, attempts=1, worker_id=name,
                     heartbeat_at=_now() - timedelta(seconds=300))
    w = Worker(["interactive"], connection=conn, name=name)
    w.register_birth()
    try:
        w.set_current_job_id(str(row.id))
        assert not await reap(_factory(db), conn)
        assert (await _row(db, row.id)).status == JobStatus.RUNNING
        w.set_current_job_id(None)  # its work horse was killed: the worker lives on, the Job does not
        assert (await reap(_factory(db), conn)).requeued == [row.id]
    finally:
        w.register_death()


async def test_stale_row_its_live_worker_runs_under_a_distinct_rq_id_is_left_alone(db, conn):
    """A continuation or delayed push runs as `<job_id>_<hex>`: still this Job."""
    c = await _campaign(db)
    name = f"live-{uuid.uuid4().hex[:8]}"
    row = await _job(db, c, age_s=600, status=JobStatus.RUNNING, attempts=1, worker_id=name,
                     heartbeat_at=_now() - timedelta(seconds=300))
    w = Worker(["interactive"], connection=conn, name=name)
    w.register_birth()
    try:
        w.set_current_job_id(outbox.distinct_rq_id(row.id))
        assert not await reap(_factory(db), conn)
        assert (await _row(db, row.id)).status == JobStatus.RUNNING
    finally:
        w.register_death()


@pytest.mark.parametrize("then", [None, "retryable", "terminal"])
async def test_late_outcome_of_an_attempt_taken_back_is_dropped(db, then):
    c = await _campaign(db)
    row = await _job(db, c, "test_r.taken_back", payload={"then": then})
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    r = await _row(db, row.id)
    # The reaper's requeue stands: no `done`, no `failed`, no new retry delay or code.
    assert r.status == JobStatus.QUEUED and r.finished_at is None
    assert r.next_run_at is None and r.error_code is None and r.worker_id is None
    assert await db.scalar(sa.select(User.id).where(User.email == f"r4-{row.id}@example.com")) is None


async def test_reaper_pushes_on_its_own_connection(db, conn):
    c = await _campaign(db)
    row = await _job(db, c, age_s=120)
    other = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    outbox.set_connection(other)  # the process-wide client points elsewhere
    assert (await reap(_factory(db), conn)).pushed == [row.id]
    assert _queued(conn) == [str(row.id)] and _queued(other) == []


async def test_a_failed_push_stops_the_pass_and_the_next_pass_retries(db, conn, monkeypatch):
    c = await _campaign(db)
    rows = [await _job(db, c, age_s=300 - i) for i in range(3)]
    real_push = outbox.push

    def flaky(job_id, *a, **kw):
        if job_id == rows[1].id:
            raise redis.ConnectionError("valkey went away")
        return real_push(job_id, *a, **kw)

    monkeypatch.setattr(outbox, "push", flaky)
    assert (await reap(_factory(db), conn)).pushed == [rows[0].id]
    assert [(await _row(db, r.id)).status for r in rows] == [JobStatus.QUEUED] * 3
    monkeypatch.setattr(outbox, "push", real_push)
    assert (await reap(_factory(db), conn)).pushed == [rows[1].id, rows[2].id]


async def test_rows_rq_holds_never_use_up_the_batch(db, conn, monkeypatch):
    monkeypatch.setattr(worker, "REAPER_BATCH", 1)
    c = await _campaign(db)
    ctx = await ctx_for(db, c.user_id, c.id)
    held = await enqueue(db, ctx, "test_r.count", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()
    await _age(db, held, 600)  # older, and still waiting in RQ's list
    lost = await _job(db, c, kind="test_r.count", age_s=120)
    later = await _job(db, c, kind="test_r.count", age_s=90)
    assert (await reap(_factory(db), conn)).pushed == [lost.id]  # at most one push per pass
    assert (await reap(_factory(db), conn)).pushed == [later.id]


async def test_web_restart_while_a_job_runs_does_not_touch_it(db, conn, monkeypatch):
    from tests.conftest import TEST_DB_URL

    web = create_async_engine(TEST_DB_URL)  # the "web" process that started the Job
    async with async_sessionmaker(web, expire_on_commit=False)() as s:
        c = await _campaign(s)
        ctx = await ctx_for(s, c.user_id, c.id)
        job_id = await enqueue(s, ctx, "test_r.slow", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
        await s.commit()
    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    w = _InlineWorker([q.value for q in JobQueue], connection=conn)
    t = threading.Thread(target=w.work, kwargs={"burst": True})
    t.start()
    for _ in range(100):
        if (await _row(db, job_id)).status == JobStatus.RUNNING:
            break
        await asyncio.sleep(0.05)
    assert (await _row(db, job_id)).status == JobStatus.RUNNING
    await web.dispose()  # web restarts mid-run; the worker has its own engine
    assert not await reap(_factory(db), conn)  # a running Job with a live worker is left alone
    await asyncio.to_thread(t.join, 30)
    r = await _row(db, job_id)
    assert r.status == JobStatus.DONE and r.attempts == 1


# ── The loop ───────────────────────────────────────────────────────────────

def test_one_pass_at_a_time_across_workers(monkeypatch):
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    c = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    first, second = Reaper("a", connection=c), Reaper("b", connection=c)
    assert first.tick() is not None
    assert second.tick() is None  # the lock is held for the rest of the interval
    assert 0 < c.ttl(worker.REAPER_LOCK_KEY) <= worker.REAPER_INTERVAL_S - 5
    c.delete(worker.REAPER_LOCK_KEY)
    assert second.tick() is not None


def test_a_failing_pass_never_kills_the_loop(monkeypatch):
    c = fakeredis.FakeRedis(server=fakeredis.FakeServer())

    async def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "reap", boom)
    assert Reaper("a", connection=c).tick() is None


@pytest.mark.parametrize("burst, started", [(False, True), (True, False)])
def test_long_running_worker_starts_the_reaper(monkeypatch, burst, started):
    calls = []

    class FakeReaper:
        def __init__(self, name):
            calls.append(("init", name))

        def start(self):
            calls.append("start")
            return self

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(worker, "Reaper", FakeReaper)
    monkeypatch.setattr(Worker, "work", lambda self, *a, **kw: True)
    w = LorekeeperWorker(["interactive"], connection=fakeredis.FakeRedis())
    assert w.work(burst=burst) is True
    assert calls == ([("init", w.name), "start", "stop"] if started else [])


# ── A real work horse, killed mid-Job ──────────────────────────────────────

@pytest.mark.skipif(not VALKEY_TEST_URL, reason="VALKEY_TEST_URL not set")
def test_killed_work_horse_is_recovered_and_the_job_runs_once(monkeypatch):
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    c = redis.Redis.from_url(VALKEY_TEST_URL)
    _empty(c)
    outbox.set_connection(c)

    async def in_db(fn):
        engine = create_async_engine(TEST_DB_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    async def setup(s):
        await s.execute(sa.update(Job).where(Job.status.in_(["queued", "running"])).values(status="cancelled"))
        await s.commit()
        camp = await _campaign(s)
        ctx = await ctx_for(s, camp.user_id, camp.id)
        job_id = await enqueue(s, ctx, "test_r.crash_once", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
        await s.commit()
        return job_id

    try:
        job_id = asyncio.run(in_db(setup))
        killed = {}

        def killer():
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                row = asyncio.run(in_db(lambda s: _row(s, job_id)))
                if row.stage and row.stage.startswith("pid:"):
                    killed["pid"] = int(row.stage[4:])
                    os.kill(killed["pid"], signal.SIGKILL)
                    return
                time.sleep(0.2)

        t = threading.Thread(target=killer)
        t.start()
        LorekeeperWorker([q.value for q in JobQueue], connection=c).work(burst=True)
        t.join(35)
        assert killed and killed["pid"] != os.getpid()

        row = asyncio.run(in_db(lambda s: _row(s, job_id)))
        assert row.status == JobStatus.RUNNING and row.attempts == 1  # left behind by the dead horse

        async def age_heartbeat(s):
            await s.execute(sa.update(Job).where(Job.id == job_id)
                            .values(heartbeat_at=_now() - timedelta(seconds=61)))
            await s.commit()
            return await reap(async_sessionmaker(s.bind, expire_on_commit=False), c)

        result = asyncio.run(in_db(age_heartbeat))
        assert result.requeued == [job_id] and result.pushed == [job_id]
        LorekeeperWorker([q.value for q in JobQueue], connection=c).work(burst=True)
        row = asyncio.run(in_db(lambda s: _row(s, job_id)))
        assert row.status == JobStatus.DONE and row.attempts == 2
        n = asyncio.run(in_db(lambda s: s.scalar(sa.select(sa.func.count()).select_from(Job)
                                                 .where(Job.idempotency_key == row.idempotency_key))))
        assert n == 1
    finally:
        outbox.set_connection(None)
        _empty(c)
        c.close()
