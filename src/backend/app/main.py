import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.limiter import limiter

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis_client import init_redis, close_redis
from app.services.nlp_service import load_nlp_model
from app.services.embedding_service import load_embedding_model
from app.services.chat_service import check_kobold_health
from app.db.session import get_db
from app.api.routes import (
    auth, campaigns, journals, tags, chat, ingest, npcs, quests, sources, share, billing, session_plans, feedback,
    admin, shorthand, character_sheets,
)
from app.api.routes import settings as settings_routes
from app.api.deps import require_active_account, require_admin

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_file)
    logger.info("Starting Lorekeeper API", extra={"env": settings.environment})
    await init_redis()
    load_nlp_model()
    load_embedding_model()
    yield
    logger.info("Shutting down Lorekeeper API")
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Lorekeeper API",
        version="0.1.0",
        lifespan=lifespan,
        # Hide docs in production
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )

    # ── Rate limiting ──────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ───────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Request timing ────────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{ms:.1f}ms"
        logger.debug("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code, ms)
        return response

    # ── Global exception handler ───────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again."},
        )

    # ── Health endpoint ────────────────────────────────────────────────────────
    @app.get("/api/health", tags=["health"])
    async def health():
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.db.session import AsyncSessionLocal
        db_ok = False
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(text("SELECT 1"))
                db_ok = True
        except Exception:
            pass
        kobold_ok = await check_kobold_health()
        status = "ok" if (db_ok and kobold_ok) else "degraded"
        return {
            "status": status,
            "db": db_ok,
            "kobold": kobold_ok,
            "version": "0.1.0",
        }

    # ── Routers ────────────────────────────────────────────────────────────────
    # Feature routers get require_active_account at registration time — every
    # route in them needs a promo-redeemed or subscribed account, enforced once
    # here rather than added to each route individually. auth/billing/settings
    # are deliberately excluded: a not-yet-paid account still needs to log in,
    # see its billing status, start checkout, and configure its own LLM key.
    # share.router is excluded too — most of it is unauthenticated public
    # reads; its one authenticated route (join) is gated inline instead (see
    # app/api/routes/share.py).
    gate = [Depends(require_active_account)]
    app.include_router(auth.router,      prefix="/api/auth",      tags=["auth"])
    app.include_router(billing.router,   prefix="/api/billing",   tags=["billing"])
    app.include_router(campaigns.router, prefix="/api/campaigns", tags=["campaigns"], dependencies=gate)
    app.include_router(journals.router,  prefix="/api/journals",  tags=["journals"],  dependencies=gate)
    app.include_router(tags.router,      prefix="/api/tags",      tags=["tags"],      dependencies=gate)
    app.include_router(chat.router,      prefix="/api/chat",      tags=["chat"],      dependencies=gate)
    app.include_router(ingest.router,    prefix="/api/ingest",    tags=["ingest"],    dependencies=gate)
    app.include_router(npcs.router,      prefix="/api/npcs",      tags=["npcs"],      dependencies=gate)
    app.include_router(quests.router,    prefix="/api/quests",    tags=["quests"],    dependencies=gate)
    app.include_router(sources.router,   prefix="/api/sources",   tags=["sources"],   dependencies=gate)
    app.include_router(session_plans.router, prefix="/api/session-plans", tags=["session-plans"], dependencies=gate)
    app.include_router(shorthand.router,     prefix="/api/shorthand",     tags=["shorthand"],     dependencies=gate)
    app.include_router(character_sheets.router, prefix="/api/character-sheets", tags=["character-sheets"], dependencies=gate)
    # POST / only needs require_active_account (covered by `gate` here); the
    # admin-only GET routes layer Depends(require_admin) on top per-route
    # (see feedback.py) since require_admin itself builds on
    # require_active_account rather than replacing it.
    app.include_router(feedback.router,  prefix="/api/feedback",  tags=["feedback"],  dependencies=gate)
    # Every route in admin.py needs full admin access (unlike feedback.py,
    # which only needed that for its GET routes) — one router-level
    # dependency covers all of them instead of repeating it per-route.
    app.include_router(admin.router,     prefix="/api/admin",     tags=["admin"],     dependencies=[Depends(require_admin)])
    app.include_router(share.router,     prefix="/api/share",     tags=["share"])
    app.include_router(settings_routes.router, prefix="/api/settings", tags=["settings"])

    return app


app = create_app()
