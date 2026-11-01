"""Static guard: the backend images install CPU-only torch (E0-Platform.2).

A plain ``pip install -r requirements.txt`` on x86-64 resolves CUDA torch from
PyPI and drags ~15 NVIDIA-proprietary wheels into the image. Both Dockerfiles
must install pinned ``+cpu`` torch/torchvision from the PyTorch CPU index
before requirements.txt, and install requirements.txt with the same CPU extra
index CI's licence job uses. Runs without Docker.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
# src/backend may be mounted alone (e.g. at /app), with no repo root above it.
REGISTER = (
    BACKEND.parents[1] / "licenses" / "register.yaml"
    if len(BACKEND.parents) > 1
    else BACKEND / "__no_repo_root__" / "register.yaml"
)
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
DOCKERFILES = ["Dockerfile", "Dockerfile.prod"]


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


def _index_url(tokens: list[str], flag: str) -> str | None:
    for i, tok in enumerate(tokens):
        if tok == flag and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


def _pins(tokens: list[str]) -> dict[str, str]:
    pins = {}
    for tok in tokens:
        m = re.fullmatch(r"(torch|torchvision)==(\S+)", tok)
        if m:
            pins[m.group(1)] = m.group(2)
    return pins


def _is_pip_install(tokens: list[str]) -> bool:
    return "pip" in tokens and "install" in tokens


def _analyse(name: str):
    runs = [t for t in _run_instructions(BACKEND / name) if _is_pip_install(t)]
    torch_idx = next((i for i, t in enumerate(runs) if "torch" in _pins(t)), None)
    req_idx = next(
        (i for i, t in enumerate(runs) if "-r" in t and "requirements.txt" in t),
        None,
    )
    return runs, torch_idx, req_idx


@pytest.mark.parametrize("name", DOCKERFILES)
def test_cpu_torch_installed_before_requirements(name):
    runs, torch_idx, req_idx = _analyse(name)
    assert torch_idx is not None, f"{name}: no pinned torch install"
    assert req_idx is not None, f"{name}: no -r requirements.txt install"
    assert torch_idx < req_idx, f"{name}: torch must be installed before requirements.txt"

    torch_run = runs[torch_idx]
    assert _index_url(torch_run, "--index-url") == CPU_INDEX, (
        f"{name}: torch must come from {CPU_INDEX} via --index-url"
    )
    pins = _pins(torch_run)
    for pkg in ("torch", "torchvision"):
        assert pkg in pins, f"{name}: {pkg} not pinned in the torch layer"
        assert pins[pkg].endswith("+cpu"), f"{name}: {pkg}=={pins[pkg]} is not a +cpu build"


@pytest.mark.parametrize("name", DOCKERFILES)
def test_requirements_install_uses_cpu_extra_index(name):
    runs, _, req_idx = _analyse(name)
    assert req_idx is not None, f"{name}: no -r requirements.txt install"
    assert _index_url(runs[req_idx], "--extra-index-url") == CPU_INDEX, (
        f"{name}: requirements install must carry --extra-index-url {CPU_INDEX}"
    )


@pytest.mark.parametrize("name", DOCKERFILES)
def test_cuda_guard_runs_after_installs(name):
    runs = _run_instructions(BACKEND / name)
    joined = [" ".join(t) for t in runs]

    def last(pred):
        return max((i for i, j in enumerate(joined) if pred(j)), default=None)

    req = last(lambda j: "pip install" in j and "-r requirements.txt" in j)
    spacy = last(lambda j: "spacy download" in j)
    guard = last(
        lambda j: "torch.version.cuda" in j
        and "torch.cuda.is_available()" in j
        and "pip list" in j
        and "nvidia|cuda" in j
    )
    assert guard is not None, f"{name}: no CUDA/NVIDIA guard RUN"
    assert req is not None and spacy is not None, f"{name}: missing install steps"
    assert guard > max(req, spacy), (
        f"{name}: the CUDA/NVIDIA guard must run after the requirements and spaCy installs"
    )


def _register_version(pkg: str, text: str) -> str:
    m = re.search(
        r'name:\s*"?' + re.escape(pkg) + r'"?\s*,\s*kind:\s*python\s*,\s*version:\s*"([^"]+)"',
        text,
    )
    assert m, f"{pkg} not found in {REGISTER}"
    return m.group(1)


@pytest.mark.skipif(not REGISTER.exists(), reason="licenses/register.yaml not reachable")
@pytest.mark.parametrize("name", DOCKERFILES)
def test_pins_match_licence_register(name):
    runs, torch_idx, _ = _analyse(name)
    assert torch_idx is not None, f"{name}: no pinned torch install"
    pins = _pins(runs[torch_idx])
    text = REGISTER.read_text()
    for pkg in ("torch", "torchvision"):
        registered = [v.strip() for v in _register_version(pkg, text).split(",")]
        assert pins.get(pkg) in registered, (
            f"{name}: {pkg}=={pins.get(pkg)} not in register versions {registered}"
        )
