"""Opt-in (ML_REAL_MODELS=1): the sidecar's batched embeddings match the
backend's current per-text path, `SentenceTransformer(...).encode(text,
normalize_embeddings=True)` in app/services/embedding_service.py.

Uses ML_EMBED_MODEL_PATH when it exists (the baked image), else the hub name.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from ml_service.config import EMBED_DIM, EMBED_MODEL_NAME, load_config

pytestmark = pytest.mark.skipif(os.environ.get("ML_REAL_MODELS") != "1",
                                reason="set ML_REAL_MODELS=1 to run against real MiniLM")

TEXTS = [
    "Borin Stonebeard forged the ring of Moradin.",
    "The party traveled through the Underdark toward Menzoberranzan.",
    "a",
    "",
]


def test_batched_embeddings_match_reference():
    from sentence_transformers import SentenceTransformer

    from ml_service.models import SentenceTransformerEmbedder

    path = load_config().embed_model_path
    source = path if Path(path).exists() else EMBED_MODEL_NAME
    reference = SentenceTransformer(source, device="cpu")
    got = SentenceTransformerEmbedder(source).encode(TEXTS)

    assert len(got) == len(TEXTS)
    for text, vec in zip(TEXTS, got):
        want = reference.encode(text, normalize_embeddings=True).tolist()
        assert len(vec) == EMBED_DIM
        assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, rel_tol=1e-5)
        cos = sum(a * b for a, b in zip(vec, want))
        assert cos > 0.99999, (text, cos)
        assert max(abs(a - b) for a, b in zip(vec, want)) < 1e-4, text
