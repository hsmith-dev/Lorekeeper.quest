import uuid
from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin, CAMPAIGN_ROLE_ENUM
from app.domain.enums import CampaignRole


class CampaignMember(Base, TimestampMixin):
    """A non-owner collaborator in a campaign, joined via a 'collaborate'
    CampaignShareToken, with a stored Role (co_gm or player; a new Member is a
    player, FR-7). The campaign owner (Campaign.user_id) is never represented
    here — ownership is checked separately and always implies full access."""

    __tablename__ = "campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "user_id", name="uq_campaign_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[CampaignRole] = mapped_column(
        CAMPAIGN_ROLE_ENUM, nullable=False, default=CampaignRole.PLAYER,
        server_default=CampaignRole.PLAYER.value)
    # Bumped on grant changes by E0-Access.10.
    access_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    campaign: Mapped["Campaign"] = relationship()
    user: Mapped["User"] = relationship()
