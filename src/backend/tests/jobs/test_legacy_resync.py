"""E0-WorldCore.6: `backfill.legacy_resync` (app/jobs/legacy_resync.py).

Each test makes its own Campaign with legacy `npcs`/`quests` rows, runs the
F3-world copy's DATA_STEPS (as the boot did), then changes the legacy rows
(as the old pages did after the copy) and/or the World, and runs the job's
cursor steps as the Owner. The legacy rows are only ever read.
"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access import ctx_for, set_visibility
from app.db.models import Campaign, Genre, User
from app.db.models.entity import Entity, EntityChange
from app.db.models.job import DataBackfill
from app.db.models.npc import NpcEntry, NpcRole, NpcStatus
from app.db.models.quest import Quest, QuestStatus
from app.domain import legacy_world as lw
from app.domain.enums import JobStatus
from app.jobs import backfill, legacy_resync
from app.jobs.backfill import run_backfills
from app.schemas.sources import RecordRef
from app.services.world_service import apply_change

BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "f3_world_revision_resync", BACKEND / "migrations" / "versions" / "03c0b504f1d1_f3_world_entities_legacy_copy.py")
f3_world = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f3_world)


# ── Setup ──────────────────────────────────────────────────────────────────

async def _campaign(db):
    owner = User(email=f"resync-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x", display_name="owner",
                 access_granted=True, access_source="promo")
    db.add(owner)
    await db.flush()
    campaign = Campaign(user_id=owner.id, name="Resync", genre=Genre.fantasy)
    db.add(campaign)
    await db.commit()
    return owner, campaign


async def _npc(db, owner, campaign, name="Barnaby", **kw) -> uuid.UUID:
    row = NpcEntry(user_id=owner.id, campaign_id=campaign.id, name=name, role=kw.pop("role", NpcRole.npc),
                   status=kw.pop("status", NpcStatus.alive), description=kw.pop("description", "An innkeeper."),
                   notes=kw.pop("notes", "secretly the lich"))
    db.add(row)
    await db.commit()
    return row.id


async def _quest(db, owner, campaign, title="Find the caravan", **kw) -> uuid.UUID:
    row = Quest(user_id=owner.id, campaign_id=campaign.id, title=title, status=kw.pop("status", QuestStatus.active),
                description=kw.pop("description", "North road."), notes=kw.pop("notes", None))
    db.add(row)
    await db.commit()
    return row.id


async def _copy(db) -> None:
    await db.run_sync(lambda session: f3_world.apply_data_steps(session.connection()))
    await db.commit()


async def _legacy_edit(db, model, row_id, **values) -> None:
    """What an old page did after the copy (tests may write the frozen tables)."""
    await db.execute(sa.update(model).where(model.id == row_id).values(**values))
    await db.commit()


async def _run(db, owner, campaign, job=None):
    """Every cursor step of the Campaign's job, each committed like the worker does."""
    ctx = await ctx_for(db, owner.id, campaign.id)
    job = job or SimpleNamespace(payload={}, campaign_id=campaign.id, progress=None, stage=None, eta_seconds=None)
    for _ in range(200):
        job._continue = False
        try:
            await legacy_resync.handle(job, ctx, db)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        if not job._continue:
            return job
    raise AssertionError("the resync did not finish")


def _entity_id(kind, legacy_id) -> uuid.UUID:
    return lw.legacy_entity_id(kind, legacy_id)


async def _entity(db, entity_id) -> Entity:
    return (await db.execute(sa.select(Entity).where(Entity.id == entity_id)
                             .execution_options(populate_existing=True))).scalar_one()


async def _changes(db, entity_id) -> list[EntityChange]:
    return list((await db.execute(sa.select(EntityChange).where(EntityChange.entity_id == entity_id)
                                  .order_by(EntityChange.created_at, EntityChange.id)
                                  .execution_options(populate_existing=True))).scalars().all())


async def _campaign_changes(db, campaign) -> int:
    return await db.scalar(sa.select(sa.func.count()).select_from(EntityChange)
                           .where(EntityChange.campaign_id == campaign.id))


async def _legacy_values(db, campaign) -> list:
    out = []
    for table in ("npcs", "quests"):
        out += list((await db.execute(sa.text(
            f"SELECT to_jsonb(t) FROM {table} t WHERE campaign_id = :c ORDER BY id"), {"c": campaign.id})).scalars())
    return out


