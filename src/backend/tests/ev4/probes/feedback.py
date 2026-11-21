"""EV-4 probes for api/routes/feedback.py (E0-QA.13).

Submitting is open to any signed-in account; the inbox and a feedback
item's Campaign context are admin-only (`require_admin`), so they must give
the uniform admin denial (probes/admin.py) whatever feedback id is asked
for: another user's feedback, whose context holds canaries, answers exactly
like a missing id.

Submit: the `campaign_id` pointer is kept only for a Campaign the submitter
can reach; a Campaign they cannot reach is dropped exactly like a missing
one (it used to answer 201 for a hidden id and fail the foreign key for a
missing one, an existence oracle).
"""
from __future__ import annotations

import uuid

from tests.ev4.families import assert_hidden_equals_missing, assert_no_canary
from tests.ev4.fixtures import create_user, mint_canary
from tests.ev4.probes._support import MISSING, assert_same_answer, authenticated, outsider, row_count
from tests.ev4.probes.admin import check_denial, uniform_denial
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak


async def _others_feedback(ev4) -> tuple[uuid.UUID, uuid.UUID]:
    """Feedback by another user (canary message) pointing at a seeded
    Campaign none of the actors may see. Returns (feedback id, campaign id)."""
    from app.db.models.feedback import Feedback

    hidden = await outsider(ev4)
    other = await create_user(ev4.db, "feedback_other")
    fb = Feedback(id=uuid.uuid4(), user_id=other.id, campaign_id=hidden.campaign_id,
                  message=mint_canary("XFEEDBACK", hidden.campaign_id).token)
    ev4.db.add(fb)
    await ev4.db.commit()
    return fb.id, hidden.campaign_id


def _stable(body: dict) -> dict:
    return {k: v for k, v in body.items() if k not in ("id", "created_at")}


async def _former_member_campaign(ev4, actor) -> uuid.UUID:
    """A seeded Campaign the actor was a Player in and has been removed from
    (the case the old "still submittable" comment was about)."""
    import sqlalchemy as sa

    from app.db.models.campaign_member import CampaignMember
    from app.db.models.user import User

    left = await outsider(ev4)
    await ev4.make_member("player", campaign_id=left.campaign_id, user=await ev4.db.get(User, actor.user_id))
    await ev4.db.execute(sa.delete(CampaignMember).where(CampaignMember.campaign_id == left.campaign_id,
                                                         CampaignMember.user_id == actor.user_id))
    await ev4.db.commit()
    return left.campaign_id


def _same_submit(actor, hidden, missing, label: str) -> list[str]:
    """Hidden vs missing for two submits whose bodies differ only in the new
    row's id and timestamp: same status, same body otherwise, same headers."""
    from tests.ev4.families import _headers

    diffs = []
    if hidden.status_code != missing.status_code:
        diffs.append(f"{label} status: hidden {hidden.status_code} vs missing {missing.status_code}")
    elif hidden.status_code < 400 and _stable(hidden.json()) != _stable(missing.json()):
        diffs.append(f"{label} body: hidden {hidden.text[:200]!r} vs missing {missing.text[:200]!r}")
    skip = frozenset({"content-length"})
    if _headers(hidden, skip) != _headers(missing, skip):
        diffs.append(f"{label} headers differ")
    return diffs


@ev4_probe("POST", "/api/feedback/")
async def probe_submit_feedback(ev4, actor):
    from app.db.models.feedback import Feedback

    _, hidden_cid = await _others_feedback(ev4)
    body = {"category": "other", "message": f"The recap missed the inn ({uuid.uuid4().hex[:8]})."}
    r_hidden = await actor.post("/api/feedback/", json={**body, "campaign_id": str(hidden_cid)})
    r_missing = await actor.post("/api/feedback/", json={**body, "campaign_id": MISSING})
    if not authenticated(actor):
        check_denial(actor, r_hidden, "POST /api/feedback/")
        assert_same_answer(actor, r_hidden, r_missing, "feedback Campaign")
        assert await row_count(ev4, Feedback, Feedback.message == body["message"]) == 0
        return
    note_family_call()
    assert_no_canary(actor, r_hidden)
    assert_no_canary(actor, r_missing)
    diffs = _same_submit(actor, r_hidden, r_missing, "never a Member")
    left_cid = await _former_member_campaign(ev4, actor)
    r_left = await actor.post("/api/feedback/", json={**body, "campaign_id": str(left_cid)})
    assert_no_canary(actor, r_left)
    diffs += _same_submit(actor, r_left, await actor.post("/api/feedback/", json={**body, "campaign_id": MISSING}),
                          "removed Member")
    for cid in (hidden_cid, left_cid):
        if await row_count(ev4, Feedback, Feedback.campaign_id == cid, Feedback.user_id == actor.user_id):
            diffs.append(f"the unreachable Campaign {cid} was stored as the feedback's pointer")
    if diffs:
        record_leak(f"EV-4 leak: {actor.name} can tell a hidden Campaign from a missing one via feedback", diffs)
    assert r_hidden.status_code == 201 and r_hidden.json()["campaign_id"] is None, r_hidden.text
    # A Campaign the actor belongs to keeps its pointer (non-vacuous).
    a = str(ev4.a.campaign_id)
    r = await actor.post("/api/feedback/", json={**body, "campaign_id": a})
    assert_no_canary(actor, r)
    assert r.status_code == 201 and r.json()["campaign_id"] == a, r.text


@ev4_probe("GET", "/api/feedback/")
async def probe_list_feedback(ev4, actor):
    await _others_feedback(ev4)
    reference = await uniform_denial(actor)
    r = await actor.get("/api/feedback/")
    check_denial(actor, r, "GET /api/feedback/")
    assert_same_answer(actor, r, reference, "the feedback inbox vs the uniform admin denial")


@ev4_probe("GET", "/api/feedback/{feedback_id}/context")
async def probe_feedback_context(ev4, actor):
    feedback_id, _ = await _others_feedback(ev4)
    reference = await uniform_denial(actor)
    url = f"/api/feedback/{feedback_id}/context"
    await assert_hidden_equals_missing(actor, url, f"/api/feedback/{MISSING}/context")
    r = await actor.get(url)
    check_denial(actor, r, url)
    assert_same_answer(actor, r, reference, "feedback context vs the uniform admin denial")
