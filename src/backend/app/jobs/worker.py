"""Running one Job (AD-2, E0-Jobs.2).

`run_job` is the single wrapper both dispatch paths use: the RQ worker (via
`perform`, the function every RQ message names) and the JOBS_EAGER in-process
run (app/jobs/outbox.py). It claims the `queued` row, rebuilds the starter's
ctx, runs the kind's handler and writes the outcome:

* the handler returns -> `done` (its writes and the status in one commit);
* it raises an LLMError -> `failed` with that error's code and message;
* anything else -> `failed`, error_code `internal`;
* the starter is no longer a Member -> `failed`, `permission_changed`.

E0-Jobs.2 is minimal on purpose: no retries, heartbeats, timeouts,
permission-epoch checks or LLM config (E0-Jobs.3, LorekeeperWorker).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.access.context import ctx_for
from app.access.policy import NotFound
from app.core.config import get_settings
from app.core.errors import LLMError
from app.db.models.job import ACTIVE_STATUSES, Job
from app.domain.enums import JobErrorCode, JobStatus
from app.jobs.registry import get_kind

logger = logging.getLogger(__name__)

INTERNAL_MESSAGE = "Something went wrong while running this job"
PERMISSION_MESSAGE = "You no longer have access to this Campaign"
UNKNOWN_KIND_MESSAGE = "This kind of job is no longer supported"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_extra(job: Job) -> dict[str, str]:
    return {"job_id": str(job.id), "kind": job.kind, "campaign_id": str(job.campaign_id)}


async def _claim(db: AsyncSession, job_id: uuid.UUID, worker_id: str) -> tuple[Job, JobStatus | None] | None:
    """Mark the Job running, or None when it is not runnable (gone, not
    `queued`, claimed by another worker, or its dependency still active)."""
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None or job.status != JobStatus.QUEUED:
        return None
    dependency_status = None
    if job.depends_on_job_id is not None:
        status = await db.scalar(sa.select(Job.status).where(Job.id == job.depends_on_job_id))
        if status in ACTIVE_STATUSES:
            return None  # released when the dependency finishes
        dependency_status = JobStatus(status) if status is not None else None
    claimed = await db.scalar(
        sa.update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
        .values(status=JobStatus.RUNNING, started_at=_now(), attempts=Job.attempts + 1, worker_id=worker_id)
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    if claimed is None:
        await db.rollback()
        return None
    await db.commit()
    job = await db.get(Job, job_id, populate_existing=True)
    return job, dependency_status


async def _finish(db: AsyncSession, job_id: uuid.UUID, status: JobStatus,
                  code: JobErrorCode | None = None, message: str | None = None) -> None:
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None:
        return
    job.status = status
    job.finished_at = _now()
    job.error_code = code
    job.error_message = message
    if status == JobStatus.DONE:
        job.progress = 1.0
    await db.commit()


def _failure(exc: BaseException) -> tuple[JobErrorCode, str]:
    if isinstance(exc, LLMError):
        try:
            return JobErrorCode(exc.code), exc.detail
        except ValueError:
            pass
    return JobErrorCode.INTERNAL, INTERNAL_MESSAGE


async def run_job(job_id: uuid.UUID | str, session_factory: async_sessionmaker[AsyncSession],
                  worker_id: str) -> JobStatus | None:
    """Run one Job to a terminal status and return it, or None when the Job
    was not runnable (see `_claim`). Handler errors become `failed` rows;
    only database errors propagate."""
    job_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
    async with session_factory() as db:
        claimed = await _claim(db, job_id, worker_id)
        if claimed is None:
            return None
        job, dependency_status = claimed
        job.dependency_status = dependency_status
        extra = _log_extra(job)

        try:
            kind = get_kind(job.kind)
            handler = kind.load_handler()
        except Exception:
            logger.exception("job kind cannot be loaded", extra=extra)
            await _finish(db, job_id, JobStatus.FAILED, JobErrorCode.INTERNAL, UNKNOWN_KIND_MESSAGE)
            return JobStatus.FAILED

        try:
            if job.ctx_user_id is None:
                raise NotFound()
            ctx = await ctx_for(db, job.ctx_user_id, job.campaign_id)
        except NotFound:
            await db.rollback()
            logger.info("job starter lost access", extra=extra)
            await _finish(db, job_id, JobStatus.FAILED, JobErrorCode.PERMISSION_CHANGED, PERMISSION_MESSAGE)
            return JobStatus.FAILED

        try:
            await handler(job, ctx, db)
            await db.flush()
        except Exception as exc:
            await db.rollback()
            code, message = _failure(exc)
            if code == JobErrorCode.INTERNAL:
                logger.exception("job handler failed", extra=extra)
            else:
                logger.warning("job handler failed: %s", code, extra=extra)
            await _finish(db, job_id, JobStatus.FAILED, code, message)
            return JobStatus.FAILED

        # The handler's writes and `done` commit together.
        await _finish(db, job_id, JobStatus.DONE)
        logger.info("job done", extra=extra)
        return JobStatus.DONE


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _perform(job_id: str) -> JobStatus | None:
    # One engine per RQ job: asyncio.run gives each call a new event loop and
    # asyncpg connections belong to the loop that opened them.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        return await run_job(job_id, async_sessionmaker(engine, expire_on_commit=False), _worker_id())
    finally:
        await engine.dispose()


def perform(job_id: str) -> None:
    """The RQ entrypoint: every message is `perform(str(job_id))`."""
    asyncio.run(_perform(job_id))


__all__ = ["perform", "run_job"]
