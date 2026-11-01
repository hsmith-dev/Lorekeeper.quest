"""Self-tests for the EV-4 probe families on a toy app: each family passes
on a clean response (positive control) and raises EV4Leak, counting one
leak, on a planted one. Planted leaks run inside report.scoped(), so they
never reach the session's leak count. No database."""
from __future__ import annotations

import sys
import types
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from tests.ev4 import report
from tests.ev4.families import (
    DowngradeCase, assert_audience_ladder, assert_captured_context_clean, assert_counts_and_ranking_unchanged,
    assert_hidden_equals_missing, assert_hidden_field_equals_unset, assert_no_canary, downgrade_suite,
)
from tests.ev4.fixtures import GM, PLAYER, Actor, mint_canary
from tests.ev4.registry import Probe
from tests.ev4.report import EV4Leak
from tests.ev4.test_probes import run_probe

CAMPAIGN = uuid.uuid4()
OTHER_CAMPAIGN = uuid.uuid4()


def _toy_app(state: dict) -> FastAPI:
    app = FastAPI()

    @app.get("/clean")
    async def clean():
        return {"items": [{"id": "1", "name": "Barnaby"}]}

    @app.get("/leak-body")
    async def leak_body():
        return {"id": "1", "notes": f"secret {state['token']}"}

    @app.get("/leak-header")
    async def leak_header():
        return JSONResponse({"id": "1"}, headers={"X-Debug": state["token"]})

    @app.get("/thing/{thing_id}")
    async def thing(thing_id: str):
        if thing_id == "visible" and not state.get("downgraded"):
            return {"id": thing_id}
        if thing_id == "hidden-leaky":
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        if thing_id == "hidden-header":
            return JSONResponse({"detail": "Not found"}, status_code=404, headers={"X-Exists": "1"})
        if thing_id == "hidden-body":
            return JSONResponse({"detail": "Not Found"}, status_code=404)  # same length: same headers
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.get("/npc/{variant}")
    async def npc(variant: str):
        status = {"hidden-clean": "unknown", "hidden-leak": "alive", "unset": "unknown"}[variant]
        return {"id": variant, "status": status, "nested": {"secret": None}}

    @app.get("/npcs")
    async def npcs():
        return [{"id": "1", "status": "unknown"}, {"id": "2", "status": state.get("second", "unknown")}]

    @app.get("/list")
    async def listing():
        return {"items": state["items"], "total": len(state["items"])}

    @app.get("/counted")
    async def counted():
        return JSONResponse([{"id": "1"}], headers={"X-Total-Count": str(state["total"])})

    @app.get("/empty")
    async def empty():
        return []

    @app.get("/gm")
    async def gm_view():
        return [{"id": i} for i in state["gm"]]

    @app.get("/public")
    async def public():
        return [{"id": i} for i in state["public"]]

    @app.get("/members")
    async def members():
        return [{"id": i} for i in state["members"]]

    return app


class ToyEV4:
    def __init__(self, actors: dict[str, Actor]):
        self._actors = actors

    async def actor(self, name: str) -> Actor:
        return self._actors[name]


@pytest_asyncio.fixture
async def toy():
    canary = mint_canary("TOYNOTES", CAMPAIGN)
    state = {"token": canary.token, "items": [{"id": "1", "updated_at": "t0"}], "public": ["1"], "members": ["1", "2"],
             "gm": ["1", "2", "9"], "total": 1}
    async with AsyncClient(transport=ASGITransport(app=_toy_app(state)), base_url="http://toy") as client:
        actors = {
            "gm": Actor("gm", client, grants={CAMPAIGN: GM}),
            "gm_owner": Actor("gm_owner", client, grants={CAMPAIGN: GM}),
            "anon_share": Actor("anon_share", client, share_token="t", grants={CAMPAIGN: "anon"}),
            "player": Actor("player", client, grants={CAMPAIGN: PLAYER}),
            "player_2": Actor("player_2", client, grants={CAMPAIGN: PLAYER}),
            "other_gm": Actor("other_gm", client, grants={OTHER_CAMPAIGN: GM, CAMPAIGN: PLAYER}),
        }
        yield types.SimpleNamespace(state=state, canary=canary, client=client, actors=actors, ev4=ToyEV4(actors))


