"""E0-Jobs.7: the Job routes and the SSE stream, against the spec's I/O matrix.

Detail (GM raw `result_ref`, a Player's own Job with the result filtered,
another's Job as the one 404), the list (default window, newest first,
`status` filter, 422, `queue_position` over visible Jobs only), cancel
(starter and GM, 409 for running/terminal, the race with the worker's claim
in both orders, the worker skipping a cancelled Job), retry (202, same row
back in `queued` with attempts 0 and pushed after commit, 409s), preview
writes, `GET /api/jobs/stream` end to end on an in-process uvicorn (filter
per viewer, preview, a real ORM change reaching the stream, a failed check
ending it), the limiter, the admin counts and the nginx location.

Rows are written directly and committed; nothing runs unless a test asks.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import fakeredis
import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
import sqlalchemy as sa
from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access import ctx_for, get_job, job_event_stream, list_jobs, queue_positions, visible_result_ref
from app.access import jobs as access_jobs
from app.access.jobs import JobEventCheckFailed, register_result_kind
from app.core import pubsub, valkey_client
from app.core.config import get_settings
from app.core.limiter import limiter, user_or_ip
from app.db.models import Campaign, Genre, Job, JournalEntry
from app.db.models.campaign_member import CampaignMember
from app.db.session import get_db
from app.domain.enums import JobQueue, JobStatus
from app.jobs import control, outbox, worker
from app.jobs.control import JobConflict, cancel_job, job_counts, retry_job
from app.jobs.registry import get_kind
from app.jobs.worker import reap
from tests.ev4.fixtures import bearer, create_user, make_member
from tests.test_sse import Reader, serve  # noqa: F401  (the uvicorn fixture)

VALKEY_TEST_URL = os.environ.get("VALKEY_TEST_URL") or os.environ.get("REDIS_TEST_URL")
NOT_FOUND = {"detail": "Not found"}
MISSING = "00000000-0000-4000-8000-000000000000"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── Fixtures ───────────────────────────────────────────────────────────────

class World:
    """A Campaign with an Owner, two Players, a co-GM and an outsider; a GM
    and a Party journal entry; another Campaign."""

    async def build(self, db: AsyncSession) -> "World":
        self.db = db
        self.owner = await create_user(db, "jobs_owner")
        self.cid = uuid.uuid4()
        db.add(Campaign(id=self.cid, user_id=self.owner.id, name="Jobs", genre=Genre("fantasy")))
        await db.commit()
        self.player = await make_member(db, role="player", campaign_id=self.cid, label="jobs_player")
        self.player2 = await make_member(db, role="player", campaign_id=self.cid, label="jobs_player2")
        self.co_gm = await make_member(db, role="gm", campaign_id=self.cid, label="jobs_cogm")
        self.outsider = await create_user(db, "jobs_outsider")
        self.hidden_entry = await self.entry("gm")
        self.party_entry = await self.entry("party")
        other_owner = await create_user(db, "jobs_other")
        self.other_owner = other_owner
        self.other_cid = uuid.uuid4()
        db.add(Campaign(id=self.other_cid, user_id=other_owner.id, name="Other", genre=Genre("fantasy")))
        await db.commit()
        return self

    async def entry(self, visibility: str) -> uuid.UUID:
        row = JournalEntry(id=uuid.uuid4(), user_id=self.owner.id, campaign_id=self.cid, shorthand="sh",
                           narrative=f"N-{visibility}", entry_hash=uuid.uuid4().hex, session_date=date(2026, 3, 1),
                           kind="gm", visibility=visibility)
        self.db.add(row)
        await self.db.commit()
        return row.id

    async def job(self, starter, *, status: str = "queued", ctx_kind: str | None = None, created_at=None,
                  result_ref=None, kind: str = "system.noop", queue: str = "interactive", key: str | None = None,
                  finished_at=None, campaign_id=None, access_epoch: int = 0) -> uuid.UUID:
        now = datetime.now(timezone.utc)
        if ctx_kind is None:
            ctx_kind = "gm" if starter in (self.owner, self.co_gm) else "player"
        terminal = status in ("done", "failed", "cancelled")
        row = Job(id=uuid.uuid4(), campaign_id=campaign_id or self.cid, kind=kind, queue=queue, status=status,
                  payload={}, idempotency_key=key or f"test-jr:{uuid.uuid4().hex}", ctx_kind=ctx_kind,
                  ctx_user_id=starter.id, created_by=starter.id, access_epoch=access_epoch,
                  attempts=3 if status == "failed" else 0, progress=0.4 if status == "running" else None,
                  stage="Working" if status == "running" else None,
                  error_code="internal" if status == "failed" else None,
                  error_message="Something went wrong while running this job" if status == "failed" else None,
                  result_ref=result_ref, created_at=created_at or now,
                  started_at=now if status in ("running", "done", "failed") else None,
                  finished_at=finished_at or (now if terminal else None),
                  worker_id="w-old" if status in ("running", "failed") else None)
        self.db.add(row)
        await self.db.commit()
        return row.id

    async def ctx(self, user):
        return await ctx_for(self.db, user.id, self.cid)

    async def row(self, job_id) -> Job:
        await self.db.commit()
        return await self.db.get(Job, job_id, populate_existing=True)


@pytest_asyncio.fixture
async def world(db) -> World:
    return await World().build(db)


@pytest.fixture
def rq_conn(monkeypatch):
    """Eager off; pushes go to fakeredis."""
    conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr(get_settings(), "jobs_eager", False)
    outbox.set_connection(conn)
    yield conn
    outbox.set_connection(None)
    conn.close()


def _factory(world) -> async_sessionmaker:
    return async_sessionmaker(world.db.bind, expire_on_commit=False)


def _ref(entry_id, **extra) -> dict:
    return {"kind": "journal", "id": str(entry_id), **extra}


# ── Detail ─────────────────────────────────────────────────────────────────

async def test_gm_detail_has_every_field_and_the_raw_result_ref(client, world):
    raw = _ref(world.hidden_entry, extra="kept for the GM")
    job_id = await world.job(world.owner, status="done", result_ref=raw)
    for gm in (world.owner, world.co_gm):
        r = await client.get(f"/api/jobs/{job_id}", headers=bearer(gm))
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"id", "kind", "status", "progress", "stage", "eta_seconds", "error_code",
                             "error_message", "result_ref", "attempts", "created_at", "started_at",
                             "finished_at", "queue_position"}
        assert body["id"] == str(job_id) and body["status"] == "done" and body["result_ref"] == raw
        assert body["queue_position"] is None


async def test_player_own_job_with_a_gm_only_result_gets_null(client, world):
    hidden = await world.job(world.player, status="done", result_ref=_ref(world.hidden_entry))
    visible = await world.job(world.player, status="done", result_ref=_ref(world.party_entry, secret="x"))
    junk = await world.job(world.player, status="done", result_ref={"kind": "nope", "id": str(world.party_entry)})
    r = await client.get(f"/api/jobs/{hidden}", headers=bearer(world.player))
    assert r.status_code == 200 and r.json()["result_ref"] is None
    r = await client.get(f"/api/jobs/{visible}", headers=bearer(world.player))
    assert r.json()["result_ref"] == {"kind": "journal", "id": str(world.party_entry)}  # extra key dropped
    r = await client.get(f"/api/jobs/{junk}", headers=bearer(world.player))
    assert r.json()["result_ref"] is None


async def test_other_jobs_are_the_one_404(client, world):
    gm_job = await world.job(world.owner, status="running")
    other_player = await world.job(world.player2, status="failed")
    elsewhere = await world.job(world.other_owner, status="done", campaign_id=world.other_cid)
    missing = await client.get(f"/api/jobs/{MISSING}", headers=bearer(world.player))
    assert missing.status_code == 404 and missing.json() == NOT_FOUND
    for job_id in (gm_job, other_player, elsewhere, "not-a-uuid"):
        r = await client.get(f"/api/jobs/{job_id}", headers=bearer(world.player))
        assert (r.status_code, r.content) == (missing.status_code, missing.content), job_id
    r = await client.get(f"/api/jobs/{gm_job}", headers=bearer(world.outsider))
    assert r.status_code == 404 and r.json() == NOT_FOUND
    # Preview: the member view sees no Job.
    r = await client.get(f"/api/jobs/{gm_job}", headers={**bearer(world.owner), "X-Lorekeeper-Preview": "member"})
    assert r.status_code == 404 and r.json() == NOT_FOUND


async def test_file_result_kind_needs_both_file_checks(world):
    player = await world.ctx(world.player)
    assert await visible_result_ref(world.db, player, {"kind": "file", "id": str(uuid.uuid4())}) is None
    assert {"journal", "entity", "file"} <= set(access_jobs.result_kinds())
    with pytest.raises(ValueError):
        register_result_kind("journal", Job)
    assert register_result_kind("journal", JournalEntry).model is JournalEntry  # same: a no-op


# ── List ───────────────────────────────────────────────────────────────────

async def test_list_default_window_newest_first(client, world):
    now = datetime.now(timezone.utc)
    old = await world.job(world.owner, status="done", created_at=now - timedelta(hours=30),
                          finished_at=now - timedelta(hours=25))
    recent = await world.job(world.owner, status="failed", created_at=now - timedelta(hours=3),
                             finished_at=now - timedelta(hours=2))
    running = await world.job(world.owner, status="running", created_at=now - timedelta(hours=2))
    queued_old = await world.job(world.owner, status="queued", created_at=now - timedelta(days=3))
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=bearer(world.owner))
    assert r.status_code == 200, r.text
    ids = [j["id"] for j in r.json()["jobs"]]
    assert ids == [str(running), str(recent), str(queued_old)]
    assert str(old) not in ids
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}&status=failed", headers=bearer(world.owner))
    assert [j["id"] for j in r.json()["jobs"]] == [str(recent)]
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}&status=bogus", headers=bearer(world.owner))
    assert r.status_code == 422


async def test_list_never_cuts_active_jobs_for_newer_finished_ones(client, world):
    now = datetime.now(timezone.utc)
    old_queued = await world.job(world.owner, status="queued", created_at=now - timedelta(days=2))
    for i in range(access_jobs.LIST_LIMIT + 5):
        world.db.add(Job(id=uuid.uuid4(), campaign_id=world.cid, kind="system.noop", queue="interactive",
                         status="done", payload={}, idempotency_key=f"test-jr:{uuid.uuid4().hex}", ctx_kind="gm",
                         ctx_user_id=world.owner.id, created_by=world.owner.id,
                         created_at=now - timedelta(minutes=i), finished_at=now - timedelta(minutes=i)))
    await world.db.commit()
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=bearer(world.owner))
    assert r.status_code == 200, r.text
    jobs = r.json()["jobs"]
    assert len(jobs) == access_jobs.LIST_LIMIT + 1
    assert jobs[-1]["id"] == str(old_queued) and jobs[-1]["queue_position"] == 0


async def test_an_explicit_status_has_no_time_window(client, world):
    now = datetime.now(timezone.utc)
    old_failed = await world.job(world.owner, status="failed", created_at=now - timedelta(days=4),
                                 finished_at=now - timedelta(days=3))
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}&status=failed", headers=bearer(world.owner))
    assert [j["id"] for j in r.json()["jobs"]] == [str(old_failed)]
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=bearer(world.owner))
    assert str(old_failed) not in [j["id"] for j in r.json()["jobs"]]


async def test_list_is_scoped_and_counts_only_visible_jobs_ahead(client, world):
    await world.job(world.owner, created_at=T0)
    await world.job(world.co_gm, created_at=T0 + timedelta(seconds=1))
    await world.job(world.player2, created_at=T0 + timedelta(seconds=2))
    first = await world.job(world.player, created_at=T0 + timedelta(seconds=3))
    other_queue = await world.job(world.player, created_at=T0 + timedelta(seconds=4), queue="onsave")
    second = await world.job(world.player, created_at=T0 + timedelta(seconds=5))
    await world.job(world.other_owner, created_at=T0 - timedelta(seconds=1), campaign_id=world.other_cid)

    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=bearer(world.player))
    jobs = {j["id"]: j for j in r.json()["jobs"]}
    assert set(jobs) == {str(first), str(other_queue), str(second)}
    assert jobs[str(first)]["queue_position"] == 0
    assert jobs[str(second)]["queue_position"] == 1  # 3 hidden ahead, 1 own ahead
    assert jobs[str(other_queue)]["queue_position"] == 0

    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=bearer(world.owner))
    jobs = {j["id"]: j for j in r.json()["jobs"]}
    assert jobs[str(second)]["queue_position"] == 4
    r = await client.get(f"/api/jobs/{second}", headers=bearer(world.player))
    assert r.json()["queue_position"] == 1

    preview = {**bearer(world.owner), "X-Lorekeeper-Preview": "member"}
    r = await client.get(f"/api/jobs/?campaign_id={world.cid}", headers=preview)
    assert r.status_code == 200 and r.json() == {"jobs": []}
    for cid in (world.other_cid, MISSING, "not-a-uuid"):
        r = await client.get(f"/api/jobs/?campaign_id={cid}", headers=bearer(world.player))
        assert r.status_code == 404 and r.json() == NOT_FOUND


async def test_access_helpers_agree_with_the_routes(world):
    own = await world.job(world.player, created_at=T0 + timedelta(seconds=9))
    await world.job(world.owner, created_at=T0)
    player = await world.ctx(world.player)
    assert [j.id for j in await list_jobs(world.db, player)] == [own]
    assert await queue_positions(world.db, player) == {own: 0}
    assert (await get_job(world.db, player, own)).id == own


# ── Cancel ─────────────────────────────────────────────────────────────────

async def test_starter_and_gm_cancel_queued_jobs_and_the_worker_skips_them(client, world):
    mine = await world.job(world.player)
    theirs = await world.job(world.player)
    r = await client.post(f"/api/jobs/{mine}/cancel", headers=bearer(world.player))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["finished_at"] is not None
    r = await client.post(f"/api/jobs/{theirs}/cancel", headers=bearer(world.co_gm))
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    for job_id in (mine, theirs):
        assert await worker.run_job(job_id, _factory(world), "w-test") is None
        assert (await world.row(job_id)).status == JobStatus.CANCELLED


async def test_cancel_running_or_terminal_is_409(client, world):
    for status in ("running", "done", "failed", "cancelled"):
        job_id = await world.job(world.owner, status=status)
        r = await client.post(f"/api/jobs/{job_id}/cancel", headers=bearer(world.owner))
        assert r.status_code == 409 and r.json() == {"detail": "Only queued Jobs can be cancelled"}, status
        await world.db.commit()  # release the row lock the request took
        assert (await world.row(job_id)).status == status


async def test_cancel_hidden_or_preview_is_404_and_writes_nothing(client, world):
    gm_job = await world.job(world.owner)
    other = await world.job(world.player2)
    for job_id in (gm_job, other):
        r = await client.post(f"/api/jobs/{job_id}/cancel", headers=bearer(world.player))
        assert r.status_code == 404 and r.json() == NOT_FOUND
    preview = {**bearer(world.owner), "X-Lorekeeper-Preview": "member"}
    r = await client.post(f"/api/jobs/{gm_job}/cancel", headers=preview)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    await world.db.commit()
    assert (await world.row(gm_job)).status == JobStatus.QUEUED
    assert (await world.row(other)).status == JobStatus.QUEUED


async def test_cancel_after_the_claim_committed_is_409(world):
    job_id = await world.job(world.owner)
    async with _factory(world)() as wdb:
        assert await worker._claim(wdb, job_id, "w-race") is not None
    with pytest.raises(JobConflict):
        await cancel_job(world.db, await world.ctx(world.owner), job_id)
    await world.db.commit()
    assert (await world.row(job_id)).status == JobStatus.RUNNING


async def test_a_claim_waiting_on_the_cancel_lock_claims_nothing(world):
    job_id = await world.job(world.owner)
    gm = await world.ctx(world.owner)
    async with _factory(world)() as cancel_db:
        job = await get_job(cancel_db, gm, job_id, for_update=True)  # cancel holds the row lock
        claim = asyncio.ensure_future(_claim_in_own_session(world, job_id))
        await asyncio.sleep(0.3)
        assert not claim.done()  # the conditional UPDATE waits for the lock
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc)
        await cancel_db.commit()
    assert await asyncio.wait_for(claim, 5) is None
    assert (await world.row(job_id)).status == JobStatus.CANCELLED


async def _claim_in_own_session(world, job_id):
    async with _factory(world)() as wdb:
        return await worker._claim(wdb, job_id, "w-race")


async def test_cancel_releases_dependents(world, rq_conn):
    dep = await world.job(world.owner)
    async with _factory(world)() as s:
        row = Job(id=uuid.uuid4(), campaign_id=world.cid, kind="system.noop", queue="interactive",
                  status="queued", payload={}, idempotency_key=f"test-jr:{uuid.uuid4().hex}", ctx_kind="gm",
                  ctx_user_id=world.owner.id, created_by=world.owner.id, depends_on_job_id=dep)
        s.add(row)
        await s.commit()
        dependent = row.id
    await cancel_job(world.db, await world.ctx(world.owner), dep)
    assert str(dependent) in Queue("interactive", connection=rq_conn).job_ids


# ── Retry ──────────────────────────────────────────────────────────────────

async def test_retry_failed_requeues_the_same_row_and_pushes_after_commit(client, world, rq_conn):
    job_id = await world.job(world.player, status="failed", queue="backfill",
                             result_ref=_ref(world.party_entry))
    row = await world.row(job_id)
    row.eta_seconds = 30
    row.heartbeat_at = datetime.now(timezone.utc)
    await world.db.commit()
    r = await client.post(f"/api/jobs/{job_id}/retry", headers=bearer(world.player))
    assert r.status_code == 202 and r.json() == {"job_id": str(job_id)}
    row = await world.row(job_id)
    assert row.status == JobStatus.QUEUED and row.attempts == 0
    assert row.queue == get_kind(row.kind).queue == JobQueue.INTERACTIVE
    assert (row.error_code, row.error_message, row.progress, row.stage, row.worker_id, row.started_at,
            row.finished_at, row.next_run_at, row.result_ref, row.eta_seconds, row.heartbeat_at) == (None,) * 11
    assert Queue("interactive", connection=rq_conn).job_ids == [str(job_id)]
    # A GM retries anyone's failed Job.
    other = await world.job(world.player2, status="failed")
    r = await client.post(f"/api/jobs/{other}/retry", headers=bearer(world.co_gm))
    assert r.status_code == 202


async def test_retry_runs_again_under_jobs_eager(client, world):
    job_id = await world.job(world.owner, status="failed")
    r = await client.post(f"/api/jobs/{job_id}/retry", headers=bearer(world.owner))
    assert r.status_code == 202
    row = await world.row(job_id)
    assert row.status == JobStatus.DONE and row.attempts == 1


async def test_the_starter_retrying_takes_their_current_epoch(client, world):
    """Demoted then re-promoted: the grant's epoch moved, so the old Job
    failed `permission_changed`. Retried by its starter, it runs."""
    await world.db.execute(sa.update(CampaignMember).where(
        CampaignMember.campaign_id == world.cid, CampaignMember.user_id == world.player.id).values(access_epoch=2))
    await world.db.commit()
    job_id = await world.job(world.player, status="failed", access_epoch=1)
    r = await client.post(f"/api/jobs/{job_id}/retry", headers=bearer(world.player))
    assert r.status_code == 202, r.text
    row = await world.row(job_id)
    assert row.access_epoch == 2
    assert row.status == JobStatus.DONE  # JOBS_EAGER ran the system.noop


async def test_a_key_taken_after_the_check_is_409_and_writes_nothing(client, world, rq_conn, monkeypatch):
    """The partial unique index backs the pre-check: with the check blind
    (no active statuses), the savepoint's flush fails and maps to 409."""
    key = f"test-jr:{uuid.uuid4().hex}"
    failed = await world.job(world.owner, status="failed", key=key)
    await world.job(world.owner, status="queued", key=key)
    monkeypatch.setattr(control, "ACTIVE_STATUSES", ())
    r = await client.post(f"/api/jobs/{failed}/retry", headers=bearer(world.owner))
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}
    await world.db.commit()
    assert (await world.row(failed)).status == JobStatus.FAILED
    assert Queue("interactive", connection=rq_conn).job_ids == []


