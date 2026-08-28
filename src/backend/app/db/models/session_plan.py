import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class SessionPlan(Base, TimestampMixin):
    """An AI-drafted (then reviewed/edited, same as journal entries — see
    app/services/session_plan_service.py) outline for an upcoming session:
    recap, likely objectives, possible encounters, NPCs to feature,
    complications. Persisted so a GM can generate several, keep the ones
    they like, and revisit them at the table."""

    __tablename__ = "session_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship()
    campaign: Mapped["Campaign"] = relationship()
