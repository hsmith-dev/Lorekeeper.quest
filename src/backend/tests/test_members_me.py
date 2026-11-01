"""E0-Access.2: GET /api/campaigns/{campaign_id}/me, the caller's own Role."""
from __future__ import annotations

import uuid

import pytest

from app.db.models.campaign import Campaign, Genre
from tests.ev4.fixtures import bearer, create_user, make_member

RANDOM = "00000000-0000-4000-8000-000000000000"


async def _campaign(db, owner) -> uuid.UUID:
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name="Me", genre=Genre.fantasy))
    await db.commit()
    return cid


@pytest.mark.parametrize("who, role, is_owner, display", [
    ("owner", "gm", True, "Owner"),
    ("co_gm", "gm", False, "Co-GM"),
    ("player", "player", False, "Player"),
])
async def test_me_per_role(client, db, who, role, is_owner, display):
    owner = await create_user(db, "me_owner")
    cid = await _campaign(db, owner)
    user = owner if who == "owner" else await make_member(db, role=who, campaign_id=cid, label=f"me_{who}")
    r = await client.get(f"/api/campaigns/{cid}/me", headers=bearer(user))
    assert r.status_code == 200, r.text
    assert r.json() == {"campaign_id": str(cid), "role": role, "is_owner": is_owner, "display_role": display}


async def test_me_is_per_campaign(client, db):
    """Owner of B, Player in A: each answer is about that Campaign only."""
    a_owner = await create_user(db, "me_a_owner")
    a = await _campaign(db, a_owner)
    user = await create_user(db, "me_cross")
    b = await _campaign(db, user)
    await make_member(db, role="player", campaign_id=a, user=user)
    ra = await client.get(f"/api/campaigns/{a}/me", headers=bearer(user))
    rb = await client.get(f"/api/campaigns/{b}/me", headers=bearer(user))
    assert (ra.json()["role"], ra.json()["display_role"]) == ("player", "Player")
    assert (rb.json()["role"], rb.json()["display_role"]) == ("gm", "Owner")


async def test_me_non_member_equals_missing(client, db):
    owner = await create_user(db, "me_owner2")
    cid = await _campaign(db, owner)
    stranger = await create_user(db, "me_stranger")
    hidden = await client.get(f"/api/campaigns/{cid}/me", headers=bearer(stranger))
    missing = await client.get(f"/api/campaigns/{RANDOM}/me", headers=bearer(stranger))
    junk = await client.get("/api/campaigns/not-a-uuid/me", headers=bearer(stranger))
    assert hidden.status_code == missing.status_code == junk.status_code == 404
    assert hidden.json() == {"detail": "Not found"}
    assert hidden.content == missing.content == junk.content


async def test_me_needs_auth(client, db):
    owner = await create_user(db, "me_owner3")
    cid = await _campaign(db, owner)
    r = await client.get(f"/api/campaigns/{cid}/me")
    assert r.status_code in (401, 403)
