"""`files.gc`: the daily sweep of the `files_data` volume (E0-Jobs.8, AD-14).

`schedule_daily` runs on every reaper pass (app/jobs/worker.py: `Reaper`)
and does its work once per UTC day across all workers (a Valkey `SET NX`
on `files.gc:day:<date>`): for every Campaign that has a directory under
`files_root` it enqueues one `files.gc` Job as the Campaign's Owner, key
`files.gc:{campaign_id}` (an active one is reused).

The Job is a cursor Job (`run_cursor`, app/jobs/backfill.py) over
`file_service.gc_candidates`, GC_BATCH candidates per step: superseded
files (deleted with their rows; bytes after the step commits), row-less
entries of the Campaign's directory older than the grace period, and the
directories of deleted Campaigns older than the grace period. A fresh file,
and a file made stale by a downgrade, are never touched.
"""
from __future__ import annotations

import inspect
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access.context import CampaignContext, ctx_for
from app.access.owners import campaign_owners
from app.access.policy import NotFound
from app.jobs.backfill import CursorStep, run_cursor
from app.jobs.enqueue import enqueue
from app.services import file_service

logger = logging.getLogger(__name__)

GC_KIND = "files.gc"
GC_BATCH = 50
# The day marker outlives the day, so a pass just after midnight UTC never
# sees the previous day's key expire under it.
DAY_TTL_S = 2 * 24 * 3600


def day_key(now: datetime) -> str:
    return f"files.gc:day:{now.astimezone(timezone.utc).date().isoformat()}"


def gc_key(campaign_id: uuid.UUID | str) -> str:
    return f"files.gc:{campaign_id}"


async def handle(job: Any, ctx: CampaignContext, db: AsyncSession) -> None:
    """One step: the next GC_BATCH candidates after the cursor."""
    done = int((job.payload or {}).get("done") or 0)

    async def select_next(db: AsyncSession, ctx: CampaignContext, cursor: Any) -> CursorStep | None:
        remaining = [c for c in await file_service.gc_candidates(db, ctx) if cursor is None or c.key > cursor]
        if not remaining:
            return None
        batch = remaining[:GC_BATCH]
        return CursorStep(item=batch, cursor=batch[-1].key, total=done + math.ceil(len(remaining) / GC_BATCH))

    async def process(db: AsyncSession, ctx: CampaignContext, batch: list[file_service.GcCandidate]) -> None:
        for candidate in batch:
            await file_service.gc_one(db, ctx, candidate)

    await run_cursor(job, ctx, db, select_next=select_next, process_one=process)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def schedule_daily(session_factory: async_sessionmaker[AsyncSession], redis: Any, *,
                         now: datetime | None = None) -> list[uuid.UUID]:
    """Once per UTC day (module docstring): one `files.gc` Job per Campaign
    with a directory. Returns the Job ids (empty when another pass already
    did today's). `redis` is a sync or asyncio client."""
    now = now or datetime.now(timezone.utc)
    if not await _maybe_await(redis.set(day_key(now), "1", nx=True, ex=DAY_TTL_S)):
        return []
    dirs = file_service.campaign_dirs()
    if not dirs:
        return []
    jobs: list[uuid.UUID] = []
    async with session_factory() as db:
        owners = await campaign_owners(db, created_before=None)
        for cid in dirs:
            owner_id = owners.get(cid)
            if owner_id is None:
                continue  # a deleted Campaign: another Campaign's Job sweeps its directory
            try:
                ctx = await ctx_for(db, owner_id, cid)
            except NotFound:
                continue
            jobs.append(await enqueue(db, ctx, GC_KIND, {}, idempotency_key=gc_key(cid)))
        await db.commit()
    if jobs:
        logger.info("files.gc scheduled for %d Campaigns", len(jobs))
    return jobs


__all__ = ["DAY_TTL_S", "GC_BATCH", "GC_KIND", "day_key", "gc_key", "handle", "schedule_daily"]
