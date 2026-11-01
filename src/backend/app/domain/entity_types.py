"""The Entity Type registry: the one source of truth for the World Model.

For each of the five Entity Types it fixes the status vocabulary (each status
with a category), the default status, the Character kinds, and the typed
`attributes` keys. Everything that stores, validates or renders an Entity
(migrations, world_service, access.project, Jobs, the graph and analytics)
reads these instead of keeping its own copy (FR-11, AR-9).

Status is a plain text column, so validate_status() is its only check; the
closed sets that are CHECK constraints live in app.domain.enums (AD-9).

Hidden renders as unset (AD-13): party_unset() gives the value a Party view
shows for a field the viewer may not see, identical to the field never having
been set: status -> the type's default status ("unknown", Quest "active"),
description and gm_notes -> None, aliases -> [], and an attribute -> ABSENT,
meaning the key is dropped from `attributes`. party_view() applies it to a
whole field dict. `name` is never hidden, so asking for it raises.
"""
from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from app.domain.enums import CharacterKind, EntityType, LocationKind


class StatusCategory(StrEnum):
    OPEN = "open"
    CLOSED_SUCCESS = "closed_success"
    CLOSED_FAILURE = "closed_failure"
    CLOSED_OTHER = "closed_other"


class ValueKind(StrEnum):
    """The type of an `attributes` value."""

    TEXT = "text"
    ENTITY_REF = "entity_ref"  # an Entity id in the same Campaign
    DATETIME = "datetime"  # ISO 8601, UTC
    CHOICE = "choice"  # one of the attribute's `choices` (a closed set)


class InvalidStatusError(ValueError):
    """A status that is not in the Entity Type's vocabulary."""

    def __init__(self, entity_type: EntityType, status: object) -> None:
        allowed = ", ".join(s.key for s in REGISTRY[entity_type].statuses)
        super().__init__(f"{status!r} is not a {entity_type.value} status (allowed: {allowed})")
        self.entity_type = entity_type
        self.status = status


@dataclass(frozen=True, slots=True)
class StatusDef:
    key: str
    category: StatusCategory
    label: str


@dataclass(frozen=True, slots=True)
class AttributeDef:
    key: str
    value_kind: ValueKind
    label: str
    # The Entity Types an ENTITY_REF may point at; empty for other kinds.
    target_types: tuple[EntityType, ...] = ()
    # The allowed values of a CHOICE, in display order; empty for other kinds.
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.value_kind is ValueKind.ENTITY_REF) != bool(self.target_types):
            raise ValueError(f"attribute {self.key!r}: target_types is required for, and only for, entity_ref")
        if (self.value_kind is ValueKind.CHOICE) != bool(self.choices):
            raise ValueError(f"attribute {self.key!r}: choices is required for, and only for, choice")
        if len(self.choices) != len(set(self.choices)):
            raise ValueError(f"attribute {self.key!r}: duplicate choice")


@dataclass(frozen=True, slots=True)
class EntityTypeDef:
    type: EntityType
    label: str
    statuses: tuple[StatusDef, ...]
    default_status: str
    attributes: tuple[AttributeDef, ...]
    kinds: tuple[CharacterKind, ...] = field(default=())

    def __post_init__(self) -> None:
        keys = [s.key for s in self.statuses]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.type}: duplicate status")
        if self.default_status not in keys:
            raise ValueError(f"{self.type}: default status {self.default_status!r} is not one of its statuses")
        attr_keys = [a.key for a in self.attributes]
        if len(attr_keys) != len(set(attr_keys)):
            raise ValueError(f"{self.type}: duplicate attribute key")


class _Absent:
    """Singleton: "drop this key" in a Party rendering of `attributes`."""

    _instance: _Absent | None = None

    def __new__(cls) -> _Absent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ABSENT"

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> _Absent:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _Absent:
        return self

    def __reduce__(self) -> str:
        return "ABSENT"


ABSENT: Final = _Absent()

_O, _CS, _CF, _CO = (StatusCategory.OPEN, StatusCategory.CLOSED_SUCCESS,
                     StatusCategory.CLOSED_FAILURE, StatusCategory.CLOSED_OTHER)
_C, _L, _F, _I, _Q = (EntityType.CHARACTER, EntityType.LOCATION, EntityType.FACTION,
                      EntityType.ITEM, EntityType.QUEST)


def _ref(key: str, label: str, *targets: EntityType) -> AttributeDef:
    return AttributeDef(key, ValueKind.ENTITY_REF, label, targets)


def _text(key: str, label: str) -> AttributeDef:
    return AttributeDef(key, ValueKind.TEXT, label)


# Every attribute, like every other hideable field, can be GM-only: a Party
# view drops it (party_unset -> ABSENT), so goals or a voice can stay secret.
# Memberships (an NPC in a Faction, a PC in the party) are not attributes:
# they are relationship edges (F3, entity_relationships).


