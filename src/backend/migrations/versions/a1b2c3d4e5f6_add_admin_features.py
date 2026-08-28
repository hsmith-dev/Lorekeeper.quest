"""add_admin_features

Revision ID: a1b2c3d4e5f6
Revises: f5e6a7b8c9d0
Create Date: 2026-08-11 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f5e6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_suspended', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('suspended_reason', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('admin_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('admin_messages')
    op.drop_column('users', 'suspended_at')
    op.drop_column('users', 'suspended_reason')
    op.drop_column('users', 'is_suspended')
