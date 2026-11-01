"""Migration-chain gates: one head, a brownfield upgrade, stated FK actions.

conftest's setup_test_db proves `alembic upgrade head` works on an empty DB.
Every self-hoster's boot runs it on a DB that already holds data, so this
module restores a seeded dump taken at SNAPSHOT_REVISION
(tests/fixtures/snapshot_a3e7c1f9d258.sql, made by scripts/make_snapshot.py),
upgrades it to head, and checks that no rows were lost and that each
revision's data changes landed (POST_UPGRADE_CHECKS).

F1-core (c95acb56c595) is the first revision after SNAPSHOT_REVISION: its
checks below cover the members -> Player migration, the chat archive, the
collaborate-token Role, party_tsv and the entry_hash uniqueness swap, and
test_c95acb56c595_data_steps_are_idempotent re-applies its data steps. The
a3e7c1f9d258 round trip downgrades through F2-jobs-files and F1-core and
upgrades again.

F2-jobs-files (cf62d979bc8a, E0-Jobs.1) only creates four empty tables; its
check below pins their indexes, and test_cf62d979bc8a_downgrade_drops_its_tables
proves its downgrade removes exactly those tables.

F3-world (03c0b504f1d1, E0-WorldCore.2) creates the seven World Model
tables and copies every seeded NPC and Quest into `entities`. Its checks
below compare every copied field with the seed, prove every copy is GM-only
and the faction NPC became a Faction, and pin the history rows, the default
relationship types, the backfill row and the `SET NULL (col)` FKs.
test_03c0b504f1d1_data_steps_are_idempotent re-applies its data steps and
re-runs it through a downgrade; test_03c0b504f1d1_downgrade_drops_its_tables
proves the downgrade removes exactly its tables and FKs.

pytest collects tests/migrations/ before tests/test_*.py, so the module
fixture rebuilds the clean session schema in teardown.
"""
import asyncio
import hashlib
import importlib.util
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.conftest import (
    TEST_DB_URL,
    _guard_test_database,
    _reset_public_schema,
    alembic_config,
    build_test_schema,
)

SNAPSHOT_REVISION = "a3e7c1f9d258"
SNAPSHOT_SQL = Path(__file__).resolve().parents[1] / "fixtures" / f"snapshot_{SNAPSHOT_REVISION}.sql"
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The seed (ids, narratives) and the F1-core revision's DATA_STEPS.
make_snapshot = _load("make_snapshot", BACKEND_DIR / "scripts" / "make_snapshot.py")
F1_CORE = "c95acb56c595"
F2_JOBS_FILES = "cf62d979bc8a"
F2_TABLES = ("data_backfills", "derived_sources", "jobs", "stored_files")
f1_core = _load(
    "f1_core_revision",
    BACKEND_DIR / "migrations" / "versions" / "c95acb56c595_f1_core_roles_visibility_party_search.py",
)
F3_WORLD = "03c0b504f1d1"
F3_TABLES = ("entities", "entity_aliases", "entity_mentions", "relationship_types", "entity_relationships",
             "quest_steps", "entity_changes")
f3_world = _load(
    "f3_world_revision",
    BACKEND_DIR / "migrations" / "versions" / "03c0b504f1d1_f3_world_entities_legacy_copy.py",
)

# Seed ids from scripts/make_snapshot.py.
SEED_ID = "00000000-0000-4000-8000-000000000{}".format

# What scripts/make_snapshot.py seeds; every other table is empty. Checked on
# the restore so the row-count comparison after the upgrade is not vacuous.
SEEDED_COUNTS = {
    "users": 3,  # 1 Owner + 2 Members
    "campaigns": 1,
    "campaign_members": 2,
    "campaign_share_tokens": 2,  # read_only + collaborate
    "journal_entries": 3,
    "shorthand_terms": 1,
    "tags": 1,
    "journal_tags": 1,
    "npcs": 3,  # a pc, an npc and a faction
    "quests": 2,
    "chat_sessions": 3,  # one per user
    "app_config": 1,  # seeded by 4b8f2d9e71c3
}