async def test_retry_conflicts(client, world, rq_conn):
    for status in ("queued", "running", "done", "cancelled"):
        job_id = await world.job(world.owner, status=status)
        r = await client.post(f"/api/jobs/{job_id}/retry", headers=bearer(world.owner))
        assert r.status_code == 409 and r.json() == {"detail": control.ONLY_FAILED}, status
        await world.db.commit()
    key = f"test-jr:{uuid.uuid4().hex}"
    failed = await world.job(world.owner, status="failed", key=key)
    await world.job(world.owner, status="queued", key=key)
    r = await client.post(f"/api/jobs/{failed}/retry", headers=bearer(world.owner))
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}
    await world.db.commit()
    gone = await world.job(world.owner, status="failed", kind="test_jr.unregistered")
    r = await client.post(f"/api/jobs/{gone}/retry", headers=bearer(world.owner))
    assert r.status_code == 409 and r.json() == {"detail": control.UNKNOWN_KIND}
    await world.db.commit()
    assert (await world.row(failed)).status == JobStatus.FAILED
    assert Queue("interactive", connection=rq_conn).job_ids == []


_VOLATILE = {"date", "x-response-time", "server"}


def _shape(r: httpx.Response, job_id) -> tuple:
    """A retry answer with its own Job id taken out: status, body, headers."""
    body = r.text.replace(str(job_id), "<id>")
    return r.status_code, body, sorted((k, v) for k, v in r.headers.multi_items() if k.lower() not in _VOLATILE)


