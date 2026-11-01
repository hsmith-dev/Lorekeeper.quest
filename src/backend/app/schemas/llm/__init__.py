"""Flat pydantic schemas for llm_provider.complete_structured.

Feature epics put their LLM output schemas in app/schemas/llm/<feature>.py
and subclass FlatModel. A flat schema is one every backend can enforce:
Ollama's `format`, OpenAI strict `response_format`, and a schema restated in
the prompt for Anthropic/Gemini. That means:

- no `$ref`/`$defs` (FlatModel.model_json_schema inlines nested models),
- no `anyOf`/`oneOf`/`allOf` (so no Optional fields or unions: use an enum,
  an empty string or an empty list for "none"),
- every object has `additionalProperties: false` (FlatModel is
  extra="forbid", and nested models must be FlatModels too),
- every property is required (no defaults: `{}` must not validate as an
  empty result, and OpenAI strict mode rejects optional properties).

Semantic rules ("at least one entity", non-blank names) go in pydantic
validators: they fail validation like a missing field, so complete_structured
repairs them the same way. tests/test_llm_schemas_flat.py lints every
FlatModel under this package with flatness_problems.
"""

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict

_REF_PREFIX = "#/$defs/"
_COMBINATORS = ("anyOf", "oneOf", "allOf")


def _inline(node: Any, defs: dict, expanding: tuple[str, ...]) -> tuple[Any, bool]:
    """(node with local $refs replaced by their definitions, whether any $ref
    had to stay because it is recursive)."""
    if isinstance(node, list):
        out, kept = [], False
        for item in node:
            new, k = _inline(item, defs, expanding)
            out.append(new)
            kept = kept or k
        return out, kept
    if not isinstance(node, dict):
        return node, False
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
        name = ref[len(_REF_PREFIX):]
        if name in defs and name not in expanding:
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            target, kept = _inline(copy.deepcopy(defs[name]), defs, (*expanding, name))
            sib, kept_sib = _inline(siblings, defs, expanding)
            return {**target, **sib}, kept or kept_sib
        # Recursive (or unknown) reference: leave it for flatness_problems.
        rest, kept = _inline({k: v for k, v in node.items() if k != "$ref"}, defs, expanding)
        return {"$ref": ref, **rest}, True
    out, kept = {}, False
    for key, value in node.items():
        if key == "$defs":
            continue
        new, k = _inline(value, defs, expanding)
        out[key] = new
        kept = kept or k
    return out, kept


def inline_refs(json_schema: dict) -> dict:
    """Copy of json_schema with every local `#/$defs/...` reference replaced
    by its definition and `$defs` removed. A recursive model can't be
    inlined: its `$ref`s (and `$defs`) are kept, and flatness_problems
    reports them."""
    defs = json_schema.get("$defs") or {}
    out, kept = _inline(json_schema, defs, ())
    if kept and defs:
        out["$defs"] = copy.deepcopy(defs)
    return out


def flat_json_schema(model: type[BaseModel]) -> dict:
    """The model's JSON schema (validation mode) with nested models inlined."""
    return inline_refs(model.model_json_schema())  # idempotent for a FlatModel


class FlatModel(BaseModel):
    """Base of every LLM output schema: extra keys are a validation error,
    and model_json_schema() comes back with nested FlatModels inlined."""

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def model_json_schema(cls, *args, **kwargs) -> dict[str, Any]:
        return inline_refs(super().model_json_schema(*args, **kwargs))


def _is_object(node: dict) -> bool:
    t = node.get("type")
    return t == "object" or (isinstance(t, list) and "object" in t) or "properties" in node


def _walk(node: Any, path: str, problems: list[str]) -> None:
    if not isinstance(node, dict):
        return
    for key in ("$ref", "$defs", *_COMBINATORS):
        if key in node:
            problems.append(f"{path}: has {key}")
    if _is_object(node):
        if node.get("additionalProperties") is not False:
            problems.append(f"{path}: object without additionalProperties: false")
        required = set(node.get("required") or [])
        for name in node.get("properties") or {}:
            if name not in required:
                problems.append(f"{path}.{name}: property not in required (has a default?)")
    for name, sub in (node.get("properties") or {}).items():
        _walk(sub, f"{path}.{name}", problems)
    items = node.get("items")
    if isinstance(items, list):
        for i, sub in enumerate(items):
            _walk(sub, f"{path}[{i}]", problems)
    else:
        _walk(items, f"{path}[]", problems)
    for i, sub in enumerate(node.get("prefixItems") or []):
        _walk(sub, f"{path}[{i}]", problems)
    if isinstance(node.get("additionalProperties"), dict):
        _walk(node["additionalProperties"], f"{path}{{*}}", problems)
    for key in _COMBINATORS:
        for i, sub in enumerate(node.get(key) or []):
            _walk(sub, f"{path}.{key}[{i}]", problems)
    for name, sub in (node.get("$defs") or {}).items():
        _walk(sub, f"{path}.$defs.{name}", problems)
    if "not" in node:
        _walk(node["not"], f"{path}.not", problems)


def flatness_problems(json_schema: dict) -> list[str]:
    """Why json_schema isn't flat, one line per problem; [] if it is. Reports
    $ref, $defs, anyOf, oneOf, allOf, an object without
    `additionalProperties: false`, and a property missing from `required`."""
    problems: list[str] = []
    _walk(json_schema, "$", problems)
    return problems


__all__ = ["FlatModel", "flat_json_schema", "flatness_problems", "inline_refs"]