# The ON DELETE rule of every foreign key at head, as "table.column": rule,
# or "table.(a, b)" for a composite FK. A revision that adds or changes an FK
# must update this table, so the deletion behaviour is a decision, not an
# accident.
EXPECTED_FK_ON_DELETE = {
    "admin_messages.user_id": "CASCADE",
    "campaign_members.campaign_id": "CASCADE",
    "campaign_members.user_id": "CASCADE",
    "campaign_share_tokens.campaign_id": "CASCADE",
    "campaign_share_tokens.created_by_user_id": "CASCADE",
    "campaigns.user_id": "CASCADE",
    "character_sheet_templates.campaign_id": "CASCADE",
    "character_sheet_templates.created_by_user_id": "CASCADE",
    "character_sheets.campaign_id": "CASCADE",
    "character_sheets.created_by_user_id": "CASCADE",
    "character_sheets.template_id": "CASCADE",
    "chat_sessions.campaign_id": "SET NULL",
    "chat_sessions.user_id": "CASCADE",
    "data_backfills.job_id": "SET NULL",
    "feedback.campaign_id": "SET NULL",
    "feedback.user_id": "CASCADE",
    "jobs.campaign_id": "CASCADE",
    "jobs.created_by": "SET NULL",
    "jobs.ctx_user_id": "SET NULL",
    "jobs.depends_on_job_id": "SET NULL",
    "journal_entries.campaign_id": "CASCADE",
    "journal_entries.user_id": "CASCADE",
    "journal_tags.journal_id": "CASCADE",
    "journal_tags.tag_id": "CASCADE",
    "model_evaluations.user_id": "CASCADE",
    "npcs.campaign_id": "CASCADE",
    "npcs.user_id": "CASCADE",
    "password_reset_tokens.user_id": "CASCADE",
    "promo_code_redemptions.promo_code_id": "CASCADE",
    "promo_code_redemptions.user_id": "CASCADE",
    "quests.campaign_id": "CASCADE",
    "quests.user_id": "CASCADE",
    "session_plans.campaign_id": "CASCADE",
    "session_plans.user_id": "CASCADE",
    "shorthand_terms.campaign_id": "CASCADE",
    "shorthand_terms.user_id": "CASCADE",
    "source_chunks.campaign_id": "CASCADE",
    "source_chunks.source_document_id": "CASCADE",
    "source_chunks.user_id": "CASCADE",
    "source_documents.campaign_id": "CASCADE",
    "source_documents.user_id": "CASCADE",
    # SET NULL here would widen the file's Audience (Owner(u) -> unnarrowed).
    "stored_files.audience_owner_id": "CASCADE",
    "stored_files.campaign_id": "CASCADE",
    "stored_files.created_by": "SET NULL",
    "subscriptions.user_id": "CASCADE",
    "tag_categories.campaign_id": "CASCADE",
    "tag_categories.created_by_user_id": "CASCADE",
    "tags.custom_category_id": "CASCADE",
    "user_settings.user_id": "CASCADE",
    # F3-world (E0-WorldCore.2): every Entity reference is the composite
    # (campaign_id, x) -> entities(campaign_id, id). The nullable links are
    # SET NULL (x), so campaign_id is never nulled (f3_set_null_links_keep_campaign_id).
    "character_sheets.(campaign_id, pc_entity_id)": "SET NULL",
    "chat_sessions.(campaign_id, npc_entity_id)": "SET NULL",
    "entities.campaign_id": "CASCADE",
    "entities.created_by_user_id": "SET NULL",
    "entities.linked_user_id": "SET NULL",
    "entities.(campaign_id, merged_into_id)": "SET NULL",
    "entity_aliases.campaign_id": "CASCADE",
    "entity_aliases.(campaign_id, entity_id)": "CASCADE",
    "entity_changes.actor_user_id": "SET NULL",
    "entity_changes.campaign_id": "CASCADE",
    "entity_changes.(campaign_id, entity_id)": "CASCADE",
    "entity_changes.reverted_change_id": "SET NULL",
    "entity_changes.source_journal_id": "SET NULL",
    "entity_mentions.campaign_id": "CASCADE",
    "entity_mentions.(campaign_id, entity_id)": "CASCADE",
    "entity_mentions.journal_id": "SET NULL",
    "entity_relationships.campaign_id": "CASCADE",
    # A relationship type in use cannot be deleted (E3.1 decides what happens to its edges).
    "entity_relationships.(campaign_id, relationship_type_id)": "NO ACTION",
    "entity_relationships.(campaign_id, source_entity_id)": "CASCADE",
    "entity_relationships.(campaign_id, target_entity_id)": "CASCADE",
    "entity_relationships.source_journal_id": "SET NULL",
    "quest_steps.campaign_id": "CASCADE",
    "quest_steps.(campaign_id, quest_entity_id)": "CASCADE",
    "quest_steps.source_journal_id": "SET NULL",
    "relationship_types.campaign_id": "CASCADE",
}

# ---------------------------------------------------------------------------
# Post-upgrade checks, keyed by the revision whose data change they verify.
# Each runs on the snapshot after `upgrade head`. A revision that rewrites
# existing rows registers one here with @post_upgrade_check("<revision>").

Check = Callable[[AsyncConnection], Awaitable[None]]
POST_UPGRADE_CHECKS: dict[str, list[Check]] = {}


def post_upgrade_check(revision: str) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        POST_UPGRADE_CHECKS.setdefault(revision, []).append(fn)
        return fn
    return register


async def _shorthand_word_matches(conn: AsyncConnection) -> int:
    return await conn.scalar(sa.text(
        "SELECT count(*) FROM journal_entries "
        "WHERE narrative_tsv @@ plainto_tsquery('english', 'brackenford')"
    ))


# a3e7c1f9d258 put shorthand into narrative_tsv. This keeps later revisions
# (e.g. F1-core's party_tsv work) from silently dropping it again. The
# migration's own backfill is tested by test_a3e7c1f9d258_backfills_shorthand.
@post_upgrade_check("a3e7c1f9d258")
async def shorthand_only_word_matches_narrative_tsv(conn: AsyncConnection) -> None:
    # "brackenford" is in entry 1's shorthand, not its narrative.
    narrative_has_it = await conn.scalar(sa.text(
        "SELECT count(*) FROM journal_entries WHERE narrative ILIKE '%brackenford%'"
    ))
    assert narrative_has_it == 0, "seed changed: the probe word must be shorthand-only"
    matches = await _shorthand_word_matches(conn)
    assert matches == 1, f"a3e7c1f9d258: shorthand-only word matched {matches} entries, expected 1"


