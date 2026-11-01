"""`job` events after every commit that changes a Job row (AD-5, E0-Jobs.6).

    job.status = JobStatus.DONE
    await db.commit()          # then publish_job(job.campaign_id, job_event(row)) on jobs:{campaign_id}

* **What changes a row.** An ORM write is noted by the `after_flush`
  listener here: a new Job, or a change to one of the event's fields
  (status, progress, stage, eta_seconds, error_code, error_message,
  result_ref). A raw `sa.update` is invisible to it, so its writer calls
  `queue_job_event(session, job_id, status_changed=...)` itself (the
  worker's claim and `job.report`'s writer, app/jobs/worker.py).
* **When.** The notes are deferred on the session (app/core/after_commit.py):
  nothing goes out unless the root transaction commits; a rollback of the
  root, or of the savepoint the change was flushed in, drops them.
* **What goes out.** After commit the channel reads the committed rows (one
  SELECT per committing session, skipped when there is no Valkey client) and
  publishes each one's current state. Reading instead of snapshotting at
  flush keeps the last event right: under JOBS_EAGER the Job runs inside its
  enqueuing commit, so a flush snapshot (`queued`) would go out after `done`.
* **Throttle.** A note whose status changed is a status event (never
  throttled); otherwise it is progress-only (at most one per Job per second,
  app/core/pubsub.py).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, attributes

from app.core import pubsub
from app.core.after_commit import committed_bind, defer, register_channel
from app.core.valkey_client import get_valkey
from app.db.models.job import Job
from app.jobs.outbox import _session_factory

logger = logging.getLogger(__name__)

CHANNEL = "job_events"
# The Job attributes a `job` event carries (job_id and kind never change).
EVENT_ATTRS = ("status", "progress", "stage", "eta_seconds", "error_code", "error_message", "result_ref")


@dataclass(frozen=True)
class _Change:
    job_id: uuid.UUID
    status_changed: bool


def _value(value: Any) -> Any:
    return getattr(value, "value", value)  # StrEnum -> its str


def job_event(job: Job) -> dict[str, Any]:
    """The `job` event for a row (AD-5 fields)."""
    return {
        "job_id": str(job.id),
        "kind": job.kind,
        "status": _value(job.status),
        "progress": job.progress,
        "stage": job.stage,
        "eta_seconds": job.eta_seconds,
        "error_code": _value(job.error_code),
        "error_message": job.error_message,
        "result_ref": job.result_ref,
    }


def queue_job_event(session: Any, job_id: uuid.UUID, *, status_changed: bool) -> None:
    """Publish `job_id`'s `job` event after `session` (an AsyncSession or
    its sync Session) commits. For writers the `after_flush` listener cannot
    see (raw UPDATEs)."""
    defer(session, CHANNEL, _Change(job_id, bool(status_changed)))


def _history(obj: Job, name: str) -> attributes.History:
    # Never load an expired attribute inside the flush: unloaded means unchanged.
    return attributes.get_history(obj, name, passive=attributes.PASSIVE_NO_INITIALIZE)


def _status_changed(obj: Job) -> bool:
    history = _history(obj, "status")
    if not history.added:
        return False
    before = history.deleted[-1] if history.deleted else None
    return before is None or _value(before) != _value(history.added[-1])


@event.listens_for(Session, "after_flush")
def _note_job_changes(session: Session, flush_context: Any) -> None:
    # Pre-flush history is still visible here.
    for obj in session.new:
        if isinstance(obj, Job) and obj.id is not None:
            queue_job_event(session, obj.id, status_changed=True)
    for obj in session.dirty:
        if not isinstance(obj, Job) or obj.id is None or obj in session.deleted:
            continue
        if not any(_history(obj, name).has_changes() for name in EVENT_ATTRS):
            continue
        queue_job_event(session, obj.id, status_changed=_status_changed(obj))


def _client_available() -> bool:
    try:
        get_valkey()
    except RuntimeError:
        return False
    return True


async def _on_commit(session: Session, items: list[_Change]) -> None:
    if not _client_available():
        return  # nothing to publish to: skip the SELECT
    changes: dict[uuid.UUID, bool] = {}
    for item in items:
        changes[item.job_id] = changes.get(item.job_id, False) or item.status_changed
    # A new session on the committed session's engine (as the outbox does).
    bind = committed_bind() or session.get_bind()
    async with _session_factory(bind)() as db:
        rows = (await db.execute(sa.select(Job).where(Job.id.in_(list(changes))))).scalars().all()
        events = [(row.campaign_id, job_event(row), not changes[row.id]) for row in rows]
    for campaign_id, data, progress_only in events:
        await pubsub.publish_job(campaign_id, data, progress_only=progress_only)


register_channel(CHANNEL, _on_commit)


__all__ = ["CHANNEL", "job_event", "queue_job_event"]