REGISTRY: Final[Mapping[EntityType, EntityTypeDef]] = MappingProxyType({
    _C: EntityTypeDef(
        type=_C,
        label="Character",
        statuses=(
            StatusDef("alive", _O, "Alive"),
            StatusDef("missing", _O, "Missing"),
            StatusDef("unknown", _O, "Unknown"),
            StatusDef("deceased", _CO, "Deceased"),
        ),
        default_status="unknown",
        attributes=(
            _text("species", "Species"),
            _text("occupation", "Occupation"),
            _ref("location_entity_id", "Location", _L),
            # Feeds Talk-to-NPC personas and narration.
            _text("voice", "Voice & mannerisms"),
            _text("appearance", "Appearance"),
            _text("pronouns", "Pronouns"),
            _text("goals", "Goals & motivation"),
        ),
        kinds=(CharacterKind.PC, CharacterKind.NPC, CharacterKind.CREATURE),
    ),
    _L: EntityTypeDef(
        type=_L,
        label="Location",
        statuses=(
            StatusDef("active", _O, "Active"),
            StatusDef("destroyed", _CO, "Destroyed"),
            StatusDef("unknown", _O, "Unknown"),
        ),
        default_status="unknown",
        attributes=(
            _text("region", "Region"),
            _ref("parent_location_entity_id", "Inside", _L),
            # attributes.kind, not the entities.kind column (Characters only).
            AttributeDef("kind", ValueKind.CHOICE, "Kind",
                         choices=tuple(k.value for k in LocationKind)),
        ),
    ),
    _F: EntityTypeDef(
        type=_F,
        label="Faction",
        statuses=(
            StatusDef("active", _O, "Active"),
            StatusDef("disbanded", _CO, "Disbanded"),
            StatusDef("unknown", _O, "Unknown"),
        ),
        default_status="unknown",
        attributes=(
            _ref("headquarters_entity_id", "Headquarters", _L),
            _ref("leader_entity_id", "Leader", _C),
            _text("goals", "Goals"),
        ),
    ),
    _I: EntityTypeDef(
        type=_I,
        label="Item",
        statuses=(
            StatusDef("active", _O, "Active"),
            StatusDef("destroyed", _CO, "Destroyed"),
            StatusDef("unknown", _O, "Unknown"),
        ),
        default_status="unknown",
        attributes=(
            _ref("holder_entity_id", "Held by", _C, _F),
            _ref("location_entity_id", "Location", _L),
            # Free text: "legendary", "cursed heirloom".
            _text("rarity", "Rarity"),
        ),
    ),
    _Q: EntityTypeDef(
        type=_Q,
        label="Quest",
        statuses=(
            StatusDef("active", _O, "Active"),
            StatusDef("completed", _CS, "Completed"),
            StatusDef("failed", _CF, "Failed"),
            StatusDef("abandoned", _CO, "Abandoned"),
        ),
        default_status="active",
        attributes=(
            _ref("giver_entity_id", "Given by", _C, _F),
            AttributeDef("completed_at", ValueKind.DATETIME, "Completed on"),
            _text("reward", "Reward"),
            _ref("location_entity_id", "Where", _L),
        ),
    ),
})

# Fields a Party view may hide (besides `attributes.<key>`) and their unset value.
_PARTY_UNSET_FIXED: Final[Mapping[str, Any]] = MappingProxyType({
    "description": None,
    "gm_notes": None,
})
_ATTR_PREFIX: Final = "attributes."


def _type(entity_type: EntityType | str) -> EntityType:
    try:
        return EntityType(entity_type)
    except ValueError:
        allowed = ", ".join(t.value for t in EntityType)
        raise ValueError(f"{entity_type!r} is not an Entity Type (allowed: {allowed})") from None


def get(entity_type: EntityType | str) -> EntityTypeDef:
    """The registry entry for a type; ValueError for an unknown type."""
    return REGISTRY[_type(entity_type)]


def statuses(entity_type: EntityType | str) -> tuple[str, ...]:
    """The type's status keys, in registry order."""
    return tuple(s.key for s in get(entity_type).statuses)


def _status_def(entity_type: EntityType | str, status: object) -> StatusDef:
    definition = get(entity_type)
    for s in definition.statuses:
        if s.key == status:
            return s
    raise InvalidStatusError(definition.type, status)


def validate_status(entity_type: EntityType | str, status: object) -> str:
    """`status` as a plain str when valid for the type, else InvalidStatusError."""
    return _status_def(entity_type, status).key


def status_category(entity_type: EntityType | str, status: object) -> StatusCategory:
    return _status_def(entity_type, status).category


def is_closed(entity_type: EntityType | str, status: object) -> bool:
    return status_category(entity_type, status) is not StatusCategory.OPEN


def default_status(entity_type: EntityType | str) -> str:
    return get(entity_type).default_status