# F1-core (E0-Access.1): Roles, Visibility, Party-only search.

@post_upgrade_check(F1_CORE)
async def members_become_players(conn: AsyncConnection) -> None:
    rows = (await conn.execute(sa.text(
        "SELECT id::text, role::text, access_epoch FROM campaign_members ORDER BY id"
    ))).all()
    assert [tuple(r) for r in rows] == [(SEED_ID("301"), "player", 0), (SEED_ID("302"), "player", 0)]
    owner_rows = await conn.scalar(sa.text(
        "SELECT count(*) FROM campaign_members m JOIN campaigns c ON c.id = m.campaign_id "
        "WHERE m.user_id = c.user_id"
    ))
    assert owner_rows == 0, "the Owner must never have a campaign_members row"


@post_upgrade_check(F1_CORE)
async def member_chats_in_their_campaign_are_archived(conn: AsyncConnection) -> None:
    archived = dict((await conn.execute(sa.text(
        "SELECT id::text, archived_at IS NOT NULL FROM chat_sessions"
    ))).all())
    assert archived == {
        SEED_ID("901"): False,  # Owner's chat in the Campaign
        SEED_ID("902"): True,   # Member A's chat in the Campaign
        SEED_ID("903"): False,  # Member B's chat with no Campaign
    }
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM chat_sessions WHERE npc_entity_id IS NOT NULL")) == 0


@post_upgrade_check(F1_CORE)
async def collaborate_token_grants_player(conn: AsyncConnection) -> None:
    rows = dict((await conn.execute(sa.text(
        "SELECT id::text, role::text FROM campaign_share_tokens"
    ))).all())
    assert rows == {SEED_ID("401"): None, SEED_ID("402"): "player"}
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM campaign_share_tokens WHERE expires_at IS NOT NULL OR access_epoch <> 0"
    )) == 0


@post_upgrade_check(F1_CORE)
async def entries_are_gm_written_party_visible_with_party_tsv(conn: AsyncConnection) -> None:
    rows = (await conn.execute(sa.text(
        "SELECT id::text, narrative, kind, visibility::text, "
        "       party_tsv = to_tsvector('english', narrative), party_embedding IS NULL "
        "FROM journal_entries ORDER BY id"
    ))).all()
    expected = [(eid, narrative, "gm", "party", True, True)
                for eid, _, narrative, _, _ in sorted(make_snapshot._ENTRIES)]
    assert [tuple(r) for r in rows] == expected
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM journal_entries WHERE narrative IS NOT NULL AND party_tsv IS NULL")) == 0
    # Shorthand stays out of Party-only search: "brackenford" is shorthand-only.
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM journal_entries "
        "WHERE party_tsv @@ plainto_tsquery('english', 'brackenford')")) == 0


@post_upgrade_check(F1_CORE)
async def other_f1_core_columns_take_their_defaults(conn: AsyncConnection) -> None:
    assert (await conn.execute(sa.text(
        "SELECT visibility::text FROM shorthand_terms"))).scalars().all() == ["gm"]
    assert (await conn.execute(sa.text(
        "SELECT source_field FROM journal_tags"))).scalars().all() == [None]


@post_upgrade_check(F1_CORE)
async def visibility_server_defaults_follow_ad12(conn: AsyncConnection) -> None:
    # Most of these tables have no seed rows, and the model diff test ignores
    # server defaults, so read the defaults themselves.
    defaults = dict((await conn.execute(sa.text(
        "SELECT table_name, column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND column_name = 'visibility'"
    ))).all())
    assert defaults == {
        "journal_entries": "'party'::visibility",
        "character_sheets": "'party'::visibility",
        "tag_categories": "'party'::visibility",
        "session_plans": "'gm'::visibility",
        "source_documents": "'gm'::visibility",
        "shorthand_terms": "'gm'::visibility",
        # F3-world (E0-WorldCore.2): the world starts GM-only.
        "entities": "'gm'::visibility",
        "entity_relationships": "'gm'::visibility",
    }


@post_upgrade_check(F1_CORE)
async def entry_hash_unique_per_campaign_and_author(conn: AsyncConnection) -> None:
    uniques = dict((await conn.execute(sa.text(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'journal_entries'::regclass AND contype = 'u'"
    ))).all())
    assert uniques == {
        "uq_journal_entries_campaign_user_entry_hash": "UNIQUE (campaign_id, user_id, entry_hash)",
    }


# F2-jobs-files (E0-Jobs.1): four new, empty tables.

async def _f2_indexes(conn: AsyncConnection) -> dict[str, str]:
    return dict((await conn.execute(sa.text(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = current_schema() AND tablename = ANY(:t) AND indexname NOT LIKE '%_pkey'"
    ), {"t": list(F2_TABLES)})).all())


