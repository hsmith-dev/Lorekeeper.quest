"""The World Model (F3-world, E0-WorldCore.2; AD-9, AD-10, AD-12, AD-19).

Seven tables, created by revision 03c0b504f1d1 (the models never emit DDL):

  entities              one row per Character, Location, Faction, Item or Quest
  entity_aliases        other names of an Entity
  entity_mentions       an Entity named in a journal entry
  relationship_types    a Campaign's relationship vocabulary
  entity_relationships  an edge between two Entities
  quest_steps           the steps of a Quest
  entity_changes        every change to the world (history, revert, provenance)

Every Entity reference is the composite `(campaign_id, x) -> entities(campaign_id, id)`,
so nothing links across Campaigns (FR-4). The migration declares the
nullable links `ON DELETE SET NULL (x)` (only x is nulled, never
campaign_id); Postgres reflects that as SET NULL, which is what the models
declare. Closed sets are text columns with CHECKs from app/domain/enums.py
(AD-9); `status` is checked per type by app.domain.entity_types.

Writes go through world_service.apply_change (E0-WorldCore.3); Visibility
writes through app.access.set_visibility. The relationships here are
view-only loaders (for app.access.audience_of).
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import VISIBILITY_ENUM, Base
from app.domain.enums import (
    CharacterKind, EntityChangeOp, EntityType, MentionOrigin, MentionSourceField, Visibility, check_expr,
)

_EMPTY = sql_text("'{}'::jsonb")
_FALSE = sql_text("false")


def _entity_fk(column: str, name: str, ondelete: str = "CASCADE") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["campaign_id", column], ["entities.campaign_id", "entities.id"],
                                name=name, ondelete=ondelete)


def _campaign_id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)


def _journal_ref() -> Mapped[uuid.UUID | None]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True)


def _to_entity(model: str, column: str) -> Any:
    """A view-only loader of the Entity `model.<column>` names (same Campaign)."""
    return relationship(
        "Entity", viewonly=True, lazy="raise",
        primaryjoin=f"and_(Entity.id == foreign({model}.{column}), "
                    f"Entity.campaign_id == foreign({model}.campaign_id))")


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(check_expr(EntityType, "type"), name="ck_entities_type"),
        CheckConstraint(check_expr(CharacterKind, "kind"), name="ck_entities_kind"),
        CheckConstraint("(type = 'character') = (kind IS NOT NULL)", name="ck_entities_kind_only_characters"),
        CheckConstraint("jsonb_typeof(attributes) = 'object'", name="ck_entities_attributes_object"),
        CheckConstraint("jsonb_typeof(field_visibility) = 'object'", name="ck_entities_field_visibility_object"),
        UniqueConstraint("campaign_id", "id", name="uq_entities_campaign_id_id"),
        UniqueConstraint("legacy_npc_id", name="uq_entities_legacy_npc_id"),
        UniqueConstraint("legacy_quest_id", name="uq_entities_legacy_quest_id"),
        _entity_fk("merged_into_id", "fk_entities_merged_into", ondelete="SET NULL"),
        Index("ix_entities_campaign_type", "campaign_id", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    type: Mapped[EntityType] = mapped_column(String(16), nullable=False)
    # Characters only (pc, npc, creature); NULL for every other type.
    kind: Mapped[CharacterKind | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Validated per type by app.domain.entity_types.validate_status.
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=_EMPTY)
    # Always GM (ALWAYS_GM_FIELDS): never in a Party schema.
    gm_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[Visibility] = mapped_column(
        VISIBILITY_ENUM, nullable=False, default=Visibility.GM, server_default=Visibility.GM.value)
    # {field: visibility}: a field hidden from a viewer renders as unset (AD-13).
    field_visibility: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=_EMPTY)
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The legacy row this Entity was copied from (no FK: AD-18).
    legacy_npc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    legacy_quest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class EntityAlias(Base):
    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("campaign_id", "entity_id", "normalized_alias", name="uq_entity_aliases_campaign_entity_alias"),
        _entity_fk("entity_id", "fk_entity_aliases_entity"),
        Index("ix_entity_aliases_campaign_normalized", "campaign_id", "normalized_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False)
    visibility_floor: Mapped[Visibility | None] = mapped_column(VISIBILITY_ENUM, nullable=True)

    entity: Mapped[Entity] = _to_entity("EntityAlias", "entity_id")


class EntityMention(Base):
    __tablename__ = "entity_mentions"
    __table_args__ = (
        CheckConstraint(check_expr(MentionSourceField, "source_field"), name="ck_entity_mentions_source_field"),
        CheckConstraint(check_expr(MentionOrigin, "origin"), name="ck_entity_mentions_origin"),
        _entity_fk("entity_id", "fk_entity_mentions_entity"),
        Index("ix_entity_mentions_campaign_entity", "campaign_id", "entity_id"),
        Index("ix_entity_mentions_journal", "journal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    journal_id: Mapped[uuid.UUID | None] = _journal_ref()
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_field: Mapped[MentionSourceField] = mapped_column(String(16), nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=_FALSE)
    origin: Mapped[MentionOrigin] = mapped_column(String(16), nullable=False)
    visibility_floor: Mapped[Visibility | None] = mapped_column(VISIBILITY_ENUM, nullable=True)
    span_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    journal: Mapped["JournalEntry | None"] = relationship(
        "JournalEntry", viewonly=True, lazy="raise", primaryjoin="JournalEntry.id == foreign(EntityMention.journal_id)")
    entity: Mapped[Entity] = _to_entity("EntityMention", "entity_id")


class RelationshipType(Base):
    __tablename__ = "relationship_types"
    __table_args__ = (
        UniqueConstraint("campaign_id", "key", name="uq_relationship_types_campaign_key"),
        UniqueConstraint("campaign_id", "id", name="uq_relationship_types_campaign_id_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    inverse_label: Mapped[str] = mapped_column(Text, nullable=False)
    # RC-13: E3 styles hostile edges apart; only the default enemy_of is hostile.
    hostile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=_FALSE)


class EntityRelationship(Base):
    __tablename__ = "entity_relationships"
    __table_args__ = (
        _entity_fk("source_entity_id", "fk_entity_relationships_source"),
        _entity_fk("target_entity_id", "fk_entity_relationships_target"),
        ForeignKeyConstraint(["campaign_id", "relationship_type_id"],
                             ["relationship_types.campaign_id", "relationship_types.id"],
                             name="fk_entity_relationships_type"),
        Index("ix_entity_relationships_campaign_source", "campaign_id", "source_entity_id"),
        Index("ix_entity_relationships_campaign_target", "campaign_id", "target_entity_id"),
        Index("ix_entity_relationships_source_journal", "source_journal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    source_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    relationship_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[Visibility] = mapped_column(
        VISIBILITY_ENUM, nullable=False, default=Visibility.GM, server_default=Visibility.GM.value)
    visibility_floor: Mapped[Visibility | None] = mapped_column(VISIBILITY_ENUM, nullable=True)
    source_journal_id: Mapped[uuid.UUID | None] = _journal_ref()
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_entity: Mapped[Entity] = _to_entity("EntityRelationship", "source_entity_id")
    target_entity: Mapped[Entity] = _to_entity("EntityRelationship", "target_entity_id")


class QuestStep(Base):
    __tablename__ = "quest_steps"
    __table_args__ = (
        _entity_fk("quest_entity_id", "fk_quest_steps_quest"),
        Index("ix_quest_steps_campaign_quest_position", "campaign_id", "quest_entity_id", "position"),
        Index("ix_quest_steps_source_journal", "source_journal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    quest_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=_FALSE)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_journal_id: Mapped[uuid.UUID | None] = _journal_ref()
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    quest: Mapped[Entity] = _to_entity("QuestStep", "quest_entity_id")


class EntityChange(Base):
    __tablename__ = "entity_changes"
    __table_args__ = (
        CheckConstraint(check_expr(EntityChangeOp, "op"), name="ck_entity_changes_op"),
        _entity_fk("entity_id", "fk_entity_changes_entity"),
        Index("ix_entity_changes_campaign_entity_created", "campaign_id", "entity_id", "created_at"),
        Index("ix_entity_changes_proposal", "proposal_id"),
        Index("ix_entity_changes_canon_note", "canon_note_id"),
        Index("ix_entity_changes_source_journal", "source_journal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = _campaign_id()
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    op: Mapped[EntityChangeOp] = mapped_column(String(32), nullable=False)
    # The Entity field the change touched (`status`, `gm_notes`, `attributes.region`, ...), or NULL.
    field: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    source_journal_id: Mapped[uuid.UUID | None] = _journal_ref()
    source_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # No FK: proposals (E1) and canon notes (E2) are later epics' tables.
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    canon_note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reverted_change_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entity_changes.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    entity: Mapped[Entity] = _to_entity("EntityChange", "entity_id")