def validate_kind(entity_type: EntityType | str, kind: object) -> CharacterKind | None:
    """A Character needs a kind; every other type must have none."""
    definition = get(entity_type)
    if not definition.kinds:
        if kind is not None:
            raise ValueError(f"a {definition.type.value} has no kind (got {kind!r})")
        return None
    allowed = ", ".join(k.value for k in definition.kinds)
    if kind is None:
        raise ValueError(f"a {definition.type.value} needs a kind ({allowed})")
    for k in definition.kinds:
        if k.value == kind:
            return k
    raise ValueError(f"{kind!r} is not a {definition.type.value} kind (allowed: {allowed})")


def attribute_keys(entity_type: EntityType | str) -> tuple[str, ...]:
    return tuple(a.key for a in get(entity_type).attributes)


def attribute(entity_type: EntityType | str, key: str) -> AttributeDef:
    definition = get(entity_type)
    for a in definition.attributes:
        if a.key == key:
            return a
    allowed = ", ".join(a.key for a in definition.attributes)
    raise ValueError(f"{key!r} is not a {definition.type.value} attribute (allowed: {allowed})")


def _check_value(entity_type: EntityType, a: AttributeDef, value: Any) -> Any:
    """`value` checked against its ValueKind (None is unset, always allowed);
    an ENTITY_REF comes back as its canonical UUID str."""
    if value is None:
        return None
    where = f"{entity_type.value} {a.key}"
    if a.value_kind is ValueKind.TEXT:
        if not isinstance(value, str):
            raise ValueError(f"{where} must be text, got {type(value).__name__}")
        return value
    if a.value_kind is ValueKind.CHOICE:
        if not isinstance(value, str) or value not in a.choices:
            raise ValueError(f"{value!r} is not a {where} (allowed: {', '.join(a.choices)})")
        return value
    if a.value_kind is ValueKind.DATETIME:
        if not isinstance(value, str):
            raise ValueError(f"{where} must be an ISO 8601 string, got {type(value).__name__}")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{where} is not an ISO 8601 date-time: {value!r}") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{where} needs a timezone: {value!r}")
        return value
    # ENTITY_REF: an Entity id (same Campaign and allowed type: world_service checks those).
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise ValueError(f"{where} must be an Entity id, got {type(value).__name__}")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise ValueError(f"{where} is not an Entity id: {value!r}") from None


def validate_attributes(entity_type: EntityType | str, attrs: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of `attrs` with every value checked against its ValueKind:
    TEXT a str, DATETIME an ISO 8601 str with a timezone, ENTITY_REF a UUID
    (returned as its canonical str), CHOICE one of its choices; None is
    unset for every kind. ValueError naming any key the type does not define
    or any value of the wrong type. That an ENTITY_REF names a live Entity of
    the same Campaign and an allowed type is world_service's check (it needs
    the database)."""
    definition = get(entity_type)
    known = set(attribute_keys(entity_type))
    unknown = sorted(k for k in attrs if k not in known)
    if unknown:
        allowed = ", ".join(attribute_keys(entity_type))
        raise ValueError(f"unknown {definition.type.value} attribute(s) {unknown} (allowed: {allowed})")
    out = dict(attrs)
    for a in definition.attributes:
        if a.key in out:
            out[a.key] = _check_value(definition.type, a, out[a.key])
    return out


def party_unset(entity_type: EntityType | str, field_name: str) -> Any:
    """What a Party view shows for a hidden field: exactly its unset value (AD-13).

    `status`, `description`, `aliases`, `gm_notes` or `attributes.<key>`;
    anything else (such as `name`, which is never hidden) raises ValueError.
    """
    definition = get(entity_type)
    if field_name == "status":
        return definition.default_status
    if field_name == "aliases":
        return []
    if field_name in _PARTY_UNSET_FIXED:
        return _PARTY_UNSET_FIXED[field_name]
    if field_name.startswith(_ATTR_PREFIX):
        attribute(definition.type, field_name[len(_ATTR_PREFIX):])
        return ABSENT
    raise ValueError(f"{field_name!r} has no Party unset value for a {definition.type.value}")


def party_view(entity_type: EntityType | str, fields: Mapping[str, Any],
               hidden: Iterable[str]) -> dict[str, Any]:
    """A deep copy of `fields` with every hidden field rendered as unset.

    A hidden `attributes.<key>` is removed from the copy's `attributes`; any
    other hidden field is set to its party_unset value. `fields` is not
    mutated. Unknown hidden fields raise ValueError, before anything is built.
    A Mapping `attributes` comes back as a plain dict; a missing or None one
    is left as is; any other `attributes` value raises TypeError.
    """
    if isinstance(hidden, str):
        raise TypeError("hidden must be a collection of field names, not a str")
    unset = {name: party_unset(entity_type, name) for name in hidden}
    source = dict(fields)
    attrs = source.get("attributes")
    if isinstance(attrs, Mapping):
        source["attributes"] = dict(attrs)
    elif attrs is not None:
        raise TypeError(f"attributes must be a mapping or None, not {type(attrs).__name__}")
    view = copy.deepcopy(source)
    for name, value in unset.items():
        if value is ABSENT:
            if view.get("attributes") is not None:
                view["attributes"].pop(name[len(_ATTR_PREFIX):], None)
        else:
            view[name] = value
    return view
