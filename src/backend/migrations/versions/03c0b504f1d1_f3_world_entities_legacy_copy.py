"""F3-world: entities, mentions, relationships, history and the legacy NPC/Quest copy (E0-WorldCore.2)

Revision ID: 03c0b504f1d1
Revises: cf62d979bc8a
Create Date: 2026-11-01 14:12:47.681039

The third foundation revision (AD-19). It creates the seven World Model
tables, adds the two Entity FKs F1-core deferred (character_sheets.pc_entity_id,
chat_sessions.npc_entity_id), and copies every legacy `npcs` and `quests` row
into `entities` with set-based SQL only (AD-18).

Every Entity reference is the composite `(campaign_id, x) -> entities(campaign_id, id)`,
so a link across Campaigns fails at insert (FR-4). A nullable Entity link
uses `ON DELETE SET NULL (x)` (PG15+), so deleting the Entity never nulls the
row's campaign_id. A chat that loses its Campaign (campaign_id SET NULL) also
loses its NPC link, through a BEFORE trigger (CHAT_NPC_DDL). FKs to campaigns cascade; to journal_entries and users
they SET NULL. legacy_npc_id / legacy_quest_id have no FK: deleting a legacy
row must never reach the world.

The copy (OD-1 option A): every copied Entity is `visibility = gm` with
`field_visibility = {}`. NPC roles npc/pc/monster become Characters of kind
npc/pc/creature, role faction becomes a Faction (no kind); NPC status
alive/dead/unknown maps to alive/deceased/unknown (a Faction: active/disbanded/
unknown); a Quest keeps its status, and a completed one gets
`attributes.completed_at` = its updated_at (ISO 8601 UTC). `notes` becomes
`gm_notes`. A value the copy cannot map takes the type's default status
(`unknown`, a Quest `active`) or kind `npc`, is logged by upgrade() (online
mode only) and never fails the revision.

Ids are `md5(<namespace>:<legacy id>)::uuid` and every insert is guarded
(NOT EXISTS / ON CONFLICT DO NOTHING), so re-applying DATA_STEPS, or a
downgrade and upgrade, gives identical rows. Each copied Entity gets one
`migrated` entity_changes row (actor: the Campaign Owner, created_at: the
legacy row's created_at). Every Campaign gets the six default
relationship_types, and data_backfills gets `suggested_mentions_v1`
(status `queued`, the schema's "pending"), consumed by E0-WorldCore.7.

`npcs` and `quests` are not changed: they are frozen from here on (AD-18,
tests/test_legacy_frozen.py).

downgrade() is for development only; production is forward-only (NFR-8).
It drops exactly the seven tables and the two FKs, the chat trigger, and the
backfill row it inserted.
"""
from __future__ import annotations

import logging
from enum import StrEnum
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.domain.enums import check_sql

# revision identifiers, used by Alembic.
revision: str = '03c0b504f1d1'
down_revision: Union[str, None] = 'cf62d979bc8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration.f3_world")

visibility = postgresql.ENUM('party', 'gm', 'private', name='visibility', create_type=False)

# Frozen copies of the StrEnums, so a later member never changes this revision's CHECKs.
_EntityType = StrEnum("EntityType", {
    "CHARACTER": "character", "LOCATION": "location", "FACTION": "faction", "ITEM": "item", "QUEST": "quest"})