async def _gm(db, owner, campaign):
    return await ctx_for(db, owner.id, campaign.id)


# ── The rule ───────────────────────────────────────────────────────────────

async def test_fresh_upgrade_writes_nothing(db):
    owner, campaign = await _campaign(db)
    await _npc(db, owner, campaign)
    await _npc(db, owner, campaign, "Ashen Hand", role=NpcRole.faction, status=NpcStatus.dead)
    await _quest(db, owner, campaign, status=QuestStatus.completed)
    await _copy(db)
    before = await _campaign_changes(db, campaign)
    await _run(db, owner, campaign)
    assert await _campaign_changes(db, campaign) == before


async def test_a_legacy_only_edit_is_applied_by_the_owner(db):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    await _legacy_edit(db, NpcEntry, npc, name="Barnaby the Bold", status=NpcStatus.dead, role=NpcRole.pc,
                       notes="now a vampire")
    legacy = await _legacy_values(db, campaign)
    await _run(db, owner, campaign)
    entity = await _entity(db, _entity_id("npc", npc))
    assert (entity.name, entity.status, entity.kind, entity.gm_notes) == (
        "Barnaby the Bold", "deceased", "pc", "now a vampire")
    assert entity.visibility == "gm" and entity.field_visibility == {}
    rows = await _changes(db, entity.id)
    assert {(r.op, r.field) for r in rows[1:]} == {("update_field", "name"), ("set_status", "status"),
                                                   ("set_kind", "kind"), ("update_field", "gm_notes")}
    assert all(r.actor_user_id == owner.id for r in rows[1:])
    assert await _legacy_values(db, campaign) == legacy  # legacy rows never modified


async def test_both_sides_changed_keeps_the_world_and_notes_the_legacy_value(db):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    eid = _entity_id("npc", npc)
    await apply_change(db, await _gm(db, owner, campaign), {"op": "update_field", "entity_id": eid,
                                                           "field": "description", "value": "World text"})
    await db.commit()
    await _legacy_edit(db, NpcEntry, npc, description="Old page text")
    await _run(db, owner, campaign)
    entity = await _entity(db, eid)
    assert entity.description == "World text"
    notes = [r for r in await _changes(db, eid) if r.op == "canon_note"]
    assert len(notes) == 1 and notes[0].field is None
    assert notes[0].new_value["note"] == (
        "Old NPC page edit not applied (World version kept): description = 'Old page text'")


async def test_the_world_changed_and_the_old_page_did_not(db):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    eid = _entity_id("npc", npc)
    await apply_change(db, await _gm(db, owner, campaign), {"op": "update_field", "entity_id": eid,
                                                           "field": "name", "value": "Barnaby II"})
    await db.commit()
    before = len(await _changes(db, eid))
    await _run(db, owner, campaign)
    assert (await _entity(db, eid)).name == "Barnaby II"
    assert len(await _changes(db, eid)) == before


async def test_a_published_entity_gets_a_note_not_the_edit(db):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    eid = _entity_id("npc", npc)
    await set_visibility(db, await _gm(db, owner, campaign), RecordRef(kind="entity", id=eid), "party")
    await db.commit()
    await _legacy_edit(db, NpcEntry, npc, description="Leaked?", notes="new gm notes")
    await _run(db, owner, campaign)
    entity = await _entity(db, eid)
    assert entity.description == "An innkeeper." and entity.visibility == "party"
    assert entity.gm_notes == "new gm notes"  # gm_notes is always GM: applied
    notes = [r.new_value["note"] for r in await _changes(db, eid) if r.op == "canon_note"]
    assert notes == ["Old NPC page edit not applied (World version kept): description = 'Leaked?'"]


async def test_a_role_change_between_character_and_faction_is_a_note(db):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    await _legacy_edit(db, NpcEntry, npc, role=NpcRole.faction)
    await _run(db, owner, campaign)
    entity = await _entity(db, _entity_id("npc", npc))
    assert entity.type == "character"
    notes = [r.new_value["note"] for r in await _changes(db, entity.id) if r.op == "canon_note"]
    assert notes == ["Old NPC page edit not applied (World version kept): role = faction"]


