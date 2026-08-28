"""add_tutorial_flag

Revision ID: e5f6a7b8c9d1
Revises: d4c5e6f7a8b9
Create Date: 2026-08-12 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d1'
down_revision: Union[str, None] = 'd4c5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default=true backfills every existing user as already having
    # seen the tutorial — only accounts created after this migration (via
    # the ORM's default=False) get prompted. See User.has_completed_tutorial.
    op.add_column('users', sa.Column('has_completed_tutorial', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('users', 'has_completed_tutorial')