@post_upgrade_check(F2_JOBS_FILES)
async def f2_tables_exist_empty_with_their_indexes(conn: AsyncConnection) -> None:
    for table in F2_TABLES:
        # F3-world's backfill row is the one row any of them holds at head.
        where = f" WHERE name <> '{f3_world.BACKFILL_NAME}'" if table == "data_backfills" else ""
        assert await conn.scalar(sa.text(f"SELECT count(*) FROM {table}{where}")) == 0, table
    defs = await _f2_indexes(conn)
    assert set(defs) == {
        "uq_jobs_idempotency_key_active", "ix_jobs_campaign_status_created", "ix_jobs_status_queue_created",
        "uq_stored_files_cache_key_fresh", "ix_derived_sources_ref", "ix_derived_sources_derived",
    }
    active = defs["uq_jobs_idempotency_key_active"]
    assert active.startswith("CREATE UNIQUE INDEX") and "(idempotency_key)" in active
    assert "'queued'" in active and "'running'" in active and "'done'" not in active
    fresh = defs["uq_stored_files_cache_key_fresh"]
    assert fresh.startswith("CREATE UNIQUE INDEX") and "(campaign_id, kind, cache_key)" in fresh
    assert "WHERE (NOT stale)" in fresh
    assert "(campaign_id, status, created_at)" in defs["ix_jobs_campaign_status_created"]
    assert "(status, queue, created_at)" in defs["ix_jobs_status_queue_created"]
    assert "(ref_kind, ref_id)" in defs["ix_derived_sources_ref"]
    assert "(derived_type, derived_id)" in defs["ix_derived_sources_derived"]
    assert await conn.scalar(sa.text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'jobs' AND column_name = 'max_attempts'"
    )) == "3"


# F3-world (E0-WorldCore.2): the legacy NPC/Quest copy.

OWNER_ID = make_snapshot.OWNER
CAMPAIGN_ID = make_snapshot.CAMPAIGN
SEED_TS = "2026-01-01 12:00:00+00"
_ROLE_MAP = {"pc": ("character", "pc"), "npc": ("character", "npc"), "monster": ("character", "creature"),
             "faction": ("faction", None)}
_STATUS_MAP = {"character": {"alive": "alive", "dead": "deceased", "unknown": "unknown"},
               "faction": {"alive": "active", "dead": "disbanded", "unknown": "unknown"}}


def f3_id(kind: str, key: str) -> str:
    """The migration's deterministic id: md5('f3-world:<kind>:<key>')::uuid."""
    return str(uuid.UUID(hashlib.md5(f"f3-world:{kind}:{key}".encode()).hexdigest()))


def _ts(literal: str) -> str:
    return literal.strip("'")


def expected_seed_entities() -> list[tuple]:
    """Every copied Entity the seed must produce, as `_entity_rows` returns them."""
    rows = []
    for i, (name, role, status, description, notes) in enumerate(make_snapshot._NPCS, start=1):
        legacy = SEED_ID(f"70{i}")
        type_, kind = _ROLE_MAP[role]
        rows.append((f3_id("npc", legacy), CAMPAIGN_ID, type_, kind, name, description,
                     _STATUS_MAP[type_][status], {}, notes, "gm", {}, None, None, None, legacy, None, OWNER_ID,
                     SEED_TS, SEED_TS))
    for i, (title, status, description, notes, updated_at) in enumerate(make_snapshot._QUESTS, start=1):
        legacy = SEED_ID(f"80{i}")
        updated = _ts(updated_at)
        attributes = {}
        if status == "completed":
            # ISO 8601 UTC of quests.updated_at.
            attributes = {"completed_at": updated.replace(" ", "T").replace("+00", ".000000Z")}
        rows.append((f3_id("quest", legacy), CAMPAIGN_ID, "quest", None, title, description, status, attributes,
                     notes, "gm", {}, None, None, None, None, legacy, OWNER_ID, SEED_TS, updated))
    return sorted(rows)


async def _entity_rows(conn: AsyncConnection) -> list[tuple]:
    rows = (await conn.execute(sa.text(
        "SELECT id::text, campaign_id::text, type, kind, name, description, status, attributes, gm_notes, "
        "       visibility::text, field_visibility, linked_user_id::text, merged_into_id::text, "
        "       deleted_at::text, legacy_npc_id::text, legacy_quest_id::text, created_by_user_id::text, "
        "       to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00', "
        "       to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00' "
        "FROM entities ORDER BY id"
    ))).all()
    return sorted(tuple(r) for r in rows)


@post_upgrade_check(F3_WORLD)
async def every_npc_and_quest_has_exactly_one_entity_with_nothing_lost(conn: AsyncConnection) -> None:
    assert await _entity_rows(conn) == expected_seed_entities()
    # Exactly one Entity per legacy row, and no other Entity.
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM npcs n WHERE (SELECT count(*) FROM entities e WHERE e.legacy_npc_id = n.id) <> 1"
    )) == 0
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM quests q WHERE (SELECT count(*) FROM entities e WHERE e.legacy_quest_id = q.id) <> 1"
    )) == 0
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM entities WHERE legacy_npc_id IS NULL AND legacy_quest_id IS NULL")) == 0
    # Field by field against the legacy rows themselves.
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM npcs n JOIN entities e ON e.legacy_npc_id = n.id "
        "WHERE e.campaign_id <> n.campaign_id OR e.name <> n.name "
        "   OR e.description IS DISTINCT FROM n.description OR e.gm_notes IS DISTINCT FROM n.notes "
        "   OR e.created_by_user_id <> n.user_id OR e.created_at <> n.created_at OR e.updated_at <> n.updated_at"
    )) == 0
    assert await conn.scalar(sa.text(
        "SELECT count(*) FROM quests q JOIN entities e ON e.legacy_quest_id = q.id "
        "WHERE e.campaign_id <> q.campaign_id OR e.name <> q.title OR e.status <> q.status::text "
        "   OR e.description IS DISTINCT FROM q.description OR e.gm_notes IS DISTINCT FROM q.notes "
        "   OR e.created_by_user_id <> q.user_id OR e.created_at <> q.created_at OR e.updated_at <> q.updated_at"
    )) == 0


