"""app/domain/entity_types.py: the Entity Type registry (E0-WorldCore.1, FR-11, AD-13)."""
from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path
from types import MappingProxyType

import pytest

from app.domain import entity_types as et
from app.domain.entity_types import (
    ABSENT,
    REGISTRY,
    AttributeDef,
    InvalidStatusError,
    StatusCategory,
    ValueKind,
)
from app.domain.enums import CharacterKind, EntityType

DEMO_SEED = Path(__file__).resolve().parents[4] / "seeds" / "demo_campaign.json"

O, CS, CF, CO = "open", "closed_success", "closed_failure", "closed_other"

# type -> [(status, category)], in registry order.
EXPECTED_STATUSES = {
    "character": [("alive", O), ("missing", O), ("unknown", O), ("deceased", CO)],
    "location": [("active", O), ("destroyed", CO), ("unknown", O)],
    "faction": [("active", O), ("disbanded", CO), ("unknown", O)],
    "item": [("active", O), ("destroyed", CO), ("unknown", O)],
    "quest": [("active", O), ("completed", CS), ("failed", CF), ("abandoned", CO)],
}
EXPECTED_DEFAULT = {"character": "unknown", "location": "unknown", "faction": "unknown",
                    "item": "unknown", "quest": "active"}
EXPECTED_ATTRIBUTES = {
    "character": ["species", "occupation", "location_entity_id"],
    "location": ["region", "parent_location_entity_id"],
    "faction": ["headquarters_entity_id", "leader_entity_id"],
    "item": ["holder_entity_id", "location_entity_id"],
    "quest": ["giver_entity_id", "completed_at"],
}


# ---- the tables -------------------------------------------------------------

def test_exactly_five_types_in_order():
    assert [t.value for t in REGISTRY] == ["character", "location", "faction", "item", "quest"]
    assert list(REGISTRY) == list(EntityType)
    for t, definition in REGISTRY.items():
        assert definition.type is t
        assert definition.label == t.value.capitalize()


def test_registry_is_read_only():
    with pytest.raises(TypeError):
        REGISTRY[EntityType.ITEM] = REGISTRY[EntityType.QUEST]  # type: ignore[index]
    with pytest.raises(AttributeError):
        REGISTRY[EntityType.ITEM].default_status = "destroyed"  # type: ignore[misc]


@pytest.mark.parametrize("type_", list(EXPECTED_STATUSES))
def test_statuses_and_categories(type_):
    assert [(s.key, s.category.value) for s in et.get(type_).statuses] == EXPECTED_STATUSES[type_]
    assert et.statuses(type_) == tuple(k for k, _ in EXPECTED_STATUSES[type_])
    for key, category in EXPECTED_STATUSES[type_]:
        assert et.status_category(type_, key) is StatusCategory(category)
        assert et.is_closed(type_, key) is (category != O)
        assert et.get(type_).statuses[et.statuses(type_).index(key)].label


def test_status_categories_are_the_four():
    assert [c.value for c in StatusCategory] == [O, CS, CF, CO]


@pytest.mark.parametrize("type_", list(EXPECTED_DEFAULT))
def test_default_status(type_):
    assert et.default_status(type_) == EXPECTED_DEFAULT[type_]


def test_kinds_only_on_characters():
    assert REGISTRY[EntityType.CHARACTER].kinds == (CharacterKind.PC, CharacterKind.NPC, CharacterKind.CREATURE)
    for t in EntityType:
        if t is not EntityType.CHARACTER:
            assert REGISTRY[t].kinds == ()


@pytest.mark.parametrize("type_", list(EXPECTED_ATTRIBUTES))
def test_attribute_keys(type_):
    assert list(et.attribute_keys(type_)) == EXPECTED_ATTRIBUTES[type_]


def test_named_attribute_examples():
    assert "region" in et.attribute_keys("location")
    assert "holder_entity_id" in et.attribute_keys("item")
    assert "completed_at" in et.attribute_keys("quest")
    assert et.attribute("quest", "completed_at").value_kind is ValueKind.DATETIME
    assert et.attribute("location", "region").value_kind is ValueKind.TEXT


