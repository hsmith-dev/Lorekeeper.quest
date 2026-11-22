"""E0-WorldCore.7: the `backfill.mentions` cursor Job (app/jobs/world.py).

DB tests cover the backfill matrix: the happy path through the real
`suggested_mentions_v1` row and the runner (narrowed to this test's Campaign
with `ours`), Session order, re-runs, a removed suggestion, an existing
Mention, Shorthand / gm_notes only, player entries, and the partial unique
index. The pure tests (`-k "quote or registration"`) need no database.

The real row is shared by the whole test database: `mention_backfill`
re-queues it for one test and parks it (`done`) afterwards, so no other
test's runner pass ever runs it.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
import sqlalchemy as sa

from app.access.context import ctx_for
from app.db.models.entity import EntityChange, EntityMention
from app.db.models.job import DataBackfill, Job
from app.db.models.journal import JournalEntry
from app.domain.enums import JobQueue, JobStatus
from app.jobs import world
from app.jobs.backfill import BACKFILLS, run_backfills
from app.jobs.enqueue import enqueue
from app.jobs.registry import KIND_MODULES, get_kind
from app.jobs.world import BACKFILL_NAME, KIND, QUOTE_LIMIT, select_next, sentence_quote, step_key, suggest_mentions
from app.schemas.entities import AddMention, CreateEntity, RemoveMention
from app.services.world_service import CanonChangeError, apply_change
from tests.jobs.test_backfill import _campaign, _factory, ours  # noqa: F401  (ours: fixture)


# ── Pure: the quote ────────────────────────────────────────────────────────

def _quote(text: str, surface: str, nth: int = 0) -> str:
    start = -1
    for _ in range(nth + 1):
        start = text.index(surface, start + 1)
    return sentence_quote(text, start, start + len(surface))


def test_quote_first_sentence():
    assert _quote("Mira ran to the docks. Later Mira slept.", "Mira") == "Mira ran to the docks."


def test_quote_middle_of_three():
    assert _quote("It rained. Then Bree came! Was it late?", "Bree") == "Then Bree came!"


def test_quote_second_match_is_its_own_sentence():
    assert _quote("Mira ran to the docks. Later Mira slept.", "Mira", nth=1) == "Later Mira slept."


def test_quote_newline_boundary():
    assert _quote("The first line\n  Mira walks here  \nthe last line", "Mira") == "Mira walks here"


def test_quote_a_period_inside_a_word_is_not_a_boundary():
    assert _quote("We paid 3.5 gold to Mira at noon. Then we left.", "Mira") == "We paid 3.5 gold to Mira at noon."


def test_quote_long_sentence_is_a_window_holding_the_match():
    text = "word " * 120 + "Mira" + " more" * 80 + "."
    quote = _quote(text, "Mira")
    assert len(quote) <= QUOTE_LIMIT and "Mira" in quote and quote == quote.strip()
    early = "Mira " + "word " * 120 + "end."
    quote = _quote(early, "Mira")
    assert len(quote) <= QUOTE_LIMIT and quote.startswith("Mira") and quote == quote.strip()


def test_quote_match_at_the_end_of_the_text():
    assert _quote("Nobody but Mira", "Mira") == "Nobody but Mira"
    assert _quote("First. We saw Mira", "Mira") == "We saw Mira"


# ── Pure: the registration ─────────────────────────────────────────────────

def test_registration_values():
    kind = get_kind("backfill.mentions")
    assert (kind.queue, kind.timeout_s, kind.handler, kind.resources, kind.live_safe, kind.result_audience) == (
        JobQueue.BACKFILL, 120, "app.jobs.world:handle", frozenset(), True, "gm")
    assert BACKFILLS["suggested_mentions_v1"] == KIND == "backfill.mentions"
    assert BACKFILL_NAME == "suggested_mentions_v1" and QUOTE_LIMIT == 300
    assert "app.jobs.world" in KIND_MODULES
    cid = uuid.uuid4()
    assert step_key(cid, 3) == f"backfill.mentions:{cid}:3"


# ── DB helpers ─────────────────────────────────────────────────────────────

@pytest.fixture
async def mention_backfill(db):
    """The real `suggested_mentions_v1` row, queued now (after the test's
    Campaigns exist: call the returned function), parked `done` afterwards."""

    async def queue() -> None:
        row = (await db.execute(sa.select(DataBackfill).where(DataBackfill.name == BACKFILL_NAME)
                                .execution_options(populate_existing=True))).scalar_one_or_none()
        if row is None:
            db.add(DataBackfill(name=BACKFILL_NAME))
        else:
            row.status = JobStatus.QUEUED
            row.cursor = None
            row.job_id = None
            row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    yield queue
    await db.rollback()
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name == BACKFILL_NAME).values(status="done"))
    await db.commit()


async def _gm(db, campaign):
    return await ctx_for(db, campaign.user_id, campaign.id)


async def _entity(db, ctx, name: str, **kw) -> uuid.UUID:
    return (await apply_change(db, ctx, CreateEntity(type="character", kind="npc", name=name, **kw))).entity_id


async def _entry(db, campaign, narrative: str, *, shorthand: str = "s", kind: str = "gm",
                 session_date: date | None = date(2026, 3, 1), created_at: datetime | None = None) -> uuid.UUID:
    entry = JournalEntry(id=uuid.uuid4(), user_id=campaign.user_id, campaign_id=campaign.id, shorthand=shorthand,
                         narrative=narrative, entry_hash=uuid.uuid4().hex, session_date=session_date, kind=kind,
                         visibility="party")
    if created_at is not None:
        entry.created_at = created_at
    db.add(entry)
    await db.flush()
    return entry.id


async def _load(db, ctx, entry_id) -> JournalEntry:
    from app.access import scoped_select

    return (await db.execute(scoped_select(JournalEntry, ctx).where(JournalEntry.id == entry_id)
                             .execution_options(populate_existing=True))).scalars().one()


async def _mentions(db, campaign_id) -> list[EntityMention]:
    return list((await db.execute(sa.select(EntityMention).where(EntityMention.campaign_id == campaign_id)
                                  .execution_options(populate_existing=True))).scalars().all())


async def _history(db, campaign_id, op: str = "add_mention") -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(EntityChange).where(
        EntityChange.campaign_id == campaign_id, EntityChange.op == op))).scalar_one()


async def _pairs(db, campaign_id) -> list[tuple]:
    return sorted((m.journal_id, m.entity_id) for m in await _mentions(db, campaign_id))


# ── The backfill ───────────────────────────────────────────────────────────

async def test_happy_path_through_the_runner(db, ours, mention_backfill):
    c = await _campaign(db, ours)
    gm = await _gm(db, c)
    mira, bree = await _entity(db, gm, "Mira"), await _entity(db, gm, "Bree")
    e1 = await _entry(db, c, "Mira ran to the docks. Later Mira slept.", session_date=date(2026, 3, 1))
    e2 = await _entry(db, c, "It rained. Bree and Mira fought!", session_date=date(2026, 3, 2))
    await _entry(db, c, "Nobody came.", session_date=date(2026, 3, 3))
    p = await _entry(db, c, "Mira was here.", kind="player", session_date=date(2026, 3, 4))
    await db.commit()
    await mention_backfill()

    assert await run_backfills(_factory(db)) == {BACKFILL_NAME: JobStatus.RUNNING}  # eager: the Job ran
    bf = (await db.execute(sa.select(DataBackfill).where(DataBackfill.name == BACKFILL_NAME)
                           .execution_options(populate_existing=True))).scalar_one()
    assert bf.cursor["campaigns"] == [str(c.id)]
    job = (await db.execute(sa.select(Job).where(Job.id == uuid.UUID(bf.cursor["jobs"][str(c.id)]))
                            .execution_options(populate_existing=True))).scalar_one()
    assert (job.kind, job.queue, job.idempotency_key) == (KIND, JobQueue.BACKFILL,
                                                          f"backfill:suggested_mentions_v1:{c.id}")
    assert (job.status, job.stage, job.progress, job.ctx_kind) == (JobStatus.DONE, "Entry 3 of 3", 1.0, "gm")
    entries = bf.cursor["entries"][str(c.id)]
    assert (entries["done"], entries["total"]) == (3, 3) and entries["cursor"] == job.payload["cursor"]

    rows = {(m.journal_id, m.entity_id): m for m in await _mentions(db, c.id)}
    assert set(rows) == {(e1, mira), (e2, mira), (e2, bree)}
    assert (p, mira) not in rows
    first = rows[(e1, mira)]
    assert (first.span_start, first.span_end, first.quote) == (0, 4, "Mira ran to the docks.")
    assert rows[(e2, bree)].quote == rows[(e2, mira)].quote == "Bree and Mira fought!"
    for m in rows.values():
        assert (m.confirmed, m.origin, m.source_field) == (False, "migration", "narrative")
    assert await _history(db, c.id) == 3

    assert await run_backfills(_factory(db)) == {BACKFILL_NAME: JobStatus.DONE}
    assert await run_backfills(_factory(db)) == {}  # done: never touched again


async def test_entries_are_processed_in_session_order(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    utc = timezone.utc
    later = await _entry(db, c, "a", session_date=date(2026, 3, 2), created_at=datetime(2026, 3, 1, 9, tzinfo=utc))
    undated = await _entry(db, c, "b", session_date=None, created_at=datetime(2026, 3, 1, 12, tzinfo=utc))
    same_day = await _entry(db, c, "c", session_date=date(2026, 3, 1),
                            created_at=datetime(2026, 3, 4, 8, tzinfo=utc))
    await _entry(db, c, "d", kind="player", session_date=date(2026, 2, 1))  # never a step
    await db.commit()
    seen, cursor = [], None
    while (step := await select_next(db, gm, cursor)) is not None:
        seen.append(step.item.id)
        assert step.total == 3
        cursor = step.cursor
    assert seen == [undated, same_day, later]


async def test_rerun_adds_nothing(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    await _entity(db, gm, "Mira")
    await _entity(db, gm, "Bree")
    ids = [await _entry(db, c, "Mira ran. Mira hid."), await _entry(db, c, "Bree met Mira.")]
    for entry_id in ids:
        await suggest_mentions(db, gm, await _load(db, gm, entry_id))
    await db.commit()
    before = (await _pairs(db, c.id), await _history(db, c.id))
    assert before[1] == 3
    for entry_id in ids:
        assert await suggest_mentions(db, gm, await _load(db, gm, entry_id)) == 0
    await db.commit()
    # A fresh Job (no cursor) over the same Campaign.
    job_id = await enqueue(db, gm, KIND, {}, idempotency_key=f"test:{uuid.uuid4().hex}")
    await db.commit()  # eager: every step runs here
    job = (await db.execute(sa.select(Job).where(Job.id == job_id)
                            .execution_options(populate_existing=True))).scalar_one()
    assert job.status == JobStatus.DONE and job.stage == "Entry 2 of 2"
    assert (await _pairs(db, c.id), await _history(db, c.id)) == before


async def test_a_removed_suggestion_is_not_recreated(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    mira = await _entity(db, gm, "Mira")
    e1 = await _entry(db, c, "Mira ran.")
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 1
    [m] = await _mentions(db, c.id)
    await apply_change(db, gm, RemoveMention(mention_id=m.id))
    await db.commit()
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 0
    assert await _pairs(db, c.id) == [] and await _history(db, c.id, "remove_mention") == 1


async def test_a_removed_manual_mention_also_blocks_a_suggestion(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    mira = await _entity(db, gm, "Mira")
    e1 = await _entry(db, c, "Mira ran.")
    row = await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, quote="manual"))
    await apply_change(db, gm, RemoveMention(mention_id=uuid.UUID(row.new_value["mention_id"])))
    await db.commit()
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 0
    # A removed Shorthand Mention of the pair does not block the Narrative suggestion.
    e2 = await _entry(db, c, "Mira hid.")
    row = await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e2, source_field="shorthand"))
    await apply_change(db, gm, RemoveMention(mention_id=uuid.UUID(row.new_value["mention_id"])))
    await db.commit()
    assert await suggest_mentions(db, gm, await _load(db, gm, e2)) == 1


async def test_an_existing_mention_blocks_a_suggestion(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    mira = await _entity(db, gm, "Mira")
    e1 = await _entry(db, c, "Mira ran.")
    await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, confirmed=True, quote="manual"))
    await db.commit()
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 0
    rows = await _mentions(db, c.id)
    assert [(m.confirmed, m.origin) for m in rows] == [(True, "manual")]


async def test_shorthand_and_gm_notes_are_never_matched(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    await _entity(db, gm, "Mira")
    await _entity(db, gm, "Bree", gm_notes="Mira is her sister")
    e1 = await _entry(db, c, "A quiet day.", shorthand="Mira, Bree")
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 0
    assert await _mentions(db, c.id) == []


async def test_the_partial_unique_index_rejects_a_second_suggestion(db):
    c = await _campaign(db)
    gm = await _gm(db, c)
    mira = await _entity(db, gm, "Mira")
    e1 = await _entry(db, c, "Mira ran. Mira hid.")
    await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, quote="Mira ran.", span_start=0,
                                          span_end=4))
    with pytest.raises(CanonChangeError) as err:
        await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, quote="Mira hid.", span_start=10,
                                              span_end=14))
    assert err.value.code == "invalid"
    # Confirmed rows are not constrained.
    await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, quote="Mira hid.", span_start=10,
                                          span_end=14, confirmed=True))
    await db.commit()
    assert len(await _mentions(db, c.id)) == 2


async def test_a_conflicting_suggestion_is_skipped_not_raised(db, monkeypatch):
    c = await _campaign(db)
    gm = await _gm(db, c)
    mira = await _entity(db, gm, "Mira")
    e1 = await _entry(db, c, "Mira ran.")
    # Another suggestion of the pair lands between the check and the write.
    await apply_change(db, gm, AddMention(entity_id=mira, journal_id=e1, quote="other", origin="extraction"))

    async def nothing_yet(*args, **kwargs):
        return False

    monkeypatch.setattr(world, "_has_mention", nothing_yet)
    assert await suggest_mentions(db, gm, await _load(db, gm, e1)) == 0
    assert len(await _mentions(db, c.id)) == 1
