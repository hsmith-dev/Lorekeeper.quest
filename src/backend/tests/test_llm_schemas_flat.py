"""E0-LLM.4: every LLM output schema under app/schemas/llm is flat.

Imports every module in the package and lints each FlatModel defined there
with flatness_problems, so a feature schema with an Optional field, a
default, a union or a nested non-FlatModel fails CI rather than a backend.
"""

import importlib
import inspect
import pkgutil
from enum import Enum
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

import app.schemas.llm as llm_schemas
from app.schemas.llm import FlatModel, flat_json_schema, flatness_problems


def _llm_schema_modules():
    yield llm_schemas
    for info in pkgutil.walk_packages(llm_schemas.__path__, prefix=f"{llm_schemas.__name__}."):
        yield importlib.import_module(info.name)


def _flat_models() -> list[type[FlatModel]]:
    found: dict[str, type[FlatModel]] = {}
    for module in _llm_schema_modules():
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, FlatModel) and obj is not FlatModel and obj.__module__ == module.__name__:
                found[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return [found[k] for k in sorted(found)]


def test_package_imports():
    assert list(_llm_schema_modules())


@pytest.mark.parametrize("model", _flat_models() or [pytest.param(None, marks=pytest.mark.skip("no feature schemas yet"))])
def test_every_llm_schema_is_flat(model):
    assert flatness_problems(model.model_json_schema()) == []
    assert model.model_config.get("extra") == "forbid"


# --- the checker itself --------------------------------------------------------


class Kind(str, Enum):
    npc = "npc"
    place = "place"


class Entity(FlatModel):
    name: str
    kind: Kind
    status: Literal["alive", "dead", "unknown"]


class Relationship(FlatModel):
    source: str
    target: str
    kind: str


class Extraction(FlatModel):
    entities: list[Entity]
    relationships: list[Relationship]
    best: Entity


def test_nested_flat_models_are_inlined():
    js = Extraction.model_json_schema()
    assert flatness_problems(js) == []
    assert "$defs" not in js
    assert "$ref" not in str(js)
    item = js["properties"]["entities"]["items"]
    assert item["additionalProperties"] is False
    assert item["properties"]["kind"]["enum"] == ["npc", "place"]
    assert js["properties"]["best"]["required"] == ["name", "kind", "status"]
    assert flat_json_schema(Extraction) == js


def test_flat_model_forbids_extra():
    with pytest.raises(ValidationError):
        Relationship.model_validate_json('{"source": "a", "target": "b", "kind": "c", "x": 1}')
    with pytest.raises(ValidationError):
        Extraction.model_validate({
            "entities": [{"name": "a", "kind": "npc", "status": "alive", "extra": True}],
            "relationships": [],
            "best": {"name": "a", "kind": "npc", "status": "alive"},
        })


def test_flat_model_itself_is_flat():
    assert flatness_problems(FlatModel.model_json_schema()) == []


class WithOptional(FlatModel):
    name: str | None


class WithDefault(FlatModel):
    name: str
    note: str = ""


class Loose(BaseModel):
    name: str


class NestedLoose(FlatModel):
    item: Loose
    items: list[Loose]


class Node(FlatModel):
    name: str
    children: list["Node"]


class WithUnion(FlatModel):
    value: int | str


class WithDict(FlatModel):
    tags: dict[str, str]


class WithTuple(FlatModel):
    pair: tuple[str, int]


class AllowExtra(FlatModel):
    model_config = ConfigDict(extra="allow")
    name: str


@pytest.mark.parametrize(
    "model,expected",
    [
        (WithOptional, ["anyOf"]),
        (WithDefault, ["$.note: property not in required"]),
        (NestedLoose, ["$.item: object without additionalProperties", "$.items[]: object without additionalProperties"]),
        (Node, ["$ref"]),
        (WithUnion, ["anyOf"]),
        (WithDict, ["$.tags: object without additionalProperties"]),
        (WithTuple, ["$.pair: has prefixItems"]),
        (AllowExtra, ["$: object without additionalProperties"]),
    ],
    ids=["optional", "default", "nested-loose", "recursive", "union", "dict", "tuple", "extra-allow"],
)
def test_non_flat_schemas_are_reported(model, expected):
    problems = flatness_problems(model.model_json_schema())
    assert problems
    for fragment in expected:
        assert any(fragment in p for p in problems), (fragment, problems)


@pytest.mark.parametrize(
    "schema,fragment",
    [
        ({"type": "object", "properties": {}, "additionalProperties": False, "$defs": {}}, "$defs"),
        ({"oneOf": [{"type": "string"}, {"type": "integer"}]}, "oneOf"),
        ({"allOf": [{"type": "string"}]}, "allOf"),
        ({"$ref": "#/$defs/X"}, "$ref"),
        ({"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}, "$.a: property not in required"),
        ({"type": "object", "properties": {}}, "additionalProperties"),
    ],
)
def test_raw_schema_problems(schema, fragment):
    assert any(fragment in p for p in flatness_problems(schema))


def test_flat_raw_schema_has_no_problems():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "array", "items": {"type": "string"}}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert flatness_problems(schema) == []