@post_upgrade_check(F3_WORLD)
async def copied_entities_are_gm_only_and_the_faction_is_a_faction(conn: AsyncConnection) -> None:
    assert (await conn.execute(sa.text(
        "SELECT DISTINCT visibility::text, field_visibility FROM entities"))).all() == [("gm", {})]
    faction = (await conn.execute(sa.text(
        "SELECT type, kind, status FROM entities WHERE legacy_npc_id = :id"), {"id": SEED_ID("703")})).one()
    assert tuple(faction) == ("faction", None, "disbanded")
    completed_at = await conn.scalar(sa.text(
        "SELECT attributes->>'completed_at' FROM entities WHERE legacy_quest_id = :id"), {"id": SEED_ID("802")})
    assert completed_at == "2026-01-08T18:30:00.000000Z"


@post_upgrade_check(F3_WORLD)
async def legacy_npcs_and_quests_are_unchanged(conn: AsyncConnection) -> None:
    npcs = (await conn.execute(sa.text(
        "SELECT name, role::text, status::text, description, notes FROM npcs ORDER BY id"))).all()
    assert [tuple(r) for r in npcs] == [tuple(n) for n in make_snapshot._NPCS]
    quests = (await conn.execute(sa.text(
        "SELECT title, status::text, description, notes, "
        "       to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || '+00' "
        "FROM quests ORDER BY id"))).all()
    assert [tuple(r) for r in quests] == [(t, st, d, n, _ts(u)) for t, st, d, n, u in make_snapshot._QUESTS]


@post_upgrade_check(F3_WORLD)
async def each_copy_has_one_migrated_history_row(conn: AsyncConnection) -> None:
    rows = (await conn.execute(sa.text(
        "SELECT ch.id::text, ch.entity_id::text, ch.op, ch.field, ch.old_value, ch.new_value, "
        "       ch.actor_user_id::text, ch.source_journal_id, ch.created_at = e.created_at "
        "FROM entity_changes ch JOIN entities e ON e.id = ch.entity_id ORDER BY ch.id"
    ))).all()
    expected = []
    for row in expected_seed_entities():
        entity_id, legacy_npc = row[0], row[14]
        # No legacy id: a published Entity's history must not carry one.
        new_value = {"from": "npcs"} if legacy_npc else {"from": "quests"}
        expected.append((f3_id("migrated", entity_id), entity_id, "migrated", None, None, new_value, OWNER_ID,
                         None, True))
    assert sorted(tuple(r) for r in rows) == sorted(expected)


@post_upgrade_check(F3_WORLD)
async def every_campaign_has_the_default_relationship_types(conn: AsyncConnection) -> None:
    rows = (await conn.execute(sa.text(
        "SELECT id::text, campaign_id::text, key, label, inverse_label, hostile FROM relationship_types "
        "ORDER BY key"))).all()
    expected = sorted(
        (f3_id("relationship_type", f"{CAMPAIGN_ID}:{key}"), CAMPAIGN_ID, key, label, inverse, hostile)
        for key, label, inverse, hostile in f3_world.DEFAULT_RELATIONSHIP_TYPES)
    assert sorted(tuple(r) for r in rows) == expected
    assert {r[2] for r in rows} == {"ally_of", "enemy_of", "member_of", "located_in", "owns", "related_to"}
    assert [r[2] for r in rows if r[5]] == ["enemy_of"]  # RC-13


@post_upgrade_check(F3_WORLD)
async def suggested_mentions_backfill_is_queued(conn: AsyncConnection) -> None:
    rows = (await conn.execute(sa.text("SELECT name, status, cursor, job_id FROM data_backfills"))).all()
    assert [tuple(r) for r in rows] == [("suggested_mentions_v1", "queued", None, None)]
    # Nothing else of the world: no Mentions, aliases, edges or steps yet.
    for table in ("entity_aliases", "entity_mentions", "entity_relationships", "quest_steps"):
        assert await conn.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0, table


