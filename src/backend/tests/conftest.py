import asyncio
import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.core.limiter import limiter
from app.db.base import Base
from app.db.session import get_db

TEST_DB_URL = "postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test"


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Drop and recreate all tables once per session using an isolated event loop."""
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

    code = PromoCode(code="TESTCODE", active=True)
    db.add(code)
    await db.commit()
    return "TESTCODE"
