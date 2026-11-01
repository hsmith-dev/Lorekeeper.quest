"""E0-Jobs.2: `enqueue`, the after-commit outbox, the kind registry and the
minimal `run_job` wrapper, against the story's I/O matrix.

Two dispatch modes:
* eager (the suite default, conftest sets JOBS_EAGER=1): the Job runs inside
  `commit()`, so the row is final when commit returns;
* RQ (`rq_conn` fixture): eager off, pushes go to fakeredis, and to a real
  Valkey too when VALKEY_TEST_URL is set (as in CI).

These tests commit (the outbox only acts on commit), so every key and
Campaign is unique per test.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

import fakeredis
import pytest
import pytest_asyncio
import redis
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from rq import Queue
from rq.job import Job as RQJob
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access.context import MEMBER_VIEW, CampaignContext, audience_ctx, ctx_for, require_campaign
from app.access.identity import get_current_user
from app.core.config import get_settings
from app.core.errors import LLMConfigError
from app.db.models import Campaign, Genre, Job, User
from app.db.session import get_db
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs import enqueue, job_accepted, outbox
from app.jobs.enqueue import is_secret_key
from app.jobs.registry import KINDS, SYSTEM_NOOP, JobKind, get_kind, register
from app.jobs.worker import run_job
from app.services import llm_provider

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")
PERFORM = "app.jobs.worker.perform"

# ── Test-local kinds ───────────────────────────────────────────────────────

SEEN: dict[uuid.UUID, JobStatus | None] = {}


async def record_handler(job, ctx, db):
    SEEN[job.id] = job.dependency_status


async def failing_handler(job, ctx, db):
    raise RuntimeError("boom")


async def llm_config_handler(job, ctx, db):
    raise LLMConfigError("No AI model is configured for your account")


register(JobKind(name="test.record", queue=JobQueue.ONSAVE, timeout_s=5, handler=f"{__name__}:record_handler"))
register(JobKind(name="test.fail", queue=JobQueue.INTERACTIVE, timeout_s=5, handler=f"{__name__}:failing_handler"))
register(JobKind(name="test.llm_config", queue=JobQueue.INTERACTIVE, timeout_s=5,
                 handler=f"{__name__}:llm_config_handler"))


# ── Fixtures ───────────────────────────────────────────────────────────────

def _key() -> str:
    return f"test:{uuid.uuid4().hex}"


def _user(label: str) -> User:
    return User(email=f"enqueue-{label}-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                display_name=label, access_granted=True, access_source="promo")


async def _campaign(db) -> Campaign:
    owner = _user("owner")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Enqueue", genre=Genre.fantasy)
    db.add(c)
    await db.flush()
    return c


@pytest_asyncio.fixture
async def campaign(db) -> Campaign:
    return await _campaign(db)


@pytest_asyncio.fixture
async def ctx(db, campaign) -> CampaignContext:
    return await ctx_for(db, campaign.user_id, campaign.id)


@pytest.fixture(params=["fake", "real"])
def rq_conn(request, monkeypatch):
    """Eager off; pushes go to this connection."""
    if request.param == "fake":
        conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    else:
        if not VALKEY_TEST_URL:
            pytest.skip("VALKEY_TEST_URL not set")
        conn = redis.Redis.from_url(VALKEY_TEST_URL)
    for q in JobQueue:
        Queue(q.value, connection=conn).empty()
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(conn)
    yield conn
    outbox.set_connection(None)
    for q in JobQueue:
        Queue(q.value, connection=conn).empty()
    conn.close()


def queued(conn, queue: JobQueue | str = JobQueue.INTERACTIVE) -> list[str]:
    return Queue(JobQueue(queue).value, connection=conn).job_ids


async def _row(db, job_id: uuid.UUID) -> Job | None:
    return (await db.execute(
        sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def _count(db, key: str) -> int:
    return await db.scalar(sa.select(sa.func.count()).select_from(Job).where(Job.idempotency_key == key))


async def _total(db) -> int:
    return await db.scalar(sa.select(sa.func.count()).select_from(Job))


def _queued_job(c: Campaign, status: JobStatus = JobStatus.QUEUED) -> Job:
    """A row written directly (not via enqueue): a dependency whose status
    the test controls."""
    return Job(campaign_id=c.id, kind="system.noop", queue=JobQueue.INTERACTIVE, status=status,
               idempotency_key=_key(), ctx_kind="gm", ctx_user_id=c.user_id, created_by=c.user_id)


# ── Registry ───────────────────────────────────────────────────────────────

def test_system_noop_is_registered():
    kind = get_kind("system.noop")
    assert kind is SYSTEM_NOOP and KINDS["system.noop"] is kind
    assert kind.queue == JobQueue.INTERACTIVE and kind.timeout_s > 0
    assert kind.resources == frozenset() and kind.result_audience == "gm"
    assert callable(kind.load_handler())


@pytest.mark.parametrize("over", [
    {"queue": "urgent"},
    {"timeout_s": 0},
    {"timeout_s": -1},
    {"timeout_s": True},
    {"resources": frozenset({"gpu"})},
    {"result_audience": "players"},
    {"handler": "no_colon"},
    {"name": "NoDots"},
    {"name": "x." + "a" * 70},
    {"live_safe": "yes"},
])
def test_job_kind_validation(over):
    values = dict(name="test.bad", queue=JobQueue.BACKFILL, timeout_s=10, handler="app.jobs.builtin:noop")
    values.update(over)
    with pytest.raises(ValueError):
        JobKind(**values)


def test_register_conflict_and_unknown_kind():
    register(JobKind(name="test.record", queue=JobQueue.ONSAVE, timeout_s=5,
                     handler=f"{__name__}:record_handler"))  # identical: no-op
    with pytest.raises(ValueError):
        register(JobKind(name="test.record", queue=JobQueue.BACKFILL, timeout_s=5,
                         handler=f"{__name__}:record_handler"))
    with pytest.raises(ValueError):
        get_kind("test.never_registered")


# ── Secret keys ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "api_key", "apikey", "apiKey", "APIKey", "X-Api-Key", "openai_api_key", "token", "accessToken",
    "ACCESS_TOKEN", "refresh-token", "password", "Password", "db_passwd", "secret", "clientSecret",
])
def test_secret_keys(key):
    assert is_secret_key(key)


@pytest.mark.parametrize("key", ["max_tokens", "maxTokens", "tokens", "key", "api", "journal_id", "tokenizer"])
def test_non_secret_keys(key):
    assert not is_secret_key(key)


# ── Bad input: ValueError, nothing written ─────────────────────────────────

@pytest.mark.parametrize("kind, payload, key", [
    ("test.unknown", {}, "k"),
    ("system.noop", ["not", "a", "dict"], "k"),
    ("system.noop", {"when": object()}, "k"),
    ("system.noop", {"x": float("nan")}, "k"),
    ("system.noop", {"api_key": "sk-1"}, "k"),
    ("system.noop", {"a": {"accessToken": "t"}}, "k"),
    ("system.noop", {"items": [{"ok": 1}, {"Password": "p"}]}, "k"),
    ("system.noop", {}, None),
    ("system.noop", {}, ""),
    ("system.noop", {}, "   "),
])
async def test_bad_input_raises_before_any_write(db, ctx, kind, payload, key):
    before = await _total(db)
    with pytest.raises(ValueError):
        await enqueue(db, ctx, kind, payload, idempotency_key=key)
    assert not db.new
    assert await _total(db) == before


async def test_max_tokens_is_allowed(db, ctx, rq_conn):
    job_id = await enqueue(db, ctx, "system.noop", {"max_tokens": 512}, idempotency_key=_key())
    assert (await _row(db, job_id)).payload == {"max_tokens": 512}


async def test_reduced_ctx_is_refused(db, ctx):
    member_view = audience_ctx(ctx.campaign_id, MEMBER_VIEW, by=ctx)
    before = await _total(db)
    with pytest.raises(ValueError):
        await enqueue(db, member_view, "system.noop", {}, idempotency_key=_key())
    assert await _total(db) == before


# ── RQ push ────────────────────────────────────────────────────────────────

async def test_happy_path_pushes_only_the_job_id(db, ctx, rq_conn):
    job_id = await enqueue(db, ctx, "system.noop", {"n": 1}, idempotency_key=_key())
    assert queued(rq_conn) == []  # nothing before commit
    await db.commit()
    assert queued(rq_conn) == [str(job_id)]
    rq_job = RQJob.fetch(str(job_id), connection=rq_conn)
    assert rq_job.func_name == PERFORM
    assert rq_job.args == (str(job_id),) and rq_job.kwargs == {}
    assert rq_job.result_ttl == 0
    assert rq_job.retries_left is None
    # RQ's kill is a backstop above the kind's timeout_s (the wrapper owns timeouts).
    assert rq_job.timeout == SYSTEM_NOOP.timeout_s + outbox.RQ_TIMEOUT_GRACE_S
    row = await _row(db, job_id)
    assert row.status == JobStatus.QUEUED and row.queue == JobQueue.INTERACTIVE


async def test_queue_comes_from_the_registry(db, ctx, rq_conn):
    job_id = await enqueue(db, ctx, "test.record", {}, idempotency_key=_key())
    await db.commit()
    assert queued(rq_conn, JobQueue.ONSAVE) == [str(job_id)]
    assert queued(rq_conn, JobQueue.INTERACTIVE) == []


async def test_stored_ctx(db, ctx, rq_conn):
    key = _key()
    job_id = await enqueue(db, ctx, "system.noop", {"a": [1, 2]}, idempotency_key=key)
    await db.commit()
    row = await _row(db, job_id)
    assert row.campaign_id == ctx.campaign_id and row.kind == "system.noop"
    assert row.ctx_kind == ctx.role == "gm"
    assert row.ctx_user_id == row.created_by == ctx.user_id
    assert row.ctx_audience == ctx.audience.level.value
    assert row.access_epoch == ctx.access_epoch
    assert row.idempotency_key == key and row.payload == {"a": [1, 2]}
    assert row.depends_on_job_id is None


async def test_rollback_writes_and_pushes_nothing(db, ctx, rq_conn):
    key = _key()
    job_id = await enqueue(db, ctx, "system.noop", {}, idempotency_key=key)
    await db.rollback()
    assert await _row(db, job_id) is None
    # A later commit on the same session must not push the rolled-back id.
    await _campaign(db)
    await db.commit()
    assert queued(rq_conn) == []


async def test_savepoint_rollback_drops_only_its_jobs(db, ctx, rq_conn):
    a = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
    b_key = _key()
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            await enqueue(db, ctx, "system.noop", {}, idempotency_key=b_key)
            raise RuntimeError("roll the savepoint back")
    await db.commit()
    assert queued(rq_conn) == [str(a)]
    assert await _count(db, b_key) == 0


async def test_savepoint_release_waits_for_the_outer_commit(db, ctx, rq_conn):
    async with db.begin_nested():
        b = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
    assert queued(rq_conn) == []  # released, not committed
    await db.commit()
    assert queued(rq_conn) == [str(b)]


async def test_push_failure_is_logged_and_swallowed(db, ctx, monkeypatch, caplog):
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2))
    try:
        job_id = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
        with caplog.at_level(logging.ERROR, logger="app.jobs.outbox"):
            await db.commit()  # must not raise
    finally:
        outbox.set_connection(None)
    assert (await _row(db, job_id)).status == JobStatus.QUEUED
    assert any("push failed" in r.getMessage() for r in caplog.records)


async def test_worker_wrapper_runs_a_pushed_job(db, ctx, rq_conn):
    job_id = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
    await db.commit()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    assert await run_job(job_id, factory, "test-worker") == JobStatus.DONE
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and row.attempts == 1 and row.worker_id == "test-worker"
    assert row.started_at is not None and row.finished_at is not None
    # A second delivery of the same message does nothing.
    assert await run_job(job_id, factory, "test-worker") is None


# ── Idempotency ────────────────────────────────────────────────────────────

async def test_dedupe_returns_the_active_job(db, ctx, rq_conn):
    key = _key()
    first = await enqueue(db, ctx, "system.noop", {}, idempotency_key=key)
    assert await enqueue(db, ctx, "system.noop", {"other": 1}, idempotency_key=key) == first
    await db.commit()
    assert await enqueue(db, ctx, "system.noop", {}, idempotency_key=key) == first
    await db.commit()
    assert await _count(db, key) == 1
    assert queued(rq_conn) == [str(first)]


async def test_key_reusable_after_done(db, ctx):
    key = _key()
    first = await enqueue(db, ctx, "system.noop", {}, idempotency_key=key)
    await db.commit()
    assert (await _row(db, first)).status == JobStatus.DONE
    second = await enqueue(db, ctx, "system.noop", {}, idempotency_key=key)
    await db.commit()
    assert second != first
    assert await _count(db, key) == 2


async def test_cross_campaign_key_is_refused_without_revealing_the_job(db, ctx, rq_conn):
    key = _key()
    other = await _campaign(db)
    other_ctx = await ctx_for(db, other.user_id, other.id)
    theirs = await enqueue(db, other_ctx, "system.noop", {}, idempotency_key=key)
    await db.commit()
    with pytest.raises(ValueError) as exc:
        await enqueue(db, ctx, "system.noop", {}, idempotency_key=key)
    assert str(theirs) not in str(exc.value)
    assert await _count(db, key) == 1


async def test_concurrent_enqueue_resolves_to_one_job(db, rq_conn):
    """Two sessions race one key: the loser's insert hits the unique index,
    its savepoint rolls back, and the re-select returns the winner's id."""
    c = await _campaign(db)
    await db.commit()
    key = _key()
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    async with factory() as a, factory() as b:
        ctx_a = await ctx_for(a, c.user_id, c.id)
        ctx_b = await ctx_for(b, c.user_id, c.id)
        winner = await enqueue(a, ctx_a, "system.noop", {}, idempotency_key=key)  # inserted, uncommitted
        loser = asyncio.create_task(enqueue(b, ctx_b, "system.noop", {}, idempotency_key=key))
        await asyncio.sleep(0.2)  # b is blocked on the unique index
        assert not loser.done()
        await a.commit()
        assert await asyncio.wait_for(loser, 5) == winner
        await b.commit()
    assert await _count(db, key) == 1
    assert queued(rq_conn) == [str(winner)]


