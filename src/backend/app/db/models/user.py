import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Account gating: True the moment a promo code is redeemed OR a subscription
    # becomes active/past_due (see app/api/deps.py::require_active_account, the
    # single place this is enforced). Denormalized onto User rather than derived
    # on every request via a join, since it's checked on nearly every request.
    # access_source records *why* — "promo" | "subscription" | "grandfathered"
    # (existing accounts when this system shipped) — for support/debugging only,
    # not used for any access decision itself.
    access_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    access_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Admin-imposed suspension (see app/api/routes/admin.py) — distinct from
    # access_granted, which is purely billing-derived and gets recomputed by
    # the Stripe webhook handler on every subscription event. A suspension
    # must survive that recomputation (an admin suspending an abusive but
    # still-paying subscriber shouldn't be silently undone by their next
    # invoice), so it's checked separately and first, in get_current_user —
    # blocks everything, not just feature routes, unlike access_granted.
    is_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suspended_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # DB-backed admin flag (see app/api/deps.py::require_admin) — the
    # original single ADMIN_EMAIL env var only ever supported one operator
    # and required a redeploy to change. This is the real mechanism now;
    # ADMIN_EMAIL is kept only as a bootstrap fallback so the first admin
    # always has a way in even before anyone has is_admin=True.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Drives the auto-launched onboarding tour (see app/api/routes/auth.py's
    # POST /tutorial-complete and the frontend's TourProvider) — False for a
    # newly registered account so the frontend prompts them on first login;
    # the migration that added this column backfills every *existing* user
    # to True (server_default=true) so nobody already using the app suddenly
    # gets interrupted by a tour of features they already know. The ORM-level
    # default=False only applies to new INSERTs going forward.
    has_completed_tutorial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Session-invalidation watermark: NULL until the password is ever reset.
    # A JWT's "iat" claim is compared against this in get_current_user — a
    # token issued before the last password reset is rejected, so resetting
    # your password (e.g. because a token leaked) actually kicks out anyone
    # holding an older token instead of leaving it valid until its 24h
    # natural expiry. Left NULL by default (not backfilled to "now" for
    # existing users) so this migration can't retroactively log anyone out.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-account brute-force lockout — complements the per-IP rate limits in
    # nginx/slowapi, which a distributed credential-stuffing attempt (many
    # source IPs, one account) can walk straight past. Incremented on every
    # failed login, reset to 0 on success; once it hits the threshold in
    # auth.py, locked_until is set a short cooldown into the future and
    # further attempts are rejected without even checking the password —
    # self-clears after the cooldown, no admin action needed.
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="user")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscription: Mapped["Subscription | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