def test_attribute_value_kinds_and_targets():
    assert [k.value for k in ValueKind] == ["text", "entity_ref", "datetime"]
    for definition in REGISTRY.values():
        for a in definition.attributes:
            if a.value_kind is ValueKind.ENTITY_REF:
                assert a.key.endswith("_entity_id")
                assert a.target_types and all(isinstance(t, EntityType) for t in a.target_types)
            else:
                assert a.target_types == ()
    assert et.attribute("location", "parent_location_entity_id").target_types == (EntityType.LOCATION,)
    assert et.attribute("faction", "leader_entity_id").target_types == (EntityType.CHARACTER,)
    with pytest.raises(ValueError):
        AttributeDef("x_entity_id", ValueKind.ENTITY_REF, "X")
    with pytest.raises(ValueError):
        AttributeDef("x", ValueKind.TEXT, "X", (EntityType.ITEM,))


# ---- validate_status --------------------------------------------------------

def test_valid_status():
    assert et.validate_status("character", "deceased") == "deceased"
    assert type(et.validate_status(EntityType.CHARACTER, "deceased")) is str
    assert et.status_category("character", "deceased") is StatusCategory.CLOSED_OTHER


def test_status_from_another_type_is_rejected():
    with pytest.raises(InvalidStatusError) as exc:
        et.validate_status("quest", "alive")
    assert isinstance(exc.value, ValueError)
    assert exc.value.entity_type is EntityType.QUEST
    assert "'alive'" in str(exc.value) and "abandoned" in str(exc.value)
    with pytest.raises(InvalidStatusError):
        et.validate_status("character", "dead")  # the legacy value, before the WorldCore.2 map
    with pytest.raises(InvalidStatusError):
        et.status_category("item", None)
    with pytest.raises(InvalidStatusError):
        et.validate_status("character", "Alive")


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="dragon"):
        et.validate_status("dragon", "alive")
    with pytest.raises(ValueError):
        et.get("npc")
    with pytest.raises(ValueError):
        et.default_status("")


# ---- validate_kind ----------------------------------------------------------

def test_kind_on_character():
    assert et.validate_kind("character", "creature") is CharacterKind.CREATURE
    assert et.validate_kind(EntityType.CHARACTER, CharacterKind.PC) is CharacterKind.PC
    with pytest.raises(ValueError):
        et.validate_kind("character", None)
    with pytest.raises(ValueError):
        et.validate_kind("character", "monster")


@pytest.mark.parametrize("type_", ["location", "faction", "item", "quest"])
def test_kind_on_non_character(type_):
    assert et.validate_kind(type_, None) is None
    with pytest.raises(ValueError):
        et.validate_kind(type_, "npc")


# ---- validate_attributes ----------------------------------------------------

def test_validate_attributes():
    attrs = {"region": "North", "parent_location_entity_id": None}
    out = et.validate_attributes("location", attrs)
    assert out == attrs and out is not attrs
    assert et.validate_attributes("item", {}) == {}
    with pytest.raises(ValueError, match="species"):
        et.validate_attributes("location", {"region": "North", "species": "elf"})


# ---- Party rendering (AD-13) ------------------------------------------------

def test_party_unset_status():
    assert et.party_unset("quest", "status") == "active"
    assert et.party_unset("faction", "status") == "unknown"
    for t in EntityType:
        assert et.party_unset(t, "status") == EXPECTED_DEFAULT[t.value]


def test_party_unset_other_fields():
    assert et.party_unset("location", "description") is None
    assert et.party_unset("location", "gm_notes") is None
    assert et.party_unset("location", "aliases") == []
    first = et.party_unset("location", "aliases")
    first.append("x")
    assert et.party_unset("location", "aliases") == []  # a fresh list every call
    assert et.party_unset("location", "attributes.region") is ABSENT


def test_party_unset_rejects_unknown_fields():
    with pytest.raises(ValueError):
        et.party_unset("location", "name")
    with pytest.raises(ValueError):
        et.party_unset("location", "attributes.species")
    with pytest.raises(ValueError):
        et.party_unset("location", "attributes.")
    with pytest.raises(ValueError):
        et.party_unset("dragon", "status")


def test_absent_sentinel():
    assert repr(ABSENT) == "ABSENT"
    assert not ABSENT
    assert type(ABSENT)() is ABSENT
    assert copy.copy(ABSENT) is ABSENT and copy.deepcopy(ABSENT) is ABSENT
    assert pickle.loads(pickle.dumps(ABSENT)) is ABSENT