# ── Eager ──────────────────────────────────────────────────────────────────

async def test_eager_row_is_done_after_commit(db, ctx):
    job_id = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
    await db.commit()
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE
    assert row.error_code is None and row.finished_at is not None and row.attempts == 1


async def test_eager_failing_handler_is_a_failed_row(db, ctx):
    job_id = await enqueue(db, ctx, "test.fail", {}, idempotency_key=_key())
    await db.commit()  # must not raise
    row = await _row(db, job_id)
    assert row.status == JobStatus.FAILED
    assert row.error_code == JobErrorCode.INTERNAL
    assert row.error_message and "boom" not in row.error_message


async def test_eager_llm_error_keeps_its_code(db, ctx):
    job_id = await enqueue(db, ctx, "test.llm_config", {}, idempotency_key=_key())
    await db.commit()
    row = await _row(db, job_id)
    assert row.status == JobStatus.FAILED
    assert row.error_code == JobErrorCode.LLM_CONFIG
    assert row.error_message == "No AI model is configured for your account"


# ── Dependencies ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("final", [JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED])
async def test_eager_dependent_waits_then_runs(db, ctx, campaign, final):
    dep = _queued_job(campaign)
    db.add(dep)
    await db.commit()
    job_id = await enqueue(db, ctx, "test.record", {}, idempotency_key=_key(), depends_on_job_id=dep.id)
    await db.commit()
    row = await _row(db, job_id)
    assert row.status == JobStatus.QUEUED and row.depends_on_job_id == dep.id
    assert job_id not in SEEN

    dep = await _row(db, dep.id)
    dep.status = final
    await db.commit()
    assert (await _row(db, job_id)).status == JobStatus.DONE
    assert SEEN[job_id] == final


