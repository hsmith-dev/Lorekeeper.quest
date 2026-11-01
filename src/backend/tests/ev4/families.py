"""The seven EV-4 probe families (AD-21).

  assert_no_canary                    canary content in a body or header
  assert_hidden_equals_missing        hidden vs nonexistent
  assert_hidden_field_equals_unset    hidden field vs unset field
  assert_counts_and_ranking_unchanged counts and ranking
  assert_captured_context_clean       captured LLM context
  assert_audience_ladder              Public vs Members vs Owner(other)
  downgrade_suite(type_name)          its DERIVED_REGISTRY downgrade cases

Every failure goes through report.record_leak: it raises EV4Leak (an
AssertionError) and counts the leak. Probe misuse that would make a check
pass vacuously (an error response where content was expected, nothing to
compare) raises ValueError instead. Every helper calls
report.note_family_call(), so the runner can fail a probe that checks nothing.
"""
from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

import httpx
import pytest

from tests.ev4.fixtures import CANARIES, Actor, find_canaries
from tests.ev4.report import note_family_call, record_leak

# Headers that differ between any two responses; never compared.
VOLATILE_HEADERS = frozenset({"date", "x-response-time", "server"})
_MISSING = object()


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _describe(response: Any) -> str:
    if isinstance(response, httpx.Response):
        try:
            return f"{response.request.method} {response.request.url}"
        except RuntimeError:
            return "response"
    return type(response).__name__


def _texts(response: Any) -> list[tuple[str, str]]:
    """(where, text) pairs to scan: the body, then every header."""
    if isinstance(response, httpx.Response):
        out = [("body", response.text)]
        out += [(f"header {k}", f"{k}: {v}") for k, v in response.headers.multi_items()]
        return out
    if isinstance(response, bytes):
        return [("body", response.decode("utf-8", "replace"))]
    if isinstance(response, str):
        return [("body", response)]
    return [("body", json.dumps(response, default=str))]


def canary_hits(actor: Actor, response: Any) -> list[str]:
    """Each canary token in ``response`` that ``actor`` may not see."""
    hits: list[str] = []
    for where, text in _texts(response):
        for token in find_canaries(text):
            if not actor.may_see(token):
                canary = CANARIES.get(token)
                owner = f"campaign {canary.campaign_id}, kind {canary.kind}" if canary else "unknown campaign"
                hits.append(f"{where}: {token} ({owner})")
    return hits


def assert_no_canary(actor: Actor, response: Any, *, label: str | None = None) -> None:
    """No canary in the body text or any header that ``actor`` may not see."""
    note_family_call()
    hits = canary_hits(actor, response)
    if hits:
        record_leak(f"EV-4 leak: {actor.name} saw {len(hits)} canary token(s) in {label or _describe(response)}",
                    hits, count=len(hits))


