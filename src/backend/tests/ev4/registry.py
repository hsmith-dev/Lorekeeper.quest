"""Probe registration, exemptions, the pending baseline and the coverage check.

    @ev4_probe("GET", "/api/npcs/{npc_id}")
    async def probe_npc_detail(ev4, actor): ...

The path is the route's template exactly as FastAPI registers it (prefix
included), the method is the HTTP method or ``WS``. tests/ev4/test_probes.py
runs every probe once per actor in ``actors``.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable

import yaml

from tests.ev4 import EV4_DIR
from tests.ev4.routes import WS, route_key

EXEMPTIONS_PATH = EV4_DIR / "exemptions.yaml"
PENDING_PATH = EV4_DIR / "pending_baseline.txt"
PROBES_PACKAGE = "tests.ev4.probes"

DEFAULT_ACTORS = ("anon_share", "player", "cross_gm_player")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", WS}


@dataclass(frozen=True)
class Probe:
    method: str
    path: str
    fn: Callable[..., Awaitable[None]] = field(compare=False)
    actors: tuple[str, ...] = DEFAULT_ACTORS

    @property
    def key(self) -> str:
        return route_key(self.method, self.path)

    @property
    def name(self) -> str:
        return f"{self.fn.__module__.rsplit('.', 1)[-1]}.{self.fn.__name__}"


_PROBES: list[Probe] = []


def ev4_probe(method: str, path: str, actors: Iterable[str] = DEFAULT_ACTORS):
    method = method.upper()
    if method not in _METHODS:
        raise ValueError(f"ev4_probe: unknown method {method!r} (use one of {sorted(_METHODS)})")
    if not path.startswith("/"):
        raise ValueError(f"ev4_probe: path must be the full route template, got {path!r}")
    actors = tuple(actors)
    if not actors:
        raise ValueError(f"ev4_probe({method} {path}): needs at least one actor")

    def register(fn):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"ev4_probe({method} {path}): {fn.__qualname__} must be `async def probe(ev4, actor)`")
        _PROBES.append(Probe(method, path, fn, actors))
        return fn

    return register


def load_probes(package: str = PROBES_PACKAGE) -> list[Probe]:
    """Import every module of tests/ev4/probes/ and return the registered probes."""
    pkg = importlib.import_module(package)
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        importlib.import_module(f"{package}.{info.name}")
    return list(_PROBES)


@dataclass(frozen=True)
class Exemption:
    route: str
    reason: str


def load_exemptions(path: Path = EXEMPTIONS_PATH) -> list[Exemption]:
    data = yaml.safe_load(path.read_text())
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a YAML list of {{route, reason}} entries")
    out: list[Exemption] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict) or set(item) - {"route", "reason"} or "route" not in item:
            raise ValueError(f"{path}: entry {i} must be a mapping with `route` and `reason`, got {item!r}")
        route = " ".join(str(item["route"]).split())
        reason = item.get("reason")
        out.append(Exemption(route, "" if reason is None else str(reason).strip()))
    return out


def load_pending(path: Path = PENDING_PATH) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(" ".join(line.split()))
    return lines


def check_coverage(
    routes: Iterable[str],
    probes: Iterable[str],
    exemptions: Iterable[Exemption],
    pending: Iterable[str],
    frozen_pending: Iterable[str],
) -> list[str]:
    """Every problem with EV-4 coverage, as messages (empty: covered).

    ``routes``/``probes``/``pending`` are ``"METHOD PATH"`` keys.
    """
    routes = set(routes)
    probes = list(probes)
    exemptions = list(exemptions)
    pending = list(pending)
    frozen = set(frozen_pending)
    probed = set(probes)
    exempt = {e.route for e in exemptions}
    errors: list[str] = []

    for key in sorted(set(probes) - routes):
        errors.append(f"stale probe: {key} has an @ev4_probe but no such route exists; fix or delete the probe")

    seen: set[str] = set()
    for e in exemptions:
        if e.route in seen:
            errors.append(f"duplicate exemption: {e.route} is listed twice in exemptions.yaml")
        seen.add(e.route)
        if not e.reason:
            errors.append(f"exemption without a reason: {e.route} in exemptions.yaml needs a non-empty `reason`")
        if e.route not in routes:
            errors.append(f"stale exemption: {e.route} is not a route; remove it from exemptions.yaml")
        elif e.route in probed:
            errors.append(f"{e.route} is both probed and exempted; remove the exemption from exemptions.yaml")

    seen = set()
    for line in pending:
        if line in seen:
            errors.append(f"duplicate pending line: {line} is in pending_baseline.txt twice")
        seen.add(line)
        if line not in frozen:
            errors.append(
                f"pending_baseline.txt only shrinks: {line} was added. Write a probe in "
                "tests/ev4/probes/<feature>.py or a reasoned exemption in exemptions.yaml instead"
            )
        if line not in routes:
            errors.append(f"stale pending line: {line} is no longer a route; remove it from pending_baseline.txt")
        elif line in probed or line in exempt:
            errors.append(
                f"stale pending line: {line} is now {'probed' if line in probed else 'exempted'}; "
                "remove it from pending_baseline.txt"
            )

    for key in sorted(routes - probed - exempt - set(pending)):
        errors.append(
            f"uncovered route: {key} has no EV-4 probe or exemption. Add a probe "
            "(@ev4_probe in tests/ev4/probes/<feature>.py) or an exemption with a reason "
            "in tests/ev4/exemptions.yaml"
        )
    return errors