async def test_retry_behind_a_hidden_holder_answers_like_a_free_key(client, world, rq_conn):
    """E0-QA.14: the Owner's queued Job (hidden from the Player) holds the
    key. A 409 would reveal it exists, so the Player's retry answers exactly
    like one whose key is free; the row waits behind the holder, unpushed,
    on a per-retry key, and the holder is untouched."""
    player_h = bearer(world.player)
    key = f"test-jr:{uuid.uuid4().hex}"
    own = await world.job(world.player, status="failed", key=key)
    holder = await world.job(world.owner, status="queued", key=key)
    free = await world.job(world.player, status="failed")
    r_free = await client.post(f"/api/jobs/{free}/retry", headers=player_h)
    r_held = await client.post(f"/api/jobs/{own}/retry", headers=player_h)
    assert r_held.status_code == 202 and r_held.json() == {"job_id": str(own)}, r_held.text
    assert _shape(r_held, own) == _shape(r_free, free)
    row = await world.row(own)
    assert row.status == JobStatus.QUEUED and row.attempts == 0
    assert row.idempotency_key == f"{key}{control.RETRY_KEY_MARK}{world.player.id}"
    assert row.depends_on_job_id == holder
    assert Queue("interactive", connection=rq_conn).job_ids == [str(free)]  # the held row is not pushed
    held = await world.row(holder)
    assert held.status == JobStatus.QUEUED and held.idempotency_key == key and held.depends_on_job_id is None
    # The Player's view of their Job: queued, no trace of the holder.
    r = await client.get(f"/api/jobs/{own}", headers=player_h)
    assert r.status_code == 200 and r.json()["status"] == "queued", r.text
    assert str(holder) not in r.text and "depends_on" not in r.text
    # Released when the holder ends.
    await cancel_job(world.db, await world.ctx(world.owner), holder)
    assert str(own) in Queue("interactive", connection=rq_conn).job_ids


