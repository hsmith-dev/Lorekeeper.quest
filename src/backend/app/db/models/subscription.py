import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class Subscription(Base, TimestampMixin):
    """One row per user, created the first time they start a Stripe Checkout
    session (status starts 'incomplete') and kept in sync by the Stripe webhook
    handler from then on (app/services/billing_service.py). tokens_used_current
    _period is a rough char-count-based estimate (see billing_service's
    estimate_tokens docstring for why exact provider usage isn't used), reset to
    0 on each successful invoice payment. tokens_included_per_period is copied
    from settings.subscription_monthly_token_quota at creation time so a plan
    change later doesn't retroactively change what an existing period promised.

    Two paid tiers, distinguished by `plan` (which Stripe Price the customer is
    on — see billing_service._plan_from_price_id, the single place a Stripe
    price ID maps to a plan name):
      - "byok" ($5/mo): full app access, bring your own OpenAI/Anthropic/
        Gemini/custom key — no hosted-model access regardless of quota.
      - "hosted" ($15/mo): full app access, PLUS metered access to the
        platform's own hosted model when no personal key is configured.
    Both grant access_granted=True identically (see _recompute_access) — plan
    only affects get_user_llm_config's hosted-vs-BYO-key routing decision."""

    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    # "incomplete" | "active" | "past_due" | "canceled" | "unpaid" — mirrors Stripe's
    # subscription status vocabulary directly so webhook handling is a passthrough.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="incomplete")

    # "byok" | "hosted" | None (not yet determined — e.g. row exists but
    # checkout hasn't completed/no webhook has told us which price yet).
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)

    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tokens_used_current_period: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_included_per_period: Mapped[int] = mapped_column(Integer, nullable=False, default=1_000_000)

    user: Mapped["User"] = relationship(back_populates="subscription")

    def is_active(self) -> bool:
        """'active' and 'past_due' both keep access — past_due is Stripe's grace
        period after a failed card charge before it gives up and cancels; kicking
        someone out on the first missed payment (rather than at final cancellation)
        would be a harsh, surprising UX for a transient card issue. 'trialing'
        is included too so a free-trial Price (if one's ever configured on the
        Stripe side — nothing here requires it) grants access during the trial
        without any other code changes."""
        return self.status in ("active", "past_due", "trialing")

    def has_quota_remaining(self) -> bool:
        return self.tokens_used_current_period < self.tokens_included_per_period

    def hosted_model_eligible(self) -> bool:
        """The $15/mo tier is the only one that ever gets the platform's own
        model — the $5/mo tier is deliberately cheaper because it costs the
        platform nothing to serve (the user's own API key pays for their own
        usage)."""
        return self.plan == "hosted" and self.is_active()