async def test_rq_dependent_is_pushed_when_the_dependency_finishes(db, ctx, campaign, rq_conn):
    dep_id = await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key())
    await db.commit()
    job_id = await enqueue(db, ctx, "test.record", {}, idempotency_key=_key(), depends_on_job_id=dep_id)
    await db.commit()
    assert queued(rq_conn, JobQueue.ONSAVE) == []

    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    assert await run_job(dep_id, factory, "test-worker") == JobStatus.DONE
    assert queued(rq_conn, JobQueue.ONSAVE) == [str(job_id)]
    assert await run_job(job_id, factory, "test-worker") == JobStatus.DONE
    assert SEEN[job_id] == JobStatus.DONE


async def test_terminal_dependency_pushes_at_once(db, ctx, campaign, rq_conn):
    dep = _queued_job(campaign, JobStatus.FAILED)
    db.add(dep)
    await db.flush()
    job_id = await enqueue(db, ctx, "test.record", {}, idempotency_key=_key(), depends_on_job_id=dep.id)
    await db.commit()
    assert queued(rq_conn, JobQueue.ONSAVE) == [str(job_id)]


async def test_eager_terminal_dependency_runs_at_once(db, ctx, campaign):
    dep = _queued_job(campaign, JobStatus.DONE)
    db.add(dep)
    await db.flush()
    job_id = await enqueue(db, ctx, "test.record", {}, idempotency_key=_key(), depends_on_job_id=str(dep.id))
    await db.commit()
    assert (await _row(db, job_id)).status == JobStatus.DONE
    assert SEEN[job_id] == JobStatus.DONE


