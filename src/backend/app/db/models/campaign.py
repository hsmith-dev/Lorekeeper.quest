import uuid
import enum
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class Genre(str, enum.Enum):
    fantasy = "fantasy"
    scifi = "scifi"
    horror = "horror"
    videogame = "videogame"
    other = "other"


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[Genre] = mapped_column(SAEnum(Genre), nullable=False, default=Genre.fantasy)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="campaigns")
    journal_entries: Mapped[list["JournalEntry"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
