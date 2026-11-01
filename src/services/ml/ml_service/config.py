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

# OCR (lazy): RapidOCR (Apache-2.0) on onnxruntime with the PP-OCRv6 "small"
# detector and recogniser (multilingual, Latin script included) plus the
# PP-OCR mobile text-line orientation classifier: RapidOCR 3.10's defaults.
# Each .onnx is a registered download (licenses/register.yaml rapidocr-*);
# bake_models.py checks its sha256 and the reader loads it by path, so
# RapidOCR never downloads. Replaced EasyOCR in E0-QA.9 (its python-bidi
# dependency is LGPL-3.0).
OCR_MODEL_NAME = "rapidocr-ppocrv6-small"
_RAPIDOCR_BASE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx"
OCR_DET_FILE = "PP-OCRv6_det_small.onnx"
OCR_CLS_FILE = "ch_ppocr_mobile_v2.0_cls_mobile.onnx"
OCR_REC_FILE = "PP-OCRv6_rec_small.onnx"
# (register name, file name, url, sha256), in det / cls / rec order.
OCR_MODELS = (
    ("rapidocr-ppocrv6-det-small", OCR_DET_FILE, _RAPIDOCR_BASE + "/PP-OCRv6/det/" + OCR_DET_FILE,
     "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    ("rapidocr-ppocr-cls-mobile-v2", OCR_CLS_FILE, _RAPIDOCR_BASE + "/PP-OCRv4/cls/" + OCR_CLS_FILE,
     "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
    ("rapidocr-ppocrv6-rec-small", OCR_REC_FILE, _RAPIDOCR_BASE + "/PP-OCRv6/rec/" + OCR_REC_FILE,
     "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
)
DEFAULT_OCR_MODEL_DIR = "/models/rapidocr"

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
# OCR: RapidOCR PP-OCRv6 small measured +230 MB RSS resident after load and 55
# inference calls in the ml image (E0-QA.9, desktop); 400 leaves headroom for
# a large photo. EasyOCR was 900 declared (+330 MB measured).
DEFAULT_OCR_COST_MB = 400


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
