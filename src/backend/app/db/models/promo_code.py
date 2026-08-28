import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class PromoCode(Base, TimestampMixin):
    """A code that lets someone create an account without subscribing. Minted by
    an operator (see scripts/create_promo_code.py — there's no admin UI for this
    yet), redeemed once per user at registration. max_redemptions=None means
    unlimited; expires_at=None means it never expires."""

    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redemption_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # operator-facing label, e.g. "beta testers"
    # "byok" | "hosted" — which tier redeeming this code grants, mirroring the
    # two real Stripe plans (see app/services/billing_service.py's PLANS).
    # Redemption creates a synthetic Subscription row with this plan and
    # status="active" but no stripe_subscription_id — same is_active()/
    # hosted_model_eligible() checks work identically to a paid subscription,
    # just with no real billing behind it.
    grants_plan: Mapped[str] = mapped_column(String(20), nullable=False, default="byok")

    def is_redeemable(self) -> bool:
        if not self.active:
            return False
        if self.expires_at is not None:
            from datetime import timezone as _tz
            now = datetime.now(_tz.utc)
            expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=_tz.utc)
            if expires < now:
                return False
        if self.max_redemptions is not None and self.redemption_count >= self.max_redemptions:
            return False
        return True


class PromoCodeRedemption(Base, TimestampMixin):
    """Audit trail: which user redeemed which code, and when. One redemption per
    user — a user's free access always traces back to exactly one row here."""

    __tablename__ = "promo_code_redemptions"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    promo_code: Mapped["PromoCode"] = relationship()
