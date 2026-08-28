import uuid
from datetime import date
from sqlalchemy import String, Text, Date, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from pgvector.sqlalchemy import Vector
from app.db.base import Base, TimestampMixin

EMBEDDING_DIM = 384


class JournalEntry(Base, TimestampMixin):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_narrative_fts", "narrative_tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    shorthand: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    user: Mapped["User"] = relationship(back_populates="journal_entries")
    campaign: Mapped["Campaign"] = relationship(back_populates="journal_entries")
    tags: Mapped[list["Tag"]] = relationship(secondary="journal_tags", back_populates="journal_entries")