async def test_retry_behind_a_holder_in_another_campaign_is_held(client, world, rq_conn):
    """A GM of this Campaign cannot see another Campaign's Job either: held,
    then released when that Job ends (here, it fails in the worker's way: an
    ORM write of a terminal status)."""
    owner_h = bearer(world.owner)  # once: the rollback below expires world.owner
    key = f"test-jr:{uuid.uuid4().hex}"
    own = await world.job(world.owner, status="failed", key=key)
    holder = await world.job(world.other_owner, status="running", key=key, campaign_id=world.other_cid,
                             ctx_kind="gm")
    r = await client.post(f"/api/jobs/{own}/retry", headers=owner_h)
    assert r.status_code == 202 and r.json() == {"job_id": str(own)}, r.text
    row = await world.row(own)
    assert row.status == JobStatus.QUEUED and row.depends_on_job_id == holder
    assert Queue("interactive", connection=rq_conn).job_ids == []
    # The held row still dedups its base key: an enqueue of the same work in
    # this Campaign returns it instead of starting the work a second time.
    from app.jobs.enqueue import enqueue

    assert await enqueue(world.db, await world.ctx(world.owner), "system.noop", {"n": 1}, idempotency_key=key) == own
    await world.db.commit()
    assert Queue("interactive", connection=rq_conn).job_ids == []
    assert await worker._claim(world.db, own, "w-held") is None  # not runnable while the holder runs
    await world.db.rollback()
    held = await world.row(holder)
    held.status = JobStatus.FAILED
    held.finished_at = datetime.now(timezone.utc)
    await world.db.commit()
    assert Queue("interactive", connection=rq_conn).job_ids == [str(own)]
    # Failed again, then retried with the key free: the original key comes back.
    row = await world.row(own)
    row.status = JobStatus.FAILED
    await world.db.commit()
    r = await client.post(f"/api/jobs/{own}/retry", headers=owner_h)
    assert r.status_code == 202, r.text
    row = await world.row(own)
    assert row.idempotency_key == key and row.depends_on_job_id is None


