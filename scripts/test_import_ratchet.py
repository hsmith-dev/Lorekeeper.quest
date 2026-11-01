"""CI-2 (AD-1): the import-linter contracts exist and their exceptions only shrink.

src/backend/.importlinter holds the layer contracts. Today's direct model
imports (the four in-process model services) are listed in the `models`
contract's ignore_imports, each under a `# ratchet: <reason>` line. This test:

  * fails if an ignore_imports line is not in FROZEN_IGNORES (the list grew),
    or has no `# ratchet:` reason above it;
  * fails if one of the contracts the E0-QA.10 AC names is missing or has
    changed type;
  * runs lint-imports on a throwaway copy of the package layout with the real
    config, to prove each contract fails on a planted violation and that a
    stale ignore_imports line fails too (skipped when import-linter is not
    installed; gates.yml installs it).

A stale line (an import that no longer exists) is caught by import-linter
itself (unmatched_ignore_imports_alerting = error): remove it from
.importlinter and from FROZEN_IGNORES.

Run: python -m pytest -q scripts/test_import_ratchet.py
"""
from __future__ import annotations

import configparser
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "src/backend/.importlinter"

# The ceiling. Remove a line here in the PR that removes it from .importlinter
# (E0-Platform.6 removes the other three; E0-QA.9 removed vision_service ->
# easyocr when OCR moved to ml /v1/ocr). Never add one.
FROZEN_IGNORES = {
    "models": frozenset({
        "app.services.nlp_service -> spacy",
        "app.services.embedding_service -> sentence_transformers",
        "app.services.transcription_service -> whisper",
    }),
}

# Contracts the E0-QA.10 AC names: id -> type.
REQUIRED_CONTRACTS = {"layers": "layers", "domain": "forbidden", "clients": "forbidden",
                      "clients_callers": "forbidden", "models": "forbidden"}

# app.access (AD-13) sits between services and schemas (E0-Access.2); app.jobs
# (AD-2) between api and services (E0-Jobs.1).
REQUIRED_LAYERS = ["app.api", "app.jobs", "app.services", "app.access", "app.schemas", "app.db", "app.core", "(app.domain)"]
# The models contract, frozen whole: dropping a source module or a forbidden
# package is a weakening and must show up here in review.
FROZEN_MODEL_SOURCES = frozenset({
    "app.api", "app.jobs", "app.clients", "app.services", "app.access", "app.schemas", "app.db", "app.core", "app.domain",
    "app.main",
})
FROZEN_MODEL_PACKAGES = frozenset({
    "torch", "torchaudio", "torchvision", "transformers", "sentence_transformers", "spacy", "whisper",
    "faster_whisper", "ctranslate2", "easyocr", "onnxruntime", "kokoro", "kokoro_onnx", "misaki",
    "phonemizer", "espeakng_loader",
})


def ignore_entries(text: str) -> dict[str, list[tuple[str, str | None]]]:
    """{contract id: [(ignore line, ratchet reason or None)]} read from the raw file."""
    out: dict[str, list[tuple[str, str | None]]] = {}
    contract = None
    in_ignores = False
    reason: str | None = None
    for raw in text.splitlines():
        m = re.match(r"^\[importlinter:contract:([^\]]+)\]", raw)
        if m:
            contract, in_ignores, reason = m.group(1), False, None
            continue
        if re.match(r"^\S", raw):  # a new key (or section) ends the value
            key = re.match(r"^ignore_imports\s*[=:](.*)$", raw)
            in_ignores = contract is not None and key is not None
            reason = None
            if in_ignores and key.group(1).strip():  # a value on the key line has no ratchet reason
                out.setdefault(contract, []).append((key.group(1).strip(), None))
            continue
        if not in_ignores:
            continue
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"^#\s*ratchet\s*:\s*(.*)$", line)
            if m:
                reason = m.group(1).strip() or None
            continue
        out.setdefault(contract, []).append((line, reason))
        reason = None
    return out


def contracts() -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read(CONFIG)
    return cp


def values(cp: configparser.ConfigParser, section: str, key: str) -> list[str]:
    return [v.strip() for v in cp.get(section, key, fallback="").splitlines() if v.strip()]


# ---- the ratchet -----------------------------------------------------------

def test_ignore_imports_never_grow():
    entries = ignore_entries(CONFIG.read_text())
    for contract, lines in entries.items():
        grown = {line for line, _ in lines} - FROZEN_IGNORES.get(contract, frozenset())
        assert not grown, (
            f"[importlinter:contract:{contract}] ignore_imports gained {sorted(grown)}. The list only "
            "shrinks: fix the import (models go through app/clients, AD-1) instead of ignoring it.")


