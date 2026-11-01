"""Unit tests for scripts/check_memory_budget.py (CI-14, E0-QA.10).

Run: python -m pytest -q scripts/test_check_memory_budget.py  (stdlib + pytest)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("check_memory_budget", HERE / "check_memory_budget.py")
cmb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = cmb
_spec.loader.exec_module(cmb)

# AD-7's table: ollama 5.25g, ml 2.5g, tts 2.5g, stt 1.25g, web 1g, worker 1g,
# postgres 768m, redis 128m, nginx 128m = 14.5 GiB exactly.
AD7 = """\
OLLAMA_MEM_LIMIT=5.25g
# ML_MEM_LIMIT=2560m
TTS_MEM_LIMIT=2.5g
STT_MEM_LIMIT=1.25g
WEB_MEM_LIMIT=1g
WORKER_MEM_LIMIT=1024m
POSTGRES_MEM_LIMIT=768m
REDIS_MEM_LIMIT=128m
#NGINX_MEM_LIMIT=128M
"""


def run(tmp_path: Path, env: str, compose: str = ""):
    (tmp_path / ".env.example").write_text(env)
    files = []
    if compose:
        (tmp_path / "docker-compose.yml").write_text(compose)
        files.append(tmp_path / "docker-compose.yml")
    return cmb.check(tmp_path / ".env.example", files)


def test_repo_passes():
    compose = sorted(cmb.REPO.glob("docker-compose*.yml"))
    report, errors = cmb.check(cmb.ENV_EXAMPLE, compose)
    assert errors == [], errors


@pytest.mark.parametrize("value, expected", [
    ("2560m", 2560 * 1024**2), ("2.5g", int(2.5 * 1024**3)), ("768M", 768 * 1024**2),
    ("128mb", 128 * 1024**2), ("1073741824", 1024**3), ("512k", 512 * 1024),
])
def test_parse_size(value, expected):
    assert cmb.parse_size(value) == expected


def test_ad7_table_exactly_at_ceiling_passes(tmp_path):
    report, errors = run(tmp_path, AD7)
    assert errors == []
    assert "14.50 GiB" in report[-1]


def test_over_ceiling_fails_and_prints_each_limit(tmp_path):
    report, errors = run(tmp_path, AD7 + "DIARIZE_MEM_LIMIT=1m\n")
    assert len(errors) == 1 and "over the AD-7 ceiling" in errors[0] and "lower another limit" in errors[0]
    text = "\n".join(report)
    for var in ("OLLAMA_MEM_LIMIT", "ML_MEM_LIMIT", "NGINX_MEM_LIMIT", "DIARIZE_MEM_LIMIT", "sum"):
        assert var in text


def test_no_limits_passes_vacuously(tmp_path):
    report, errors = run(tmp_path, "SECRET_KEY=x\n# Override with ML_MEM_LIMIT in .env\n")
    assert errors == [] and "nothing to sum" in report[0]


def test_bad_size_fails(tmp_path):
    _, errors = run(tmp_path, "ML_MEM_LIMIT=lots\n")
    assert len(errors) == 1 and "ML_MEM_LIMIT" in errors[0]


def test_declared_twice_fails(tmp_path):
    _, errors = run(tmp_path, "ML_MEM_LIMIT=1g\n# ML_MEM_LIMIT=2g\n")
    assert len(errors) == 1 and "declared twice" in errors[0]


def test_compose_matching_default_passes(tmp_path):
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", "        memory: ${ML_MEM_LIMIT:-2.5g}\n")
    assert errors == []


def test_compose_undeclared_variable_fails(tmp_path):
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", "memory: ${ML_MEM_LIMIT:-2560m}\nmemory: ${STT_MEM_LIMIT:-1280m}\n")
    assert len(errors) == 1
    assert "docker-compose.yml:2" in errors[0] and "STT_MEM_LIMIT" in errors[0] and "not declared" in errors[0]


def test_compose_different_default_fails(tmp_path):
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", "memory: ${ML_MEM_LIMIT:-3g}\n")
    assert len(errors) == 1 and "ML_MEM_LIMIT" in errors[0] and "make them match" in errors[0]


def test_compose_comment_lines_ignored(tmp_path):
    _, errors = run(tmp_path, "", "    # memory: ${ML_MEM_LIMIT:-3g}\n")
    assert errors == []
