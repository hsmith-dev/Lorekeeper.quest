"""F2-jobs-files: jobs, data_backfills, stored_files, derived_sources (E0-Jobs.1)

Revision ID: cf62d979bc8a
Revises: c95acb56c595
Create Date: 2026-11-01 18:00:00.000000

The second foundation revision (AD-19): four new tables and nothing else,
so no existing row changes. The CHECKs come from frozen copies of the
StrEnums in app/domain/enums.py; CI-10 (tests/test_enum_check_sync.py)
compares them with the live enums.

downgrade() is for development only; production is forward-only (NFR-8).
It drops exactly the four tables (their indexes and constraints go with
them).
"""
from enum import StrEnum
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.domain.enums import check_sql

# revision identifiers, used by Alembic.
revision: str = 'cf62d979bc8a'
down_revision: Union[str, None] = 'c95acb56c595'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies of the StrEnums, so a later member never changes this revision's CHECKs.
_JobStatus = StrEnum("JobStatus", {
    "QUEUED": "queued", "RUNNING": "running", "DONE": "done", "FAILED": "failed", "CANCELLED": "cancelled"})
_JobQueue = StrEnum("JobQueue", {"INTERACTIVE": "interactive", "ONSAVE": "onsave", "BACKFILL": "backfill"})
_JobErrorCode = StrEnum("JobErrorCode", {
    "LLM_CONFIG": "llm_config",
    "AI_OUTPUT_UNUSABLE": "ai_output_unusable",
    "PERMISSION_CHANGED": "permission_changed",
    "MODEL_UNAVAILABLE": "model_unavailable",
    "LLM_UNAVAILABLE": "llm_unavailable",
    "LLM_BUSY": "llm_busy",
    "TIMEOUT": "timeout",
    "INTERRUPTED": "interrupted",
    "INTERNAL": "internal",
    "PROMPT_TOO_LARGE": "prompt_too_large",
})

# (table, constraint, enum, column)
CHECKS = (
    ('jobs', 'ck_jobs_status', _JobStatus, 'status'),
    ('jobs', 'ck_jobs_queue', _JobQueue, 'queue'),
    ('jobs', 'ck_jobs_error_code', _JobErrorCode, 'error_code'),
    ('data_backfills', 'ck_data_backfills_status', _JobStatus, 'status'),
)

TABLES = ('jobs', 'data_backfills', 'stored_files', 'derived_sources')


def _now() -> sa.TextClause:
    return sa.text('now()')


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('queue', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='queued'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column('idempotency_key', sa.Text(), nullable=False),
        sa.Column('ctx_kind', sa.String(length=16), nullable=False),
        sa.Column('ctx_user_id', sa.UUID(), nullable=True),
        sa.Column('ctx_audience', sa.Text(), nullable=True),
        sa.Column('access_epoch', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('progress', sa.REAL(), nullable=True),
        sa.Column('stage', sa.Text(), nullable=True),
        sa.Column('eta_seconds', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.String(length=32), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('result_ref', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('depends_on_job_id', sa.UUID(), nullable=True),
        sa.Column('worker_id', sa.Text(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ctx_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['depends_on_job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    # AD-4: an idempotency key is unique among unfinished Jobs only.
    op.create_index('uq_jobs_idempotency_key_active', 'jobs', ['idempotency_key'], unique=True,
                    postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.create_index('ix_jobs_campaign_status_created', 'jobs', ['campaign_id', 'status', 'created_at'])
    op.create_index('ix_jobs_status_queue_created', 'jobs', ['status', 'queue', 'created_at'])

    op.create_table(
        'data_backfills',
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='queued'),
        sa.Column('cursor', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('job_id', sa.UUID(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('name'),
    )

    op.create_table(
        'stored_files',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=64), nullable=False),
        sa.Column('storage_key', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('audience_owner_id', sa.UUID(), nullable=True),
        sa.Column('cache_key', sa.String(length=128), nullable=True),
        sa.Column('stale', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        # CASCADE, not SET NULL: dropping the owner must never widen the file's Audience.
        sa.ForeignKeyConstraint(['audience_owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('uq_stored_files_cache_key_fresh', 'stored_files', ['campaign_id', 'kind', 'cache_key'],
                    unique=True, postgresql_where=sa.text('NOT stale'))

    op.create_table(
        'derived_sources',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('derived_type', sa.String(length=64), nullable=False),
        sa.Column('derived_id', sa.UUID(), nullable=False),
        sa.Column('ref_kind', sa.String(length=64), nullable=False),
        sa.Column('ref_id', sa.UUID(), nullable=False),
        sa.Column('ref_field', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_derived_sources_ref', 'derived_sources', ['ref_kind', 'ref_id'])
    op.create_index('ix_derived_sources_derived', 'derived_sources', ['derived_type', 'derived_id'])

    for table, name, enum, column in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} " + check_sql(enum, column))


def downgrade() -> None:
    # Dev only (NFR-8). Indexes and constraints go with their tables.
    for table in reversed(TABLES):
        op.drop_table(table)
