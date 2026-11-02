"""World Model response schemas (E0-WorldCore.2): the GM and Party pairs
`app.access.project` renders the seven F3-world models through (AD-13).

A Party schema never names a GM field: no `gm_notes`, no `field_visibility`,
no Visibility columns, no provenance (`source_journal_id`, `actor_user_id`,
...) and no legacy ids. A field an Entity hides from the viewer through
`field_visibility` renders as its unset value (entity_types.party_view).

`CanonChange` (E0-WorldCore.3) is the one write schema of the world: the
discriminated union (on `op`) of the 19 public ops `world_service.apply_change`
takes. The HTTP bodies (`EntityCreate`, `EntityPatch`) belong to
E0-WorldCore.5. A CanonChange never carries a Visibility value: Visibility
reaches apply_change only through `access.set_visibility` (the registry
writer). `migrated` is the F3-world copy's op and has no member.
"""
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.domain.enums import CharacterKind, EntityChangeOp, EntityType, MentionOrigin, MentionSourceField, Visibility

_ORM = {"from_attributes": True}


# ── entities ───────────────────────────────────────────────────────────────

class EntityGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    type: EntityType
    kind: CharacterKind | None
    name: str
    description: str | None
    status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    gm_notes: str | None
    visibility: Visibility
    field_visibility: dict[str, Any] = Field(default_factory=dict)
    linked_user_id: uuid.UUID | None
    merged_into_id: uuid.UUID | None
    deleted_at: datetime | None
    legacy_npc_id: uuid.UUID | None
    legacy_quest_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = _ORM


class EntityPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    type: EntityType
    kind: CharacterKind | None
    name: str
    description: str | None
    status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    # No merged_into_id: the survivor may be GM-only.
    created_at: datetime
    updated_at: datetime

    model_config = _ORM


# ── entity_aliases ─────────────────────────────────────────────────────────

class EntityAliasGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    entity_id: uuid.UUID
    alias: str
    normalized_alias: str
    visibility_floor: Visibility | None

    model_config = _ORM


class EntityAliasPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    entity_id: uuid.UUID
    alias: str

    model_config = _ORM


# ── entity_mentions ────────────────────────────────────────────────────────

class EntityMentionGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    journal_id: uuid.UUID | None
    entity_id: uuid.UUID
    quote: str | None
    source_field: MentionSourceField
    confirmed: bool
    origin: MentionOrigin
    visibility_floor: Visibility | None
    span_start: int | None
    span_end: int | None
    created_at: datetime

    model_config = _ORM


class EntityMentionPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    journal_id: uuid.UUID | None
    entity_id: uuid.UUID
    quote: str | None
    confirmed: bool
    span_start: int | None
    span_end: int | None
    created_at: datetime

    model_config = _ORM


# ── relationship_types ─────────────────────────────────────────────────────

class RelationshipTypeGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    key: str
    label: str
    inverse_label: str
    hostile: bool

    model_config = _ORM


class RelationshipTypePartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    key: str
    label: str
    inverse_label: str
    hostile: bool

    model_config = _ORM


# ── entity_relationships ───────────────────────────────────────────────────

class EntityRelationshipGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relationship_type_id: uuid.UUID
    note: str | None
    visibility: Visibility
    visibility_floor: Visibility | None
    source_journal_id: uuid.UUID | None
    source_deleted_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = _ORM


class EntityRelationshipPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relationship_type_id: uuid.UUID
    note: str | None
    started_at: datetime | None
    ended_at: datetime | None

    model_config = _ORM


# ── quest_steps ────────────────────────────────────────────────────────────

class QuestStepGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    quest_entity_id: uuid.UUID
    position: int
    text: str
    done: bool
    done_at: datetime | None
    source_journal_id: uuid.UUID | None
    source_deleted_at: datetime | None

    model_config = _ORM


class QuestStepPartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    quest_entity_id: uuid.UUID
    position: int
    text: str
    done: bool
    done_at: datetime | None

    model_config = _ORM


# ── entity_changes ─────────────────────────────────────────────────────────

class EntityChangeGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    entity_id: uuid.UUID
    op: EntityChangeOp
    field: str | None
    old_value: Any = None
    new_value: Any = None
    source_journal_id: uuid.UUID | None
    source_deleted_at: datetime | None
    proposal_id: uuid.UUID | None
    canon_note_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    reverted_change_id: uuid.UUID | None
    created_at: datetime

    model_config = _ORM


class EntityChangePartyResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    entity_id: uuid.UUID
    op: EntityChangeOp
    field: str | None
    old_value: Any = None
    new_value: Any = None
    created_at: datetime

    model_config = _ORM


# ── CanonChange (E0-WorldCore.3) ───────────────────────────────────────────

# Entity fields `update_field` may set (besides `attributes.<key>`). Status
# and kind have their own ops; Visibility only comes through set_visibility.
UPDATABLE_FIELDS = frozenset({"name", "description", "gm_notes"})
ATTRIBUTES_PREFIX = "attributes."
_VISIBILITY_NAMES = ("visibility", "field_visibility", "visibility_floor")
INT4_MAX = 2**31 - 1  # positions and spans are Postgres integer columns


class _Change(BaseModel):
    """What every op carries: its provenance (E1 approvals, E2 retcons)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_journal_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None
    canon_note_id: uuid.UUID | None = None
    # Stored on a Mention; for other ops there is no column (E1 keeps it on the proposal).
    quote: str | None = None


class CreateEntity(_Change):
    op: Literal["create_entity"] = "create_entity"
    # A caller-chosen id makes the create idempotent (an existing id returns its create row).
    entity_id: uuid.UUID | None = None
    type: EntityType
    kind: CharacterKind | None = None
    name: str = Field(min_length=1)
    description: str | None = None
    status: str | None = None  # None: the type's default status
    attributes: dict[str, Any] = Field(default_factory=dict)
    gm_notes: str | None = None

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class UpdateField(_Change):
    op: Literal["update_field"] = "update_field"
    entity_id: uuid.UUID
    field: str  # name, description, gm_notes or attributes.<key>
    value: Any = None

    @field_validator("field")
    @classmethod
    def _settable(cls, value: str) -> str:
        if value.split(".", 1)[0] in _VISIBILITY_NAMES:
            raise ValueError("Visibility is changed only through access.set_visibility")
        if value in UPDATABLE_FIELDS:
            return value
        if value.startswith(ATTRIBUTES_PREFIX) and len(value) > len(ATTRIBUTES_PREFIX) and "." not in value[
                len(ATTRIBUTES_PREFIX):]:
            return value
        raise ValueError(f"update_field cannot set {value!r} (one of {sorted(UPDATABLE_FIELDS)} or attributes.<key>)")


class SetStatus(_Change):
    op: Literal["set_status"] = "set_status"
    entity_id: uuid.UUID
    status: str


class SetKind(_Change):
    op: Literal["set_kind"] = "set_kind"
    entity_id: uuid.UUID
    kind: CharacterKind


class AddAlias(_Change):
    op: Literal["add_alias"] = "add_alias"
    entity_id: uuid.UUID
    alias: str = Field(min_length=1)


class RemoveAlias(_Change):
    op: Literal["remove_alias"] = "remove_alias"
    entity_id: uuid.UUID
    alias: str = Field(min_length=1)


class AddRelationship(_Change):
    op: Literal["add_relationship"] = "add_relationship"
    entity_id: uuid.UUID  # the source endpoint
    target_entity_id: uuid.UUID
    relationship_type_id: uuid.UUID
    note: str | None = None
    started_at: datetime | None = None


class UpdateRelationship(_Change):
    """Only the fields given are changed (at least one)."""

    op: Literal["update_relationship"] = "update_relationship"
    relationship_id: uuid.UUID
    relationship_type_id: uuid.UUID | None = None
    note: str | None = None
    started_at: datetime | None = None

    @model_validator(mode="after")
    def _something(self) -> "UpdateRelationship":
        if not self.model_fields_set & {"relationship_type_id", "note", "started_at"}:
            raise ValueError("update_relationship needs relationship_type_id, note or started_at")
        if "relationship_type_id" in self.model_fields_set and self.relationship_type_id is None:
            raise ValueError("relationship_type_id cannot be cleared")
        return self


class EndRelationship(_Change):
    op: Literal["end_relationship"] = "end_relationship"
    relationship_id: uuid.UUID
    ended_at: datetime | None = None  # None: now


class AddQuestStep(_Change):
    op: Literal["add_quest_step"] = "add_quest_step"
    entity_id: uuid.UUID  # the Quest
    text: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=0, le=INT4_MAX)  # None: after the last step
    done: bool = False


class UpdateQuestStep(_Change):
    """Only the fields given are changed (at least one)."""

    op: Literal["update_quest_step"] = "update_quest_step"
    step_id: uuid.UUID
    text: str | None = Field(default=None, min_length=1)
    done: bool | None = None
    position: int | None = Field(default=None, ge=0, le=INT4_MAX)

    @model_validator(mode="after")
    def _something(self) -> "UpdateQuestStep":
        given = self.model_fields_set & {"text", "done", "position"}
        if not given:
            raise ValueError("update_quest_step needs text, done or position")
        if any(getattr(self, name) is None for name in given):
            raise ValueError("update_quest_step: text, done and position cannot be null")
        return self


class AddMention(_Change):
    op: Literal["add_mention"] = "add_mention"
    entity_id: uuid.UUID
    journal_id: uuid.UUID
    source_field: MentionSourceField = MentionSourceField.NARRATIVE
    origin: MentionOrigin = MentionOrigin.MANUAL
    confirmed: bool = False
    span_start: int | None = Field(default=None, ge=0, le=INT4_MAX)
    span_end: int | None = Field(default=None, ge=0, le=INT4_MAX)

    @model_validator(mode="after")
    def _span(self) -> "AddMention":
        if (self.span_start is None) != (self.span_end is None):
            raise ValueError("span_start and span_end go together")
        if self.span_start is not None and self.span_end < self.span_start:
            raise ValueError("span_end is before span_start")
        return self


class ConfirmMention(_Change):
    op: Literal["confirm_mention"] = "confirm_mention"
    mention_id: uuid.UUID


class RemoveMention(_Change):
    op: Literal["remove_mention"] = "remove_mention"
    mention_id: uuid.UUID


class DeleteEntity(_Change):
    op: Literal["delete_entity"] = "delete_entity"
    entity_id: uuid.UUID


class Merge(_Change):
    """The merge primitive (system ctx `merge` only): `entity_id` is absorbed into `survivor_id`."""

    op: Literal["merge"] = "merge"
    entity_id: uuid.UUID
    survivor_id: uuid.UUID


class Revert(_Change):
    op: Literal["revert"] = "revert"
    change_id: uuid.UUID
    # Revert even when a later change touched the same field.
    force: bool = False


class SourceDeleted(_Change):
    """The journal entry `source_journal_id` is going away (system ctx
    `entry_deleted` only): flag the Entity's changes it sourced."""

    op: Literal["source_deleted"] = "source_deleted"
    entity_id: uuid.UUID
    field: str | None = None  # only that field's changes; None: every change of the entry

    @model_validator(mode="after")
    def _source(self) -> "SourceDeleted":
        if self.source_journal_id is None:
            raise ValueError("source_deleted needs source_journal_id")
        return self


