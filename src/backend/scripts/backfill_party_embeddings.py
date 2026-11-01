#!/usr/bin/env python
"""Backfill the Party search fields of journal entries (E0-Access.7, AD-18).

Non-GM search and chat match on `party_tsv` and `party_embedding` (the
Narrative alone, never the Shorthand). Migration c95acb56c595 added both
columns and filled `party_tsv` once; rows written since then, and every
`party_embedding`, are filled here. Run it once after deploying
E0-Access.7 (no Alembic revision: Alembic holds schema plus set-based SQL
only). Until a row is filled, non-GM vector search skips it and never falls
back to `embedding`.

Two passes, both idempotent and resumable:

  1. one set-based UPDATE: `party_tsv = to_tsvector('english', narrative)`
     where it is NULL or stale;
  2. `party_embedding = embed(narrative)` for rows `WHERE party_embedding IS
     NULL`, in batches of 50 (keyset order on id), committing per batch. A
     row whose embedding fails stays NULL, is reported, and the run goes on;
     a later run retries it.

A second run over a filled table changes nothing.

  python scripts/backfill_party_embeddings.py [--database-url URL] [--dry-run]

Run inside the backend container (it has the embedding model):

  docker compose -f docker-compose.prod.yml exec backend python scripts/backfill_party_embeddings.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import func, or_, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

import app.db.models  # noqa: E402,F401  (registers every mapper)
from app.db.models.journal import EMBEDDING_DIM, JournalEntry  # noqa: E402

BATCH_SIZE = 50

Embedder = Callable[[str], list[float]]


@dataclass
class BackfillResult:
    dry_run: bool
    tsv_updated: int = 0          # rows whose party_tsv was set (dry run: would be)
    embedding_pending: int = 0    # rows with a NULL party_embedding before the run
    embedded: int = 0             # rows whose party_embedding was set
    batches: int = 0
    failed: list[uuid.UUID] = field(default_factory=list)  # embed failed; left NULL

    def summary(self) -> str:
        verb = "would update" if self.dry_run else "updated"
        lines = [
            f"party_tsv: {verb} {self.tsv_updated} row(s)",
            f"party_embedding: {self.embedding_pending} row(s) NULL before the run"
            + ("" if self.dry_run else f"; embedded {self.embedded} in {self.batches} batch(es); "
                                        f"{len(self.failed)} failed (left NULL)"),
        ]
        lines += [f"  failed: {fid}" for fid in self.failed[:20]]
        if len(self.failed) > 20:
            lines.append(f"  ... and {len(self.failed) - 20} more")
        return "\n".join(lines)


def _stale_tsv():
    expected = func.to_tsvector("english", JournalEntry.narrative)
    return or_(JournalEntry.party_tsv.is_(None), JournalEntry.party_tsv.is_distinct_from(expected))


def _default_embed(text: str) -> list[float]:
    from app.services import embedding_service

    return embedding_service.embed(text)


async def backfill(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
    embed: Embedder | None = None,
) -> BackfillResult:
    """Fill NULL/stale `party_tsv` and NULL `party_embedding` over every
    journal entry. `embed` defaults to `embedding_service.embed`."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    embed_fn = embed or _default_embed
    result = BackfillResult(dry_run=dry_run)
    result.tsv_updated = await session.scalar(select(func.count()).select_from(JournalEntry).where(_stale_tsv()))
    result.embedding_pending = await session.scalar(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.party_embedding.is_(None))
    )
    if dry_run:
        return result

    # Pass 1: set-based, one statement.
    tsv = await session.execute(
        update(JournalEntry).where(_stale_tsv())
        .values(party_tsv=func.to_tsvector("english", JournalEntry.narrative))
        .execution_options(synchronize_session=False)
    )
    result.tsv_updated = tsv.rowcount
    await session.commit()

    # Pass 2: batches in id order. Keyset paging, so a row that failed stays
    # NULL without being selected again in this run.
    last_id: uuid.UUID | None = None
    while True:
        stmt = (select(JournalEntry.id, JournalEntry.narrative)
                .where(JournalEntry.party_embedding.is_(None))
                .order_by(JournalEntry.id).limit(batch_size))
        if last_id is not None:
            stmt = stmt.where(JournalEntry.id > last_id)
        rows = (await session.execute(stmt)).all()
        if not rows:
            break
        for entry_id, narrative in rows:
            try:
                vector = list(embed_fn(narrative))
                if len(vector) != EMBEDDING_DIM:
                    raise ValueError(f"embedder returned {len(vector)} dims, expected {EMBEDDING_DIM}")
            except Exception:
                result.failed.append(entry_id)
                continue
            # IS NULL again: a journal write since the SELECT has already set it.
            done = await session.execute(
                update(JournalEntry)
                .where(JournalEntry.id == entry_id, JournalEntry.party_embedding.is_(None))
                .values(party_embedding=vector)
                .execution_options(synchronize_session=False)
            )
            result.embedded += done.rowcount
        await session.commit()
        result.batches += 1
        last_id = rows[-1][0]
    return result


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="SQLAlchemy async URL (default: $DATABASE_URL)")
    p.add_argument("--dry-run", action="store_true", help="count what would change; write nothing")
    return p


def _load_model() -> None:
    from app.services import embedding_service

    if embedding_service._model is not None:
        return
    try:
        embedding_service.load_embedding_model()
    except Exception as exc:
        print(f"warning: embedding model not loaded ({type(exc).__name__}: {exc}); "
              "party_embedding rows will fail and stay NULL", file=sys.stderr)


async def run(args: argparse.Namespace, *, embed: Embedder | None = None) -> BackfillResult:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if not args.database_url:
        raise SystemExit("error: no database: pass --database-url or set DATABASE_URL")
    if embed is None and not args.dry_run:
        _load_model()
    engine = create_async_engine(args.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await backfill(session, dry_run=args.dry_run, embed=embed)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = asyncio.run(run(args))
    print(result.summary())
    return 1 if result.failed else 0  # failed rows stay NULL; a rerun retries them


if __name__ == "__main__":
    sys.exit(main())