def test_every_ignore_has_a_ratchet_reason():
    for contract, lines in ignore_entries(CONFIG.read_text()).items():
        missing = [line for line, reason in lines if not reason]
        assert not missing, (
            f"[importlinter:contract:{contract}] ignore_imports {missing} lack a "
            "'# ratchet: <why, which story removes it>' line directly above")


def test_frozen_ignores_match_config():
    """A line removed from .importlinter must leave FROZEN_IGNORES too, so it can't come back."""
    entries = ignore_entries(CONFIG.read_text())
    for contract, frozen in FROZEN_IGNORES.items():
        current = {line for line, _ in entries.get(contract, [])}
        stale = frozen - current
        assert not stale, f"remove {sorted(stale)} from FROZEN_IGNORES['{contract}'] in {Path(__file__).name}"


def test_required_contracts_exist():
    cp = contracts()
    assert cp.get("importlinter", "root_package") == "app"
    for cid, ctype in REQUIRED_CONTRACTS.items():
        section = f"importlinter:contract:{cid}"
        assert cp.has_section(section), f"{CONFIG.name} lost the '{cid}' contract (E0-QA.10 AC)"
        assert cp.get(section, "type") == ctype, f"contract '{cid}' must be type {ctype}"


def test_contract_shapes():
    cp = contracts()
    assert values(cp, "importlinter:contract:layers", "layers") == REQUIRED_LAYERS
    assert values(cp, "importlinter:contract:domain", "source_modules") == ["app.domain"]
    assert {"app.api", "app.services", "app.access", "app.schemas", "app.db", "app.core", "app.clients",
            "app.main"} <= set(values(cp, "importlinter:contract:domain", "forbidden_modules"))
    assert values(cp, "importlinter:contract:clients", "source_modules") == ["app.clients"]
    assert {"app.api", "app.services", "app.access", "app.schemas", "app.db", "app.main"} <= set(
        values(cp, "importlinter:contract:clients", "forbidden_modules"))
    models = "importlinter:contract:models"
    assert set(values(cp, models, "source_modules")) == FROZEN_MODEL_SOURCES
    assert set(values(cp, models, "forbidden_modules")) == FROZEN_MODEL_PACKAGES
    callers = "importlinter:contract:clients_callers"
    assert set(values(cp, callers, "source_modules")) == {
        "app.access", "app.schemas", "app.db", "app.core", "app.domain"}
    assert values(cp, callers, "forbidden_modules") == ["app.clients"]
    assert cp.get(models, "unmatched_ignore_imports_alerting", fallback="error") == "error"


def test_parser_reads_reasons():
    text = (
        "[importlinter:contract:x]\nignore_imports =\n    # ratchet: because\n    a -> b\n    c -> d\n"
        "name = later key\n[importlinter:contract:y]\nignore_imports =\n    # plain comment\n    e -> f\n"
    )
    assert ignore_entries(text) == {"x": [("a -> b", "because"), ("c -> d", None)], "y": [("e -> f", None)]}


def test_parser_reads_value_on_key_line():
    text = "[importlinter:contract:x]\nignore_imports = app.x -> torch\n    # ratchet: r\n    a -> b\n"
    assert ignore_entries(text) == {"x": [("app.x -> torch", None), ("a -> b", "r")]}


# ---- planted violations (real lint-imports on a throwaway package) --------

HAVE_LINTER = importlib.util.find_spec("importlinter") is not None
needs_linter = pytest.mark.skipif(not HAVE_LINTER, reason="import-linter not installed (requirements-dev.txt)")

TODAY = {
    "services/nlp_service.py": "import spacy\n",
    "services/embedding_service.py": "from sentence_transformers import SentenceTransformer\n",
    "services/transcription_service.py": "import whisper\n",
    "services/vision_service.py": "from app.clients import ml\n",
    "services/journal_service.py": ("from app.access import context\nfrom app.db import base\n"
                                    "from app.schemas import journal\nfrom app.clients import ml\n"),
    "access/context.py": ("from app.schemas import journal\nfrom app.db import base\nfrom app.core import config\n"
                          "from app.domain import embedding\n"),
    "api/routes.py": "from app.services import journal_service\nfrom app.jobs import errors\n",
    "jobs/errors.py": ("from app.services import journal_service\nfrom app.access import context\n"
                       "from app.core import config\nfrom app.domain import embedding\n"),
    "schemas/journal.py": "from app.domain import embedding\n",
    "db/base.py": "from app.core import config\n",
    "core/config.py": "from app.domain import embedding\n",
    "clients/ml.py": "import httpx\nfrom app.core import config\nfrom app.domain import embedding\n",
    "domain/embedding.py": "EMBEDDING_DIM = 384\n",
    "main.py": "from app.api import routes\n",
}


