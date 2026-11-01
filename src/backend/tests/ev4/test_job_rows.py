"""EV-4 (E0-Jobs.5): the Job rows this story creates stay GM-only.

The data_backfills runner starts Jobs as each Campaign's Owner, with
progress and stage on the row; admission leaves deferred rows with a
waiting stage. Through `scoped_select(Job, ctx)` neither is visible to a
Player of that Campaign or to a GM of another Campaign, while a Player's
own Job (deferred included) stays visible to them.
"""
from __future__ import annotations

import uuid

import fakeredis
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access.context import ctx_for
from app.access.registry import scoped_select
from app.core.valkey_client import set_valkey
from app.db.models import Campaign, Genre, Job, User
from app.db.models.campaign_member import CampaignMember
from app.db.models.job import DataBackfill
from app.domain.enums import CampaignRole, JobQueue, JobStatus
from app.jobs import backfill
from app.jobs.admission import WAITING_STAGE
from app.jobs.backfill import CursorStep, register_backfill, run_backfills, run_cursor
from app.jobs.registry import JobKind, register
from app.jobs.worker import run_job


async def _two_steps(job, ctx, db):
    async def select_next(db, ctx, cursor):
        return None if (cursor or 0) >= 2 else CursorStep(item=None, cursor=(cursor or 0) + 1, total=2)

    async def process_one(db, ctx, item):
        return None

    await run_cursor(job, ctx, db, select_next=select_next, process_one=process_one)


async def _noop(job, ctx, db):
    return None


register(JobKind(name="test_ev4j.backfill", queue=JobQueue.BACKFILL, timeout_s=10,
                 handler=f"{__name__}:_two_steps"))
register(JobKind(name="test_ev4j.heavy", queue=JobQueue.ONSAVE, timeout_s=10, handler=f"{__name__}:_noop",
                 resources=frozenset({"cpu_heavy"})))


def _user(label: str) -> User:
    return User(email=f"ev4j-{label}-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                display_name=label, access_granted=True, access_source="promo")


async def _campaign(db) -> Campaign:
    owner = _user("owner")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="EV4 Jobs", genre=Genre.fantasy)
    db.add(c)
    await db.flush()
    return c


async def _player(db, c: Campaign) -> User:
    u = _user("player")
    db.add(u)
    await db.flush()
    db.add(CampaignMember(campaign_id=c.id, user_id=u.id, role=CampaignRole.PLAYER))
    await db.flush()
    return u


async def _job(db, c: Campaign, user_id, ctx_kind: str, kind: str = "test_ev4j.heavy") -> Job:
    row = Job(campaign_id=c.id, kind=kind, queue=JobQueue.ONSAVE, idempotency_key=f"test:{uuid.uuid4().hex}",
              ctx_kind=ctx_kind, ctx_user_id=user_id, created_by=user_id, access_epoch=0, payload={})
    db.add(row)
    await db.commit()
    return row


async def _visible(db, ctx, ids) -> set[uuid.UUID]:
    return {j.id for j in (await db.scalars(scoped_select(Job, ctx).where(Job.id.in_(list(ids))))).all()}


@pytest.fixture
async def world(db):
    c, other = await _campaign(db), await _campaign(db)
    player = await _player(db, c)
    await db.commit()
    return c, other, player


async def test_runner_jobs_with_progress_are_gm_only(db, world, monkeypatch):
    c, other, player = world
    name = f"test_ev4j_{uuid.uuid4().hex[:12]}"
    register_backfill(name, "test_ev4j.backfill")

    async def only_c(db, *, created_before):
        return {c.id: c.user_id}

    monkeypatch.setattr(backfill, "campaign_owners", only_c)
    db.add(DataBackfill(name=name))
    await db.commit()
    try:
        await run_backfills(async_sessionmaker(db.bind, expire_on_commit=False))  # eager: runs inline
        bf = (await db.execute(sa.select(DataBackfill).where(DataBackfill.name == name)
                               .execution_options(populate_existing=True))).scalar_one()
        job_id = uuid.UUID(bf.cursor["jobs"][str(c.id)])
        job = (await db.execute(sa.select(Job).where(Job.id == job_id)
                                .execution_options(populate_existing=True))).scalar_one()
        assert job.status == JobStatus.DONE and job.stage == "Entry 2 of 2" and job.progress == 1.0

        assert await _visible(db, await ctx_for(db, c.user_id, c.id), [job_id]) == {job_id}
        assert await _visible(db, await ctx_for(db, player.id, c.id), [job_id]) == set()
        assert await _visible(db, await ctx_for(db, other.user_id, other.id), [job_id]) == set()
    finally:
        backfill.BACKFILLS.pop(name, None)
        await db.execute(sa.delete(DataBackfill).where(DataBackfill.name == name))
        await db.commit()


async def test_deferred_rows_stay_with_their_starter(db, world):
    c, other, player = world
    second = await _player(db, c)
    await db.commit()
    gm_job = await _job(db, c, c.user_id, "gm")
    own_job = await _job(db, c, player.id, "player")
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
    await client.set("res:cpu_heavy", "someone-else")
    previous = set_valkey(client)
    try:
        factory = async_sessionmaker(db.bind, expire_on_commit=False)
        assert await run_job(gm_job.id, factory, "w") == JobStatus.QUEUED
        assert await run_job(own_job.id, factory, "w") == JobStatus.QUEUED
    finally:
        set_valkey(previous)
        await client.aclose()
    stages = dict((await db.execute(sa.select(Job.id, Job.stage).where(Job.id.in_([gm_job.id, own_job.id])))).all())
    assert stages == {gm_job.id: WAITING_STAGE, own_job.id: WAITING_STAGE}

    ids = [gm_job.id, own_job.id]
    assert await _visible(db, await ctx_for(db, player.id, c.id), ids) == {own_job.id}
    assert await _visible(db, await ctx_for(db, second.id, c.id), ids) == set()  # another Player's Job
    assert await _visible(db, await ctx_for(db, other.user_id, other.id), ids) == set()
    assert await _visible(db, await ctx_for(db, c.user_id, c.id), ids) == {gm_job.id, own_job.id}
