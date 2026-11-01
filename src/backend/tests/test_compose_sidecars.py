"""The model sidecars (ml, stt) stay off host ports and on the internal
`models` network in both compose files, with their prod memory ceilings."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE = {name: REPO / name for name in ("docker-compose.yml", "docker-compose.prod.yml")}
SIDECARS = ("ml", "stt")
PROD_MEMORY = {"ml": "${ML_MEM_LIMIT:-2560m}", "stt": "${STT_MEM_LIMIT:-1280m}"}


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
