"""Unit tests for scripts/check-licenses.py register mode (E0-QA.7).

Run: python -m pytest -q scripts/test_check_licenses.py  (needs pyyaml, Python 3.11+)
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "check-licenses.py"
_spec = importlib.util.spec_from_file_location("check_licenses", SCRIPT)
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)

POLICY = cl.Policy(cl.DEFAULT_POLICY)


def make_register(tmp_path: Path, entries: list[dict], rejected: list[dict] | None = None) -> "cl.Register":
    import yaml

    path = tmp_path / "register.yaml"
    path.write_text(yaml.safe_dump({"entries": entries, "rejected": rejected or []}))
    return cl.Register(path)


def entry(name: str, kind: str = "python", license: str = "MIT", editions=("agpl", "commercial"), **extra) -> dict:
    e = {"name": name, "kind": kind, "version": "1.0", "license": license,
         "source_url": f"https://example.invalid/{name}", "editions": list(editions), "notes": ""}
    e.update(extra)
    return e


def scan(reg, deps, edition="commercial", artifact="backend", eco="python"):
    failures, excepted, matched, missing, _ = cl.check_register_scan(POLICY, reg, eco, deps, edition, artifact)
    return failures, excepted, matched, missing


def entries_check(reg, edition="commercial", skip=frozenset()):
    return cl.check_register_entries(POLICY, reg, edition, set(skip))


# ---- scan vs register ------------------------------------------------------

@pytest.mark.parametrize("edition", cl.EDITIONS)
def test_registered_permissive_package_passes(tmp_path, edition):
    reg = make_register(tmp_path, [entry("fastapi")])
    failures, excepted, _, _ = scan(reg, [("fastapi", "1.0", "MIT License")], edition)
    assert failures == [] and excepted == []


def test_unregistered_package_fails(tmp_path):
    reg = make_register(tmp_path, [])
    failures, _, _, missing = scan(reg, [("leftpad", "1.0", "MIT")])
    assert len(failures) == 1 and "no register entry" in failures[0][3]
    assert missing == [("leftpad", "1.0", "MIT")]


def test_licence_drift_fails(tmp_path):
    reg = make_register(tmp_path, [entry("libfoo", license="MIT")])
    failures, _, _, _ = scan(reg, [("libfoo", "2.0", "GPL-3.0")], "agpl")
    assert len(failures) == 1
    assert "register says 'MIT', scan says 'GPL-3.0'" in failures[0][3]


def test_version_difference_is_informational(tmp_path):
    reg = make_register(tmp_path, [entry("fastapi")])
    failures, _, _, _ = scan(reg, [("fastapi", "9.9", "MIT")])
    assert failures == []


def test_normalisation_and_scanned_license_pin(tmp_path):
    reg = make_register(tmp_path, [
        entry("sniffio", license="MIT OR Apache-2.0"),
        entry("numba", license="BSD-2-Clause", scanned_license="BSD License"),
    ])
    failures, _, _, _ = scan(reg, [("sniffio", "1", "MIT License; Apache Software License"),
                                   ("numba", "1", "BSD License")])
    assert failures == []
    # the pin is exact: a changed metadata string is drift
    failures, _, _, _ = scan(reg, [("numba", "1", "BSD-3-Clause")])
    assert len(failures) == 1 and "register says 'BSD License'" in failures[0][3]


def test_npm_multiple_versions_and_licences(tmp_path):
    reg = make_register(tmp_path, [
        entry("lru-cache", kind="npm", license="ISC", version="5.1.1"),
        entry("lru-cache", kind="npm", license="BlueOak-1.0.0", version="11.5.2"),
        entry("picomatch", kind="npm", version="2.3.2, 4.0.4"),
    ])
    deps = [("lru-cache", "5.1.1", "ISC"), ("lru-cache", "11.6.0", "BlueOak-1.0.0"),
            ("picomatch", "4.0.4", "MIT")]
    failures, _, _, _ = scan(reg, deps, eco="npm", artifact="nginx")
    assert failures == []


@pytest.mark.parametrize("edition", cl.EDITIONS)
def test_cuda_wheels_fail_and_are_not_excepted(tmp_path, edition):
    reg = make_register(tmp_path, [entry("torch", license="BSD-3-Clause")])
    deps = [("torch", "2.5.0", "BSD-3-Clause"),
            ("nvidia-cublas-cu12", "12.4", "LicenseRef-NVIDIA-Proprietary"),
            ("nvidia-cusparselt-cu12", "0.6", "NVIDIA Proprietary Software")]
    failures, excepted, _, _ = scan(reg, deps, edition)
    assert [f[0] for f in failures] == ["nvidia-cublas-cu12", "nvidia-cusparselt-cu12"]
    assert all("no register entry" in f[3] and "proprietary" in f[3] for f in failures)
    assert excepted == []


def test_agpl_only_entry_in_commercial_artifact(tmp_path):
    reg = make_register(tmp_path, [entry("kokoro", license="Apache-2.0", editions=["agpl"], images=["tts"])])
    deps = [("kokoro", "1.0", "Apache-2.0")]
    failures, _, _, _ = scan(reg, deps, "commercial", "backend")
    assert len(failures) == 1 and "exclude commercial" in failures[0][3]
    failures, _, _, _ = scan(reg, deps, "commercial", "tts")
    assert len(failures) == 1, "the commercial build has no tts image"
    failures, _, _, _ = scan(reg, deps, "agpl", "backend")
    assert len(failures) == 1 and "AGPL-only" in failures[0][3]
    failures, _, _, _ = scan(reg, deps, "agpl", "tts")
    assert failures == []


def test_gpl_scan_only_passes_in_agpl_tts(tmp_path):
    reg = make_register(tmp_path, [entry("espeakng-loader", license="GPL-3.0-or-later",
                                         editions=["agpl"], images=["tts"])])
    deps = [("espeakng-loader", "0.2", "GPL-3.0-or-later")]
    assert scan(reg, deps, "agpl", "tts")[0] == []
    assert len(scan(reg, deps, "agpl", "backend")[0]) == 1
    assert len(scan(reg, deps, "agpl", None)[0]) == 1
    assert len(scan(reg, deps, "commercial", "tts")[0]) == 1


def test_gpl_scan_with_both_editions_fails_even_in_tts(tmp_path):
    reg = make_register(tmp_path, [entry("gplthing", license="GPL-3.0-only")])
    failures, _, _, _ = scan(reg, [("gplthing", "1", "GPL-3.0-only")], "agpl", "tts")
    assert len(failures) == 1 and "GPL" in failures[0][3]


def test_denied_package_fails_even_if_registered(tmp_path):
    reg = make_register(tmp_path, [entry("pyvips-binary")])
    failures, _, _, _ = scan(reg, [("pyvips_binary", "8.16", "MIT")], "agpl")
    assert len(failures) == 1 and "denied" in failures[0][3]


@pytest.mark.parametrize("edition", cl.EDITIONS)
def test_owner_exceptions_keep_working(tmp_path, edition):
    reg = make_register(tmp_path, [
        entry("fpdf2", license="LGPL-3.0-only"),
        entry("python-bidi", license="LGPL-3.0-or-later",
              scanned_license="GNU Library or Lesser General Public License (LGPL)"),
    ])
    deps = [("fpdf2", "2.8.7", "LGPL-3.0-only"),
            ("python-bidi", "0.6", "GNU Library or Lesser General Public License (LGPL)")]
    failures, excepted, matched, _ = scan(reg, deps, edition)
    assert failures == [] and len(excepted) == 2
    failures, excepted = entries_check(reg, edition)
    assert failures == [] and len(excepted) == 2


def test_pip_package_model_matches_scan(tmp_path):
    model = entry("en_core_web_trf", kind="model", pip_package="en-core-web-trf",
                  download="https://example.invalid/x.whl", sha256="a" * 64)
    reg = make_register(tmp_path, [model])
    failures, _, matched, _ = scan(reg, [("en_core_web_trf", "3.7.3", "MIT")])
    assert failures == [] and len(matched) == 1


# ---- register entries and edition rules -------------------------------------

def test_gpl_entry_outside_tts_fails_in_agpl(tmp_path):
    reg = make_register(tmp_path, [entry("espeak-ng", kind="apt", license="GPL-3.0-or-later",
                                         editions=["agpl"], images=["backend"])])
    for edition in cl.EDITIONS:
        failures, _ = entries_check(reg, edition)
        assert len(failures) == 1, edition


@pytest.mark.parametrize("edition", cl.EDITIONS)
def test_espeak_ng_tts_only_entry_passes(tmp_path, edition):
    reg = make_register(tmp_path, [entry("espeak-ng", kind="apt", license="GPL-3.0-or-later",
                                         editions=["agpl"], images=["tts"])])
    assert entries_check(reg, edition) == ([], [])


def test_gpl_entry_in_both_editions_fails(tmp_path):
    reg = make_register(tmp_path, [entry("gplthing", license="AGPL-3.0-only")])
    assert len(entries_check(reg, "commercial")[0]) == 1
    assert len(entries_check(reg, "agpl")[0]) == 1


def test_system_lib_allowlist(tmp_path):
    reg = make_register(tmp_path, [
        entry("libvips42", kind="apt", license="LGPL-2.1-or-later"),
        entry("libpango-1.0-0", kind="apt", license="LGPL-2.0-or-later"),
        entry("libglib2.0-0", kind="apt", license="LGPL-2.1-or-later"),
        entry("libharfbuzz0b", kind="apt", license="LGPL-2.1-or-later"),
    ])
    assert entries_check(reg, "commercial") == ([], [])
    reg = make_register(tmp_path, [
        entry("libsomething", kind="apt", license="LGPL-2.1-or-later"),  # not allowlisted
        entry("libvips42", kind="apt", license="GPL-2.0-only"),          # not LGPL
        entry("libvips-py", kind="python", license="LGPL-2.1-or-later"),  # not apt
    ])
    failures, _ = entries_check(reg, "commercial")
    assert sorted(f[0] for f in failures) == ["apt:libsomething", "apt:libvips42", "python:libvips-py"]


@pytest.mark.parametrize("lic", ["CC-BY-NC-4.0", "Hippocratic-2.1", "UNKNOWN", "LicenseRef-Custom", "WTFPL-ish"])
@pytest.mark.parametrize("edition", cl.EDITIONS)
def test_bad_licences_fail_in_both_editions(tmp_path, lic, edition):
    reg = make_register(tmp_path, [entry("thing", kind="model", license=lic,
                                         download="https://example.invalid/m", sha256="b" * 64)])
    assert len(entries_check(reg, edition)[0]) == 1


def test_agpl_only_entry_with_commercial_image_fails_in_commercial(tmp_path):
    reg = make_register(tmp_path, [entry("kokoro", editions=["agpl"], images=["tts", "backend"])])
    failures, _ = entries_check(reg, "commercial")
    assert len(failures) == 1 and "backend" in failures[0][3]


def test_scanned_entries_are_not_double_reported(tmp_path):
    reg = make_register(tmp_path, [entry("gplthing", license="GPL-3.0-only")])
    failures, _, matched, _ = scan(reg, [("gplthing", "1", "GPL-3.0-only")])
    assert len(failures) == 1
    assert entries_check(reg, "commercial", matched) == ([], [])


def test_schema_errors(tmp_path):
    reg = make_register(tmp_path, [
        {"name": "x", "kind": "python"},
        entry("m", kind="model"),
        entry("f", kind="font", artifact="a.woff2", sha256="nothex"),
        entry("e", editions=["gpl"]),
        entry("k", kind="wheel"),
    ], rejected=[{"name": "Piper"}])
    text = "\n".join(reg.errors)
    assert "python:x: missing field(s)" in text
    assert "model:m: model entries need `artifact`" in text and "model:m: model entries need a 64-hex" in text
    assert "font:f: font entries need a 64-hex" in text
    assert "python:e: editions" in text
    assert "wheel:k: kind must be one of" in text
    assert "rejected[0]" in text


def test_schema_errors_do_not_crash_scans(tmp_path):
    bad = [
        {"kind": "python", "version": "1.0", "license": "MIT", "source_url": "u",
         "editions": ["agpl"], "notes": ""},                                   # no name
        {"name": "nolicence", "kind": "python", "version": "1.0", "source_url": "u",
         "editions": ["agpl", "commercial"], "notes": ""},                      # no license
        entry(["listname"]),                                                     # name is a list
        entry("mapkind", kind={"a": 1}),                                         # kind is a mapping
    ]
    reg = make_register(tmp_path, bad + [entry("fastapi")])
    assert len(reg.errors) >= 4
    assert [e["name"] for e in reg.entries] == ["fastapi"]
    deps = [("nolicence", "1.0", "MIT"), ("fastapi", "1.0", "MIT")]
    for edition in cl.EDITIONS:
        failures, _, _, _ = scan(reg, deps, edition)
        assert [f[0] for f in failures] == ["nolicence"] and "no register entry" in failures[0][3]
        assert entries_check(reg, edition) == ([], [])
    assert cl.check_artifacts(POLICY, reg, tmp_path)[0] == []
    assert cl.label({}) == "?:?"


def test_unquoted_version_and_licence_are_schema_errors(tmp_path):
    reg = make_register(tmp_path, [entry("numpyish", version=1.10), entry("weird", license=123)])
    text = "\n".join(reg.errors)
    assert "python:numpyish: field(s) ['version'] must be strings" in text
    assert "python:weird: field(s) ['license'] must be strings" in text
    assert reg.entries == []


def test_register_licence_is_normalised_too(tmp_path):
    reg = make_register(tmp_path, [entry("dual", kind="npm", license="(MIT OR Apache-2.0)")])
    failures, _, _, _ = scan(reg, [("dual", "1.0", "(MIT OR Apache-2.0)")], eco="npm")
    assert failures == []


def test_denied_package_in_register_fails_without_scan(tmp_path):
    reg = make_register(tmp_path, [entry("pyvips-binary")])
    for edition in cl.EDITIONS:
        failures, _ = entries_check(reg, edition)
        assert len(failures) == 1 and "denied" in failures[0][3]


@pytest.mark.parametrize("lic, expected", [
    ("LGPL-2.1-or-later AND GPL-3.0-only", "gpl"),
    ("GPL-2.0-only OR LGPL-3.0-only", "gpl"),
    ("GNU Lesser General Public License v2 or later (LGPLv2+) AND GNU General Public License v3", "gpl"),
    ("GNU Library or Lesser General Public License (LGPL); GNU General Public License v3 (GPLv3)", "gpl"),
    ("LGPL-3.0-only", "lgpl"),
    ("LGPL-2.1-or-later", "lgpl"),
    ("GNU Lesser General Public License v3 (LGPLv3)", "lgpl"),
    ("GNU Lesser General Public License v2 or later (LGPLv2+)", "lgpl"),
    ("GNU Library or Lesser General Public License (LGPL)", "lgpl"),
])
def test_classify_mixed_lgpl_gpl(lic, expected):
    assert cl.classify(POLICY, lic) == expected


def test_image_exception(tmp_path):
    redis = POLICY.exceptions[("image", "redis")]
    reg = make_register(tmp_path, [entry("redis", kind="image", license=redis["license"])])
    for edition in cl.EDITIONS:
        failures, excepted = entries_check(reg, edition)
        assert failures == [] and [x[0] for x in excepted] == ["image:redis"]
    reg = make_register(tmp_path, [entry("redis", kind="image", license="SSPL-1.0")])
    failures, excepted = entries_check(reg, "commercial")
    assert excepted == [] and len(failures) == 1 and failures[0][0] == "image:redis"


# ---- register vs artifacts --------------------------------------------------

def _repo(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "repo"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    try:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    except (OSError, subprocess.CalledProcessError):
        pass  # the checker falls back to walking the tree
    return root


def test_artifacts_pass_when_hashes_match(tmp_path):
    data = b"font bytes"
    root = _repo(tmp_path, {"site/fonts/a.woff2": data, "site/index.html": b"<html>"})
    reg = make_register(tmp_path, [entry("A", kind="font", license="OFL-1.1", artifact="site/fonts/a.woff2",
                                         sha256=hashlib.sha256(data).hexdigest())])
    failures, n = cl.check_artifacts(POLICY, reg, root)
    assert failures == [] and n == 1


def test_artifact_sha_mismatch_and_missing_file(tmp_path):
    root = _repo(tmp_path, {"site/fonts/a.woff2": b"changed"})
    reg = make_register(tmp_path, [
        entry("A", kind="font", license="OFL-1.1", artifact="site/fonts/a.woff2", sha256="0" * 64),
        entry("B", kind="font", license="OFL-1.1", artifact="site/fonts/gone.woff2", sha256="0" * 64),
    ])
    failures, _ = cl.check_artifacts(POLICY, reg, root)
    reasons = [f[3] for f in failures]
    assert any("sha256 mismatch" in r for r in reasons)
    assert any("does not exist" in r for r in reasons)


def test_unregistered_baked_artifact_fails(tmp_path):
    root = _repo(tmp_path, {"src/ml/models/lorekeeper.gguf": b"gguf", "src/app/main.py": b""})
    reg = make_register(tmp_path, [])
    failures, n = cl.check_artifacts(POLICY, reg, root)
    assert n == 1 and failures[0][0] == "src/ml/models/lorekeeper.gguf"
    assert "no register entry" in failures[0][3]


# ---- CLI --------------------------------------------------------------------

def run_cli(*args, env=None, cwd=None):
    full_env = {k: v for k, v in os.environ.items() if k not in ("LOREKEEPER_EDITION", "GITHUB_ACTIONS")}
    full_env.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env=full_env, cwd=cwd)


def _npm_json(tmp_path: Path, rows: dict) -> Path:
    p = tmp_path / "npm.json"
    p.write_text(json.dumps({k: {"licenses": v} for k, v in rows.items()}))
    return p


def test_cli_bad_edition_value_exits_2(tmp_path):
    npm = _npm_json(tmp_path, {"react@18.3.1": "MIT"})
    reg = make_register(tmp_path, [entry("react", kind="npm")])
    r = run_cli("--npm", str(npm), "--register", str(reg.path), env={"LOREKEEPER_EDITION": "foo"})
    assert r.returncode == 2 and "LOREKEEPER_EDITION" in r.stderr
    r = run_cli("--npm", str(npm), "--register", str(reg.path), "--edition", "foo")
    assert r.returncode == 2


def test_cli_edition_from_env(tmp_path):
    npm = _npm_json(tmp_path, {"kokoro-web@1.0.0": "Apache-2.0"})
    reg = make_register(tmp_path, [entry("kokoro-web", kind="npm", license="Apache-2.0",
                                         editions=["agpl"], images=["tts"])])
    args = ("--npm", str(npm), "--register", str(reg.path), "--artifact", "tts")
    assert run_cli(*args, env={"LOREKEEPER_EDITION": "agpl"}).returncode == 0
    r = run_cli(*args)  # default: commercial
    assert r.returncode == 1 and "edition: commercial" in r.stdout


def test_cli_unregistered_exits_1_and_emits_stub(tmp_path):
    npm = _npm_json(tmp_path, {"leftpad@1.0.0": "MIT"})
    reg = make_register(tmp_path, [])
    r = run_cli("--npm", str(npm), "--register", str(reg.path), "--emit-missing")
    assert r.returncode == 1
    assert '- {name: "leftpad", kind: npm, version: "1.0.0", license: "MIT"' in r.stdout


def test_cli_without_register_is_unchanged(tmp_path):
    npm = _npm_json(tmp_path, {"react@18.3.1": "MIT", "gplpkg@1.0.0": "GPL-3.0"})
    r = run_cli("--npm", str(npm), env={"LOREKEEPER_EDITION": "foo"})  # edition ignored without --register
    assert r.returncode == 1
    assert "== npm: 2 packages, 1 violation(s), 0 exception(s)" in r.stdout
    assert "dependency licence violation(s)" in r.stdout
    r = run_cli("--check-artifacts")
    assert r.returncode == 2


def test_real_register_is_valid():
    reg = cl.Register(cl.REPO_ROOT / "licenses" / "register.yaml")
    assert reg.errors == []
    names = {(e["kind"], e["name"]) for e in reg.entries}
    assert ("apt", "espeak-ng") in names
    assert sum(1 for e in reg.entries if e["kind"] == "image") >= 5
    for edition in cl.EDITIONS:
        failures, _ = entries_check(reg, edition)
        assert failures == [], (edition, failures)
    assert not any(n.startswith("nvidia-") for _, n in names)
