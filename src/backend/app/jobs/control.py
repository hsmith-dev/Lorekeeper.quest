"""Cancel, retry and count Jobs (E0-Jobs.7, AD-4, AD-5).

    job = await cancel_job(db, ctx, job_id)     # queued -> cancelled, committed; JobConflict otherwise
    job_id = await retry_job(db, ctx, job_id)   # failed -> queued (same row), committed and pushed
    stats = await job_counts(db)                 # admin: counts by status and queue

Both writes need a user's writable ctx (a reduced or anonymous one is
`not_found()`), and read the Job through `app.access.get_job`: a Player
reaches only the Jobs they started, a GM every Job of the Campaign, and a
hidden id is the one 404. Each commits its own transaction (the row lock is
held until then). A JobConflict writes nothing and leaves the transaction to
the caller (a request's session is closed, and the lock released, when the
request ends).

**Cancel** only a `queued` Job. The row is locked `FOR UPDATE` and written
through the ORM (`cancelled`, `finished_at`), so the outbox releases its
dependents and the `job` event goes out after commit. It races the worker's
claim safely: the claim (app/jobs/worker.py `_claim`) is a conditional
`UPDATE ... WHERE status = 'queued'`, which waits for this lock and then
matches nothing, and a claim that committed first leaves the row `running`,
which this lock then reads (409). The reaper only touches `running` and
`queued` rows, so a cancelled Job never runs. RQ may still hold its message;
the claim skips it.

**Retry** only a `failed` Job of a still-registered kind: the same row goes
back to `queued` with `attempts` 0 and its run state and error cleared, and
is pushed after commit through the outbox (`record_pending`). Its
idempotency key must be free: an active Job holding it now is a 409.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import get_job
from app.access.context import CampaignContext
from app.access.policy import not_found
from app.db.models.job import ACTIVE_STATUSES, Job
from app.domain.enums import JobQueue, JobStatus
from app.jobs import outbox
from app.jobs.registry import get_kind

ONLY_QUEUED = "Only queued Jobs can be cancelled"
ONLY_FAILED = "Only failed Jobs can be retried"
UNKNOWN_KIND = "This kind of job is no longer supported"
KEY_IN_USE = "The same work is already queued or running"


class JobConflict(Exception):
    """The Job is in a state the action does not apply to (the route's 409)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_writer(ctx: CampaignContext) -> None:
    if not isinstance(ctx, CampaignContext) or ctx.read_only or ctx.user_id is None:
        not_found()


async def cancel_job(db: AsyncSession, ctx: CampaignContext, job_id: Any) -> Job:
    """Cancel a queued Job and commit; the cancelled row comes back.
    JobConflict (nothing written) for any other status."""
    _require_writer(ctx)
    job = await get_job(db, ctx, job_id, for_update=True)
    if JobStatus(job.status) != JobStatus.QUEUED:
        raise JobConflict(ONLY_QUEUED)
    job.status = JobStatus.CANCELLED
    job.finished_at = _now()
    job.next_run_at = None
    await db.commit()
    return job


async def retry_job(db: AsyncSession, ctx: CampaignContext, job_id: Any) -> uuid.UUID:
    """Put a failed Job back in `queued` (same row, `attempts` 0) and commit;
    it is pushed after commit. JobConflict (nothing written) when the Job
    is not failed, its kind is no longer registered, or another active Job
    holds its idempotency key."""
    _require_writer(ctx)
    job = await get_job(db, ctx, job_id, for_update=True)
    if JobStatus(job.status) != JobStatus.FAILED:
        raise JobConflict(ONLY_FAILED)
    try:
        kind = get_kind(job.kind)
    except ValueError:
        raise JobConflict(UNKNOWN_KIND) from None
    holder = await db.scalar(
        sa.select(Job.id).where(Job.idempotency_key == job.idempotency_key, Job.id != job.id,
                                Job.status.in_([s.value for s in ACTIVE_STATUSES])).limit(1)
    )
    if holder is not None:
        raise JobConflict(KEY_IN_USE)
    job.status = JobStatus.QUEUED
    job.queue = kind.queue
    job.attempts = 0
    job.progress = job.stage = job.eta_seconds = None
    job.error_code = job.error_message = None
    job.result_ref = None
    job.worker_id = job.heartbeat_at = None
    job.started_at = job.finished_at = job.next_run_at = None
    try:
        # A concurrent enqueue may take the key between the check and here:
        # the partial unique index decides, and this write rolls back.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        if "uq_jobs_idempotency_key_active" in str(exc.orig):
            raise JobConflict(KEY_IN_USE) from None
        raise
    outbox.record_pending(db.sync_session, job.id, kind.queue, kind.name)
    job_id = job.id
    await db.commit()
    return job_id


async def job_counts(db: AsyncSession) -> dict[str, Any]:
    """Every Job's count by status and by queue and status, across all
    Campaigns (the admin System tab; operators only, no Campaign data)."""
    statuses = [s.value for s in JobStatus]
    by_status = {s: 0 for s in statuses}
    by_queue = {q.value: {s: 0 for s in statuses} for q in JobQueue}
    rows = (await db.execute(
        sa.select(Job.queue, Job.status, sa.func.count()).group_by(Job.queue, Job.status)
    )).all()
    for queue, status, count in rows:
        queue, status = getattr(queue, "value", queue), getattr(status, "value", status)
        by_status[status] = by_status.get(status, 0) + count
        by_queue.setdefault(queue, {s: 0 for s in statuses})[status] = count
    return {"total": sum(by_status.values()), "by_status": by_status, "by_queue": by_queue}


__all__ = ["JobConflict", "KEY_IN_USE", "ONLY_FAILED", "ONLY_QUEUED", "UNKNOWN_KIND", "cancel_job", "job_counts",
           "retry_job"]
