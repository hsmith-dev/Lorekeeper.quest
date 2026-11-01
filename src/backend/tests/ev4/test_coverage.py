"""EV-4 coverage gate (CI-12): every route is probed, exempted or pending,
and every route reaches nginx's API locations.

The pending baseline only shrinks: FROZEN_PENDING below is the ceiling, the
routes that existed when the harness landed (E0-QA.11). Never add to it.
Deleting a line from pending_baseline.txt needs no change here.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from starlette.routing import Mount, Route

from app.main import app
from tests.ev4 import nginx
from tests.ev4.registry import Exemption, check_coverage, load_exemptions, load_pending, load_probes
from tests.ev4.routes import (
    DOCS_PATHS, UnknownRouteKind, api_routes, is_api_location, nginx_locations, resolve_route, sample_path,
)

FROZEN_PENDING = frozenset({
    'DELETE /api/admin/promo-codes/{promo_id}',
    'DELETE /api/admin/users/{user_id}',
    'DELETE /api/campaigns/{campaign_id}',
    'DELETE /api/campaigns/{campaign_id}/members/{member_id}',
    'DELETE /api/campaigns/{campaign_id}/share/{token_id}',
    'DELETE /api/campaigns/{campaign_id}/tag-categories/{category_id}',
    'DELETE /api/character-sheets/{sheet_id}',
    'DELETE /api/character-sheets/templates/{template_id}',
    'DELETE /api/chat/sessions/{session_id}',
    'DELETE /api/journals/{journal_id}',
    'DELETE /api/journals/{journal_id}/tags/{tag_id}',
    'DELETE /api/npcs/{npc_id}',
    'DELETE /api/quests/{quest_id}',
    'DELETE /api/session-plans/{plan_id}',
    'DELETE /api/settings/evaluations/{evaluation_id}',
    'DELETE /api/shorthand/{term_id}',
    'DELETE /api/sources/{source_id}',
    'GET /api/admin/config',
    'GET /api/admin/logs',
    'GET /api/admin/models',
    'GET /api/admin/promo-codes',
    'GET /api/admin/support-bundle',
    'GET /api/admin/users',
    'GET /api/auth/me',
    'GET /api/billing/status',
    'GET /api/campaigns/',
    'GET /api/campaigns/{campaign_id}/analytics',
    'GET /api/campaigns/{campaign_id}/export',
    'GET /api/campaigns/{campaign_id}/members',
    'GET /api/campaigns/{campaign_id}/share',
    'GET /api/campaigns/{campaign_id}/tag-categories',
    'GET /api/character-sheets/',
    'GET /api/character-sheets/{sheet_id}',
    'GET /api/character-sheets/templates',
    'GET /api/chat/health',
    'GET /api/chat/sessions',
    'GET /api/chat/sessions/{session_id}',
    'GET /api/feedback/',
    'GET /api/feedback/{feedback_id}/context',
    'GET /api/health',
    'GET /api/journals/',
    'GET /api/journals/{journal_id}',
    'GET /api/npcs/',
    'GET /api/npcs/{npc_id}',
    'GET /api/npcs/{npc_id}/entries',
    'GET /api/quests/',
    'GET /api/quests/{quest_id}',
    'GET /api/quests/{quest_id}/entries',
    'GET /api/session-plans/',
    'GET /api/session-plans/{plan_id}',
    'GET /api/settings/',
    'GET /api/settings/evaluations',
    'GET /api/settings/model-status',
    'GET /api/share/{token}',
    'GET /api/share/{token}/journals',
    'GET /api/share/{token}/journals/{journal_id}',
    'GET /api/share/{token}/npcs',
    'GET /api/share/{token}/quests',
    'GET /api/shorthand/',
    'GET /api/sources/',
    'GET /api/tags/',
    'PATCH /api/admin/promo-codes/{promo_id}',
    'PATCH /api/admin/users/{user_id}/access',
    'PATCH /api/campaigns/{campaign_id}',
    'PATCH /api/character-sheets/{sheet_id}',
    'PATCH /api/character-sheets/templates/{template_id}',
    'POST /api/admin/models/install',
    'POST /api/admin/promo-codes',
    'POST /api/admin/users/{user_id}/demote',
    'POST /api/admin/users/{user_id}/message',
    'POST /api/admin/users/{user_id}/promote',
    'POST /api/admin/users/{user_id}/suspend',
    'POST /api/admin/users/{user_id}/unsuspend',
    'POST /api/auth/forgot-password',
    'POST /api/auth/login',
    'POST /api/auth/register',
    'POST /api/auth/reset-password',
    'POST /api/auth/tutorial-complete',
    'POST /api/billing/checkout',
    'POST /api/billing/portal',
    'POST /api/billing/redeem-promo',
    'POST /api/billing/webhook',
    'POST /api/campaigns/',
    'POST /api/campaigns/{campaign_id}/leave',
    'POST /api/campaigns/{campaign_id}/share',
    'POST /api/campaigns/{campaign_id}/tag-categories',
    'POST /api/campaigns/generate-concept',
    'POST /api/character-sheets/',
    'POST /api/character-sheets/templates',
    'POST /api/chat/',
    'POST /api/chat/stream',
    'POST /api/feedback/',
    'POST /api/ingest/discord',
    'POST /api/ingest/image',
    'POST /api/ingest/voice',
    'POST /api/journals/{journal_id}/tags',
    'POST /api/journals/autocomplete',
    'POST /api/journals/generate',
    'POST /api/journals/generate-draft',
    'POST /api/journals/recap',
    'POST /api/journals/reindex',
    'POST /api/journals/summarize-session',
    'POST /api/npcs/',
    'POST /api/npcs/{npc_id}/generate',
    'POST /api/npcs/extract',
    'POST /api/quests/',
    'POST /api/quests/{quest_id}/generate',
    'POST /api/quests/suggest',
    'POST /api/session-plans/',
    'POST /api/session-plans/generate',
    'POST /api/settings/evaluate',
    'POST /api/settings/test',
    'POST /api/share/{token}/join',
    'POST /api/shorthand/',
    'POST /api/sources/',
    'PUT /api/admin/config',
    'PUT /api/auth/me/avatar',
    'PUT /api/npcs/{npc_id}',
    'PUT /api/quests/{quest_id}',
    'PUT /api/session-plans/{plan_id}',
    'PUT /api/settings/',
    'PUT /api/shorthand/{term_id}',
})


def _keys() -> set[str]:
    return {r.key for r in api_routes(app)}


# ── The gate ────────────────────────────────────────────────────────────────

def test_every_route_is_probed_exempted_or_pending():
    errors = check_coverage(
        _keys(), [p.key for p in load_probes()], load_exemptions(), load_pending(), FROZEN_PENDING,
    )
    assert not errors, "EV-4 coverage:\n" + "\n".join(f"  - {e}" for e in errors)


def test_route_enumeration_covers_the_whole_app():
    keys = _keys()
    assert "GET /api/health" in keys
    assert "GET /api/share/{token}/npcs" in keys
    assert all(k.split(" ", 1)[1].startswith("/api") for k in keys), "a route outside /api"
    assert not any(k.split(" ", 1)[1] in DOCS_PATHS for k in keys)


def test_every_route_resolves_to_an_api_location():
    bad = []
    for route in api_routes(app):
        loc = resolve_route(route)
        if not is_api_location(loc):
            bad.append(f"{route.key} -> {sample_path(route.path)} lands in {loc!r}")
    assert not bad, "routes nginx would not proxy to the API:\n" + "\n".join(bad)


def test_every_exact_api_location_matches_a_route():
    routes = api_routes(app)
    exact = [loc for loc in nginx_locations().walk()
             if loc.modifier == nginx.EXACT and loc.uri.startswith("/api/")]
    assert exact, "expected the AI-zone exact locations in nginx/locations.conf"
    orphans = [f"{loc.label} ({loc.where})" for loc in exact
               if not any(r.path_regex.match(loc.uri) for r in routes)]
    assert not orphans, "nginx exact locations with no app route (stale rate-limit block?):\n" + "\n".join(orphans)


# ── check_coverage rules (I/O matrix) ──────────────────────────────────────

ROUTES = {"GET /api/a", "GET /api/b/{id}", "POST /api/c"}


def _check(probes=(), exemptions=(), pending=(), frozen=None):
    return check_coverage(ROUTES, probes, exemptions, pending, ROUTES if frozen is None else frozen)


def test_all_covered_passes():
    assert _check(probes=["GET /api/a"], exemptions=[Exemption("POST /api/c", "static")],
                  pending=["GET /api/b/{id}"]) == []


def test_new_route_fails_naming_it():
    errors = _check(probes=["GET /api/a"], pending=["GET /api/b/{id}"])
    assert len(errors) == 1
    assert "POST /api/c" in errors[0] and "probe" in errors[0] and "exemption" in errors[0]


def test_baseline_growth_fails_naming_the_line():
    errors = _check(pending=sorted(ROUTES), frozen={"GET /api/a", "GET /api/b/{id}"})
    assert len(errors) == 1
    assert "POST /api/c" in errors[0] and "only shrinks" in errors[0]


def test_stale_pending_probed_route_fails():
    errors = _check(probes=["GET /api/a"], pending=sorted(ROUTES))
    assert any("GET /api/a" in e and "remove it from pending_baseline.txt" in e for e in errors)


def test_stale_pending_removed_route_fails():
    errors = check_coverage({"GET /api/a"}, [], [], ["GET /api/a", "GET /api/gone"], {"GET /api/a", "GET /api/gone"})
    assert len(errors) == 1
    assert "GET /api/gone" in errors[0] and "remove it from pending_baseline.txt" in errors[0]


def test_exemption_without_reason_fails():
    errors = _check(exemptions=[Exemption("POST /api/c", "")], pending=["GET /api/a", "GET /api/b/{id}"])
    assert len(errors) == 1
    assert "POST /api/c" in errors[0] and "reason" in errors[0]


def test_stale_exemption_and_probe_fail():
    errors = _check(probes=["GET /api/gone"], exemptions=[Exemption("GET /api/old", "x")], pending=sorted(ROUTES))
    assert any("stale probe" in e and "GET /api/gone" in e for e in errors)
    assert any("stale exemption" in e and "GET /api/old" in e for e in errors)


def test_duplicate_pending_line_fails():
    errors = _check(pending=sorted(ROUTES) + ["POST /api/c"])
    assert any("twice" in e for e in errors)


def test_exemptions_file_loader(tmp_path):
    f = tmp_path / "ex.yaml"
    f.write_text("- route: 'GET  /api/a'\n  reason: '  static  '\n- route: POST /api/c\n")
    assert load_exemptions(f) == [Exemption("GET /api/a", "static"), Exemption("POST /api/c", "")]
    f.write_text("[]\n")
    assert load_exemptions(f) == []
    f.write_text("- route: GET /api/a\n  why: nope\n")
    with pytest.raises(ValueError):
        load_exemptions(f)


def test_unknown_route_kind_fails_loudly():
    toy = FastAPI()

    @toy.get("/api/x")
    async def x():
        return {}

    assert [r.key for r in api_routes(toy)] == ["GET /api/x"]
    toy.router.routes.append(Mount("/static", routes=[]))
    with pytest.raises(UnknownRouteKind, match="Mount"):
        api_routes(toy)
    toy.router.routes.pop()
    toy.router.routes.append(Route("/raw", lambda request: None))
    with pytest.raises(UnknownRouteKind, match="/raw"):
        api_routes(toy)


def test_websocket_routes_are_enumerated():
    toy = FastAPI()

    @toy.websocket("/api/live/{live_session_id}/ws")
    async def ws(websocket: WebSocket, live_session_id: str):
        pass

    assert [r.key for r in api_routes(toy)] == ["WS /api/live/{live_session_id}/ws"]


def test_sample_path():
    assert sample_path("/api/npcs/{npc_id}") == "/api/npcs/00000000-0000-4000-8000-000000000000"
    assert sample_path("/api/x/{n:int}") == "/api/x/1"
    assert sample_path("/api/health") == "/api/health"
