"""`journal.reembed_sweep`: the durable backstop for the reembed fallback (E0-Journal.2).

A journal save with the `ml` sidecar down leaves `embedding` /
`party_embedding` NULL and the `entry_saved` / `entry_updated` hook enqueues
`journal.reembed` (app/hooks/journal.py). Hooks are at most once, so a crash
between the commit and the hook would leave the entry unembedded. This sweep
closes that gap:

* **Kind.** `journal.reembed_sweep` (queue `backfill`, `cpu_heavy`, not
  live-safe): a cursor Job (`run_cursor`, app/jobs/backfill.py) over the
  Campaign's entries with a NULL vector, keyset on id, one entry per step
  (`journal_service.reindex_entry(strict=True)`, the same recompute path as
  every writer). It runs as the Campaign Owner's GM ctx, which sees every
  entry.
* **Once, for existing rows.** The `data_backfills` row `journal_reembed_v1`
  (inserted by revision 7d1e2a9c4b6f) is run by the runner: one Job per
  Campaign, key `backfill:journal_reembed_v1:{campaign_id}`.
* **Daily, for anything a lost hook left behind.** `schedule_daily` runs on
  every reaper pass (app/jobs/worker.py) and works once per UTC day across
  workers (Valkey `SET NX` on `journal.reembed_sweep:day:<date>`): for every
  Campaign with an unembedded entry it enqueues one Job, key
  `journal.reembed_sweep:{campaign_id}` (an active one is reused).

**ml down is a no-op, never a failure storm.** `schedule_daily` probes ml
first (one tiny embed): when it does not answer, nothing is enqueued and the
day key is shortened to ML_RETRY_S, so the next try is ML_RETRY_S later, not
every reaper pass. A Job step whose probe fails ends the Job `done` with the
rest of its rows untouched (the next sweep picks them up). A step whose own
reindex hits an ml error logs it and moves on: the row stays NULL for the
next sweep, and the next step's probe stops the Job. An entry edited while it
was being embedded (`EntryTextChanged`) is skipped the same way; its own
writer recomputed it.
"""
from __future__ import annotations

import inspect
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.context import CampaignContext, ctx_for
from app.access.owners import campaign_owners
from app.access.policy import NotFound
from app.clients.errors import ModelServiceError
from app.domain.enums import JobQueue
from app.jobs.backfill import CursorStep, register_backfill, run_cursor
from app.jobs.enqueue import enqueue
from app.jobs.registry import JobKind, register
from app.services import journal_service

logger = logging.getLogger(__name__)

SWEEP_KIND = "journal.reembed_sweep"
BACKFILL_NAME = "journal_reembed_v1"
# The day marker outlives the day (as files.gc's does).
DAY_TTL_S = 2 * 24 * 3600
# ml down at schedule time: try again this much later instead of tomorrow.
ML_RETRY_S = 600

REEMBED_SWEEP = register(JobKind(
    name=SWEEP_KIND, queue=JobQueue.BACKFILL, timeout_s=300, handler="app.jobs.journal:handle",
    resources=frozenset({"cpu_heavy"}), live_safe=False,
))
register_backfill(BACKFILL_NAME, SWEEP_KIND)


def day_key(now: datetime) -> str:
    return f"{SWEEP_KIND}:day:{now.astimezone(timezone.utc).date().isoformat()}"


def sweep_key(campaign_id: uuid.UUID | str) -> str:
    return f"{SWEEP_KIND}:{campaign_id}"


# ── The Job ────────────────────────────────────────────────────────────────

async def _select_next(db: AsyncSession, ctx: CampaignContext, cursor: Any) -> CursorStep | None:
    found = await journal_service.next_unembedded(db, ctx, cursor)
    if found is None:
        return None
    entry, remaining = found
    return CursorStep(item=entry, cursor=str(entry.id), total=remaining)


async def _process_one(db: AsyncSession, ctx: CampaignContext, entry: Any) -> None:
    try:
        async with db.begin_nested():
            await journal_service.reindex_entry(db, entry, strict=True)
    except (ModelServiceError, ValueError, journal_service.EntryTextChanged) as exc:
        # Never the text; the row stays as it was for the next sweep.
        logger.info("journal reembed sweep skipped an entry", extra={
            "campaign_id": str(ctx.campaign_id), "journal_id": str(entry.id), "error_type": type(exc).__name__})


async def handle(job: Any, ctx: CampaignContext, db: AsyncSession) -> None:
    """One step: the next unembedded entry, or nothing while ml is down."""
    if not await journal_service.ml_available():
        logger.info("journal reembed sweep paused: ml sidecar unavailable",
                    extra={"campaign_id": str(ctx.campaign_id)})
        return
    await run_cursor(job, ctx, db, select_next=_select_next, process_one=_process_one)


# ── The daily schedule ─────────────────────────────────────────────────────

async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _schedule(session_factory: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    jobs: list[uuid.UUID] = []
    async with session_factory() as db:
        owners = await campaign_owners(db, created_before=None)
        for cid, owner in owners.items():
            try:
                ctx = await ctx_for(db, owner, cid)
            except NotFound:
                continue
            if await journal_service.has_unembedded(db, ctx):
                jobs.append(await enqueue(db, ctx, SWEEP_KIND, {}, idempotency_key=sweep_key(cid)))
        await db.commit()
    return jobs


async def schedule_daily(session_factory: async_sessionmaker[AsyncSession], redis: Any, *,
                         now: datetime | None = None) -> list[uuid.UUID]:
    """Once per UTC day (module docstring): one sweep Job per Campaign with
    an unembedded entry. Returns the Job ids (empty when another pass already
    did today's, or ml is down). A failure deletes the day key, so the next
    pass tries again. `redis` is a sync or asyncio client."""
    now = now or datetime.now(timezone.utc)
    key = day_key(now)
    if not await _maybe_await(redis.set(key, "1", nx=True, ex=DAY_TTL_S)):
        return []
    try:
        if not await journal_service.ml_available():
            await _maybe_await(redis.set(key, "ml_down", ex=ML_RETRY_S))
            logger.info("journal reembed sweep deferred: ml sidecar unavailable")
            return []
        jobs = await _schedule(session_factory)
    except BaseException:
        await _maybe_await(redis.delete(key))
        raise
    if jobs:
        logger.info("journal reembed sweep scheduled for %d Campaigns", len(jobs))
    return jobs


__all__ = ["BACKFILL_NAME", "DAY_TTL_S", "ML_RETRY_S", "REEMBED_SWEEP", "SWEEP_KIND", "day_key", "handle",
           "schedule_daily", "sweep_key"]
