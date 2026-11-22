"""scripts/deploy-oci.sh: the AD-16 edition rule, the image tag, and a
source-only deploy (E0-Platform.9). The functions run in bash with the
script sourced (sourcing deploys nothing) and a stub `docker` first on PATH
that records every call."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "deploy-oci.sh"

pytestmark = pytest.mark.skipif(
    not SCRIPT.exists() or shutil.which("bash") is None, reason="needs the repo's scripts/ and bash")


def _run(tmp_path: Path, snippet: str, env: dict[str, str] | None = None, dotenv: str | None = None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "docker.calls"
    stub = bin_dir / "docker"
    stub.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 1\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    if dotenv is not None:
        (root / ".env").write_text(dotenv)
    base = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; REPO_ROOT="{root}"; {snippet}'],
        env={**base, **(env or {})}, capture_output=True, text=True)
    docker_calls = calls.read_text().splitlines() if calls.exists() else []
    return proc, docker_calls


RULE = ('apply_edition_rule; rc=$?; '
        'echo "rc=$rc profiles=[${COMPOSE_PROFILES-}] edition=${LOREKEEPER_EDITION-}"')


@pytest.mark.parametrize("env,dotenv,expected", [
    ({}, None, "profiles=[tts] edition=agpl"),  # unset: AGPL
    ({"LOREKEEPER_EDITION": "agpl"}, None, "profiles=[tts]"),
    ({"LOREKEEPER_EDITION": "AGPL", "COMPOSE_PROFILES": "gpu"}, None, "profiles=[gpu,tts]"),
    ({"COMPOSE_PROFILES": "tts"}, None, "profiles=[tts]"),  # not doubled
    ({}, "LOREKEEPER_EDITION=agpl\nCOMPOSE_PROFILES=extra\n", "profiles=[extra,tts]"),
    ({"LOREKEEPER_EDITION": "commercial"}, None, "profiles=[] edition=commercial"),
    ({"LOREKEEPER_EDITION": "commercial", "COMPOSE_PROFILES": "gpu"}, None, "profiles=[gpu]"),
    ({}, "LOREKEEPER_EDITION=commercial\n", "profiles=[] edition=commercial"),
])
def test_edition_rule_sets_profiles(tmp_path, env, dotenv, expected):
    proc, calls = _run(tmp_path, f"set +e; {RULE}", env, dotenv)
    assert "rc=0 " in proc.stdout, proc.stderr
    assert expected in proc.stdout
    if "commercial" in expected:
        assert "tts" not in proc.stdout.split("profiles=")[1].split("]")[0]
    assert calls == []


@pytest.mark.parametrize("env,dotenv", [
    ({"LOREKEEPER_EDITION": "commercial", "COMPOSE_PROFILES": "tts"}, None),
    ({"LOREKEEPER_EDITION": "commercial", "COMPOSE_PROFILES": "gpu, tts"}, None),
    ({}, "LOREKEEPER_EDITION=commercial\nCOMPOSE_PROFILES=tts\n"),
])
def test_commercial_with_tts_refuses_with_ad16_reason(tmp_path, env, dotenv):
    proc, calls = _run(tmp_path, f"set +e; {RULE}", env, dotenv)
    assert "rc=1 " in proc.stdout
    assert "AD-16" in proc.stderr and "commercial" in proc.stderr
    assert calls == []


def test_unknown_edition_refuses(tmp_path):
    proc, _ = _run(tmp_path, f"set +e; {RULE}", {"LOREKEEPER_EDITION": "enterprise"})
    assert "rc=1 " in proc.stdout and "agpl or commercial" in proc.stderr


def test_tag_from_env_then_dotenv_then_latest(tmp_path):
    proc, _ = _run(tmp_path, "resolve_tag", {"LOREKEEPER_TAG": "v1.2"})
    assert proc.stdout == "v1.2"
    proc, _ = _run(tmp_path, "resolve_tag", {"LOREKEEPER_TAG": "feat/x y"})
    assert proc.stdout == "feat-x-y"
    proc, _ = _run(tmp_path, "resolve_tag", dotenv="LOREKEEPER_TAG=v1.1\n")
    assert proc.stdout == "v1.1"
    (tmp_path / "repo" / ".env").unlink()
    proc, _ = _run(tmp_path, "resolve_tag")  # repo/ is not a git checkout
    assert proc.stdout == "latest"


def test_sourcing_deploys_nothing(tmp_path):
    proc, calls = _run(tmp_path, "echo sourced")
    assert proc.returncode == 0 and proc.stdout.strip() == "sourced" and calls == []


def test_deploy_is_source_only_on_the_prod_compose_file():
    text = SCRIPT.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"docker\s+(push|login)\b|--push\b|buildx\s+build\b.*--push", code)
    assert "docker buildx bake --load" in code
    assert "docker compose -f docker-compose.prod.yml pull --ignore-buildable" in code
    assert "docker compose -f docker-compose.prod.yml up -d --no-build --remove-orphans" in code
    # Only docker-compose.prod.yml (and .env), never a second compose file.
    assert set(re.findall(r"docker compose((?:\s+-f\s+\S+)+)", code)) == {" -f docker-compose.prod.yml"}
    assert "--entrypoint" not in code
    # The model import is kept.
    assert "ollama create lorekeeper -f /import-models/lorekeeper-Modelfile" in code
    assert "ollama create lorekeeper-base -f /import-models/base-Modelfile" in code


def test_restore_script_uses_web_image_client_and_no_restart():
    text = (REPO / "scripts" / "restore-db.sh").read_text()
    assert "--no-restart" in text
    assert "run --rm --no-deps -T web python scripts/boot_migrate.py restore" in text
    assert "--entrypoint" not in text
    assert "pg_restore -U" not in text  # no longer the postgres container's pg16 client


def _ok_stub(tmp_path: Path, *, fail_on: str = "") -> tuple[Path, Path]:
    """A `docker` that records `<LOREKEEPER_TAG>|<VITE_API_URL>|<args>` and
    succeeds, except for calls containing `fail_on`."""
    bin_dir = tmp_path / "okbin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "ok.calls"
    stub = bin_dir / "docker"
    fail = f'case "$*" in *"{fail_on}"*) exit 1;; esac\n' if fail_on else ""
    stub.write_text(f'#!/bin/sh\necho "${{LOREKEEPER_TAG-}}|${{VITE_API_URL-}}|$*" >> "{calls}"\n{fail}exit 0\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bin_dir, calls


def _env(bin_dir: Path, tmp_path: Path) -> dict[str, str]:
    return {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}


def test_build_images_always_bakes_this_checkout_with_dotenv_build_args(tmp_path):
    """No reuse of an existing tag (it may be older source), the bake file
    named explicitly, and VITE_API_URL taken from .env like compose did."""
    bin_dir, calls = _ok_stub(tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("VITE_API_URL=https://api.example\n")
    proc = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; REPO_ROOT="{root}"; build_images v1.2'],
                          env=_env(bin_dir, tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    lines = calls.read_text().splitlines()
    assert not any("image inspect" in line for line in lines)
    assert f"v1.2|https://api.example|buildx bake --load -f {root}/docker-bake.hcl" in lines


def test_build_images_without_buildx_refuses(tmp_path):
    bin_dir, calls = _ok_stub(tmp_path, fail_on="buildx version")
    proc = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; REPO_ROOT="{tmp_path}"; build_images v1.2'],
                          env=_env(bin_dir, tmp_path), capture_output=True, text=True)
    assert proc.returncode != 0 and "buildx" in proc.stderr
    assert not any("bake" in line for line in calls.read_text().splitlines())


RESTORE = REPO / "scripts" / "restore-db.sh"
PRE = "pre-upgrade_20261121T101500Z_0f1c3b194a4b.dump"


def _restore(tmp_path: Path, args: list[str], dotenv: str, fail_on: str = ""):
    """Run a copy of restore-db.sh (it cds to its own repo root) against the stub."""
    root = tmp_path / "rrepo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(RESTORE, root / "scripts" / "restore-db.sh")
    (root / ".env").write_text(dotenv)
    bin_dir, calls = _ok_stub(tmp_path, fail_on=fail_on)
    proc = subprocess.run(["bash", str(root / "scripts" / "restore-db.sh"), *args], input="yes\n",
                          env=_env(bin_dir, tmp_path), capture_output=True, text=True)
    return proc, calls.read_text().splitlines()


@pytest.mark.parametrize("args", [["--no-restart", PRE], [PRE, "--no-restart"]])
def test_restore_pre_upgrade_dump_no_restart(tmp_path, args):
    proc, calls = _restore(tmp_path, args, 'POSTGRES_DB=lorekeeper\nLOREKEEPER_TAG="v1.2"\n')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    restores = [c for c in calls if "boot_migrate.py restore" in c]
    # The volume name becomes the in-container path; the quoted .env tag is unquoted.
    assert restores == ["v1.2||compose -f docker-compose.prod.yml run --rm --no-deps -T web "
                        f"python scripts/boot_migrate.py restore /backups/{PRE}"]
    assert any(c.endswith("stop web worker") for c in calls)
    assert not any("start web worker" in c for c in calls)


def test_restore_failure_with_no_restart_still_leaves_services_stopped(tmp_path):
    proc, calls = _restore(tmp_path, ["--no-restart", PRE], "POSTGRES_DB=lorekeeper\n",
                           fail_on="boot_migrate.py restore")
    assert proc.returncode != 0
    assert not any("start web worker" in c for c in calls)


def test_restore_without_no_restart_restarts(tmp_path):
    proc, calls = _restore(tmp_path, [PRE], "POSTGRES_DB=lorekeeper\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls[-1].startswith("latest|") and calls[-1].endswith("start web worker")
