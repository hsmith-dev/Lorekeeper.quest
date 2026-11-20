"""Sidecar configuration, read from the environment.

The model pins (repo, revision, sha256) must match the `faster-whisper-base`
row in licenses/register.yaml; tests/test_dockerfile.py checks they agree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MODEL_NAME = "faster-whisper-base"
MODEL_REPO = "Systran/faster-whisper-base"
MODEL_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
MODEL_SHA256 = "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
DEFAULT_MODEL_PATH = "/models/faster-whisper-base"

# Whisper's native rate: every decoded clip is resampled to 16 kHz mono.
SAMPLE_RATE = 16000
# Upper bound on the initial_prompt form field (422 above it). A campaign
# glossary prompt is a few hundred characters; Whisper itself only uses the
# last ~224 tokens of it.
MAX_PROMPT_CHARS = 2000
DEFAULT_MAX_UPLOAD_BYTES = 32 * 1024 * 1024

# int8 / float32 for the CPU image; float16 / int8_float16 exist for the
# local-only gpu Dockerfile target.
COMPUTE_TYPES = ("int8", "float32", "float16", "int8_float16")


@dataclass(frozen=True)
class Config:
    model_path: str = DEFAULT_MODEL_PATH
    compute_type: str = "int8"
    device: str = "cpu"
    cpu_threads: int = 0  # 0 = ctranslate2's default
    idle_unload_s: float = 600.0  # 0 = never unload
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    language: str | None = None  # None = auto-detect
    beam_size: int = 5

    def __post_init__(self) -> None:
        if self.compute_type not in COMPUTE_TYPES:
            raise ValueError(
                f"STT_COMPUTE_TYPE {self.compute_type!r} is not one of {', '.join(COMPUTE_TYPES)}"
            )


def load_config(environ: dict[str, str] | None = None) -> Config:
    env = os.environ if environ is None else environ
    return Config(
        model_path=env.get("STT_MODEL_PATH") or DEFAULT_MODEL_PATH,
        compute_type=(env.get("STT_COMPUTE_TYPE") or "int8").strip().lower(),
        device=env.get("STT_DEVICE") or "cpu",
        cpu_threads=int(env.get("STT_CPU_THREADS") or 0),
        idle_unload_s=float(env.get("STT_IDLE_UNLOAD_S") or 600),
        max_upload_bytes=int(env.get("STT_MAX_UPLOAD_BYTES") or DEFAULT_MAX_UPLOAD_BYTES),
        language=env.get("STT_LANGUAGE") or None,
        beam_size=int(env.get("STT_BEAM_SIZE") or 5),
    )
