import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class PasswordResetToken(Base, TimestampMixin):
    """Single-use, short-lived token for the forgot-password flow (see
    app/api/routes/auth.py's forgot_password/reset_password). Deliberately a
    real DB row rather than a signed JWT with a short expiry — a JWT would
    still validate for its entire window even after being used once (no way
    to invalidate it early), letting a captured reset link be replayed. This
    row is deleted the moment it's redeemed, closing that gap.

    token_hash, not the raw token — same reasoning as hashed_password on
    User: a DB dump shouldn't hand over usable reset links. SHA-256 (not
    bcrypt) is enough here since the token itself is a full-entropy random
    string, not a low-entropy secret that needs a slow, salted hash to
    resist guessing.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship()