async def test_a_quest_completed_on_the_old_page_gets_completed_at(db):
    owner, campaign = await _campaign(db)
    quest = await _quest(db, owner, campaign)
    await _copy(db)
    await _legacy_edit(db, Quest, quest, status=QuestStatus.completed, title="Found the caravan")
    updated_at = await db.scalar(sa.select(Quest.updated_at).where(Quest.id == quest))
    await _run(db, owner, campaign)
    entity = await _entity(db, _entity_id("quest", quest))
    assert (entity.name, entity.status) == ("Found the caravan", "completed")
    assert entity.attributes["completed_at"] == legacy_resync._iso(updated_at)


async def test_a_new_legacy_row_becomes_a_gm_only_entity(db):
    owner, campaign = await _campaign(db)
    await _copy(db)
    npc = await _npc(db, owner, campaign, "Late Arrival", role=NpcRole.faction, status=NpcStatus.alive)
    quest = await _quest(db, owner, campaign, "Late quest", status=QuestStatus.completed, notes="n")
    await _run(db, owner, campaign)
    faction = await _entity(db, _entity_id("npc", npc))
    assert (faction.type, faction.kind, faction.status, faction.legacy_npc_id, faction.visibility,
            faction.gm_notes) == ("faction", None, "active", npc, "gm", "secretly the lich")
    q = await _entity(db, _entity_id("quest", quest))
    assert (q.legacy_quest_id, q.status, q.visibility) == (quest, "completed", "gm")
    assert q.attributes["completed_at"] == legacy_resync._iso(
        await db.scalar(sa.select(Quest.updated_at).where(Quest.id == quest)))
    # Re-applying the F3 copy afterwards inserts nothing (same ids, legacy ids held).
    before = await db.scalar(sa.select(sa.func.count()).select_from(Entity).where(Entity.campaign_id == campaign.id))
    await _copy(db)
    assert await db.scalar(sa.select(sa.func.count()).select_from(Entity)
                           .where(Entity.campaign_id == campaign.id)) == before


async def test_a_deleted_legacy_row(db):
    owner, campaign = await _campaign(db)
    untouched = await _npc(db, owner, campaign, "Untouched")
    touched = await _npc(db, owner, campaign, "Touched")
    await _copy(db)
    await apply_change(db, await _gm(db, owner, campaign), {"op": "update_field", "entity_id": _entity_id(
        "npc", touched), "field": "description", "value": "World text"})
    await db.commit()
    await db.execute(sa.delete(NpcEntry).where(NpcEntry.id.in_([untouched, touched])))
    await db.commit()
    await _run(db, owner, campaign)
    gone = await _entity(db, _entity_id("npc", untouched))
    assert gone.deleted_at is not None and (await _changes(db, gone.id))[-1].op == "delete_entity"
    kept = await _entity(db, _entity_id("npc", touched))
    assert kept.deleted_at is None
    assert [r.new_value["note"] for r in await _changes(db, kept.id) if r.op == "canon_note"] == [
        "Deleted on the old NPC page; kept because it was changed in World"]


# ── Idempotency and resumption ─────────────────────────────────────────────

async def _messy_campaign(db):
    owner, campaign = await _campaign(db)
    a = await _npc(db, owner, campaign, "A")
    b = await _npc(db, owner, campaign, "B")
    q = await _quest(db, owner, campaign)
    await _copy(db)
    await apply_change(db, await _gm(db, owner, campaign), {"op": "update_field", "entity_id": _entity_id("npc", b),
                                                           "field": "description", "value": "World"})
    await db.commit()
    await _legacy_edit(db, NpcEntry, a, name="A2")
    await _legacy_edit(db, NpcEntry, b, description="Legacy")
    await _legacy_edit(db, Quest, q, status=QuestStatus.failed)
    await _npc(db, owner, campaign, "C")
    return owner, campaign


async def _snapshot(db, campaign) -> list:
    rows = (await db.execute(sa.text(
        "SELECT e.id::text, e.name, e.status, e.description, e.deleted_at IS NULL, "
        "(SELECT count(*) FROM entity_changes c WHERE c.entity_id = e.id) "
        "FROM entities e WHERE e.campaign_id = :c ORDER BY e.id"), {"c": campaign.id})).all()
    return [tuple(r) for r in rows]


