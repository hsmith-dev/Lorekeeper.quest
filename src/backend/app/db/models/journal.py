import uuid
from datetime import date
from sqlalchemy import CheckConstraint, String, Text, Date, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from pgvector.sqlalchemy import Vector
from app.db.base import Base, TimestampMixin, VISIBILITY_ENUM
from app.domain.embedding import EMBEDDING_DIM
from app.domain.enums import EntryKind, Visibility, check_expr


class JournalEntry(Base, TimestampMixin):
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_narrative_fts", "narrative_tsv", postgresql_using="gin"),
        Index("ix_journal_party_fts", "party_tsv", postgresql_using="gin"),
        CheckConstraint(check_expr(EntryKind, "kind"), name="ck_journal_entries_kind"),
        # AR-17: unique per (Campaign, author), not globally.
        UniqueConstraint("campaign_id", "user_id", "entry_hash",
                         name="uq_journal_entries_campaign_user_entry_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    shorthand: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    kind: Mapped[EntryKind] = mapped_column(
        String(16), nullable=False, default=EntryKind.GM, server_default=EntryKind.GM.value)
    visibility: Mapped[Visibility] = mapped_column(
        VISIBILITY_ENUM, nullable=False, default=Visibility.PARTY, server_default=Visibility.PARTY.value)
    # Party-only search: the Narrative alone, never the Shorthand. Written by
    # the F1-core backfill; E0-Access.7 keeps it (and party_embedding) current.
    party_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    party_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    user: Mapped["User"] = relationship(back_populates="journal_entries")
    campaign: Mapped["Campaign"] = relationship(back_populates="journal_entries")
    tags: Mapped[list["Tag"]] = relationship(secondary="journal_tags", back_populates="journal_entries")
