"""Journal writers: the only module that assigns a JournalEntry's text and
index columns (E0-Journal.2, AD-17).

    entry = await create_journal_entry(db, ctx, notes, session_date, narrative=draft)
    entry = await update_journal_entry(db, ctx, entry, {"narrative": "..."})
    await delete_journal_entry(db, ctx, entry_id)
    await reindex_entry(db, entry)                      # index columns only, no hooks, no commit

`narrative`, `shorthand`, `entry_hash`, `narrative_tsv`, `party_tsv`,
`embedding`, `party_embedding` and the derived tag links are written here and
nowhere else (tests/test_journal_writers.py greps app/ and scripts/). Every
writer that changes Shorthand or Narrative goes through `_recompute_index`:

  * `narrative_tsv` (Shorthand + Narrative) and `party_tsv` (Narrative only)
    are computed in SQL from the stored row;
  * `embedding` (Shorthand + Narrative) and `party_embedding` (Narrative only)
    come from one `embed_many` call to the `ml` sidecar;
  * tags are re-derived from `ml /v1/ner` over the Narrative
    (`source_field=narrative`) and the Shorthand (`shorthand`); a tag found in
    both is `narrative`. `manual` links are kept, and so are legacy NULL links
    (one whose tag is re-derived takes the derived `source_field`, which can
    only narrow who sees it).

A save never blocks on `ml`: when it fails, the vectors are cleared and the
derived tags dropped, a warning is logged, and the `entry_saved` /
`entry_updated` handler (app/hooks/journal.py) enqueues a `journal.reembed`
onsave Job that runs `reindex_entry(strict=True)` (`reembed_job`). Services
never import app.jobs, so the enqueue lives in the hook layer.

`entry_hash = sha256(shorthand.strip().lower())` (utils/hashNotes.ts computes
the same value for the client's own dedup UX), always computed here; a hash a
client sends is ignored. A collision with another of the author's entries in
the Campaign (the Valkey dedup key, else the unique constraint) is a 409.

The create / update / delete writers commit, emit their hook event (refs
`{journal_id, kind, previous_entry_hash, entry_hash, changed_fields}`;
delete: `{journal_id, kind}`) and then update the dedup key. A Valkey failure
after the commit is logged, never raised.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.access import CampaignContext, can_write, scoped_get, scoped_select, set_visibility
from app.clients.errors import ModelServiceUnavailable
from app.core.hooks import HookEvent, emit
from app.db.models.journal import JournalEntry
from app.db.models.tag import JournalTag, Tag
from app.domain.embedding import EMBEDDING_DIM
from app.domain.enums import EntryKind, TagSourceField, Visibility
from app.schemas.sources import RecordRef
from app.services import embedding_service
from app.services.ai_service import generate_narrative
from app.services.dedup_service import check_hash, drop_hash, store_hash
from app.services.llm_provider import LLMConfig
from app.services.nlp_service import ExtractedTag, extract_tags
from app.services.shorthand_service import get_glossary
from app.services.source_service import retrieve_canon_context

logger = logging.getLogger(__name__)

# The fallback Job (registered in app/jobs/registry.py; enqueued by app/hooks/journal.py).
REEMBED_KIND = "journal.reembed"
DUPLICATE_DETAIL = "Duplicate entry detected"
_UNIQUE_HASH = "uq_journal_entries_campaign_user_entry_hash"
_TAG_NAME_MAX = 200
TEXT_FIELDS = frozenset({"shorthand", "narrative"})
# What update_journal_entry accepts (`notes` is the API's name for `shorthand`).
UPDATABLE_FIELDS = frozenset({"shorthand", "narrative", "session_date", "visibility"})
_DERIVED_SOURCES = (TagSourceField.NARRATIVE.value, TagSourceField.SHORTHAND.value)
_ENTRY_TAGS = selectinload(JournalEntry.tags).selectinload(Tag.custom_category)

# `embed=`: True (embedding_service.embed_many), False (never call ml; the
# vectors stay NULL), or any `async (texts) -> vectors` (the demo seed's).
EmbedMany = Callable[[list[str]], Awaitable[list[list[float]]]]


def compute_entry_hash(shorthand: str) -> str:
    """sha256 of the normalized Shorthand, as utils/hashNotes.ts computes it."""
    return hashlib.sha256(shorthand.strip().lower().encode("utf-8")).hexdigest()


def reembed_key(journal_id: uuid.UUID | str, entry_hash: str) -> str:
    """The `journal.reembed` idempotency key: one active Job per entry text."""
    return f"{REEMBED_KIND}:{journal_id}:{entry_hash}"


def _kind_value(entry: JournalEntry) -> str:
    return EntryKind(entry.kind or EntryKind.GM).value


def _visibility_kind(entry: JournalEntry) -> str:
    """The set_visibility kind of an entry (app/access/visibility.py)."""
    return "player_journal" if _kind_value(entry) == EntryKind.PLAYER.value else "journal"


def _is_duplicate(exc: IntegrityError) -> bool:
    return _UNIQUE_HASH in str(exc.orig)


def _duplicate() -> HTTPException:
    return HTTPException(status_code=409, detail=DUPLICATE_DETAIL)


# ── Dedup store (Valkey), best effort ──────────────────────────────────────

async def _dedup_has(campaign_id: uuid.UUID, user_id: uuid.UUID, entry_hash: str) -> bool:
    try:
        return await check_hash(campaign_id, user_id, entry_hash)
    except Exception as exc:  # noqa: BLE001 -- the unique constraint still catches it
        logger.warning("dedup check skipped, Valkey failed: %s", type(exc).__name__)
        return False


async def _dedup_store(campaign_id: uuid.UUID, user_id: uuid.UUID, entry_hash: str) -> None:
    try:
        await store_hash(campaign_id, user_id, entry_hash)
    except Exception as exc:  # noqa: BLE001 -- the write already committed
        logger.warning("dedup store skipped, Valkey failed: %s", type(exc).__name__)


async def _dedup_drop(campaign_id: uuid.UUID, user_id: uuid.UUID, entry_hash: str) -> None:
    try:
        await drop_hash(campaign_id, user_id, entry_hash)
    except Exception as exc:  # noqa: BLE001 -- the write already committed
        logger.warning("dedup drop skipped, Valkey failed: %s", type(exc).__name__)


# ── Generation ─────────────────────────────────────────────────────────────

async def generate_draft_narrative(
    db: AsyncSession,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    notes: str,
    config: LLMConfig | None = None,
    *,
    gm_context: bool,
) -> str:
    """The generation half of create_journal_entry, pulled out on its own so a
    narrative can be previewed and edited before anything is persisted (see
    POST /api/journals/generate-draft) — create_journal_entry calls this too
    when the caller doesn't already have an edited narrative to save.

    `gm_context` is required (no default, so a new caller cannot leak by
    forgetting it): False (a caller who is not GM of the Campaign) leaves out
    the GM-only context, no source-document canon and no Shorthand glossary,
    so a Player's draft is built from their own notes only (E0-Access.5)."""
    from app.db.models.campaign import Campaign
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = campaign_result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    canon_context = shorthand_glossary = None
    if gm_context:
        try:
            canon_context, _ = await retrieve_canon_context(db, notes, user_id, campaign_id)
        except Exception:
            canon_context = None  # RAG failure must not block journal generation
        try:
            shorthand_glossary = await get_glossary(db, campaign_id)
        except Exception:
            shorthand_glossary = None  # same — a glossary lookup failure must not block generation

    # Quick-entry length preference (Settings → AI). Same must-not-block
    # posture as the lookups above — a missing row just means no preference.
    paragraph_limit: int | None = None
    try:
        from app.db.models.user_settings import UserSettings
        us_result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        us = us_result.scalar_one_or_none()
        if us is not None:
            paragraph_limit = us.narrative_paragraph_limit
    except Exception:
        pass

    return await generate_narrative(
        notes, genre=campaign.genre.value, config=config,
        canon_context=canon_context, shorthand_glossary=shorthand_glossary,
        paragraph_limit=paragraph_limit,
    )


