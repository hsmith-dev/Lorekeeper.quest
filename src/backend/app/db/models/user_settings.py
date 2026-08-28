import uuid
from sqlalchemy import String, Float, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class UserSettings(Base, TimestampMixin):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # LLM provider: "kobold" | "openai" | "anthropic" | "gemini" | "custom"
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="kobold")
    llm_api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    llm_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.72)
    llm_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=800)

    # Max paragraphs for quick-entry narrative generation. NULL = no
    # preference — the genre prompts' own default ("2-4 paragraphs") applies.
    # Unlike llm_max_tokens (a hard decode cutoff that can truncate
    # mid-sentence), this shapes the prompt so the model plans a complete
    # narrative at the requested length.
    narrative_paragraph_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # "finetuned" | "base" — only meaningful when the user is on the platform
    # hosted default (no personal provider/url/key/model saved; see
    # app/api/deps.py::get_user_llm_config). Deliberately a separate column
    # rather than piggybacking on llm_model: that field being non-empty is
    # exactly what get_user_llm_config's has_personal_config check uses to
    # decide "this user brought their own config" and skip the
    # hosted-tier/quota gate entirely — reusing it here would let anyone set
    # this and get free, unmetered access to the platform's hosted model
    # regardless of subscription tier. Keeping it separate means it can only
    # ever take effect *after* a user has already passed that gate.
    hosted_model_variant: Mapped[str] = mapped_column(String(20), nullable=False, default="finetuned")
