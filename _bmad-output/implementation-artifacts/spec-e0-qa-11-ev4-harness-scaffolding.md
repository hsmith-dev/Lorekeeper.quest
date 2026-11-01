---
title: 'E0-QA.11 EV-4 harness scaffolding: route enumeration, actors and probe families'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '3c8d426a15d1ea531257f57b456d1298a3c3d37e'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Nothing enumerates the API surface for spoiler-leak testing, so a new route that leaks GM content is silently untested. E0-Access, E0-QA.13 and E0-QA.14 need a harness (route list, canary seed, actors, probe families) to build on.

**Approach:** A new `src/backend/tests/ev4/` package: route enumeration from `app.routes` plus an nginx `location` parser with nginx's real matching order; a coverage test (probe, reasoned exemption, or shrink-only pending baseline); a canary seed and actor fixtures; the probe-family helpers with a leak counter; and a CI-12 step in `gates.yml` that reports probe/exemption/pending/leak counts.

## Boundaries & Constraints

**Always:**
- Coverage is computed from the live `app.routes` (every `APIRoute` method and `APIWebSocketRoute`); any other route kind except FastAPI's docs routes fails loudly.
- Every pre-existing route is listed in `tests/ev4/pending_baseline.txt`; the test holds a frozen ceiling, so adding a line fails, and a stale line (route probed, exempted or gone) fails.
- Exemptions need a non-empty `reason`; stale exemptions/probes (no such route) fail.
- The nginx parser fails loudly on location syntax it cannot parse (bad arg count, unknown modifier, bad regex, unbalanced braces, duplicate location).
- Canary tokens are unique per seeding (`CANARY-<KIND>-<uuid4>`); a hit is a leak unless the actor is GM in the canary's Campaign.
- Family helpers raise `EV4Leak` (an `AssertionError`) and increment the leak count; a leak fails the build, a pending route does not.
- `make_member(role=…)` raises `pytest.skip("roles not yet available")` while `campaign_members.role` does not exist, and inserts the role when it does.
- `assert_captured_context_clean` uses `llm_provider.capture()` when present, else skips with a reason; `downgrade_suite` reads `app.access.registry.DERIVED_REGISTRY` when importable, else returns `[]`.

**Never:**
- Write probes for existing routes (E0-QA.13) or chat/captured-context probes (E0-QA.14); change app code, nginx config, `tests/conftest.py`, `tests/test_share.py`, `sprint-status.yaml` or `epics.md`.
- Depend on E0-QA.12's `seeds/demo_campaign.json`.
- Touch `llm_provider.py`, the stt sidecar or the frontend.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| New route | route not probed/exempt/pending | coverage test fails | names `METHOD PATH`, says add a probe or exemption |
| Baseline grows | line added to pending | test fails | names the line, "only shrinks" |
| Stale pending | pending route now probed or removed | test fails | "remove it from pending_baseline.txt" |
| Exemption no reason | `reason: ""` | test fails | names entry |
| nginx exact vs regex | `= /a` and `~ ^/a` | exact wins | — |
| nginx `^~` vs regex | `^~ /a/` and `~ /a/b` on `/a/b` | `^~` wins | — |
| nginx regex vs prefix | `/a/` and `~ /a/b` on `/a/b` | regex (file order) wins | — |
| nginx unparseable | `location a b c {` or `{36}` unquoted | parse raises `NginxParseError` | message names file/line |
| Canary in body/header | non-GM response holds a canary | `EV4Leak`, leak count +1 | lists hits |
| Roles absent | `make_member(role="player")` | `pytest.skip` | reason "roles not yet available" |

</intent-contract>

## Code Map

- `src/backend/app/main.py` -- `create_app()`: all routers under `/api/*`; `/api/health` inline; `share.router` unauthenticated. FastAPI docs routes `/openapi.json`, `/docs`, `/docs/oauth2-redirect` are starlette `Route`s.
- `nginx/nginx.conf` -- 443 server `include /etc/nginx/locations.conf;` (80 server only `return 301`); `map` block has quoted `~*` regex (tokenizer must honour quotes).
- `nginx/locations.conf` -- `=` exact AI locations, prefix `/api/auth/`, `/api/`, `/` with a nested `~*` static-assets regex; commented template with unquoted `{36}` (comments are stripped).
- `src/backend/tests/conftest.py` -- `db`, `client`, `promo_code` fixtures; `client` resets the limiter and overrides `get_db`. Rows committed persist across tests (unique tokens needed).
- `src/backend/app/core/security.py` -- `create_access_token(user_id)`, `hash_password`; actors are ORM users with `access_granted=True` (avoids the 5/min register limit).
- `src/backend/app/db/models/{campaign,campaign_member,share_token,journal,npc,quest,shorthand,session_plan,chat,source,character_sheet}.py` -- seed targets; GM-only today: journal `shorthand`, NPC/Quest `notes`, whole `shorthand_terms`, `session_plans`, `chat_sessions`, `source_documents`/`source_chunks`, `character_sheets` (AR-26: no Visibility). `CampaignMember` has no `role` yet.
- `src/backend/app/services/llm_provider.py` -- no `capture()` yet (E0-LLM.5).
- `src/backend/tests/test_share.py` -- reference for seeding rows via ORM; share reads at `/api/share/{token}/{journals,npcs,quests}`.
- `.github/workflows/gates.yml` -- commented CI-12 slot in the `database` job.

## Tasks & Acceptance