# ── The one recompute path ─────────────────────────────────────────────────

def _gm_text(entry: JournalEntry) -> str:
    """What `embedding` covers (and `narrative_tsv`, in SQL): Shorthand + Narrative."""
    return f"{entry.shorthand} {entry.narrative}"


def _checked_vector(vector: Any) -> list[float]:
    vector = list(vector)
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"embedder returned {len(vector)} dims, expected {EMBEDDING_DIM}")
    return vector


async def _derive(entry: JournalEntry, *, embed: bool | EmbedMany, tags: bool, strict: bool):
    """The ml half: (vectors or None, {(name, type): source_field} or None, ok).
    Writes nothing. `strict` raises the first ml failure; otherwise it is
    logged and ok is False (no vectors, no derived tags)."""
    derived: dict[tuple[str, Any], str] | None = None
    vectors: tuple[list[float] | None, list[float] | None] = (None, None)
    failed = down = False

    if tags:
        try:
            narrative_tags: list[ExtractedTag] = await extract_tags(entry.narrative)
            shorthand_tags: list[ExtractedTag] = (
                await extract_tags(entry.shorthand) if entry.shorthand and entry.shorthand.strip() else [])
        except Exception as exc:  # noqa: BLE001 -- ModelServiceError mostly; never block the save
            if strict:
                raise
            logger.warning("Tag extraction skipped, ml sidecar failed: %s", exc)
            failed, down = True, isinstance(exc, ModelServiceUnavailable)
        else:
            derived = {}
            # Narrative wins: written last, it overrides a Shorthand source.
            for source, found in ((TagSourceField.SHORTHAND, shorthand_tags),
                                  (TagSourceField.NARRATIVE, narrative_tags)):
                for t in found:
                    name = t.name.strip().title()[:_TAG_NAME_MAX]
                    if name:
                        derived[(name, t.tag_type)] = source.value

    if embed is not False:
        if failed:
            logger.warning("Journal embedding skipped, ml sidecar %s", "unavailable" if down else "failed earlier")
        else:
            embed_fn = embedding_service.embed_many if embed is True else embed
            try:
                gm_vec, party_vec = await embed_fn([_gm_text(entry), entry.narrative])
                vectors = (_checked_vector(gm_vec), _checked_vector(party_vec))
            except Exception as exc:  # noqa: BLE001 -- ModelServiceError mostly; never block the save
                if strict:
                    raise
                logger.warning("Journal embedding skipped, ml sidecar failed: %s", exc)
                failed = True

    if failed:
        return (None, None), ({} if tags else None), False
    return vectors, derived, True


