"""The model sidecars (ml, stt) stay off host ports and on the internal
`models` network in both compose files, with their prod memory ceilings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE = {name: REPO / name for name in ("docker-compose.yml", "docker-compose.prod.yml")}
SIDECARS = ("ml", "stt")
# AD-7 values, the same spelling as .env.example (E0-Platform.7).
PROD_MEMORY = {"ml": "${ML_MEM_LIMIT:-2.5g}", "stt": "${STT_MEM_LIMIT:-1.25g}"}


def _load(name: str) -> dict:
    path = COMPOSE[name]
    if not path.exists():
        pytest.skip(f"{name} not in this checkout")
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("name", sorted(COMPOSE))
@pytest.mark.parametrize("sidecar", SIDECARS)
def test_sidecar_is_internal_only(name, sidecar):
    compose = _load(name)
    service = compose["services"][sidecar]
    assert "ports" not in service, f"{sidecar} publishes host ports in {name}"
    assert service["networks"] == ["models"], f"{sidecar} networks in {name}"
    assert compose["networks"]["models"]["internal"] is True


@pytest.mark.parametrize("sidecar", SIDECARS)
def test_prod_memory_ceiling(sidecar):
    service = _load("docker-compose.prod.yml")["services"][sidecar]
    assert service["deploy"]["resources"]["limits"]["memory"] == PROD_MEMORY[sidecar]


_GPU_DEVICE = [{"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}]


def test_gpu_override_only_adds_gpus_to_ollama_and_stt():
    """AD-7: docker-compose.gpu.yml reserves a GPU for ollama and stt, builds
    stt's local `gpu` target, and changes nothing else (no limits, no other
    service, no network)."""
    path = REPO / "docker-compose.gpu.yml"
    if not path.exists():
        pytest.skip("docker-compose.gpu.yml not in this checkout")
    gpu = yaml.safe_load(path.read_text())
    assert set(gpu) == {"services"}
    assert set(gpu["services"]) == {"ollama", "stt"}
    for name, service in gpu["services"].items():
        assert service["deploy"] == {"resources": {"reservations": {"devices": _GPU_DEVICE}}}, name
    stt = gpu["services"]["stt"]
    assert stt["build"]["target"] == "gpu"
    assert stt["build"]["context"] == _load("docker-compose.prod.yml")["services"]["stt"]["build"]["context"]
    assert stt["image"] != "lorekeeper-stt:latest"  # never overwrites the CPU image
    assert set(stt) <= {"image", "build", "environment", "deploy"}
    assert set(gpu["services"]["ollama"]) == {"deploy"}


def test_prod_web_service_and_host_gateway():
    """E0-Platform.7: the API runs as `web` (alias `backend`), and web and
    worker can reach an LLM on the Docker host."""
    services = _load("docker-compose.prod.yml")["services"]
    assert "backend" not in services
    web = services["web"]
    assert "gunicorn app.main:app -w 4 " in web["command"]
    assert web["networks"]["default"]["aliases"] == ["backend"]
    for name in ("web", "worker"):
        assert "host.docker.internal:host-gateway" in services[name]["extra_hosts"], name
    assert services["worker"]["depends_on"]["web"]["condition"] == "service_healthy"
    assert services["nginx"]["depends_on"]["web"]["condition"] == "service_healthy"
    ollama = services["ollama"]["environment"]
    assert ollama["OLLAMA_MAX_LOADED_MODELS"] == "1" and ollama["OLLAMA_KEEP_ALIVE"] == "30m"
    assert ollama["OLLAMA_NUM_PARALLEL"] == "1"  # fixed: .env's 0 ("auto") must not reach it
    assert ollama["OLLAMA_CONTEXT_LENGTH"] == "${OLLAMA_CONTEXT_LENGTH:-4096}"
    assert services["postgres"]["command"] == "postgres -c shared_buffers=192MB"
    assert "--maxmemory 96mb --maxmemory-policy noeviction" in services["valkey"]["command"]


# `docker compose -f docker-compose.prod.yml <subcommand> [flags] <service>` in
# the ops scripts. A network alias does not make a service name work here.
_PROD_CALL = re.compile(
    r"docker compose -f docker-compose\.prod\.yml (exec|run|start|stop|restart|logs|cp)\b((?:\s+-{1,2}[\w-]+(?:[ =]\d+)?)*)\s+([A-Za-z][\w-]*)((?:\s+[A-Za-z][\w-]*)*)")
_MULTI = {"start", "stop", "restart", "logs"}  # take several service names


def test_ops_scripts_name_real_prod_services():
    services = set(_load("docker-compose.prod.yml")["services"])
    calls = []
    for path in sorted((REPO / "scripts").glob("*.sh")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for m in _PROD_CALL.finditer(line):
                sub, first, rest = m.group(1), m.group(3), m.group(4).split()
                if sub == "cp":
                    continue  # `cp <src> <svc>:<path>`; checked below
                names = [first] + (rest if sub in _MULTI else [])
                calls += [(f"{path.name}:{n}", name) for name in names]
            for m in re.finditer(r"docker compose -f docker-compose\.prod\.yml cp\s+(\S+)\s+(\S+)", line):
                for arg in m.groups():
                    if ":" in arg:
                        calls.append((f"{path.name}:{n}", arg.split(":", 1)[0]))
    assert calls, "found no prod compose calls in scripts/*.sh: the pattern is stale"
    bad = [(where, name) for where, name in calls if name not in services]
    assert bad == [], f"scripts call prod services that don't exist: {bad}"
