"""entity_mentions: one suggested Mention per (entry, Entity, source field) (E0-WorldCore.7)

Revision ID: eed202f2eead
Revises: 0f1c3b194a4b
Create Date: 2026-11-21 10:00:00.000000

A partial unique index, `uq_entity_mentions_suggested` on
`(journal_id, entity_id, source_field) WHERE NOT confirmed`, backs the
`suggested_mentions_v1` backfill (app/jobs/world.py): a GM never sees two
suggestions of one Entity for the same field of one entry. Confirmed rows are
not constrained (a GM may confirm several quotes of one entry).

**Data safety.**

- Before this revision no route or Job wrote `entity_mentions` (there was no
  add-mention route, and merge had no route), so production has no rows and
  the dedupe `DELETE` below is a no-op there. It exists only so that
  `CREATE UNIQUE INDEX` can never fail at boot on a development database.
- The dedupe deletes only *suggested* rows (`confirmed = false`) that have an
  older suggested twin (same entry, Entity and source field; older by
  `(created_at, id)`). Suggested rows carry no Canon; confirmed rows are
  never touched.
- Re-running the upgrade is safe: the dedupe is idempotent, and Alembic
  creates the index once.
- downgrade() drops only the index (development only; production is
  forward-only, NFR-8). No row is changed.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'eed202f2eead'
down_revision: Union[str, None] = '0f1c3b194a4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = 'uq_entity_mentions_suggested'


def upgrade() -> None:
    # Keep the oldest suggested row of each (entry, Entity, source field).
    op.execute(
        "DELETE FROM entity_mentions m USING entity_mentions d "
        "WHERE NOT m.confirmed AND NOT d.confirmed "
        "AND m.journal_id = d.journal_id AND m.entity_id = d.entity_id AND m.source_field = d.source_field "
        "AND (d.created_at, d.id) < (m.created_at, m.id)"
    )
    op.create_index(INDEX, 'entity_mentions', ['journal_id', 'entity_id', 'source_field'], unique=True,
                    postgresql_where=sa.text('NOT confirmed'))


def downgrade() -> None:
    op.drop_index(INDEX, table_name='entity_mentions')
