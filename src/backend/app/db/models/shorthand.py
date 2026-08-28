import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class ShorthandTerm(Base, TimestampMixin):
    """A campaign-specific abbreviation the table actually uses (e.g. "BBEG"
    -> "the big bad evil guy", or a player's nickname for their character),
    plus an optional note on how/when it's used. Fed into the AI's system
    prompt for both journal narrative generation
    (app/services/ai_service.py) and chat (app/services/chat_service.py) —
    see app/services/shorthand_service.py::get_glossary — so a session's
    shorthand notes get expanded using the table's own vocabulary instead of
    the model guessing or silently ignoring unfamiliar abbreviations."""

    __tablename__ = "shorthand_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    term: Mapped[str] = mapped_column(String(50), nullable=False)
    meaning: Mapped[str] = mapped_column(Text, nullable=False)
    usage: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship()
    campaign: Mapped["Campaign"] = relationship()
