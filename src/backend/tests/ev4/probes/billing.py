"""EV-4 probes for api/routes/billing.py's per-user routes (E0-QA.13).

`GET /api/billing/status`: the caller's own access and plan only. Another
user's redeemed promo code (a canary) never shows up, and the answer does
not move when another user redeems one.

`POST /api/billing/redeem-promo`: a code someone else used up answers
exactly like a code that does not exist, redeeming touches only the
caller's account, and the answer is the caller's own billing status.

Checkout, portal (Stripe, the caller's own customer) and the Stripe webhook
are exempted in exemptions.yaml.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_no_canary
from tests.ev4.fixtures import create_user, mint_canary
from tests.ev4.probes._support import assert_same_answer, authenticated
from tests.ev4.probes.admin import check_denial
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak

NOBODY = uuid.UUID("00000000-0000-4000-8000-00000000e4a3")  # no actor is GM here


async def redeem_for_other(ev4) -> None:
    from app.db.models.promo_code import PromoCode, PromoCodeRedemption

    other = await create_user(ev4.db, "billing_other")
    promo = PromoCode(id=uuid.uuid4(), code=mint_canary("XP", NOBODY).token, redemption_count=1)
    ev4.db.add(promo)
    await ev4.db.flush()
    ev4.db.add(PromoCodeRedemption(promo_code_id=promo.id, user_id=other.id))
    await ev4.db.commit()


@ev4_probe("GET", "/api/billing/status")
async def probe_billing_status(ev4, actor):
    await redeem_for_other(ev4)
    url = "/api/billing/status"
    r = await actor.get(url)
    if not authenticated(actor):
        check_denial(actor, r, f"GET {url}")
        return
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json()["promo_code_used"] is None, r.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: redeem_for_other(ev4))


def _new_code() -> str:
    # Upper case: redemption looks codes up upper-cased.
    return f"EV4-{uuid.uuid4().hex[:12].upper()}"


async def _promo(ev4, *, used_by=None) -> str:
    """A single-use promo code; with `used_by`, that user has used it up."""
    from app.db.models.promo_code import PromoCode, PromoCodeRedemption

    code = _new_code()
    promo = PromoCode(id=uuid.uuid4(), code=code, max_redemptions=1, redemption_count=1 if used_by else 0)
    ev4.db.add(promo)
    await ev4.db.flush()
    if used_by is not None:
        ev4.db.add(PromoCodeRedemption(promo_code_id=promo.id, user_id=used_by))
    await ev4.db.commit()
    return code


@ev4_probe("POST", "/api/billing/redeem-promo")
async def probe_redeem_promo(ev4, actor):
    from app.db.models.promo_code import PromoCode, PromoCodeRedemption

    other = await create_user(ev4.db, "promo_other")
    theirs = await _promo(ev4, used_by=other.id)
    url = "/api/billing/redeem-promo"
    r_used = await actor.post(url, json={"code": theirs})
    r_missing = await actor.post(url, json={"code": _new_code()})
    assert_same_answer(actor, r_used, r_missing, "used-up promo code")
    if not authenticated(actor):
        check_denial(actor, r_used, f"POST {url}")
        return
    mine = await _promo(ev4)
    r = await actor.post(url, json={"code": mine})
    assert_no_canary(actor, r)
    assert r.status_code == 200 and r.json()["promo_code_used"] == mine, r.text
    note_family_call()
    rows = (await ev4.db.execute(
        sa.select(PromoCodeRedemption.user_id, PromoCode.code, PromoCode.redemption_count)
        .join(PromoCode, PromoCode.id == PromoCodeRedemption.promo_code_id)
        .where(PromoCodeRedemption.user_id.in_([other.id, actor.user_id]))
    )).all()
    want = sorted([(str(other.id), theirs, 1), (str(actor.user_id), mine, 1)])
    if sorted((str(u), c, n) for u, c, n in rows) != want:
        record_leak(f"EV-4 leak: {actor.name}'s promo redemption touched another user's", [repr(rows)[:300]])
