"""F1-core: Roles, Visibility and Party-only search columns (E0-Access.1)

Revision ID: c95acb56c595
Revises: a3e7c1f9d258
Create Date: 2026-11-01 12:00:00.000000

The first foundation revision (AD-19). Schema plus set-based SQL only
(AD-18): no tables, no FKs on npc_entity_id / pc_entity_id (F3-world adds
them), no party_embedding backfill (E0-Access.7).

Existing Members become Players through the column default of
campaign_members.role (ADD COLUMN ... NOT NULL DEFAULT 'player'), not an
UPDATE, so re-running the data steps can never demote a later Co-GM. Every
UPDATE in DATA_STEPS has a WHERE that makes it a no-op on rows it already
changed; tests/migrations/test_upgrade_snapshot.py re-applies them through
apply_data_steps() and checks nothing moves.

downgrade() is for development only; production is forward-only (NFR-8). It
restores the exact a3e7c1f9d258 schema, including the global
journal_entries_entry_hash_key, so it fails if two Campaigns (or two users)
have since stored the same entry_hash.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

from app.domain.enums import EntryKind, TagSourceField, check_sql

# revision identifiers, used by Alembic.
revision: str = 'c95acb56c595'
down_revision: Union[str, None] = 'a3e7c1f9d258'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen here: a later label is added by its own ALTER TYPE revision. CI-10
# (tests/test_enum_check_sync.py PG_ENUMS) compares these with the StrEnums.
VISIBILITY_LABELS = ('party', 'gm', 'private')
CAMPAIGN_ROLE_LABELS = ('co_gm', 'player')

visibility = postgresql.ENUM(*VISIBILITY_LABELS, name='visibility', create_type=False)
campaign_role = postgresql.ENUM(*CAMPAIGN_ROLE_LABELS, name='campaign_role', create_type=False)

# (table, server default) for every table that gains a `visibility` column.
VISIBILITY_COLUMNS = (
    ('journal_entries', 'party'),
    ('character_sheets', 'party'),
    ('session_plans', 'gm'),
    ('source_documents', 'gm'),
    ('shorthand_terms', 'gm'),
    ('tag_categories', 'party'),
)

OLD_ENTRY_HASH_UNIQUE = 'journal_entries_entry_hash_key'
NEW_ENTRY_HASH_UNIQUE = 'uq_journal_entries_campaign_user_entry_hash'

# Set-based, idempotent data steps (AD-18). Each WHERE skips rows already done.
DATA_STEPS: tuple[str, ...] = (
    # FR-9(b): a Member's chats in the Campaign they are a Member of are
    # archived; they were written with GM-level retrieval. The Owner's chats
    # and chats with no Campaign are untouched.
    """
    UPDATE chat_sessions AS cs
    SET archived_at = now()
    FROM campaign_members AS m, campaigns AS c
    WHERE m.campaign_id = cs.campaign_id
      AND m.user_id = cs.user_id
      AND c.id = cs.campaign_id
      AND c.user_id <> cs.user_id
      AND cs.archived_at IS NULL
    """,
    # FR-7: an existing collaborate link grants Player.
    """
    UPDATE campaign_share_tokens
    SET role = 'player'
    WHERE kind = 'collaborate' AND role IS NULL
    """,
    # Party-only search reads only the Narrative, never the Shorthand.
    """
    UPDATE journal_entries
    SET party_tsv = to_tsvector('english', coalesce(narrative, ''))
    WHERE party_tsv IS NULL
    """,
)


def apply_data_steps(bind) -> None:
    """Run DATA_STEPS on a sync Connection (the idempotency test re-runs them)."""
    for step in DATA_STEPS:
        bind.execute(sa.text(step))


def upgrade() -> None:
    op.execute(
        "CREATE TYPE visibility AS ENUM ("
        + ", ".join(f"'{v}'" for v in VISIBILITY_LABELS) + ")"
    )
    op.execute(
        "CREATE TYPE campaign_role AS ENUM ("
        + ", ".join(f"'{v}'" for v in CAMPAIGN_ROLE_LABELS) + ")"
    )

    # journal_entries
    op.add_column('journal_entries', sa.Column(
        'kind', sa.String(length=16), nullable=False, server_default='gm'))
    op.execute("ALTER TABLE journal_entries ADD CONSTRAINT ck_journal_entries_kind "
               + check_sql(EntryKind, 'kind'))
    op.add_column('journal_entries', sa.Column('party_tsv', postgresql.TSVECTOR(), nullable=True))
    op.add_column('journal_entries', sa.Column('party_embedding', Vector(384), nullable=True))
    op.create_index('ix_journal_party_fts', 'journal_entries', ['party_tsv'],
                    unique=False, postgresql_using='gin')

    for table, default in VISIBILITY_COLUMNS:
        op.add_column(table, sa.Column(
            'visibility', visibility, nullable=False, server_default=default))

    # campaign_members: every existing Member becomes a Player by this default.
    op.add_column('campaign_members', sa.Column(
        'role', campaign_role, nullable=False, server_default='player'))
    op.add_column('campaign_members', sa.Column(
        'access_epoch', sa.Integer(), nullable=False, server_default='0'))

    # campaign_share_tokens: role is used only by `collaborate` links.
    op.add_column('campaign_share_tokens', sa.Column('role', campaign_role, nullable=True))
    op.add_column('campaign_share_tokens', sa.Column(
        'expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('campaign_share_tokens', sa.Column(
        'access_epoch', sa.Integer(), nullable=False, server_default='0'))

    # chat_sessions: npc_entity_id gets its FK in F3-world.
    op.add_column('chat_sessions', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('chat_sessions', sa.Column('npc_entity_id', sa.UUID(), nullable=True))

    # journal_tags.source_field: NULL for every existing tag.
    op.add_column('journal_tags', sa.Column('source_field', sa.String(length=16), nullable=True))
    op.execute("ALTER TABLE journal_tags ADD CONSTRAINT ck_journal_tags_source_field "
               + check_sql(TagSourceField, 'source_field'))

    # character_sheets.pc_entity_id gets its FK in F3-world.
    op.add_column('character_sheets', sa.Column('pc_entity_id', sa.UUID(), nullable=True))

    # AR-17: entry_hash is unique per (Campaign, author), not globally.
    op.drop_constraint(OLD_ENTRY_HASH_UNIQUE, 'journal_entries', type_='unique')
    op.create_unique_constraint(
        NEW_ENTRY_HASH_UNIQUE, 'journal_entries', ['campaign_id', 'user_id', 'entry_hash'])

    # The same statements as apply_data_steps(), through op so --sql works too.
    for step in DATA_STEPS:
        op.execute(step)


def downgrade() -> None:
    # Dev only (NFR-8). Fails if entry_hash is no longer globally unique.
    op.drop_constraint(NEW_ENTRY_HASH_UNIQUE, 'journal_entries', type_='unique')
    op.create_unique_constraint(OLD_ENTRY_HASH_UNIQUE, 'journal_entries', ['entry_hash'])

    op.drop_column('character_sheets', 'pc_entity_id')
    op.drop_constraint('ck_journal_tags_source_field', 'journal_tags', type_='check')
    op.drop_column('journal_tags', 'source_field')
    op.drop_column('chat_sessions', 'npc_entity_id')
    op.drop_column('chat_sessions', 'archived_at')
    op.drop_column('campaign_share_tokens', 'access_epoch')
    op.drop_column('campaign_share_tokens', 'expires_at')
    op.drop_column('campaign_share_tokens', 'role')
    op.drop_column('campaign_members', 'access_epoch')
    op.drop_column('campaign_members', 'role')
    for table, _ in reversed(VISIBILITY_COLUMNS):
        op.drop_column(table, 'visibility')
    op.drop_index('ix_journal_party_fts', table_name='journal_entries', postgresql_using='gin')
    op.drop_column('journal_entries', 'party_embedding')
    op.drop_column('journal_entries', 'party_tsv')
    op.drop_constraint('ck_journal_entries_kind', 'journal_entries', type_='check')
    op.drop_column('journal_entries', 'kind')

    op.execute("DROP TYPE campaign_role")
    op.execute("DROP TYPE visibility")
