import uuid
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class AdminMessage(Base, TimestampMixin):
    """Audit log of admin-to-user messages (see app/api/routes/admin.py's
    POST /users/{id}/message) — delivery itself is via email
    (email_service.send_admin_message_email), this row just records that it
    happened, when, and what was said, so there's a paper trail for
    account-moderation decisions (warnings before a suspension, etc.)."""

    __tablename__ = "admin_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship()
