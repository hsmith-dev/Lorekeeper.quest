"""Static guard: the backend images install no model packages (E0-Platform.6).

Embeddings, NER and OCR come from the ml sidecar and speech from stt, so
both Dockerfiles install requirements.txt with a plain pip install: no
torch layer, no PyTorch CPU index, no spaCy model download, and no compiler
or libpq (every requirement has a binary wheel; asyncpg needs no libpq).
scripts/check_model_packages.py (CI-3) checks requirements.txt and the built
image's pip list; this checks the Dockerfiles themselves. Runs without Docker.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
DOCKERFILES = ["Dockerfile", "Dockerfile.prod"]
FORBIDDEN_TOKENS = ("torch", "spacy", "sentence-transformers", "en_core_web", "download.pytorch.org",
                    "build-essential", "libpq-dev", "gcc")


def _run_instructions(path: Path) -> list[list[str]]:
    """Return each RUN instruction as tokens, with line continuations joined."""
    logical: list[str] = []
    buf = ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        # Docker drops comment lines even inside a backslash continuation.
        if line.startswith("#") or (not buf and not line):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        logical.append(buf + line)
        buf = ""
    if buf:
        logical.append(buf)
    return [shlex.split(ins)[1:] for ins in logical if ins.split(None, 1)[0].upper() == "RUN"]


def _pip_installs(name: str) -> list[list[str]]:
    return [t for t in _run_instructions(BACKEND / name) if "pip" in t and "install" in t]


@pytest.mark.parametrize("name", DOCKERFILES)
def test_single_plain_requirements_install(name):
    installs = _pip_installs(name)
    assert len(installs) == 1, f"{name}: expected one pip install, got {installs}"
    tokens = installs[0]
    assert "-r" in tokens and "requirements.txt" in tokens, f"{name}: pip install is not -r requirements.txt"
    assert not any(t.startswith(("--index-url", "--extra-index-url", "-i")) for t in tokens), (
        f"{name}: the requirements install must use plain PyPI, no extra index"
    )


@pytest.mark.parametrize("name", DOCKERFILES)
def test_no_model_or_compiler_steps(name):
    for tokens in _run_instructions(BACKEND / name):
        joined = " ".join(tokens).lower()
        for bad in FORBIDDEN_TOKENS:
            assert bad not in joined, f"{name}: RUN mentions {bad!r}: {joined}"
