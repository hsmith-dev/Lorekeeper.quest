"""The schema the suite runs on comes from the Alembic migrations (conftest's
setup_test_db). These tests check that the migrations and the models agree,
and cover the edge cases of building that schema.

The last test rebuilds the session schema, so it stays at the bottom of the file.
"""
import asyncio
import os

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from tests.conftest import (
    TEST_DB_URL,
    _guard_test_database,
    alembic_config,
    build_test_schema,
)

# Known model/migration drift that is deliberately not fixed here. Each entry is
# (diff kind, table, columns) and matches one autogenerate diff.
IGNORED_DIFFS = {
    # The migrations add a UniqueConstraint *and* a unique index on these columns.
    # The models declare unique=True, index=True, which gives only the unique
    # index, so autogenerate wants to drop the constraint. The constraint is
    # redundant but harmless.
    ("remove_constraint", "password_reset_tokens", ("token_hash",)),
    ("remove_constraint", "promo_codes", ("code",)),
}


def _diff_key(diff):
    """(kind, table, columns) for a constraint/index diff, else None."""
    if not isinstance(diff, tuple) or len(diff) != 2:
        return None
    kind, obj = diff
    if kind not in {"add_constraint", "remove_constraint", "add_index", "remove_index"}:
        return None
    table = getattr(obj, "table", None)
    if table is None:
        return None
    return (kind, table.name, tuple(c.name for c in obj.columns))


def _unexpected(diffs):
    return [d for d in diffs if _diff_key(d) not in IGNORED_DIFFS]


async def _diffs_against(metadata):
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: compare_metadata(
                    MigrationContext.configure(sync_conn, opts={"compare_type": True}),
                    metadata,
                )
            )
    finally:
        await engine.dispose()


async def _scalar(sql: str):
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(sa.text(sql))
    finally:
        await engine.dispose()


def _script_head() -> str:
    return ScriptDirectory.from_config(alembic_config(TEST_DB_URL)).get_current_head()


async def test_migrations_match_models():
    diffs = _unexpected(await _diffs_against(Base.metadata))
    assert not diffs, (
        "The models and the migrated schema differ. Add a migration, or, for "
        "deliberate drift, an IGNORED_DIFFS entry with a comment:\n"
        + "\n".join(repr(d) for d in diffs)
    )


async def test_database_is_at_script_head():
    assert await _scalar("SELECT version_num FROM alembic_version") == _script_head()


async def test_unmigrated_model_table_is_detected():
    # Guards against a vacuous comparison: a model table with no migration must show up.
    metadata = sa.MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    sa.Table("zz_unmigrated", metadata, sa.Column("id", sa.Integer, primary_key=True))

    diffs = _unexpected(await _diffs_against(metadata))
    assert [d[1].name for d in diffs if d[0] == "add_table"] == ["zz_unmigrated"]


async def test_unmigrated_model_column_is_detected():
    metadata = sa.MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    metadata.tables["users"].append_column(sa.Column("zz_unmigrated", sa.Integer))

    diffs = _unexpected(await _diffs_against(metadata))
    assert [(d[0], d[2], d[3].name) for d in diffs] == [("add_column", "users", "zz_unmigrated")]


def test_alembic_config_escapes_percent_and_locks_url():
    url = "postgresql+asyncpg://u:p%40ss@localhost:5432/x_test"
    cfg = alembic_config(url)
    assert cfg.get_main_option("sqlalchemy.url") == url
    assert cfg.attributes["sqlalchemy_url_locked"] is True
    assert cfg.attributes["configure_logger"] is False


def test_locked_url_wins_over_database_url(monkeypatch):
    # env.py would otherwise point the migration at DATABASE_URL (or .env's),
    # which here is unreachable, so this would fail to connect.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nobody:x@127.0.0.1:1/lorekeeper")
    command.current(alembic_config(TEST_DB_URL))


def test_env_is_set_before_app_import():
    assert os.environ["ENVIRONMENT"] == "test"
    assert os.environ["JOBS_EAGER"] == "1"
    assert get_settings().environment == "test"


# Keep last: rebuilds the session schema.
def test_build_recovers_from_leftover_tables():
    async def _leave_leftovers():
        engine = create_async_engine(TEST_DB_URL)
        try:
            async with engine.begin() as conn:
                await conn.execute(sa.text("CREATE TABLE zz_leftover_create_all (id int)"))
                await conn.execute(sa.text("DELETE FROM alembic_version"))
        finally:
            await engine.dispose()

    asyncio.run(_leave_leftovers())

    _guard_test_database(TEST_DB_URL)
    build_test_schema(TEST_DB_URL)

    assert asyncio.run(_scalar("SELECT to_regclass('public.zz_leftover_create_all')")) is None
    assert asyncio.run(_scalar("SELECT version_num FROM alembic_version")) == _script_head()
    assert (
        asyncio.run(_scalar("SELECT open_access_mode FROM app_config WHERE id = 1"))
        == get_settings().open_access_mode
    )
