"""Per-user rate-limit keying (E0-Platform.8 / story 3.8).

AI and streaming routes key slowapi buckets on ``user_or_ip`` so a GM and
Players behind one home router don't share a single AI bucket; everything else
keeps the default IP key.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings
from app.core.limiter import limiter, user_or_ip
from app.core.security import ALGORITHM, create_access_token

CLIENT_IP = "203.0.113.7"


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat/",
        "headers": headers,
        "client": (CLIENT_IP, 12345),
        "query_string": b"",
    }
    return Request(scope)


def _token(claims: dict, key: str | None = None) -> str:
    return jwt.encode(claims, key or get_settings().secret_key, algorithm=ALGORITHM)


# ── user_or_ip unit tests ────────────────────────────────────────────────────

def test_valid_bearer_keys_on_user():
    user_id = str(uuid.uuid4())
    assert user_or_ip(_request(f"Bearer {create_access_token(user_id)}")) == f"user:{user_id}"


def test_bearer_scheme_is_case_insensitive():
    user_id = str(uuid.uuid4())
    assert user_or_ip(_request(f"bearer {create_access_token(user_id)}")) == f"user:{user_id}"


def test_missing_header_falls_back_to_ip():
    assert user_or_ip(_request()) == CLIENT_IP


def test_wrong_signature_falls_back_to_ip():
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = _token({"sub": "someone", "exp": exp}, key="not-the-real-secret")
    assert user_or_ip(_request(f"Bearer {token}")) == CLIENT_IP


def test_expired_token_falls_back_to_ip():
    exp = datetime.now(timezone.utc) - timedelta(minutes=5)
    token = _token({"sub": "someone", "exp": exp})
    assert user_or_ip(_request(f"Bearer {token}")) == CLIENT_IP


def test_malformed_token_falls_back_to_ip():
    assert user_or_ip(_request("Bearer not.a.jwt")) == CLIENT_IP
    assert user_or_ip(_request("Bearer ")) == CLIENT_IP
    assert user_or_ip(_request("Bearer")) == CLIENT_IP


def test_non_bearer_scheme_falls_back_to_ip():
    token = create_access_token(str(uuid.uuid4()))
    assert user_or_ip(_request(f"Basic {token}")) == CLIENT_IP
    assert user_or_ip(_request(token)) == CLIENT_IP


def test_token_without_sub_falls_back_to_ip():
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert user_or_ip(_request(f"Bearer {_token({'exp': exp})}")) == CLIENT_IP
    assert user_or_ip(_request(f"Bearer {_token({'sub': '', 'exp': exp})}")) == CLIENT_IP


# ── Decorator inspection ────────────────────────────────────────────────────

# Route -> expected requests per minute.
_AI_ROUTES = {
    "app.api.routes.chat.chat": 20,
    "app.api.routes.chat.chat_stream": 20,
    "app.api.routes.ingest.ingest_image": 10,
    "app.api.routes.ingest.ingest_voice": 10,
    "app.api.routes.journals.generate_journal_draft": 20,
    "app.api.routes.journals.generate_journal": 20,
    "app.api.routes.journals.autocomplete_journal_notes": 20,
    "app.api.routes.journals.recap_campaign_session": 20,
    "app.api.routes.journals.summarize_session": 20,
    "app.api.routes.session_plans.generate_plan_draft": 20,
    "app.api.routes.settings.test_connection": 20,
    "app.api.routes.settings.evaluate_model": 5,
}


def test_ai_routes_key_on_user_or_ip():
    import app.main  # noqa: F401 — imports every router so decorators register

    route_limits = limiter._route_limits
    for name, per_minute in _AI_ROUTES.items():
        assert name in route_limits, f"{name} has no slowapi limit"
        lims = route_limits[name]
        assert all(lim.key_func is user_or_ip for lim in lims), name
        assert [(lim.limit.amount, lim.limit.get_expiry()) for lim in lims] == [(per_minute, 60)], name


def test_other_limited_routes_keep_ip_key():
    import app.main  # noqa: F401

    others = {n: lims for n, lims in limiter._route_limits.items() if n not in _AI_ROUTES}
    assert any(n.startswith("app.api.routes.auth.") for n in others)
    for name, lims in others.items():
        if name.startswith(("app.api.routes.auth.", "app.api.routes.share.", "app.api.routes.sources.")):
            assert all(lim.key_func is get_remote_address for lim in lims), name


# ── Integration: two users behind one IP ────────────────────────────────────

async def _register(client, promo_code: str) -> dict:
    r = await client.post("/api/auth/register", json={
        "email": f"rl_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "Rate Limit", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _post_non_image(client, headers):
    # A non-image upload is rejected with 415 inside the handler, after the
    # limiter has counted it — so no OCR/LLM work runs.
    return await client.post(
        "/api/ingest/image",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
        headers=headers,
    )


@pytest.mark.asyncio
async def test_two_users_on_one_ip_get_separate_buckets(client, promo_code):
    # The ASGITransport client address is fixed, so both users share an IP.
    headers_a = await _register(client, promo_code)
    headers_b = await _register(client, promo_code)

    for _ in range(10):
        r = await _post_non_image(client, headers_a)
        assert r.status_code == 415, r.text
    for _ in range(10):
        r = await _post_non_image(client, headers_b)
        assert r.status_code == 415, r.text

    r = await _post_non_image(client, headers_a)
    assert r.status_code == 429, r.text
    # B's own bucket filled separately, so B is throttled at its 11th too.
    r = await _post_non_image(client, headers_b)
    assert r.status_code == 429, r.text
