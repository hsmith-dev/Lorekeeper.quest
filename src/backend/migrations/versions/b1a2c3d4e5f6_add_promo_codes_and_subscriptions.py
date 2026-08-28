"""add_promo_codes_and_subscriptions

Revision ID: b1a2c3d4e5f6
Revises: 46e514a682dd
Create Date: 2026-08-06 09:00:00.000000

Adds account-access gating: users.access_granted / access_source, plus
promo_codes / promo_code_redemptions (the free-account path) and subscriptions
(the paid path, synced from Stripe). Every account that already exists when
this migration runs is grandfathered in (access_granted=true) — this gate
didn't exist when they signed up, so it shouldn't retroactively lock them out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1a2c3d4e5f6'
down_revision: Union[str, None] = '46e514a682dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: access gate ──────────────────────────────────────────────────
    op.add_column('users', sa.Column('access_granted', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('users', sa.Column('access_source', sa.String(length=20), nullable=True))

    # Grandfather every pre-existing account — this table already had rows
    # before account gating existed.
    op.execute("UPDATE users SET access_granted = true, access_source = 'grandfathered'")

    # ── promo_codes ──────────────────────────────────────────────────────────
    op.create_table('promo_codes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=50), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('max_redemptions', sa.Integer(), nullable=True),
    sa.Column('redemption_count', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_promo_codes_code'), 'promo_codes', ['code'], unique=True)

    # ── promo_code_redemptions ──────────────────────────────────────────────
    op.create_table('promo_code_redemptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('promo_code_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['promo_code_id'], ['promo_codes.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id')
    )

    # ── subscriptions ────────────────────────────────────────────────────────
    op.create_table('subscriptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('period_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tokens_used_current_period', sa.Integer(), nullable=False),
    sa.Column('tokens_included_per_period', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id'),
    sa.UniqueConstraint('stripe_subscription_id')
    )
    op.create_index(op.f('ix_subscriptions_stripe_customer_id'), 'subscriptions', ['stripe_customer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_subscriptions_stripe_customer_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_table('promo_code_redemptions')
    op.drop_index(op.f('ix_promo_codes_code'), table_name='promo_codes')
    op.drop_table('promo_codes')
    op.drop_column('users', 'access_source')
    op.drop_column('users', 'access_granted')
