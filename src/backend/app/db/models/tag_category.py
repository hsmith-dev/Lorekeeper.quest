import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class TagCategory(Base, TimestampMixin):
    """A user-defined tag type (e.g. "Deity", "House Rule") scoped to one
    campaign, alongside the built-in TagType enum (character/location/item/
    quest/faction). Campaign-scoped, not global, since these are house-specific
    taxonomy rather than universal gaming concepts."""

    __tablename__ = "tag_categories"
    __table_args__ = (UniqueConstraint("campaign_id", "name", name="uq_tag_category_campaign_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50), nullable=False)

    campaign: Mapped["Campaign"] = relationship()
