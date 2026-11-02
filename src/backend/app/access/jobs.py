"""Jobs, the read side (E0-Jobs.7, AD-5, AD-13).

    job = await get_job(db, ctx, job_id)                  # not_found() unless ctx may read it
    jobs = await list_jobs(db, ctx, status=None)          # the tray: running, queued, finished <= 24 h
    body = await job_response(db, ctx, job)               # JobResponse, result_ref and queue_position decided
    gen = job_event_stream(stream_ctx(request, ctx), bind=bind)   # the SSE route's `job` events

Every read of `jobs` outside app/jobs/ lives here, through the registry
(`Job: always_gm(owner_field="created_by")`): a GM ctx reads every Job of its
Campaign, a Player ctx only the Jobs they started (`created_by`), the member
view and anon none. A hidden, missing, another Campaign's or malformed id is
the one `not_found()`.

**result_ref.** A writable GM ctx gets the stored value unchanged. Any other
ctx (a Player, the member view in preview) gets it only when it names
`{"kind", "id"}` of a registered result kind whose row that ctx can see now
(in its own Campaign), and then only as `{"kind": ..., "id": ...}`: any other
key is dropped. Anything else (an unregistered kind, a malformed ref, a
hidden or deleted row) is null. Features register their kinds like event
domains: `register_result_kind("recap", Recap)`. Built in: `journal`,
`entity` and `file` (a file passes both of app/access/files.py's checks).

**queue_position.** For a queued Job only: the number of Jobs the ctx can
see that sit ahead of it in the same `queue` (queued, earlier `created_at`,
`id` as the tie-break). Hidden Jobs and other Campaigns' Jobs are never
counted, so it is a lower bound by design (privacy first): a Player may read
"0 ahead" while a GM's Jobs run first.

**The stream.** `job_event_stream(ctx)` yields `subscribed` first (the
resync point, app/core/pubsub.py: the client refetches on every
`subscribed`), then each `job` event of the Campaign that ctx could
`GET /api/jobs/{job_id}` now, rebuilt from JOB_EVENT_FIELDS with
`result_ref` filtered as above. Other event names are dropped. A check that
cannot run ends the stream (`JobEventCheckFailed`, logged) instead of
dropping the event silently: the client reconnects and refetches.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.context import CampaignContext
from app.access.files import visible_file
from app.access.policy import GM, NotFound, not_found
from app.access.registry import registration, scoped_select
from app.core import pubsub
from app.db.models.entity import Entity
from app.db.models.job import ACTIVE_STATUSES, Job
from app.db.models.journal import JournalEntry
from app.db.models.stored_file import StoredFile
from app.domain.enums import JobStatus
from app.schemas.jobs import JobResponse

logger = logging.getLogger(__name__)

# The tray shows finished Jobs for this long (running and queued always).
FINISHED_WINDOW = timedelta(hours=24)
LIST_LIMIT = 200


class JobEventCheckFailed(Exception):
    """A `job` event's visibility check could not run: the stream must end."""


# ── Result kinds ───────────────────────────────────────────────────────────

ResultCheck = Callable[[AsyncSession, CampaignContext, uuid.UUID], Awaitable[bool]]


@dataclass(frozen=True)
class ResultKind:
    kind: str
    model: type
    check: ResultCheck | None = None  # None: the row is in scoped_select(model, ctx)


_RESULT_KINDS: dict[str, ResultKind] = {}


