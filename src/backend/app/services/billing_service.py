"""Stripe subscription billing: checkout, customer portal, webhook sync, and a
rough token-usage estimate for metering hosted-LLM access. Every state change
funnels through here so app/api/routes/billing.py stays a thin HTTP shell."""

import logging
import secrets
import string
import uuid
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.services.email_service import send_welcome_email

logger = logging.getLogger(__name__)

# Pinned explicitly rather than left to drift with whatever version happens to
# be the account's Dashboard default (which can change independently of a
# deploy) or whatever the installed SDK's bundled default is. Bump deliberately
# alongside the `stripe` package version in requirements.txt, not silently.
_STRIPE_API_VERSION = "2026-07-29.dahlia"


class BillingNotConfigured(Exception):
    """Stripe env vars aren't fully set on this server yet."""


PLANS = ("byok", "hosted")


def _require_stripe_configured() -> None:
    s = get_settings()
    if not s.stripe_secret_key or not s.stripe_price_id_byok or not s.stripe_price_id_hosted:
        raise BillingNotConfigured(
            "Stripe isn't configured on this server yet — set STRIPE_SECRET_KEY, "
            "STRIPE_PRICE_ID_BYOK, and STRIPE_PRICE_ID_HOSTED. Running Lorekeeper as a "
            "paid service requires a commercial license: hello@harrisonsmith.ai."
        )
    stripe.api_key = s.stripe_secret_key
    stripe.api_version = _STRIPE_API_VERSION


def _integration_identifier(flow: str) -> str:
    """A per-call label for Dashboard tracking/comparison of checkout flows —
    stable prefix plus an 8-random-letter suffix, per Stripe's own guidance
    for the `integration_identifier` param (API version 2026-03-25.dahlia+)."""
    suffix = "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
    return f"lorekeeper_{flow}_{suffix}"


def _price_id_for_plan(plan: str) -> str | None:
    s = get_settings()
    return {"byok": s.stripe_price_id_byok, "hosted": s.stripe_price_id_hosted}.get(plan)


def _plan_from_price_id(price_id: str | None) -> str | None:
    s = get_settings()
    if price_id and price_id == s.stripe_price_id_hosted:
        return "hosted"
    if price_id and price_id == s.stripe_price_id_byok:
        return "byok"
    return None


def _plan_from_subscription_obj(obj: dict) -> str | None:
    """The Stripe subscription's own line item price is the source of truth
    for which plan a customer is on — more reliable than trusting whatever
    plan checkout was merely *started* with, and the only source available at
    all for e.g. a plan change made through the Customer Portal rather than a
    fresh Checkout Session."""
    items = (obj.get("items") or {}).get("data") or []
    if not items:
        return None
    price = (items[0] or {}).get("price") or {}
    return _plan_from_price_id(price.get("id"))


async def _get_or_create_subscription_row(db: AsyncSession, user: User) -> Subscription:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = Subscription(
            user_id=user.id,
            status="incomplete",
            tokens_included_per_period=get_settings().subscription_monthly_token_quota,
        )
        db.add(sub)
        await db.flush()
    return sub


