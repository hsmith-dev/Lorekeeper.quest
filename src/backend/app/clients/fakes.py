"""Deterministic stand-in for the ml sidecar, used under ENVIRONMENT=test.

No network, no models: the same text always gives the same 384-d unit
vector (seeded from its sha256), and NER is a handful of regex rules that
return the same shape and ordering as the real sidecar (entities first,
then ITEM / QUEST matches). NLI gives each pair a stable softmax seeded
from its sha256; OCR returns the bytes' UTF-8 text (so a test can "scan" a
known string) or "" for real image bytes. The fake mirrors the sidecar's
size and emptiness limits only (raising ModelServiceError with 422 / 413),
not image decoding: it accepts non-image bytes the sidecar would reject.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct

from app.clients.errors import ModelServiceError
from app.clients.ml import NLI_LABELS, MLStatus, ModelState, NamedEntity, NliScores
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL

# A run of Capitalised words ("Borin Stonebeard", "Waterdeep"); a leading
# stop word such as "The" is dropped. GPE when preceded by a place
# preposition ("toward Menzoberranzan"), else PERSON.
_PROPER = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
_LOCATION_HINT = re.compile(r"\b(?:at|in|to|toward|towards|from|through|near)\s+(?:the\s+)?$", re.I)
_ITEM = re.compile(r"\b(?:ring|wand|staff|amulet|sword|dagger|bow|shield|armor)\s+of\s+[A-Za-z]+", re.I)
_QUEST = re.compile(r"\b(?:defeat|find|retrieve|escort|destroy|investigate|survive)\s+(?:the\s+)?[A-Za-z]+", re.I)
_STOP = {"The", "A", "An", "He", "She", "They", "It", "We", "I", "After", "Then"}
# Mirrors the sidecar's ml_service/config.py request limits.
_MAX_NLI_CHARS = 4000
_MAX_OCR_BYTES = 10_485_760


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


def fake_nli_scores(premise: str, hypothesis: str) -> NliScores:
    seed = hashlib.sha256(f"{premise}\0{hypothesis}".encode()).digest()
    exps = [math.exp(b / 64.0) for b in seed[:3]]
    total = sum(exps)
    return NliScores(**{k: e / total for k, e in zip(NLI_LABELS, exps)})


def fake_ocr_text(image: bytes) -> str:
    try:
        decoded = bytes(image).decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return "\n".join(line.strip() for line in decoded.splitlines() if line.strip())


class FakeMLClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [fake_vector(t) for t in texts]

    async def ner(self, text: str) -> list[NamedEntity]:
        return fake_entities(text)

    async def nli(self, pairs: list[tuple[str, str]]) -> list[NliScores]:
        out = []
        for premise, hypothesis in pairs:
            if len(premise) > _MAX_NLI_CHARS or len(hypothesis) > _MAX_NLI_CHARS:
                raise ModelServiceError(f"ml /v1/nli: a side is over {_MAX_NLI_CHARS} chars", status_code=422)
            out.append(fake_nli_scores(premise, hypothesis))
        return out

    async def ocr(self, image: bytes, filename: str = "image") -> str:
        if not image:
            raise ModelServiceError("ml /v1/ocr: empty upload", status_code=422)
        if len(image) > _MAX_OCR_BYTES:
            raise ModelServiceError(f"ml /v1/ocr: image over {_MAX_OCR_BYTES} bytes", status_code=413)
        return fake_ocr_text(image)

    async def status(self) -> MLStatus:
        return MLStatus(
            models=[ModelState(EMBEDDING_MODEL, "embedding", "loaded"),
                    ModelState("en_core_web_trf", "ner", "loaded"),
                    ModelState("nli-deberta-v3-xsmall", "nli", "not_loaded", lazy=True, cost_mb=600),
                    ModelState("easyocr-en", "ocr", "not_loaded", lazy=True, cost_mb=900)],
            rss_bytes=0,
            resident_budget_mb=2000,
            lazy_resident_mb=0,
        )
