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
takes a per-retry key `{key}#retry:{campaign}:{starter}` (the partial unique index stays
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
from app.jobs.enqueue import RETRY_KEY_MARK, _like_escape  # a held retry's `{key}#retry:{campaign}:{starter}`
from app.jobs.registry import get_kind

ONLY_QUEUED = "Only queued Jobs can be cancelled"
ONLY_FAILED = "Only failed Jobs can be retried"
UNKNOWN_KIND = "This kind of job is no longer supported"
KEY_IN_USE = "The same work is already queued or running"
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


def _held_prefix(base: str, campaign_id: uuid.UUID) -> str:
    return f"{base}{RETRY_KEY_MARK}{campaign_id}:"


def _base_key(job: Job) -> str:
    """The Job's idempotency key without the per-retry suffix
    (`{key}#retry:{campaign}:{starter}`) a hidden-holder retry gave it.
    `enqueue` refuses keys holding RETRY_KEY_MARK, so only a held retry has it."""
    key = job.idempotency_key
    cut = key.rfind(f"{RETRY_KEY_MARK}{job.campaign_id}:")
    return key[:cut] if cut >= 0 else key


def _held_key(base: str, job: Job, ctx: CampaignContext) -> str:
    """The key a retry held behind a hidden Job takes: one per (Campaign,
    starter, original key); a Job with no starter left shares `none` (only a
    GM, who sees every Job of the Campaign, can retry it). The partial
    unique index on active keys then allows one held copy each, so a second
    retry (sequential or racing) by the starter or a GM, who can both see
    that copy, finds or collides with it and answers 409 instead of queueing
    the work twice. The Campaign in the key keeps the same starter's held
    copies in two Campaigns from colliding (that 409 would reveal the
    hidden holder)."""
    return f"{_held_prefix(base, job.campaign_id)}{job.ctx_user_id or 'none'}"


async def _key_holders(db: AsyncSession, ctx: CampaignContext, job: Job,
                       key: str) -> tuple[uuid.UUID | None, bool]:
    """(a hidden active Job holding `key` to wait behind, whether ctx can see
    any active holder). Holders are the active Jobs other than `job` whose
    key is `key` (in any Campaign: the index is global) or a held retry's
    `{key}#retry:{job's Campaign}:...`; they are locked
    FOR SHARE (a worker finishing one waits for this transaction, so its
    after-commit release sees a dependent written here). The exact-key
    holder is preferred to wait behind. (None, False) when the key is free."""
    exact = Job.idempotency_key == key
    rows = (await db.execute(
        sa.select(Job.id, exact.label("exact")).where(
            sa.or_(exact, Job.idempotency_key.like(f"{_like_escape(_held_prefix(key, job.campaign_id))}%",
                                                   escape="\\")),
            Job.id != job.id, Job.status.in_([s.value for s in ACTIVE_STATUSES]))
        .order_by(sa.case((exact, 0), else_=1), Job.created_at, Job.id)
        .with_for_update(read=True)
    )).all()
    if not rows:
        return None, False
    ids = [r.id for r in rows]
    visible = await db.scalar(scoped_select(Job, ctx).where(Job.id.in_(ids)).with_only_columns(Job.id).limit(1))
    return ids[0], visible is not None


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
        hidden_holder, seen = await _key_holders(db, ctx, job, base)
        if seen:
            raise JobConflict(KEY_IN_USE)  # the ctx can see a Job holding the key
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
                    job.idempotency_key = _held_key(base, job, ctx)
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
