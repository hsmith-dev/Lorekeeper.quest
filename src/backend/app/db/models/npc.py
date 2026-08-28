import uuid
import enum
from sqlalchemy import String, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class NpcRole(str, enum.Enum):
    npc = "npc"
    pc = "pc"
    monster = "monster"
    faction = "faction"


class NpcStatus(str, enum.Enum):
    alive = "alive"
    dead = "dead"
    unknown = "unknown"


class NpcEntry(Base, TimestampMixin):
    __tablename__ = "npcs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[NpcRole] = mapped_column(SAEnum(NpcRole), nullable=False, default=NpcRole.npc)
    status: Mapped[NpcStatus] = mapped_column(SAEnum(NpcStatus), nullable=False, default=NpcStatus.unknown)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship()
    campaign: Mapped["Campaign"] = relationship()
