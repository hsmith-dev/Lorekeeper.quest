"""entity_changes.write_visibility: the audience a history row was written for (E0-WorldCore.5)

Revision ID: 0f1c3b194a4b
Revises: 03c0b504f1d1
Create Date: 2026-11-20 10:00:00.000000

Owner decision (round 4): a history row written while its Entity or field
was hidden from an audience stays hidden from that audience after
publication. `world_service.apply_change` now records, on every row it
writes, whether the Party could already see the row's field both just before
and just after the change (`party`) or not (`gm`). The access registry reads
the column as a floor on `entity_changes` (most_restrictive(current rule,
floor)), so a row is never wider than its Entity is now, nor than it was
when it was written.

**Backfill rule.** `ADD COLUMN ... NOT NULL DEFAULT 'gm'` sets every existing
row to `gm`. On PostgreSQL 11+ that is a metadata-only change: no table
rewrite and no per-row SQL. It is exact, not just conservative: before this
revision no HTTP route wrote Entity fields, so the only rows that can exist
are

  (a) F3-world `migrated` rows (03c0b504f1d1), written while every copied
      Entity was GM-only by construction, and
  (b) rows written by `POST /api/campaigns/{id}/visibility` (publish, hide and
      field-hide rows), whose before- or after-state is GM.

Both are `gm` under the new rule. Consequence: a Player no longer sees the
`migrated` row of a published Entity (it was public through
`public_null_ops`); the GM still does. A later re-run of the F3 copy
(E0-WorldCore.6) inserts without this column and gets `gm` from the server
default.

downgrade() is for development only; production is forward-only (NFR-8). It
drops the column and leaves every other value of `entity_changes` as it was.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0f1c3b194a4b'
down_revision: Union[str, None] = '03c0b504f1d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The one statement is the backfill: every existing row becomes `gm`.
    op.add_column('entity_changes', sa.Column(
        'write_visibility', postgresql.ENUM(name='visibility', create_type=False), nullable=False,
        server_default='gm'))


def downgrade() -> None:
    op.drop_column('entity_changes', 'write_visibility')
