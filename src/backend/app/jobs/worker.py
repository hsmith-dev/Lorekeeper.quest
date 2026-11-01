"""Running one Job, and the worker process that does it (AD-2, E0-Jobs.2/3).

`run_job` is the single wrapper both dispatch paths use: the RQ worker (via
`perform`, the function every RQ message names) and the JOBS_EAGER in-process
run (app/jobs/outbox.py). For one `queued` row it:

1. claims it: `running`, `started_at`, `heartbeat_at`, `worker_id`,
   `attempts + 1`. A row that is not `queued`, whose `next_run_at` is still in
   the future, or whose dependency is still active is not claimed (None);
2. checks the starter still holds the rights stored at enqueue: `ctx_for`
   finds them, the grant's `access_epoch` is unchanged and their Role ranks at
   least the stored `ctx_kind` (gm > player > anon). Otherwise `failed`,
   `permission_changed`, the handler is never called;
3. for kinds with `llm` in `resources`, resolves the starter's LLM config
   (llm_config_service.resolve_llm_config); none -> `failed`, `llm_config`.
   The handler gets it as `job.llm_config` and the User as `job.starter`, and
   meters with llm_config_service.meter;
4. sets the LLM gate class (the kind's `gate_class`, else the queue's) and a
   gate deadline of now + timeout_s, starts the heartbeat thread, injects
   `job.report`, and runs the handler under the kind's `timeout_s`;
5. writes the outcome. Success: `done`, committed with the handler's writes.
   Failure: the handler's writes roll back, and the error is classified
   (`_failure`). Codes in TERMINAL_CODES fail at once; others go back to
   `queued` with `next_run_at` = now + RETRY_DELAYS_S[attempts - 1] while
   attempts < max_attempts, then `failed`. A requeued row is not pushed again
   here (RQ's current job has the same id): the reaper (E0-Jobs.4) re-pushes
   rows whose `next_run_at` has passed.

The stored message is always readable fixed text or an LLMError's `detail`,
never an exception's own text. Logs carry job_id, kind and campaign_id (also
from code the handler calls, through app.core.logging's JobContextFilter),
never the payload.

The timeout is cooperative: it cancels the handler at its next await, so a
handler that blocks the event loop is not interrupted (sync CPU work belongs
in `asyncio.to_thread`). RQ's `job_timeout` (timeout_s + 60 s) is the
backstop: it kills the work horse and leaves the row `running` for the
E0-Jobs.4 reaper.

`_perform` swaps the process-wide Valkey client (app.core.valkey_client) for
its own; that is safe only because RQ runs one Job per work horse.

`python -m app.jobs.worker` runs `settings.worker_processes` LorekeeperWorker
processes in an RQ WorkerPool on the three queues, highest priority first.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
import sqlalchemy as sa
from rq import Worker
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.pool import NullPool

from app.access.context import CampaignContext, ctx_for
from app.access.policy import ANON, GM, PLAYER, NotFound
from app.clients.errors import ModelServiceUnavailable
from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import LLMConfigError, LLMError, StructuredOutputError
from app.core.logging import job_log_context
from app.core.valkey_client import set_valkey
from app.db.models.job import ACTIVE_STATUSES, Job
from app.db.models.user import User
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs.errors import TERMINAL_CODES
from app.jobs.registry import JobKind, get_kind, load_kind_modules
from app.services import llm_config_service

logger = logging.getLogger(__name__)

# Delay before attempt n+1, indexed by attempts - 1 (AD-4: +10 s, then +60 s).
RETRY_DELAYS_S: tuple[int, ...] = (10, 60)
HEARTBEAT_INTERVAL_S: float = 10
# How long the heartbeat and `job.report` wait for the row lock (the handler's
# own session may hold it if it changed the Job row) before giving up.
_LOCK_TIMEOUT = "2s"
_LOCK_NOT_AVAILABLE = "55P03"  # SQLSTATE lock_not_available (asyncpg LockNotAvailableError)
_HEARTBEAT_JOIN_S = 5

INTERNAL_MESSAGE = "Something went wrong while running this job"
PERMISSION_MESSAGE = "You no longer have access to this Campaign"
UNKNOWN_KIND_MESSAGE = "This kind of job is no longer supported"
LLM_CONFIG_MESSAGE = "No AI model is configured for your account"
AI_OUTPUT_MESSAGE = "AI output unusable"
TIMEOUT_MESSAGE = "This job took too long and was stopped"
MODEL_UNAVAILABLE_MESSAGE = "An AI model service is not available right now"

# The stored ctx_kind the starter must still meet (gm > player > anon).
_ROLE_RANK = {ANON: 0, PLAYER: 1, GM: 2}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_extra(job: Job) -> dict[str, str]:
    return {"job_id": str(job.id), "kind": job.kind, "campaign_id": str(job.campaign_id)}


# ── Claim and outcome ──────────────────────────────────────────────────────

async def _claim(db: AsyncSession, job_id: uuid.UUID, worker_id: str) -> tuple[Job, JobStatus | None] | None:
    """Mark the Job running, or None when it is not runnable (gone, not
    `queued`, not yet due, claimed by another worker, or its dependency still
    active)."""
    now = _now()
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None or job.status != JobStatus.QUEUED:
        return None
    if job.next_run_at is not None and job.next_run_at > now:
        return None  # a retry that is not due yet
    dependency_status = None
    if job.depends_on_job_id is not None:
        status = await db.scalar(sa.select(Job.status).where(Job.id == job.depends_on_job_id))
        if status in ACTIVE_STATUSES:
            return None  # released when the dependency finishes
        dependency_status = JobStatus(status) if status is not None else None
    claimed = await db.scalar(
        sa.update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.QUEUED,
               sa.or_(Job.next_run_at.is_(None), Job.next_run_at <= now))
        .values(status=JobStatus.RUNNING, started_at=now, heartbeat_at=now, attempts=Job.attempts + 1,
                worker_id=worker_id)
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
                  code: JobErrorCode | None = None, message: str | None = None) -> JobStatus:
    """Write a terminal status (with the handler's writes, for `done`)."""
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None:
        return status
    job.status = status
    job.finished_at = _now()
    job.next_run_at = None
    job.error_code = code
    job.error_message = message
    if status == JobStatus.DONE:
        job.progress = 1.0
    await db.commit()
    return status


async def _record_failure(db: AsyncSession, job_id: uuid.UUID, code: JobErrorCode, message: str,
                          extra: dict[str, str]) -> JobStatus:
    """`failed` for a terminal code or the last attempt; otherwise back to
    `queued` with the next retry delay, keeping this attempt's code."""
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None:
        return JobStatus.FAILED
    if code in TERMINAL_CODES or job.attempts >= job.max_attempts:
        logger.warning("job failed: %s", code.value, extra=extra)
        return await _finish(db, job_id, JobStatus.FAILED, code, message)
    delay = RETRY_DELAYS_S[min(max(job.attempts - 1, 0), len(RETRY_DELAYS_S) - 1)]
    job.status = JobStatus.QUEUED
    job.next_run_at = _now() + timedelta(seconds=delay)
    job.finished_at = None
    job.error_code = code
    job.error_message = message
    # The dead attempt's run state goes; its error stays (the last attempt's).
    job.progress = job.stage = job.eta_seconds = job.worker_id = job.heartbeat_at = None
    await db.commit()
    logger.warning("job attempt failed: %s; retry in %ss", code.value, delay, extra=extra)
    return JobStatus.QUEUED


def _failure(exc: BaseException, timed_out: bool = False) -> tuple[JobErrorCode, str]:
    """The (error_code, readable message) a handler failure is stored as."""
    if timed_out:
        return JobErrorCode.TIMEOUT, TIMEOUT_MESSAGE
    if isinstance(exc, StructuredOutputError):
        return JobErrorCode.AI_OUTPUT_UNUSABLE, AI_OUTPUT_MESSAGE
    if isinstance(exc, LLMConfigError):
        return JobErrorCode.LLM_CONFIG, LLM_CONFIG_MESSAGE
    if isinstance(exc, LLMError):
        try:
            code = JobErrorCode(exc.code)
        except ValueError:
            pass
        else:
            detail = exc.detail if isinstance(exc.detail, str) and exc.detail.strip() else INTERNAL_MESSAGE
            return code, detail
    if isinstance(exc, ModelServiceUnavailable):
        return JobErrorCode.MODEL_UNAVAILABLE, MODEL_UNAVAILABLE_MESSAGE
    return JobErrorCode.INTERNAL, INTERNAL_MESSAGE


# ── Rights and config ──────────────────────────────────────────────────────

async def _current_ctx(db: AsyncSession, job: Job) -> CampaignContext | None:
    """The starter's ctx now, or None when they lost the rights the Job was
    started with (gone, another grant epoch, or a lower Role)."""
    if job.ctx_user_id is None:
        return None
    try:
        ctx = await ctx_for(db, job.ctx_user_id, job.campaign_id)
    except NotFound:
        return None
    if ctx.access_epoch != job.access_epoch:
        return None
    if _ROLE_RANK.get(ctx.role, -1) < _ROLE_RANK.get(job.ctx_kind, len(_ROLE_RANK)):
        return None
    return ctx


# ── Heartbeat and progress ─────────────────────────────────────────────────

def _bind_url(session_factory: async_sessionmaker[AsyncSession]) -> Any:
    bind = session_factory.kw.get("bind")
    engine = getattr(bind, "engine", bind)  # an AsyncConnection's engine
    return getattr(engine, "url", None)


class _Heartbeat:
    """Writes `heartbeat_at` every HEARTBEAT_INTERVAL_S from a daemon thread
    with its own event loop and engine, so a handler that blocks the Job's
    event loop still beats. Only this row, while `running` and owned by this
    worker_id."""

    def __init__(self, url: Any, job_id: uuid.UUID, worker_id: str, extra: dict[str, str]):
        self._url = url
        self._job_id = job_id
        self._worker_id = worker_id
        self._extra = extra
        self._interval = HEARTBEAT_INTERVAL_S
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"job-heartbeat-{job_id}", daemon=True)

    def start(self) -> "_Heartbeat":
        if self._url is not None:
            self._thread.start()
        else:
            logger.warning("job heartbeat disabled: no database URL on the session factory", extra=self._extra)
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(_HEARTBEAT_JOIN_S)

    def _run(self) -> None:
        try:
            asyncio.run(self._beat())
        except Exception:
            logger.exception("job heartbeat thread died", extra=self._extra)

    async def _beat(self) -> None:
        engine = None
        try:
            # Event.wait blocks this thread's own loop, which has nothing else to do.
            while not self._stop.wait(self._interval):
                if engine is None:
                    engine = create_async_engine(self._url, poolclass=NullPool)
                try:
                    async with engine.begin() as conn:
                        await conn.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                        await conn.execute(
                            sa.update(Job)
                            .where(Job.id == self._job_id, Job.status == JobStatus.RUNNING,
                                   Job.worker_id == self._worker_id)
                            .values(heartbeat_at=_now())
                        )
                except Exception:
                    logger.warning("job heartbeat write failed", exc_info=True, extra=self._extra)
        finally:
            if engine is not None:
                await engine.dispose()


