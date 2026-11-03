"""Unit tests for scripts/check_model_packages.py (CI-3, E0-QA.10).

Run: python -m pytest -q scripts/test_check_model_packages.py  (stdlib + pytest)
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check_model_packages", HERE / "check_model_packages.py")
cmp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cmp  # dataclasses resolve annotations through sys.modules
_spec.loader.exec_module(cmp)

# The ceiling: the baseline may lose entries, never gain them. Shrink this set
# in the same PR that removes a line from model_packages_baseline.txt.
FROZEN_BASELINE = frozenset({
    "torch", "torchvision", "spacy", "en-core-web-trf", "sentence-transformers",
})


def write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


def run(tmp_path, requirements="", dockerfile="", baseline=""):
    req = write(tmp_path, "requirements.txt", requirements)
    dock = write(tmp_path, "Dockerfile", dockerfile)
    base = write(tmp_path, "baseline.txt", baseline)
    return cmp.check([req], [dock], base, root=tmp_path)


# ---- the real repo ---------------------------------------------------------

def test_repo_passes():
    assert cmp.check(cmp.REQUIREMENTS, cmp.DOCKERFILES, cmp.BASELINE) == []


def test_baseline_never_grows():
    baseline, errors = cmp.load_baseline(cmp.BASELINE)
    assert errors == []
    grown = set(baseline) - FROZEN_BASELINE
    assert not grown, (
        f"model_packages_baseline.txt gained {sorted(grown)}; the baseline only shrinks. "
        "Run the model in a sidecar behind app/clients instead.")


def test_baseline_entries_have_reasons():
    baseline, _ = cmp.load_baseline(cmp.BASELINE)
    assert all(reason for reason in baseline.values())


# ---- planted violations ----------------------------------------------------

def test_requirement_not_in_baseline_fails(tmp_path):
    errors = run(tmp_path, requirements="fastapi==0.115.0\ntorch==2.15.0\n")
    assert len(errors) == 1
    assert "requirements.txt:2" in errors[0] and "'torch'" in errors[0] and "sidecar" in errors[0]


def test_dockerfile_pip_install_not_in_baseline_fails(tmp_path):
    dockerfile = """\
        FROM python:3.11-slim
        RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \\
                torch==2.15.0+cpu torchvision==0.29.2+cpu
        """
    errors = run(tmp_path, dockerfile=dockerfile)
    assert len(errors) == 2
    assert all("Dockerfile:2" in e for e in errors)
    assert any("'torch'" in e for e in errors) and any("'torchvision'" in e for e in errors)


def test_spacy_download_installs_a_model_package(tmp_path):
    errors = run(tmp_path, dockerfile="RUN python -m spacy download en_core_web_sm\n")
    assert len(errors) == 1 and "'en-core-web-sm'" in errors[0] and "Dockerfile:1" in errors[0]


@pytest.mark.parametrize("name", ["en_core_web_trf", "de-core-news-lg", "xx_ent_wiki_sm"])
def test_spacy_pipeline_packages_are_forbidden(tmp_path, name):
    errors = run(tmp_path, requirements=f"{name}==3.7.1\n")
    assert len(errors) == 1, errors


def test_direct_reference_is_parsed(tmp_path):
    errors = run(tmp_path, requirements="torch @ https://download.pytorch.org/whl/cpu/torch-2.15.0.whl\n")
    assert len(errors) == 1 and "'torch'" in errors[0]


@pytest.mark.parametrize("spec", [
    "Sentence_Transformers==5.5.1", "sentence.transformers>=5", "SpaCy[cuda]==3.7.6",
    "kokoro-onnx==0.4", "Misaki", "phonemizer", "espeakng_loader", "TTS==0.22", "faster-whisper",
    "onnxruntime==1.20; platform_machine == 'x86_64'", "torchaudio==2.15", "TorchVision",
])
def test_names_are_pep503_normalized(tmp_path, spec):
    errors = run(tmp_path, requirements=spec + "\n")
    assert len(errors) == 1, errors


def test_include_is_followed(tmp_path):
    write(tmp_path, "more.txt", "easyocr==1.7.2\n")
    errors = run(tmp_path, requirements="-r more.txt\n")
    assert len(errors) == 1 and "more.txt:1" in errors[0]


def test_baselined_package_passes(tmp_path):
    errors = run(tmp_path, requirements="spacy==3.7.6\n", baseline="spacy: in-process NER until E0-Platform.6\n")
    assert errors == []


def test_stale_baseline_entry_fails(tmp_path):
    errors = run(tmp_path, requirements="fastapi\n", baseline="easyocr: OCR until E0-Platform.4\n")
    assert len(errors) == 1
    assert "'easyocr'" in errors[0] and "remove it from the baseline" in errors[0]


def test_baseline_entry_without_reason_fails(tmp_path):
    errors = run(tmp_path, requirements="spacy\n", baseline="spacy\n")
    assert any("no reason" in e for e in errors)


def test_baseline_entry_not_forbidden_fails(tmp_path):
    errors = run(tmp_path, requirements="fastapi\n", baseline="fastapi: why not\n")
    assert any("not a forbidden model package" in e for e in errors)


# ---- parsing details -------------------------------------------------------

def test_non_model_lines_are_ignored(tmp_path):
    dockerfile = """\
        RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \\
                -r requirements.txt
        # RUN pip install torch
        RUN python -m spacy validate
        RUN python -c "import torch" && ! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]'
        """
    requirements = "# torch is not here\nnumpy<2.0\nuvicorn[standard]==0.30.0  # spacy in a comment\n"
    assert run(tmp_path, requirements=requirements, dockerfile=dockerfile) == []


def test_pip_install_forms():
    assert cmp.pip_install_packages("python -m pip install --upgrade pip && pip3 install 'torch==2' easyocr") == ["pip", "torch", "easyocr"]
    assert cmp.pip_install_packages("/usr/local/bin/pip install -r req.txt --target=/x spacy") == ["spacy"]
    assert cmp.pip_install_packages("pip install ./wheels/foo.whl https://x/y.whl") == []
