"""add_journal_embeddings

Revision ID: 7ffedba22a12
Revises: 622e1505cab4
Create Date: 2026-06-05 17:56:01.194348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = '7ffedba22a12'
down_revision: Union[str, None] = '622e1505cab4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column('journal_entries', sa.Column('embedding', Vector(384), nullable=True))


def downgrade() -> None:
    op.drop_column('journal_entries', 'embedding')
    op.execute("DROP EXTENSION IF EXISTS vector")
