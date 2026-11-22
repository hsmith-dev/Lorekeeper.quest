"""World Model response schemas (E0-WorldCore.2): the GM and Party pairs
`app.access.project` renders the seven F3-world models through (AD-13).

A Party schema never names a GM field: no `gm_notes`, no `field_visibility`,
no Visibility columns, no provenance (`source_journal_id`, `actor_user_id`,
...) and no legacy ids. A field an Entity hides from the viewer through
`field_visibility` renders as its unset value (entity_types.party_view).

`CanonChange` (E0-WorldCore.3) is the one write schema of the world: the
discriminated union (on `op`) of the 19 public ops `world_service.apply_change`
takes. The HTTP bodies at the end (`EntityCreate`, `EntityPatch`, ...) are
E0-WorldCore.5's; the routes turn them into CanonChanges. A CanonChange never carries a Visibility value: Visibility
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
    # E0-WorldCore.5: the route fills these (each projected for ctx).
    aliases: list["EntityAliasGMResponse"] = Field(default_factory=list)
    steps: list["QuestStepGMResponse"] = Field(default_factory=list)
    mention_count: int = 0

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
    # No merged_into_id: the survivor may be GM-only. No created_at/updated_at
    # (E0-WorldCore.5, privacy first): they would date GM-only edits (gm_notes,
    # a hidden field, a Visibility change) and the time before publication.
    # E0-WorldCore.5: a hidden `aliases` field renders [] (as unset).
    aliases: list["EntityAliasPartyResponse"] = Field(default_factory=list)
    steps: list["QuestStepPartyResponse"] = Field(default_factory=list)
    mention_count: int = 0

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
    # E0-WorldCore.7: the Mention routes fill these (entry title from resolve_sources).
    entry_title: str | None = None
    entity_name: str | None = None
    entity_type: EntityType | None = None

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
    # E0-WorldCore.7: the Mention routes fill these (each as ctx may see it).
    entry_title: str | None = None
    entity_name: str | None = None
    entity_type: EntityType | None = None

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
    # The audience the row was written for (E0-WorldCore.5).
    write_visibility: Visibility

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


EntityGMResponse.model_rebuild()
EntityPartyResponse.model_rebuild()


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


# ── HTTP bodies (E0-WorldCore.5, app/api/routes/entities.py) ───────────────
#
# None of them takes a Visibility value for an Entity field: Visibility is
# changed only through the two visibility routes (access.set_visibility).

MAX_BULK_IDS = 500
MAX_PAGE = 200


def _non_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("must not be blank")
    return value


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityCreate(_Body):
    campaign_id: uuid.UUID
    type: EntityType
    kind: CharacterKind | None = None
    name: str = Field(min_length=1)
    description: str | None = None
    status: str | None = None  # None: the type's default status
    attributes: dict[str, Any] = Field(default_factory=dict)
    gm_notes: str | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _non_blank(value)


class EntityPatch(_Body):
    """Only the fields given change (at least one), all in one transaction."""

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    gm_notes: str | None = None
    status: str | None = None
    kind: CharacterKind | None = None
    attributes: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _non_blank(value)

    @model_validator(mode="after")
    def _something(self) -> "EntityPatch":
        given = self.model_fields_set & set(type(self).model_fields)
        if not given:
            raise ValueError("a patch needs at least one field")
        for name in ("name", "status", "kind", "attributes"):
            if name in given and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        if "attributes" in given and not self.attributes:
            raise ValueError("attributes needs at least one key")
        return self


class AliasCreate(_Body):
    alias: str = Field(min_length=1)

    @field_validator("alias")
    @classmethod
    def _alias_not_blank(cls, value: str | None) -> str | None:
        return _non_blank(value)


class StepCreate(_Body):
    text: str = Field(min_length=1)
    position: int | None = Field(default=None, ge=0, le=INT4_MAX)
    done: bool = False

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, value: str | None) -> str | None:
        return _non_blank(value)


class StepPatch(_Body):
    """Only the fields given change (at least one)."""

    text: str | None = Field(default=None, min_length=1)
    done: bool | None = None
    position: int | None = Field(default=None, ge=0, le=INT4_MAX)

    @model_validator(mode="after")
    def _something(self) -> "StepPatch":
        given = self.model_fields_set & {"text", "done", "position"}
        if not given:
            raise ValueError("a step patch needs text, done or position")
        if any(getattr(self, name) is None for name in given):
            raise ValueError("text, done and position cannot be null")
        return self


class RevertRequest(_Body):
    force: bool = False


class EntityVisibilityRequest(_Body):
    """One Entity, or one field of it (`description`, `status`, `attributes`, `aliases`)."""

    visibility: Visibility
    field: str | None = None


class BulkEntityVisibilityRequest(_Body):
    campaign_id: uuid.UUID
    entity_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    visibility: Visibility


class UpdatedResponse(BaseModel):
    updated: int


class EntityListGMResponse(BaseModel):
    items: list[EntityGMResponse]
    total: int
    limit: int
    offset: int


class EntityListPartyResponse(BaseModel):
    items: list[EntityPartyResponse]
    total: int
    limit: int
    offset: int


class EntityHistoryGMResponse(BaseModel):
    items: list[EntityChangeGMResponse]
    total: int
    limit: int
    offset: int


class EntityHistoryPartyResponse(BaseModel):
    items: list[EntityChangePartyResponse]
    total: int
    limit: int
    offset: int


# ── Merge (E0-WorldCore.9): GM-only request and response ───────────────────

class MergeRequest(_Body):
    """`POST /api/entities/{survivor_id}/merge`: absorb `absorbed_id` into the
    path's Entity; `preview` validates and reports without writing."""

    absorbed_id: uuid.UUID
    preview: bool = False


class MergeDowngrade(BaseModel):
    """A moved alias, Mention or Relationship whose Party audience the merge changes."""

    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["alias", "mention", "relationship"]
    id: uuid.UUID
    from_: Visibility = Field(alias="from")
    to: Visibility


class MergeRelationship(BaseModel):
    """A Relationship that moves to the survivor, with its ends after the merge."""

    id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relationship_type_id: uuid.UUID


class MergeResponse(BaseModel):
    """GM-only (no Party twin): a Player never reaches the merge route.
    `change_id` is the merge row (None for a preview); `aliases`,
    `mention_count` and `relationships` are the preview's extras."""

    survivor_id: uuid.UUID
    change_id: uuid.UUID | None = None
    downgrades: list[MergeDowngrade] = Field(default_factory=list)
    moved_counts: dict[str, int] = Field(default_factory=dict)
    warning: str | None = None
    revertible: bool = True
    aliases: list[str] | None = None
    mention_count: int | None = None
    relationships: list[MergeRelationship] | None = None
# ── Mention lists (E0-WorldCore.7) ─────────────────────────────────────────

class EntityMentionListGMResponse(BaseModel):
    items: list[EntityMentionGMResponse]
    total: int
    page: int
    page_size: int


class EntityMentionListPartyResponse(BaseModel):
    items: list[EntityMentionPartyResponse]
    total: int
    page: int
    page_size: int


class EntryMentionsGMResponse(BaseModel):
    items: list[EntityMentionGMResponse]


class EntryMentionsPartyResponse(BaseModel):
    items: list[EntityMentionPartyResponse]