class planted:
    """Expect exactly one EV4Leak, counted in a scoped report."""

    def __enter__(self):
        self.session_before = report.leak_count()
        self._scope = report.scoped()
        self.report = self._scope.__enter__()
        self._raises = pytest.raises(EV4Leak)
        self.excinfo = self._raises.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            suppressed = self._raises.__exit__(*exc)
        finally:
            self._scope.__exit__(None, None, None)
        assert self.report.leaks == 1
        assert report.leak_count() == self.session_before, "a planted leak reached the session count"
        return suppressed


# ── canary content ─────────────────────────────────────────────────────────

async def test_no_canary_passes_on_clean_response(toy):
    assert_no_canary(toy.actors["player"], await toy.client.get("/clean"))


async def test_no_canary_lets_a_gm_see_own_campaign(toy):
    assert_no_canary(toy.actors["gm"], await toy.client.get("/leak-body"))


async def test_no_canary_catches_body_leak(toy):
    r = await toy.client.get("/leak-body")
    with planted() as p:
        assert_no_canary(toy.actors["player"], r)
    assert toy.canary.token in str(p.excinfo.value)
    assert "body" in str(p.excinfo.value)


async def test_no_canary_catches_header_leak(toy):
    r = await toy.client.get("/leak-header")
    with planted() as p:
        assert_no_canary(toy.actors["anon_share"], r)
    assert "header x-debug" in str(p.excinfo.value)


async def test_no_canary_gm_of_another_campaign_is_not_gm_here(toy):
    with planted():
        assert_no_canary(toy.actors["other_gm"], await toy.client.get("/leak-body"))


async def test_no_canary_unknown_and_recased_tokens_count(toy):
    stray = f"CANARY-STRAY-{uuid.uuid4()}"
    with planted():
        assert_no_canary(toy.actors["gm"], {"x": stray})
    with planted():
        assert_no_canary(toy.actors["player"], toy.canary.token.lower())


def test_leak_is_an_assertion_error():
    assert issubclass(EV4Leak, AssertionError)


# ── hidden vs nonexistent ──────────────────────────────────────────────────

async def test_hidden_equals_missing_passes(toy):
    await assert_hidden_equals_missing(toy.actors["player"], "/thing/hidden", "/thing/missing")


async def test_hidden_equals_missing_catches_status(toy):
    with planted() as p:
        await assert_hidden_equals_missing(toy.actors["player"], "/thing/hidden-leaky", "/thing/missing")
    assert "status" in str(p.excinfo.value)


async def test_hidden_equals_missing_catches_header(toy):
    with planted() as p:
        await assert_hidden_equals_missing(toy.actors["player"], "/thing/hidden-header", "/thing/missing")
    assert "x-exists" in str(p.excinfo.value)


async def test_hidden_equals_missing_catches_body(toy):
    with planted() as p:
        await assert_hidden_equals_missing(toy.actors["player"], "/thing/hidden-body", "/thing/missing")
    assert "body" in str(p.excinfo.value)
    assert "status:" not in str(p.excinfo.value) and "headers:" not in str(p.excinfo.value)


# ── hidden field vs unset field ────────────────────────────────────────────

async def test_hidden_field_passes(toy):
    player = toy.actors["player"]
    await assert_hidden_field_equals_unset(player, "/npc/hidden-clean", "status", unset="unknown")
    await assert_hidden_field_equals_unset(player, "/npc/hidden-clean", "status", unset_url="/npc/unset")
    await assert_hidden_field_equals_unset(player, "/npc/hidden-clean", "nested.secret")
    await assert_hidden_field_equals_unset(player, "/npc/hidden-clean", "absent.field")
    await assert_hidden_field_equals_unset(player, "/npcs", "status", unset="unknown")


async def test_hidden_field_catches_value(toy):
    with planted():
        await assert_hidden_field_equals_unset(toy.actors["player"], "/npc/hidden-leak", "status", unset="unknown")
    with planted():
        await assert_hidden_field_equals_unset(toy.actors["player"], "/npc/hidden-leak", "status",
                                               unset_url="/npc/unset")


async def test_hidden_field_checks_every_list_item(toy):
    toy.state["second"] = "dead"
    with planted():
        await assert_hidden_field_equals_unset(toy.actors["player"], "/npcs", "status", unset="unknown")


async def test_hidden_field_refuses_error_response(toy):
    with pytest.raises(ValueError, match=r"/thing/missing returned 404"):
        await assert_hidden_field_equals_unset(toy.actors["player"], "/thing/missing", "status")


async def test_hidden_field_refuses_nothing_to_check(toy):
    with pytest.raises(ValueError, match=r"/empty .*no object"):
        await assert_hidden_field_equals_unset(toy.actors["player"], "/empty", "status")