@post_upgrade_check(F3_WORLD)
async def f3_set_null_links_keep_campaign_id(conn: AsyncConnection) -> None:
    defs = dict((await conn.execute(sa.text(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname IN ('fk_entities_merged_into', 'fk_character_sheets_pc_entity', "
        "                  'fk_chat_sessions_npc_entity')"
    ))).all())
    assert defs == {
        "fk_entities_merged_into": "FOREIGN KEY (campaign_id, merged_into_id) REFERENCES entities(campaign_id, id) "
                                   "ON DELETE SET NULL (merged_into_id)",
        "fk_character_sheets_pc_entity": "FOREIGN KEY (campaign_id, pc_entity_id) REFERENCES "
                                         "entities(campaign_id, id) ON DELETE SET NULL (pc_entity_id)",
        "fk_chat_sessions_npc_entity": "FOREIGN KEY (campaign_id, npc_entity_id) REFERENCES "
                                       "entities(campaign_id, id) ON DELETE SET NULL (npc_entity_id)",
    }


# Every F1-core column, by table: (key columns, F1-core columns). The
# idempotency test compares these values before and after re-applying the
# data steps.
F1_CORE_COLUMNS = {
    "journal_entries": ("id", ("kind", "visibility", "party_tsv", "party_embedding")),
    "campaign_members": ("id", ("role", "access_epoch")),
    "campaign_share_tokens": ("id", ("role", "expires_at", "access_epoch")),
    "chat_sessions": ("id", ("archived_at", "npc_entity_id")),
    "journal_tags": ("journal_id, tag_id", ("source_field",)),
    "character_sheets": ("id", ("pc_entity_id", "visibility")),
    "session_plans": ("id", ("visibility",)),
    "source_documents": ("id", ("visibility",)),
    "shorthand_terms": ("id", ("visibility",)),
    "tag_categories": ("id", ("visibility",)),
}


async def _f1_core_values(conn: AsyncConnection) -> dict[str, list[tuple]]:
    values = {}
    for table, (key, columns) in F1_CORE_COLUMNS.items():
        keys = [k.strip() for k in key.split(",")]
        cols = ", ".join(f"{c}::text" for c in [*keys, *columns])
        rows = (await conn.execute(sa.text(
            f"SELECT {cols} FROM {table} ORDER BY {key}"))).all()
        values[table] = [tuple(r) for r in rows]
    return values


# ---------------------------------------------------------------------------


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config(TEST_DB_URL))


async def _restore(url: str, sql: str) -> None:
    # The dump starts with `set_config('search_path', '', false)`, so it gets
    # its own engine. asyncpg's execute() without arguments uses the simple
    # query protocol, which runs a multi-statement script (no psql needed).
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(sql)
    finally:
        await engine.dispose()


async def _state(url: str) -> tuple[str, dict[str, int]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            version = await conn.scalar(sa.text("SELECT version_num FROM alembic_version"))
            tables = (await conn.scalars(sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "AND table_name <> 'alembic_version' ORDER BY table_name"
            ))).all()
            counts = {
                t: await conn.scalar(sa.text(f'SELECT count(*) FROM public."{t}"'))
                for t in tables
            }
            return version, counts
    finally:
        await engine.dispose()


async def _run_check(url: str, check: Check) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await check(conn)
    finally:
        await engine.dispose()


_DELETE_RULES = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


def fk_key(table: str, columns: list[str]) -> str:
    """"table.column", or "table.(a, b)" for a composite FK."""
    return f"{table}.{columns[0]}" if len(columns) == 1 else f"{table}.({', '.join(columns)})"


async def _fk_rules(url: str) -> dict[str, set[str]]:
    # pg_constraint, one row per FK constraint (information_schema joins by
    # constraint name, which is unique only per table, and splits composites).
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.text(
                "SELECT c.conrelid::regclass::text, "
                "       array(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, i) "
                "             JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "             ORDER BY k.i)::text[], "
                "       c.confdeltype::text "
                "FROM pg_constraint c "
                "WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"
            ))).all()
            rules: dict[str, set[str]] = {}
            for t, cols, rule in rows:
                rules.setdefault(fk_key(t, list(cols)), set()).add(_DELETE_RULES[rule])
            return rules
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def upgraded_snapshot():
    """Restore the snapshot, upgrade it to head; rebuild the clean schema after."""
    _guard_test_database(TEST_DB_URL)
    try:
        asyncio.run(_reset_public_schema(TEST_DB_URL, with_vector=False))
        asyncio.run(_restore(TEST_DB_URL, SNAPSHOT_SQL.read_text()))
        before = asyncio.run(_state(TEST_DB_URL))
        command.upgrade(alembic_config(TEST_DB_URL), "head")
        after = asyncio.run(_state(TEST_DB_URL))
        yield {"before": before, "after": after}
    finally:
        build_test_schema(TEST_DB_URL)


def test_single_alembic_head():
    heads = _script().get_heads()
    assert len(heads) == 1, f"expected one Alembic head, found {len(heads)}: {sorted(heads)}"


def test_snapshot_restores_at_baseline_with_seed(upgraded_snapshot):
    version, counts = upgraded_snapshot["before"]
    assert version == SNAPSHOT_REVISION
    nonempty = {t: n for t, n in counts.items() if n}
    assert nonempty == SEEDED_COUNTS


def test_snapshot_upgrades_to_head(upgraded_snapshot):
    version, _ = upgraded_snapshot["after"]
    assert version == _script().get_current_head()


def test_upgrade_keeps_row_counts(upgraded_snapshot):
    _, before = upgraded_snapshot["before"]
    _, after = upgraded_snapshot["after"]
    changed = {
        t: (n, after.get(t, "table dropped"))
        for t, n in before.items()
        if after.get(t) != n
    }
    assert not changed, f"row counts changed by the upgrade (before, after): {changed}"


@pytest.mark.parametrize(
    "check",
    [c for checks in POST_UPGRADE_CHECKS.values() for c in checks],
    ids=lambda c: c.__name__,
)
def test_post_upgrade_check(upgraded_snapshot, check):
    asyncio.run(_run_check(TEST_DB_URL, check))


