"""Sidecar configuration, read from the environment.

The embedding contract (model name, dimension) must match the backend's
app/domain/embedding.py. The two packages cannot import each other, so
src/backend/tests/test_ml_client.py reads this file and checks they agree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBED_MODEL_SHA256 = "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"
EMBED_DIM = 384
DEFAULT_EMBED_MODEL_PATH = "/models/all-MiniLM-L6-v2"

NER_MODEL_NAME = "en_core_web_trf"

# Upper bound on texts per /v1/embed request (larger bodies get a 422).
MAX_EMBED_TEXTS = 256


@dataclass(frozen=True)
class Config:
    embed_model_name: str = EMBED_MODEL_NAME
    embed_model_path: str = DEFAULT_EMBED_MODEL_PATH
    embed_dim: int = EMBED_DIM
    embed_batch_size: int = 32
    ner_model_name: str = NER_MODEL_NAME


def load_config(environ: dict[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    return Config(
        embed_model_path=env.get("ML_EMBED_MODEL_PATH") or DEFAULT_EMBED_MODEL_PATH,
        embed_batch_size=int(env.get("ML_EMBED_BATCH_SIZE") or 32),
        ner_model_name=env.get("ML_NER_MODEL") or NER_MODEL_NAME,
    )