async def _tag_ids(db: AsyncSession, keys: list[tuple[str, Any]]) -> dict[tuple[str, Any], uuid.UUID]:
    """Each (name, type)'s global Tag id, inserted when missing (one upsert)."""
    if not keys:
        return {}
    # One lock order for every writer: concurrent upserts of overlapping tag
    # sets never deadlock.
    keys = sorted(keys, key=lambda k: (k[0], str(getattr(k[1], "value", k[1]))))
    ins = pg_insert(Tag).values([{"id": uuid.uuid4(), "name": n, "tag_type": t} for n, t in keys])
    # DO UPDATE (a no-op) rather than DO NOTHING, so RETURNING yields existing rows too.
    stmt = ins.on_conflict_do_update(constraint="uq_tag_name_type", set_={"name": ins.excluded.name}) \
        .returning(Tag.id, Tag.name, Tag.tag_type)
    rows = (await db.execute(stmt)).all()
    return {(r.name, r.tag_type): r.id for r in rows}


async def _replace_derived_tags(db: AsyncSession, entry: JournalEntry, derived: dict[tuple[str, Any], str]) -> None:
    ids = await _tag_ids(db, list(derived))
    links = [{"journal_id": entry.id, "tag_id": ids[key], "source_field": source}
             for key, source in derived.items() if key in ids]
    if links:
        ins = pg_insert(JournalTag).values(links)
        # A manual link stays manual; a legacy NULL one takes the derived source.
        await db.execute(ins.on_conflict_do_update(
            index_elements=[JournalTag.journal_id, JournalTag.tag_id],
            set_={"source_field": ins.excluded.source_field},
            where=or_(JournalTag.source_field.is_(None), JournalTag.source_field != TagSourceField.MANUAL.value),
        ))
    keep = [link["tag_id"] for link in links]
    await db.execute(
        delete(JournalTag)
        .where(JournalTag.journal_id == entry.id, JournalTag.source_field.in_(_DERIVED_SOURCES),
               JournalTag.tag_id.not_in(keep) if keep else true())
        .execution_options(synchronize_session=False)
    )


