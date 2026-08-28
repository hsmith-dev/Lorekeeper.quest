"""add_app_config

Revision ID: 4b8f2d9e71c3
Revises: 9a7c31e04b5d
Create Date: 2026-08-28 05:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b8f2d9e71c3'
down_revision: Union[str, None] = '9a7c31e04b5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('open_access_mode', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    # Seed the singleton row. Open access is the platform default — gated
    # SaaS mode (promo codes / Stripe) is the opt-in, flipped from the admin
    # portal. Deployments that predate this migration and were running gated
    # keep gating only if the operator unticks the box after upgrading.
    op.execute("INSERT INTO app_config (id, open_access_mode) VALUES (1, true)")


def downgrade() -> None:
    op.drop_table('app_config')