@pytest.mark.parametrize("which", ["unknown", "not_a_uuid", "other_campaign"])
async def test_bad_dependency_is_refused(db, ctx, which):
    if which == "unknown":
        dep = uuid.uuid4()
    elif which == "not_a_uuid":
        dep = "nope"
    else:
        other = await _campaign(db)
        row = _queued_job(other)
        db.add(row)
        await db.flush()
        dep = row.id
    before = await _total(db)
    with pytest.raises(ValueError):
        await enqueue(db, ctx, "system.noop", {}, idempotency_key=_key(), depends_on_job_id=dep)
    assert await _total(db) == before


# ── The 202 route ──────────────────────────────────────────────────────────

async def test_route_returns_202_and_does_no_model_work(db, campaign):
    owner = await db.get(User, campaign.user_id)
    test_app = FastAPI()

    @test_app.post("/t/{campaign_id}/noop", status_code=202)
    async def start(ctx: CampaignContext = Depends(require_campaign("gm")), session=Depends(get_db)):
        job_id = await enqueue(session, ctx, "system.noop", {}, idempotency_key=f"noop:{uuid.uuid4().hex}")
        await session.commit()
        return job_accepted(job_id)

    test_app.dependency_overrides[get_db] = lambda: db
    test_app.dependency_overrides[get_current_user] = lambda: owner
    with llm_provider.capture() as cap:
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
            started = time.monotonic()
            resp = await client.post(f"/t/{campaign.id}/noop")
            elapsed = time.monotonic() - started
    assert resp.status_code == 202, resp.text
    assert set(resp.json()) == {"job_id"}
    assert elapsed < 1.0
    assert cap.calls == []
    row = await _row(db, uuid.UUID(resp.json()["job_id"]))
    assert row.status == JobStatus.DONE
