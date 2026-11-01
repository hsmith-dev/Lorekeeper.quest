"""E0-Journal.1: the hook dispatcher on after_commit, against the story's I/O
matrix: dispatch after commit (in emit order, never inside `commit()`, never
on its session), rollback of the root and of a savepoint, a failing or slow
handler, a handler that enqueues, no handlers, an unknown event, the
`visibility_changed` bridge and the worker's `job_finished`.

Every test swaps in an empty handler registry and drains the background
tasks before it ends. They commit, so every Campaign is unique per test.
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import date, datetime, timedelta, timezone

import fakeredis
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.access.visibility as vis
import app.hooks as hook_handlers
from app.access import ctx_for, set_visibility
from app.core import after_commit, hooks
from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.db.models import Campaign, Genre, Job, JournalEntry, User
from app.db.session import get_db
from app.domain.enums import JobQueue, JobStatus, Visibility
from app.hooks import HANDLERS, HookEvent, HookPayload, emit
from app.jobs import enqueue, outbox, worker
from app.jobs.registry import SYSTEM_NOOP, JobKind, register
from app.schemas.sources import RecordRef

E = HookEvent


async def _boom_terminal(job, ctx, db):
    raise StructuredOutputError("unusable", attempts=1, errors=[])


async def _boom_retry(job, ctx, db):
    raise RuntimeError("try again")


register(JobKind(name="test_h.fail", queue=JobQueue.INTERACTIVE, timeout_s=5, handler=f"{__name__}:_boom_terminal"))
register(JobKind(name="test_h.retry", queue=JobQueue.INTERACTIVE, timeout_s=5, handler=f"{__name__}:_boom_retry"))


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def registry(monkeypatch):
    """An empty handler registry; every hook task finished before teardown."""
    monkeypatch.setattr(hooks, "_HANDLERS", {})
    yield
    await hooks.drain()


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, HookEvent, HookPayload, AsyncSession]] = []

    def handler(self, name: str, *, fail: bool = False):
        async def handle(db, event, payload):
            self.calls.append((name, event, payload, db))
            if fail:
                raise RuntimeError("handler boom")

        handle.__qualname__ = f"Recorder.{name}"
        return handle

    def of(self, event: HookEvent) -> list[HookPayload]:
        return [p for _n, e, p, _db in self.calls if e == event]


@pytest.fixture
def rec() -> Recorder:
    return Recorder()


async def _campaign(db) -> Campaign:
    owner = User(email=f"hooks-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x", display_name="owner",
                 access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Hooks", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c


def _refs() -> dict:
    return {"journal_id": uuid.uuid4()}


# ── The public surface ─────────────────────────────────────────────────────

def test_app_hooks_exports_the_events_emit_and_handlers():
    assert {e.value for e in HookEvent} == {
        "entry_saved", "entry_updated", "entry_deleted", "visibility_changed", "canon_changed", "role_changed",
        "job_finished", "live_session_ended"}
    params = inspect.signature(emit).parameters
    assert list(params)[:2] == ["db", "event"]
    for name in ("campaign_id", "refs", "actor_ctx"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
    assert isinstance(HANDLERS, list)
    assert vis._LISTENERS.count(hook_handlers._visibility_changed) == 1


# ── Commit and rollback ────────────────────────────────────────────────────

async def test_commit_dispatches_each_event_in_order_after_commit_returns(db, rec):
    c = await _campaign(db)
    for event in (E.ENTRY_SAVED, E.ENTRY_UPDATED):
        hooks.register_handler(event, rec.handler("first"))
        hooks.register_handler(event, rec.handler("second"))
    saved, updated = _refs(), _refs()
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=saved, actor_ctx="ctx")
    emit(db, E.ENTRY_UPDATED, campaign_id=str(c.id), refs=updated, actor_ctx="ctx")
    await db.commit()
    assert rec.calls == []  # nothing runs inside commit()
    await hooks.drain()
    assert [(n, e) for n, e, _p, _db in rec.calls] == [
        ("first", E.ENTRY_SAVED), ("second", E.ENTRY_SAVED), ("first", E.ENTRY_UPDATED), ("second", E.ENTRY_UPDATED)]
    assert [p for _n, _e, p, _db in rec.calls] == [
        HookPayload(c.id, saved, "ctx"), HookPayload(c.id, saved, "ctx"),
        HookPayload(c.id, updated, "ctx"), HookPayload(c.id, updated, "ctx")]
    sessions = [s for *_rest, s in rec.calls]
    assert all(isinstance(s, AsyncSession) and s is not db for s in sessions)
    assert len({id(s) for s in sessions}) == 4  # a fresh session per handler call


async def test_root_rollback_discards_the_events(db, rec):
    c = await _campaign(db)
    hooks.register_handler(E.ENTRY_SAVED, rec.handler("h"))
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=_refs(), actor_ctx=None)
    await db.rollback()
    await db.commit()
    assert not hooks._TASKS
    await hooks.drain()
    assert rec.calls == []


async def test_close_without_commit_discards_the_events(db, rec):
    c = await _campaign(db)
    hooks.register_handler(E.ENTRY_SAVED, rec.handler("h"))
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=_refs(), actor_ctx=None)
    await db.close()
    await db.commit()
    await hooks.drain()
    assert rec.calls == []


async def test_a_rolled_back_savepoint_drops_only_its_events(db, rec):
    c = await _campaign(db)
    hooks.register_handler(E.ENTRY_SAVED, rec.handler("h"))
    outer, inner, released = _refs(), _refs(), _refs()
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=outer, actor_ctx=None)
    savepoint = await db.begin_nested()
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=inner, actor_ctx=None)
    await savepoint.rollback()
    async with db.begin_nested():
        emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=released, actor_ctx=None)
    assert not hooks._TASKS  # a savepoint release is not the commit
    await db.commit()
    await hooks.drain()
    assert [p.refs for p in rec.of(E.ENTRY_SAVED)] == [outer, released]


async def test_an_event_nobody_handles_schedules_nothing(db, rec):
    c = await _campaign(db)
    hooks.register_handler(E.ENTRY_SAVED, rec.handler("h"))
    emit(db, E.LIVE_SESSION_ENDED, campaign_id=c.id, refs={}, actor_ctx=None)
    await db.commit()
    assert not hooks._TASKS
    await hooks.drain()
    assert rec.calls == []


async def test_an_unknown_event_raises_at_emit(db):
    with pytest.raises(ValueError):
        emit(db, "nope", campaign_id=uuid.uuid4(), refs={}, actor_ctx=None)
    with pytest.raises(ValueError):
        hooks.register_handler("nope", lambda db, e, p: None)


def test_the_primitive_refuses_unknown_and_conflicting_channels():
    with pytest.raises(ValueError):
        after_commit.defer(object(), "no-such-channel", 1)
    with pytest.raises(ValueError):
        after_commit.register_channel(hooks.CHANNEL, lambda session, items: None)
    assert after_commit.committed_bind() is None


# ── Failing handlers ───────────────────────────────────────────────────────

async def test_a_raising_handler_is_logged_and_the_route_still_returns_200(db, rec, caplog):
    c = await _campaign(db)
    secret = f"secret-{uuid.uuid4().hex}"
    canary = f"canary-{uuid.uuid4().hex}"
    written = f"hookwrite-{uuid.uuid4().hex}@example.com"

    async def writes_then_raises(hdb, event, payload):
        hdb.add(User(email=written, hashed_password="x", display_name="w"))
        await hdb.flush()
        raise RuntimeError(f"handler boom {canary}")

    hooks.register_handler(E.ENTRY_SAVED, writes_then_raises)
    hooks.register_handler(E.ENTRY_SAVED, rec.handler("after"))

    api = FastAPI()

    @api.post("/emit/{campaign_id}")
    async def route(campaign_id: uuid.UUID, rdb: AsyncSession = Depends(get_db)):
        emit(rdb, E.ENTRY_SAVED, campaign_id=campaign_id, refs={"shorthand": secret}, actor_ctx=None)
        await rdb.commit()
        return {"ok": True}

    api.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        r = await client.post(f"/emit/{c.id}")
    assert r.status_code == 200 and r.json() == {"ok": True}
    await hooks.drain()

    assert [n for n, *_ in rec.calls] == ["after"]  # the next handler still ran
    failed = [rec_ for rec_ in caplog.records if "hook_failed" in rec_.getMessage()]
    assert len(failed) == 1
    msg = failed[0].getMessage()
    assert '"hook_event": "entry_saved"' in msg and "writes_then_raises" in msg and str(c.id) in msg
    assert '"error_type": "RuntimeError"' in msg
    assert secret not in caplog.text  # never the refs
    assert canary not in caplog.text and "Traceback" not in caplog.text  # nor the exception's message
    assert await db.scalar(sa.select(sa.func.count()).select_from(User).where(User.email == written)) == 0


async def test_a_slow_handler_times_out_and_the_next_one_runs(db, rec, caplog, monkeypatch):
    monkeypatch.setattr(hooks, "HANDLER_TIMEOUT_S", 0.05)
    c = await _campaign(db)

    async def hangs(hdb, event, payload):
        await asyncio.sleep(5)

    hooks.register_handler(E.CANON_CHANGED, hangs)
    hooks.register_handler(E.CANON_CHANGED, rec.handler("after"))
    emit(db, E.CANON_CHANGED, campaign_id=c.id, refs={}, actor_ctx=None)
    await db.commit()
    await asyncio.wait_for(hooks.drain(), 3)
    assert [n for n, *_ in rec.calls] == ["after"]
    assert '"reason": "timeout"' in caplog.text and "hangs" in caplog.text


async def test_a_drain_timeout_leaves_the_handlers_running(db, rec, caplog):
    c = await _campaign(db)
    release = asyncio.Event()

    async def waits(hdb, event, payload):
        await release.wait()
        rec.calls.append(("waits", event, payload, hdb))

    hooks.register_handler(E.ROLE_CHANGED, waits)
    emit(db, E.ROLE_CHANGED, campaign_id=c.id, refs={}, actor_ctx=None)
    await db.commit()
    await hooks.drain(timeout=0.05)
    assert "hook drain timed out" in caplog.text and rec.calls == []
    release.set()
    await hooks.drain()
    assert [n for n, *_ in rec.calls] == ["waits"]


# ── A handler that enqueues ────────────────────────────────────────────────

async def test_a_handler_enqueue_goes_through_the_outbox(db, rec):
    c = await _campaign(db)
    key = f"test:{uuid.uuid4().hex}"

    async def on_saved(hdb, event, payload):
        ctx = await ctx_for(hdb, payload.actor_ctx.user_id, payload.campaign_id)
        await enqueue(hdb, ctx, SYSTEM_NOOP.name, {"note": "x"}, idempotency_key=key)

    hooks.register_handler(E.ENTRY_SAVED, on_saved)
    gm = await ctx_for(db, c.user_id, c.id)
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=_refs(), actor_ctx=gm)
    await db.commit()
    await hooks.drain()
    job = (await db.execute(sa.select(Job).where(Job.idempotency_key == key))).scalars().one()
    assert job.campaign_id == c.id
    assert job.status == JobStatus.DONE  # pushed by the handler session's commit (eager in tests)


async def test_an_enqueue_error_is_a_hook_failure(db, caplog):
    c = await _campaign(db)

    async def bad_enqueue(hdb, event, payload):
        ctx = await ctx_for(hdb, payload.actor_ctx.user_id, payload.campaign_id)
        await enqueue(hdb, ctx, "no.such_kind", {}, idempotency_key="k")

    hooks.register_handler(E.ENTRY_SAVED, bad_enqueue)
    emit(db, E.ENTRY_SAVED, campaign_id=c.id, refs=_refs(), actor_ctx=await ctx_for(db, c.user_id, c.id))
    await db.commit()
    await hooks.drain()
    assert "hook_failed" in caplog.text and "bad_enqueue" in caplog.text


# ── visibility_changed ─────────────────────────────────────────────────────

async def test_set_visibility_reaches_visibility_changed_handlers(db, rec):
    c = await _campaign(db)
    entry = JournalEntry(user_id=c.user_id, campaign_id=c.id, shorthand="s", narrative="n",
                         entry_hash=uuid.uuid4().hex, session_date=date(2026, 5, 1), visibility="party", kind="gm")
    db.add(entry)
    await db.commit()
    gm = await ctx_for(db, c.user_id, c.id)
    hooks.register_handler(E.VISIBILITY_CHANGED, rec.handler("h"))
    await set_visibility(db, gm, RecordRef(kind="journal", id=entry.id), Visibility.GM)
    await db.commit()
    assert rec.calls == []
    await hooks.drain()
    [payload] = rec.of(E.VISIBILITY_CHANGED)
    assert payload.campaign_id == c.id
    assert payload.refs == [RecordRef(kind="journal", id=entry.id)]
    assert payload.actor_ctx.user_id == gm.user_id and payload.actor_ctx.role == gm.role


# ── job_finished ───────────────────────────────────────────────────────────

async def _enqueued(db, c: Campaign, kind: str) -> uuid.UUID:
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, kind, {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()  # eager: the Job runs here
    await hooks.drain()
    return job_id


async def test_the_worker_emits_job_finished_on_done_and_failed_only(db, rec):
    c = await _campaign(db)
    hooks.register_handler(E.JOB_FINISHED, rec.handler("h"))
    done = await _enqueued(db, c, SYSTEM_NOOP.name)
    failed = await _enqueued(db, c, "test_h.fail")
    retried = await _enqueued(db, c, "test_h.retry")
    by_job = {p.refs["job_id"]: p for p in rec.of(E.JOB_FINISHED)}
    assert by_job[done] == HookPayload(c.id, {"job_id": done, "kind": SYSTEM_NOOP.name, "status": JobStatus.DONE},
                                       None)
    assert by_job[failed] == HookPayload(c.id, {"job_id": failed, "kind": "test_h.fail", "status": JobStatus.FAILED},
                                         None)
    assert retried not in by_job  # requeued for a retry: not finished
    assert await db.scalar(sa.select(Job.status).where(Job.id == retried)) == JobStatus.QUEUED


async def test_the_reaper_emits_job_finished_for_an_interrupted_last_attempt(db, rec, monkeypatch):
    c = await _campaign(db)
    hooks.register_handler(E.JOB_FINISHED, rec.handler("h"))
    conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(conn)
    try:
        ctx = await ctx_for(db, c.user_id, c.id)
        job_id = await enqueue(db, ctx, SYSTEM_NOOP.name, {}, idempotency_key=f"test:{uuid.uuid4().hex}")
        await db.commit()
        old = datetime.now(timezone.utc) - timedelta(seconds=worker.STALE_AFTER_S * 2)
        await db.execute(sa.update(Job).where(Job.id == job_id).values(
            status=JobStatus.RUNNING, attempts=3, max_attempts=3, worker_id="gone", started_at=old,
            heartbeat_at=old))
        await db.commit()
        factory = async_sessionmaker(db.bind, expire_on_commit=False)
        result = worker.ReapResult()
        async with factory() as rdb:
            await worker._recover_running(rdb, {}, datetime.now(timezone.utc), result)
        await hooks.drain()
    finally:
        outbox.set_connection(None)
        for q in JobQueue:
            Queue(q.value, connection=conn).empty()
    assert job_id in result.failed
    by_job = {p.refs["job_id"]: p for p in rec.of(E.JOB_FINISHED)}
    assert by_job[job_id] == HookPayload(c.id, {"job_id": job_id, "kind": SYSTEM_NOOP.name,
                                                "status": JobStatus.FAILED}, None)


async def test_perform_drains_job_finished_handlers_on_its_own_loop(db, rec, monkeypatch):
    """The RQ path: `perform` runs the Job under its own `asyncio.run` and
    must let the job_finished handler run before that loop ends."""
    c = await _campaign(db)
    hooks.register_handler(E.JOB_FINISHED, rec.handler("h"))  # a plain list append: thread-safe
    conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    monkeypatch.setattr(get_settings(), "database_url", db.bind.url.render_as_string(hide_password=False))
    outbox.set_connection(conn)
    try:
        ctx = await ctx_for(db, c.user_id, c.id)
        job_id = await enqueue(db, ctx, SYSTEM_NOOP.name, {}, idempotency_key=f"test:{uuid.uuid4().hex}")
        await db.commit()
        assert rec.calls == []
        await asyncio.to_thread(worker.perform, str(job_id))
    finally:
        outbox.set_connection(None)
        for q in JobQueue:
            Queue(q.value, connection=conn).empty()
    by_job = {p.refs["job_id"]: p for p in rec.of(E.JOB_FINISHED)}
    assert by_job[job_id].refs == {"job_id": job_id, "kind": SYSTEM_NOOP.name, "status": JobStatus.DONE}
