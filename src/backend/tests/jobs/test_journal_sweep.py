"""`journal.reembed_sweep` (app/jobs/journal.py, E0-Journal.2): the durable
backstop that fills journal entries left with a NULL vector, once through the
`journal_reembed_v1` backfill and daily through `schedule_daily`. While ml is
down it does nothing (no failed Job, no per-row ml calls)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access.context import ctx_for
from app.clients.errors import ModelServiceUnavailable
from app.clients.fakes import FakeMLClient, fake_vector
from app.db.models.campaign import Campaign, Genre
from app.db.models.job import Job
from app.db.models.journal import JournalEntry
from app.db.models.user import User
from app.domain.enums import JobQueue
from app.jobs import journal as journal_jobs
from app.jobs.backfill import BACKFILLS
from app.jobs.registry import KIND_MODULES, get_kind
from app.services import embedding_service, nlp_service


class _CountingML(FakeMLClient):
    def __init__(self) -> None:
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        return await super().embed(texts)


class _DownML:
    def __init__(self) -> None:
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")

    async def ner(self, text):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")


def _ml(monkeypatch, client) -> None:
    monkeypatch.setattr(embedding_service, "_override", client)
    monkeypatch.setattr(nlp_service, "get_ml_client", lambda: client)


@pytest.fixture
def ml_up(monkeypatch):
    client = _CountingML()
    _ml(monkeypatch, client)
    return client


@pytest.fixture
def ml_down(monkeypatch):
    client = _DownML()
    _ml(monkeypatch, client)
    return client


class _Redis:
    """The SET NX / EX / DELETE subset schedule_daily uses."""

    def __init__(self) -> None:
        self.keys: dict[str, tuple[str, int | None]] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return False
        self.keys[key] = (value, ex)
        return True

    async def delete(self, key):
        self.keys.pop(key, None)


async def _campaign(db) -> Campaign:
    owner = User(email=f"sweep-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                 display_name="owner", access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Sweep", genre=Genre.fantasy)
    db.add(c)
    await db.commit()
    return c


async def _entry(db, c: Campaign, narrative: str, *, embedded: bool = False) -> uuid.UUID:
    entry = JournalEntry(user_id=c.user_id, campaign_id=c.id, shorthand=f"notes {uuid.uuid4().hex[:6]}",
                         narrative=narrative, entry_hash=uuid.uuid4().hex, kind="gm", visibility="party")
    if embedded:
        entry.embedding = fake_vector("already")
        entry.party_embedding = fake_vector("already")
    db.add(entry)
    await db.commit()
    return entry.id


async def _vectors(db, entry_id):
    return (await db.execute(sa.select(JournalEntry.embedding, JournalEntry.party_embedding)
                             .where(JournalEntry.id == entry_id).execution_options(populate_existing=True))).one()


async def _run_sweep(db, c: Campaign, *, max_steps: int = 20) -> SimpleNamespace:
    """Run the handler step by step the way the worker would (one commit per step)."""
    ctx = await ctx_for(db, c.user_id, c.id)
    job = SimpleNamespace(payload={}, campaign_id=c.id, progress=None, stage=None, eta_seconds=None)
    for _ in range(max_steps):
        job._continue = False
        await journal_jobs.handle(job, ctx, db)
        await db.commit()
        if not job._continue:
            return job
    raise AssertionError("the sweep did not finish")


def test_registration():
    kind = get_kind(journal_jobs.SWEEP_KIND)
    assert kind.queue == JobQueue.BACKFILL and kind.resources == frozenset({"cpu_heavy"}) and not kind.live_safe
    assert BACKFILLS[journal_jobs.BACKFILL_NAME] == journal_jobs.SWEEP_KIND == "journal.reembed_sweep"
    assert "app.jobs.journal" in KIND_MODULES


async def test_sweep_fills_every_unembedded_entry_and_leaves_the_rest(db, ml_up):
    c = await _campaign(db)
    a = await _entry(db, c, "Mira crossed the bridge.")
    b = await _entry(db, c, "Borin slept at the inn.")
    done = await _entry(db, c, "Already indexed.", embedded=True)
    job = await _run_sweep(db, c)
    assert job.payload["done"] == 2
    for entry_id, narrative in ((a, "Mira crossed the bridge."), (b, "Borin slept at the inn.")):
        gm_vec, party_vec = await _vectors(db, entry_id)
        assert gm_vec is not None
        assert list(party_vec) == pytest.approx(fake_vector(narrative), abs=1e-5)
    assert list((await _vectors(db, done))[1]) == pytest.approx(fake_vector("already"), abs=1e-5)


async def test_sweep_with_ml_down_is_a_noop_not_a_failure(db, ml_down):
    c = await _campaign(db)
    a = await _entry(db, c, "Mira crossed the bridge.")
    await _entry(db, c, "Borin slept at the inn.")
    job = await _run_sweep(db, c)
    assert job.payload == {}  # the probe failed: no step ran, no cursor
    assert ml_down.embed_calls == 1  # one probe, never one call per row
    assert (await _vectors(db, a)) == (None, None)


async def test_sweep_skips_a_row_whose_ml_call_fails_and_moves_on(db, ml_up, monkeypatch):
    c = await _campaign(db)
    first = await _entry(db, c, "First entry.")
    second = await _entry(db, c, "Second entry.")
    real = ml_up.embed

    async def flaky(texts):
        if "First entry." in texts:
            raise ModelServiceUnavailable("ml sidecar unreachable")
        return await real(texts)

    monkeypatch.setattr(ml_up, "embed", flaky)
    job = await _run_sweep(db, c)
    assert job.payload["done"] == 2
    assert (await _vectors(db, first)) == (None, None)  # left for the next sweep
    assert (await _vectors(db, second))[1] is not None


@pytest.fixture
def only(monkeypatch):
    """Narrow schedule_daily to the Campaigns a test adds."""
    allowed: set[uuid.UUID] = set()
    from app.access.owners import campaign_owners

    async def narrowed(db, *, created_before):
        return {cid: owner for cid, owner in (await campaign_owners(db, created_before=created_before)).items()
                if cid in allowed}

    monkeypatch.setattr(journal_jobs, "campaign_owners", narrowed)
    return allowed


async def test_schedule_daily_with_ml_down_enqueues_nothing_and_retries_soon(db, ml_down, only):
    c = await _campaign(db)
    only.add(c.id)
    await _entry(db, c, "Unembedded.")
    redis = _Redis()
    now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    assert await journal_jobs.schedule_daily(factory, redis, now=now) == []
    value, ex = redis.keys[journal_jobs.day_key(now)]
    assert value == "ml_down" and ex == journal_jobs.ML_RETRY_S
    count = await db.scalar(sa.select(sa.func.count()).select_from(Job).where(
        Job.idempotency_key == journal_jobs.sweep_key(c.id)))
    assert count == 0


async def test_schedule_daily_enqueues_one_sweep_per_campaign_with_work_once_a_day(db, ml_up, only):
    busy, idle = await _campaign(db), await _campaign(db)
    only.update({busy.id, idle.id})
    entry_id = await _entry(db, busy, "Lost hook, NULL vectors.")
    await _entry(db, idle, "All indexed.", embedded=True)
    redis = _Redis()
    now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    jobs = await journal_jobs.schedule_daily(factory, redis, now=now)
    assert len(jobs) == 1
    job = (await db.execute(sa.select(Job).where(Job.id == jobs[0]))).scalar_one()
    assert (job.kind, job.campaign_id, job.idempotency_key) == (
        journal_jobs.SWEEP_KIND, busy.id, journal_jobs.sweep_key(busy.id))
    # Under JOBS_EAGER the Job ran at commit: the entry is filled.
    assert (await _vectors(db, entry_id))[1] is not None
    # Once per day.
    assert await journal_jobs.schedule_daily(factory, redis, now=now) == []
