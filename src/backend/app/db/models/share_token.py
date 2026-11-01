import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin, CAMPAIGN_ROLE_ENUM
from app.domain.enums import CampaignRole


class CampaignShareToken(Base, TimestampMixin):
    __tablename__ = "campaign_share_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "read_only": anyone with the link can view, no account needed.
    # "collaborate": redeeming the link (requires an account) grants CampaignMember write access.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="read_only")
    # The Role a collaborate link grants; NULL for read_only links. New links
    # get a role from E0-Access.4/12 (the share routes are unchanged here).
    role: Mapped[CampaignRole | None] = mapped_column(CAMPAIGN_ROLE_ENUM, nullable=True)
    # Expiry is enforced by E0-Access.4.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped on grant changes by E0-Access.10.
    access_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    campaign: Mapped["Campaign"] = relationship()