async def test_a_second_run_writes_nothing(db):
    owner, campaign = await _messy_campaign(db)
    await _run(db, owner, campaign)
    first = await _snapshot(db, campaign)
    changes = await _campaign_changes(db, campaign)
    await _run(db, owner, campaign)
    assert await _snapshot(db, campaign) == first
    assert await _campaign_changes(db, campaign) == changes


async def test_a_crash_mid_campaign_resumes_without_duplicates(db, monkeypatch):
    owner, campaign = await _messy_campaign(db)
    # Plain ids: the rollback after the crash expires the ORM rows (no lazy loads in async).
    owner, campaign = SimpleNamespace(id=owner.id), SimpleNamespace(id=campaign.id)
    real = legacy_resync.apply_change
    calls = {"n": 0}

    async def flaky(db_, ctx, change):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker died")
        return await real(db_, ctx, change)

    monkeypatch.setattr(legacy_resync, "apply_change", flaky)
    job = SimpleNamespace(payload={}, campaign_id=campaign.id, progress=None, stage=None, eta_seconds=None)
    with pytest.raises(RuntimeError):
        await _run(db, owner, campaign, job)
    await _run(db, owner, campaign, job)  # the retry resumes at the failed step
    crashed = await _snapshot(db, campaign)

    # The same data through one clean run gives the same shape.
    monkeypatch.setattr(legacy_resync, "apply_change", real)
    owner2, campaign2 = await _messy_campaign(db)
    await _run(db, owner2, campaign2)
    clean = await _snapshot(db, campaign2)
    assert sorted(r[1:] for r in crashed) == sorted(r[1:] for r in clean)  # ids differ: another Campaign
    notes = (await db.execute(sa.select(sa.func.count()).select_from(EntityChange).where(
        EntityChange.campaign_id == campaign.id, EntityChange.op == "canon_note"))).scalar_one()
    assert notes == 1


# ── The data_backfills runner ──────────────────────────────────────────────

@pytest.fixture
async def resync_row(db, monkeypatch):
    """legacy_resync_v1 queued and untouched, the runner narrowed to `allowed`; restored after."""
    saved = (await db.execute(sa.select(DataBackfill.status, DataBackfill.cursor, DataBackfill.job_id)
                              .where(DataBackfill.name == legacy_resync.BACKFILL_NAME))).one()
    others = list((await db.execute(sa.select(DataBackfill.name).where(
        DataBackfill.name != legacy_resync.BACKFILL_NAME, DataBackfill.status.in_(["queued", "running"])))).scalars())
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name.in_(others)).values(status="done"))
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name == legacy_resync.BACKFILL_NAME)
                     .values(status="queued", cursor=None, job_id=None))
    await db.commit()
    allowed: set[uuid.UUID] = set()
    real = backfill.campaign_owners

    async def narrowed(db_, *, created_before):
        return {c: o for c, o in (await real(db_, created_before=created_before)).items() if c in allowed}

    monkeypatch.setattr(backfill, "campaign_owners", narrowed)
    yield allowed
    await db.rollback()
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name.in_(others)).values(status="queued"))
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name == legacy_resync.BACKFILL_NAME)
                     .values(status=saved.status, cursor=saved.cursor, job_id=saved.job_id))
    await db.commit()


async def test_the_runner_resyncs_each_campaign_and_finishes(db, resync_row):
    owner, campaign = await _campaign(db)
    npc = await _npc(db, owner, campaign)
    await _copy(db)
    await _legacy_edit(db, NpcEntry, npc, name="Renamed on the old page")
    # The row's snapshot covers Campaigns created at or before its updated_at.
    await db.execute(sa.update(DataBackfill).where(DataBackfill.name == legacy_resync.BACKFILL_NAME)
                     .values(updated_at=sa.func.now()))
    await db.commit()
    resync_row.add(campaign.id)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    await run_backfills(factory)  # enqueues (and, eager, runs) the Campaign's Job
    assert (await run_backfills(factory)).get(legacy_resync.BACKFILL_NAME) == JobStatus.DONE
    assert (await _entity(db, _entity_id("npc", npc))).name == "Renamed on the old page"
