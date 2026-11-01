import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

# Programmatic callers (the test suite) pass configure_logger=False so that
# alembic.ini's logging config does not replace their own loggers.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Load .env from project root so DATABASE_URL is available even when alembic
# is run without manually exporting environment variables first. In the
# production Docker image the app lives in a shallower directory tree (see
# Dockerfile.prod), so this many parents may not exist there — that's fine,
# since docker-compose.prod.yml already injects everything via `env_file:
# .env` straight into the container's environment; this is a local-dev
# convenience only and must never be fatal if the depth doesn't exist.
try:
    _env_file = Path(__file__).resolve().parents[3] / ".env"
except IndexError:
    _env_file = None
if _env_file is not None and _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# A caller that set sqlalchemy.url itself (the test suite, via
# config.attributes["sqlalchemy_url_locked"]) keeps that URL; the CLI takes
# DATABASE_URL from the environment / .env.
database_url = os.environ.get("DATABASE_URL")
if database_url and not config.attributes.get("sqlalchemy_url_locked"):
    config.set_main_option("sqlalchemy.url", database_url)

from app.db.base import Base
import app.db.models  # noqa: E402,F401  registers every model on Base.metadata
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
