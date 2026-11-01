"""Closed sets stored as text columns with a CHECK constraint (AD-9).

Apart from the `visibility` and `campaign_role` Postgres enums, every closed
set in the schema is a text column whose CHECK is generated from a StrEnum
here, via check_sql() (raw DDL) or check_expr() (sa.CheckConstraint). CI-10
(tests/test_enum_check_sync.py) compares each registered enum with the CHECK
it generated in the migrated schema; an enum whose column does not exist yet
is listed there as pending, with the story that adds the column.

Where each CHECK lives:

- EntityType         -> entities.type                    (E0-WorldCore.2)
- CharacterKind      -> entities.kind, Characters only   (E0-WorldCore.2)
- EntityChangeOp     -> entity_changes.op                (E0-WorldCore.2)
- MentionOrigin      -> entity_mentions.origin           (E0-WorldCore.2)
- MentionSourceField -> entity_mentions.source_field     (E0-WorldCore.2)
- TagSourceField     -> journal_tags.source_field        (E0-Access.1)
- EntryKind          -> journal_entries.kind             (E0-Access.1)

Two StrEnums mirror Postgres enum types instead of a CHECK (AD-12). The
F1-core revision (c95acb56c595) creates the types; models bind them with
postgresql.ENUM(create_type=False), and CI-10 compares each StrEnum with the
type's pg_enum labels:

- Visibility   -> PG enum `visibility`: journal_entries, character_sheets,
                  session_plans, source_documents, shorthand_terms,
                  tag_categories (E0-Access.1)
- CampaignRole -> PG enum `campaign_role`: campaign_members.role,
                  campaign_share_tokens.role (E0-Access.1)

RC-12: the two `source_field` enums keep distinct names and classes.
MentionSourceField says which part of a journal entry a Mention came from;
TagSourceField says how a journal tag was added. The planning (RC-12) put
the `journal_tags.source_field` enum, and `kind`, in app/access/enums.py;
they are defined here instead, because the models (app.db) import them and
app.domain is the only layer below app.db (AD-1). Nothing else defines them.

Entity statuses are not an enum: they are plain text, checked per type by
app.domain.entity_types.validate_status.
"""
from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    FACTION = "faction"
    ITEM = "item"
    QUEST = "quest"


class CharacterKind(StrEnum):
    """Only Characters have a kind; every other type stores NULL."""

    PC = "pc"
    NPC = "npc"
    CREATURE = "creature"


class EntityChangeOp(StrEnum):
    """The `op` of an entity_changes row: the E0-WorldCore.3 CanonChange ops."""

    CREATE_ENTITY = "create_entity"
    UPDATE_FIELD = "update_field"
    SET_STATUS = "set_status"
    SET_KIND = "set_kind"
    ADD_ALIAS = "add_alias"
    REMOVE_ALIAS = "remove_alias"
    ADD_RELATIONSHIP = "add_relationship"
    UPDATE_RELATIONSHIP = "update_relationship"
    END_RELATIONSHIP = "end_relationship"
    ADD_QUEST_STEP = "add_quest_step"
    UPDATE_QUEST_STEP = "update_quest_step"
    ADD_MENTION = "add_mention"
    CONFIRM_MENTION = "confirm_mention"
    REMOVE_MENTION = "remove_mention"
    DELETE_ENTITY = "delete_entity"
    MERGE = "merge"
    REVERT = "revert"
    SOURCE_DELETED = "source_deleted"
    CANON_NOTE = "canon_note"
    # Written only by the F3-world legacy NPC/Quest copy.
    MIGRATED = "migrated"


class MentionOrigin(StrEnum):
    """What created an entity_mentions row."""

    MIGRATION = "migration"
    EXTRACTION = "extraction"
    MANUAL = "manual"


class MentionSourceField(StrEnum):
    """Which part of a journal entry a Mention was found in (RC-12)."""

    NARRATIVE = "narrative"
    SHORTHAND = "shorthand"
    GM_NOTES = "gm_notes"


class TagSourceField(StrEnum):
    """How a journal tag was added (journal_tags.source_field, RC-12)."""

    SHORTHAND = "shorthand"
    NARRATIVE = "narrative"
    MANUAL = "manual"


class EntryKind(StrEnum):
    """Who wrote a journal entry (journal_entries.kind)."""

    GM = "gm"
    PLAYER = "player"


class Visibility(StrEnum):
    """Mirror of the Postgres enum `visibility` (AD-12)."""

    PARTY = "party"
    GM = "gm"
    PRIVATE = "private"


class CampaignRole(StrEnum):
    """Mirror of the Postgres enum `campaign_role` (AD-12). The Owner has no
    campaign_members row, so `owner` is not a stored Role."""

    CO_GM = "co_gm"
    PLAYER = "player"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def check_expr(enum: type[StrEnum], column: str) -> str:
    """`column IN ('a', 'b', ...)` in definition order, for sa.CheckConstraint."""
    values = [m.value for m in enum]
    if not values:
        raise ValueError(f"{enum.__name__} has no members")
    return f"{column} IN ({', '.join(_literal(v) for v in values)})"


def check_sql(enum: type[StrEnum], column: str) -> str:
    """`CHECK (column IN ('a', 'b', ...))`, the DDL a migration uses (AD-9)."""
    return f"CHECK ({check_expr(enum, column)})"
