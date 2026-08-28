import enum
import uuid
from sqlalchemy import ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class FeedbackCategory(str, enum.Enum):
    bug = "bug"
    model_quality = "model_quality"
    feature_request = "feature_request"
    other = "other"


class Feedback(Base, TimestampMixin):
    """User-submitted feedback, optionally linked to a campaign so whoever's
    reviewing it (see app/api/deps.py::require_admin) can pull that
    campaign's actual journal/NPC/quest/source content alongside the
    feedback text for model-quality research — the point isn't just
    collecting complaints, it's collecting complaints *with the context
    that produced them*. campaign_id is nullable (general feedback doesn't
    need one) and SET NULL on campaign delete so removing a campaign
    doesn't destroy the feedback history about it."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[FeedbackCategory] = mapped_column(
        SAEnum(FeedbackCategory), nullable=False, default=FeedbackCategory.other
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped["User"] = relationship()
    campaign: Mapped["Campaign | None"] = relationship()