class CanonNote(_Change):
    op: Literal["canon_note"] = "canon_note"
    entity_id: uuid.UUID
    note: str = Field(min_length=1)


CANON_CHANGE_TYPES: tuple[type[_Change], ...] = (
    CreateEntity, UpdateField, SetStatus, SetKind, AddAlias, RemoveAlias, AddRelationship, UpdateRelationship,
    EndRelationship, AddQuestStep, UpdateQuestStep, AddMention, ConfirmMention, RemoveMention, DeleteEntity, Merge,
    Revert, SourceDeleted, CanonNote,
)

CanonChange = Annotated[
    Union[CreateEntity, UpdateField, SetStatus, SetKind, AddAlias, RemoveAlias, AddRelationship, UpdateRelationship,
          EndRelationship, AddQuestStep, UpdateQuestStep, AddMention, ConfirmMention, RemoveMention, DeleteEntity,
          Merge, Revert, SourceDeleted, CanonNote],
    Field(discriminator="op"),
]

CANON_CHANGE: TypeAdapter[Any] = TypeAdapter(CanonChange)


def parse_canon_change(data: Any) -> Any:
    """A CanonChange member from a dict (or the member itself); pydantic's ValidationError otherwise."""
    if isinstance(data, CANON_CHANGE_TYPES):
        return data
    return CANON_CHANGE.validate_python(data)
