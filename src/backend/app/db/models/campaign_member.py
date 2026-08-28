import uuid
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class CampaignMember(Base, TimestampMixin):
    """A non-owner collaborator with write access to a campaign, joined via a
    'collaborate' CampaignShareToken. The campaign owner (Campaign.user_id) is
    not represented here — ownership is checked separately and always implies
    full access."""

    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_campaign_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    campaign: Mapped["Campaign"] = relationship()
    user: Mapped["User"] = relationship()