async def test_retry_behind_a_visible_holder_is_409(client, world, rq_conn):
    """A holder the ctx can see is still the 409: the actor's own active Job,
    or (for a GM) any Job of the Campaign."""
    player_h, co_gm_h = bearer(world.player), bearer(world.co_gm)
    key = f"test-jr:{uuid.uuid4().hex}"
    own = await world.job(world.player, status="failed", key=key)
    await world.job(world.player, status="running", key=key)
    r = await client.post(f"/api/jobs/{own}/retry", headers=player_h)
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}
    await world.db.commit()
    key2 = f"test-jr:{uuid.uuid4().hex}"
    theirs = await world.job(world.player2, status="failed", key=key2)
    await world.job(world.owner, status="queued", key=key2)
    r = await client.post(f"/api/jobs/{theirs}/retry", headers=co_gm_h)
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}
    await world.db.commit()
    assert (await world.row(own)).status == JobStatus.FAILED
    assert (await world.row(theirs)).status == JobStatus.FAILED
    assert Queue("interactive", connection=rq_conn).job_ids == []


def _race_key_holder(world, monkeypatch, starter_id, ctx_kind: str) -> list:
    """control._key_holders that, on its first call only, commits a queued Job
    of `starter_id` holding the key from another session (a concurrent
    enqueue landing between the check and the flush) and reports the key
    free. Later calls are the real check. The racing Job's id is appended
    to the returned list."""
    real = control._key_holders
    raced: list = []

    async def racing(db, ctx, job_id, key):
        if raced:
            return await real(db, ctx, job_id, key)
        async with _factory(world)() as s:
            row = Job(id=uuid.uuid4(), campaign_id=world.cid, kind="system.noop", queue="interactive",
                      status="queued", payload={}, idempotency_key=key, ctx_kind=ctx_kind,
                      ctx_user_id=starter_id, created_by=starter_id)
            s.add(row)
            await s.commit()
            raced.append(row.id)
        return None, False

    monkeypatch.setattr(control, "_key_holders", racing)
    return raced