_CharacterKind = StrEnum("CharacterKind", {"PC": "pc", "NPC": "npc", "CREATURE": "creature"})
_EntityChangeOp = StrEnum("EntityChangeOp", {
    "CREATE_ENTITY": "create_entity",
    "UPDATE_FIELD": "update_field",
    "SET_STATUS": "set_status",
    "SET_KIND": "set_kind",
    "ADD_ALIAS": "add_alias",
    "REMOVE_ALIAS": "remove_alias",
    "ADD_RELATIONSHIP": "add_relationship",
    "UPDATE_RELATIONSHIP": "update_relationship",
    "END_RELATIONSHIP": "end_relationship",
    "ADD_QUEST_STEP": "add_quest_step",
    "UPDATE_QUEST_STEP": "update_quest_step",
    "ADD_MENTION": "add_mention",
    "CONFIRM_MENTION": "confirm_mention",
    "REMOVE_MENTION": "remove_mention",
    "DELETE_ENTITY": "delete_entity",
    "MERGE": "merge",
    "REVERT": "revert",
    "SOURCE_DELETED": "source_deleted",
    "CANON_NOTE": "canon_note",
    "MIGRATED": "migrated",
})
_MentionOrigin = StrEnum("MentionOrigin", {"MIGRATION": "migration", "EXTRACTION": "extraction", "MANUAL": "manual"})
_MentionSourceField = StrEnum(
    "MentionSourceField", {"NARRATIVE": "narrative", "SHORTHAND": "shorthand", "GM_NOTES": "gm_notes"})

# (table, constraint, enum, column)
CHECKS = (
    ('entities', 'ck_entities_type', _EntityType, 'type'),
    ('entities', 'ck_entities_kind', _CharacterKind, 'kind'),
    ('entity_mentions', 'ck_entity_mentions_source_field', _MentionSourceField, 'source_field'),
    ('entity_mentions', 'ck_entity_mentions_origin', _MentionOrigin, 'origin'),
    ('entity_changes', 'ck_entity_changes_op', _EntityChangeOp, 'op'),
)
# Only Characters have a kind, and every Character has one.
KIND_ONLY_CHARACTERS = ('ck_entities_kind_only_characters', "(type = 'character') = (kind IS NOT NULL)")
# The two JSONB maps are always objects (projection reads them as dicts).
ENTITY_OBJECT_CHECKS = (
    ('ck_entities_attributes_object', "jsonb_typeof(attributes) = 'object'"),
    ('ck_entities_field_visibility_object', "jsonb_typeof(field_visibility) = 'object'"),
)

TABLES = ('entities', 'entity_aliases', 'entity_mentions', 'relationship_types', 'entity_relationships',
          'quest_steps', 'entity_changes')

# The nullable Entity links: (table, constraint, column). ON DELETE SET NULL (column)
# keeps campaign_id; SQLAlchemy cannot spell the column list, so these are raw DDL.
SET_NULL_ENTITY_LINKS = (
    ('entities', 'fk_entities_merged_into', 'merged_into_id'),
    ('character_sheets', 'fk_character_sheets_pc_entity', 'pc_entity_id'),
    ('chat_sessions', 'fk_chat_sessions_npc_entity', 'npc_entity_id'),
)
DEFERRED_FKS = SET_NULL_ENTITY_LINKS[1:]  # the two F1-core added without an FK

