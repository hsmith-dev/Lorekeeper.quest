"""Campaign owners, for system bookkeeping that runs per Campaign (E0-Jobs.5).

The `data_backfills` runner (app/jobs/backfill.py) starts one Job per
Campaign, as that Campaign's Owner. Reading `Campaign` rows outside
app/access/ is a CI-8 violation, so the enumeration lives here.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.campaign import Campaign


async def campaign_owners(db: AsyncSession, *, created_before: datetime | None) -> dict[uuid.UUID, uuid.UUID]:
    """Campaign id -> Owner's user id, for every Campaign created at or
    before `created_before` (None: every Campaign), oldest first."""
    query = sa.select(Campaign.id, Campaign.user_id).order_by(Campaign.created_at, Campaign.id)
    if created_before is not None:
        query = query.where(Campaign.created_at <= created_before)
    return {row.id: row.user_id for row in await db.execute(query)}


__all__ = ["campaign_owners"]
