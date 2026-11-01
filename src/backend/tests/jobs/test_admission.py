"""E0-Jobs.5: admission (resource leases, the Live Session hold) and the
delayed set, on fakeredis and, as `real`, the CI Valkey (VALKEY_TEST_URL).

Rows are written directly and run with `run_job` (the same wrapper the RQ
worker uses), with eager dispatch off, so a deferral's delayed push is
observable on the RQ connection.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
import redis
import redis.asyncio as aioredis
import sqlalchemy as sa
from rq import Queue

from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.core.valkey_client import get_valkey, set_valkey
from app.db.models import Campaign, Genre, Job, User
from app.db.models.user_settings import UserSettings
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs import admission, outbox, registry, worker
from app.jobs.admission import DELAYED_KEY, PAUSED_STAGE, WAITING_STAGE, Deferral
from app.jobs.registry import JobKind, register
from app.jobs.worker import Reaper, run_job

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")
REPO = Path(__file__).resolve().parents[4]

SEEN: dict[uuid.UUID, dict] = {}


async def record(job, ctx, db):
    vk = get_valkey()
    SEEN[job.id] = {"res": {r: await vk.get(f"res:{r}") for r in sorted(registry.RESOURCES)}}


async def hold_then_record(job, ctx, db):
    """Waits until the test lets it go (so two Jobs overlap)."""
    SEEN[job.id] = {"started": True}
    await asyncio.sleep(0.3)


async def outcome(job, ctx, db):
    then = job.payload.get("then")
    if then == "stolen":  # the lease lapsed and another Job took it mid-run
        await get_valkey().set("res:nli", "other-job")
    if then == "retryable":
        raise RuntimeError("boom")
    if then == "terminal":
        raise StructuredOutputError("bad", attempts=1, errors=[])


async def plain(job, ctx, db):
    SEEN[job.id] = {"ran": True}


def _kind(name, handler, resources=(), **kw):
    return register(JobKind(name=name, queue=kw.pop("queue", JobQueue.ONSAVE), timeout_s=30,
                            handler=f"{__name__}:{handler}", resources=frozenset(resources), **kw))


_kind("test_a.nli", "hold_then_record", {"nli"})
_kind("test_a.nli_llm", "record", {"nli", "llm"})
_kind("test_a.outcome", "outcome", {"nli"})
_kind("test_a.llm", "record", {"llm"})
_kind("test_a.llm_safe", "record", {"llm"}, live_safe=True)
_kind("test_a.ocr", "record", {"ocr"})
_kind("test_a.none", "record")
_kind("test_a.heavy", "record", {"cpu_heavy", "stt"})
_kind("test_a.heavy_plain", "plain", {"cpu_heavy", "stt"})


# ── Fixtures ───────────────────────────────────────────────────────────────

def _clean(sync) -> None:
    for q in JobQueue:
        Queue(q.value, connection=sync).empty()
    keys = [k for pattern in ("res:*", "lease:*") for k in sync.keys(pattern)]
    if keys:
        sync.delete(*keys)
    sync.delete(DELAYED_KEY, admission.HOLD_TTLS_KEY, worker.REAPER_LOCK_KEY)


@pytest.fixture(params=["fake", "real"])
async def vk(request, monkeypatch):
    """(sync RQ connection, async Valkey client) on one server; eager off.
    The async client is the process-wide one (leases, holds); the sync one
    is RQ's (pushes, the delayed set)."""
    if request.param == "fake":
        server = fakeredis.FakeServer()
        sync = fakeredis.FakeRedis(server=server)
        client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    else:
        if not VALKEY_TEST_URL:
            pytest.skip("VALKEY_TEST_URL not set")
        sync = redis.Redis.from_url(VALKEY_TEST_URL)
        client = aioredis.from_url(VALKEY_TEST_URL, decode_responses=True)
    _clean(sync)
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(sync)
    previous = set_valkey(client)
    yield sync, client
    set_valkey(previous)
    outbox.set_connection(None)
    _clean(sync)
    await client.aclose()
    sync.close()


@pytest.fixture(autouse=True)
async def only_this_tests_jobs(db):
    await db.execute(sa.update(Job).where(Job.status.in_(["queued", "running"])).values(status="cancelled"))
    await db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _campaign(db, *, llm: bool = False) -> Campaign:
    owner = User(email=f"adm-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                 display_name="owner", access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Admission", genre=Genre.fantasy)
    db.add(c)
    if llm:
        db.add(UserSettings(user_id=owner.id, llm_provider="openai", llm_api_key="sk-test", llm_model="gpt-x"))
    await db.commit()
    return c


