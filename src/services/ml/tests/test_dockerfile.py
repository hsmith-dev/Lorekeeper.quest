"""Static guard on the ml Dockerfile (same rules as the backend's E0-Platform.2 test).

CPU-only torch from the PyTorch CPU index before requirements.txt, the CPU
extra index on the requirements install, the CUDA/NVIDIA guard after the last
pip install, offline env set, and the torch pin equal to requirements.txt's.
Runs without Docker.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


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


def _runs() -> list[list[str]]:
    return [t for op, t in _instructions() if op == "RUN"]


def _flag(tokens: list[str], flag: str) -> str | None:
    for i, tok in enumerate(tokens):
        if tok == flag and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _is_pip_install(t: list[str]) -> bool:
    return "pip" in t and "install" in t


def _is_guard(t: list[str]) -> bool:
    j = " ".join(t)
    return "torch.version.cuda" in j and "torch.cuda.is_available()" in j and "nvidia|cuda" in j


def test_cpu_torch_before_requirements_with_cpu_index():
    runs = _runs()
    torch_idx = next(i for i, t in enumerate(runs) if any(x.startswith("torch==") for x in t))
    req_idx = next(i for i, t in enumerate(runs) if "-r" in t and "requirements.txt" in t)
    assert torch_idx < req_idx
    assert _flag(runs[torch_idx], "--index-url") == CPU_INDEX
    pin = next(x for x in runs[torch_idx] if x.startswith("torch=="))
    assert pin.endswith("+cpu")
    assert _flag(runs[req_idx], "--extra-index-url") == CPU_INDEX


def test_guard_after_every_pip_install():
    runs = _runs()
    installs = [i for i, t in enumerate(runs) if _is_pip_install(t)]
    for i in installs:
        assert any(_is_guard(t) for t in runs[i + 1:]), f"no CUDA/NVIDIA guard after RUN #{i}"


def test_torch_pin_matches_requirements_lock():
    pin = next(x for t in _runs() for x in t if x.startswith("torch=="))
    lock = (ROOT / "requirements.txt").read_text()
    assert re.search(rf"^{re.escape(pin)}$", lock, re.M), f"{pin} not in requirements.txt"


def test_offline_env_after_bake():
    ins = _instructions()
    bake = max(i for i, (op, t) in enumerate(ins) if op == "RUN" and "bake_models.py" in t)
    env = " ".join(" ".join(t) for op, t in ins[bake:] if op == "ENV")
    assert "HF_HUB_OFFLINE=1" in env and "TRANSFORMERS_OFFLINE=1" in env
    assert any(op == "HEALTHCHECK" for op, _ in ins)
