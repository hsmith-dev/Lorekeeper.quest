"""E0-LLM.4: complete_structured against a real Ollama (opt-in).

Skipped unless OLLAMA_TEST_URL is set, e.g.

    OLLAMA_TEST_URL=http://localhost:11434 OLLAMA_TEST_MODEL=lorekeeper \\
        python -m pytest -m ollama -s tests/integration

(tests/conftest.py still builds the test DB at session start; run with a
reachable TEST_DATABASE_URL, or with --noconftest and the settings env vars.)

50 calls over three flat schemas: an E1-shaped entity list, a recap update,
and a yes/no verdict with a quote. OLLAMA_TEST_PARAGRAPHS may hold a JSON
list of input paragraphs. Prints first-try, after-repair and failed rates and
latency, and asserts at least 95% valid within the allowed attempts.
"""

import json
import os
import statistics
import time
from typing import Literal

import pytest
from pydantic import field_validator

from app.core.errors import StructuredOutputError
from app.schemas.llm import FlatModel
from app.services import llm_provider
from app.services.llm_provider import LLMConfig, complete_structured

OLLAMA_URL = os.environ.get("OLLAMA_TEST_URL", "")
pytestmark = [
    pytest.mark.ollama,
    pytest.mark.skipif(not OLLAMA_URL, reason="set OLLAMA_TEST_URL to run against a real Ollama"),
]

CALLS = 50

DEFAULT_PARAGRAPHS = [
    "The party reached Thornwall at dusk. Captain Ilsa Varn of the town guard met them at the gate "
    "and warned that the old mill had been taken by goblins loyal to a hobgoblin named Gresk.",
    "In the Gilded Tankard, the innkeeper Mira Oakhart traded rumours for coin: the Duke of Harrowmere "
    "was dead, poisoned at his own feast, and his niece Seraphine had fled north with the signet ring.",
    "Brother Aldous, a priest of the Dawnfather, agreed to guide them through the Ashen Marsh, but only "
    "if they first recovered the stolen reliquary from the Black Hand thieves' guild.",
    "The dragon Vyraxis rose from the ruins of Kel Dorran. Sir Bram fell defending the bridge, and the "
    "wizard Oren swore an oath of vengeance against the wyrm before the survivors.",
    "At the crossroads shrine the druid Fenna revealed that the Circle of Thorns had been betrayed by "
    "its own elder, Maelis, who now served the lich in the Hollow Tower.",
]


def _paragraphs() -> list[str]:
    raw = os.environ.get("OLLAMA_TEST_PARAGRAPHS")
    if raw:
        paragraphs = json.loads(raw)
        assert isinstance(paragraphs, list) and paragraphs and all(isinstance(p, str) for p in paragraphs)
        return paragraphs
    return DEFAULT_PARAGRAPHS


class Entity(FlatModel):
    name: str
    type: Literal["npc", "location", "faction", "item", "creature", "other"]
    status: Literal["alive", "dead", "missing", "unknown"]

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v


class Relationship(FlatModel):
    source: str
    target: str
    kind: str


class EntityExtraction(FlatModel):
    entities: list[Entity]
    relationships: list[Relationship]

    @field_validator("entities")
    @classmethod
    def at_least_one(cls, v):
        if not v:
            raise ValueError("at least one entity is required")
        return v


class RecapUpdate(FlatModel):
    summary: str
    new_threads: list[str]
    resolved_threads: list[str]

    @field_validator("summary")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("summary must not be blank")
        return v


class Verdict(FlatModel):
    answer: Literal["yes", "no"]
    quote: str


def _prompt(i: int, paragraph: str) -> tuple[list[dict], type[FlatModel]]:
    kind = i % 3
    if kind == 0:
        return [
            {"role": "system", "content": "You extract tabletop RPG entities and their relationships from session notes."},
            {"role": "user", "content": f"Notes:\n{paragraph}\n\nList every named entity and how they relate."},
        ], EntityExtraction
    if kind == 1:
        return [
            {"role": "system", "content": "You keep a rolling recap of a tabletop RPG session."},
            {"role": "user", "content": (
                "Recap so far: The party arrived in the region.\n\n"
                f"New notes:\n{paragraph}\n\nUpdate the recap."
            )},
        ], RecapUpdate
    return [
        {"role": "system", "content": "You answer yes/no questions about session notes, quoting the evidence."},
        {"role": "user", "content": (
            f"Notes:\n{paragraph}\n\nQuestion: does anyone in these notes die or get killed? "
            "Quote the sentence that decides it, or an empty string if none does."
        )},
    ], Verdict


async def test_structured_output_validity_on_real_ollama(monkeypatch):
    monkeypatch.setattr(llm_provider, "structured_stats", {})
    monkeypatch.setattr(llm_provider, "_transport", None)
    cfg = LLMConfig(
        provider="kobold",
        api_url=OLLAMA_URL,
        model=os.environ.get("OLLAMA_TEST_MODEL", "lorekeeper"),
    )
    assert await llm_provider.detect_backend(OLLAMA_URL) == llm_provider.BACKEND_OLLAMA

    paragraphs = _paragraphs()
    latencies: list[float] = []
    failed = 0
    for i in range(CALLS):
        messages, schema = _prompt(i, paragraphs[i % len(paragraphs)])
        started = time.monotonic()
        try:
            result = await complete_structured(messages, schema, cfg, task=f"ollama_it_{schema.__name__}", timeout=300)
            assert isinstance(result, schema)
        except StructuredOutputError:
            failed += 1
        latencies.append(time.monotonic() - started)

    totals = {"first_try_valid": 0, "valid_after_repair": 0, "failed": 0}
    for counts in llm_provider.structured_stats.values():
        for k in totals:
            totals[k] += counts[k]
    assert totals["failed"] == failed
    assert sum(totals.values()) == CALLS
    valid = totals["first_try_valid"] + totals["valid_after_repair"]
    print(
        f"\ncomplete_structured on {cfg.model} @ {OLLAMA_URL}, {CALLS} calls:\n"
        f"  first try valid    {totals['first_try_valid'] / CALLS:.0%}\n"
        f"  valid after repair {totals['valid_after_repair'] / CALLS:.0%}\n"
        f"  failed             {totals['failed'] / CALLS:.0%}\n"
        f"  latency p50 {statistics.median(latencies):.1f}s, "
        f"max {max(latencies):.1f}s, mean {statistics.fmean(latencies):.1f}s\n"
        f"  per task {json.dumps(llm_provider.structured_stats)}"
    )
    assert valid / CALLS >= 0.95
