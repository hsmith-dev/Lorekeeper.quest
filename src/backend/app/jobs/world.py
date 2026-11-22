"""`backfill.mentions`: suggested Mentions for old journal entries (E0-WorldCore.7, AD-18).

The `data_backfills` row `suggested_mentions_v1` (inserted by F3-world,
03c0b504f1d1) is run by the runner in app/jobs/backfill.py: one Job per
Campaign, as the Campaign Owner's GM ctx (never `as_system`), key
`backfill:suggested_mentions_v1:{campaign_id}`. The Job is a cursor Job
(`run_cursor`) over the Campaign's `kind = gm` entries in Session order,
`(session_date, else the UTC date of created_at; created_at; id)`, one entry per
step ("Entry 3 of 140").

Per entry (`suggest_mentions`): `match_names` on the Narrative only (never
Shorthand or `gm_notes`), the first match per Entity, and one
`apply_change(add_mention)` each with `confirmed = false`, `origin =
migration`, `source_field = narrative`, the match as the span and its
sentence (at most QUOTE_LIMIT characters, `sentence_quote`) as the quote.

**Idempotent and resumable.** A pair (entry, Entity) is skipped when any
Mention of it with source field `narrative` exists (confirmed or not, any
origin) or when the GM removed a `narrative` Mention of it, of any origin (a
`remove_mention` history row). The partial unique index
`uq_entity_mentions_suggested` backs that up: a conflicting insert is
`CanonChangeError("invalid")` inside apply_change's savepoint, which is
logged and skipped. Each step's Mentions, cursor and progress commit
together (app/jobs/worker.py), so a crash retries the same entry.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, scoped_select
from app.db.models.entity import EntityChange, EntityMention
from app.db.models.journal import JournalEntry
from app.domain.enums import EntityChangeOp, EntryKind, JobQueue, MentionOrigin, MentionSourceField
from app.jobs.backfill import CursorStep, register_backfill, run_cursor
from app.jobs.registry import JobKind, register
from app.schemas.entities import AddMention
from app.services.world_service import CanonChangeError, apply_change, match_names

logger = logging.getLogger(__name__)

BACKFILL_NAME = "suggested_mentions_v1"
KIND = "backfill.mentions"
QUOTE_LIMIT = 300

_ENDS = ".!?"

BACKFILL_MENTIONS = register(JobKind(
    name=KIND, queue=JobQueue.BACKFILL, timeout_s=120, handler="app.jobs.world:handle",
    resources=frozenset(), live_safe=True, result_audience="gm",
))
register_backfill(BACKFILL_NAME, KIND)


def step_key(campaign_id: uuid.UUID | str, cursor: Any) -> str:
    """The story's per-step key form. The runner's `backfill:{name}:{campaign_id}`
    is what actually dedupes: a continuation re-pushes the same Job id, so
    there is no per-step enqueue to key (kept for any future direct enqueue)."""
    return f"backfill.mentions:{campaign_id}:{cursor}"


# ── The quote ──────────────────────────────────────────────────────────────

def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    s = 0
    for i in range(start - 1, -1, -1):
        ch = text[i]
        if ch == "\n":
            s = i + 1
            break
        if ch in _ENDS and i + 1 < len(text) and text[i + 1].isspace():
            s = i + 1
            break
    e = len(text)
    for j in range(end, len(text)):
        ch = text[j]
        if ch == "\n":
            e = j
            break
        if ch in _ENDS and (j + 1 == len(text) or text[j + 1].isspace()):
            e = j + 1
            break
    return s, e


def sentence_quote(text: str, start: int, end: int, limit: int = QUOTE_LIMIT) -> str:
    """The sentence of `text` holding `[start, end)`, stripped; when longer than
    `limit`, a `limit`-character window of it that contains the match."""
    s, e = _sentence_bounds(text, start, end)
    sentence = text[s:e].strip()
    if len(sentence) <= limit:
        return sentence
    window = max(s, min(start, end - limit))
    return text[window:min(window + limit, e)].strip()


# ── One entry ──────────────────────────────────────────────────────────────

async def _has_mention(db: AsyncSession, ctx: CampaignContext, entry_id: uuid.UUID, entity_id: uuid.UUID) -> bool:
    stmt = (scoped_select(EntityMention, ctx)
            .where(EntityMention.journal_id == entry_id, EntityMention.entity_id == entity_id,
                   EntityMention.source_field == MentionSourceField.NARRATIVE.value)
            .with_only_columns(EntityMention.id).limit(1))
    return (await db.execute(stmt)).first() is not None


async def _was_removed(db: AsyncSession, ctx: CampaignContext, entry_id: uuid.UUID, entity_id: uuid.UUID) -> bool:
    old = EntityChange.old_value
    stmt = (scoped_select(EntityChange, ctx)
            .where(EntityChange.entity_id == entity_id, EntityChange.op == EntityChangeOp.REMOVE_MENTION.value,
                   old["journal_id"].astext == str(entry_id),
                   old["source_field"].astext == MentionSourceField.NARRATIVE.value)
            .with_only_columns(EntityChange.id).limit(1))
    return (await db.execute(stmt)).first() is not None


async def suggest_mentions(db: AsyncSession, ctx: CampaignContext, entry: JournalEntry) -> int:
    """Suggested Mentions for one entry's Narrative (module docstring); the
    number added. Never commits."""
    text = entry.narrative or ""
    first: dict[uuid.UUID, Any] = {}
    for m in await match_names(db, ctx, text):
        first.setdefault(m.entity_id, m)
    added = 0
    for entity_id, m in first.items():
        if await _has_mention(db, ctx, entry.id, entity_id) or await _was_removed(db, ctx, entry.id, entity_id):
            continue
        change = AddMention(
            entity_id=entity_id, journal_id=entry.id, source_journal_id=entry.id,
            source_field=MentionSourceField.NARRATIVE, origin=MentionOrigin.MIGRATION, confirmed=False,
            span_start=m.start, span_end=m.end, quote=sentence_quote(text, m.start, m.end))
        try:
            await apply_change(db, ctx, change)
        except CanonChangeError as exc:
            # Never the text: names and quotes are Campaign content.
            logger.info("suggested mention skipped", extra={
                "campaign_id": str(ctx.campaign_id), "entity_id": str(entity_id), "code": exc.code})
            continue
        added += 1
    return added


# ── The cursor ─────────────────────────────────────────────────────────────

def _key(session_date: date | None, created_at: datetime, entry_id: uuid.UUID) -> tuple[str, str, str]:
    key_date = session_date if session_date is not None else created_at.date()
    return key_date.isoformat(), created_at.isoformat(), str(entry_id)


def _decode(cursor: Any) -> tuple[date, datetime, str] | None:
    if cursor is None:
        return None
    d, c, i = cursor
    return date.fromisoformat(d), datetime.fromisoformat(c), str(i)


def _sortable(key: tuple[str, str, str]) -> tuple[date, datetime, str]:
    return date.fromisoformat(key[0]), datetime.fromisoformat(key[1]), key[2]


async def select_next(db: AsyncSession, ctx: CampaignContext, cursor: Any) -> CursorStep | None:
    """The first gm entry after `cursor` in Session order (sorted in Python)."""
    stmt = (scoped_select(JournalEntry, ctx)
            .where(JournalEntry.campaign_id == ctx.campaign_id, JournalEntry.kind == EntryKind.GM.value)
            .with_only_columns(JournalEntry.id, JournalEntry.session_date, JournalEntry.created_at))
    keys = sorted((_key(sd, ca, eid) for eid, sd, ca in (await db.execute(stmt)).all()), key=_sortable)
    after = _decode(cursor)
    nxt = next((k for k in keys if after is None or _sortable(k) > after), None)
    if nxt is None:
        return None
    entry = (await db.execute(scoped_select(JournalEntry, ctx).where(JournalEntry.id == uuid.UUID(nxt[2]))
                              .execution_options(populate_existing=True))).scalars().first()
    if entry is None:  # pragma: no cover - deleted between the two reads: retry the step
        raise LookupError("the next entry went away")
    return CursorStep(item=entry, cursor=list(nxt), total=len(keys))


async def _process_one(db: AsyncSession, ctx: CampaignContext, entry: JournalEntry) -> None:
    await suggest_mentions(db, ctx, entry)


async def handle(job: Any, ctx: CampaignContext, db: AsyncSession) -> None:
    """One step: the next gm entry of the Campaign."""
    await run_cursor(job, ctx, db, select_next=select_next, process_one=_process_one)


__all__ = ["BACKFILL_MENTIONS", "BACKFILL_NAME", "KIND", "QUOTE_LIMIT", "handle", "select_next", "sentence_quote",
           "step_key", "suggest_mentions"]