def _headers(response: httpx.Response, skip: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
    return sorted((k.lower(), v) for k, v in response.headers.multi_items()
                  if k.lower() not in VOLATILE_HEADERS and k.lower() not in skip)


def _require_ok(response: httpx.Response, url: str, what: str) -> None:
    """ValueError (probe misuse, not a leak) when ``response`` is an error:
    a check on an error body would pass without comparing anything."""
    if response.status_code >= 400:
        raise ValueError(f"{what}: GET {url} returned {response.status_code}; the check needs a successful "
                         "response to compare (fix the probe's URL or actor)")


async def assert_hidden_equals_missing(actor: Actor, hidden_url: str, missing_url: str, *, method: str = "GET",
                                       **kwargs) -> None:
    """A hidden record answers exactly like one that does not exist: same
    status, same body bytes, same headers (bar date/x-response-time/server)."""
    note_family_call()
    hidden = await actor.request(method, hidden_url, **kwargs)
    missing = await actor.request(method, missing_url, **kwargs)
    assert_no_canary(actor, hidden)
    assert_no_canary(actor, missing)
    diffs: list[str] = []
    if hidden.status_code != missing.status_code:
        diffs.append(f"status: hidden {hidden.status_code} vs missing {missing.status_code}")
    if hidden.content != missing.content:
        diffs.append(f"body: hidden {hidden.text[:200]!r} vs missing {missing.text[:200]!r}")
    hh, mh = _headers(hidden), _headers(missing)
    if hh != mh:
        diffs.append(f"headers: hidden-only {sorted(set(hh) - set(mh))} missing-only {sorted(set(mh) - set(hh))}")
    if diffs:
        record_leak(f"EV-4 leak: {actor.name} can tell hidden {method} {hidden_url} from missing {missing_url}",
                    diffs)


def _field_states(body: Any, path: list[str]) -> list[tuple[bool, Any]]:
    """(present, value) for the dotted ``path`` in ``body``; lists fan out."""
    if isinstance(body, list):
        return [s for item in body for s in _field_states(item, path)]
    if not path:
        return [(True, body)]
    if not isinstance(body, dict):
        return [(False, None)]
    if path[0] not in body:
        return [(False, None)]
    return _field_states(body[path[0]], path[1:])


async def assert_hidden_field_equals_unset(actor: Actor, url: str, field: str, unset: Any = None,
                                           unset_url: str | None = None) -> None:
    """The dotted ``field`` (in the object, or in every list item) is absent
    or equals ``unset``. With ``unset_url`` (a record whose field really is
    unset), presence and value must match that control instead."""
    note_family_call()
    response = await actor.get(url)
    assert_no_canary(actor, response)
    _require_ok(response, url, "assert_hidden_field_equals_unset")
    states = _field_states(response.json(), field.split("."))
    if not states:
        raise ValueError(f"assert_hidden_field_equals_unset: GET {url} ({response.status_code}) has no object "
                         f"or list item to check {field!r} in")
    if unset_url is None:
        bad = [v for present, v in states if present and v != unset]
        if bad:
            record_leak(f"EV-4 leak: {actor.name} sees hidden field {field!r} at {url} (expected absent or "
                        f"{unset!r})", [repr(v)[:200] for v in bad])
        return
    control = await actor.get(unset_url)
    assert_no_canary(actor, control)
    _require_ok(control, unset_url, "assert_hidden_field_equals_unset (unset control)")
    expected = set(map(_freeze, _field_states(control.json(), field.split("."))))
    if len(expected) != 1:
        raise ValueError(f"unset control {unset_url} gives {len(expected)} different states for {field!r}; "
                         "use a control whose field is unset everywhere")
    (want,) = expected
    bad = [s for s in map(_freeze, states) if s != want]
    if bad:
        record_leak(f"EV-4 leak: hidden field {field!r} at {url} does not render like the unset control "
                    f"{unset_url} for {actor.name}", [f"got {b!r}, control {want!r}" for b in bad])


def _freeze(state: tuple[bool, Any]) -> tuple[bool, str]:
    return state[0], json.dumps(state[1], sort_keys=True, default=str)


def _strip(value: Any, ignore: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v, ignore) for k, v in value.items() if k not in ignore}
    if isinstance(value, list):
        return [_strip(v, ignore) for v in value]
    return value


async def _snapshot(actor: Actor, url: str, ignore: frozenset[str]):
    r = await actor.get(url)
    assert_no_canary(actor, r)
    try:
        body = _strip(r.json(), ignore)
    except ValueError:
        body = r.text
    return r.status_code, body, _headers(r, skip=frozenset({"content-length"}))


async def assert_counts_and_ranking_unchanged(actor: Actor, urls: str | Iterable[str],
                                              mutate_gm_only: Callable[[], Awaitable[Any] | Any],
                                              ignore: Iterable[str] = ("updated_at",)) -> None:
    """A GM-only change moves nothing ``actor`` can see: each URL's status,
    full JSON body (minus ``ignore`` keys, at any depth) and non-volatile
    headers (bar content-length) are identical before and after
    ``await mutate_gm_only()``."""
    note_family_call()
    urls = [urls] if isinstance(urls, str) else list(urls)
    ignore = frozenset(ignore)
    before = [await _snapshot(actor, u, ignore) for u in urls]
    for u, (status, _, _) in zip(urls, before):
        if status >= 400:
            raise ValueError(f"assert_counts_and_ranking_unchanged: GET {u} returned {status} before the "
                             "mutation; the check needs a successful response to compare")
    await _maybe_await(mutate_gm_only())
    after = [await _snapshot(actor, u, ignore) for u in urls]
    diffs = [f"{u}: before {b!r:.200} after {a!r:.200}" for u, b, a in zip(urls, before, after) if b != a]
    if diffs:
        record_leak(f"EV-4 leak: a GM-only change is visible to {actor.name} through counts or ranking", diffs)


def _captured_text(captured: Any) -> str:
    for attr in ("calls", "messages", "records"):
        if hasattr(captured, attr) and not callable(getattr(captured, attr)):
            captured = getattr(captured, attr)
            break
    try:
        return json.dumps(captured, default=lambda o: getattr(o, "__dict__", repr(o)))
    except (TypeError, ValueError):
        return repr(captured)


async def assert_captured_context_clean(actor: Actor, run: Callable[[], Awaitable[Any] | Any], *,
                                        label: str | None = None) -> Any:
    """Every prompt sent to the LLM while ``run()`` executes on ``actor``'s
    behalf holds no canary ``actor`` may not see. Needs llm_provider.capture()
    (E0-LLM.5); skips until it exists. Returns run()'s result."""
    note_family_call()
    from app.services import llm_provider

    capture = getattr(llm_provider, "capture", None)
    if capture is None:
        pytest.skip("llm_provider.capture() not available yet (E0-LLM.5)")
    cm = capture()
    if hasattr(cm, "__aenter__"):
        async with cm as captured:
            result = await _maybe_await(run())
    else:
        with cm as captured:
            result = await _maybe_await(run())
    if captured is None:
        raise TypeError("capture() yielded nothing to scan")
    hits = canary_hits(actor, _captured_text(captured))
    if hits:
        record_leak(f"EV-4 leak: the LLM context built for {actor.name} in {label or 'run()'} holds "
                    f"{len(hits)} canary token(s)", hits, count=len(hits))
    return result


