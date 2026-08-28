from typing import Literal
from pydantic import BaseModel, Field


class CheckoutRequest(BaseModel):
    plan: Literal["byok", "hosted"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class RedeemPromoRequest(BaseModel):
    code: str = Field(..., max_length=50)


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    access_granted: bool
    access_source: str | None
    subscription_status: str | None
    plan: str | None
    tokens_used_current_period: int | None
    tokens_included_per_period: int | None
    current_period_end: str | None
    stripe_configured: bool
    promo_code_used: str | None
