import uuid
import enum
from sqlalchemy import String, ForeignKey, UniqueConstraint, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class TagType(str, enum.Enum):
    character = "character"
    location = "location"
    item = "item"
    quest = "quest"
    faction = "faction"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", "tag_type", name="uq_tag_name_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Exactly one of tag_type / custom_category_id is set — built-in type, or a
    # user-defined TagCategory. NLP auto-extraction only ever produces the
    # built-in types; custom categories are attached manually.
    tag_type: Mapped[TagType | None] = mapped_column(SAEnum(TagType), nullable=True)
    custom_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tag_categories.id", ondelete="CASCADE"), nullable=True
    )

    journal_entries: Mapped[list["JournalEntry"]] = relationship(secondary="journal_tags", back_populates="tags")
    custom_category: Mapped["TagCategory | None"] = relationship()


class JournalTag(Base):
    __tablename__ = "journal_tags"

    journal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