def _reporter(session_factory: async_sessionmaker[AsyncSession], job: Job, worker_id: str,
              extra: dict[str, str]) -> Callable[[float, str | None, int | None], Awaitable[None]]:
    """`job.report`'s writer: progress, stage and ETA in a short transaction
    of their own (visible before the Job ends)."""

    async def write(progress: float, stage: str | None, eta_seconds: int | None) -> None:
        values = {"progress": progress, "stage": stage, "eta_seconds": eta_seconds}
        try:
            async with session_factory() as s:
                await s.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
                await s.execute(
                    sa.update(Job)
                    .where(Job.id == job.id, Job.status == JobStatus.RUNNING, Job.worker_id == worker_id)
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                await s.commit()
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            # The handler's session holds the row (it changed the Job): the
            # values go out with the Job's own commit instead.
            logger.warning("job progress not written early; it is saved with the job", extra=extra)
            for key, value in values.items():
                setattr(job, key, value)
            return
        # Keep the handler's copy current without marking it dirty.
        for key, value in values.items():
            set_committed_value(job, key, value)

    return write


# ── The wrapper ────────────────────────────────────────────────────────────

async def run_job(job_id: uuid.UUID | str, session_factory: async_sessionmaker[AsyncSession],
                  worker_id: str) -> JobStatus | None:
    """Run one attempt of a Job and return the status it was left in
    (`done`, `failed`, or `queued` for a retry), or None when the Job was not
    runnable (see `_claim`). Handler errors become the row's outcome; only
    database errors propagate."""
    job_id = job_id if isinstance(job_id, uuid.UUID) else uuid.UUID(str(job_id))
    async with session_factory() as db:
        claimed = await _claim(db, job_id, worker_id)
        if claimed is None:
            return None
        job, dependency_status = claimed
        job.dependency_status = dependency_status
        extra = _log_extra(job)
        log_token = job_log_context.set(extra)
        try:
            return await _run_claimed(db, session_factory, job, worker_id, extra)
        finally:
            job_log_context.reset(log_token)


async def _fail_attempt(db: AsyncSession, session_factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID,
                        code: JobErrorCode, message: str, extra: dict[str, str]) -> JobStatus:
    """Roll the attempt's writes back and record the failure (`_record_failure`)."""
    try:
        await db.rollback()
    except Exception:
        # A cancelled query can leave the connection unusable (and holding the
        # Job row): drop it, then record the outcome from a fresh session.
        logger.warning("job session rollback failed; recording the outcome on a new session", extra=extra)
        try:
            await db.invalidate()
        except Exception:
            logger.warning("job session invalidate failed", exc_info=True, extra=extra)
        async with session_factory() as fresh:
            return await _record_failure(fresh, job_id, code, message, extra)
    return await _record_failure(db, job_id, code, message, extra)


async def _prepare(db: AsyncSession, job: Job, kind: JobKind,
                   extra: dict[str, str]) -> tuple[CampaignContext, llm_gate.GateClass] | JobStatus:
    """Rights check, starter, LLM config and gate class. Returns the JobStatus
    when the Job ends here (permission_changed, llm_config)."""
    job_id = job.id  # read before any rollback expires the instance
    ctx = await _current_ctx(db, job)
    starter = await db.get(User, job.ctx_user_id) if ctx is not None else None
    if ctx is None or starter is None:
        await db.rollback()
        logger.info("job starter lost access", extra=extra)
        return await _finish(db, job_id, JobStatus.FAILED, JobErrorCode.PERMISSION_CHANGED, PERMISSION_MESSAGE)
    job.starter = starter
    job.llm_config = None
    if "llm" in kind.resources:
        try:
            job.llm_config = await llm_config_service.resolve_llm_config(db, starter)
        except LLMConfigError:
            await db.rollback()
            logger.info("job has no LLM config", extra=extra)
            return await _finish(db, job_id, JobStatus.FAILED, JobErrorCode.LLM_CONFIG, LLM_CONFIG_MESSAGE)
    return ctx, kind.gate_class or llm_gate.class_for_queue(job.queue)


async def _run_claimed(db: AsyncSession, session_factory: async_sessionmaker[AsyncSession], job: Job,
                       worker_id: str, extra: dict[str, str]) -> JobStatus:
    job_id = job.id
    try:
        kind: JobKind = get_kind(job.kind)
        handler = kind.load_handler()
    except Exception:
        logger.exception("job kind cannot be loaded", extra=extra)
        return await _finish(db, job_id, JobStatus.FAILED, JobErrorCode.INTERNAL, UNKNOWN_KIND_MESSAGE)

    try:
        prepared = await _prepare(db, job, kind, extra)
    except Exception:
        logger.exception("job setup failed", extra=extra)
        job.starter = job.llm_config = None
        return await _fail_attempt(db, session_factory, job_id, JobErrorCode.INTERNAL, INTERNAL_MESSAGE, extra)
    if isinstance(prepared, JobStatus):
        job.starter = job.llm_config = None
        return prepared
    ctx, gate_class = prepared

    job._reporter = _reporter(session_factory, job, worker_id, extra)
    gate_token = llm_gate.current_class.set(gate_class)
    deadline_token = llm_gate.current_deadline.set(time.monotonic() + kind.timeout_s)
    heartbeat = _Heartbeat(_bind_url(session_factory), job_id, worker_id, extra).start()
    error: Exception | None = None
    timed_out = False
    try:
        timeout = asyncio.timeout(kind.timeout_s)
        try:
            async with timeout:
                await handler(job, ctx, db)
                await db.flush()
        except Exception as exc:
            error = exc
            timed_out = timeout.expired()
        if error is None and timeout.expired():
            # The handler swallowed the cancellation and returned: still a timeout.
            error, timed_out = TimeoutError(), True
    finally:
        heartbeat.stop()
        llm_gate.current_deadline.reset(deadline_token)
        llm_gate.current_class.reset(gate_token)
        # Never leave the decrypted config (or the User) on the instance.
        job._reporter = job.starter = job.llm_config = None

    if error is None:
        try:
            # The handler's writes and `done` commit together.
            status = await _finish(db, job_id, JobStatus.DONE)
        except Exception:
            logger.exception("job done commit failed", extra=extra)
            return await _fail_attempt(db, session_factory, job_id, JobErrorCode.INTERNAL, INTERNAL_MESSAGE, extra)
        logger.info("job done", extra=extra)
        return status

    code, message = _failure(error, timed_out)
    if code == JobErrorCode.INTERNAL:
        logger.error("job handler raised %s", type(error).__name__, exc_info=error, extra=extra)
    return await _fail_attempt(db, session_factory, job_id, code, message, extra)


# ── The RQ side ────────────────────────────────────────────────────────────

# Set by LorekeeperWorker in the worker process (its RQ worker name); the
# forked work horse inherits it, so every Job a worker runs carries the same
# worker_id. Outside a LorekeeperWorker: `<host>:<pid>`.
_WORKER_ID: str | None = None


def _worker_id() -> str:
    return _WORKER_ID or f"{socket.gethostname()}:{os.getpid()}"


async def _perform(job_id: str) -> JobStatus | None:
    # Per RQ job: asyncio.run gives each call a new event loop, and asyncpg
    # connections and asyncio redis clients belong to the loop that opened them.
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    valkey = aioredis.from_url(settings.valkey_url, decode_responses=True)
    previous = set_valkey(valkey)
    try:
        return await run_job(job_id, async_sessionmaker(engine, expire_on_commit=False), _worker_id())
    finally:
        set_valkey(previous)
        await valkey.aclose()
        await engine.dispose()


def perform(job_id: str) -> None:
    """The RQ entrypoint: every message is `perform(str(job_id))`."""
    asyncio.run(_perform(job_id))


class LorekeeperWorker(Worker):
    """An RQ worker that knows every Job kind before its first Job: it imports
    the kind-registering modules (registry.KIND_MODULES) at start, and stamps
    the Jobs it runs with its RQ worker name as `worker_id`, so the reaper
    (E0-Jobs.4) can look the worker up in RQ's worker registry."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        load_kind_modules()
        super().__init__(*args, **kwargs)
        global _WORKER_ID
        _WORKER_ID = self.name


def main() -> None:
    """`python -m app.jobs.worker`: settings.worker_processes LorekeeperWorkers
    in an RQ WorkerPool on interactive, onsave and backfill (in that order)."""
    from redis import Redis
    from rq.worker_pool import WorkerPool

    from app.core.logging import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_file)
    load_kind_modules()
    connection = Redis.from_url(settings.valkey_url)
    pool = WorkerPool([q.value for q in JobQueue], connection=connection,
                      num_workers=settings.worker_processes, worker_class=LorekeeperWorker)
    logger.info("starting %d job workers on %s", settings.worker_processes, ", ".join(q.value for q in JobQueue))
    pool.start(burst=False, logging_level=settings.log_level.upper())


__all__ = ["HEARTBEAT_INTERVAL_S", "RETRY_DELAYS_S", "LorekeeperWorker", "main", "perform", "run_job"]


if __name__ == "__main__":
    # Run through the imported module, not __main__, so the worker class and
    # _WORKER_ID are the ones `perform` (app.jobs.worker.perform) sees.
    from app.jobs.worker import main as _main

    _main()
