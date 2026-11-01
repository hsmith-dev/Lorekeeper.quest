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
# postgres 768m, valkey 128m, nginx 128m = 14.5 GiB exactly.
AD7 = """\
OLLAMA_MEM_LIMIT=5.25g
# ML_MEM_LIMIT=2560m
TTS_MEM_LIMIT=2.5g
STT_MEM_LIMIT=1.25g
WEB_MEM_LIMIT=1g
WORKER_MEM_LIMIT=1024m
POSTGRES_MEM_LIMIT=768m
VALKEY_MEM_LIMIT=128m
#NGINX_MEM_LIMIT=128M
"""


# The ceiling for hard-coded compose limits (outside the sum). Shrink it in the
# PR that moves a literal to a *_MEM_LIMIT variable (E0-Platform.7).
FROZEN_LITERALS = frozenset({
    ("docker-compose.prod.yml", "postgres", "3g"),
    ("docker-compose.prod.yml", "valkey", "512m"),  # was "redis" (renamed, same limit)
    ("docker-compose.prod.yml", "ollama", "14g"),
    ("docker-compose.prod.yml", "backend", "14g"),
    ("docker-compose.prod.yml", "nginx", "256m"),
})


def run(tmp_path: Path, env: str, compose: str = "", baseline: str | None = None):
    (tmp_path / ".env.example").write_text(env)
    files = []
    if compose:
        (tmp_path / "docker-compose.yml").write_text(compose)
        files.append(tmp_path / "docker-compose.yml")
    base = None
    if baseline is not None:
        base = tmp_path / "literal_baseline.txt"
        base.write_text(baseline)
    return cmb.check(tmp_path / ".env.example", files, literal_baseline=base)


def test_repo_passes():
    report, errors = cmb.check(cmb.ENV_EXAMPLE, cmb.compose_files(cmb.REPO), literal_baseline=cmb.LITERAL_BASELINE)
    assert errors == [], errors


def test_literal_baseline_never_grows():
    baseline, errors = cmb.load_literal_baseline(cmb.LITERAL_BASELINE)
    assert errors == []
    grown = set(baseline) - FROZEN_LITERALS
    assert not grown, (
        f"memory_literal_limits_baseline.txt gained {sorted(grown)}; it only shrinks. "
        "Use a *_MEM_LIMIT variable declared in .env.example instead.")


def test_ceiling_is_binary_gib():
    # AD-7's "14.5 GB" is 14.5 GiB because Docker's g suffix is binary.
    assert cmb.LIMIT_BYTES == cmb.parse_size("14.5g") == int(14.5 * 1024**3)


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


@pytest.mark.parametrize("ref", [
    "${STT_MEM_LIMIT}", "$STT_MEM_LIMIT", "${STT_MEM_LIMIT:?set it}", "${STT_MEM_LIMIT:+1g}",
    "${STT_MEM_LIMIT-1g}", "${STT_MEM_LIMIT:=1g}",
])
def test_every_reference_form_must_be_declared(tmp_path, ref):
    _, errors = run(tmp_path, "", f"memory: {ref}\n")
    assert len(errors) == 1 and "STT_MEM_LIMIT" in errors[0] and "not declared" in errors[0]


@pytest.mark.parametrize("ref", ["${STT_MEM_LIMIT}", "$STT_MEM_LIMIT", "${STT_MEM_LIMIT:?x}", "${STT_MEM_LIMIT:+3g}"])
def test_reference_without_default_only_needs_declaring(tmp_path, ref):
    _, errors = run(tmp_path, "# STT_MEM_LIMIT=1280m\n", f"memory: {ref}\n")
    assert errors == []


@pytest.mark.parametrize("ref", ["${STT_MEM_LIMIT-3g}", "${STT_MEM_LIMIT:=3g}"])
def test_other_default_forms_must_match(tmp_path, ref):
    _, errors = run(tmp_path, "# STT_MEM_LIMIT=1280m\n", f"memory: {ref}\n")
    assert len(errors) == 1 and "make them match" in errors[0]


def test_compose_globs(tmp_path):
    for name in ("docker-compose.yml", "docker-compose.prod.yaml", "compose.yaml", "compose.override.yml", "other.yml"):
        (tmp_path / name).write_text("")
    assert [p.name for p in cmb.compose_files(tmp_path)] == [
        "compose.override.yml", "compose.yaml", "docker-compose.prod.yaml", "docker-compose.yml"]


COMPOSE_LITERALS = """\
services:
  postgres:
    deploy:
      resources:
        limits:
          memory: 3g
        reservations:
          memory: 1g
  redis:
    mem_limit: "512m"  # old syntax
  ml:
    deploy:
      resources:
        limits:
          memory: ${ML_MEM_LIMIT:-2560m}
volumes:
  data:
"""


def test_literal_limit_not_in_baseline_fails(tmp_path):
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", COMPOSE_LITERALS)
    assert len(errors) == 2
    assert "docker-compose.yml:6" in errors[0] and "'postgres'" in errors[0] and "POSTGRES_MEM_LIMIT" in errors[0]
    assert "docker-compose.yml:10" in errors[1] and "'redis'" in errors[1] and "512m" in errors[1]


def test_baselined_literal_passes_and_is_reported_outside_the_sum(tmp_path):
    baseline = ("docker-compose.yml postgres 3g  # until E0-Platform.7\n"
                "docker-compose.yml redis 512M  # until E0-Platform.7\n")
    report, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", COMPOSE_LITERALS, baseline)
    assert errors == []
    literal_lines = [l for l in report if "literal" in l]
    assert len(literal_lines) == 2 and all("NOT in the sum" in l for l in literal_lines)
    assert "2.50 GiB" in report[1]  # the sum is the variable only


def test_stale_literal_baseline_entry_fails(tmp_path):
    baseline = ("docker-compose.yml postgres 3g  # x\ndocker-compose.yml redis 512m  # x\n"
                "docker-compose.yml nginx 256m  # x\n")
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", COMPOSE_LITERALS, baseline)
    assert len(errors) == 1 and "nginx" in errors[0] and "remove it from the baseline" in errors[0]


def test_literal_baseline_entry_without_reason_fails(tmp_path):
    baseline = "docker-compose.yml postgres 3g\ndocker-compose.yml redis 512m  # x\n"
    _, errors = run(tmp_path, "# ML_MEM_LIMIT=2560m\n", COMPOSE_LITERALS, baseline)
    assert any("no reason" in e for e in errors)