async def _job(db, c: Campaign, kind: str, **kw) -> Job:
    row = Job(campaign_id=c.id, kind=kind, queue=registry.get_kind(kind).queue,
              idempotency_key=f"test:{uuid.uuid4().hex}", ctx_kind="gm", ctx_user_id=c.user_id,
              created_by=c.user_id, access_epoch=0, **{"payload": {}, **kw})
    db.add(row)
    await db.commit()
    return row


async def _row(db, job_id) -> Job:
    return (await db.execute(
        sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )).scalar_one()


def _factory(db):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(db.bind, expire_on_commit=False)


def _close_to(value: datetime, expected: datetime, slack_s: float = 3) -> bool:
    return abs((value - expected).total_seconds()) <= slack_s


def _delayed(sync) -> dict[str, float]:
    return {(m.decode() if isinstance(m, bytes) else m): s
            for m, s in sync.zrange(DELAYED_KEY, 0, -1, withscores=True)}


# ── Resource leases ────────────────────────────────────────────────────────

async def test_two_nli_jobs_at_once_one_waits_for_the_model(db, vk):
    sync, client = vk
    c = await _campaign(db)
    a, b = await _job(db, c, "test_a.nli"), await _job(db, c, "test_a.nli")
    first = asyncio.create_task(run_job(a.id, _factory(db), "w1"))
    while a.id not in SEEN:  # a holds res:nli and is running
        await asyncio.sleep(0.02)
    assert await run_job(b.id, _factory(db), "w2") == JobStatus.QUEUED
    assert await first == JobStatus.DONE

    ra, rb = await _row(db, a.id), await _row(db, b.id)
    assert ra.status == JobStatus.DONE
    assert rb.status == JobStatus.QUEUED and rb.attempts == 0 and rb.stage == WAITING_STAGE
    assert _close_to(rb.next_run_at, _now() + timedelta(seconds=5))
    assert rb.worker_id is None and rb.heartbeat_at is None and rb.started_at is None and rb.progress is None
    assert b.id not in SEEN
    member = f"{b.id}|onsave|test_a.nli"
    assert _delayed(sync) == {member: pytest.approx(rb.next_run_at.timestamp(), abs=0.01)}
    assert await client.get("res:nli") is None  # a's lease went with its outcome


async def test_a_waiting_job_runs_once_the_lease_is_free(db, vk):
    sync, client = vk
    c = await _campaign(db)
    row = await _job(db, c, "test_a.nli")
    await client.set("res:nli", "someone-else")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    await client.delete("res:nli")
    await db.execute(sa.update(Job).where(Job.id == row.id).values(next_run_at=_now()))
    await db.commit()
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    r = await _row(db, row.id)
    assert r.attempts == 1  # the wait never counted as an attempt
    assert r.stage is None  # the waiting stage ended when it ran


async def test_only_the_leased_resources_are_taken(db, vk):
    sync, client = vk
    c = await _campaign(db, llm=True)
    row = await _job(db, c, "test_a.nli_llm")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    res = SEEN[row.id]["res"]
    assert res["nli"] == str(row.id)
    assert res["llm"] is None  # llm is E0-LLM's llm_slot, never leased here
    assert await client.get("res:nli") is None


async def test_every_resource_of_a_multi_lease_kind_is_taken_or_none(db, vk):
    sync, client = vk
    c = await _campaign(db)
    await client.set("res:stt", "someone-else")
    row = await _job(db, c, "test_a.heavy")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    assert await client.get("res:cpu_heavy") is None  # given back
    assert await client.get("res:stt") == "someone-else"
    await client.delete("res:stt")
    await db.execute(sa.update(Job).where(Job.id == row.id).values(next_run_at=None))
    await db.commit()
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    assert SEEN[row.id]["res"]["cpu_heavy"] == str(row.id) and SEEN[row.id]["res"]["stt"] == str(row.id)


@pytest.mark.parametrize("then, status", [(None, JobStatus.DONE), ("retryable", JobStatus.QUEUED),
                                          ("terminal", JobStatus.FAILED)])
async def test_the_lease_is_released_after_any_outcome(db, vk, then, status):
    sync, client = vk
    c = await _campaign(db)
    row = await _job(db, c, "test_a.outcome", payload={"then": then})
    assert await run_job(row.id, _factory(db), "w") == status
    assert await client.get("res:nli") is None
    if then == "retryable":
        r = await _row(db, row.id)
        assert r.attempts == 1 and r.error_code == JobErrorCode.INTERNAL


