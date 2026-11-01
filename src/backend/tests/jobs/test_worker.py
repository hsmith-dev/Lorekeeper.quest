"""E0-Jobs.3: the full `run_job` wrapper and LorekeeperWorker, against the
story's I/O matrix: rights check, LLM config, retries and their delays,
classification, timeout, gate class and deadline, heartbeat, `job.report`,
log fields, and a real RQ worker running a pushed Job.

Rows are written directly and committed (nothing is dispatched for a row not
made by `enqueue`), then run with `run_job`, so each test controls the row.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import io
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import pytest
import redis
import sqlalchemy as sa
from rq import Queue
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.access.context import ctx_for
from app.clients.errors import ModelServiceUnavailable
from app.core import errors as llm_errors
from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import LLMBusy, LLMConfigError, LLMError, LLMUnavailable, StructuredOutputError
from app.core.llm_gate import GateClass
from app.core.logging import JobContextFilter, JSONFormatter
from app.db.models import Campaign, Genre, Job, User
from app.db.models.campaign_member import CampaignMember
from app.db.models.journal import JournalEntry
from app.db.models.user_settings import UserSettings
from app.domain.enums import CampaignRole, JobErrorCode, JobQueue, JobStatus
from app.jobs import enqueue, outbox, registry, worker
from app.jobs.registry import KIND_MODULES, JobKind, register
from app.jobs.worker import LorekeeperWorker, run_job

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")
BACKEND = Path(__file__).resolve().parents[2]

# ── Test-local kinds ───────────────────────────────────────────────────────

SEEN: dict[uuid.UUID, dict] = {}
FACTORY: dict[str, async_sessionmaker] = {}

ERRORS = {
    "busy": lambda: LLMBusy("The AI is busy right now; try again shortly"),
    "llm_unavailable": lambda: LLMUnavailable("The AI service is unavailable"),
    "model_unavailable": lambda: ModelServiceUnavailable("ml sidecar 503 at http://ml:8000"),
    "runtime": lambda: RuntimeError("raw secret boom"),
    "structured": lambda: StructuredOutputError("schema said no", attempts=2, errors=[{"loc": "x"}]),
    "config": lambda: LLMConfigError("Add your own LLM API key in Settings"),
}


async def record(job, ctx, db):
    SEEN[job.id] = {
        "ctx_role": ctx.role, "starter": getattr(job.starter, "id", None), "llm_config": job.llm_config,
        "gate_class": llm_gate.current_class.get(), "deadline": llm_gate.current_deadline.get(),
        "monotonic": time.monotonic(),
    }


async def raise_error(job, ctx, db):
    SEEN[job.id] = {"called": True}
    raise ERRORS[job.payload["error"]]()


async def slow(job, ctx, db):
    await asyncio.sleep(5)


async def block_loop(job, ctx, db):
    time.sleep(0.8)  # blocks the event loop; the heartbeat thread still beats


async def report(job, ctx, db):
    with pytest.raises(ValueError):
        await job.report(1.5, "Too far")
    await job.report(0.5, "Reading", 30)
    async with FACTORY["f"]() as other:  # another session sees it mid-run
        row = (await other.execute(sa.select(Job.progress, Job.stage, Job.eta_seconds, Job.status)
                                   .where(Job.id == job.id))).one()
    SEEN[job.id] = {"seen": tuple(row)}


async def log_inside(job, ctx, db):
    logging.getLogger("tests.jobs.handler").info("inside the handler")


async def write_then_fail(job, ctx, db):
    db.add(User(email=f"w3-{job.id}@example.com", hashed_password="x", display_name="w"))
    await db.flush()
    raise RuntimeError("after the write")


def _kind(name, handler, queue=JobQueue.INTERACTIVE, timeout_s=5, **kw):
    return register(JobKind(name=name, queue=queue, timeout_s=timeout_s, handler=f"{__name__}:{handler}", **kw))


_kind("test_w.record", "record")
_kind("test_w.llm", "record", resources=frozenset({"llm"}))
_kind("test_w.raise", "raise_error")
_kind("test_w.slow", "slow", timeout_s=1)
_kind("test_w.block", "block_loop")
_kind("test_w.report", "report")
_kind("test_w.log", "log_inside")
_kind("test_w.write_fail", "write_then_fail")
_kind("test_w.gate_live", "record", queue=JobQueue.ONSAVE, gate_class=GateClass.live_recap)
_kind("test_w.gate_default", "record", queue=JobQueue.ONSAVE)


# ── Helpers ────────────────────────────────────────────────────────────────

def _user(label: str) -> User:
    return User(email=f"worker-{label}-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                display_name=label, access_granted=True, access_source="promo")


async def _campaign(db) -> Campaign:
    owner = _user("owner")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Worker", genre=Genre.fantasy)
    db.add(c)
    await db.flush()
    return c


async def _member(db, campaign: Campaign, role: CampaignRole) -> CampaignMember:
    user = _user("member")
    db.add(user)
    await db.flush()
    m = CampaignMember(campaign_id=campaign.id, user_id=user.id, role=role)
    db.add(m)
    await db.flush()
    return m


async def _job(db, campaign: Campaign, kind: str, *, user_id=None, ctx_kind="gm", access_epoch=0,
               payload=None, **kw) -> Job:
    user_id = campaign.user_id if user_id is None else user_id
    row = Job(campaign_id=campaign.id, kind=kind, queue=registry.get_kind(kind).queue,
              idempotency_key=f"test:{uuid.uuid4().hex}", ctx_kind=ctx_kind, ctx_user_id=user_id,
              created_by=user_id, access_epoch=access_epoch, payload=payload or {}, **kw)
    db.add(row)
    await db.commit()
    return row


async def _row(db, job_id) -> Job:
    return (await db.execute(
        sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )).scalar_one()


def _factory(db) -> async_sessionmaker:
    return async_sessionmaker(db.bind, expire_on_commit=False)


async def _due_now(db, job_id) -> None:
    """What the reaper (E0-Jobs.4) will do: make a waiting retry runnable."""
    await db.execute(sa.update(Job).where(Job.id == job_id).values(next_run_at=None))
    await db.commit()


# ── Contracts ──────────────────────────────────────────────────────────────

def _llm_error_classes(cls=LLMError):
    for sub in cls.__subclasses__():
        yield sub
        yield from _llm_error_classes(sub)


def test_every_llm_error_code_is_a_job_error_code():
    classes = list(_llm_error_classes())
    assert {c.__name__ for c in llm_errors.RETRYABLE + llm_errors.TERMINAL} <= {c.__name__ for c in classes}
    for cls in classes:
        JobErrorCode(cls.code)  # ValueError if not a member


def _registering_modules() -> set[str]:
    """Every app module with a `register(JobKind(...))` call."""
    found = set()
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "register"
                    and node.args and isinstance(node.args[0], ast.Call)
                    and getattr(node.args[0].func, "id", None) == "JobKind"):
                found.add(".".join(path.relative_to(BACKEND).with_suffix("").parts))
    return found


def test_kind_modules_cover_every_module_that_registers_a_kind():
    registering = _registering_modules()
    assert "app.jobs.registry" in registering  # the scan works (system.noop)
    assert registering - {"app.jobs.registry"} <= set(KIND_MODULES)
    for module in KIND_MODULES:
        importlib.import_module(module)


def test_lorekeeper_worker_imports_the_kind_modules(monkeypatch):
    imported = []
    real = registry.importlib.import_module
    monkeypatch.setattr(registry, "KIND_MODULES", ("tests.jobs.test_worker",))
    monkeypatch.setattr(registry.importlib, "import_module", lambda name: imported.append(name) or real(name))
    monkeypatch.setattr(worker, "_WORKER_ID", None)
    w = LorekeeperWorker([q.value for q in JobQueue], connection=fakeredis.FakeRedis())
    assert imported == ["tests.jobs.test_worker"]
    assert [q.name for q in w.queues] == ["interactive", "onsave", "backfill"]
    assert worker._worker_id() == w.name


@pytest.mark.parametrize("bad", ["urgent", 3])
def test_gate_class_is_validated(bad):
    with pytest.raises(ValueError):
        JobKind(name="test_w.bad", queue=JobQueue.ONSAVE, timeout_s=5, handler="app.jobs.builtin:noop",
                gate_class=bad)


def test_gate_class_is_coerced():
    kind = JobKind(name="test_w.coerce", queue=JobQueue.ONSAVE, timeout_s=5, handler="app.jobs.builtin:noop",
                   gate_class="live_recap")
    assert kind.gate_class is GateClass.live_recap


# ── Happy path and claim ───────────────────────────────────────────────────

async def test_happy_path(db):
    c = await _campaign(db)
    row = await _job(db, c, "system.noop")
    assert await run_job(row.id, _factory(db), "host-a:1") == JobStatus.DONE
    row = await _row(db, row.id)
    assert row.status == JobStatus.DONE and row.attempts == 1 and row.worker_id == "host-a:1"
    assert row.started_at is not None and row.heartbeat_at is not None and row.finished_at is not None
    assert row.progress == 1.0 and row.error_code is None


async def test_not_yet_due_is_not_claimed(db):
    c = await _campaign(db)
    row = await _job(db, c, "test_w.record", next_run_at=datetime.now(timezone.utc) + timedelta(seconds=60))
    assert await run_job(row.id, _factory(db), "w") is None
    row = await _row(db, row.id)
    assert row.status == JobStatus.QUEUED and row.attempts == 0 and row.worker_id is None
    assert row.id not in SEEN


# ── Rights check ───────────────────────────────────────────────────────────

async def _assert_permission_changed(db, row):
    assert await run_job(row.id, _factory(db), "w") == JobStatus.FAILED
    row = await _row(db, row.id)
    assert row.status == JobStatus.FAILED and row.error_code == JobErrorCode.PERMISSION_CHANGED
    assert row.attempts == 1 and row.next_run_at is None
    assert row.id not in SEEN


async def test_demoted_starter_fails_without_retry(db):
    c = await _campaign(db)
    m = await _member(db, c, CampaignRole.CO_GM)
    row = await _job(db, c, "test_w.record", user_id=m.user_id, ctx_kind="gm")
    m.role = CampaignRole.PLAYER
    await db.commit()
    await _assert_permission_changed(db, row)


async def test_bumped_epoch_fails_without_retry(db):
    c = await _campaign(db)
    m = await _member(db, c, CampaignRole.PLAYER)
    row = await _job(db, c, "test_w.record", user_id=m.user_id, ctx_kind="player", access_epoch=0)
    m.access_epoch = 1
    await db.commit()
    await _assert_permission_changed(db, row)


async def test_removed_starter_fails_without_retry(db):
    c = await _campaign(db)
    m = await _member(db, c, CampaignRole.PLAYER)
    row = await _job(db, c, "test_w.record", user_id=m.user_id, ctx_kind="player")
    await db.delete(m)
    await db.commit()
    await _assert_permission_changed(db, row)


async def test_unchanged_member_runs_with_the_current_ctx(db):
    c = await _campaign(db)
    m = await _member(db, c, CampaignRole.PLAYER)
    row = await _job(db, c, "test_w.record", user_id=m.user_id, ctx_kind="player")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    assert SEEN[row.id]["ctx_role"] == "player" and SEEN[row.id]["starter"] == m.user_id


# ── LLM config ─────────────────────────────────────────────────────────────

async def test_llm_kind_without_config_fails_without_retry(db):
    c = await _campaign(db)  # owner: no personal key, no subscription, not open access
    row = await _job(db, c, "test_w.llm")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.FAILED
    row = await _row(db, row.id)
    assert row.error_code == JobErrorCode.LLM_CONFIG and row.attempts == 1
    assert row.error_message == "No AI model is configured for your account"
    assert row.id not in SEEN


async def test_llm_kind_gets_the_config_and_the_starter(db):
    c = await _campaign(db)
    db.add(UserSettings(user_id=c.user_id, llm_provider="openai", llm_api_key="sk-test", llm_model="gpt-x"))
    await db.commit()
    row = await _job(db, c, "test_w.llm")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    seen = SEEN[row.id]
    assert seen["starter"] == c.user_id
    assert seen["llm_config"] is not None and seen["llm_config"].provider == "openai"
    assert seen["llm_config"].model == "gpt-x"


async def test_non_llm_kind_has_no_config(db):
    c = await _campaign(db)
    row = await _job(db, c, "test_w.record")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    assert SEEN[row.id]["llm_config"] is None and SEEN[row.id]["starter"] == c.user_id


# ── Retries and classification ─────────────────────────────────────────────

def _close_to(value: datetime, expected: datetime, slack_s: float = 3) -> bool:
    return abs((value - expected).total_seconds()) <= slack_s


@pytest.mark.parametrize("error, code, message", [
    ("busy", JobErrorCode.LLM_BUSY, "The AI is busy right now; try again shortly"),
    ("llm_unavailable", JobErrorCode.LLM_UNAVAILABLE, "The AI service is unavailable"),
    ("model_unavailable", JobErrorCode.MODEL_UNAVAILABLE, worker.MODEL_UNAVAILABLE_MESSAGE),
    ("runtime", JobErrorCode.INTERNAL, worker.INTERNAL_MESSAGE),
])
async def test_retryable_failure_requeues_twice_then_fails(db, error, code, message):
    c = await _campaign(db)
    row = await _job(db, c, "test_w.raise", payload={"error": error})
    factory = _factory(db)

    for attempt, delay in ((1, 10), (2, 60)):
        before = datetime.now(timezone.utc)
        assert await run_job(row.id, factory, "w") == JobStatus.QUEUED
        r = await _row(db, row.id)
        assert r.status == JobStatus.QUEUED and r.attempts == attempt
        assert r.error_code == code and r.error_message == message
        assert r.finished_at is None and _close_to(r.next_run_at, before + timedelta(seconds=delay))
        # Not due yet: a second delivery does nothing.
        assert await run_job(row.id, factory, "w") is None
        await _due_now(db, row.id)

    assert await run_job(row.id, factory, "w") == JobStatus.FAILED
    r = await _row(db, row.id)
    assert r.status == JobStatus.FAILED and r.attempts == 3
    assert r.error_code == code and r.error_message == message
    assert r.finished_at is not None and r.next_run_at is None
    assert "raw secret boom" not in (r.error_message or "") and "ml:8000" not in (r.error_message or "")


@pytest.mark.parametrize("error, code, message", [
    ("structured", JobErrorCode.AI_OUTPUT_UNUSABLE, "AI output unusable"),
    ("config", JobErrorCode.LLM_CONFIG, "Add your own LLM API key in Settings"),
])
async def test_terminal_failure_does_not_retry(db, error, code, message):
    c = await _campaign(db)
    row = await _job(db, c, "test_w.raise", payload={"error": error})
    assert await run_job(row.id, _factory(db), "w") == JobStatus.FAILED
    r = await _row(db, row.id)
    assert r.status == JobStatus.FAILED and r.attempts == 1
    assert r.error_code == code and r.error_message == message


async def test_timeout_retries_then_fails_on_the_last_attempt(db):
    c = await _campaign(db)
    first = await _job(db, c, "test_w.slow")
    started = time.monotonic()
    assert await run_job(first.id, _factory(db), "w") == JobStatus.QUEUED
    assert time.monotonic() - started < 4  # stopped at timeout_s, not after the 5 s sleep
    r = await _row(db, first.id)
    assert r.error_code == JobErrorCode.TIMEOUT and r.error_message == worker.TIMEOUT_MESSAGE

    last = await _job(db, c, "test_w.slow", attempts=2)
    assert await run_job(last.id, _factory(db), "w") == JobStatus.FAILED
    r = await _row(db, last.id)
    assert r.status == JobStatus.FAILED and r.attempts == 3 and r.error_code == JobErrorCode.TIMEOUT


async def test_failing_handler_writes_roll_back(db):
    c = await _campaign(db)
    row = await _job(db, c, "test_w.write_fail")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.QUEUED
    assert await db.scalar(sa.select(sa.func.count()).select_from(User).where(
        User.email == f"w3-{row.id}@example.com")) == 0


async def test_failing_job_never_touches_the_entry_that_triggered_it(db):
    c = await _campaign(db)
    await db.commit()
    ctx = await ctx_for(db, c.user_id, c.id)
    entry = JournalEntry(user_id=c.user_id, campaign_id=c.id, shorthand="sh", narrative="The party rested.",
                         entry_hash=uuid.uuid4().hex)
    db.add(entry)
    job_id = await enqueue(db, ctx, "test_w.write_fail", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()  # eager: the Job runs (and fails) inside this commit
    assert (await _row(db, job_id)).status != JobStatus.DONE
    saved = (await db.execute(sa.select(JournalEntry).where(JournalEntry.id == entry.id)
                              .execution_options(populate_existing=True))).scalar_one()
    assert saved.narrative == "The party rested." and saved.shorthand == "sh"


# ── Gate class and deadline ────────────────────────────────────────────────

@pytest.mark.parametrize("kind, expected", [
    ("test_w.gate_live", GateClass.live_recap),
    ("test_w.gate_default", GateClass.job_onsave),
    ("test_w.record", GateClass.gm_interactive),
])
async def test_gate_class_and_deadline_are_set_then_reset(db, kind, expected):
    c = await _campaign(db)
    row = await _job(db, c, kind)
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    seen = SEEN[row.id]
    assert seen["gate_class"] is expected
    timeout_s = registry.get_kind(kind).timeout_s
    assert seen["deadline"] is not None and 0 < seen["deadline"] - seen["monotonic"] <= timeout_s
    assert llm_gate.current_class.get() is GateClass.gm_interactive
    assert llm_gate.current_deadline.get() is None


# ── Heartbeat, progress, logs ──────────────────────────────────────────────

async def test_heartbeat_beats_while_the_handler_blocks_the_loop(db, monkeypatch):
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_S", 0.1)
    c = await _campaign(db)
    row = await _job(db, c, "test_w.block")
    assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
    r = await _row(db, row.id)
    assert r.heartbeat_at > r.started_at


async def test_heartbeat_only_touches_its_own_running_row(db, monkeypatch):
    monkeypatch.setattr(worker, "HEARTBEAT_INTERVAL_S", 0.05)
    c = await _campaign(db)
    row = await _job(db, c, "test_w.record", status=JobStatus.RUNNING, worker_id="someone-else")
    beat = worker._Heartbeat(db.bind.url, row.id, "w", {}).start()
    await asyncio.sleep(0.3)
    beat.stop()
    assert (await _row(db, row.id)).heartbeat_at is None


async def test_report_is_visible_mid_run(db):
    c = await _campaign(db)
    FACTORY["f"] = _factory(db)
    row = await _job(db, c, "test_w.report")
    assert await run_job(row.id, FACTORY["f"], "w") == JobStatus.DONE
    assert SEEN[row.id]["seen"] == (0.5, "Reading", 30, JobStatus.RUNNING)
    r = await _row(db, row.id)
    assert r.progress == 1.0 and r.stage == "Reading"


async def test_report_outside_a_running_job_raises():
    with pytest.raises(RuntimeError):
        await Job().report(0.1)
    for bad in (-0.1, 1.01, float("nan"), True, "0.5"):
        with pytest.raises(ValueError):
            await Job().report(bad)


async def test_logs_carry_the_job_fields_and_never_the_payload(db):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(JobContextFilter())
    loggers = [logging.getLogger("tests.jobs.handler"), logging.getLogger("app.jobs")]
    previous = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    try:
        c = await _campaign(db)
        row = await _job(db, c, "test_w.log", payload={"note": "PAYLOAD-SHOULD-NOT-BE-LOGGED"})
        assert await run_job(row.id, _factory(db), "w") == JobStatus.DONE
        failed = await _job(db, c, "test_w.raise", payload={"error": "runtime", "x": "PAYLOAD-SHOULD-NOT-BE-LOGGED"})
        await run_job(failed.id, _factory(db), "w")
    finally:
        for lg, level in zip(loggers, previous):
            lg.removeHandler(handler)
            lg.setLevel(level)
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.startswith("{")]
    inside = [line for line in lines if line["msg"] == "inside the handler"]
    assert inside and inside[0]["job_id"] == str(row.id)
    assert inside[0]["kind"] == "test_w.log" and inside[0]["campaign_id"] == str(c.id)
    assert any(line.get("job_id") == str(failed.id) for line in lines)
    assert "PAYLOAD-SHOULD-NOT-BE-LOGGED" not in buf.getvalue()


# ── A real RQ worker ───────────────────────────────────────────────────────

class _InProcessWorker(LorekeeperWorker):
    """LorekeeperWorker without the fork (rq's SimpleWorker.execute_job), so
    a fakeredis server is shared with the test."""

    def execute_job(self, job, queue):
        self.prepare_execution(job)
        self.perform_job(job, queue)
        from rq.worker import WorkerStatus

        self.set_state(WorkerStatus.IDLE)


def _rq_run(conn, worker_class, monkeypatch, db_url: str) -> tuple[str, Job]:
    """Enqueue a noop for real (eager off, pushed to `conn`), run the worker
    in burst mode, and return the row."""
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    monkeypatch.setattr(get_settings(), "database_url", db_url)
    outbox.set_connection(conn)

    async def setup() -> uuid.UUID:
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                c = await _campaign(s)
                await s.commit()
                ctx = await ctx_for(s, c.user_id, c.id)
                job_id = await enqueue(s, ctx, "system.noop", {}, idempotency_key=f"test:{uuid.uuid4().hex}")
                await s.commit()
                return job_id
        finally:
            await engine.dispose()

    async def fetch(job_id) -> Job:
        engine = create_async_engine(db_url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await _row(s, job_id)
        finally:
            await engine.dispose()

    try:
        for q in JobQueue:
            Queue(q.value, connection=conn).empty()
        job_id = asyncio.run(setup())
        assert Queue("interactive", connection=conn).job_ids == [str(job_id)]
        w = worker_class([q.value for q in JobQueue], connection=conn)
        w.work(burst=True)
        return w.name, asyncio.run(fetch(job_id))
    finally:
        outbox.set_connection(None)
        for q in JobQueue:
            Queue(q.value, connection=conn).empty()


def test_lorekeeper_worker_runs_a_pushed_job(monkeypatch):
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(worker, "_WORKER_ID", None)
    conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    name, row = _rq_run(conn, _InProcessWorker, monkeypatch, TEST_DB_URL)
    assert row.status == JobStatus.DONE
    assert row.worker_id == name


@pytest.mark.skipif(not VALKEY_TEST_URL, reason="VALKEY_TEST_URL not set")
def test_forking_lorekeeper_worker_runs_a_pushed_job_on_valkey(monkeypatch):
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(worker, "_WORKER_ID", None)
    conn = redis.Redis.from_url(VALKEY_TEST_URL)
    try:
        name, row = _rq_run(conn, LorekeeperWorker, monkeypatch, TEST_DB_URL)
    finally:
        conn.close()
    assert row.status == JobStatus.DONE
    assert row.worker_id == name  # the RQ worker's name, as its registry knows it