async def _recompute_index(db: AsyncSession, entry: JournalEntry, *, embed: bool | EmbedMany = True,
                           tags: bool = True, strict: bool = False) -> bool:
    """Recompute every index column of `entry` from its stored text, in the
    caller's transaction. True when ml answered (vectors set, tags derived).

    `strict` (reindex, the reembed Job) raises an ml failure before anything
    is written. Otherwise a failure clears both vectors and drops the derived
    tags (manual and legacy links stay). `tags=False` leaves the tag links
    alone; `embed=False` never calls ml and leaves both vectors NULL."""
    vectors, derived, ok = await _derive(entry, embed=embed, tags=tags, strict=strict)
    await db.flush()  # the row exists and the stored text is the current one
    await db.execute(
        update(JournalEntry)
        .where(JournalEntry.id == entry.id)
        .values(narrative_tsv=func.to_tsvector("english", JournalEntry.shorthand + " " + JournalEntry.narrative),
                party_tsv=func.to_tsvector("english", JournalEntry.narrative))
        .execution_options(synchronize_session=False)
    )
    entry.embedding, entry.party_embedding = vectors
    if derived is not None:
        await _replace_derived_tags(db, entry, derived)
    await db.flush()
    return ok


async def reindex_entry(db: AsyncSession, entry: JournalEntry, *, strict: bool = False,
                        embed: bool | EmbedMany = True, tags: bool = True) -> bool:
    """Recompute `entry`'s index columns only: no hook, no commit, no change
    to its text or hash. `strict=True` (POST /reindex, the reembed Job)
    raises an ml failure before writing anything."""
    return await _recompute_index(db, entry, embed=embed, tags=tags, strict=strict)


