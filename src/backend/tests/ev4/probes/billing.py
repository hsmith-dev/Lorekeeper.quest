"""EV-4 probe for `GET /api/billing/status` (E0-QA.13): the caller's own
access and plan only. Another user's redeemed promo code (a canary) never
shows up, and the answer does not move when another user redeems one.
Checkout, portal, promo redemption (Stripe and the caller's own account)
and the Stripe webhook are exempted in exemptions.yaml.
"""
from __future__ import annotations

import uuid

from tests.ev4.families import assert_counts_and_ranking_unchanged, assert_no_canary
from tests.ev4.fixtures import create_user, mint_canary
from tests.ev4.probes._support import authenticated
from tests.ev4.probes.admin import check_denial
from tests.ev4.registry import ev4_probe

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