async def test_another_jobs_lease_is_never_deleted(db, vk):
    sync, client = vk
    c = await _campaign(db)
    row = await _job(db, c, "test_a.outcome", payload={"then": "stolen"})
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    assert await client.get("res:nli") == "other-job"


async def test_lease_ttl_is_rq_timeout(db, vk):
    sync, client = vk
    kind = registry.get_kind("test_a.nli")
    assert await admission.acquire_resources(uuid.uuid4(), kind) == ["nli"]
    ttl = await client.ttl("res:nli")
    assert outbox.rq_timeout(kind.name) - 2 <= ttl <= outbox.rq_timeout(kind.name) == kind.timeout_s + 60


# ── Live Sessions ──────────────────────────────────────────────────────────

async def test_hold_renew_release(vk):
    sync, client = vk
    assert await admission.renew("live") is False  # never held
    assert await admission.hold("live", 90) is True
    assert await admission.is_held("live")
    assert 85 <= await client.ttl("lease:live") <= 90
    await client.expire("lease:live", 5)
    assert await admission.renew("live") is True
    assert await client.ttl("lease:live") > 85  # its stored TTL
    assert await admission.hold("live", 90) is True  # a second session: refreshes, not exclusive
    await admission.release("live")
    assert not await admission.is_held("live")
    assert await admission.renew("live") is True  # the other session's renew sets it again
    assert await admission.is_held("live")
    with pytest.raises(ValueError):
        await admission.hold("live", 0)


async def test_a_live_session_pauses_a_non_safe_llm_kind(db, vk):
    sync, client = vk
    c = await _campaign(db, llm=True)
    await admission.hold("live", 90)
    row = await _job(db, c, "test_a.llm")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    r = await _row(db, row.id)
    assert r.stage == PAUSED_STAGE and r.attempts == 0
    assert _close_to(r.next_run_at, _now() + timedelta(seconds=15))
    assert row.id not in SEEN
    assert f"{row.id}|onsave|test_a.llm" in _delayed(sync)


async def test_live_pause_is_checked_before_resource_leases(db, vk):
    sync, client = vk
    c = await _campaign(db)
    await admission.hold("live", 90)
    await client.set("res:nli", "someone-else")
    row = await _job(db, c, "test_a.nli")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    assert (await _row(db, row.id)).stage == PAUSED_STAGE


@pytest.mark.parametrize("kind", ["test_a.llm_safe", "test_a.ocr", "test_a.none"])
async def test_live_safe_and_unaffected_kinds_run_during_a_live_session(db, vk, kind):
    sync, client = vk
    c = await _campaign(db, llm=True)
    await admission.hold("live", 90)
    row = await _job(db, c, kind)
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE


@pytest.mark.parametrize("how", ["released", "expired"])
async def test_a_lapsed_live_session_no_longer_pauses(db, vk, how):
    sync, client = vk
    c = await _campaign(db, llm=True)
    if how == "released":
        await admission.hold("live", 90)
        await admission.release("live")
    else:
        await admission.hold("live", 1)
        await asyncio.sleep(1.2)
    row = await _job(db, c, "test_a.llm")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE


async def test_a_deferral_keeps_a_previous_retrys_error(db, vk):
    sync, client = vk
    c = await _campaign(db)
    await client.set("res:nli", "someone-else")
    row = await _job(db, c, "test_a.nli", attempts=1, error_code=JobErrorCode.LLM_BUSY, error_message="busy")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    r = await _row(db, row.id)
    assert r.attempts == 1 and r.error_code == JobErrorCode.LLM_BUSY and r.error_message == "busy"


# ── The delayed set ────────────────────────────────────────────────────────

async def test_drain_pushes_what_is_due_once_with_a_distinct_rq_id(vk):
    sync, client = vk
    due_id, later_id = uuid.uuid4(), uuid.uuid4()
    admission.defer_push(due_id, JobQueue.ONSAVE, "test_a.nli", _now() - timedelta(seconds=1))
    admission.defer_push(later_id, JobQueue.ONSAVE, "test_a.nli", _now() + timedelta(seconds=60))
    assert admission.drain_delayed(sync) == [due_id]
    ids = Queue("onsave", connection=sync).job_ids
    assert len(ids) == 1 and re.fullmatch(rf"{due_id}_[0-9a-f]+", ids[0])
    assert outbox.job_id_of(ids[0]) == str(due_id)
    assert admission.drain_delayed(sync) == []  # pushed once
    assert list(_delayed(sync)) == [f"{later_id}|onsave|test_a.nli"]  # not yet due: stays


