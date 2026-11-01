"""F3-world (03c0b504f1d1, E0-WorldCore.2): the legacy copy on hostile data.

The module fixture builds a database at F2-jobs-files (cf62d979bc8a), widens
the legacy PG enums with values the copy cannot map (as a fork or a later
release might have), inserts an adversarial dataset with raw SQL, and runs
`alembic upgrade head` on it, collecting the revision's log lines. Then:

  * every legacy role x status maps as tests/domain/test_entity_types.py
    pins it; duplicates stay two Entities; unicode, empty notes and NULL
    descriptions are copied byte-exact; a Campaign with no NPCs still gets
    its relationship types;
  * an unmappable value takes the type's default, is logged with its ids,
    and never fails the upgrade;
  * re-applying the data steps changes nothing;
  * composite FKs refuse a link across Campaigns;
  * deleting an Entity nulls only the link column (SET NULL (col)), and
    deleting a Campaign cascades through the world while a chat keeps its
    row.

Teardown rebuilds the clean session schema (tests/conftest.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import logging
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.conftest import TEST_DB_URL, _guard_test_database, _reset_public_schema, alembic_config, build_test_schema
from tests.domain.test_entity_types import LEGACY_ROLE, LEGACY_STATUS

BACKEND_DIR = Path(__file__).resolve().parents[2]
F2_JOBS_FILES = "cf62d979bc8a"
TS = "2026-02-01 09:30:00+00"
COMPLETED_TS = "2026-03-04 05:06:07.123456+00"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


f3_world = _load("f3_world_revision_adv",
                 BACKEND_DIR / "migrations" / "versions" / "03c0b504f1d1_f3_world_entities_legacy_copy.py")


def f3_id(kind: str, key: str) -> str:
    return str(uuid.UUID(hashlib.md5(f"f3-world:{kind}:{key}".encode()).hexdigest()))


def _uid() -> str:
    return str(uuid.uuid4())


OWNER, OTHER = _uid(), _uid()
WORLD, EMPTY = _uid(), _uid()  # the dataset Campaign, a Campaign with no NPCs or Quests
UNICODE_NAME = "Ælfrīð 竜 \U0001F409 'quoted'"

# Every legacy role x status (the pinned map), keyed by its npc id.
COMBOS: dict[str, tuple[str, str]] = {
    _uid(): (role, status) for role in LEGACY_ROLE for status in LEGACY_STATUS["character"]}
BOB_1, BOB_2 = _uid(), _uid()
UNICODE_NPC = _uid()
ZOMBIE_NPC, LICH_NPC, ZOMBIE_FACTION = _uid(), _uid(), _uid()
QUESTS = {_uid(): s for s in ("active", "completed", "failed", "abandoned")}
ZOMBIE_QUEST = _uid()
UNMAPPED = {ZOMBIE_NPC, LICH_NPC, ZOMBIE_FACTION, ZOMBIE_QUEST}
TEMPLATE, SHEET, CHAT = _uid(), _uid(), _uid()


def _q(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def _npc(npc_id: str, name: str, role: str, status: str, description: str | None = None,
         notes: str | None = None, campaign: str = WORLD) -> str:
    return ("INSERT INTO npcs (id, user_id, campaign_id, name, role, status, description, notes, created_at, "
            f"updated_at) VALUES ('{npc_id}', '{OWNER}', '{campaign}', {_q(name)}, '{role}', '{status}', "
            f"{_q(description)}, {_q(notes)}, '{TS}', '{TS}')")


def _quest(quest_id: str, title: str, status: str, updated_at: str = TS) -> str:
    return ("INSERT INTO quests (id, user_id, campaign_id, title, description, status, notes, created_at, "
            f"updated_at) VALUES ('{quest_id}', '{OWNER}', '{WORLD}', {_q(title)}, NULL, '{status}', "
            f"'quest notes', '{TS}', '{updated_at}')")


def dataset() -> list[str]:
    stmts = []
    for uid, label in ((OWNER, "owner"), (OTHER, "other")):
        stmts.append("INSERT INTO users (id, email, hashed_password, display_name, access_granted, created_at, "
                     f"updated_at) VALUES ('{uid}', '{label}-{uid[:8]}@example.test', 'x', {_q(label)}, true, "
                     f"'{TS}', '{TS}')")
    for cid, name in ((WORLD, "World"), (EMPTY, "Empty")):
        stmts.append("INSERT INTO campaigns (id, user_id, name, genre, description, created_at, updated_at) "
                     f"VALUES ('{cid}', '{OWNER}', {_q(name)}, 'fantasy', NULL, '{TS}', '{TS}')")
    for npc_id, (role, status) in COMBOS.items():
        stmts.append(_npc(npc_id, f"{role}-{status}", role, status, f"desc {role}", f"notes {status}"))
    stmts += [
        _npc(BOB_1, "Bob", "npc", "alive"),
        _npc(BOB_2, "Bob", "npc", "alive"),
        _npc(UNICODE_NPC, UNICODE_NAME, "npc", "alive", description=None, notes=""),
        _npc(ZOMBIE_NPC, "Shambler", "npc", "zombie"),
        _npc(LICH_NPC, "Lich King", "lich", "alive"),
        _npc(ZOMBIE_FACTION, "Grave Guild", "faction", "zombie"),
    ]
    for quest_id, status in QUESTS.items():
        stmts.append(_quest(quest_id, f"quest {status}", status,
                            COMPLETED_TS if status == "completed" else TS))
    stmts.append(_quest(ZOMBIE_QUEST, "Undead quest", "zombie"))
    # F1-core left these unconstrained: ids that name nothing must not block the FKs.
    stmts += [
        "INSERT INTO character_sheet_templates (id, campaign_id, created_by_user_id, name, fields, created_at, "
        f"updated_at) VALUES ('{TEMPLATE}', '{WORLD}', '{OWNER}', 'T', '[]'::jsonb, '{TS}', '{TS}')",
        "INSERT INTO character_sheets (id, campaign_id, template_id, created_by_user_id, name, data, pc_entity_id, "
        f"created_at, updated_at) VALUES ('{SHEET}', '{WORLD}', '{TEMPLATE}', '{OWNER}', 'S', '{{}}'::jsonb, "
        f"'{_uid()}', '{TS}', '{TS}')",
        "INSERT INTO chat_sessions (id, user_id, campaign_id, title, messages, message_count, npc_entity_id, "
        f"created_at, updated_at) VALUES ('{CHAT}', '{OWNER}', '{WORLD}', 't', '[]'::jsonb, 0, '{_uid()}', "
        f"'{TS}', '{TS}')",
    ]
    return stmts


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


async def _exec(url: str, statements: list[str], *, each_in_own_transaction: bool = False) -> None:
    engine = create_async_engine(url)
    try:
        if each_in_own_transaction:
            for stmt in statements:
                async with engine.begin() as conn:
                    await conn.execute(sa.text(stmt))
        else:
            async with engine.begin() as conn:
                for stmt in statements:
                    await conn.execute(sa.text(stmt))
    finally:
        await engine.dispose()


async def _with_conn(url: str, fn):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await fn(conn)
    finally:
        await engine.dispose()


def run(fn):
    return asyncio.run(_with_conn(TEST_DB_URL, fn))


@pytest.fixture(scope="module")
def migrated():
    _guard_test_database(TEST_DB_URL)
    handler = _Collect()
    logger = logging.getLogger(f3_world.logger.name)
    logger.addHandler(handler)
    try:
        asyncio.run(_reset_public_schema(TEST_DB_URL, with_vector=True))
        cfg = alembic_config(TEST_DB_URL)
        command.upgrade(cfg, F2_JOBS_FILES)
        # Values the copy cannot map; ADD VALUE must commit before rows use it.
        asyncio.run(_exec(TEST_DB_URL, [
            "ALTER TYPE npcstatus ADD VALUE 'zombie'",
            "ALTER TYPE npcrole ADD VALUE 'lich'",
            "ALTER TYPE queststatus ADD VALUE 'zombie'",
        ], each_in_own_transaction=True))
        asyncio.run(_exec(TEST_DB_URL, dataset()))
        legacy_before = run(_legacy)
        command.upgrade(cfg, "head")
        yield {"log": list(handler.messages), "legacy_before": legacy_before}
    finally:
        logger.removeHandler(handler)
        build_test_schema(TEST_DB_URL)


async def _legacy(conn: AsyncConnection) -> dict[str, list]:
    return {t: list((await conn.execute(sa.text(f"SELECT to_jsonb(x) FROM {t} x ORDER BY id"))).scalars())
            for t in ("npcs", "quests")}


async def _entities(conn: AsyncConnection) -> dict[str, dict]:
    rows = (await conn.execute(sa.text(
        "SELECT coalesce(legacy_npc_id, legacy_quest_id)::text AS legacy, to_jsonb(e) AS row FROM entities e"
    ))).all()
    return {r.legacy: r.row for r in rows}


async def _world(conn: AsyncConnection) -> dict[str, list]:
    out = {}
    for table in f3_world.TABLES:
        out[table] = list((await conn.execute(sa.text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))).scalars())
    out["data_backfills"] = [tuple(r) for r in (await conn.execute(sa.text(
        "SELECT name, status FROM data_backfills ORDER BY name"))).all()]
    return out


# ---- the copy --------------------------------------------------------------

def test_every_legacy_role_and_status_maps_as_pinned(migrated):
    entities = run(_entities)
    for npc_id, (role, status) in COMBOS.items():
        e = entities[npc_id]
        type_, kind = LEGACY_ROLE[role]
        assert (e["type"], e["kind"], e["status"]) == (type_, kind, LEGACY_STATUS[type_][status]), (role, status)
        assert e["id"] == f3_id("npc", npc_id)
        assert (e["name"], e["description"], e["gm_notes"]) == (f"{role}-{status}", f"desc {role}", f"notes {status}")
        assert (e["visibility"], e["field_visibility"], e["attributes"]) == ("gm", {}, {})
        assert e["created_by_user_id"] == OWNER and e["campaign_id"] == WORLD
    for quest_id, status in QUESTS.items():
        e = entities[quest_id]
        assert (e["type"], e["kind"], e["status"], e["name"], e["gm_notes"]) == (
            "quest", None, status, f"quest {status}", "quest notes")
        expected_attrs = {"completed_at": "2026-03-04T05:06:07.123456Z"} if status == "completed" else {}
        assert e["attributes"] == expected_attrs


def test_duplicate_names_stay_two_entities(migrated):
    entities = run(_entities)
    bobs = [entities[BOB_1], entities[BOB_2]]
    assert [b["name"] for b in bobs] == ["Bob", "Bob"]
    assert bobs[0]["id"] != bobs[1]["id"]


def test_unicode_empty_notes_and_null_description_are_byte_exact(migrated):
    e = run(_entities)[UNICODE_NPC]
    assert e["name"] == UNICODE_NAME
    assert e["gm_notes"] == ""
    assert e["description"] is None
    exact = run(lambda c: c.scalar(sa.text(
        "SELECT e.name = n.name AND e.gm_notes = n.notes AND e.description IS NULL "
        "FROM entities e JOIN npcs n ON n.id = e.legacy_npc_id WHERE n.id = :id"), {"id": UNICODE_NPC}))
    assert exact is True


def test_campaign_without_npcs_gets_relationship_types_only(migrated):
    async def counts(conn):
        return (await conn.scalar(sa.text("SELECT count(*) FROM entities WHERE campaign_id = :c"), {"c": EMPTY}),
                (await conn.execute(sa.text(
                    "SELECT key, hostile FROM relationship_types WHERE campaign_id = :c ORDER BY key"),
                    {"c": EMPTY})).all())
    n, types = run(counts)
    assert n == 0
    assert [tuple(t) for t in types] == sorted(
        (key, hostile) for key, _, _, hostile in f3_world.DEFAULT_RELATIONSHIP_TYPES)


def test_unmappable_values_take_the_default_and_are_logged(migrated):
    entities = run(_entities)
    assert (entities[ZOMBIE_NPC]["type"], entities[ZOMBIE_NPC]["kind"], entities[ZOMBIE_NPC]["status"]) == (
        "character", "npc", "unknown")
    assert (entities[LICH_NPC]["type"], entities[LICH_NPC]["kind"], entities[LICH_NPC]["status"]) == (
        "character", "npc", "alive")
    assert (entities[ZOMBIE_FACTION]["type"], entities[ZOMBIE_FACTION]["kind"],
            entities[ZOMBIE_FACTION]["status"]) == ("faction", None, "unknown")
    assert (entities[ZOMBIE_QUEST]["type"], entities[ZOMBIE_QUEST]["status"]) == ("quest", "active")
    log = migrated["log"]
    for legacy_id in UNMAPPED:
        assert any(legacy_id in line and WORLD in line for line in log), (legacy_id, log)
    assert len(log) == len(UNMAPPED)  # mapped rows are not logged


def test_every_copy_is_gm_only_with_history_and_legacy_rows_untouched(migrated):
    async def check(conn):
        n_npcs = await conn.scalar(sa.text("SELECT count(*) FROM npcs"))
        n_quests = await conn.scalar(sa.text("SELECT count(*) FROM quests"))
        n_entities = await conn.scalar(sa.text("SELECT count(*) FROM entities"))
        not_gm = await conn.scalar(sa.text(
            "SELECT count(*) FROM entities WHERE visibility <> 'gm' OR field_visibility <> '{}'::jsonb"))
        history = await conn.scalar(sa.text(
            "SELECT count(*) FROM entity_changes ch JOIN entities e ON e.id = ch.entity_id "
            "WHERE ch.op = 'migrated' AND ch.actor_user_id = :o AND ch.field IS NULL AND ch.old_value IS NULL "
            "AND ch.new_value = jsonb_build_object('from', CASE WHEN e.legacy_npc_id IS NOT NULL "
            "                                                 THEN 'npcs' ELSE 'quests' END)"), {"o": OWNER})
        return n_npcs, n_quests, n_entities, not_gm, history
    n_npcs, n_quests, n_entities, not_gm, history = run(check)
    assert n_entities == n_npcs + n_quests == history
    assert not_gm == 0
    assert run(_legacy) == migrated["legacy_before"]


def test_reapplying_the_data_steps_changes_nothing(migrated):
    before = run(_world)

    async def reapply(conn):
        await conn.run_sync(f3_world.apply_data_steps)
        await conn.commit()
    run(reapply)
    assert run(_world) == before


def test_dangling_f1_core_links_are_cleared_before_the_fks(migrated):
    async def links(conn):
        return (await conn.scalar(sa.text("SELECT pc_entity_id FROM character_sheets WHERE id = :id"), {"id": SHEET}),
                await conn.scalar(sa.text("SELECT npc_entity_id FROM chat_sessions WHERE id = :id"), {"id": CHAT}))
    assert run(links) == (None, None)


def test_campaign_less_chat_cannot_take_an_npc(migrated):
    async def scenario(conn):
        npc = await _entity_id(conn, BOB_1)
        chat = _uid()
        await conn.execute(sa.text(
            "INSERT INTO chat_sessions (id, user_id, campaign_id, title, messages, message_count, created_at, "
            "updated_at) VALUES (:id, :o, NULL, 't', '[]'::jsonb, 0, now(), now())"), {"id": chat, "o": OWNER})
        await conn.execute(sa.text("UPDATE chat_sessions SET npc_entity_id = :n WHERE id = :id"),
                           {"n": npc, "id": chat})
        value = await conn.scalar(sa.text("SELECT npc_entity_id FROM chat_sessions WHERE id = :id"), {"id": chat})
        await conn.rollback()
        return value
    assert run(scenario) is None


# ---- referential rules -----------------------------------------------------

async def _entity_id(conn: AsyncConnection, legacy: str) -> str:
    return str(await conn.scalar(sa.text(
        "SELECT id FROM entities WHERE legacy_npc_id = :l OR legacy_quest_id = :l"), {"l": legacy}))


@pytest.mark.parametrize("sql", [
    "INSERT INTO entity_aliases (id, campaign_id, entity_id, alias, normalized_alias) "
    "VALUES (gen_random_uuid(), :other, :entity, 'x', 'x')",
    "INSERT INTO entity_mentions (id, campaign_id, entity_id, source_field, origin) "
    "VALUES (gen_random_uuid(), :other, :entity, 'narrative', 'manual')",
    "INSERT INTO quest_steps (id, campaign_id, quest_entity_id, position, text) "
    "VALUES (gen_random_uuid(), :other, :entity, 0, 'x')",
    "INSERT INTO entity_changes (id, campaign_id, entity_id, op) VALUES (gen_random_uuid(), :other, :entity, 'merge')",
    "INSERT INTO entity_relationships (id, campaign_id, source_entity_id, target_entity_id, relationship_type_id) "
    "SELECT gen_random_uuid(), :other, :entity, :entity, rt.id FROM relationship_types rt "
    "WHERE rt.campaign_id = :other LIMIT 1",
    "UPDATE entities SET merged_into_id = :entity WHERE campaign_id = :other",
], ids=["alias", "mention", "quest_step", "change", "relationship", "merged_into"])
def test_cross_campaign_links_fail_at_insert(migrated, sql):
    async def attempt(conn):
        entity = await _entity_id(conn, BOB_1)  # an Entity of WORLD
        if sql.startswith("UPDATE"):
            # Give EMPTY one Entity to point across from.
            await conn.execute(sa.text(
                "INSERT INTO entities (id, campaign_id, type, name, status) "
                "VALUES (gen_random_uuid(), :c, 'item', 'Key', 'active')"), {"c": EMPTY})
        try:
            with pytest.raises(IntegrityError, match="foreign key"):
                await conn.execute(sa.text(sql), {"other": EMPTY, "entity": entity})
        finally:
            await conn.rollback()
    run(attempt)


def test_relationship_type_of_another_campaign_is_refused(migrated):
    async def attempt(conn):
        a, b = await _entity_id(conn, BOB_1), await _entity_id(conn, BOB_2)
        try:
            with pytest.raises(IntegrityError, match="foreign key"):
                await conn.execute(sa.text(
                    "INSERT INTO entity_relationships (id, campaign_id, source_entity_id, target_entity_id, "
                    "relationship_type_id) SELECT gen_random_uuid(), :c, :a, :b, rt.id FROM relationship_types rt "
                    "WHERE rt.campaign_id = :other LIMIT 1"), {"c": WORLD, "a": a, "b": b, "other": EMPTY})
        finally:
            await conn.rollback()
    run(attempt)


def test_deleting_an_entity_nulls_only_the_link(migrated):
    async def scenario(conn):
        cid = _uid()
        await conn.execute(sa.text(
            "INSERT INTO campaigns (id, user_id, name, genre, created_at, updated_at) "
            "VALUES (:c, :o, 'Links', 'fantasy', now(), now())"),
            {"c": cid, "o": OWNER})
        survivor, merged, npc = _uid(), _uid(), _uid()
        for eid, name in ((survivor, "Survivor"), (merged, "Merged"), (npc, "Talker")):
            await conn.execute(sa.text(
                "INSERT INTO entities (id, campaign_id, type, kind, name, status) "
                "VALUES (:id, :c, 'character', 'npc', :n, 'alive')"), {"id": eid, "c": cid, "n": name})
        await conn.execute(sa.text("UPDATE entities SET merged_into_id = :s WHERE id = :m"),
                           {"s": survivor, "m": merged})
        chat = _uid()
        await conn.execute(sa.text(
            "INSERT INTO chat_sessions (id, user_id, campaign_id, title, messages, message_count, npc_entity_id, "
            "created_at, updated_at) VALUES (:id, :o, :c, 't', '[]'::jsonb, 0, :n, now(), now())"), {"id": chat, "o": OWNER, "c": cid, "n": npc})
        await conn.execute(sa.text("DELETE FROM entities WHERE id IN (:s, :n)"), {"s": survivor, "n": npc})
        merged_row = (await conn.execute(sa.text(
            "SELECT campaign_id::text, merged_into_id FROM entities WHERE id = :m"), {"m": merged})).one()
        chat_row = (await conn.execute(sa.text(
            "SELECT campaign_id::text, npc_entity_id FROM chat_sessions WHERE id = :id"), {"id": chat})).one()
        await conn.rollback()
        return cid, tuple(merged_row), tuple(chat_row)
    cid, merged_row, chat_row = run(scenario)
    assert merged_row == (cid, None)
    assert chat_row == (cid, None)


def test_deleting_a_campaign_cascades_through_the_world(migrated):
    async def scenario(conn):
        cid = _uid()
        p = {"c": cid, "o": OWNER}
        await conn.execute(sa.text(
            "INSERT INTO campaigns (id, user_id, name, genre, created_at, updated_at) "
            "VALUES (:c, :o, 'Doomed', 'fantasy', now(), now())"), p)
        pc, npc, quest, entry, tpl, rt = (_uid() for _ in range(6))
        for eid, type_, kind, status in ((pc, "character", "pc", "alive"), (npc, "character", "npc", "alive"),
                                         (quest, "quest", None, "active")):
            await conn.execute(sa.text(
                "INSERT INTO entities (id, campaign_id, type, kind, name, status) "
                "VALUES (:id, :c, :t, :k, 'n', :s)"), {**p, "id": eid, "t": type_, "k": kind, "s": status})
        await conn.execute(sa.text(
            "INSERT INTO journal_entries (id, user_id, campaign_id, shorthand, narrative, entry_hash, created_at, "
            "updated_at) VALUES (:id, :o, :c, 's', 'n', :h, now(), now())"), {**p, "id": entry, "h": _uid()})
        await conn.execute(sa.text(
            "INSERT INTO relationship_types (id, campaign_id, key, label, inverse_label) "
            "VALUES (:id, :c, 'k', 'l', 'i')"), {**p, "id": rt})
        stmts = [
            "INSERT INTO entity_aliases (id, campaign_id, entity_id, alias, normalized_alias) "
            "VALUES (gen_random_uuid(), :c, :pc, 'A', 'a')",
            "INSERT INTO entity_mentions (id, campaign_id, journal_id, entity_id, source_field, origin) "
            "VALUES (gen_random_uuid(), :c, :entry, :pc, 'narrative', 'manual')",
            "INSERT INTO entity_relationships (id, campaign_id, source_entity_id, target_entity_id, "
            "relationship_type_id, source_journal_id) VALUES (gen_random_uuid(), :c, :pc, :npc, :rt, :entry)",
            "INSERT INTO quest_steps (id, campaign_id, quest_entity_id, position, text) "
            "VALUES (gen_random_uuid(), :c, :quest, 0, 'go')",
            "INSERT INTO entity_changes (id, campaign_id, entity_id, op, actor_user_id) "
            "VALUES (gen_random_uuid(), :c, :pc, 'create_entity', :o)",
            "INSERT INTO character_sheet_templates (id, campaign_id, created_by_user_id, name, fields, created_at, "
            "updated_at) VALUES (:tpl, :c, :o, 'T', '[]'::jsonb, now(), now())",
            "INSERT INTO character_sheets (id, campaign_id, template_id, created_by_user_id, name, data, "
            "pc_entity_id, created_at, updated_at) VALUES (gen_random_uuid(), :c, :tpl, :o, 'S', '{}'::jsonb, :pc, "
            "now(), now())",
        ]
        args = {**p, "pc": pc, "npc": npc, "quest": quest, "entry": entry, "tpl": tpl, "rt": rt}
        for stmt in stmts:
            await conn.execute(sa.text(stmt), args)
        chat = _uid()
        await conn.execute(sa.text(
            "INSERT INTO chat_sessions (id, user_id, campaign_id, title, messages, message_count, npc_entity_id, "
            "created_at, updated_at) VALUES (:id, :o, :c, 't', '[]'::jsonb, 0, :npc, now(), now())"), {**args, "id": chat})
        # A journal delete keeps the edge (SET NULL), before the Campaign goes.
        await conn.execute(sa.text("DELETE FROM journal_entries WHERE id = :entry"), args)
        kept = (await conn.execute(sa.text(
            "SELECT (SELECT count(*) FROM entity_relationships WHERE campaign_id = :c AND source_journal_id IS NULL), "
            "       (SELECT count(*) FROM entity_mentions WHERE campaign_id = :c AND journal_id IS NULL)"), p)).one()
        await conn.execute(sa.text("DELETE FROM campaigns WHERE id = :c"), p)
        left = {}
        for table in (*f3_world.TABLES, "character_sheets", "character_sheet_templates"):
            left[table] = await conn.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE campaign_id = :c"), p)
        chat_row = (await conn.execute(sa.text(
            "SELECT campaign_id, npc_entity_id FROM chat_sessions WHERE id = :id"), {"id": chat})).one()
        await conn.rollback()
        return tuple(kept), left, tuple(chat_row)
    kept, left, chat_row = run(scenario)
    assert kept == (1, 1)
    assert left == {t: 0 for t in left}
    assert chat_row == (None, None)
