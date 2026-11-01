"""Stored files, the access side (E0-Jobs.8, AD-14).

    row = await visible_file(db, ctx, file_id)   # not_found() unless SQL and Python both allow it
    pairs = await file_sources(db, row)           # every (derived_sources row, source row or None)

Every read of `stored_files` and `derived_sources` lives here: CI-8
(scripts/check_scoped_queries.py) fails a `select(StoredFile)` or
`select(DerivedSource)` outside app/access/. app/services/file_service.py
owns the volume and does the writes.

A file is served only when two independent checks agree:

  * SQL: `scoped_get(StoredFile)`, the registry's `_sources_clause` (not
    stale for a non-GM, a registered kind, every source a visible row of the
    same Campaign, no always-GM `ref_field`);
  * Python: `audience_of(file, parents=<all of its source rows>)` covers the
    ctx's Audience.

A disagreement is a bug in one twin; it answers the same 404 as a missing
file and logs a `file_visibility_mismatch` warning (no ids beyond the file
and Campaign, never a source's content).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.audience import visible_to
from app.access.context import CampaignContext
from app.access.policy import GM, not_found
from app.access.registry import SOURCE_KIND_MODELS, audience_of, scoped_get, scoped_select
from app.db.models.stored_file import DerivedSource, StoredFile

logger = logging.getLogger(__name__)

SourcePair = tuple[DerivedSource, Any]


async def file_sources(db: AsyncSession, file: StoredFile) -> list[SourcePair]:
    """ALL of `file`'s `derived_sources` rows (no visibility filter, no
    limit), ordered by id, each paired with the source row it names, or None
    when its `ref_kind` has no model or the row is gone. This is the
    `parents=` `audience_of` needs: a missing pair would widen the file."""
    sources = list((await db.execute(
        sa.select(DerivedSource)
        .where(DerivedSource.derived_type == file.kind, DerivedSource.derived_id == file.id)
        .order_by(DerivedSource.id)
    )).scalars())
    wanted: dict[str, set[uuid.UUID]] = {}
    for ds in sources:
        if ds.ref_kind in SOURCE_KIND_MODELS:
            wanted.setdefault(ds.ref_kind, set()).add(ds.ref_id)
    found: dict[tuple[str, uuid.UUID], Any] = {}
    for ref_kind, ids in wanted.items():
        model = SOURCE_KIND_MODELS[ref_kind]
        for row in (await db.execute(sa.select(model).where(model.id.in_(ids)))).scalars():
            found[(ref_kind, row.id)] = row
    return [(ds, found.get((ds.ref_kind, ds.ref_id))) for ds in sources]


async def file_audience(db: AsyncSession, file: StoredFile) -> Any:
    """`audience_of(file)` from every one of its sources."""
    return audience_of(file, parents=await file_sources(db, file))


async def visible_file(db: AsyncSession, ctx: CampaignContext, file_id: Any) -> StoredFile:
    """The file `file_id` if ctx may read it (module docstring); else the one
    `not_found()`: missing, another Campaign's, a malformed id, hidden, stale
    for a non-GM, and a SQL/Python disagreement are the same answer."""
    row = await scoped_get(db, StoredFile, ctx, file_id)
    try:
        audience = await file_audience(db, row)
        allowed = visible_to(audience, ctx)
    except (TypeError, ValueError):
        allowed = False
    if not allowed:
        logger.warning(json.dumps({"event": "file_visibility_mismatch", "file_id": str(row.id),
                                   "campaign_id": str(row.campaign_id)}))
        not_found()
    return row


async def files_derived_from(db: AsyncSession, ref_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of every non-stale file with a `derived_sources` row naming
    `ref_id` under any modelled `ref_kind` (SOURCE_KIND_MODELS; a Visibility
    kind such as `player_journal` may differ from the stored `ref_kind`, the
    id does not). The `ref_kind IN (...)` lets `ix_derived_sources_ref` serve
    the lookup; a ref_kind with no model already makes its file GM-only, so
    its staleness never matters. For the stale marker; no ctx: it only finds
    what must stop being served."""
    return list((await db.execute(
        sa.select(StoredFile.id)
        .where(sa.not_(StoredFile.stale),
               sa.exists().where(DerivedSource.derived_type == StoredFile.kind,
                                 DerivedSource.derived_id == StoredFile.id,
                                 DerivedSource.ref_kind.in_(list(SOURCE_KIND_MODELS)),
                                 DerivedSource.ref_id == ref_id))
        .order_by(StoredFile.id)
    )).scalars())


async def campaign_files(db: AsyncSession, ctx: CampaignContext) -> list[StoredFile]:
    """Every file of ctx's Campaign, stale ones included, oldest first. A
    writable GM ctx only (the `files.gc` Job runs as the Owner); anything
    else is `not_found()`."""
    if not isinstance(ctx, CampaignContext) or ctx.role != GM or ctx.read_only:
        not_found()
    return list((await db.execute(
        scoped_select(StoredFile, ctx).order_by(StoredFile.created_at, StoredFile.id)
    )).scalars())


__all__ = ["campaign_files", "file_audience", "file_sources", "files_derived_from", "visible_file"]
