"""E0-LLM.1: the single LLM-config resolver, the deps 402 wrapper, metering,
and the typed LLMError family's one HTTP mapping.

Rows are created directly and only flushed (never committed) where possible,
so the db fixture's rollback undoes them — in particular the AppConfig
singleton's open_access_mode, which every other test's account gate reads.
No test here makes an LLM call or opens a socket to KOBOLD_URL.
"""

import json
import uuid

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_user_llm_config
from app.core.config import get_settings
from app.core.errors import (
    RETRYABLE,
    TERMINAL,
    LLMBusy,
    LLMConfigError,
    LLMError,
    LLMUnavailable,
    PromptBudgetError,
    StructuredOutputError,
    llm_error_response,
    llm_exception_handler,
)
from app.db.models.app_config import AppConfig
from app.db.models.subscription import Subscription
from app.db.models.user import User
from app.db.models.user_settings import UserSettings
from app.services import billing_service, llm_config_service
from app.services.llm_config_service import resolve_llm_config
from app.services.llm_provider import LLMConfig, get_default_config

QUOTA_MSG = "You've used your hosted-model quota for this billing period."
BYOK_MSG = "your plan doesn't include the hosted model"
SUBSCRIBE_MSG = "or subscribe to use Lorekeeper's hosted model."


async def _user(db) -> User:
    user = User(
        email=f"llmcfg_{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        display_name="LLM Config",
    )
    db.add(user)
    await db.flush()
    return user


async def _set_open_access(db, value: bool) -> None:
    cfg = await db.scalar(sa.select(AppConfig).where(AppConfig.id == 1))
    if cfg is None:
        db.add(AppConfig(id=1, open_access_mode=value))
    else:
        cfg.open_access_mode = value
    await db.flush()


async def _settings(db, user, **kw) -> UserSettings:
    us = UserSettings(user_id=user.id, **kw)
    db.add(us)
    await db.flush()
    return us


async def _sub(db, user, **kw) -> Subscription:
    sub = Subscription(user_id=user.id, **kw)
    db.add(sub)
    await db.flush()
    return sub


# ── resolve_llm_config: the I/O matrix ───────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [
    {"llm_provider": "openai", "llm_api_key": "sk-test", "llm_model": "gpt-x"},
    {"llm_provider": "kobold", "llm_api_url": "http://my-own-box:5001"},
    {"llm_provider": "kobold", "llm_model": "my-model"},
    {"llm_provider": "kobold", "llm_api_key": "k"},
])
async def test_personal_config_wins(db, fields):
    user = await _user(db)
    # Gating fully on and no subscription: a personal config still resolves.
    await _set_open_access(db, False)
    await _settings(db, user, llm_temperature=0.3, llm_max_tokens=123, **fields)

    cfg = await resolve_llm_config(db, user)

    assert cfg == LLMConfig(
        provider=fields["llm_provider"],
        api_url=fields.get("llm_api_url"),
        api_key=fields.get("llm_api_key"),
        model=fields.get("llm_model"),
        temperature=0.3,
        max_tokens=123,
    )


@pytest.mark.asyncio
async def test_open_access_returns_default(db):
    user = await _user(db)
    await _set_open_access(db, True)

    assert await resolve_llm_config(db, user) == get_default_config()


@pytest.mark.asyncio
async def test_open_access_base_variant_swaps_model(db):
    user = await _user(db)
    await _set_open_access(db, True)
    await _settings(db, user, hosted_model_variant="base")

    cfg = await resolve_llm_config(db, user)

    expected = get_default_config()
    expected.model = get_settings().kobold_base_model
    assert cfg == expected


@pytest.mark.asyncio
async def test_hosted_with_quota_returns_default(db):
    user = await _user(db)
    await _set_open_access(db, False)
    await _sub(db, user, plan="hosted", status="active",
               tokens_used_current_period=10, tokens_included_per_period=100)

    assert await resolve_llm_config(db, user) == get_default_config()


@pytest.mark.asyncio
async def test_hosted_with_quota_base_variant_swaps_model(db):
    user = await _user(db)
    await _set_open_access(db, False)
    await _settings(db, user, hosted_model_variant="base")
    await _sub(db, user, plan="hosted", status="active",
               tokens_used_current_period=0, tokens_included_per_period=100)

    cfg = await resolve_llm_config(db, user)

    assert cfg.model == get_settings().kobold_base_model
    assert cfg.api_url == get_default_config().api_url


