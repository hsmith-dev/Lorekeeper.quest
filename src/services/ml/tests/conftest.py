"""Fake models for the HTTP tests: no torch, sentence-transformers or spaCy needed."""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import pytest

# Importable whether pytest runs from src/services/ml (pytest.ini) or elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_service.config import Config  # noqa: E402
from ml_service.models import Entity  # noqa: E402


class FakeEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.calls: list[list[str]] = []

    def encode(self, texts):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            seed = hashlib.sha256(t.encode()).digest()
            raw = [((seed[i % len(seed)] + i) % 251) - 125.0 for i in range(self.dim)]
            norm = math.sqrt(sum(x * x for x in raw)) or 1.0
            out.append([x / norm for x in raw])
        return out


class FakeNer:
    """Capitalised words are PERSON; "ring of <Word>" is an ITEM (after ents)."""

    def extract(self, text):
        ents, matcher, pos = [], [], 0
        words = text.split(" ")
        for i, w in enumerate(words):
            word = w.strip(".,!?")
            if word[:1].isupper():
                ents.append(Entity(word, "PERSON", pos, pos + len(word)))
            if word.lower() == "ring" and i + 2 < len(words) and words[i + 1] == "of":
                span = " ".join([word, "of", words[i + 2].strip(".,!?")])
                matcher.append(Entity(span, "ITEM", pos, pos + len(span)))
            pos += len(w) + 1
        return ents + matcher


@pytest.fixture
def fake_embedder():
    return FakeEmbedder()


@pytest.fixture
def client(fake_embedder):
    from fastapi.testclient import TestClient

    from ml_service.app import create_app

    app = create_app(Config(), embedder_factory=lambda c: fake_embedder, ner_factory=lambda c: FakeNer())
    with TestClient(app) as c:  # the context runs the lifespan (model loading)
        yield c
