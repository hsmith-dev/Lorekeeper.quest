"""add_user_settings

Revision ID: a3f8b9c2d1e4
Revises: eb3bb3b53bd9
Create Date: 2026-06-05 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "a3f8b9c2d1e4"
down_revision: Union[str, None] = "eb3bb3b53bd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("llm_provider", sa.String(50), nullable=False, server_default="kobold"),
        sa.Column("llm_api_url", sa.String(500), nullable=True),
        sa.Column("llm_api_key", sa.String(500), nullable=True),
        sa.Column("llm_model", sa.String(200), nullable=True),
        sa.Column("llm_temperature", sa.Float(), nullable=False, server_default="0.72"),
        sa.Column("llm_max_tokens", sa.Integer(), nullable=False, server_default="800"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
