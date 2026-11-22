"""journal_entries: duplicate hash is a 409 only when visible; reembed backfill (E0-Journal.2)

Revision ID: 7d1e2a9c4b6f
Revises: eed202f2eead
Create Date: 2026-11-22 10:00:00.000000

Two changes.

1. `uq_journal_entries_campaign_user_entry_hash` (UNIQUE on `(campaign_id,
   user_id, entry_hash)`, F1-core c95acb56c595) becomes the plain index
   `ix_journal_entries_campaign_user_entry_hash` on the same columns. The
   constraint is per author, not Campaign-wide, but an author can be unable
   to see one of their own entries (a demoted GM's GM-only entry, say). The
   unique constraint then turns a save into a 409 that reveals the hidden
   entry exists. Owner decision (privacy first): a duplicate is a 409 only
   when the writer can see it (`journal_service.visible_duplicate`, under a
   per-(Campaign, author, hash) advisory lock). A hidden entry and a visible
   one may share a hash.
2. The `data_backfills` row `journal_reembed_v1` (status `queued`): the
   runner (app/jobs/backfill.py) runs `journal.reembed_sweep`
   (app/jobs/journal.py) once per Campaign, filling every entry left with a
   NULL `embedding` / `party_embedding` (saves made while `ml` was down
   whose reembed hook was lost).

**Data safety.**

- Upgrade changes no row. Dropping a unique constraint and adding a
  non-unique index on the same columns loses no data, and every query that
  used the unique index can use the new one.
- The backfill only fills NULL vectors (and re-derives that entry's derived
  tags, keeping manual and legacy ones) through the same writer path as a
  save. It never changes text, hash or Visibility. While `ml` is down it
  does nothing and is retried later.
- Re-running the upgrade is safe: the row insert is `ON CONFLICT DO
  NOTHING`, and the index is created once by Alembic.
- downgrade() (development only, production is forward-only, NFR-8)
  restores the unique constraint, and refuses with a clear error when rows
  now share a hash, rather than deleting any entry. It also removes the
  backfill row.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7d1e2a9c4b6f'
down_revision: Union[str, None] = 'eed202f2eead'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE = 'uq_journal_entries_campaign_user_entry_hash'
INDEX = 'ix_journal_entries_campaign_user_entry_hash'
COLUMNS = ['campaign_id', 'user_id', 'entry_hash']
BACKFILL_NAME = 'journal_reembed_v1'


def upgrade() -> None:
    op.drop_constraint(UNIQUE, 'journal_entries', type_='unique')
    op.create_index(INDEX, 'journal_entries', COLUMNS)
    op.execute(f"INSERT INTO data_backfills (name, status) VALUES ('{BACKFILL_NAME}', 'queued') "
               "ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    op.execute(f"DELETE FROM data_backfills WHERE name = '{BACKFILL_NAME}'")
    dupes = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM (SELECT 1 FROM journal_entries "
        "GROUP BY campaign_id, user_id, entry_hash HAVING count(*) > 1) d"
    )).scalar()
    if dupes:
        raise RuntimeError(
            f"cannot restore {UNIQUE}: {dupes} (campaign, author, hash) groups now hold more than one "
            "entry (a hidden and a visible entry may share a hash since 7d1e2a9c4b6f); "
            "resolve them by hand first, nothing was deleted")
    op.drop_index(INDEX, table_name='journal_entries')
    op.create_unique_constraint(UNIQUE, 'journal_entries', COLUMNS)
