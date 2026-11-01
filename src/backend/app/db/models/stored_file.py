"""`stored_files` and `derived_sources` (F2-jobs-files, E0-Jobs.1; AD-14).

A stored file's Audience is derived (app/access/registry.py,
`derived_from_sources`): the most restrictive of the rows its
`derived_sources` name, narrowed to Owner(audience_owner_id) when that is
set. `stored_files.kind` is the file's derived type (a DERIVED_REGISTRY
name) and its `derived_sources` rows carry `derived_type = kind`,
`derived_id = stored_files.id`.

`derived_sources` is typed provenance for every derived record (files,
recaps, chronicle runs, chat messages, live recaps): `derived_id` has no FK
because it points into several tables. `kind`, `derived_type`, `ref_kind`
are open sets with no CHECK: their vocabularies belong to later stories.
The file service (E0-Jobs.8) is the only writer of stored_files.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StoredFile(Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        # A cache hit is a fresh file of the same Campaign and kind; a stale
        # one never blocks regenerating under the same key.
        Index("uq_stored_files_cache_key_fresh", "campaign_id", "kind", "cache_key", unique=True,
              postgresql_where=text("NOT stale")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Narrows the file to Owner(u) (a Player's own export). CASCADE, not SET
    # NULL: dropping the owner must never widen the file's Audience.
    audience_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class DerivedSource(Base):
    """One input of a derived record (AD-14a). `ref_field` names the field of
    the source the value came from (an always-GM field makes it GM)."""

    __tablename__ = "derived_sources"
    __table_args__ = (
        Index("ix_derived_sources_ref", "ref_kind", "ref_id"),
        Index("ix_derived_sources_derived", "derived_type", "derived_id"),
    )

    # A surrogate key: ref_field is nullable, so the listed columns cannot be the PK.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    derived_type: Mapped[str] = mapped_column(String(64), nullable=False)
    derived_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ref_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    ref_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ref_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
