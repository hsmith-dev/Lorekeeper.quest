import uuid
import enum
from sqlalchemy import Text, Float, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class TrainingGenre(str, enum.Enum):
    fantasy = "fantasy"
    scifi = "scifi"
    horror = "horror"
    videogame = "videogame"
    other = "other"


class GameSystem(str, enum.Enum):
    dnd_5e = "dnd_5e"
    pathfinder_2e = "pathfinder_2e"
    warhammer_fantasy = "warhammer_fantasy"
    starfinder = "starfinder"
    cyberpunk_red = "cyberpunk_red"
    shadowrun = "shadowrun"
    call_of_cthulhu = "call_of_cthulhu"
    world_of_darkness = "world_of_darkness"
    elden_ring = "elden_ring"
    final_fantasy = "final_fantasy"
    world_of_warcraft = "world_of_warcraft"
    baldurs_gate = "baldurs_gate"
    generic = "generic"


class ScenarioType(str, enum.Enum):
    combat = "combat"
    exploration = "exploration"
    social = "social"
    loot = "loot"
    rest = "rest"
    quest_update = "quest_update"
    boss_fight = "boss_fight"
    character_development = "character_development"
    world_event = "world_event"
    travel = "travel"
    puzzle = "puzzle"
    downtime = "downtime"


class TrainingSample(Base, TimestampMixin):
    __tablename__ = "training_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    genre: Mapped[TrainingGenre] = mapped_column(SAEnum(TrainingGenre, name="traininggenre"), nullable=False, index=True)
    game_system: Mapped[GameSystem] = mapped_column(SAEnum(GameSystem, name="gamesystem"), nullable=False, index=True)
    scenario_type: Mapped[ScenarioType] = mapped_column(SAEnum(ScenarioType, name="scenariotype"), nullable=False, index=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    shorthand: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
