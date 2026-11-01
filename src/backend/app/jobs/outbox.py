"""The transactional outbox for Jobs (AD-2, E0-Jobs.2).

`enqueue` writes a `jobs` row and records its id in `session.info`. Only when
the session's transaction commits does `after_commit` hand the id on, so a
rolled-back Job is never pushed and a pushed Job always has its row:

* RQ (the default): `perform(str(job_id))` is pushed to the kind's queue on
  Valkey, with the Job id as the RQ job id, no RQ retry and result_ttl=0. The
  message carries nothing else; the row is the authority. A failed push is
  logged and swallowed: the row stays `queued` and the reaper (E0-Jobs.4)
  pushes it again.
* JOBS_EAGER=1 (tests): `run_job` runs in-process before `commit()` returns,
  through the same wrapper as the worker, so the row is final after commit.
  Errors are logged, never raised from commit.

Dependents: `after_flush` notes every Job whose status is flushed to a
terminal value (any ORM write: the worker, a cancel, the reaper). After
commit, every `queued` Job depending on one of them is dispatched the same way.

The listeners are on the sync `Session` class, so they apply to every
AsyncSession. `after_commit` runs inside the AsyncSession's greenlet, which is
what lets `await_only` await the push (via `asyncio.to_thread`, the redis
client is sync) or the eager run before commit returns. The follow-up queries
use a new session on the same engine: the committed transaction is over.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, SessionTransaction, aliased, attributes
from sqlalchemy.util.concurrency import await_only, in_greenlet

from app.core.config import get_settings
from app.db.models.job import Job
from app.domain.enums import JobQueue, JobStatus

logger = logging.getLogger(__name__)

PENDING_KEY = "lorekeeper.jobs.pending"
FINISHED_KEY = "lorekeeper.jobs.finished"
PERFORM = "app.jobs.worker.perform"
TERMINAL_STATUSES = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})
EAGER_WORKER_ID = "eager"


@dataclass(frozen=True)
class _Pending:
    job_id: uuid.UUID
    queue: JobQueue
    kind: str
    transaction: SessionTransaction | None


def record_pending(session: Session, job_id: uuid.UUID, queue: JobQueue, kind: str) -> None:
    """Dispatch `job_id` when `session`'s transaction commits (enqueue's
    hook). Tagged with the innermost open transaction, so rolling back a
    savepoint drops the Jobs enqueued inside it."""
    txn = session.get_nested_transaction() or session.get_transaction()
    session.info.setdefault(PENDING_KEY, []).append(_Pending(job_id, JobQueue(queue), kind, txn))


# ── The RQ connection ──────────────────────────────────────────────────────

_connection: Any = None


def get_connection() -> Any:
    """The sync redis client RQ pushes with (settings.valkey_url)."""
    global _connection
    if _connection is None:
        from redis import Redis

        _connection = Redis.from_url(get_settings().valkey_url)
    return _connection


def set_connection(connection: Any) -> None:
    """Replace the RQ connection (tests: fakeredis or a test Valkey); None
    goes back to settings.valkey_url on next use."""
    global _connection
    _connection = connection


# RQ's own timeout sits above the kind's timeout_s: the wrapper (E0-Jobs.3)
# enforces timeout_s and writes the row; RQ's kill is only the backstop.
RQ_TIMEOUT_GRACE_S = 60


def rq_timeout(kind: str) -> int:
    from app.jobs.registry import KINDS

    job_kind = KINDS.get(kind)
    return (job_kind.timeout_s if job_kind is not None else 180) + RQ_TIMEOUT_GRACE_S


def push(job_id: uuid.UUID, queue: JobQueue | str, kind: str) -> None:
    """Push one Job to RQ. Sync (redis-py): call it off the event loop."""
    from rq import Queue

    Queue(JobQueue(queue).value, connection=get_connection()).enqueue(
        PERFORM, str(job_id), job_id=str(job_id), result_ttl=0, job_timeout=rq_timeout(kind),
    )


# ── Dispatch ───────────────────────────────────────────────────────────────

def _session_factory(bind: Engine | Connection | AsyncEngine) -> async_sessionmaker[AsyncSession]:
    if isinstance(bind, Connection):
        bind = bind.engine
    engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _dispatch_one(job_id: uuid.UUID, queue: JobQueue, kind: str,
                        session_factory: async_sessionmaker[AsyncSession]) -> None:
    if get_settings().jobs_eager:
        from app.jobs.worker import run_job  # lazy: worker imports this module

        try:
            await run_job(job_id, session_factory, EAGER_WORKER_ID)
        except Exception:
            logger.exception("eager job run failed", extra={"job_id": str(job_id)})
        return
    try:
        await asyncio.to_thread(push, job_id, queue, kind)
    except Exception:
        # The row stays queued; the reaper (E0-Jobs.4) pushes it again.
        logger.exception("job push failed; left queued for the reaper",
                         extra={"job_id": str(job_id), "queue": str(queue)})


async def _released_dependents(session_factory: async_sessionmaker[AsyncSession],
                               finished: Iterable[uuid.UUID]) -> list[tuple[uuid.UUID, JobQueue, str]]:
    """`queued` Jobs whose dependency is one of `finished` and is terminal now
    (re-checked: a status flushed in a rolled-back savepoint releases nothing)."""
    dep = aliased(Job)
    async with session_factory() as db:
        rows = await db.execute(
            sa.select(Job.id, Job.queue, Job.kind)
            .join(dep, dep.id == Job.depends_on_job_id)
            .where(Job.depends_on_job_id.in_(list(finished)),
                   Job.status == JobStatus.QUEUED,
                   dep.status.in_([s.value for s in TERMINAL_STATUSES]))
            .order_by(Job.created_at, Job.id)
        )
        return [(row.id, JobQueue(row.queue), row.kind) for row in rows]


async def dispatch(bind: Engine | Connection | AsyncEngine, pending: Iterable[tuple[uuid.UUID, JobQueue, str]],
                   finished: Iterable[uuid.UUID] = ()) -> None:
    """Hand committed Jobs on (RQ push, or the eager run), then release the
    `queued` dependents of the Jobs in `finished`. Never raises."""
    factory = _session_factory(bind)
    sent: set[uuid.UUID] = set()
    for job_id, queue, kind in pending:
        if job_id not in sent:
            sent.add(job_id)
            await _dispatch_one(job_id, queue, kind, factory)
    finished = list(finished)
    if not finished:
        return
    try:
        dependents = await _released_dependents(factory, finished)
    except Exception:
        logger.exception("releasing job dependents failed; left queued for the reaper")
        return
    for job_id, queue, kind in dependents:
        # A dependent enqueued in this same transaction against an already
        # terminal dependency was in `pending`: push it once.
        if job_id not in sent:
            sent.add(job_id)
            await _dispatch_one(job_id, queue, kind, factory)


# ── Session listeners ──────────────────────────────────────────────────────

def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


@event.listens_for(Session, "after_flush")
def _note_finished_jobs(session: Session, flush_context: Any) -> None:
    # Pre-flush state is still visible here: the history of what was flushed.
    for obj in (*session.new, *session.dirty):
        if not isinstance(obj, Job):
            continue
        added = attributes.get_history(obj, "status").added
        if added and added[-1] in TERMINAL_STATUSES and obj.id is not None:
            session.info.setdefault(FINISHED_KEY, set()).add(obj.id)


@event.listens_for(Session, "after_soft_rollback")
def _drop_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop(PENDING_KEY, None)
        session.info.pop(FINISHED_KEY, None)
        return
    pending = session.info.get(PENDING_KEY)
    if pending:
        session.info[PENDING_KEY] = [p for p in pending if not _within(p.transaction, previous_transaction)]


@event.listens_for(Session, "after_transaction_end")
def _clear_on_end(session: Session, transaction: SessionTransaction) -> None:
    # after_commit has already taken what it dispatches; a root transaction
    # that ends any other way (close() without commit) must leave nothing.
    if transaction.parent is None:
        session.info.pop(PENDING_KEY, None)
        session.info.pop(FINISHED_KEY, None)


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        # A savepoint release (begin_nested() exiting): not durable yet.
        return
    pending = session.info.pop(PENDING_KEY, None) or []
    finished = session.info.pop(FINISHED_KEY, None) or set()
    if not pending and not finished:
        return
    if not in_greenlet():
        # A plain sync Session (no event loop to await on): nothing in the
        # app commits Jobs this way; the reaper (E0-Jobs.4) picks them up.
        logger.warning("jobs committed outside an AsyncSession were not dispatched",
                       extra={"job_ids": [str(p.job_id) for p in pending]})
        return
    try:
        await_only(dispatch(session.get_bind(), [(p.job_id, p.queue, p.kind) for p in pending], finished))
    except Exception:
        logger.exception("job dispatch after commit failed")


__all__ = ["dispatch", "get_connection", "push", "record_pending", "set_connection"]
