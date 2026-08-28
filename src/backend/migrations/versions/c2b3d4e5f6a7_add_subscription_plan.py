"""add_subscription_plan

Revision ID: c2b3d4e5f6a7
Revises: b1a2c3d4e5f6
Create Date: 2026-08-08 09:00:00.000000

Two paid tiers ("byok" $5/mo, "hosted" $15/mo — see app/db/models/subscription.py
and app/services/billing_service.py) replace the single flat-rate tier.
Existing subscription rows (if any exist yet — this shipped before any real
customer had subscribed) get plan=NULL, which get_user_llm_config treats the
same as "not hosted-eligible" — the safe default, no backfill needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2b3d4e5f6a7'
down_revision: Union[str, None] = 'b1a2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('plan', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('subscriptions', 'plan')
