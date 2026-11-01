"""E0-Jobs.5: cursor Jobs (`run_cursor`) and the data_backfills runner.

Cursor Jobs run eagerly (JOBS_EAGER, every step inline) or, with eager off,
through a real RQ burst worker on fakeredis / the CI Valkey. The runner's
Campaign enumeration is narrowed to this test's Campaigns (the shared test
database holds every other test's too); `campaign_owners` itself is tested
against its own rows. Each test deletes the data_backfills rows it made, so a
reaper pass in another test never runs them.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from rq import Queue
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access.context import ctx_for
from app.access.owners import campaign_owners
from app.access.registry import scoped_select
from app.core.config import get_settings
from app.core.errors import StructuredOutputError
from app.db.models import Campaign, Genre, Job, User
from app.db.models.job import DataBackfill
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs import backfill, enqueue, outbox, worker
from app.jobs.backfill import CursorStep, register_backfill, run_backfills, run_cursor
from app.jobs.registry import JobKind, register
from app.jobs.worker import reap, run_job, run_job_step
from tests.jobs.test_reaper import _drain, _empty, _now, conn  # noqa: F401  (conn: fixture)

SEEN: dict[uuid.UUID, list[tuple]] = {}
# Campaign id -> the items its backfill Job walks through.
ITEMS: dict[uuid.UUID, list[str]] = {}
FAILED_ONCE: set[tuple[uuid.UUID, str]] = set()


def _select_next(items):
    async def select_next(db, ctx, cursor):
        index = cursor or 0
        if index >= len(items):
            return None
        return CursorStep(item=items[index], cursor=index + 1, total=len(items))
    return select_next


def _process_one(job):
    async def process_one(db, ctx, item):
        # The entry's own write (rolled back with the step when it fails).
        db.add(User(email=f"bf-{job.id}-{item}@example.com", hashed_password="x", display_name="b"))
        await db.flush()
        if item == "boom" and (job.id, item) not in FAILED_ONCE:
            FAILED_ONCE.add((job.id, item))
            raise RuntimeError("one entry failed")
        if item == "fatal":
            raise StructuredOutputError("unusable", attempts=1, errors=[])
    return process_one


async def walk(job, ctx, db):
    """Walks payload["items"] (or, for a backfill, ITEMS[campaign])."""
    SEEN.setdefault(job.id, []).append((job.progress, job.stage, job.attempts, dict(job.payload)))
    items = job.payload.get("items") if "items" in job.payload else ITEMS.get(job.campaign_id, [])
    await run_cursor(job, ctx, db, select_next=_select_next(items), process_one=_process_one(job))


register(JobKind(name="test_b.walk", queue=JobQueue.BACKFILL, timeout_s=10, handler=f"{__name__}:walk"))
async def stuck(job, ctx, db):
    async def select_next(db, ctx, cursor):
        return CursorStep(item="stuck", cursor=job.payload["next"], total=3)

    await run_cursor(job, ctx, db, select_next=select_next, process_one=_process_one(job))


register(JobKind(name="test_b.stuck", queue=JobQueue.BACKFILL, timeout_s=10, handler=f"{__name__}:stuck"))
register(JobKind(name="test_b.onsave", queue=JobQueue.ONSAVE, timeout_s=10, handler=f"{__name__}:walk"))


# ── Fixtures and helpers ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def only_this_tests_jobs(db):
    await db.execute(sa.update(Job).where(Job.status.in_(["queued", "running"])).values(status="cancelled"))
    await db.commit()


@pytest.fixture
async def backfill_name(db):
    """A fresh backfill name registered to test_b.walk, its row deleted after."""
    name = f"test_bf_{uuid.uuid4().hex[:12]}"
    register_backfill(name, "test_b.walk")
    yield name
    backfill.BACKFILLS.pop(name, None)
    await db.rollback()
    await db.execute(sa.delete(DataBackfill).where(DataBackfill.name == name))
    await db.commit()


@pytest.fixture
def ours(monkeypatch):
    """Narrow the runner to the Campaigns a test adds to the returned set."""
    allowed: set[uuid.UUID] = set()

    async def narrowed(db, *, created_before):
        return {cid: owner for cid, owner in (await campaign_owners(db, created_before=created_before)).items()
                if cid in allowed}

    monkeypatch.setattr(backfill, "campaign_owners", narrowed)
    return allowed


async def _campaign(db, ours: set | None = None) -> Campaign:
    owner = User(email=f"bf-owner-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                 display_name="owner", access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Backfill", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    if ours is not None:
        ours.add(c.id)
    return c


async def _row(db, job_id) -> Job | None:
    return (await db.execute(
        sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
    )).scalar_one_or_none()


async def _backfill(db, name) -> DataBackfill:
    return (await db.execute(
        sa.select(DataBackfill).where(DataBackfill.name == name).execution_options(populate_existing=True)
    )).scalar_one()


async def _add_backfill(db, name) -> None:
    db.add(DataBackfill(name=name))
    await db.commit()


def _factory(db) -> async_sessionmaker:
    return async_sessionmaker(db.bind, expire_on_commit=False)


async def _users(db, job_id) -> set[str]:
    prefix = f"bf-{job_id}-"
    rows = await db.scalars(sa.select(User.email).where(User.email.like(f"{prefix}%")))
    return {e[len(prefix):].split("@")[0] for e in rows}


async def _start(db, c: Campaign, items: list[str], kind: str = "test_b.walk") -> uuid.UUID:
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, kind, {"items": items}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()
    return job_id


# ── run_cursor ─────────────────────────────────────────────────────────────

async def test_a_cursor_job_steps_through_its_entries_on_one_row(db):
    c = await _campaign(db)
    job_id = await _start(db, c, ["a", "b", "c"])  # eager: every step runs inside commit()
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and row.progress == 1.0 and row.stage == "Entry 3 of 3"
    assert row.payload == {"items": ["a", "b", "c"], "cursor": 3, "done": 3}
    assert row.attempts == 1 and row.error_code is None
    assert await db.scalar(sa.select(sa.func.count()).select_from(Job)
                           .where(Job.idempotency_key == row.idempotency_key)) == 1
    steps = SEEN[job_id]
    assert [(round(p, 3) if p is not None else None, s, a) for p, s, a, _ in steps] == [
        (None, None, 1), (0.333, "Entry 1 of 3", 1), (0.667, "Entry 2 of 3", 1), (1.0, "Entry 3 of 3", 1),
    ]
    assert await _users(db, job_id) == {"a", "b", "c"}


async def test_an_empty_cursor_ends_done(db):
    c = await _campaign(db)
    job_id = await _start(db, c, [])
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and row.progress == 1.0 and len(SEEN[job_id]) == 1


async def test_a_failed_step_rolls_back_and_retries_from_the_same_cursor(db):
    c = await _campaign(db)
    job_id = await _start(db, c, ["a", "boom", "c"])
    row = await _row(db, job_id)
    # Step 1 committed; step 2 raised: its write and cursor rolled back, a normal retry.
    assert row.status == JobStatus.QUEUED and row.attempts == 1 and row.error_code == JobErrorCode.INTERNAL
    assert row.payload["cursor"] == 1 and row.payload["done"] == 1
    assert row.next_run_at is not None and row.progress is None
    assert await _users(db, job_id) == {"a"}

    await db.execute(sa.update(Job).where(Job.id == job_id).values(next_run_at=None))
    await db.commit()
    result = await run_job_step(job_id, _factory(db), "w")  # the retry: "boom" again, now fine
    assert result.continued and result.status == JobStatus.QUEUED
    row = await _row(db, job_id)
    # A continuation clears the error and resets the attempts: the budget is per entry.
    assert row.attempts == 0 and row.error_code is None and row.error_message is None
    assert row.stage == "Entry 2 of 3" and row.payload["cursor"] == 2
    while (await run_job_step(job_id, _factory(db), "w")).continued:
        pass
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and await _users(db, job_id) == {"a", "boom", "c"}


@pytest.mark.parametrize("payload", [{"next": None}, {"cursor": 1, "next": 1}])
async def test_a_cursor_that_does_not_advance_fails_instead_of_looping(db, payload):
    c = await _campaign(db)
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, "test_b.stuck", payload, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()  # eager: one attempt, no continuation
    row = await _row(db, job_id)
    assert row.status == JobStatus.QUEUED and row.attempts == 1 and row.error_code == JobErrorCode.INTERNAL
    assert row.payload == payload and await _users(db, job_id) == set()  # nothing processed


async def test_a_continuation_is_pushed_again_with_a_distinct_rq_id(db, conn, monkeypatch):
    c = await _campaign(db)
    job_id = await _start(db, c, ["a", "b"])  # eager off: pushed, not run
    assert Queue("backfill", connection=conn).job_ids == [str(job_id)]
    Queue("backfill", connection=conn).empty()
    assert await run_job(job_id, _factory(db), "w") == JobStatus.QUEUED
    row = await _row(db, job_id)
    assert row.status == JobStatus.QUEUED and row.stage == "Entry 1 of 2" and row.attempts == 0
    assert row.next_run_at is None and row.worker_id is None
    ids = Queue("backfill", connection=conn).job_ids
    assert len(ids) == 1 and re.fullmatch(rf"{job_id}_[0-9a-f]+", ids[0])

    await db.execute(sa.update(Job).where(Job.id == job_id).values(created_at=_now() - timedelta(seconds=600)))
    await db.commit()
    assert (await reap(_factory(db), conn)).pushed == []  # the reaper sees RQ holds it

    _drain(conn, monkeypatch)  # a real RQ worker runs the remaining steps
    row = await _row(db, job_id)
    assert row.status == JobStatus.DONE and row.payload["done"] == 2
    assert await _users(db, job_id) == {"a", "b"}


# ── The data_backfills runner ──────────────────────────────────────────────

async def test_runner_starts_one_job_per_campaign_as_its_owner(db, backfill_name, ours):
    c1, c2 = await _campaign(db, ours), await _campaign(db, ours)
    ITEMS[c1.id], ITEMS[c2.id] = ["x", "y"], ["z"]
    await _add_backfill(db, backfill_name)

    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.RUNNING}
    bf = await _backfill(db, backfill_name)
    assert bf.status == JobStatus.RUNNING
    assert sorted(bf.cursor["campaigns"]) == sorted([str(c1.id), str(c2.id)])
    jobs = {cid: await _row(db, uuid.UUID(jid)) for cid, jid in bf.cursor["jobs"].items()}
    assert set(jobs) == {str(c1.id), str(c2.id)}
    for c in (c1, c2):
        job = jobs[str(c.id)]
        assert job.kind == "test_b.walk" and job.queue == JobQueue.BACKFILL
        assert job.ctx_user_id == c.user_id and job.created_by == c.user_id and job.ctx_kind == "gm"
        assert job.payload["backfill"] == backfill_name
        assert job.idempotency_key == f"backfill:{backfill_name}:{c.id}"
        assert job.status == JobStatus.DONE  # eager: ran inside the runner's commit
    assert bf.cursor["entries"] == {
        str(c1.id): {"done": 2, "total": 2, "cursor": 2}, str(c2.id): {"done": 1, "total": 1, "cursor": 1},
    }

    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.DONE}
    bf = await _backfill(db, backfill_name)
    assert bf.status == JobStatus.DONE and sorted(bf.cursor["finished"]) == sorted([str(c1.id), str(c2.id)])
    assert bf.cursor["failed"] == []
    assert await run_backfills(_factory(db)) == {}  # done: never touched again
    n = await db.scalar(sa.select(sa.func.count()).select_from(Job)
                        .where(Job.idempotency_key.like(f"backfill:{backfill_name}:%")))
    assert n == 2


async def test_runner_records_a_failed_campaign_and_still_finishes(db, backfill_name, ours):
    good, bad = await _campaign(db, ours), await _campaign(db, ours)
    ITEMS[good.id], ITEMS[bad.id] = ["x"], ["fatal"]
    await _add_backfill(db, backfill_name)
    await run_backfills(_factory(db))
    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.DONE}
    bf = await _backfill(db, backfill_name)
    assert bf.cursor["failed"] == [str(bad.id)]
    failed = await _row(db, uuid.UUID(bf.cursor["jobs"][str(bad.id)]))
    assert failed.status == JobStatus.FAILED and failed.error_code == JobErrorCode.AI_OUTPUT_UNUSABLE
    owner_ctx = await ctx_for(db, bad.user_id, bad.id)
    visible = (await db.scalars(scoped_select(Job, owner_ctx).where(Job.id == failed.id))).all()
    assert [j.id for j in visible] == [failed.id]  # in the Owner's own Job list


async def test_runner_restart_never_starts_a_second_job(db, backfill_name, ours, conn):
    c = await _campaign(db, ours)
    ITEMS[c.id] = ["x"]
    await _add_backfill(db, backfill_name)
    await run_backfills(_factory(db))  # eager off: the Job stays queued
    first = (await _backfill(db, backfill_name)).cursor["jobs"][str(c.id)]
    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.RUNNING}
    assert (await _backfill(db, backfill_name)).cursor["jobs"] == {str(c.id): first}
    # Even with cursor.jobs lost, the idempotency key returns the active Job.
    bf = await _backfill(db, backfill_name)
    bf.cursor = {**bf.cursor, "jobs": {}}
    await db.commit()
    await run_backfills(_factory(db))
    assert (await _backfill(db, backfill_name)).cursor["jobs"] == {str(c.id): first}
    n = await db.scalar(sa.select(sa.func.count()).select_from(Job)
                        .where(Job.idempotency_key == f"backfill:{backfill_name}:{c.id}"))
    assert n == 1


async def test_a_campaign_created_after_the_row_is_not_backfilled(db, backfill_name, ours):
    early = await _campaign(db, ours)
    await _add_backfill(db, backfill_name)
    late = await _campaign(db, ours)
    await run_backfills(_factory(db))
    bf = await _backfill(db, backfill_name)
    assert bf.cursor["campaigns"] == [str(early.id)] and list(bf.cursor["jobs"]) == [str(early.id)]
    assert str(late.id) not in str(bf.cursor)


async def test_deleted_campaigns_and_jobs_count_as_finished(db, backfill_name, ours, conn):
    gone, job_gone, waiting = [await _campaign(db, ours) for _ in range(3)]
    await _add_backfill(db, backfill_name)
    await run_backfills(_factory(db))  # eager off: three queued Jobs
    jobs = (await _backfill(db, backfill_name)).cursor["jobs"]
    await db.execute(sa.delete(Campaign).where(Campaign.id == gone.id))
    await db.execute(sa.delete(Job).where(Job.id == uuid.UUID(jobs[str(job_gone.id)])))
    await db.commit()
    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.RUNNING}
    bf = await _backfill(db, backfill_name)
    assert sorted(bf.cursor["finished"]) == sorted([str(gone.id), str(job_gone.id)])
    await db.execute(sa.update(Job).where(Job.id == uuid.UUID(jobs[str(waiting.id)])).values(status="cancelled"))
    await db.commit()
    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.DONE}


async def test_a_backfill_with_no_campaigns_is_done_at_once(db, backfill_name, ours):
    await _add_backfill(db, backfill_name)
    assert await run_backfills(_factory(db)) == {backfill_name: JobStatus.DONE}
    assert (await _backfill(db, backfill_name)).cursor == {"campaigns": [], "jobs": {}, "finished": [],
                                                           "failed": []}


async def test_an_unregistered_backfill_is_logged_once_and_left_alone(db, ours, caplog):
    name = f"test_unreg_{uuid.uuid4().hex[:12]}"
    await _campaign(db, ours)
    await _add_backfill(db, name)
    try:
        with caplog.at_level(logging.WARNING, logger="app.jobs.backfill"):
            assert await run_backfills(_factory(db)) == {}
            assert await run_backfills(_factory(db)) == {}
        assert sum("backfill_unregistered" in r.getMessage() for r in caplog.records) == 1
        bf = await _backfill(db, name)
        assert bf.status == JobStatus.QUEUED and bf.cursor is None
    finally:
        await db.execute(sa.delete(DataBackfill).where(DataBackfill.name == name))
        await db.commit()


async def test_a_reaper_pass_runs_the_runner(db, backfill_name, ours, monkeypatch):
    from tests.conftest import TEST_DB_URL

    import fakeredis

    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    await _campaign(db, ours)
    await _add_backfill(db, backfill_name)
    reaper = worker.Reaper("runner", connection=fakeredis.FakeRedis(server=fakeredis.FakeServer()))
    assert await asyncio.to_thread(reaper.tick) is not None  # its own event loop
    assert (await _backfill(db, backfill_name)).status == JobStatus.RUNNING


def test_register_backfill_validates():
    with pytest.raises(ValueError):
        register_backfill("test_bf_onsave", "test_b.onsave")  # not the backfill queue
    with pytest.raises(ValueError):
        register_backfill("test_bf_x", "test_b.unknown")
    register_backfill("test_bf_same", "test_b.walk")
    register_backfill("test_bf_same", "test_b.walk")  # same pair: a no-op
    register(JobKind(name="test_b.other", queue=JobQueue.BACKFILL, timeout_s=10, handler=f"{__name__}:walk"))
    with pytest.raises(ValueError):
        register_backfill("test_bf_same", "test_b.other")
    backfill.BACKFILLS.pop("test_bf_same")


async def test_campaign_owners_honours_created_before(db):
    a = await _campaign(db)
    cut = (await db.scalar(sa.select(Campaign.created_at).where(Campaign.id == a.id)))
    b = await _campaign(db)
    before = await campaign_owners(db, created_before=cut)
    everything = await campaign_owners(db, created_before=None)
    assert before[a.id] == a.user_id and b.id not in before
    assert everything[a.id] == a.user_id and everything[b.id] == b.user_id