async def create_checkout_session(db: AsyncSession, user: User, plan: str) -> str:
    """Create (or reuse) a Stripe customer for this user and start a Checkout
    Session in subscription mode for the given plan ("byok" $5/mo or "hosted"
    $15/mo — see PLANS). Returns the hosted Checkout URL to redirect the
    browser to — we never touch card details ourselves."""
    if plan not in PLANS:
        raise ValueError(f"Unknown plan '{plan}'. Expected one of {PLANS}.")
    _require_stripe_configured()
    s = get_settings()
    price_id = _price_id_for_plan(plan)
    sub = await _get_or_create_subscription_row(db, user)

    if sub.is_active() and sub.plan and sub.plan != plan:
        # Already on the other paid tier — a second Checkout Session would
        # create a *second* Stripe subscription for the same customer rather
        # than switching the existing one. Plan switching belongs in the
        # Customer Portal (see docs/PAYMENT_PROCESSOR_SETUP.md — enable
        # "update subscription" with both Products listed as options there).
        raise ValueError(
            "You already have an active subscription — use Manage Subscription "
            "in Settings → Billing to switch plans, rather than starting a new checkout."
        )

    if sub.stripe_customer_id:
        customer_id = sub.stripe_customer_id
    else:
        customer = stripe.Customer.create(
            email=user.email, name=user.display_name, metadata={"user_id": str(user.id)}
        )
        customer_id = customer["id"]
        sub.stripe_customer_id = customer_id
        await db.commit()

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(user.id),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{s.frontend_url}/settings?checkout=success",
        cancel_url=f"{s.frontend_url}/subscribe?checkout=cancelled",
        # plan is stashed here so checkout.session.completed can set it
        # immediately without waiting on a separate customer.subscription.*
        # event; _plan_from_subscription_obj (driven off the actual Stripe
        # price ID) is still the source of truth for every event afterward.
        metadata={"user_id": str(user.id), "plan": plan},
        integration_identifier=_integration_identifier("checkout"),
        # No payment_method_types — deliberately omitted so Stripe determines
        # eligible payment methods dynamically from the Dashboard config
        # instead of hardcoding to card-only.
    )
    return session["url"]


async def create_portal_session(db: AsyncSession, user: User) -> str:
    """Stripe-hosted page where a subscriber manages/cancels their own plan —
    no custom billing-management UI needed on our side."""
    _require_stripe_configured()
    s = get_settings()
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub is None or not sub.stripe_customer_id:
        raise ValueError("No billing account yet — subscribe first.")
    portal = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{s.frontend_url}/settings",
    )
    return portal["url"]


async def admin_cancel_subscription(sub: Subscription | None) -> None:
    """Best-effort immediate cancellation, used by admin account deletion
    (app/api/routes/admin.py) so a deleted account doesn't keep getting
    billed. Deliberately swallows errors rather than raising — a Stripe API
    hiccup or an already-canceled subscription must never block the account
    deletion itself; worst case, the admin double-checks the Stripe
    Dashboard for that customer afterward."""
    if sub is None or not sub.stripe_subscription_id:
        return
    try:
        _require_stripe_configured()
        stripe.Subscription.delete(sub.stripe_subscription_id)
    except Exception:
        logger.exception("Failed to cancel Stripe subscription %s during account deletion", sub.stripe_subscription_id)


async def apply_promo_plan(db: AsyncSession, user: User, promo: "PromoCode") -> None:
    """Give a promo-redeeming user a Subscription row matching the code's
    granted tier (see PromoCode.grants_plan), so get_user_llm_config's
    hosted-vs-byok routing — which reads Subscription.plan/is_active(),
    identically for a real Stripe subscription or this synthetic one — works
    the same way regardless of which path granted access. No
    stripe_subscription_id/stripe_customer_id, since no real billing is
    involved; if this user later actually subscribes via Stripe, the webhook
    handler updates this same row (found by user_id) rather than creating a
    second one."""
    sub = await _get_or_create_subscription_row(db, user)
    sub.plan = promo.grants_plan
    sub.status = "active"
    sub.tokens_included_per_period = (
        get_settings().subscription_monthly_token_quota if promo.grants_plan == "hosted" else 0
    )
    if sub.period_started_at is None:
        sub.period_started_at = datetime.now(timezone.utc)


async def admin_set_access(db: AsyncSession, user: User, access_granted: bool, plan: str | None) -> None:
    """Direct admin override of a user's access/tier (see
    app/api/routes/admin.py's PATCH /users/{id}/access) — bypasses promo
    codes and Stripe entirely. Same synthetic-Subscription-row approach as
    apply_promo_plan, so hosted_model_eligible() etc. work identically
    regardless of how access was granted."""
    user.access_granted = access_granted
    user.access_source = "grandfathered" if access_granted else None
    if plan in PLANS:
        sub = await _get_or_create_subscription_row(db, user)
        sub.plan = plan
        sub.status = "active" if access_granted else sub.status
        sub.tokens_included_per_period = (
            get_settings().subscription_monthly_token_quota if plan == "hosted" else 0
        )
        if sub.period_started_at is None:
            sub.period_started_at = datetime.now(timezone.utc)


