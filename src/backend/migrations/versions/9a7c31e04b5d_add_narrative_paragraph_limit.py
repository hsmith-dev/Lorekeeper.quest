"""add_narrative_paragraph_limit

Revision ID: 9a7c31e04b5d
Revises: d7e8f9a0b1c2
Create Date: 2026-08-28 02:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a7c31e04b5d'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on purpose: NULL means "no preference" — the genre prompts'
    # default length guidance ("2-4 paragraphs") applies. A value pins the
    # narrative length for quick entry generation.
    op.add_column(
        'user_settings',
        sa.Column('narrative_paragraph_limit', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_settings', 'narrative_paragraph_limit')
