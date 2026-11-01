import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, ForeignKeyConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base import Base, TimestampMixin


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        # F3-world: ON DELETE SET NULL (npc_entity_id) in the migration; reflected as SET NULL.
        ForeignKeyConstraint(["campaign_id", "npc_entity_id"], ["entities.campaign_id", "entities.id"],
                             name="fk_chat_sessions_npc_entity", ondelete="SET NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="New conversation")
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The NPC Entity this chat talks to (same Campaign; F3-world FK).
    npc_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="chat_sessions")
    campaign: Mapped["Campaign | None"] = relationship()