async def redeem_promo_code(db: AsyncSession, user: User, code: str) -> None:
    """Validate and redeem a promo code for `user`, granting access on success.
    Raises ValueError (→ caller returns 400) if the code doesn't exist, is
    inactive/expired/exhausted, or this user already redeemed one. Shared by
    registration (app/api/routes/auth.py) and post-registration redemption
    (app/api/routes/billing.py) so both paths agree on what "valid" means."""
    from app.db.models.promo_code import PromoCode, PromoCodeRedemption

    existing = (
        await db.execute(select(PromoCodeRedemption).where(PromoCodeRedemption.user_id == user.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("You've already redeemed a promo code.")

    result = await db.execute(select(PromoCode).where(PromoCode.code == code.strip().upper()))
    promo = result.scalar_one_or_none()
    if promo is None or not promo.is_redeemable():
        raise ValueError("That promo code isn't valid or has expired.")

    db.add(PromoCodeRedemption(promo_code_id=promo.id, user_id=user.id))
    promo.redemption_count += 1
    user.access_granted = True
    user.access_source = "promo"
    await apply_promo_plan(db, user, promo)
    await db.commit()


async def _recompute_access(db: AsyncSession, user: User, sub: Subscription) -> None:
    """access_granted = active subscription OR a redeemed promo code —
    recomputed rather than blindly set, so a lapsed subscription doesn't strip
    access from someone who separately holds a valid promo redemption."""
    from app.db.models.promo_code import PromoCodeRedemption

    has_promo = (
        await db.execute(select(PromoCodeRedemption).where(PromoCodeRedemption.user_id == user.id))
    ).scalar_one_or_none() is not None

    if sub.is_active():
        user.access_granted = True
        user.access_source = "subscription"
    elif has_promo:
        user.access_granted = True
        user.access_source = "promo"
    else:
        user.access_granted = False
        user.access_source = None


async def handle_webhook_event(db: AsyncSession, payload: bytes, sig_header: str) -> None:
    """Verify and apply a Stripe webhook event. Raises ValueError on a bad
    signature (→ 400, so Stripe knows to stop retrying that specific delivery)."""
    _require_stripe_configured()
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise BillingNotConfigured("STRIPE_WEBHOOK_SECRET is not set.")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
    except Exception as exc:  # signature mismatch or malformed payload
        raise ValueError(f"Invalid Stripe webhook: {exc}") from exc

    etype = event["type"]
    # .to_dict() is deliberate, not cosmetic: stripe-python's StripeObject
    # supports __getitem__ (obj["x"]) and __contains__ ("x" in obj) but NOT
    # .get() — StripeObject.__getattr__ falls through to self[name], so
    # obj.get("x") is interpreted as "look up the dict key 'get'" and raises
    # AttributeError, not "call the dict method get". Found by actually
    # POSTing signed webhook events at this handler, not by reading the code —
    # every .get() call below on the raw StripeObject would have thrown a 500
    # on every single real webhook delivery.
    obj = event["data"]["object"].to_dict()
    logger.info("Stripe webhook received: %s (event %s)", etype, event["id"])

    if etype == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
        if not user_id:
            return
        user = await db.get(User, uuid.UUID(user_id))
        if not user:
            return
        sub = await _get_or_create_subscription_row(db, user)
        sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
        sub.stripe_subscription_id = obj.get("subscription")
        sub.status = "active"
        sub.period_started_at = datetime.now(timezone.utc)
        # Metadata plan is the immediate signal (set at checkout creation);
        # customer.subscription.created/updated will confirm it from the
        # actual price shortly after and is the source of truth if they ever
        # disagree.
        plan = (obj.get("metadata") or {}).get("plan")
        if plan in PLANS:
            sub.plan = plan
            sub.tokens_included_per_period = (
                get_settings().subscription_monthly_token_quota if plan == "hosted" else 0
            )
        await _recompute_access(db, user, sub)
        await db.commit()
        if plan in PLANS:
            # Best-effort, same as the registration welcome email — a broken
            # email integration must never fail webhook processing (Stripe
            # would just retry the same event, and this isn't idempotent-safe
            # to skip on retry since we only get here once per checkout).
            await send_welcome_email(user.display_name, user.email, plan)

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        stripe_sub_id = obj.get("id")
        result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id))
        sub = result.scalar_one_or_none()
        if sub is None:
            result = await db.execute(
                select(Subscription).where(Subscription.stripe_customer_id == obj.get("customer"))
            )
            sub = result.scalar_one_or_none()
            if sub is None:
                return
            sub.stripe_subscription_id = stripe_sub_id
        sub.status = obj.get("status", sub.status)
        period_end = obj.get("current_period_end")
        if period_end:
            sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)
        # The subscription's actual price is authoritative — covers plan
        # changes made through the Customer Portal, not just fresh checkouts.
        # Mid-period plan changes don't reset tokens_used_current_period here
        # (only invoice.payment_succeeded does) — a small simplification that
        # self-corrects at the next billing period.
        plan = _plan_from_subscription_obj(obj)
        if plan and plan != sub.plan:
            sub.plan = plan
            sub.tokens_included_per_period = (
                get_settings().subscription_monthly_token_quota if plan == "hosted" else 0
            )
        user = await db.get(User, sub.user_id)
        if user:
            await _recompute_access(db, user, sub)
        await db.commit()

    elif etype == "customer.subscription.deleted":
        result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == obj.get("id")))
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        sub.status = "canceled"
        user = await db.get(User, sub.user_id)
        if user:
            await _recompute_access(db, user, sub)
        await db.commit()

    elif etype == "invoice.payment_succeeded":
        result = await db.execute(select(Subscription).where(Subscription.stripe_customer_id == obj.get("customer")))
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        # New billing period — reset the usage meter.
        sub.tokens_used_current_period = 0
        sub.period_started_at = datetime.now(timezone.utc)
        sub.status = "active"
        user = await db.get(User, sub.user_id)
        if user:
            await _recompute_access(db, user, sub)
        await db.commit()

    elif etype == "invoice.payment_failed":
        result = await db.execute(select(Subscription).where(Subscription.stripe_customer_id == obj.get("customer")))
        sub = result.scalar_one_or_none()
        if sub is None:
            return
        # Grace period — Subscription.is_active() still returns True for
        # "past_due", so the subscriber isn't cut off over one bounced charge.
        # Full loss of access waits for Stripe to actually cancel the subscription.
        sub.status = "past_due"
        await db.commit()


def estimate_tokens(*texts: str) -> int:
    """Rough token estimate (~4 characters/token, the commonly-cited average for
    English GPT-family tokenizers) used to meter hosted-model usage against a
    subscriber's monthly quota. This is an approximation, not the provider's
    real tokenizer output — Ollama's OpenAI-compatible endpoint doesn't reliably
    report `usage` the way OpenAI's does, so exact counts aren't available for
    the hosted model without extra plumbing. Good enough to catch runaway
    usage; swap in real `usage.total_tokens` if this proves too imprecise."""
    return max(1, sum(len(t) for t in texts) // 4)


async def record_hosted_usage(db: AsyncSession, user: User, *texts: str) -> None:
    """Call after a hosted-LLM completion for a subscriber — pass whatever text
    changed hands (prompt and/or response; route handlers generally only have
    the response text handy, which is fine, see estimate_tokens). No-op if the
    user has no subscription row: BYO-key usage never counts against a quota,
    and this should only ever be called when
    app.services.llm_provider.is_hosted_default(config) is True."""
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if sub is None:
        return
    sub.tokens_used_current_period += estimate_tokens(*texts)
    await db.commit()
