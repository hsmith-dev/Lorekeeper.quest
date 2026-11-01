"""Sidecar configuration, read from the environment.

The embedding contract (model name, dimension) must match the backend's
app/domain/embedding.py. The two packages cannot import each other, so
src/backend/tests/test_ml_client.py reads this file and checks they agree
(also MAX_EMBED_TEXTS and MAX_NLI_PAIRS, which the client batches by).
Keep those constants plain literals: the check is an AST read.
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

# NLI (lazy): cross-encoder over (premise, hypothesis) pairs, softmax over
# entailment / neutral / contradiction. sha256 is model.safetensors at this
# revision (licenses/register.yaml nli-deberta-v3-xsmall).
NLI_MODEL_NAME = "nli-deberta-v3-xsmall"
NLI_MODEL_REPO = "cross-encoder/nli-deberta-v3-xsmall"
NLI_MODEL_REVISION = "a150876415327c80daeff35ca6f68f5ed8cf5c24"
NLI_MODEL_SHA256 = "4e4fc4977f8d29d2a164255c8f69b9d6c158deeb309bb5e70445b94666ccd9e9"
DEFAULT_NLI_MODEL_PATH = "/models/nli-deberta-v3-xsmall"

# OCR (lazy): EasyOCR "en" = CRAFT detector + english_g2 recogniser. The zips
# are the registered downloads (licenses/register.yaml easyocr-craft-mlt-25k,
# easyocr-english-g2); bake_models.py checks them and extracts the .pth files.
OCR_MODEL_NAME = "easyocr-en"
OCR_DETECTOR_URL = "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip"
OCR_DETECTOR_SHA256 = "8dc6a1c703a89ed56308ef742d26ebd45c656248cbbbda6e7fe60e569f873e65"
OCR_RECOGNIZER_URL = "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip"
OCR_RECOGNIZER_SHA256 = "1b5eaebf1c062de6205560c97ffcfa8dc0e6f413c340e8adc5cfc57e159f61ff"
OCR_ZIPS = (
    (OCR_DETECTOR_URL, OCR_DETECTOR_SHA256),
    (OCR_RECOGNIZER_URL, OCR_RECOGNIZER_SHA256),
)
DEFAULT_OCR_MODEL_DIR = "/models/easyocr"

# Upper bound on texts per /v1/embed request (larger bodies get a 422).
MAX_EMBED_TEXTS = 256
# Upper bound on /v1/ner text length (422 above it). Journal entries and NPC
# notes are far shorter; it keeps one request from holding the NER lock for
# minutes or tripping spaCy's own max_length as a 500.
MAX_NER_CHARS = 100_000
# /v1/nli: pairs per request, and characters per premise or hypothesis (422).
MAX_NLI_PAIRS = 256
MAX_NLI_CHARS = 4000
# /v1/ocr: upload size (413 above it). 10 MiB.
MAX_OCR_BYTES = 10_485_760

# Resident-memory budget for the lazy models (NLI, OCR), in MB of declared
# cost. Declared, not measured: see budget.py.
DEFAULT_RESIDENT_BUDGET_MB = 2000
DEFAULT_NLI_COST_MB = 600
DEFAULT_OCR_COST_MB = 900


@dataclass(frozen=True)
class Config:
    embed_model_name: str = EMBED_MODEL_NAME
    embed_model_path: str = DEFAULT_EMBED_MODEL_PATH
    embed_dim: int = EMBED_DIM
    embed_batch_size: int = 32
    ner_model_name: str = NER_MODEL_NAME
    nli_model_name: str = NLI_MODEL_NAME
    nli_model_path: str = DEFAULT_NLI_MODEL_PATH
    nli_batch_size: int = 32
    nli_cost_mb: int = DEFAULT_NLI_COST_MB
    ocr_model_name: str = OCR_MODEL_NAME
    ocr_model_dir: str = DEFAULT_OCR_MODEL_DIR
    ocr_cost_mb: int = DEFAULT_OCR_COST_MB
    resident_budget_mb: int = DEFAULT_RESIDENT_BUDGET_MB


def _int(env, key: str, default: int, minimum: int) -> int:
    raw = env.get(key)
    value = int(raw) if raw else default
    if value < minimum:
        raise ValueError(f"{key}={value} must be >= {minimum}")
    return value


def load_config(environ: dict[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    return Config(
        embed_model_path=env.get("ML_EMBED_MODEL_PATH") or DEFAULT_EMBED_MODEL_PATH,
        embed_batch_size=_int(env, "ML_EMBED_BATCH_SIZE", 32, 1),
        ner_model_name=env.get("ML_NER_MODEL") or NER_MODEL_NAME,
        nli_model_path=env.get("ML_NLI_MODEL_PATH") or DEFAULT_NLI_MODEL_PATH,
        nli_batch_size=_int(env, "ML_NLI_BATCH_SIZE", 32, 1),
        nli_cost_mb=_int(env, "ML_NLI_COST_MB", DEFAULT_NLI_COST_MB, 0),
        ocr_model_dir=env.get("ML_OCR_MODEL_DIR") or DEFAULT_OCR_MODEL_DIR,
        ocr_cost_mb=_int(env, "ML_OCR_COST_MB", DEFAULT_OCR_COST_MB, 0),
        resident_budget_mb=_int(env, "ML_RESIDENT_BUDGET_MB", DEFAULT_RESIDENT_BUDGET_MB, 0),
    )
