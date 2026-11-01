"""Cursor Jobs and the `data_backfills` runner (AD-4, AD-18, E0-Jobs.5).

A Job does at most one Journal Entry's worth of model work. Work over many
entries is a cursor Job: one `jobs` row that processes one item per run,
stores its cursor in the payload, reports progress on the same row, and is
pushed again until nothing is left. A handler does it with `run_cursor`:

    async def handle(job, ctx, db):
        await run_cursor(job, ctx, db, select_next=next_entry, process_one=suggest_mentions)

    async def next_entry(db, ctx, cursor) -> CursorStep | None:
        ...  # the first item after `cursor` (None at the start), its new cursor
             # and the total; None when nothing is left
    async def process_one(db, ctx, item) -> None:
        ...  # one entry's work; never db.commit() (the wrapper commits)

Per step, the entry's writes, the new `payload.cursor`/`payload.done`,
`progress` (done/total), `stage` ("Entry {done} of {total}") and the row back
in `queued` commit together (app/jobs/worker.py: `_continue`), and the row is
pushed again at once with the same Job id. A step that raises rolls all of
it back and retries as usual; the cursor is unchanged. A continuation resets
`attempts` to 0: the retry budget is per entry. When `select_next` returns
None the Job ends `done`.

`data_backfills` (RC-2): one row per named backfill (AD-18), run per
Campaign. A feature registers the backfill's kind (queue `backfill`) at
import time, from a module in registry.KIND_MODULES:

    register(JobKind(name="mentions.backfill", queue=JobQueue.BACKFILL, ...))
    register_backfill("suggested_mentions_v1", "mentions.backfill")

and a migration inserts the `data_backfills` row (status `queued`, the
schema's "pending": its CHECK is JobStatus). `run_backfills` runs on every
reaper pass (app/jobs/worker.py: `Reaper`; the first at worker start). For
each `queued` or `running` row (one transaction per row, FOR UPDATE SKIP
LOCKED):

* first sight: the Campaigns created at or before the row's `updated_at`
  go into `cursor.campaigns` (a Campaign created later is not backfilled:
  it is created with the new behaviour);
* each of them not yet in `cursor.jobs` gets the kind enqueued as its Owner
  (`ctx_for`), payload `{"backfill": name}`, key `backfill:{name}:{cid}`;
* a Campaign whose Job is `done`, `cancelled` or deleted, or that was
  deleted, goes into `cursor.finished`; a `failed` Job also goes into
  `cursor.failed` (the Owner sees it in their Job tray and can retry);
* status `running`, then `done` once every Campaign is finished.

`run_cursor` records each Campaign's progress in `cursor.entries[<cid>]`
(`{"done", "total", "cursor"}`) when the payload names a `backfill`. A row
whose name has no registered kind is left untouched, logged once per
process (`backfill_unregistered`).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.context import CampaignContext, ctx_for
from app.access.owners import campaign_owners
from app.access.policy import NotFound
from app.db.models.job import DataBackfill, Job
from app.domain.enums import JobQueue, JobStatus
from app.jobs.enqueue import enqueue
from app.jobs.registry import get_kind

logger = logging.getLogger(__name__)


# ── Cursor Jobs ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CursorStep:
    """The next item to process, the cursor after it, and the total count."""
    item: Any
    cursor: Any
    total: int


SelectNext = Callable[[AsyncSession, CampaignContext, Any], Awaitable["CursorStep | None"]]
ProcessOne = Callable[[AsyncSession, CampaignContext, Any], Awaitable[None]]


async def run_cursor(job: Job, ctx: CampaignContext, db: AsyncSession, *, select_next: SelectNext,
                     process_one: ProcessOne) -> bool:
    """One step of a cursor Job (see the module docstring). True when a step
    ran and the Job continues; False when nothing was left (the Job ends
    `done`)."""
    payload = dict(job.payload or {})
    step = await select_next(db, ctx, payload.get("cursor"))
    if step is None:
        return False
    await process_one(db, ctx, step.item)
    done = int(payload.get("done") or 0) + 1
    total = max(int(step.total), done)
    payload["cursor"] = step.cursor
    payload["done"] = done
    job.payload = payload
    job.progress = done / total
    job.stage = f"Entry {done} of {total}"
    job.eta_seconds = None
    name = payload.get("backfill")
    if isinstance(name, str):
        await _record_entry(db, name, job.campaign_id, {"done": done, "total": total, "cursor": step.cursor})
    job._continue = True
    return True


async def _record_entry(db: AsyncSession, name: str, campaign_id: uuid.UUID, entry: dict[str, Any]) -> None:
    """`data_backfills.cursor.entries[<campaign_id>]` = entry, in the step's
    transaction (the row lock waits for a runner pass holding it)."""
    row = (await db.execute(
        sa.select(DataBackfill).where(DataBackfill.name == name).with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        return
    cursor = dict(row.cursor or {})
    cursor["entries"] = {**(cursor.get("entries") or {}), str(campaign_id): entry}
    row.cursor = cursor


# ── data_backfills ─────────────────────────────────────────────────────────

# backfill name -> the registered kind that runs it per Campaign.
BACKFILLS: dict[str, str] = {}
_ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
_FINISHED_JOB = frozenset({JobStatus.DONE, JobStatus.CANCELLED})
_unregistered_logged: set[str] = set()


def register_backfill(name: str, kind: str) -> str:
    """Run the `data_backfills` row `name` with `kind` (registered, queue
    `backfill`), one Job per Campaign. Registering the same pair again is a
    no-op; another kind under a taken name is a ValueError."""
    if not isinstance(name, str) or not name.strip() or len(name) > 128:
        raise ValueError(f"register_backfill: name must be a non-empty str (<= 128 chars), got {name!r}")
    job_kind = get_kind(kind)
    if job_kind.queue != JobQueue.BACKFILL:
        raise ValueError(f"register_backfill: kind {kind!r} must use the backfill queue, not {job_kind.queue}")
    existing = BACKFILLS.get(name)
    if existing is not None and existing != job_kind.name:
        raise ValueError(f"register_backfill: backfill {name!r} is already registered to {existing!r}")
    BACKFILLS[name] = job_kind.name
    return name


def backfill_key(name: str, campaign_id: uuid.UUID | str) -> str:
    return f"backfill:{name}:{campaign_id}"


async def run_backfills(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, JobStatus]:
    """One runner pass over every `queued`/`running` data_backfills row
    (module docstring). Returns the status each row it advanced was left in.
    A row that fails is logged and left for the next pass."""
    async with session_factory() as db:
        names = list((await db.execute(
            sa.select(DataBackfill.name).where(DataBackfill.status.in_(_ACTIVE)).order_by(DataBackfill.name)
        )).scalars())
    result: dict[str, JobStatus] = {}
    for name in names:
        try:
            async with session_factory() as db:
                status = await _advance(db, name)
        except Exception:
            logger.exception("data backfill pass failed", extra={"backfill": name})
            continue
        if status is not None:
            result[name] = status
    return result


async def _advance(db: AsyncSession, name: str) -> JobStatus | None:
    row = (await db.execute(
        sa.select(DataBackfill)
        .where(DataBackfill.name == name, DataBackfill.status.in_(_ACTIVE))
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if row is None:
        return None  # another pass holds it, or it finished meanwhile
    kind = BACKFILLS.get(name)
    if kind is None:
        await db.rollback()
        if name not in _unregistered_logged:
            _unregistered_logged.add(name)
            logger.warning("backfill_unregistered: no kind is registered for data backfill %r", name,
                           extra={"backfill": name})
        return None

    cursor = dict(row.cursor or {})
    if "campaigns" not in cursor:
        snapshot = await campaign_owners(db, created_before=row.updated_at)
        cursor["campaigns"] = [str(cid) for cid in snapshot]
    campaigns: list[str] = list(cursor["campaigns"])
    jobs: dict[str, str] = dict(cursor.get("jobs") or {})
    finished: list[str] = list(cursor.get("finished") or [])
    failed: list[str] = list(cursor.get("failed") or [])

    owners = {str(cid): owner for cid, owner in (await campaign_owners(db, created_before=None)).items()}
    statuses = {str(r.id): JobStatus(r.status) for r in await db.execute(
        sa.select(Job.id, Job.status).where(Job.id.in_([uuid.UUID(j) for j in jobs.values()]))
    )} if jobs else {}

    for cid in campaigns:
        if cid in finished:
            continue
        if cid not in owners:
            finished.append(cid)  # the Campaign was deleted
            continue
        if cid in jobs:
            status = statuses.get(jobs[cid])
            if status is None or status in _FINISHED_JOB:
                finished.append(cid)
            elif status == JobStatus.FAILED:
                finished.append(cid)
                if cid not in failed:
                    failed.append(cid)
            continue
        try:
            ctx = await ctx_for(db, owners[cid], cid)
        except NotFound:
            finished.append(cid)
            continue
        job_id = await enqueue(db, ctx, kind, {"backfill": name}, idempotency_key=backfill_key(name, cid))
        jobs[cid] = str(job_id)

    cursor.update(campaigns=campaigns, jobs=jobs, finished=finished, failed=failed)
    row.cursor = cursor
    row.status = JobStatus.DONE if len(finished) >= len(campaigns) else JobStatus.RUNNING
    status = JobStatus(row.status)
    await db.commit()
    if status == JobStatus.DONE:
        logger.info("data backfill done: %d Campaigns, %d failed", len(campaigns), len(failed),
                    extra={"backfill": name})
    return status


__all__ = ["BACKFILLS", "CursorStep", "backfill_key", "register_backfill", "run_backfills", "run_cursor"]
