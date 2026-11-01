import asyncio
import atexit
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

# Must be set before app.main (and so app.core.config) is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["JOBS_EAGER"] = "1"
# The files_data volume (E0-Jobs.8): a temporary directory for the session,
# removed at exit, never the real /data/files.
_FILES_ROOT = tempfile.mkdtemp(prefix="lorekeeper-files-")
os.environ["FILES_ROOT"] = _FILES_ROOT
atexit.register(shutil.rmtree, _FILES_ROOT, ignore_errors=True)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker  # noqa: E402

from app.main import app  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.limiter import limiter  # noqa: E402
from app.db.session import get_db  # noqa: E402
from tests.fixtures.fake_llm import fake_llm, no_kobold_socket  # noqa: E402,F401  (E0-LLM.5)

DEFAULT_TEST_DB_URL = "postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test"


# Override per machine or per worktree, e.g. one lorekeeper_test_<lane> DB per
# parallel lane. An empty value counts as unset.
def resolve_test_db_url(environ: Mapping[str, str] = os.environ) -> str:
    return environ.get("TEST_DATABASE_URL") or DEFAULT_TEST_DB_URL


TEST_DB_URL = resolve_test_db_url()

# setup_test_db drops every table, so only run against a database whose name
# marks it as a test DB: "..._test" or "..._test_<lane>" (lane alphanumeric).
_TEST_DB_NAME_RE = re.compile(r"^.+_test(_[A-Za-z0-9]+)?$")
TEST_DB_NAME_RULE = (
    "the database name must end in '_test' or '_test_<lane>' "
    "(lane = letters/digits only)"
)


def is_test_database_name(name: str | None) -> bool:
    """True if `name` is safe for the suite to wipe."""
    return bool(name) and _TEST_DB_NAME_RE.fullmatch(name) is not None


def _guard_test_database(url: str) -> None:
    """Abort the whole session before anything connects to a non-test DB."""
    try:
        name = make_url(url).database
    except Exception:  # unparseable URL — refuse rather than guess
        # No exception text: SQLAlchemy's message echoes the URL, password included.
        pytest.exit(
            "Refusing to run tests: TEST_DATABASE_URL could not be parsed.",
            returncode=1,
        )
    if not is_test_database_name(name):
        pytest.exit(
            f"Refusing to run tests against database {name!r}: {TEST_DB_NAME_RULE}. "
            "The suite drops all tables. Set TEST_DATABASE_URL to a test database.",
            returncode=1,
        )


ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config(url: str) -> Config:
    """An Alembic Config that migrates `url`, whatever DATABASE_URL or .env say.

    The ini is found by absolute path, so this works from any cwd. ConfigParser
    treats `%` as interpolation, so the URL (a password may contain one) is
    escaped. migrations/env.py honours both attributes.
    """
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["sqlalchemy_url_locked"] = True
    cfg.attributes["configure_logger"] = False  # keep pytest's loggers
    return cfg


async def _reset_public_schema(url: str, *, with_vector: bool) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(sa.text("CREATE SCHEMA public"))
            if with_vector:
                # DROP SCHEMA took the extension with it.
                await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        await engine.dispose()


async def _reset_app_config(url: str) -> None:
    # The migration seeds open_access_mode=true. The suite was written against
    # the gated row get_app_config() used to create from settings when the
    # schema came from the models instead of the migrations.
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE app_config SET open_access_mode = :v"),
                {"v": get_settings().open_access_mode},
            )
    finally:
        await engine.dispose()


def build_test_schema(url: str) -> None:
    """Wipe `url`'s public schema and migrate it to head.

    Sync, so call it outside a running event loop. The caller must already
    have run _guard_test_database(url).
    """
    # Reset first: an older lane DB may hold model-built tables with no
    # alembic_version, and a bare upgrade would fail on "already exists".
    asyncio.run(_reset_public_schema(url, with_vector=True))
    command.upgrade(alembic_config(url), "head")
    asyncio.run(_reset_app_config(url))


def drop_test_schema(url: str) -> None:
    asyncio.run(_reset_public_schema(url, with_vector=False))


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Build the schema from the Alembic migrations once per session."""
    _guard_test_database(TEST_DB_URL)
    build_test_schema(TEST_DB_URL)
    yield
    drop_test_schema(TEST_DB_URL)


@pytest_asyncio.fixture
async def db():
    # Fresh engine per test — asyncpg connections stay in the current event loop.
    engine = create_async_engine(TEST_DB_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    # slowapi's Limiter uses process-wide in-memory storage by default — it
    # isn't scoped per test, so without resetting it here, whichever test
    # happens to run first "spends" part of the real 5/minute (register) or
    # 10/minute (login) budget that a *later* test then inherits, making that
    # later test fail with a 429 depending purely on execution order/count,
    # not on anything it did wrong itself. Reproduced this exact flake before
    # adding the reset: test_password_reset_invalidates_existing_tokens and
    # test_user_cannot_access_other_users_journal both failed with a KeyError
    # on 'access_token' because their register() call landed after 5 earlier
    # tests' register() calls had already used up the quota.
    limiter.reset()
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def promo_code(db: AsyncSession) -> str:
    """An unlimited-use promo code, for tests that need a registered user to
    actually have access_granted=True (see app/api/routes/auth.py::register —
    accounts are gated by default since account-gating shipped)."""
    from app.db.models.promo_code import PromoCode

    # Committed (registration reads it from a separate request session), so it
    # persists across tests — reuse it instead of re-inserting into the unique index.
    existing = await db.scalar(sa.select(PromoCode).where(PromoCode.code == "TESTCODE"))
    if existing is None:
        db.add(PromoCode(code="TESTCODE", active=True))
        await db.commit()
    return "TESTCODE"