@pytest.mark.asyncio
async def test_hosted_quota_spent_raises(db):
    user = await _user(db)
    await _set_open_access(db, False)
    await _sub(db, user, plan="hosted", status="active",
               tokens_used_current_period=100, tokens_included_per_period=100)

    with pytest.raises(LLMConfigError) as ei:
        await resolve_llm_config(db, user)
    assert QUOTA_MSG in ei.value.detail
    assert ei.value.headers == {"X-Gate-Reason": "llm-config"}


@pytest.mark.asyncio
async def test_byok_plan_without_key_raises(db):
    user = await _user(db)
    await _set_open_access(db, False)
    await _sub(db, user, plan="byok", status="active")

    with pytest.raises(LLMConfigError) as ei:
        await resolve_llm_config(db, user)
    assert BYOK_MSG in ei.value.detail


@pytest.mark.asyncio
async def test_nothing_configured_raises(db):
    user = await _user(db)
    await _set_open_access(db, False)

    with pytest.raises(LLMConfigError) as ei:
        await resolve_llm_config(db, user)
    assert SUBSCRIBE_MSG in ei.value.detail


@pytest.mark.asyncio
async def test_inactive_hosted_sub_gets_subscribe_message(db):
    # Canceled hosted plan: not eligible, not an active byok — falls through
    # to the generic subscribe message, same as before the move.
    user = await _user(db)
    await _set_open_access(db, False)
    await _sub(db, user, plan="hosted", status="canceled")

    with pytest.raises(LLMConfigError) as ei:
        await resolve_llm_config(db, user)
    assert SUBSCRIBE_MSG in ei.value.detail


# ── deps.get_user_llm_config: thin 402 wrapper ───────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("case,needle", [
    ("quota", QUOTA_MSG),
    ("byok", BYOK_MSG),
    ("nothing", SUBSCRIBE_MSG),
])
async def test_deps_wrapper_maps_to_402_with_header(db, case, needle):
    user = await _user(db)
    await _set_open_access(db, False)
    if case == "quota":
        await _sub(db, user, plan="hosted", status="active",
                   tokens_used_current_period=5, tokens_included_per_period=5)
    elif case == "byok":
        await _sub(db, user, plan="byok", status="active")

    with pytest.raises(HTTPException) as ei:
        await get_user_llm_config(user=user, db=db)
    assert ei.value.status_code == 402
    assert needle in ei.value.detail
    assert ei.value.headers == {"X-Gate-Reason": "llm-config"}


@pytest.mark.asyncio
async def test_deps_wrapper_passes_config_through(db):
    user = await _user(db)
    await _set_open_access(db, True)

    assert await get_user_llm_config(user=user, db=db) == get_default_config()


# ── meter ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_meter_hosted_records_once(db, monkeypatch):
    user = await _user(db)
    calls = []

    async def spy(db_, user_, *texts):
        calls.append((db_, user_, texts))

    monkeypatch.setattr(billing_service, "record_hosted_usage", spy)
    await llm_config_service.meter(db, user, get_default_config(), "prompt", "reply")

    assert calls == [(db, user, ("prompt", "reply"))]


@pytest.mark.asyncio
async def test_meter_hosted_updates_quota(db):
    # Real record_hosted_usage end to end: the subscription's token estimate
    # moves (it commits, so this test's rows persist under a unique email).
    user = await _user(db)
    sub = await _sub(db, user, plan="hosted", status="active", tokens_used_current_period=0)

    await llm_config_service.meter(db, user, get_default_config(), "x" * 400)

    await db.refresh(sub)
    assert sub.tokens_used_current_period == billing_service.estimate_tokens("x" * 400)


@pytest.mark.asyncio
async def test_meter_byok_skips_billing(db, monkeypatch):
    user = await _user(db)
    await _sub(db, user, plan="byok", status="active", tokens_used_current_period=0)

    async def boom(*a, **k):
        raise AssertionError("BYOK usage must never be metered")

    monkeypatch.setattr(billing_service, "record_hosted_usage", boom)
    byok = LLMConfig(provider="openai", api_key="sk-test", model="gpt-x")
    await llm_config_service.meter(db, user, byok, "prompt", "reply")


# ── route-level: a converted call site still meters (and only for hosted) ────

