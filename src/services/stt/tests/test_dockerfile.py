"""Static guard on the stt Dockerfile and lock (same rules as the ml sidecar's).

The GPU-stack guard after every pip install in `base`, offline env after the
bake, a HEALTHCHECK, the CPU stage last (so it is the default build), no
torch in the lock, the faster-whisper / ctranslate2 pins, and the model pins
equal to licenses/register.yaml's. Runs without Docker.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from stt_service.config import MODEL_REPO, MODEL_REVISION, MODEL_SHA256

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
LOCK = ROOT / "requirements.txt"
REGISTER = ROOT.parents[2] / "licenses" / "register.yaml"


def _instructions() -> list[tuple[str, list[str]]]:
    logical, buf = [], ""
    for raw in DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#") or (not buf and not line):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        logical.append(buf + line)
        buf = ""
    out = []
    for ins in logical:
        op, _, rest = ins.partition(" ")
        out.append((op.upper(), shlex.split(rest) if op.upper() == "RUN" else rest.split()))
    return out


def _stage(name: str) -> list[tuple[str, list[str]]]:
    """Instructions of one stage (FROM ... AS name), FROM line excluded."""
    out, current = [], None
    for op, t in _instructions():
        if op == "FROM":
            current = t[-1] if len(t) >= 3 and t[-2].upper() == "AS" else None
            continue
        if current == name:
            out.append((op, t))
    return out


def _runs(ins) -> list[list[str]]:
    return [t for op, t in ins if op == "RUN"]


def _is_pip_install(t: list[str]) -> bool:
    return "pip" in t and "install" in t


def _is_guard(t: list[str]) -> bool:
    j = " ".join(t)
    return t[:1] == ["!"] and "pip list" in j and "nvidia|cuda" in j and "torch==" in j


def _lock_pins() -> dict[str, str]:
    pins = {}
    for line in LOCK.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, version = line.partition("==")
            pins[name.lower()] = version
    return pins


def test_stages_and_cpu_is_last():
    froms = [t for op, t in _instructions() if op == "FROM"]
    assert [t[-1] for t in froms] == ["base", "gpu", "cpu"]
    assert froms[0][0] == "python:3.11-slim"
    assert froms[1][0] == froms[2][0] == "base"
    assert froms[-1][-1] != "gpu"


def test_guard_after_every_pip_install_in_base():
    runs = _runs(_stage("base"))
    installs = [i for i, t in enumerate(runs) if _is_pip_install(t)]
    assert installs, "base installs nothing?"
    for i in installs:
        assert any(_is_guard(t) for t in runs[i + 1:]), f"no GPU-stack guard after base RUN #{i}"
    assert any("requirements.txt" in t and "-r" in t for t in runs)


def test_faster_whisper_is_installed_without_deps_and_av_is_guarded():
    runs = _runs(_stage("base"))
    nodeps = [i for i, t in enumerate(runs) if "requirements-nodeps.txt" in t]
    assert nodeps and "--no-deps" in runs[nodeps[0]]
    guard = next(i for i, t in enumerate(runs) if _is_guard(t))
    assert guard > max(i for i, t in enumerate(runs) if _is_pip_install(t))
    joined = " ".join(runs[guard])
    assert "^av==" in joined and 'import av' in joined and "ffmpeg" in joined


def test_ffmpeg_comes_from_apt():
    runs = _runs(_stage("base"))
    apt = next(t for t in runs if "apt-get" in t and "install" in t)
    assert "ffmpeg" in apt and "--no-install-recommends" in apt


def test_offline_env_after_bake():
    ins = _stage("base")
    bake = max(i for i, (op, t) in enumerate(ins) if op == "RUN" and "bake_models.py" in t)
    env = " ".join(" ".join(t) for op, t in ins[bake:] if op == "ENV")
    assert "HF_HUB_OFFLINE=1" in env and "TRANSFORMERS_OFFLINE=1" in env


def test_healthcheck_user_and_single_worker():
    ins = _stage("base")
    hc = next(t for op, t in ins if op == "HEALTHCHECK")
    assert "--start-period=30s" in hc
    assert any(op == "USER" and t != ["root"] for op, t in ins)
    cmd = " ".join(next(t for op, t in ins if op == "CMD"))
    assert "stt_service.app:app" in cmd and '"--workers", "1"' in cmd


def test_gpu_stage_sets_cuda_and_pins_nvidia_wheels():
    gpu = _stage("gpu")
    env = " ".join(" ".join(t) for op, t in gpu if op == "ENV")
    assert "STT_DEVICE=cuda" in env and "LD_LIBRARY_PATH=" in env
    pkgs = [x for t in _runs(gpu) for x in t if x.startswith("nvidia-")]
    assert {p.split("==")[0] for p in pkgs} == {"nvidia-cublas-cu12", "nvidia-cudnn-cu12"}
    assert all("==" in p for p in pkgs)
    assert any(p.startswith("nvidia-cudnn-cu12==9.") for p in pkgs)
    assert _runs(_stage("cpu")) == []  # the default image adds nothing to base


def test_lock_pins():
    pins = _lock_pins()
    assert len(pins) == 29
    assert "faster-whisper" not in pins  # installed --no-deps from requirements-nodeps.txt
    assert "av" not in pins  # PyAV bundles a GPL-linked FFmpeg: never installed
    assert pins["ctranslate2"] == "4.8.4"
    nodeps = [l.strip() for l in (ROOT / "requirements-nodeps.txt").read_text().splitlines()
              if l.strip() and not l.startswith("#")]
    assert nodeps == ["faster-whisper==1.2.1"]
    assert "torch" not in pins
    assert not [p for p in pins if re.match(r"^(nvidia|cuda)[-_]", p)]


def test_model_pins_match_the_register():
    text = REGISTER.read_text()
    m = re.search(r"- name: faster-whisper-base\n((?:    .*\n)+)", text)
    assert m, "no faster-whisper-base block in licenses/register.yaml"
    block = m.group(1)
    assert re.search(rf"^\s+version: \"?{MODEL_REVISION}\"?$", block, re.M)
    assert re.search(rf"^\s+sha256: {MODEL_SHA256}$", block, re.M)
    assert f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/model.bin" in block
    assert re.search(r"^\s+images: \[stt\]$", block, re.M)
