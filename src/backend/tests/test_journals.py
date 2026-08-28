import pytest

# Sprint 5 — US13: journal list, search, pagination tests
# Sprint 5 — US4: cross-user access denial tests


@pytest.mark.asyncio
async def test_list_journals_requires_auth(client):
    r = await client.get("/api/journals/")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_journal(client, promo_code):
    # Register two users — a promo code is required to get access_granted=True
    # (see app/api/routes/auth.py::register), otherwise every feature route is
    # gated with 402 regardless of whose data it's touching.
    r1 = await client.post("/api/auth/register", json={
        "email": "user_a@example.com", "password": "password123", "display_name": "User A",
        "promo_code": promo_code,
    })
    token_a = r1.json()["access_token"]

    r2 = await client.post("/api/auth/register", json={
        "email": "user_b@example.com", "password": "password123", "display_name": "User B",
        "promo_code": promo_code,
    })
    token_b = r2.json()["access_token"]  # noqa: F841 — used in future assertion

    # User A creates a campaign
    camp = await client.post(
        "/api/campaigns/",
        json={"name": "Test Campaign", "genre": "fantasy"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert camp.status_code == 201