@pytest.mark.asyncio
@pytest.mark.parametrize("byok", [False, True])
async def test_generate_draft_route_meters_hosted_only(client, db, monkeypatch, byok):
    from app.api.routes import journals as journals_routes
    from app.core.security import create_access_token
    from app.db.models.campaign import Campaign

    async def fake_draft(*a, **k):
        return "A fixed narrative for metering." * 4

    monkeypatch.setattr(journals_routes, "generate_draft_narrative", fake_draft)

    # The client fixture shares this session with the app, and the route's
    # record_hosted_usage commits — so the AppConfig flip is committed too and
    # must be put back explicitly afterwards.
    prior = await db.scalar(sa.select(AppConfig.open_access_mode).where(AppConfig.id == 1))
    try:
        await _set_open_access(db, False)
        user = await _user(db)
        user.access_granted = True
        if byok:
            await _settings(db, user, llm_provider="openai", llm_api_key="sk-test", llm_model="gpt-x")
        sub = await _sub(db, user, plan="hosted", status="active",
                         tokens_used_current_period=0, tokens_included_per_period=1_000_000)
        campaign = Campaign(user_id=user.id, name="Metering Campaign")
        db.add(campaign)
        await db.commit()

        r = await client.post(
            "/api/journals/generate-draft",
            json={"notes": "The party met a dragon.", "campaign_id": str(campaign.id)},
            headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"},
        )
        assert r.status_code == 200, r.text

        await db.refresh(sub)
        if byok:
            assert sub.tokens_used_current_period == 0
        else:
            assert sub.tokens_used_current_period > 0
    finally:
        cfg = await db.scalar(sa.select(AppConfig).where(AppConfig.id == 1))
        if prior is None:
            if cfg is not None:
                await db.delete(cfg)
        else:
            cfg.open_access_mode = prior
        await db.commit()


# ── errors: classes, response mapping, handler ───────────────────────────────

ERROR_CASES = [
    (LLMConfigError("need a key"), 402, "llm_config", {"x-gate-reason": "llm-config"}),
    (LLMBusy("queue full"), 503, "llm_busy", {}),
    (LLMUnavailable("ollama down"), 503, "llm_unavailable", {}),
    (StructuredOutputError("AI output unusable", attempts=3, errors=[{"loc": ["x"]}]),
     422, "ai_output_unusable", {}),
    (PromptBudgetError("prompt too large"), 422, "prompt_too_large", {}),
]


@pytest.mark.parametrize("exc,status,code,headers", ERROR_CASES)
def test_llm_error_response(exc, status, code, headers):
    resp = llm_error_response(exc)
    assert resp.status_code == status
    assert json.loads(resp.body) == {"detail": exc.detail, "code": code}
    for k, v in headers.items():
        assert resp.headers[k] == v
    if not headers:
        assert "x-gate-reason" not in resp.headers


def test_llm_config_error_custom_reason():
    exc = LLMConfigError("x", reason="something-else")
    assert exc.headers == {"X-Gate-Reason": "something-else"}
    assert exc.reason == "something-else"


def test_structured_output_error_keeps_attempts_and_errors():
    exc = StructuredOutputError("AI output unusable", attempts=3, errors=[{"msg": "bad"}])
    assert exc.attempts == 3
    assert exc.errors == [{"msg": "bad"}]
    assert StructuredOutputError("x").errors == []


@pytest.mark.asyncio
@pytest.mark.parametrize("exc,status,code,headers", ERROR_CASES)
async def test_handler_on_fresh_app(exc, status, code, headers):
    app = FastAPI()
    app.add_exception_handler(LLMError, llm_exception_handler)

    @app.get("/boom")
    async def boom():
        raise exc

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == status
    assert r.json() == {"detail": exc.detail, "code": code}
    for k, v in headers.items():
        assert r.headers[k] == v


def test_main_app_registers_handler():
    from app.main import app
    assert app.exception_handlers.get(LLMError) is llm_exception_handler


def test_retryable_terminal_membership():
    assert set(RETRYABLE) == {LLMBusy, LLMUnavailable}
    assert set(TERMINAL) == {LLMConfigError, StructuredOutputError, PromptBudgetError}
    assert not set(RETRYABLE) & set(TERMINAL)
    for cls in (*RETRYABLE, *TERMINAL):
        assert issubclass(cls, LLMError)
    # isinstance-style use from a Job worker
    assert isinstance(LLMBusy("x"), RETRYABLE)
    assert isinstance(PromptBudgetError("x"), TERMINAL)
