"""Cancel, retry and count Jobs (E0-Jobs.7, AD-4, AD-5).

    job = await cancel_job(db, ctx, job_id)     # queued -> cancelled, committed; JobConflict otherwise
    job_id = await retry_job(db, ctx, job_id)   # failed -> queued (same row), committed and pushed
    stats = await job_counts(db)                 # admin: counts by status and queue

Both writes need a user's writable ctx (a reduced or anonymous one is
`not_found()`), pass the write gate (`app.access.can_write`: a GM, or the
Player who started the Job), and read the Job through `app.access.get_job`: a Player
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
idempotency key must be free of Jobs the ctx can see: an active Job holding
it that `scoped_select(Job, ctx)` returns is a 409. A holder the ctx cannot
see (another starter's Job, or one in another Campaign) must not be revealed
(E0-QA.14, EV-4): the retry answers exactly like a free key, but the row
takes a per-retry key `{key}#retry:{id}` (the partial unique index stays
satisfied), `depends_on_job_id` = the holder (locked FOR SHARE), stays
`queued` and is not pushed; the outbox releases it when the holder ends
(the work runs again then: kinds are idempotent on content-derived keys).
`queue_position` counts only visible Jobs and `depends_on_job_id` is never
serialised, so the wait looks like a busy queue. A lost race on the index
re-runs the check. When
the starter retries their own Job, the row takes their current grant's
`access_epoch` (a Job that failed `permission_changed` after a demote and a
re-promote can run again); `ctx_kind` and `ctx_user_id` stay, so the worker
still fails a starter whose Role really dropped, and a GM retrying a Player's
Job still runs it as that Player (at its stored epoch).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import can_write, get_job, scoped_select
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
# A retry held behind a hidden Job takes `{key}#retry:{job id}`.
RETRY_KEY_MARK = "#retry:"
_RETRY_ATTEMPTS = 3


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
    can_write(ctx, job)  # the single write gate: a GM, or the Job's starter
    if JobStatus(job.status) != JobStatus.QUEUED:
        raise JobConflict(ONLY_QUEUED)
    job.status = JobStatus.CANCELLED
    job.finished_at = _now()
    job.next_run_at = None
    await db.commit()
    return job


def _base_key(job: Job) -> str:
    """The Job's idempotency key without the per-retry suffix a hidden-holder
    retry gave it."""
    suffix = f"{RETRY_KEY_MARK}{job.id}"
    key = job.idempotency_key
    return key[: -len(suffix)] if key.endswith(suffix) else key


async def _key_holder(db: AsyncSession, ctx: CampaignContext, job_id: uuid.UUID,
                      key: str) -> tuple[uuid.UUID, bool] | None:
    """The active Job (other than `job_id`) holding `key`, locked FOR SHARE
    (a worker finishing it waits for this transaction, so its after-commit
    release sees a dependent written here), and whether ctx may see it
    (`scoped_select`). None when the key is free."""
    holder = await db.scalar(
        sa.select(Job.id).where(Job.idempotency_key == key, Job.id != job_id,
                                Job.status.in_([s.value for s in ACTIVE_STATUSES]))
        .limit(1).with_for_update(read=True)
    )
    if holder is None:
        return None
    visible = await db.scalar(scoped_select(Job, ctx).where(Job.id == holder).with_only_columns(Job.id))
    return holder, visible is not None


async def retry_job(db: AsyncSession, ctx: CampaignContext, job_id: Any) -> uuid.UUID:
    """Put a failed Job back in `queued` (same row, `attempts` 0) and commit;
    it is pushed after commit. JobConflict (nothing written) when the Job
    is not failed, its kind is no longer registered, or another active Job
    the ctx can see holds its idempotency key. A holder the ctx cannot see
    answers the same as a free key: the row waits `queued` behind it,
    unpushed, on a per-retry key (module docstring)."""
    _require_writer(ctx)
    job = await get_job(db, ctx, job_id, for_update=True)
    can_write(ctx, job)  # the single write gate: a GM, or the Job's starter
    if JobStatus(job.status) != JobStatus.FAILED:
        raise JobConflict(ONLY_FAILED)
    try:
        kind = get_kind(job.kind)
    except ValueError:
        raise JobConflict(UNKNOWN_KIND) from None
    job_pk, base = job.id, _base_key(job)
    for _ in range(_RETRY_ATTEMPTS):
        holder = await _key_holder(db, ctx, job_pk, base)
        if holder is not None and holder[1]:
            raise JobConflict(KEY_IN_USE)  # the ctx can see the Job holding the key
        hidden_holder = holder[0] if holder is not None else None
        try:
            # A concurrent enqueue may take the key between the check and here:
            # the partial unique index decides. The savepoint opens BEFORE the
            # row changes (begin_nested flushes pending changes first, so a
            # change made earlier would fail outside it and break the whole
            # transaction); a conflict rolls back only the savepoint, writes
            # nothing and leaves the session usable.
            async with db.begin_nested():
                job.status = JobStatus.QUEUED
                job.queue = kind.queue
                if ctx.user_id == job.ctx_user_id:
                    job.access_epoch = ctx.access_epoch  # the starter's grant now
                job.attempts = 0
                job.progress = job.stage = job.eta_seconds = None
                job.error_code = job.error_message = None
                job.result_ref = None
                job.worker_id = job.heartbeat_at = None
                job.started_at = job.finished_at = job.next_run_at = None
                if hidden_holder is None:
                    if job.idempotency_key != base:
                        job.depends_on_job_id = None  # the hold an earlier retry set is over
                    job.idempotency_key = base
                else:
                    # Held behind a Job the ctx cannot see: a key of its own
                    # (the partial unique index holds), released by the
                    # outbox when the holder ends. Answered like any retry.
                    job.idempotency_key = f"{base}{RETRY_KEY_MARK}{job_pk}"
                    job.depends_on_job_id = hidden_holder
                await db.flush()
        except IntegrityError as exc:
            if "uq_jobs_idempotency_key_active" not in str(exc.orig):
                raise
            # Lost a race on the key: reload the row (the savepoint's rollback
            # expired it) and run the check again.
            job = await get_job(db, ctx, job_pk, for_update=True)
            continue
        break
    else:
        raise JobConflict(KEY_IN_USE)
    if hidden_holder is not None:
        job_id = job.id
        await db.commit()  # not pushed: queued until the holder ends
        return job_id
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
