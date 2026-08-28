"""add_semantic_similarity_metric

Revision ID: 8c1d5f3a92e7
Revises: 4b8f2d9e71c3
Create Date: 2026-08-28 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c1d5f3a92e7'
down_revision: Union[str, None] = '4b8f2d9e71c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable — evaluation runs stored before this metric existed simply
    # have no value for it; the UI shows a dash.
    op.add_column(
        'model_evaluations',
        sa.Column('avg_semantic_similarity', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('model_evaluations', 'avg_semantic_similarity')
