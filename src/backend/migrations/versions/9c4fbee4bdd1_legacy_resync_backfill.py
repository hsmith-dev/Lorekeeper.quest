"""legacy_resync_v1: re-copy what the old NPC/Quest pages changed after F3-world (E0-WorldCore.6)

Revision ID: 9c4fbee4bdd1
Revises: eed202f2eead
Create Date: 2026-11-21 10:00:00.000000

Until E0-WorldCore.6 the legacy NPC/Quest routes kept writing `npcs` and
`quests` after F3-world (03c0b504f1d1) copied them into `entities`. From
this release those routes are adapters over `entities` and the legacy tables
are frozen. This revision only queues the one-shot reconciliation: it
inserts the `data_backfills` row `legacy_resync_v1` (status `queued`), which
the worker's backfill runner runs once per Campaign as its Owner through the
Job kind `backfill.legacy_resync` (app/jobs/legacy_resync.py). The job, not
SQL, does the work, because every Canon write must go through
`world_service.apply_change` (history, write-time visibility, hooks) and the
three-way comparison needs that history.

**Data safety.**

* Idempotent: one `INSERT ... ON CONFLICT (name) DO NOTHING`. The job commits
  each step's writes with its cursor; a re-run finds nothing left to change
  (the same value, the same canon_note, the F3 deterministic create id).
* Privacy first (OD-1 A): every Entity the job creates is GM-only, it never
  changes a Visibility, and it never applies a legacy edit to an Entity that
  is not GM-only (except `gm_notes`, which is always GM). It records a
  GM-only `canon_note` instead.
* Edited on both sides: the World wins; the legacy value stays in the
  untouched legacy row and is quoted in a GM-only `canon_note`. Nothing the
  World changed is deleted.
* Legacy rows are only read: `npcs`/`quests` are never written or deleted.
* Locks: no DDL, no table rewrite; one row lock on `data_backfills` here.
  The job locks one Entity row (`FOR UPDATE`) per short step.
* Fresh upgrade (F3 and this revision in one boot): every Entity equals its
  legacy row, so the job writes no `entity_changes` row.

downgrade() is for development only (production is forward-only, NFR-8): it
removes the backfill row only while it is untouched (queued, no job, no
cursor). Entities the job wrote stay; each write is a normal history row the
GM can revert.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9c4fbee4bdd1'
down_revision: Union[str, None] = 'eed202f2eead'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL_NAME = 'legacy_resync_v1'


def upgrade() -> None:
    op.execute(f"INSERT INTO data_backfills (name, status) VALUES ('{BACKFILL_NAME}', 'queued') "
               "ON CONFLICT (name) DO NOTHING")


def downgrade() -> None:
    # Only while untouched: a row the runner has started is not this revision's to remove.
    op.execute(f"DELETE FROM data_backfills WHERE name = '{BACKFILL_NAME}' "
               "AND status = 'queued' AND job_id IS NULL AND cursor IS NULL")
