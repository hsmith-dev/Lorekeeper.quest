"""Rebuilding the test schema over leftovers from an older run.

This rebuilds the shared session schema. The zz_ prefix makes pytest collect
the file last, so no other test runs on the rebuilt schema.
"""
import asyncio

import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.conftest import (
    TEST_DB_URL,
    _guard_test_database,
    alembic_config,
    build_test_schema,
)


async def _execute(*statements: str) -> None:
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.begin() as conn:
            for sql in statements:
                await conn.execute(sa.text(sql))
    finally:
        await engine.dispose()


async def _scalar(sql: str):
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with engine.connect() as conn:
            return await conn.scalar(sa.text(sql))
    finally:
        await engine.dispose()


def test_build_recovers_from_leftover_create_all_schema():
    # What an older lane DB looks like: model-built tables (including ones the
    # migrations also create) and no alembic_version table. A bare
    # `alembic upgrade head` would fail on "relation users already exists".
    asyncio.run(_execute(
        "DROP TABLE alembic_version",
        "DROP TABLE users CASCADE",
        "CREATE TABLE users (id int)",
        "CREATE TABLE zz_leftover_create_all (id int)",
    ))

    _guard_test_database(TEST_DB_URL)
    build_test_schema(TEST_DB_URL)

    head = ScriptDirectory.from_config(alembic_config(TEST_DB_URL)).get_current_head()
    assert asyncio.run(_scalar("SELECT to_regclass('public.zz_leftover_create_all')")) is None
    assert asyncio.run(_scalar("SELECT version_num FROM alembic_version")) == head
    # The migrated users table, not the leftover one.
    assert asyncio.run(_scalar(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'email'"
    )) == 1
    assert (
        asyncio.run(_scalar("SELECT open_access_mode FROM app_config WHERE id = 1"))
        == get_settings().open_access_mode
    )
