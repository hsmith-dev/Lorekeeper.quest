"""add_training_samples

Revision ID: c5d4e3f2a1b0
Revises: a3f8b9c2d1e4
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ENUM

revision: str = "c5d4e3f2a1b0"
down_revision: Union[str, None] = "a3f8b9c2d1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_genre_enum = ENUM(
    "fantasy", "scifi", "horror", "videogame", "other",
    name="traininggenre", create_type=False,
)
_system_enum = ENUM(
    "dnd_5e", "pathfinder_2e", "warhammer_fantasy",
    "starfinder", "cyberpunk_red", "shadowrun",
    "call_of_cthulhu", "world_of_darkness",
    "elden_ring", "final_fantasy", "world_of_warcraft",
    "baldurs_gate", "generic",
    name="gamesystem", create_type=False,
)
_scenario_enum = ENUM(
    "combat", "exploration", "social", "loot", "rest",
    "quest_update", "boss_fight", "character_development",
    "world_event", "travel", "puzzle", "downtime",
    name="scenariotype", create_type=False,
)


def upgrade() -> None:
    op.execute("""
        CREATE TYPE traininggenre AS ENUM (
            'fantasy', 'scifi', 'horror', 'videogame', 'other'
        )
    """)
    op.execute("""
        CREATE TYPE gamesystem AS ENUM (
            'dnd_5e', 'pathfinder_2e', 'warhammer_fantasy',
            'starfinder', 'cyberpunk_red', 'shadowrun',
            'call_of_cthulhu', 'world_of_darkness',
            'elden_ring', 'final_fantasy', 'world_of_warcraft',
            'baldurs_gate', 'generic'
        )
    """)
    op.execute("""
        CREATE TYPE scenariotype AS ENUM (
            'combat', 'exploration', 'social', 'loot', 'rest',
            'quest_update', 'boss_fight', 'character_development',
            'world_event', 'travel', 'puzzle', 'downtime'
        )
    """)

    op.create_table(
        "training_samples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("genre", _genre_enum, nullable=False),
        sa.Column("game_system", _system_enum, nullable=False),
        sa.Column("scenario_type", _scenario_enum, nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("shorthand", sa.Text(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("is_validated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_training_samples_genre", "training_samples", ["genre"])
    op.create_index("ix_training_samples_game_system", "training_samples", ["game_system"])
    op.create_index("ix_training_samples_scenario_type", "training_samples", ["scenario_type"])


def downgrade() -> None:
    op.drop_index("ix_training_samples_scenario_type", table_name="training_samples")
    op.drop_index("ix_training_samples_game_system", table_name="training_samples")
    op.drop_index("ix_training_samples_genre", table_name="training_samples")
    op.drop_table("training_samples")
    op.execute("DROP TYPE IF EXISTS scenariotype")
    op.execute("DROP TYPE IF EXISTS gamesystem")
    op.execute("DROP TYPE IF EXISTS traininggenre")
