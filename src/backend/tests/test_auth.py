import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.user import User


@pytest.mark.asyncio
async def test_register_and_login(client):
    r = await client.post("/api/auth/register", json={
        "email": "test@example.com", "password": "password123", "display_name": "Tester"
    })
    assert r.status_code == 201
    assert "access_token" in r.json()

    r2 = await client.post("/api/auth/login", json={
        "email": "test@example.com", "password": "password123"
    })
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "password123", "display_name": "A"}
    await client.post("/api/auth/register", json=payload)
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_wrong_password_increments_failed_attempts(client, db):
    await client.post("/api/auth/register", json={
        "email": "lockout@example.com", "password": "password123", "display_name": "L"
    })

    r = await client.post("/api/auth/login", json={"email": "lockout@example.com", "password": "wrongpass"})
    assert r.status_code == 401

    result = await db.execute(select(User).where(User.email == "lockout@example.com"))
    user = result.scalar_one()
    assert user.failed_login_attempts == 1

    # A subsequent correct login clears the counter rather than leaving it to
    # decay/expire — see auth.py's login().
    r2 = await client.post("/api/auth/login", json={"email": "lockout@example.com", "password": "password123"})
    assert r2.status_code == 200
    await db.refresh(user)
    assert user.failed_login_attempts == 0


@pytest.mark.asyncio
async def test_locked_account_rejects_correct_password(client, db):
    await client.post("/api/auth/register", json={
        "email": "locked@example.com", "password": "password123", "display_name": "L2"
    })
    result = await db.execute(select(User).where(User.email == "locked@example.com"))
    user = result.scalar_one()
    # Simulate having already tripped the lockout threshold, rather than
    # sending 10 real failed logins through the endpoint's own rate limiter.
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    await db.commit()

    r = await client.post("/api/auth/login", json={"email": "locked@example.com", "password": "password123"})
    assert r.status_code == 403
    assert "Too many failed login attempts" in r.json()["detail"]


@pytest.mark.asyncio
async def test_password_reset_invalidates_existing_tokens(client, db):
    r = await client.post("/api/auth/register", json={
        "email": "resetme@example.com", "password": "password123", "display_name": "R"
    })
    old_token = r.json()["access_token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me.status_code == 200

    result = await db.execute(select(User).where(User.email == "resetme@example.com"))
    user = result.scalar_one()
    raw_token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=60),
    ))
    await db.commit()

    r2 = await client.post("/api/auth/reset-password", json={"token": raw_token, "new_password": "newpassword456"})
    assert r2.status_code == 200

    # The old token was issued before this reset — it must stop working
    # immediately rather than riding out its 24h expiry. See
    # User.password_changed_at / get_current_user.
    me2 = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert me2.status_code == 401

    r3 = await client.post("/api/auth/login", json={"email": "resetme@example.com", "password": "newpassword456"})
    assert r3.status_code == 200