async def test_a_lost_race_to_a_hidden_holder_reruns_the_check_and_holds(client, world, rq_conn, monkeypatch):
    """The Owner's Job takes the key after the check: the index refuses the
    flush, the check runs again, finds a holder the Player cannot see and
    answers like a free key (held, per-retry key, not pushed)."""
    player_h, owner_id, player_id = bearer(world.player), world.owner.id, world.player.id
    key = f"test-jr:{uuid.uuid4().hex}"
    own = await world.job(world.player, status="failed", key=key)
    raced = _race_key_holder(world, monkeypatch, owner_id, "gm")
    r = await client.post(f"/api/jobs/{own}/retry", headers=player_h)
    assert r.status_code == 202 and r.json() == {"job_id": str(own)}, r.text
    (holder,) = raced
    row = await world.row(own)
    assert row.status == JobStatus.QUEUED and row.depends_on_job_id == holder
    assert row.idempotency_key == f"{key}{control.RETRY_KEY_MARK}{player_id}"
    assert Queue("interactive", connection=rq_conn).job_ids == []
    assert (await world.row(holder)).status == JobStatus.QUEUED


async def test_a_lost_race_to_a_visible_holder_is_409(client, world, rq_conn, monkeypatch):
    """The racing Job is the Player's own: the re-run check sees it, 409."""
    player_h, player_id = bearer(world.player), world.player.id
    key = f"test-jr:{uuid.uuid4().hex}"
    own = await world.job(world.player, status="failed", key=key)
    raced = _race_key_holder(world, monkeypatch, player_id, "player")
    r = await client.post(f"/api/jobs/{own}/retry", headers=player_h)
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}
    assert len(raced) == 1
    await world.db.commit()
    row = await world.row(own)
    assert row.status == JobStatus.FAILED and row.idempotency_key == key
    assert Queue("interactive", connection=rq_conn).job_ids == []


# ── One held copy per (starter, original key) ──────────────────────────────

async def _active_copies(world, key: str, starter_id) -> list[uuid.UUID]:
    """The starter's active Jobs doing `key`'s work: the exact key or a held
    retry's `{key}#retry:...`."""
    await world.db.commit()
    rows = (await world.db.execute(sa.select(Job.id).where(
        sa.or_(Job.idempotency_key == key, Job.idempotency_key.like(f"{key}{control.RETRY_KEY_MARK}%")),
        Job.ctx_user_id == starter_id, Job.status.in_(["queued", "running"])))).scalars().all()
    return list(rows)


async def _hidden_setup(world):
    """Two failed Jobs of the Player with one key, and the Owner's queued
    Job (hidden from the Player) holding it."""
    key = f"test-jr:{uuid.uuid4().hex}"
    a = await world.job(world.player, status="failed", key=key)
    b = await world.job(world.player, status="failed", key=key)
    holder = await world.job(world.owner, status="queued", key=key)
    return key, a, b, holder


async def test_two_sequential_retries_behind_a_hidden_holder_queue_one_copy(client, world, rq_conn):
    """The first retry is held; the second finds that held Job (the Player's
    own, so visible) and is the 409: one queued copy, never two."""
    player_h, player_id = bearer(world.player), world.player.id
    key, a, b, holder = await _hidden_setup(world)
    r = await client.post(f"/api/jobs/{a}/retry", headers=player_h)
    assert r.status_code == 202, r.text
    r = await client.post(f"/api/jobs/{b}/retry", headers=player_h)
    assert r.status_code == 409 and r.json() == {"detail": control.KEY_IN_USE}, r.text
    assert await _active_copies(world, key, player_id) == [a]
    assert (await world.row(b)).status == JobStatus.FAILED
    # A GM retrying the Player's other Job sees the held one too.
    r = await client.post(f"/api/jobs/{b}/retry", headers=bearer(world.co_gm))
    assert r.status_code == 409, r.text
    assert await _active_copies(world, key, player_id) == [a]
    assert Queue("interactive", connection=rq_conn).job_ids == []


async def test_two_racing_retries_behind_a_hidden_holder_queue_one_copy(world, rq_conn):
    """Two retries in two transactions at once: both see only the hidden
    holder, both write the same per-starter held key, and the partial unique
    index lets one commit. The loser re-runs the check, sees the winner (the
    Player's own Job) and is the 409."""
    player_id = world.player.id
    key, a, b, holder = await _hidden_setup(world)
    ctx = await world.ctx(world.player)
    await world.db.commit()
    factory = _factory(world)

    async def attempt(job_id):
        async with factory() as s:
            try:
                return await retry_job(s, ctx, job_id)
            except JobConflict as exc:
                return exc.detail

    results = await asyncio.gather(attempt(a), attempt(b))
    winners = [r for r in results if isinstance(r, uuid.UUID)]
    assert len(winners) == 1 and control.KEY_IN_USE in results, results
    (winner,) = winners
    assert await _active_copies(world, key, player_id) == [winner]
    loser = b if winner == a else a
    assert (await world.row(loser)).status == JobStatus.FAILED
    assert (await world.row(winner)).depends_on_job_id == holder
    assert Queue("interactive", connection=rq_conn).job_ids == []


async def test_a_retry_after_the_hidden_holder_ends_queues_one_copy(client, world, rq_conn):
    """The held Job is released when the hidden holder ends; while it is
    queued or running, a second retry is the 409. Once it is done, the key
    is free and the next retry takes the original key: one copy each time."""
    player_h, player_id = bearer(world.player), world.player.id
    key, a, b, holder = await _hidden_setup(world)
    assert (await client.post(f"/api/jobs/{a}/retry", headers=player_h)).status_code == 202
    await cancel_job(world.db, await world.ctx(world.owner), holder)
    assert Queue("interactive", connection=rq_conn).job_ids == [str(a)]  # released
    r = await client.post(f"/api/jobs/{b}/retry", headers=player_h)
    assert r.status_code == 409, r.text
    assert await _active_copies(world, key, player_id) == [a]
    row = await world.row(a)
    row.status = JobStatus.DONE
    row.finished_at = datetime.now(timezone.utc)
    await world.db.commit()
    r = await client.post(f"/api/jobs/{b}/retry", headers=player_h)
    assert r.status_code == 202, r.text
    assert await _active_copies(world, key, player_id) == [b]
    row = await world.row(b)
    assert row.idempotency_key == key and row.depends_on_job_id is None


