import uuid
from sqlalchemy import String, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class ModelEvaluation(Base, TimestampMixin):
    """A stored result of running the validation set against one provider —
    run once per model (e.g. label="Base Mistral", then label="Fine-tuned"),
    then compare stored runs side by side. Two full models rarely fit in VRAM
    at once on typical dev hardware, so evaluation runs one provider at a
    time rather than requiring both live simultaneously."""

    __tablename__ = "model_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_length: Mapped[float] = mapped_column(Float, nullable=False)
    avg_word_overlap: Mapped[float] = mapped_column(Float, nullable=False)
    has_content_pct: Mapped[float] = mapped_column(Float, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
