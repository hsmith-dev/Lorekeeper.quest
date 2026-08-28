from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.db.models.promo_code import PromoCode, PromoCodeRedemption
from app.api.deps import get_current_user
from app.schemas.billing import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    BillingStatusResponse,
    RedeemPromoRequest,
)
from app.services import billing_service
from app.core.config import get_settings

router = APIRouter()

# NOTE: every route here uses the plain get_current_user (auth only, no access
# gate) — checkout/portal/status must work for a user who doesn't have access
# yet, since starting checkout is how they GET access. The webhook route has
# no user auth at all; Stripe authenticates itself via the signature header.


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    body: CheckoutRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CheckoutResponse:
    try:
        url = await billing_service.create_checkout_session(db, user, body.plan)
    except billing_service.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return CheckoutResponse(checkout_url=url)


@router.post("/portal", response_model=PortalResponse)
async def portal(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> PortalResponse:
    try:
        url = await billing_service.create_portal_session(db, user)
    except billing_service.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PortalResponse(portal_url=url)


@router.post("/redeem-promo", response_model=BillingStatusResponse)
async def redeem_promo(
    body: RedeemPromoRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BillingStatusResponse:
    """For an account that registered without a promo code (so is still
    gated) and got one later — e.g. a beta invite that arrived after signup.
    Registration itself validates promo codes inline (app/api/routes/auth.py)
    since that path also has to decide the account's *initial* state; this is
    the equivalent for an account that already exists."""
    try:
        await billing_service.redeem_promo_code(db, user, body.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await billing_status(user=user, db=db)


@router.get("/status", response_model=BillingStatusResponse)
async def billing_status(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BillingStatusResponse:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    s = get_settings()

    promo_result = await db.execute(
        select(PromoCode.code)
        .join(PromoCodeRedemption, PromoCodeRedemption.promo_code_id == PromoCode.id)
        .where(PromoCodeRedemption.user_id == user.id)
    )
    promo_code_used = promo_result.scalar_one_or_none()

    return BillingStatusResponse(
        access_granted=user.access_granted,
        access_source=user.access_source,
        subscription_status=sub.status if sub else None,
        plan=sub.plan if sub else None,
        tokens_used_current_period=sub.tokens_used_current_period if sub else None,
        tokens_included_per_period=sub.tokens_included_per_period if sub else None,
        current_period_end=sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        stripe_configured=bool(s.stripe_secret_key and s.stripe_price_id_byok and s.stripe_price_id_hosted),
        promo_code_used=promo_code_used,
    )


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        await billing_service.handle_webhook_event(db, payload, sig_header)
    except billing_service.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"received": True}