async def test_a_failed_delayed_push_is_put_back(vk, monkeypatch):
    sync, client = vk
    job_id = uuid.uuid4()
    admission.defer_push(job_id, JobQueue.ONSAVE, "test_a.nli", _now() - timedelta(seconds=1))

    def broken(*a, **kw):
        raise redis.ConnectionError("gone")

    monkeypatch.setattr(outbox, "push", broken)
    assert admission.drain_delayed(sync) == []
    assert list(_delayed(sync)) == [f"{job_id}|onsave|test_a.nli"]


async def test_the_reaper_thread_drains_the_delayed_set_every_second(db, vk, monkeypatch):
    from tests.conftest import TEST_DB_URL

    sync, client = vk
    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    monkeypatch.setattr(worker, "reap", _no_reap)
    job_id = uuid.uuid4()
    reaper = Reaper("drainer", connection=sync).start()
    try:
        await asyncio.sleep(0.2)  # the first pass has run; the next is 30 s away
        admission.defer_push(job_id, JobQueue.ONSAVE, "test_a.nli", _now())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not Queue("onsave", connection=sync).job_ids:
            await asyncio.sleep(0.1)
    finally:
        reaper.stop()
    assert [outbox.job_id_of(i) for i in Queue("onsave", connection=sync).job_ids] == [str(job_id)]


async def _no_reap(*a, **kw):
    return worker.ReapResult()


async def test_under_jobs_eager_a_deferral_is_not_pushed(db, vk, monkeypatch):
    sync, client = vk
    monkeypatch.setattr(get_settings(), "jobs_eager", True)
    c = await _campaign(db)
    await client.set("res:nli", "someone-else")
    row = await _job(db, c, "test_a.nli")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    assert (await _row(db, row.id)).status == JobStatus.QUEUED
    assert _delayed(sync) == {}


async def test_the_reaper_maps_distinct_rq_ids_back_to_the_job(db, vk):
    sync, client = vk
    c = await _campaign(db)
    row = await _job(db, c, "test_a.none")
    await db.execute(sa.update(Job).where(Job.id == row.id).values(created_at=_now() - timedelta(seconds=120)))
    await db.commit()
    outbox.push(row.id, JobQueue.ONSAVE, "test_a.none", sync, rq_id=outbox.distinct_rq_id(row.id))
    assert (await worker.reap(_factory(db), sync)).pushed == []  # RQ holds it under another id


# ── Valkey unavailable ─────────────────────────────────────────────────────

async def test_without_valkey_admission_fails_open(db, monkeypatch, caplog):
    previous = set_valkey(None)
    try:
        c = await _campaign(db)
        row = await _job(db, c, "test_a.heavy_plain")
        with caplog.at_level(logging.WARNING, logger="app.jobs.admission"):
            assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
        assert any("admitting" in r.getMessage() for r in caplog.records)
        assert await admission.admit(uuid.uuid4(), registry.get_kind("test_a.llm")) == []
        assert await admission.hold("live", 90) is False
        assert await admission.renew("live") is False
        await admission.release("live")  # a logged no-op
    finally:
        set_valkey(previous)


async def test_a_redis_error_also_fails_open(monkeypatch):
    class Broken:
        async def exists(self, *a):
            raise redis.ConnectionError("down")

        async def set(self, *a, **kw):
            raise redis.ConnectionError("down")

    previous = set_valkey(Broken())
    try:
        assert await admission.admit(uuid.uuid4(), registry.get_kind("test_a.heavy")) == []
        assert not isinstance(await admission.admit(uuid.uuid4(), registry.get_kind("test_a.llm")), Deferral)
    finally:
        set_valkey(previous)


# ── Never `rq suspend` ─────────────────────────────────────────────────────

_SUSPEND = re.compile(r"rq\s+suspend|rq\.suspension|\bsuspend\s*\(\s*(conn|connection|redis)")
_SCANNED = ("src/backend/app", "src/backend/scripts", "scripts", "docker-compose.yml", "docker-compose.dev.yml",
            "docker-compose.prod.yml", ".github", "nginx", "src/backend/Dockerfile", "src/backend/Dockerfile.prod")


def test_nothing_suspends_rq():
    """AD-5: pausing RQ (`rq suspend`) stops every queue, Live-safe work
    included; admission defers per kind instead."""
    found = []
    for rel in _SCANNED:
        root = REPO / rel
        paths = [root] if root.is_file() else (p for p in root.rglob("*") if p.is_file()) if root.exists() else []
        for path in paths:
            if path.suffix in {".pyc", ".png", ".jpg", ".woff2"}:
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            if _SUSPEND.search(text):
                found.append(str(path.relative_to(REPO)))
    assert found == []