# ── counts and ranking ─────────────────────────────────────────────────────

async def test_counts_unchanged_passes_ignoring_updated_at(toy):
    async def touch():
        toy.state["items"][0]["updated_at"] = "t1"
    await assert_counts_and_ranking_unchanged(toy.actors["player"], ["/list", "/clean"], touch)


async def test_counts_catches_a_gm_only_row(toy):
    def add_hidden():
        toy.state["items"].append({"id": "gm-only"})
    with planted() as p:
        await assert_counts_and_ranking_unchanged(toy.actors["player"], "/list", add_hidden)
    assert "/list" in str(p.excinfo.value)


async def test_counts_catches_reordering(toy):
    toy.state["items"] = [{"id": "1"}, {"id": "2"}]

    async def reorder():
        toy.state["items"].reverse()
    with planted():
        await assert_counts_and_ranking_unchanged(toy.actors["player"], "/list", reorder)


async def test_counts_catches_a_header_change(toy):
    def add_hidden():
        toy.state["total"] = 2
    with planted() as p:
        await assert_counts_and_ranking_unchanged(toy.actors["player"], "/counted", add_hidden)
    assert "x-total-count" in str(p.excinfo.value)


async def test_counts_refuses_error_before_snapshot(toy):
    with pytest.raises(ValueError, match=r"/thing/missing returned 404"):
        await assert_counts_and_ranking_unchanged(toy.actors["player"], "/thing/missing", lambda: None)


# ── captured LLM context ───────────────────────────────────────────────────

class _FakeCapture:
    def __init__(self, sink: list):
        self.calls = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


async def test_captured_context_skips_without_capture(monkeypatch):
    from app.services import llm_provider

    monkeypatch.delattr(llm_provider, "capture", raising=False)
    with pytest.raises(pytest.skip.Exception, match="capture"):
        await assert_captured_context_clean(None, lambda: None)


async def test_captured_context_passes_and_catches(toy, monkeypatch):
    from app.services import llm_provider

    sink: list = []
    monkeypatch.setattr(llm_provider, "capture", lambda: _FakeCapture(sink), raising=False)
    player = toy.actors["player"]

    async def clean_run():
        sink.append({"messages": [{"role": "user", "content": "who is Barnaby?"}]})
        return "ok"
    assert await assert_captured_context_clean(player, clean_run) == "ok"

    async def leaky_run():
        sink.append({"messages": [{"role": "system", "content": f"GM notes: {toy.canary.token}"}]})
    with planted():
        await assert_captured_context_clean(player, leaky_run)


async def test_captured_context_refuses_empty_capture(toy, monkeypatch):
    from contextlib import nullcontext

    from app.services import llm_provider

    monkeypatch.setattr(llm_provider, "capture", lambda: nullcontext(None), raising=False)
    with pytest.raises(TypeError, match="capture\\(\\) yielded nothing to scan"):
        await assert_captured_context_clean(toy.actors["player"], lambda: None)


# ── Public vs Members vs Owner(other) ──────────────────────────────────────

async def test_audience_ladder_passes(toy):
    await assert_audience_ladder(toy.ev4, lambda a: "/public" if a.name == "anon_share" else "/members")


async def test_audience_ladder_catches_public_superset(toy):
    toy.state["public"] = ["1", "3"]
    with planted() as p:
        await assert_audience_ladder(toy.ev4, lambda a: "/public" if a.name == "anon_share" else "/members")
    assert "'3'" in str(p.excinfo.value)


async def test_audience_ladder_catches_canary(toy):
    with planted():
        await assert_audience_ladder(toy.ev4, "/leak-body")


def _ladder_url(actor):
    return {"anon_share": "/public", "gm_owner": "/gm"}.get(actor.name, "/members")


async def test_audience_ladder_requires_members_within_gm(toy):
    await assert_audience_ladder(toy.ev4, _ladder_url)
    toy.state["gm"] = ["1"]
    with planted() as p:
        await assert_audience_ladder(toy.ev4, _ladder_url)
    assert "the GM does not" in str(p.excinfo.value) and "'2'" in str(p.excinfo.value)


async def test_audience_ladder_refuses_error_response(toy):
    url = lambda a: "/thing/missing" if a.name == "player_2" else _ladder_url(a)  # noqa: E731
    with pytest.raises(ValueError, match=r"as player_2: GET /thing/missing returned 404"):
        await assert_audience_ladder(toy.ev4, url)


