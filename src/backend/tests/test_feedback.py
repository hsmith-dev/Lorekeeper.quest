"""POST /api/feedback/: the campaign_id pointer is kept only for a Campaign
the submitter can reach now (E0-QA.13). Anything else is dropped exactly like
an id that does not exist, and the feedback is still accepted."""
from __future__ import annotations

import uuid

import sqlalchemy as sa

from app.db.models.campaign import Campaign, Genre
from app.db.models.feedback import Feedback
from tests.ev4.fixtures import bearer, create_user, make_member

URL = "/api/feedback/"


async def _campaign(db, owner) -> uuid.UUID:
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name=f"Feedback {cid.hex[:6]}", genre=Genre("fantasy")))
    await db.commit()
    return cid


async def _stored(db, feedback_id: str):
    return (await db.execute(sa.select(Feedback.campaign_id).where(Feedback.id == uuid.UUID(feedback_id)))).scalar_one()


async def _submit(client, user, campaign_id):
    return await client.post(URL, headers=bearer(user),
                             json={"category": "other", "message": "hi", "campaign_id": str(campaign_id)})


async def test_owner_and_member_keep_the_pointer(client, db):
    owner = await create_user(db, "fb_owner")
    cid = await _campaign(db, owner)
    member = await make_member(db, role="player", campaign_id=cid, label="fb_member")
    for user in (owner, member):
        r = await _submit(client, user, cid)
        assert r.status_code == 201, r.text
        assert r.json()["campaign_id"] == str(cid)
        assert await _stored(db, r.json()["id"]) == cid


async def test_missing_campaign_is_201_without_a_pointer(client, db):
    user = await create_user(db, "fb_missing")
    r = await _submit(client, user, uuid.uuid4())
    assert r.status_code == 201, r.text
    assert r.json()["campaign_id"] is None
    assert await _stored(db, r.json()["id"]) is None


async def test_unreachable_campaign_answers_like_a_missing_one(client, db):
    owner = await create_user(db, "fb_other_owner")
    cid = await _campaign(db, owner)
    outsider = await create_user(db, "fb_outsider")
    removed = await make_member(db, role="player", campaign_id=cid, label="fb_removed")
    await db.execute(sa.text("DELETE FROM campaign_members WHERE campaign_id = :c AND user_id = :u"),
                     {"c": cid, "u": removed.id})
    await db.commit()
    for user in (outsider, removed):
        hidden = await _submit(client, user, cid)
        missing = await _submit(client, user, uuid.uuid4())
        assert hidden.status_code == missing.status_code == 201
        strip = lambda b: {k: v for k, v in b.items() if k not in ("id", "created_at")}  # noqa: E731
        assert strip(hidden.json()) == strip(missing.json())
        assert hidden.json()["campaign_id"] is None
        assert await _stored(db, hidden.json()["id"]) is None