def register_result_kind(kind: str, model: type, *, check: ResultCheck | None = None) -> ResultKind:
    """Map a `result_ref` kind to the registered model whose `id` it names
    (`check(db, ctx, id) -> bool` replaces the default `scoped_select`
    lookup, e.g. a file's two checks). A kind nobody registered reaches GMs
    only. Re-registering the same model and check is a no-op; anything else
    under a taken kind raises ValueError."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("register_result_kind: kind must be a non-empty string")
    registration(model)  # UnregisteredModel for an unregistered model
    if not hasattr(model, "id"):
        raise ValueError(f"register_result_kind: {model.__name__} has no `id` column")
    existing = _RESULT_KINDS.get(kind)
    if existing is not None:
        if existing.model is model and existing.check is check:
            return existing
        raise ValueError(f"register_result_kind: {kind!r} is already {existing.model.__name__}")
    entry = ResultKind(kind, model, check)
    _RESULT_KINDS[kind] = entry
    return entry


def result_kinds() -> list[str]:
    return sorted(_RESULT_KINDS)


def _sees_everything(ctx: CampaignContext) -> bool:
    return ctx.role == GM and not ctx.read_only


def _uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None


async def _row_visible(db: AsyncSession, ctx: CampaignContext, entry: ResultKind, row_id: uuid.UUID) -> bool:
    if entry.check is not None:
        return bool(await entry.check(db, ctx, row_id))
    stmt = scoped_select(entry.model, ctx).where(entry.model.id == row_id).with_only_columns(entry.model.id)
    return bool((await db.execute(sa.select(sa.exists(stmt)))).scalar())


async def visible_result_ref(db: AsyncSession, ctx: CampaignContext, ref: Any) -> dict[str, Any] | None:
    """What `ctx` may see of a Job's `result_ref` (module docstring). Errors
    of the visibility query propagate (the caller fails closed)."""
    if _sees_everything(ctx):
        return ref
    if not isinstance(ref, dict):
        return None
    kind, row_id = ref.get("kind"), _uuid(ref.get("id"))
    entry = _RESULT_KINDS.get(kind) if isinstance(kind, str) else None
    if entry is None or row_id is None:
        return None
    if not await _row_visible(db, ctx, entry, row_id):
        return None
    return {"kind": kind, "id": str(row_id)}


async def _file_visible(db: AsyncSession, ctx: CampaignContext, file_id: uuid.UUID) -> bool:
    try:
        await visible_file(db, ctx, file_id)
    except NotFound:
        return False
    return True


# ── Reads ──────────────────────────────────────────────────────────────────

async def get_job(db: AsyncSession, ctx: CampaignContext, job_id: Any, *, for_update: bool = False) -> Job:
    """The Job `job_id` if ctx may read it, else the one `not_found()`.
    `for_update` locks the row (FOR UPDATE) and reloads it from the database
    (app/jobs/control.py's cancel and retry)."""
    row_id = _uuid(job_id)
    if row_id is None:
        not_found()
    stmt = scoped_select(Job, ctx).where(Job.id == row_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        not_found()
    return row


async def list_jobs(db: AsyncSession, ctx: CampaignContext, *, status: JobStatus | str | None = None,
                    now: datetime | None = None, limit: int = LIST_LIMIT) -> list[Job]:
    """The ctx's visible Jobs, newest first (`created_at`, then `id`): every
    queued and running Job, and the finished ones (done, failed, cancelled)
    of the last FINISHED_WINDOW. `status` narrows that set to one status. At
    most `limit` rows."""
    now = now or datetime.now(timezone.utc)
    active = [s.value for s in ACTIVE_STATUSES]
    finished_at = sa.func.coalesce(Job.finished_at, Job.created_at)
    stmt = scoped_select(Job, ctx).where(sa.or_(Job.status.in_(active), finished_at >= now - FINISHED_WINDOW))
    if status is not None:
        stmt = stmt.where(Job.status == JobStatus(status).value)
    stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())


async def queue_positions(db: AsyncSession, ctx: CampaignContext,
                          job_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, int]:
    """{job_id: Jobs ahead} for the queued Jobs ctx can see (only `job_ids`
    when given), counted over the queued Jobs ctx can see in the same queue
    (module docstring)."""
    position = sa.func.row_number().over(partition_by=Job.queue, order_by=(Job.created_at, Job.id)) - 1
    stmt = (scoped_select(Job, ctx).where(Job.status == JobStatus.QUEUED.value)
            .with_only_columns(Job.id, position.label("ahead")))
    rows = (await db.execute(stmt)).all()
    wanted = None if job_ids is None else set(job_ids)
    return {row.id: int(row.ahead) for row in rows if wanted is None or row.id in wanted}


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


async def job_response(db: AsyncSession, ctx: CampaignContext, job: Job, *,
                       positions: dict[uuid.UUID, int] | None = None) -> JobResponse:
    """`job` as ctx may see it (a row ctx read through `get_job`/`list_jobs`).
    `positions` (from `queue_positions`) saves a query per row in a list."""
    queue_position = None
    if _value(job.status) == JobStatus.QUEUED.value:
        if positions is None:
            positions = await queue_positions(db, ctx, [job.id])
        queue_position = positions.get(job.id)
    return JobResponse(
        id=job.id, kind=job.kind, status=JobStatus(_value(job.status)), progress=job.progress, stage=job.stage,
        eta_seconds=job.eta_seconds, error_code=_value(job.error_code), error_message=job.error_message,
        result_ref=await visible_result_ref(db, ctx, job.result_ref), attempts=job.attempts,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
        queue_position=queue_position,
    )


# ── The stream ─────────────────────────────────────────────────────────────

async def deliverable_job_event(session: AsyncSession, ctx: CampaignContext, data: Any) -> dict | None:
    """The `job` payload ctx may receive for one event's `data`, or None
    (drop it): the Job must be one ctx could `GET` now. The payload holds
    JOB_EVENT_FIELDS only, `result_ref` filtered. Raises JobEventCheckFailed
    when a query fails."""
    if not isinstance(data, dict):
        return None
    job_id = _uuid(data.get("job_id"))
    if job_id is None:
        return None
    try:
        found = (await session.execute(
            sa.select(sa.exists(scoped_select(Job, ctx).where(Job.id == job_id).with_only_columns(Job.id)))
        )).scalar()
        if not found:
            return None
        payload = {name: data.get(name) for name in pubsub.JOB_EVENT_FIELDS}
        payload["job_id"] = str(job_id)
        payload["result_ref"] = await visible_result_ref(session, ctx, data.get("result_ref"))
    except Exception as exc:
        raise JobEventCheckFailed(str(job_id)) from exc
    return payload


async def job_event_stream(ctx: CampaignContext, *, bind: Any = None) -> AsyncIterator[tuple[str, Any]]:
    """`(event, data)` for the SSE route: `subscribed` first (once the
    subscription is live), then each `job` event ctx may receive. Each check
    runs in its own short session on `bind` (default: the app engine). Ends
    when the listener ends, or when a check fails (logged)."""
    if bind is None:
        from app.db.session import AsyncSessionLocal

        bind = AsyncSessionLocal.kw["bind"]
    listener = pubsub.listen_jobs(ctx.campaign_id, announce=True)
    try:
        async for event, data in listener:
            if event == pubsub.SUBSCRIBED_EVENT:
                yield event, {}
                continue
            if event != pubsub.JOB_EVENT:
                continue
            try:
                async with AsyncSession(bind=bind, expire_on_commit=False) as session:
                    payload = await deliverable_job_event(session, ctx, data)
            except Exception:
                # Fail closed, but never drop silently: end the stream so the
                # client reconnects, gets `subscribed` and refetches.
                logger.warning(json.dumps({"event": "job_event_check_failed",
                                           "campaign_id": str(ctx.campaign_id)}), exc_info=True)
                return
            if payload is not None:
                yield pubsub.JOB_EVENT, payload
    finally:
        await listener.aclose()


# ── Built-in result kinds ──────────────────────────────────────────────────

register_result_kind("journal", JournalEntry)
register_result_kind("entity", Entity)
register_result_kind("file", StoredFile, check=_file_visible)


__all__ = [
    "FINISHED_WINDOW", "JobEventCheckFailed", "ResultKind", "deliverable_job_event", "get_job", "job_event_stream",
    "job_response", "list_jobs", "queue_positions", "register_result_kind", "result_kinds", "visible_result_ref",
]
