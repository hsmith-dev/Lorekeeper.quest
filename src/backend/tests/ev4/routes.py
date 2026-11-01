"""The API surface EV-4 must cover: every ``app.routes`` entry, and where
nginx sends each one.

``api_routes(app)`` lists one ApiRoute per (method, path) of every
``APIRoute`` and one ``WS`` entry per ``APIWebSocketRoute``. FastAPI's docs
routes are the only other route kind allowed; anything else (a Mount, a bare
starlette Route) raises, because EV-4 could not probe it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from fastapi.routing import APIRoute, APIWebSocketRoute
from starlette.routing import Route

from tests.ev4 import nginx

WS = "WS"

# FastAPI's own docs routes (starlette Routes, not APIRoutes). Not app content.
DOCS_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})

# A UUID-shaped sample: matches `{x}` path params, uuid converters and the
# `[0-9a-f-]{36}` id pattern AD-20 regex locations use.
SAMPLE_ID = "00000000-0000-4000-8000-000000000000"
_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_]+))?\}")
_SAMPLES = {None: SAMPLE_ID, "str": SAMPLE_ID, "uuid": SAMPLE_ID, "int": "1", "float": "1.0",
            "path": f"{SAMPLE_ID}/{SAMPLE_ID}"}


class UnknownRouteKind(Exception):
    """app.routes holds a route kind EV-4 cannot enumerate."""


@dataclass(frozen=True)
class ApiRoute:
    method: str
    path: str
    path_regex: re.Pattern = field(compare=False, hash=False, repr=False)

    @property
    def key(self) -> str:
        return route_key(self.method, self.path)

    def __str__(self) -> str:
        return self.key


def route_key(method: str, path: str) -> str:
    return f"{method.upper()} {path}"


def api_routes(app) -> list[ApiRoute]:
    out: list[ApiRoute] = []
    for r in app.routes:
        if isinstance(r, APIRoute):
            for method in sorted(r.methods or ()):
                out.append(ApiRoute(method.upper(), r.path, r.path_regex))
        elif isinstance(r, APIWebSocketRoute):
            out.append(ApiRoute(WS, r.path, r.path_regex))
        elif type(r) is Route and r.path in DOCS_PATHS:
            continue
        else:
            raise UnknownRouteKind(
                f"EV-4 cannot enumerate {type(r).__module__}.{type(r).__name__} "
                f"{getattr(r, 'path', '?')!r}: register routes as FastAPI APIRoute or "
                "APIWebSocketRoute (or teach tests/ev4/routes.py about the new kind)."
            )
    return out


def sample_path(path: str) -> str:
    """A concrete request path for a route template (``{x}`` -> a UUID)."""
    def sub(m: re.Match) -> str:
        conv = m.group(2)
        if conv not in _SAMPLES:
            raise ValueError(f"no sample for path converter {conv!r} in {path!r}")
        return _SAMPLES[conv]
    return _PARAM_RE.sub(sub, path)


def nginx_locations() -> nginx.Location:
    """The 443 server's location tree from the repo's nginx config."""
    return nginx.https_locations()


def resolve_route(route: ApiRoute | str) -> nginx.Location | None:
    """The nginx location a request for ``route`` lands in."""
    path = route.path if isinstance(route, ApiRoute) else route
    return nginx_locations().resolve(sample_path(path))


def is_api_location(loc: nginx.Location | None) -> bool:
    """True for a location that proxies the API (``/api…``), never the
    static ``/`` location or its nested asset regex."""
    if loc is None:
        return False
    if loc.modifier in (nginx.REGEX, nginx.REGEX_CI):
        return loc.uri.startswith("^/api")
    return loc.uri.startswith("/api")