async def _reload(db: AsyncSession, ctx: CampaignContext, entry: JournalEntry) -> JournalEntry:
    row = (await db.execute(
        scoped_select(JournalEntry, ctx).where(JournalEntry.id == entry.id).options(_ENTRY_TAGS)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    return row if row is not None else entry


def _refs(entry: JournalEntry, previous_hash: str | None, changed: list[str]) -> dict[str, Any]:
    return {"journal_id": entry.id, "kind": _kind_value(entry), "previous_entry_hash": previous_hash,
            "entry_hash": entry.entry_hash, "changed_fields": list(changed)}


# ── Writers ────────────────────────────────────────────────────────────────

async def create_journal_entry(
    db: AsyncSession,
    ctx: CampaignContext,
    notes: str,
    session_date: date | None = None,
    config: LLMConfig | None = None,
    narrative: str | None = None,
    *,
    offline: bool = False,
    kind: EntryKind = EntryKind.GM,
    visibility: Visibility | None = None,
    hooks: bool = True,
    tags: bool = True,
    embed: bool | EmbedMany = True,
    commit: bool = True,
) -> JournalEntry:
    """Persist a journal entry by ctx's user in ctx's Campaign.

    If `narrative` isn't supplied (the one-step generate-and-save path, e.g.
    the offline sync queue), it is generated here (generate_draft_narrative,
    GM context when ctx is GM). An entry nobody reviewed (no narrative given,
    or `offline`) lands `visibility=gm`; otherwise `visibility` (default the
    column's, party).

    A duplicate of the author's own entry in the Campaign (same normalized
    Shorthand) is a 409. Bulk loaders (the demo seed) pass `hooks=False`
    (no `entry_saved`), `commit=False` (they commit; no dedup key is stored),
    and `tags` / `embed` to keep ml out."""
    reviewed = narrative is not None
    if narrative is None:
        narrative = await generate_draft_narrative(db, ctx.user_id, ctx.campaign_id, notes, config,
                                                   gm_context=ctx.is_gm)
    if offline or not reviewed:
        visibility = Visibility.GM
    fields: dict[str, Any] = {}
    if visibility is not None:
        fields["visibility"] = Visibility(visibility)
    entry = JournalEntry(
        user_id=ctx.user_id, campaign_id=ctx.campaign_id, kind=EntryKind(kind).value,
        shorthand=notes, narrative=narrative, entry_hash=compute_entry_hash(notes),
        session_date=session_date, **fields,
    )
    can_write(ctx, entry)
    try:
        async with db.begin_nested():
            db.add(entry)
            await db.flush()
    except IntegrityError as exc:
        if _is_duplicate(exc):
            raise _duplicate() from None
        raise

    await _recompute_index(db, entry, embed=embed, tags=tags)
    if hooks:
        changed = ["narrative", "shorthand"] + (["session_date"] if session_date is not None else [])
        emit(db, HookEvent.ENTRY_SAVED, campaign_id=entry.campaign_id, refs=_refs(entry, None, changed),
             actor_ctx=ctx)
    if not commit:
        return entry
    await db.commit()
    await _dedup_store(entry.campaign_id, entry.user_id, entry.entry_hash)
    return await _reload(db, ctx, entry)


def _normalize_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in changes.items():
        field = "shorthand" if key == "notes" else key
        if field not in UPDATABLE_FIELDS:
            raise ValueError(f"update_journal_entry: {key!r} is not an editable field")
        if field in TEXT_FIELDS and not isinstance(value, str):
            raise ValueError(f"update_journal_entry: {key!r} must be a string")
        if field == "session_date" and value is not None and not isinstance(value, date):
            raise ValueError("update_journal_entry: 'session_date' must be a date or None")
        out[field] = Visibility(value) if field == "visibility" else value
    return out


async def update_journal_entry(db: AsyncSession, ctx: CampaignContext, entry: JournalEntry,
                               changes: Mapping[str, Any]) -> JournalEntry:
    """Apply `changes` (any of shorthand / `notes`, narrative, session_date,
    visibility) to `entry`, which the caller loaded through ctx.

    A Shorthand or Narrative change recomputes every index column and the
    hash; a hash that collides with another of the author's entries in the
    Campaign is a 409 with nothing written. A date or Visibility change
    recomputes nothing; Visibility goes through `set_visibility`. Emits
    `entry_updated` (only when something changed) and commits."""
    changes = _normalize_changes(changes)
    can_write(ctx, entry)
    changed = sorted(f for f, value in changes.items() if getattr(entry, f) != value)
    if not changed:
        return entry

    previous_hash = entry.entry_hash
    new_hash = compute_entry_hash(changes["shorthand"]) if "shorthand" in changed else previous_hash
    hash_changed = new_hash != previous_hash
    if hash_changed and await _dedup_has(entry.campaign_id, entry.user_id, new_hash):
        raise _duplicate()

    try:
        async with db.begin_nested():
            if "shorthand" in changed:
                entry.shorthand = changes["shorthand"]
            if "narrative" in changed:
                entry.narrative = changes["narrative"]
            if "session_date" in changed:
                entry.session_date = changes["session_date"]
            if hash_changed:
                entry.entry_hash = new_hash
            await db.flush()
    except IntegrityError as exc:
        if _is_duplicate(exc):
            raise _duplicate() from None
        raise

    if "visibility" in changed:
        await set_visibility(db, ctx, RecordRef(kind=_visibility_kind(entry), id=entry.id), changes["visibility"])
    if TEXT_FIELDS & set(changed):
        await _recompute_index(db, entry)
    emit(db, HookEvent.ENTRY_UPDATED, campaign_id=entry.campaign_id, refs=_refs(entry, previous_hash, changed),
         actor_ctx=ctx)
    await db.commit()
    if hash_changed:
        await _dedup_drop(entry.campaign_id, entry.user_id, previous_hash)
        await _dedup_store(entry.campaign_id, entry.user_id, new_hash)
    return await _reload(db, ctx, entry)


async def delete_journal_entry(db: AsyncSession, ctx: CampaignContext, entry_id: uuid.UUID | str) -> None:
    """Delete an entry ctx may see and write (anything else is the one 404),
    with its tag links; emit `entry_deleted {journal_id, kind}`, commit, and
    drop its dedup key."""
    entry = await scoped_get(db, JournalEntry, ctx, entry_id)
    can_write(ctx, entry)
    campaign_id, user_id, entry_hash = entry.campaign_id, entry.user_id, entry.entry_hash
    refs = {"journal_id": entry.id, "kind": _kind_value(entry)}
    await db.delete(entry)  # its journal_tags rows go with it (secondary, ON DELETE CASCADE)
    emit(db, HookEvent.ENTRY_DELETED, campaign_id=campaign_id, refs=refs, actor_ctx=ctx)
    await db.commit()
    await _dedup_drop(campaign_id, user_id, entry_hash)


# ── The fallback Job and its hook check ────────────────────────────────────

async def needs_reembed(db: AsyncSession, ctx: CampaignContext, journal_id: uuid.UUID | str,
                        entry_hash: str | None) -> bool:
    """True when the entry (as ctx sees it) still has `entry_hash` and a
    NULL vector: the save fell back, so `journal.reembed` should fill it."""
    row = (await db.execute(
        scoped_select(JournalEntry, ctx).where(JournalEntry.id == uuid.UUID(str(journal_id)))
        .with_only_columns(JournalEntry.entry_hash,
                           or_(JournalEntry.embedding.is_(None), JournalEntry.party_embedding.is_(None)))
    )).first()
    return row is not None and row[0] == entry_hash and bool(row[1])


async def reembed_job(job: Any, ctx: CampaignContext, db: AsyncSession) -> None:
    """`journal.reembed` (onsave, cpu_heavy): `reindex_entry(strict=True)` for
    the entry named in the payload. An entry deleted, hidden from the starter
    or edited (another hash) since is a no-op, `done`. ml down raises, so the
    Job retries. Never commits (the worker does)."""
    payload = job.payload or {}
    try:
        journal_id = uuid.UUID(str(payload.get("journal_id")))
    except (TypeError, ValueError):
        return None
    entry = (await db.execute(
        scoped_select(JournalEntry, ctx).where(JournalEntry.id == journal_id)
    )).scalar_one_or_none()
    if entry is None or entry.entry_hash != payload.get("entry_hash"):
        return None
    await reindex_entry(db, entry, strict=True)
    return None


# ── Party fields and the backfill helpers ──────────────────────────────────

async def index_party_fields(
    db: AsyncSession, entry: JournalEntry, *, party_vector: list[float] | None = None,
    skip_embed: bool = False,
) -> None:
    """Set only `entry`'s Party search fields from its stored Narrative, in
    the caller's transaction: `party_tsv` in SQL and `party_embedding =
    embed(narrative)` (`party_vector` when the caller has it; NULL with
    `skip_embed`). An embedding failure leaves it NULL and never raises.
    The writers use `_recompute_index`; this is the narrower form kept for
    retrieval_service.index_party_fields (EV-4 probes)."""
    await db.flush()
    await db.execute(
        update(JournalEntry)
        .where(JournalEntry.id == entry.id)
        .values(party_tsv=func.to_tsvector("english", JournalEntry.narrative))
        .execution_options(synchronize_session=False)
    )
    if party_vector is not None or skip_embed:
        entry.party_embedding = party_vector
        return
    try:
        vector = await embedding_service.embed(entry.narrative)
    except Exception:
        vector = None  # ml sidecar down / failure: non-GM vector search skips the row
    entry.party_embedding = vector


def stale_party_tsv():
    """Rows whose `party_tsv` is NULL or not to_tsvector(narrative)."""
    expected = func.to_tsvector("english", JournalEntry.narrative)
    return or_(JournalEntry.party_tsv.is_(None), JournalEntry.party_tsv.is_distinct_from(expected))


async def refresh_party_tsv(db: AsyncSession, *where: Any) -> int:
    """Set-based: `party_tsv = to_tsvector(narrative)` where it is stale (and
    `where`). Returns the row count. The caller commits."""
    result = await db.execute(
        update(JournalEntry).where(stale_party_tsv(), *where)
        .values(party_tsv=func.to_tsvector("english", JournalEntry.narrative))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


async def fill_party_embedding(db: AsyncSession, entry_id: uuid.UUID, vector: list[float]) -> int:
    """Set a NULL `party_embedding` (a journal write since may have set it
    already: then nothing changes). Returns the row count."""
    result = await db.execute(
        update(JournalEntry)
        .where(JournalEntry.id == entry_id, JournalEntry.party_embedding.is_(None))
        .values(party_embedding=_checked_vector(vector))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount
