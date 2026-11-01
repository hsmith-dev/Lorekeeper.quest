"""Deterministic stand-in for the ml sidecar, used under ENVIRONMENT=test.

No network, no models: the same text always gives the same 384-d unit
vector (seeded from its sha256), and NER is a handful of regex rules that
return the same shape and ordering as the real sidecar (entities first,
then ITEM / QUEST matches).
"""

from __future__ import annotations

import hashlib
import math
import re
import struct

from app.clients.ml import MLStatus, ModelState, NamedEntity
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL

# A run of Capitalised words ("Borin Stonebeard", "Waterdeep"); a leading
# stop word such as "The" is dropped. GPE when preceded by a place
# preposition ("toward Menzoberranzan"), else PERSON.
_PROPER = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
_LOCATION_HINT = re.compile(r"\b(?:at|in|to|toward|towards|from|through|near)\s+(?:the\s+)?$", re.I)
_ITEM = re.compile(r"\b(?:ring|wand|staff|amulet|sword|dagger|bow|shield|armor)\s+of\s+[A-Za-z]+", re.I)
_QUEST = re.compile(r"\b(?:defeat|find|retrieve|escort|destroy|investigate|survive)\s+(?:the\s+)?[A-Za-z]+", re.I)
_STOP = {"The", "A", "An", "He", "She", "They", "It", "We", "I", "After", "Then"}


def fake_vector(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    raw: list[float] = []
    counter = 0
    while len(raw) < dim:
        block = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        # 8 signed 32-bit ints per block, mapped into [-1, 1).
        raw.extend(x / 2**31 for x in struct.unpack(">8i", block))
        counter += 1
    raw = raw[:dim]
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


def fake_entities(text: str) -> list[NamedEntity]:
    ents: list[NamedEntity] = []
    for m in _PROPER.finditer(text):
        span, start = m.group(0), m.start()
        first, _, rest = span.partition(" ")
        if first in _STOP:
            if not rest:
                continue
            span, start = rest, start + len(first) + 1
        label = "GPE" if _LOCATION_HINT.search(text[:start]) else "PERSON"
        ents.append(NamedEntity(span, label, start, start + len(span)))
    for label, pattern in (("ITEM", _ITEM), ("QUEST", _QUEST)):
        for m in pattern.finditer(text):
            ents.append(NamedEntity(m.group(0), label, m.start(), m.end()))
    return ents


class FakeMLClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    async def ner(self, text: str) -> list[NamedEntity]:
        return fake_entities(text)

    async def status(self) -> MLStatus:
        return MLStatus(
            models=[ModelState(EMBEDDING_MODEL, "embedding", "loaded"),
                    ModelState("en_core_web_trf", "ner", "loaded")],
            rss_bytes=0,
        )
