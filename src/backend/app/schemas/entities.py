"""World Model response schemas (E0-WorldCore.2): the GM and Party pairs
`app.access.project` renders the seven F3-world models through (AD-13).

A Party schema never names a GM field: no `gm_notes`, no `field_visibility`,
no Visibility columns, no provenance (`source_journal_id`, `actor_user_id`,
...) and no legacy ids. A field an Entity hides from the viewer through
`field_visibility` renders as its unset value (entity_types.party_view).

The write schemas (`CanonChange`, `EntityCreate`, `EntityPatch`) belong to
E0-WorldCore.3 and E0-WorldCore.5.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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