**Execution:**
- `seeds/ev4_canary.json` -- canary Campaign seed: Party-visible rows plus each GM-only field/record holding a `{canary:KIND}` placeholder.
- `src/backend/tests/ev4/__init__.py`, `probes/__init__.py` -- package; probes docstring is the append-point template.
- `src/backend/tests/ev4/nginx.py` -- tokenizer, block parser (include splicing for files in `nginx/`), `Location` tree, `resolve(uri)` in nginx order.
- `src/backend/tests/ev4/routes.py` -- `api_routes(app)`, `nginx_locations()`, `resolve_route(route)`, sample-path generation.
- `src/backend/tests/ev4/registry.py` -- `ev4_probe(method, path, actors=…)`, `load_probes()`, exemptions/pending loaders.
- `src/backend/tests/ev4/report.py` -- counters, `EV4Leak`, `record_leak`, scoped report for self-tests.
- `src/backend/tests/ev4/fixtures.py` -- `Actor`, canary seeding, `EV4` context (`actor(name)`, `make_member`), pytest fixture `ev4`.
- `src/backend/tests/ev4/families.py` -- the seven family helpers.
- `src/backend/tests/ev4/conftest.py` -- registers fixtures; `pytest_terminal_summary` prints counts (and to `$GITHUB_STEP_SUMMARY`).
- `src/backend/tests/ev4/exemptions.yaml`, `pending_baseline.txt` -- empty exemptions list; every current route pending.
- `src/backend/tests/ev4/test_coverage.py`, `test_nginx.py`, `test_families.py`, `test_fixtures.py`, `test_probes.py` -- coverage gate, parser/matching tests (matrix rows), family self-tests on a toy app (positive + planted-leak controls), seed/actor tests against the DB, probe runner.
- `.github/workflows/gates.yml` -- uncomment CI-12 step (`python -m pytest -v tests/ev4`).

**Acceptance Criteria:**
- Given `pytest tests/ev4` on this branch, when it runs in CI, then it passes and the summary line reports probes=0, exemptions=0, pending=<route count>, leaks=0.
- Given each API route, when resolved against the parsed nginx config, then it maps to a `/api…` location (never the static `/`), and every `=` location under `/api/` matches an app route.
- Given the canary seed, when the GM's own `GET /api/npcs/?campaign_id=` body is checked with `assert_no_canary` for a non-GM actor, then it raises `EV4Leak` (positive control), and the share-read routes as `anon_share` pass.

## Spec Change Log

## Review Triage Log

## Design Notes

nginx matching (mirrors `ngx_http_core_find_location`): at each level, an exact `=` hit returns; else take the longest prefix (`^~` sets noregex), recurse into its children (a child exact/regex hit returns), then try this level's regexes in file order unless noregex, else the longest prefix (or deeper child prefix).

Probe shape: `@ev4_probe("GET", "/api/npcs/{npc_id}")` on `async def probe(ev4, actor)`; the runner parametrizes probe × actor (default `anon_share`, `player`, `cross_gm_player`), so a role-less actor skips only its own case.


Actor model: `Actor(name, client, headers, user_id, share_token, grants: {campaign_id: "gm"|"player"|"anon"})`; `actor.get/post/request(...)`; `actor.may_see(canary)` is true only when `grants[canary.campaign_id] == "gm"`. Actors: `gm_owner` (owns A), `anon_share` (no auth, read-only token for A), `anonymous` (no auth, no token), `player` (Player in A), `co_gm` (role `gm` in A), `cross_gm_player` (owns B, seeded from the same JSON with its own tokens; Player in A). `player`/`co_gm`/`cross_gm_player` resolve lazily via `make_member`, so the skip hits only cases that need them. Repo root (for `seeds/`, `nginx/`) is found from the test file path; fail with a clear message if missing.

Family semantics: `assert_no_canary` regex-scans body text and every header for `CANARY-[A-Z0-9]+-<uuid>` and leaks on any token the actor may not see (tokens from other tests' campaigns count). `assert_hidden_equals_missing` compares status, body and headers except volatile ones (`date`, `x-response-time`, `server`). `assert_hidden_field_equals_unset(actor, url, field, unset=None, unset_url=None)`: dotted field in an object or every list item is absent or equals `unset`; with `unset_url`, presence and value must match the control. `assert_counts_and_ranking_unchanged(actor, url | [urls], mutate_gm_only, ignore=("updated_at",))`: full JSON body (minus ignored keys) and status identical before/after the awaited mutation. `assert_audience_ladder(url | callable(actor) -> url)`: as `anon_share`, `player`, a second player — no unpermitted canary, and Public item ids ⊆ Members item ids. `downgrade_suite` returns `DowngradeCase(derived_type, derive_from)` items with `async check(actor, derived_url, missing_url, downgrade)` = await downgrade, then hidden-equals-missing.

## Verification

**Commands:**
- `cd src/backend && python -m pytest -v tests/ev4` (CI `gates.yml` database job and `backend-tests.yml`) -- expected: all pass, role-dependent cases skipped.
- `uv run --python 3.11 python -m py_compile src/backend/tests/ev4/*.py` -- expected: no errors.
- Local machine has no Postgres and no heavy backend deps; run the DB-free parts locally where possible (`test_nginx.py` logic via a small `uv run --with pyyaml --with pytest` harness importing only `tests/ev4/nginx.py`), and leave DB/app tests to GitHub CI. Do not install torch/whisper locally; do not push or commit.