# ── downgrade suite ────────────────────────────────────────────────────────

def test_downgrade_suite_is_empty_without_registry():
    try:
        import app.access.registry  # noqa: F401
    except ImportError:
        assert downgrade_suite() == []
    else:
        pytest.skip("app.access.registry exists; covered by test_downgrade_suite_reads_registry")


def test_downgrade_suite_reads_registry(monkeypatch):
    access = types.ModuleType("app.access")
    registry = types.ModuleType("app.access.registry")
    registry.DERIVED_REGISTRY = {
        "recap": types.SimpleNamespace(derive_from=["journal_entries", "entities"]),
        "chat_message": ("journal_entries",),
    }
    monkeypatch.setitem(sys.modules, "app.access", access)
    monkeypatch.setitem(sys.modules, "app.access.registry", registry)
    assert downgrade_suite() == [
        DowngradeCase("chat_message", ("journal_entries",)),
        DowngradeCase("recap", ("journal_entries", "entities")),
    ]
    assert downgrade_suite("recap") == [DowngradeCase("recap", ("journal_entries", "entities"))]
    assert downgrade_suite("not_registered") == []


def _install_registry(monkeypatch, **attrs):
    access = types.ModuleType("app.access")
    access.__path__ = []
    registry = types.ModuleType("app.access.registry")
    for k, v in attrs.items():
        setattr(registry, k, v)
    monkeypatch.setitem(sys.modules, "app.access", access)
    monkeypatch.setitem(sys.modules, "app.access.registry", registry)


def test_downgrade_suite_fails_when_registry_lacks_derived_registry(monkeypatch):
    _install_registry(monkeypatch)
    with pytest.raises(ValueError, match="defines no DERIVED_REGISTRY"):
        downgrade_suite()


@pytest.mark.parametrize("derived_registry, missing", [
    ({"recap": {"source": ["journal_entries"]}}, "derive_from"),
    ({"recap": types.SimpleNamespace(sources=["journal_entries"])}, "derive_from"),
    ([{"derive_from": ["journal_entries"]}], "derived_type"),
    ([{"derived_type": "recap"}], "derive_from"),
    ([types.SimpleNamespace(derived_type="recap")], "derive_from"),
])
def test_downgrade_suite_rejects_incomplete_entries(monkeypatch, derived_registry, missing):
    _install_registry(monkeypatch, DERIVED_REGISTRY=derived_registry)
    with pytest.raises(ValueError, match=f"has no '{missing}'"):
        downgrade_suite()


def test_downgrade_suite_reads_list_registry(monkeypatch):
    # RC-8 shape: a list of {derived_type, derive_from} entries.
    access = types.ModuleType("app.access")
    registry = types.ModuleType("app.access.registry")
    registry.DERIVED_REGISTRY = [{"derived_type": "live_recap", "derive_from": ["live_segment"]}]
    monkeypatch.setitem(sys.modules, "app.access", access)
    monkeypatch.setitem(sys.modules, "app.access.registry", registry)
    assert downgrade_suite("live_recap") == [DowngradeCase("live_recap", ("live_segment",))]


async def test_downgrade_case_passes_and_catches(toy):
    case = DowngradeCase("recap", ("journal_entries",))
    player = toy.actors["player"]

    def downgrade():
        toy.state["downgraded"] = True
    await case.check(player, "/thing/visible", "/thing/missing", downgrade)

    toy.state["downgraded"] = False
    with planted():
        await case.check(player, "/thing/visible", "/thing/missing", lambda: None)


async def test_downgrade_case_refuses_derived_not_visible_before(toy):
    case = DowngradeCase("recap", ("journal_entries",))
    with pytest.raises(ValueError, match=r"/thing/missing returned 404"):
        await case.check(toy.actors["player"], "/thing/missing", "/thing/missing", lambda: None)


# ── probe runner ───────────────────────────────────────────────────────────

async def test_runner_fails_a_probe_that_runs_no_family_check(toy):
    async def probe_nothing(ev4, actor):
        await actor.get("/clean")

    async def probe_checks(ev4, actor):
        assert_no_canary(actor, await actor.get("/clean"))

    await run_probe(Probe("GET", "/clean", probe_checks), toy.ev4, toy.actors["player"])
    with pytest.raises(pytest.fail.Exception, match="probe test_families.probe_nothing ran no EV-4 family check"):
        await run_probe(Probe("GET", "/clean", probe_nothing), toy.ev4, toy.actors["player"])
