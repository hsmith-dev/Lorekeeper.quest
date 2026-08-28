"""add_promo_plan_and_multi_admin

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('promo_codes', sa.Column('grants_plan', sa.String(length=20), nullable=False, server_default='byok'))
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()))

    # One-time bootstrap: promote whoever currently matches ADMIN_EMAIL (the
    # old single-operator mechanism) to the new DB-backed is_admin flag, so
    # the existing admin doesn't lose access the moment this ships — from
    # here on, is_admin is grantable to anyone via the admin panel itself
    # (POST /api/admin/users/{id}/promote), no env var or redeploy needed.
    from app.core.config import get_settings
    admin_email = get_settings().admin_email
    if admin_email:
        op.execute(
            sa.text("UPDATE users SET is_admin = true WHERE lower(email) = lower(:email)")
            .bindparams(email=admin_email)
        )


def downgrade() -> None:
    op.drop_column('users', 'is_admin')
    op.drop_column('promo_codes', 'grants_plan')