async def test_retry_hidden_or_preview_is_404(client, world, rq_conn):
    gm_job = await world.job(world.owner, status="failed")
    r = await client.post(f"/api/jobs/{gm_job}/retry", headers=bearer(world.player))
    assert r.status_code == 404 and r.json() == NOT_FOUND
    preview = {**bearer(world.owner), "X-Lorekeeper-Preview": "member"}
    r = await client.post(f"/api/jobs/{gm_job}/retry", headers=preview)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    await world.db.commit()
    assert (await world.row(gm_job)).status == JobStatus.FAILED


async def test_writes_need_a_writable_ctx(world):
    from app.access import MEMBER_VIEW, audience_ctx, NotFound

    job_id = await world.job(world.owner, status="failed")
    view = audience_ctx(world.cid, MEMBER_VIEW, by=await world.ctx(world.owner))
    for action in (cancel_job, retry_job):
        with pytest.raises(NotFound):
            await action(world.db, view, job_id)


async def test_the_reaper_leaves_cancelled_jobs_alone(world):
    conn = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    idle = await world.job(world.owner, status="cancelled", created_at=long_ago)
    stale = await world.job(world.owner, status="cancelled", created_at=long_ago)
    row = await world.row(stale)
    row.heartbeat_at = long_ago
    row.worker_id = "w-gone"
    await world.db.commit()
    try:
        result = await reap(_factory(world), conn)
        for job_id in (idle, stale):
            assert job_id not in result.pushed + result.requeued + result.failed
            row = await world.row(job_id)
            assert row.status == JobStatus.CANCELLED and row.started_at is None
            for q in JobQueue:
                assert str(job_id) not in Queue(q.value, connection=conn).job_ids
            assert await worker.run_job(job_id, _factory(world), "w-test") is None
    finally:
        conn.close()


async def test_the_write_gate_lets_only_a_gm_or_the_starter_write_a_job(world):
    """`can_write` (E0-Access.6) is the gate cancel and retry pass: a GM any
    Job of the Campaign, a Player only a persisted Job they started (a
    transient one, i.e. a create, never: Jobs come only from enqueue)."""
    from app.access import may_write

    gm, player = await world.ctx(world.owner), await world.ctx(world.player)
    own = await world.row(await world.job(world.player, status="queued"))
    others = await world.row(await world.job(world.owner, status="queued"))
    assert may_write(gm, own) and may_write(gm, others)
    assert may_write(player, own)
    assert not may_write(player, others)
    transient = Job(id=uuid.uuid4(), campaign_id=world.cid, kind="system.noop", queue="interactive",
                    idempotency_key="k", ctx_kind="player", created_by=world.player.id)
    assert not may_write(player, transient)


# ── Admin counts ───────────────────────────────────────────────────────────

async def test_job_counts_by_status_and_queue(world):
    before = await job_counts(world.db)
    await world.job(world.owner, status="failed", queue="onsave")
    await world.job(world.owner, status="queued")
    after = await job_counts(world.db)
    assert after["total"] == before["total"] + 2
    assert after["by_status"]["failed"] == before["by_status"]["failed"] + 1
    assert after["by_queue"]["onsave"]["failed"] == before["by_queue"]["onsave"]["failed"] + 1
    assert set(after["by_status"]) == {s.value for s in JobStatus}
    assert set(after["by_queue"]) >= {q.value for q in JobQueue}


async def test_admin_stats_route_is_admin_only(client, world):
    r = await client.get("/api/admin/jobs/stats", headers=bearer(world.owner))
    assert r.status_code in (403, 404)
    world.owner.is_admin = True
    world.db.add(world.owner)
    await world.db.commit()
    r = await client.get("/api/admin/jobs/stats", headers=bearer(world.owner))
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"total", "by_status", "by_queue"}


# ── The stream ─────────────────────────────────────────────────────────────

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


