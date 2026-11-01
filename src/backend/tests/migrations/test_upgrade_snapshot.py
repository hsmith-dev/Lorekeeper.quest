"""Migration-chain gates: one head, a brownfield upgrade, stated FK actions.

conftest's setup_test_db proves `alembic upgrade head` works on an empty DB.
Every self-hoster's boot runs it on a DB that already holds data, so this
module restores a seeded dump taken at SNAPSHOT_REVISION
(tests/fixtures/snapshot_a3e7c1f9d258.sql, made by scripts/make_snapshot.py),
upgrades it to head, and checks that no rows were lost and that each
revision's data changes landed (POST_UPGRADE_CHECKS).

While SNAPSHOT_REVISION is still the head, `upgrade head` runs no revisions
and the row-count and post-upgrade checks pass trivially. They start to bite
when the first later revision (F1-core) lands. The a3e7c1f9d258 round trip
below does exercise a real data migration on the seeded rows today.

pytest collects tests/migrations/ before tests/test_*.py, so the module
fixture rebuilds the clean session schema in teardown.
"""
import asyncio
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