def test_post_upgrade_checks_name_real_revisions():
    script = _script()
    known = {rev.revision for rev in script.walk_revisions()}
    bad = sorted(set(POST_UPGRADE_CHECKS) - known)
    assert not bad, f"POST_UPGRADE_CHECKS keys that are not Alembic revisions: {bad}"


def test_fk_on_delete_actions(upgraded_snapshot):
    actual = asyncio.run(_fk_rules(TEST_DB_URL))
    # A set, so two FKs on one column with different rules can't hide each other.
    unexpected = sorted(
        f"{k} -> {'/'.join(sorted(v))}"
        for k, v in actual.items()
        if v != {EXPECTED_FK_ON_DELETE.get(k)}
    )
    missing = sorted(k for k in EXPECTED_FK_ON_DELETE if k not in actual)
    assert not unexpected and not missing, (
        f"FKs whose ON DELETE rule is not in EXPECTED_FK_ON_DELETE: {unexpected}; "
        f"expected FKs that no longer exist: {missing}. "
        "State each FK's ON DELETE rule in EXPECTED_FK_ON_DELETE "
        "(tests/migrations/test_upgrade_snapshot.py)."
    )


async def _with_conn(url: str, fn):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return await fn(conn)
    finally:
        await engine.dispose()


async def _reapply_f1_core_data_steps(conn: AsyncConnection) -> None:
    await conn.run_sync(f1_core.apply_data_steps)
    await conn.commit()


def test_c95acb56c595_data_steps_are_idempotent(upgraded_snapshot):
    # "upgrade head a second time": stamp back to the baseline, re-apply the
    # revision's data steps on the already-migrated rows, stamp head again.
    # A Co-GM promoted after the upgrade (token 402, member 301) must survive
    # the re-run: catches a dropped `role IS NULL` guard or a role UPDATE.
    cfg = alembic_config(TEST_DB_URL)
    asyncio.run(_with_conn(TEST_DB_URL, lambda c: _set_promoted_roles(c, "co_gm")))
    try:
        before = asyncio.run(_with_conn(TEST_DB_URL, _f1_core_values))
        assert before["chat_sessions"], "seed changed: no chat_sessions to compare"
        command.stamp(cfg, SNAPSHOT_REVISION, purge=True)
        try:
            asyncio.run(_with_conn(TEST_DB_URL, _reapply_f1_core_data_steps))
        finally:
            command.stamp(cfg, "head", purge=True)
        after = asyncio.run(_with_conn(TEST_DB_URL, _f1_core_values))
        assert after == before
        assert (SEED_ID("402"), "co_gm", None, "0") in after["campaign_share_tokens"]
        assert (SEED_ID("301"), "co_gm", "0") in after["campaign_members"]
    finally:
        asyncio.run(_with_conn(TEST_DB_URL, lambda c: _set_promoted_roles(c, "player")))


async def _set_promoted_roles(conn: AsyncConnection, role: str) -> None:
    await conn.execute(sa.text(
        "UPDATE campaign_share_tokens SET role = CAST(:r AS campaign_role) WHERE id = :id"
    ), {"r": role, "id": SEED_ID("402")})
    await conn.execute(sa.text(
        "UPDATE campaign_members SET role = CAST(:r AS campaign_role) WHERE id = :id"
    ), {"r": role, "id": SEED_ID("301")})
    await conn.commit()


