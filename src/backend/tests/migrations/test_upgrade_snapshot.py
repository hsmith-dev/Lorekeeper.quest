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
a3e7c1f9d258 round trip downgrades through F1-core and upgrades again.

pytest collects tests/migrations/ before tests/test_*.py, so the module
fixture rebuilds the clean session schema in teardown.
"""
import asyncio
import importlib.util
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
f1_core = _load(
    "f1_core_revision",
    BACKEND_DIR / "migrations" / "versions" / "c95acb56c595_f1_core_roles_visibility_party_search.py",
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
    "npcs": 2,
    "quests": 2,
    "chat_sessions": 3,  # one per user
    "app_config": 1,  # seeded by 4b8f2d9e71c3
}

# The ON DELETE rule of every foreign key at head, as "table.column": rule.
# A revision that adds or changes an FK must update this table, so the
# deletion behaviour is a decision, not an accident.
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
    "feedback.campaign_id": "SET NULL",
    "feedback.user_id": "CASCADE",
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
    "subscriptions.user_id": "CASCADE",
    "tag_categories.campaign_id": "CASCADE",
    "tag_categories.created_by_user_id": "CASCADE",
    "tags.custom_category_id": "CASCADE",
    "user_settings.user_id": "CASCADE",
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
async def entry_hash_unique_per_campaign_and_author(conn: AsyncConnection) -> None:
    uniques = dict((await conn.execute(sa.text(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'journal_entries'::regclass AND contype = 'u'"
    ))).all())
    assert uniques == {
        "uq_journal_entries_campaign_user_entry_hash": "UNIQUE (campaign_id, user_id, entry_hash)",
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


async def _fk_rules(url: str) -> dict[str, set[str]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(sa.text(
                "SELECT kcu.table_name, kcu.column_name, rc.delete_rule "
                "FROM information_schema.referential_constraints rc "
                "JOIN information_schema.key_column_usage kcu "
                "  ON kcu.constraint_schema = rc.constraint_schema "
                " AND kcu.constraint_name = rc.constraint_name "
                "WHERE rc.constraint_schema = 'public'"
            ))).all()
            rules: dict[str, set[str]] = {}
            for t, c, rule in rows:
                rules.setdefault(f"{t}.{c}", set()).add(rule)
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
    cfg = alembic_config(TEST_DB_URL)
    before = asyncio.run(_with_conn(TEST_DB_URL, _f1_core_values))
    assert before["chat_sessions"], "seed changed: no chat_sessions to compare"
    command.stamp(cfg, SNAPSHOT_REVISION, purge=True)
    try:
        asyncio.run(_with_conn(TEST_DB_URL, _reapply_f1_core_data_steps))
    finally:
        command.stamp(cfg, "head", purge=True)
    after = asyncio.run(_with_conn(TEST_DB_URL, _f1_core_values))
    assert after == before


async def _baseline_schema(conn: AsyncConnection) -> dict:
    f1_columns = {f"{t}.{c}" for t, (_, cols) in F1_CORE_COLUMNS.items() for c in cols}
    existing = set((await conn.execute(sa.text(
        "SELECT table_name || '.' || column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    ))).scalars())
    return {
        "types": sorted((await conn.execute(sa.text(
            "SELECT typname FROM pg_type WHERE typname IN ('visibility', 'campaign_role')"
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