# A chat whose Campaign is deleted keeps its row (campaign_id SET NULL), but
# then the composite NPC link no longer matches anything (MATCH SIMPLE skips
# a row with a NULL key) and would be left dangling, whichever RI trigger
# fires first. A chat without a Campaign has no NPC.
CHAT_NPC_TRIGGER = 'trg_chat_sessions_npc_needs_campaign'
CHAT_NPC_FUNCTION = 'chat_sessions_npc_needs_campaign'
CHAT_NPC_DDL = (
    f"""
    CREATE FUNCTION {CHAT_NPC_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NEW.campaign_id IS NULL THEN
            NEW.npc_entity_id := NULL;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    f"""
    CREATE TRIGGER {CHAT_NPC_TRIGGER} BEFORE INSERT OR UPDATE OF campaign_id, npc_entity_id ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION {CHAT_NPC_FUNCTION}()
    """,
)

BACKFILL_NAME = 'suggested_mentions_v1'

# key, label, inverse_label, hostile (RC-13: only enemy_of is hostile).
DEFAULT_RELATIONSHIP_TYPES = (
    ('ally_of', 'Ally of', 'Ally of', False),
    ('enemy_of', 'Enemy of', 'Enemy of', True),
    ('member_of', 'Member of', 'Has member', False),
    ('located_in', 'Located in', 'Contains', False),
    ('owns', 'Owns', 'Owned by', False),
    ('related_to', 'Related to', 'Related to', False),
)

# Deterministic ids: md5(<namespace>:<key>)::uuid.
NS = 'f3-world'


def _id(kind: str, key_sql: str) -> str:
    return f"md5('{NS}:{kind}:' || {key_sql})::uuid"


# ISO 8601 UTC, e.g. 2026-01-15T18:30:00.000000Z.
_ISO_UTC = "to_char({col} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"

# Legacy value -> new value. Anything else falls to the ELSE branch (and is
# reported by _warn_unmapped). role/status are PG enums: compare as text.
_NPC_KIND = ("CASE n.role::text WHEN 'npc' THEN 'npc' WHEN 'pc' THEN 'pc' "
             "WHEN 'monster' THEN 'creature' ELSE 'npc' END")
_CHARACTER_STATUS = ("CASE n.status::text WHEN 'alive' THEN 'alive' WHEN 'dead' THEN 'deceased' "
                     "WHEN 'unknown' THEN 'unknown' ELSE 'unknown' END")
_FACTION_STATUS = ("CASE n.status::text WHEN 'alive' THEN 'active' WHEN 'dead' THEN 'disbanded' "
                   "WHEN 'unknown' THEN 'unknown' ELSE 'unknown' END")
_QUEST_STATUS = ("CASE WHEN q.status::text IN ('active', 'completed', 'failed', 'abandoned') "
                 "THEN q.status::text ELSE 'active' END")

_MAPPED_ROLES = ('npc', 'pc', 'monster', 'faction')
_MAPPED_NPC_STATUSES = ('alive', 'dead', 'unknown')
_MAPPED_QUEST_STATUSES = ('active', 'completed', 'failed', 'abandoned')


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


_RELATIONSHIP_VALUES = ", ".join(
    f"('{key}', '{label}', '{inverse}', {'true' if hostile else 'false'})"
    for key, label, inverse, hostile in DEFAULT_RELATIONSHIP_TYPES
)

# Set-based, idempotent data steps (AD-18). Every insert is guarded.
DATA_STEPS: tuple[str, ...] = (
    # NPCs -> Characters and Factions.
    f"""
    INSERT INTO entities (id, campaign_id, type, kind, name, description, status, attributes, gm_notes,
                          visibility, field_visibility, legacy_npc_id, created_by_user_id, created_at, updated_at)
    SELECT {_id('npc', 'n.id::text')}, n.campaign_id,
           CASE WHEN n.role::text = 'faction' THEN 'faction' ELSE 'character' END,
           CASE WHEN n.role::text = 'faction' THEN NULL ELSE {_NPC_KIND} END,
           n.name, n.description,
           CASE WHEN n.role::text = 'faction' THEN {_FACTION_STATUS} ELSE {_CHARACTER_STATUS} END,
           '{{}}'::jsonb, n.notes, 'gm', '{{}}'::jsonb, n.id, n.user_id, n.created_at, n.updated_at
    FROM npcs AS n
    WHERE NOT EXISTS (SELECT 1 FROM entities AS e WHERE e.legacy_npc_id = n.id)
    ON CONFLICT DO NOTHING
    """,
    # Quests -> Quests. A completed Quest records when it was completed.
    f"""
    INSERT INTO entities (id, campaign_id, type, kind, name, description, status, attributes, gm_notes,
                          visibility, field_visibility, legacy_quest_id, created_by_user_id, created_at, updated_at)
    SELECT {_id('quest', 'q.id::text')}, q.campaign_id, 'quest', NULL, q.title, q.description,
           {_QUEST_STATUS},
           CASE WHEN q.status::text = 'completed'
                THEN jsonb_build_object('completed_at', {_ISO_UTC.format(col='q.updated_at')})
                ELSE '{{}}'::jsonb END,
           q.notes, 'gm', '{{}}'::jsonb, q.id, q.user_id, q.created_at, q.updated_at
    FROM quests AS q
    WHERE NOT EXISTS (SELECT 1 FROM entities AS e WHERE e.legacy_quest_id = q.id)
    ON CONFLICT DO NOTHING
    """,
    # One `migrated` history row per copied Entity ("Came over from your NPC list").
    f"""
    INSERT INTO entity_changes (id, campaign_id, entity_id, op, field, old_value, new_value, actor_user_id,
                                created_at)
    SELECT {_id('migrated', 'e.id::text')}, e.campaign_id, e.id, 'migrated', NULL, NULL,
           CASE WHEN e.legacy_npc_id IS NOT NULL
                THEN jsonb_build_object('from', 'npcs')
                ELSE jsonb_build_object('from', 'quests') END,
           c.user_id, e.created_at
    FROM entities AS e
    JOIN campaigns AS c ON c.id = e.campaign_id
    WHERE (e.legacy_npc_id IS NOT NULL OR e.legacy_quest_id IS NOT NULL)
      AND NOT EXISTS (SELECT 1 FROM entity_changes AS ch WHERE ch.entity_id = e.id AND ch.op = 'migrated')
    ON CONFLICT DO NOTHING
    """,
    # The default relationship types of every Campaign.
    f"""
    INSERT INTO relationship_types (id, campaign_id, key, label, inverse_label, hostile)
    SELECT {_id('relationship_type', "c.id::text || ':' || v.key")}, c.id, v.key, v.label, v.inverse_label,
           v.hostile
    FROM campaigns AS c
    CROSS JOIN (VALUES {_RELATIONSHIP_VALUES}) AS v (key, label, inverse_label, hostile)
    ON CONFLICT DO NOTHING
    """,
    # The suggested-Mentions backfill (E0-WorldCore.7), "pending" = queued.
    f"""
    INSERT INTO data_backfills (name, status) VALUES ('{BACKFILL_NAME}', 'queued')
    ON CONFLICT (name) DO NOTHING
    """,
)

# The rows the copy cannot map exactly (they take a default instead).
UNMAPPED_SQL = (
    ("npcs", f"""
     SELECT n.id::text, n.campaign_id::text, n.role::text, n.status::text FROM npcs AS n
     WHERE n.role::text NOT IN {_in(_MAPPED_ROLES)} OR n.status::text NOT IN {_in(_MAPPED_NPC_STATUSES)}
     ORDER BY n.id"""),
    ("quests", f"""
     SELECT q.id::text, q.campaign_id::text, NULL, q.status::text FROM quests AS q
     WHERE q.status::text NOT IN {_in(_MAPPED_QUEST_STATUSES)}
     ORDER BY q.id"""),
)


def unmapped_rows(bind) -> list[tuple[str, str, str, str | None, str]]:
    """(table, id, campaign_id, role, status) for every legacy row the copy maps to a default."""
    out = []
    for table, sql in UNMAPPED_SQL:
        for row_id, campaign_id, role, status in bind.execute(sa.text(sql)).all():
            out.append((table, row_id, campaign_id, role, status))
    return out


def _warn_unmapped(bind) -> None:
    for table, row_id, campaign_id, role, status in unmapped_rows(bind):
        logger.warning(
            "f3-world copy: %s row %s (campaign %s) has an unmapped value (role=%r, status=%r); "
            "it takes the type's default", table, row_id, campaign_id, role, status)


def apply_data_steps(bind) -> None:
    """Run DATA_STEPS on a sync Connection (the idempotency tests re-run them)."""
    for step in DATA_STEPS:
        bind.execute(sa.text(step))


def _now() -> sa.TextClause:
    return sa.text('now()')


def _jsonb_empty() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def _entity_fk(column: str, name: str, ondelete: str = 'CASCADE') -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(['campaign_id', column], ['entities.campaign_id', 'entities.id'],
                                   name=name, ondelete=ondelete)


def _campaign_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE')


def _journal_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ['journal_entries.id'], ondelete='SET NULL')


def upgrade() -> None:
    op.create_table(
        'entities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=_jsonb_empty()),
        sa.Column('gm_notes', sa.Text(), nullable=True),
        sa.Column('visibility', visibility, nullable=False, server_default='gm'),
        sa.Column('field_visibility', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=_jsonb_empty()),
        sa.Column('linked_user_id', sa.UUID(), nullable=True),
        sa.Column('merged_into_id', sa.UUID(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('legacy_npc_id', sa.UUID(), nullable=True),
        sa.Column('legacy_quest_id', sa.UUID(), nullable=True),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        _campaign_fk(),
        sa.ForeignKeyConstraint(['linked_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        # The composite-FK target of every Entity reference.
        sa.UniqueConstraint('campaign_id', 'id', name='uq_entities_campaign_id_id'),
        sa.UniqueConstraint('legacy_npc_id', name='uq_entities_legacy_npc_id'),
        sa.UniqueConstraint('legacy_quest_id', name='uq_entities_legacy_quest_id'),
    )
    op.create_index('ix_entities_campaign_type', 'entities', ['campaign_id', 'type'])

    op.create_table(
        'entity_aliases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('alias', sa.Text(), nullable=False),
        sa.Column('normalized_alias', sa.Text(), nullable=False),
        sa.Column('visibility_floor', visibility, nullable=True),
        _campaign_fk(),
        _entity_fk('entity_id', 'fk_entity_aliases_entity'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'entity_id', 'normalized_alias',
                            name='uq_entity_aliases_campaign_entity_alias'),
    )
    op.create_index('ix_entity_aliases_campaign_normalized', 'entity_aliases', ['campaign_id', 'normalized_alias'])

    op.create_table(
        'entity_mentions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('journal_id', sa.UUID(), nullable=True),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('quote', sa.Text(), nullable=True),
        sa.Column('source_field', sa.String(length=16), nullable=False),
        sa.Column('confirmed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('origin', sa.String(length=16), nullable=False),
        sa.Column('visibility_floor', visibility, nullable=True),
        sa.Column('span_start', sa.Integer(), nullable=True),
        sa.Column('span_end', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        _campaign_fk(),
        _journal_fk('journal_id'),
        _entity_fk('entity_id', 'fk_entity_mentions_entity'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_entity_mentions_campaign_entity', 'entity_mentions', ['campaign_id', 'entity_id'])
    op.create_index('ix_entity_mentions_journal', 'entity_mentions', ['journal_id'])

    op.create_table(
        'relationship_types',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('label', sa.Text(), nullable=False),
        sa.Column('inverse_label', sa.Text(), nullable=False),
        sa.Column('hostile', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        _campaign_fk(),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'key', name='uq_relationship_types_campaign_key'),
        sa.UniqueConstraint('campaign_id', 'id', name='uq_relationship_types_campaign_id_id'),
    )

    op.create_table(
        'entity_relationships',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('source_entity_id', sa.UUID(), nullable=False),
        sa.Column('target_entity_id', sa.UUID(), nullable=False),
        sa.Column('relationship_type_id', sa.UUID(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('visibility', visibility, nullable=False, server_default='gm'),
        sa.Column('visibility_floor', visibility, nullable=True),
        sa.Column('source_journal_id', sa.UUID(), nullable=True),
        sa.Column('source_deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        _campaign_fk(),
        _entity_fk('source_entity_id', 'fk_entity_relationships_source'),
        _entity_fk('target_entity_id', 'fk_entity_relationships_target'),
        # NO ACTION: a type in use cannot be deleted (E3.1 decides what to do with its edges).
        sa.ForeignKeyConstraint(['campaign_id', 'relationship_type_id'],
                                ['relationship_types.campaign_id', 'relationship_types.id'],
                                name='fk_entity_relationships_type'),
        _journal_fk('source_journal_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_entity_relationships_campaign_source', 'entity_relationships',
                    ['campaign_id', 'source_entity_id'])
    op.create_index('ix_entity_relationships_source_journal', 'entity_relationships', ['source_journal_id'])
    op.create_index('ix_entity_relationships_campaign_target', 'entity_relationships',
                    ['campaign_id', 'target_entity_id'])

    op.create_table(
        'quest_steps',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('quest_entity_id', sa.UUID(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('source_journal_id', sa.UUID(), nullable=True),
        sa.Column('source_deleted_at', sa.DateTime(timezone=True), nullable=True),
        _campaign_fk(),
        _entity_fk('quest_entity_id', 'fk_quest_steps_quest'),
        _journal_fk('source_journal_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_quest_steps_source_journal', 'quest_steps', ['source_journal_id'])
    op.create_index('ix_quest_steps_campaign_quest_position', 'quest_steps',
                    ['campaign_id', 'quest_entity_id', 'position'])

    op.create_table(
        'entity_changes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('campaign_id', sa.UUID(), nullable=False),
        sa.Column('entity_id', sa.UUID(), nullable=False),
        sa.Column('op', sa.String(length=32), nullable=False),
        sa.Column('field', sa.Text(), nullable=True),
        sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_journal_id', sa.UUID(), nullable=True),
        sa.Column('source_deleted_at', sa.DateTime(timezone=True), nullable=True),
        # No FK: proposals (E1) and canon notes (E2) are later epics' tables.
        sa.Column('proposal_id', sa.UUID(), nullable=True),
        sa.Column('canon_note_id', sa.UUID(), nullable=True),
        sa.Column('actor_user_id', sa.UUID(), nullable=True),
        sa.Column('reverted_change_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_now()),
        _campaign_fk(),
        _entity_fk('entity_id', 'fk_entity_changes_entity'),
        _journal_fk('source_journal_id'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reverted_change_id'], ['entity_changes.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_entity_changes_campaign_entity_created', 'entity_changes',
                    ['campaign_id', 'entity_id', 'created_at'])
    op.create_index('ix_entity_changes_proposal', 'entity_changes', ['proposal_id'])
    op.create_index('ix_entity_changes_canon_note', 'entity_changes', ['canon_note_id'])
    op.create_index('ix_entity_changes_source_journal', 'entity_changes', ['source_journal_id'])

    for table, name, enum, column in CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} " + check_sql(enum, column))
    op.execute(f"ALTER TABLE entities ADD CONSTRAINT {KIND_ONLY_CHARACTERS[0]} CHECK ({KIND_ONLY_CHARACTERS[1]})")
    for name, expr in ENTITY_OBJECT_CHECKS:
        op.execute(f"ALTER TABLE entities ADD CONSTRAINT {name} CHECK ({expr})")

    # F1-core added pc_entity_id / npc_entity_id with no FK, so a value may
    # name nothing; it cannot name an Entity (there were none), so it goes.
    for table, _name, column in DEFERRED_FKS:
        op.execute(
            f"UPDATE {table} AS t SET {column} = NULL WHERE t.{column} IS NOT NULL AND NOT EXISTS "
            f"(SELECT 1 FROM entities AS e WHERE e.campaign_id = t.campaign_id AND e.id = t.{column})")

    for table, name, column in SET_NULL_ENTITY_LINKS:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (campaign_id, {column}) "
            f"REFERENCES entities (campaign_id, id) ON DELETE SET NULL ({column})")

    for ddl in CHAT_NPC_DDL:
        op.execute(ddl)

    if not context.is_offline_mode():
        _warn_unmapped(op.get_bind())
    # The same statements as apply_data_steps(), through op so --sql works too.
    for step in DATA_STEPS:
        op.execute(step)


def downgrade() -> None:
    # Dev only (NFR-8). Indexes and constraints go with their tables; npcs
    # and quests were never changed.
    op.execute(f"DROP TRIGGER {CHAT_NPC_TRIGGER} ON chat_sessions")
    op.execute(f"DROP FUNCTION {CHAT_NPC_FUNCTION}()")
    for table, name, column in DEFERRED_FKS:
        # The Entities they name are about to go: a re-upgrade must not meet a dangling id.
        op.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} IS NOT NULL")
        op.drop_constraint(name, table, type_='foreignkey')
    # Only while untouched: a row the runner has started is not this revision's to remove.
    op.execute(f"DELETE FROM data_backfills WHERE name = '{BACKFILL_NAME}' "
               "AND status = 'queued' AND job_id IS NULL AND cursor IS NULL")
    for table in reversed(TABLES):
        op.drop_table(table)