async def _baseline_schema(conn: AsyncConnection) -> dict:
    f1_columns = {f"{t}.{c}" for t, (_, cols) in F1_CORE_COLUMNS.items() for c in cols}
    existing = set((await conn.execute(sa.text(
        "SELECT table_name || '.' || column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    ))).scalars())
    return {
        "types": sorted((await conn.execute(sa.text(
            "SELECT typname FROM pg_type WHERE typname IN ('visibility', 'campaign_role') "
            "AND typnamespace = to_regnamespace(current_schema())"
        ))).scalars()),
        "columns": sorted(f1_columns & existing),
        "indexes": sorted((await conn.execute(sa.text(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'ix_journal_party_fts'"
        ))).scalars()),
        "uniques": sorted((await conn.execute(sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'journal_entries'::regclass AND contype = 'u'"
        ))).scalars()),
    }


def test_c95acb56c595_downgrade_restores_baseline(upgraded_snapshot):
    # Dev only (NFR-8): the downgrade puts back the exact a3e7c1f9d258 schema.
    cfg = alembic_config(TEST_DB_URL)
    command.downgrade(cfg, SNAPSHOT_REVISION)
    try:
        schema = asyncio.run(_with_conn(TEST_DB_URL, _baseline_schema))
    finally:
        command.upgrade(cfg, "head")
    assert schema == {
        "types": [],
        "columns": [],
        "indexes": [],
        "uniques": ["journal_entries_entry_hash_key"],
    }
    assert asyncio.run(_with_conn(TEST_DB_URL, _f1_core_values))["campaign_members"] == [
        (SEED_ID("301"), "player", "0"), (SEED_ID("302"), "player", "0")]


async def _public_tables(conn: AsyncConnection) -> set[str]:
    return set((await conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    ))).scalars())


def test_cf62d979bc8a_downgrade_drops_its_tables(upgraded_snapshot):
    # Dev only (NFR-8): downgrading to F1-core removes exactly the four tables
    # (and, on the way, F3-world's seven).
    cfg = alembic_config(TEST_DB_URL)
    at_head = asyncio.run(_with_conn(TEST_DB_URL, _public_tables))
    command.downgrade(cfg, F1_CORE)
    try:
        at_f1 = asyncio.run(_with_conn(TEST_DB_URL, _public_tables))
        f1_version = asyncio.run(_state(TEST_DB_URL))[0]
    finally:
        command.upgrade(cfg, "head")
    assert f1_version == F1_CORE
    assert at_head - at_f1 == set(F2_TABLES) | set(F3_TABLES)
    assert at_f1 <= at_head
    assert asyncio.run(_with_conn(TEST_DB_URL, _public_tables)) == at_head


# F3-world: the rows the revision writes, by table, for the idempotency and
# downgrade tests (data_backfills without its updated_at, which is now()).
async def _f3_values(conn: AsyncConnection) -> dict[str, list]:
    values = {}
    for table in F3_TABLES:
        values[table] = list((await conn.execute(sa.text(
            f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))).scalars())
    values["data_backfills"] = [tuple(r) for r in (await conn.execute(sa.text(
        "SELECT name, status, cursor FROM data_backfills ORDER BY name"))).all()]
    return values


async def _legacy_values(conn: AsyncConnection) -> dict[str, list]:
    return {table: list((await conn.execute(sa.text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id"))).scalars())
            for table in ("npcs", "quests")}


async def _reapply_f3_data_steps(conn: AsyncConnection) -> None:
    await conn.run_sync(f3_world.apply_data_steps)
    await conn.commit()


def test_03c0b504f1d1_data_steps_are_idempotent(upgraded_snapshot):
    # Re-applying the copy (as E0-WorldCore.6 will) and re-running the whole
    # revision through a downgrade both give identical rows, ids included.
    cfg = alembic_config(TEST_DB_URL)
    before = asyncio.run(_with_conn(TEST_DB_URL, _f3_values))
    assert len(before["entities"]) == 5 and len(before["entity_changes"]) == 5
    command.stamp(cfg, F2_JOBS_FILES, purge=True)
    try:
        asyncio.run(_with_conn(TEST_DB_URL, _reapply_f3_data_steps))
    finally:
        command.stamp(cfg, "head", purge=True)
    assert asyncio.run(_with_conn(TEST_DB_URL, _f3_values)) == before

    command.downgrade(cfg, F2_JOBS_FILES)
    command.upgrade(cfg, "head")
    assert asyncio.run(_with_conn(TEST_DB_URL, _f3_values)) == before


async def _deferred_fks(conn: AsyncConnection) -> list[str]:
    return sorted((await conn.execute(sa.text(
        "SELECT conname FROM pg_constraint WHERE contype = 'f' "
        "AND conrelid IN ('character_sheets'::regclass, 'chat_sessions'::regclass) "
        "AND conname IN ('fk_character_sheets_pc_entity', 'fk_chat_sessions_npc_entity')"
    ))).scalars())


def test_03c0b504f1d1_downgrade_drops_its_tables(upgraded_snapshot):
    # Dev only (NFR-8): downgrading to F2-jobs-files removes exactly the seven
    # tables, the two deferred FKs and the backfill row; npcs and quests are
    # untouched.
    cfg = alembic_config(TEST_DB_URL)
    at_head = asyncio.run(_with_conn(TEST_DB_URL, _public_tables))
    legacy = asyncio.run(_with_conn(TEST_DB_URL, _legacy_values))
    assert asyncio.run(_with_conn(TEST_DB_URL, _deferred_fks)) == [
        "fk_character_sheets_pc_entity", "fk_chat_sessions_npc_entity"]
    command.downgrade(cfg, F2_JOBS_FILES)
    try:
        at_f2 = asyncio.run(_with_conn(TEST_DB_URL, _public_tables))
        version = asyncio.run(_state(TEST_DB_URL))[0]
        fks = asyncio.run(_with_conn(TEST_DB_URL, _deferred_fks))
        backfills = asyncio.run(_with_conn(TEST_DB_URL, lambda c: c.scalar(sa.text(
            "SELECT count(*) FROM data_backfills"))))
        legacy_at_f2 = asyncio.run(_with_conn(TEST_DB_URL, _legacy_values))
    finally:
        command.upgrade(cfg, "head")
    assert version == F2_JOBS_FILES
    assert at_head - at_f2 == set(F3_TABLES)
    assert at_f2 <= at_head
    assert fks == []
    assert backfills == 0
    assert legacy_at_f2 == legacy
    assert asyncio.run(_with_conn(TEST_DB_URL, _legacy_values)) == legacy


def test_a3e7c1f9d258_backfills_shorthand(upgraded_snapshot):
    # Runs a3e7c1f9d258's downgrade and upgrade on the seeded rows: before it,
    # narrative_tsv held only the narrative, so the shorthand-only word is
    # missing; its backfill adds it. Ends back at head with the same rows.
    cfg = alembic_config(TEST_DB_URL)
    command.downgrade(cfg, "8c1d5f3a92e7")
    try:
        assert asyncio.run(_with_conn(TEST_DB_URL, _shorthand_word_matches)) == 0
    finally:
        command.upgrade(cfg, "head")
    assert asyncio.run(_with_conn(TEST_DB_URL, _shorthand_word_matches)) == 1