def test_party_view_hides_without_mutating():
    fields = {
        "name": "Thornwick",
        "status": "destroyed",
        "description": "Market town.",
        "aliases": ["Thorn"],
        "attributes": {"region": "Vale", "parent_location_entity_id": "abc"},
    }
    before = copy.deepcopy(fields)
    view = et.party_view("location", fields, hidden={"description", "attributes.region"})
    assert fields == before
    assert view == {
        "name": "Thornwick",
        "status": "destroyed",
        "description": None,
        "aliases": ["Thorn"],
        "attributes": {"parent_location_entity_id": "abc"},
    }
    assert view["aliases"] is not fields["aliases"]
    assert view["attributes"] is not fields["attributes"]


def test_party_view_hidden_equals_unset():
    unset = {"name": "Q", "status": "active", "description": None, "aliases": [], "attributes": {}}
    set_ = {"name": "Q", "status": "failed", "description": "Secret", "aliases": ["Q2"],
            "attributes": {"giver_entity_id": "e1"}}
    hidden = ["status", "description", "aliases", "attributes.giver_entity_id"]
    assert et.party_view("quest", set_, hidden) == unset
    assert et.party_view("quest", unset, hidden) == unset


def test_party_view_without_attributes():
    fields = {"name": "Key", "description": "Silver"}
    view = et.party_view("item", fields, hidden={"attributes.holder_entity_id"})
    assert view == fields and "attributes" not in view
    assert et.party_view("item", {"name": "Key", "attributes": None},
                         hidden={"attributes.holder_entity_id"}) == {"name": "Key", "attributes": None}


def test_party_view_mapping_attributes_are_stripped():
    attrs = MappingProxyType({"region": "Vale", "parent_location_entity_id": "abc"})
    view = et.party_view("location", {"name": "T", "attributes": attrs}, hidden={"attributes.region"})
    assert view["attributes"] == {"parent_location_entity_id": "abc"}
    assert dict(attrs) == {"region": "Vale", "parent_location_entity_id": "abc"}


def test_party_view_rejects_bad_attributes_and_str_hidden():
    with pytest.raises(TypeError):
        et.party_view("location", {"name": "T", "attributes": ["region"]}, hidden={"attributes.region"})
    with pytest.raises(TypeError):
        et.party_view("location", {"name": "T", "description": "d"}, hidden="description")


def test_party_view_rejects_unknown_hidden_field():
    with pytest.raises(ValueError):
        et.party_view("item", {"name": "Key"}, hidden={"name"})


# ---- the demo seed maps onto the registry ------------------------------------

# The E0-WorldCore.2 legacy copy: npc role -> (type, kind), npc status -> status.
LEGACY_ROLE = {
    "pc": ("character", "pc"),
    "npc": ("character", "npc"),
    "monster": ("character", "creature"),
    "faction": ("faction", None),
}
LEGACY_STATUS = {
    "character": {"alive": "alive", "dead": "deceased", "unknown": "unknown"},
    "faction": {"alive": "active", "dead": "disbanded", "unknown": "unknown"},
}


def test_demo_seed_maps_to_valid_entities():
    seed = json.loads(DEMO_SEED.read_text())
    assert seed["npcs"] and seed["quests"] and seed["locations"]
    for npc in seed["npcs"]:
        type_, kind = LEGACY_ROLE[npc["role"]]
        assert et.validate_kind(type_, kind) == kind
        for entry in npc["status_history"]:
            assert et.validate_status(type_, LEGACY_STATUS[type_][entry["status"]])
    for quest in seed["quests"]:
        assert et.validate_status("quest", quest["status"]) == quest["status"]
        assert et.validate_kind("quest", None) is None
    for _location in seed["locations"]:
        assert et.validate_kind("location", None) is None
        assert et.validate_status("location", et.default_status("location")) == "unknown"


def test_legacy_mapping_covers_every_legacy_enum_value():
    from app.db.models.npc import NpcRole, NpcStatus
    from app.db.models.quest import QuestStatus

    assert set(LEGACY_ROLE) == {r.value for r in NpcRole}
    for type_, kind in LEGACY_ROLE.values():
        assert et.validate_kind(type_, kind) == kind
    for type_, mapping in LEGACY_STATUS.items():
        assert set(mapping) == {s.value for s in NpcStatus}
        for status in mapping.values():
            assert et.validate_status(type_, status) == status
    assert {type_ for type_, _ in LEGACY_ROLE.values()} == set(LEGACY_STATUS)
    for status in QuestStatus:
        assert et.validate_status("quest", status.value) == status.value