def lint(tmp_path: Path, extra: dict[str, str | None] | None = None) -> subprocess.CompletedProcess[str]:
    files = dict(TODAY)
    files.update(extra or {})
    pkg = tmp_path / "app"
    for sub in ("", "api", "jobs", "services", "access", "schemas", "db", "core", "domain", "clients"):
        (pkg / sub).mkdir(parents=True, exist_ok=True)
        (pkg / sub / "__init__.py").write_text("")
    for rel, body in files.items():
        if body is not None:
            (pkg / rel).write_text(body)
    (tmp_path / ".importlinter").write_text(CONFIG.read_text())
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    return subprocess.run(
        [sys.executable, "-c", "import sys; from importlinter.cli import lint_imports_command as c; sys.exit(c())",
         "--no-cache"],
        cwd=tmp_path, env=env, capture_output=True, text=True)


@needs_linter
def test_layout_like_today_passes(tmp_path):
    r = lint(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


@needs_linter
@pytest.mark.parametrize("plant, contract, offender", [
    ({"db/bad.py": "from app.services import journal_service\n"}, "AD-1 layers", "app.db.bad -> app.services"),
    ({"core/bad.py": "import app.api.routes\n"}, "AD-1 layers", "app.core.bad -> app.api"),
    ({"domain/bad.py": "from app.clients import ml\n"}, "AD-1 app.domain imports no other app package", "app.domain.bad -> app.clients"),
    ({"clients/bad.py": "from app.db import base\n"}, "AD-1 app.clients imports only", "app.clients.bad -> app.db"),
    ({"schemas/bad.py": "from app.clients import ml\n"}, "AD-1 only services and above import app.clients", "app.schemas.bad -> app.clients"),
    ({"api/bad.py": "import torch\n"}, "AD-1 no model packages", "app.api.bad -> torch"),
    ({"clients/stt.py": "import faster_whisper\n"}, "AD-1 no model packages", "app.clients.stt -> faster_whisper"),
    ({"services/new_tts.py": "from kokoro_onnx import Kokoro\n"}, "AD-1 no model packages", "app.services.new_tts -> kokoro_onnx"),
    # app.access (E0-Access.2): below services and api, above schemas; never clients.
    ({"access/bad.py": "from app.services import journal_service\n"}, "AD-1 layers", "app.access.bad -> app.services"),
    ({"access/bad.py": "import app.api.routes\n"}, "AD-1 layers", "app.access.bad -> app.api"),
    ({"schemas/bad.py": "from app.access import context\n"}, "AD-1 layers", "app.schemas.bad -> app.access"),
    ({"access/bad.py": "from app.clients import ml\n"}, "AD-1 only services and above import app.clients", "app.access.bad -> app.clients"),
    ({"domain/bad.py": "from app.access import context\n"}, "AD-1 app.domain imports no other app package", "app.domain.bad -> app.access"),
    ({"clients/bad.py": "from app.access import context\n"}, "AD-1 app.clients imports only", "app.clients.bad -> app.access"),
    ({"access/bad.py": "import torch\n"}, "AD-1 no model packages", "app.access.bad -> torch"),
    # app.jobs (E0-Jobs.1): below api, above services.
    ({"jobs/bad.py": "import app.api.routes\n"}, "AD-1 layers", "app.jobs.bad -> app.api"),
    ({"services/bad.py": "from app.jobs import errors\n"}, "AD-1 layers", "app.services.bad -> app.jobs"),
    ({"access/bad.py": "from app.jobs import errors\n"}, "AD-1 layers", "app.access.bad -> app.jobs"),
    ({"jobs/bad.py": "import torch\n"}, "AD-1 no model packages", "app.jobs.bad -> torch"),
])
def test_planted_violation_fails(tmp_path, plant, contract, offender):
    r = lint(tmp_path, plant)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert contract in out and "BROKEN" in out
    assert offender in out


@needs_linter
def test_stale_ignore_line_fails(tmp_path):
    r = lint(tmp_path, {"services/transcription_service.py": "# STT now goes through a sidecar\n"})
    out = r.stdout + r.stderr
    assert r.returncode != 0, out
    assert "app.services.transcription_service -> whisper" in out
