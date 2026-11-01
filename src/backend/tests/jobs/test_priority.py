"""E0-Jobs.5: queue priority (interactive > onsave > backfill) with a real RQ
burst worker on fakeredis and, as `real`, the CI Valkey. One Campaign's
backfill delays another Campaign's on-save Job by at most one Job: the
running one."""
from __future__ import annotations

import asyncio
import threading
import uuid

import sqlalchemy as sa

from app.access.context import ctx_for
from app.db.models import Campaign, Genre, Job, User
from app.domain.enums import JobQueue, JobStatus
from app.jobs import enqueue, outbox
from app.jobs.registry import JobKind, register
from tests.jobs.test_reaper import _drain, conn  # noqa: F401  (conn: fixture)

ORDER: list[str] = []
_LOCK = threading.Lock()


async def note(job, ctx, db):
    with _LOCK:
        ORDER.append(job.payload["name"])
    push = job.payload.get("push")
    if push:  # a GM saves an entry (another Campaign) while this backfill runs
        await asyncio.to_thread(outbox.push, uuid.UUID(push), JobQueue.ONSAVE, "test_p.onsave")


register(JobKind(name="test_p.backfill", queue=JobQueue.BACKFILL, timeout_s=10, handler=f"{__name__}:note"))
register(JobKind(name="test_p.onsave", queue=JobQueue.ONSAVE, timeout_s=10, handler=f"{__name__}:note"))
register(JobKind(name="test_p.interactive", queue=JobQueue.INTERACTIVE, timeout_s=10,
                 handler=f"{__name__}:note"))


async def _campaign(db) -> Campaign:
    owner = User(email=f"prio-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                 display_name="owner", access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Priority", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c


async def _enqueue(db, c: Campaign, kind: str, payload: dict) -> uuid.UUID:
    ctx = await ctx_for(db, c.user_id, c.id)
    job_id = await enqueue(db, ctx, kind, payload, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()  # eager off (conn): pushed in this order
    return job_id


async def _unpushed(db, c: Campaign, kind: str, payload: dict) -> Job:
    row = Job(campaign_id=c.id, kind=kind, queue=JobQueue.ONSAVE, idempotency_key=f"test:{uuid.uuid4().hex}",
              ctx_kind="gm", ctx_user_id=c.user_id, created_by=c.user_id, access_epoch=0, payload=payload)
    db.add(row)
    await db.commit()
    return row


async def test_an_onsave_job_waits_for_at_most_the_running_backfill(db, conn, monkeypatch):
    ORDER.clear()
    backfilling, saving = await _campaign(db), await _campaign(db)
    onsave = await _unpushed(db, saving, "test_p.onsave", {"name": "O"})
    ids = [await _enqueue(db, backfilling, "test_p.backfill",
                          {"name": f"B{i}", **({"push": str(onsave.id)} if i == 1 else {})})
           for i in range(1, 6)]
    _drain(conn, monkeypatch)
    assert ORDER == ["B1", "O", "B2", "B3", "B4", "B5"]
    statuses = (await db.execute(sa.select(Job.status).where(Job.id.in_([*ids, onsave.id])))).scalars().all()
    assert set(statuses) == {JobStatus.DONE}


async def test_at_rest_the_higher_queue_goes_first(db, conn, monkeypatch):
    ORDER.clear()
    backfilling, saving = await _campaign(db), await _campaign(db)
    for i in range(1, 6):
        await _enqueue(db, backfilling, "test_p.backfill", {"name": f"B{i}"})
    await _enqueue(db, saving, "test_p.onsave", {"name": "O"})
    _drain(conn, monkeypatch)
    assert ORDER.index("O") <= 1  # behind at most one backfill Job
    assert ORDER == ["O", "B1", "B2", "B3", "B4", "B5"]


async def test_interactive_goes_before_onsave_and_backfill(db, conn, monkeypatch):
    ORDER.clear()
    c = await _campaign(db)
    await _enqueue(db, c, "test_p.backfill", {"name": "B"})
    await _enqueue(db, c, "test_p.onsave", {"name": "O"})
    await _enqueue(db, c, "test_p.interactive", {"name": "I"})
    _drain(conn, monkeypatch)
    assert ORDER == ["I", "O", "B"]
