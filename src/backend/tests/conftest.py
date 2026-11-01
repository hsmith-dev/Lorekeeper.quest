import asyncio
import os
import re
from collections.abc import Mapping

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import AsyncClient, ASGITransport
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.core.limiter import limiter
from app.db.base import Base
from app.db.session import get_db

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


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Drop and recreate all tables once per session using an isolated event loop."""
    _guard_test_database(TEST_DB_URL)

    async def _create():
        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    async def _drop():
        engine = create_async_engine(TEST_DB_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_create())
    yield
    asyncio.run(_drop())


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