@pytest_asyncio.fixture
async def base_url(serve, db):  # noqa: F811
    from app.main import app

    limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield await serve(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _event(job_id, result_ref=None, **extra) -> dict:
    return {"job_id": str(job_id), "kind": "system.noop", "status": "running", "progress": 0.5, "stage": "S",
            "eta_seconds": 3, "error_code": None, "error_message": None, "result_ref": result_ref, **extra}


async def _raw(client, cid, event, data) -> None:
    await client.publish(pubsub.jobs_channel(cid), json.dumps({"event": event, "data": data}))


async def _frames_until(base_url, world, valkey, headers, messages, marker) -> list:
    """Open the stream, publish `messages` then the `marker` job event, and
    return the frames before the marker (or all of them, when it never
    arrives within 2 s)."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        async with http.stream("GET", f"/api/jobs/stream?campaign_id={world.cid}", headers=headers) as resp:
            assert resp.status_code == 200, await resp.aread()
            assert resp.headers["content-type"].startswith("text/event-stream")
            assert resp.headers["x-accel-buffering"] == "no"
            reader = Reader(resp)
            assert await asyncio.wait_for(reader.frames.get(), 5) == ("subscribed", {})
            for event, data in messages:
                await _raw(valkey, world.cid, event, data)
            await valkey.publish(pubsub.jobs_channel(world.cid), "not json")
            await _raw(valkey, world.cid, "job", marker)
            frames = []
            try:
                while True:
                    frame = await reader.next(timeout=2)
                    if frame == ("job", marker):
                        break
                    frames.append(frame)
            except asyncio.TimeoutError:
                pass
            reader.task.cancel()
            return frames


async def test_player_stream_gets_only_their_jobs_filtered(base_url, world, valkey):
    own = await world.job(world.player, status="running")
    gm_job = await world.job(world.owner, status="running")
    other = await world.job(world.player2, status="running")
    elsewhere = await world.job(world.other_owner, status="running", campaign_id=world.other_cid)
    messages = [("job", _event(gm_job)), ("job", _event(other)), ("job", _event(elsewhere)),
                ("job", _event(uuid.uuid4())), ("job", "junk"), ("invalidate", {"domain": "x", "id": None}),
                ("job", _event(own, result_ref=_ref(world.hidden_entry), leak="secret")),
                ("job", _event(own, result_ref=_ref(world.party_entry, leak="secret")))]
    marker = {**_event(own), "stage": "Marker"}
    frames = await _frames_until(base_url, world, valkey, bearer(world.player), messages, marker)
    assert frames == [("job", _event(own)),
                      ("job", _event(own, result_ref={"kind": "journal", "id": str(world.party_entry)}))]
    text = json.dumps(frames)
    for hidden in (gm_job, other, elsewhere, world.hidden_entry):
        assert str(hidden) not in text
    assert "secret" not in text


async def test_gm_stream_gets_every_job_of_the_campaign_raw(base_url, world, valkey):
    gm_job = await world.job(world.owner, status="running")
    other = await world.job(world.player2, status="running")
    elsewhere = await world.job(world.other_owner, status="running", campaign_id=world.other_cid)
    raw = _ref(world.hidden_entry, note="kept")
    messages = [("job", _event(gm_job, result_ref=raw)), ("job", _event(other)), ("job", _event(elsewhere))]
    marker = {**_event(gm_job), "stage": "Marker"}
    frames = await _frames_until(base_url, world, valkey, bearer(world.co_gm), messages, marker)
    assert frames == [("job", _event(gm_job, result_ref=raw)), ("job", _event(other))]


async def test_preview_stream_gets_no_job_events(base_url, world, valkey):
    gm_job = await world.job(world.owner, status="running")
    headers = {**bearer(world.owner), "X-Lorekeeper-Preview": "member"}
    frames = await _frames_until(base_url, world, valkey, headers, [("job", _event(gm_job))], _event(gm_job))
    assert [f for f in frames if f[0] == "job"] == []


async def test_a_real_job_change_reaches_the_starter(base_url, world, valkey):
    own = await world.job(world.player, status="running")
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as http:
        async with http.stream("GET", f"/api/jobs/stream?campaign_id={world.cid}",
                               headers=bearer(world.player)) as resp:
            reader = Reader(resp)
            assert await asyncio.wait_for(reader.frames.get(), 5) == ("subscribed", {})
            async with _factory(world)() as s:
                row = await s.get(Job, own)
                row.status = JobStatus.DONE
                row.progress = 1.0
                row.result_ref = _ref(world.hidden_entry)
                row.finished_at = datetime.now(timezone.utc)
                await s.commit()
            event, data = await reader.next(timeout=5)
            reader.task.cancel()
    assert event == "job"
    assert data["job_id"] == str(own) and data["status"] == "done" and data["result_ref"] is None


async def test_a_failed_check_ends_the_stream(world, valkey, monkeypatch):
    player = await world.ctx(world.player)
    own = await world.job(world.player, status="running")

    async def broken(session, ctx, data):
        raise JobEventCheckFailed("db down")

    monkeypatch.setattr(access_jobs, "deliverable_job_event", broken)
    gen = job_event_stream(player, bind=world.db.bind)
    assert await asyncio.wait_for(gen.__anext__(), 5) == ("subscribed", {})
    await _raw(valkey, world.cid, "job", _event(own))
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 5)


async def test_stream_outsiders_get_the_one_404(client, world):
    previous = valkey_client.set_valkey(None)
    try:
        missing = await client.get(f"/api/jobs/stream?campaign_id={MISSING}", headers=bearer(world.outsider))
        hidden = await client.get(f"/api/jobs/stream?campaign_id={world.cid}", headers=bearer(world.outsider))
        bad = await client.get("/api/jobs/stream?campaign_id=not-a-uuid", headers=bearer(world.outsider))
    finally:
        valkey_client.set_valkey(previous)
    for r in (missing, hidden, bad):
        assert r.status_code == 404 and r.json() == NOT_FOUND, r.text


# ── Limiter and nginx ──────────────────────────────────────────────────────

def test_every_route_is_limited_per_user():
    import app.main  # noqa: F401

    for name in ("job_stream", "list_campaign_jobs", "get_campaign_job", "retry_campaign_job",
                 "cancel_campaign_job"):
        lims = limiter._route_limits[f"app.api.routes.jobs.{name}"]
        assert lims and all(lim.key_func is user_or_ip for lim in lims), name
    assert all(lim.key_func is user_or_ip for lim in limiter._route_limits["app.api.routes.admin.job_stats"])


def test_stream_route_is_matched_before_the_item_route():
    from app.main import app

    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api/jobs/")]
    assert paths.index("/api/jobs/stream") < paths.index("/api/jobs/{job_id}")


def test_nginx_streams_the_route_unbuffered_for_an_hour():
    from tests.ev4.routes import resolve_route

    loc = resolve_route("/api/jobs/stream")
    assert loc is not None and loc.uri == "/api/jobs/stream" and loc.modifier == "=", loc
    directives = {d.name: d.args for d in loc.directives}
    assert directives["proxy_buffering"] == ["off"]
    assert directives["gzip"] == ["off"]
    assert directives["proxy_read_timeout"] == ["1h"]
    assert directives["limit_req"][0] == "zone=api"
    assert directives["proxy_pass"] == ["http://backend"]
    assert "include" not in directives
    assert resolve_route("/api/jobs/{job_id}").uri == "/api/"