def _item_ids(response: httpx.Response, id_key: str) -> set[str]:
    body = response.json()
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        body = body["items"]
    items = body if isinstance(body, list) else [body]
    return {str(i[id_key]) for i in items if isinstance(i, dict) and id_key in i}


async def assert_audience_ladder(ev4, url: str | Callable[[Actor], str], *, id_key: str = "id") -> None:
    """As anon_share (Public), player and a second player (Members, each
    Owner(other) to the other) and gm_owner (GM): no actor sees an
    unpermitted canary, the Public item ids are a subset of each Member's,
    and each Member's are a subset of the GM's. ``url`` may be a callable
    taking the actor (share and member routes differ). Every response must
    succeed (an error response would make the ladder vacuous)."""
    note_family_call()
    public = await ev4.actor("anon_share")
    members = [await ev4.actor("player"), await ev4.actor("player_2")]
    gm = await ev4.actor("gm_owner")
    ids: dict[str, set[str]] = {}
    for actor in [public, *members, gm]:
        u = url(actor) if callable(url) else url
        r = await actor.get(u)
        assert_no_canary(actor, r)
        _require_ok(r, u, f"assert_audience_ladder as {actor.name}")
        ids[actor.name] = _item_ids(r, id_key)
    diffs = [f"{m.name} lacks Public ids {sorted(ids[public.name] - ids[m.name])}"
             for m in members if not ids[public.name] <= ids[m.name]]
    diffs += [f"{m.name} sees ids the GM does not: {sorted(ids[m.name] - ids[gm.name])}"
              for m in members if not ids[m.name] <= ids[gm.name]]
    if diffs:
        record_leak("EV-4 leak: the audience ladder is broken (Public must be a subset of Members, "
                    "Members of GM)", diffs)


@dataclass(frozen=True)
class DowngradeCase:
    derived_type: str
    derive_from: tuple[str, ...]

    async def check(self, actor: Actor, derived_url: str, missing_url: str,
                    downgrade: Callable[[], Awaitable[Any] | Any]) -> None:
        """After ``downgrade()`` hides a source, the derived record must answer
        ``actor`` exactly like a missing one. The derived record must be
        visible to ``actor`` before the downgrade, or the check is vacuous."""
        note_family_call()
        before = await actor.get(derived_url)
        _require_ok(before, derived_url, f"DowngradeCase({self.derived_type}).check before the downgrade")
        await _maybe_await(downgrade())
        await assert_hidden_equals_missing(actor, derived_url, missing_url)


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _spec_field(spec: Any, name: str) -> Any:
    """A required field of a DERIVED_REGISTRY entry (dict key or attribute)."""
    value = spec.get(name, _MISSING) if isinstance(spec, dict) else getattr(spec, name, _MISSING)
    if value is _MISSING:
        raise ValueError(f"DERIVED_REGISTRY entry {spec!r} has no {name!r}")
    return value


def downgrade_suite(type_name: str | None = None) -> list[DowngradeCase]:
    """The DowngradeCases for ``type_name`` (every type when None), driven by
    app.access.registry.DERIVED_REGISTRY. Empty until E0-Access/E0-Jobs add
    the registry, or when ``type_name`` is not registered."""
    try:
        registry = importlib.import_module("app.access.registry")
    except ModuleNotFoundError as exc:
        if exc.name in ("app.access", "app.access.registry"):
            return []
        raise
    if not hasattr(registry, "DERIVED_REGISTRY"):
        raise ValueError("app.access.registry exists but defines no DERIVED_REGISTRY")
    derived_registry = registry.DERIVED_REGISTRY
    cases: list[DowngradeCase] = []
    if hasattr(derived_registry, "items"):
        for derived_type, spec in derived_registry.items():
            # A bare str/list/tuple value is the derive_from list itself; a
            # mapping or object entry must name its derive_from.
            sources = spec if isinstance(spec, (str, list, tuple)) else _spec_field(spec, "derive_from")
            cases.append(DowngradeCase(str(derived_type), _as_tuple(sources)))
    else:
        for spec in derived_registry:
            if isinstance(spec, tuple) and len(spec) == 2:
                cases.append(DowngradeCase(str(spec[0]), _as_tuple(spec[1])))
            else:
                cases.append(DowngradeCase(str(_spec_field(spec, "derived_type")),
                                           _as_tuple(_spec_field(spec, "derive_from"))))
    if type_name is not None:
        cases = [c for c in cases if c.derived_type == type_name]
    return sorted(cases, key=lambda c: c.derived_type)
