---
title: 'E0-QA.11 EV-4 harness scaffolding: route enumeration, actors and probe families'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '3c8d426a15d1ea531257f57b456d1298a3c3d37e'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Canary detection needs the whole token; truncated previews and compressed or archive bodies (campaign export zip) are not scanned.
    evidence: |-
      CANARY_RE needs the full uuid4 and _texts scans response.text only. It matters once E0-QA.13 probes GET /api/campaigns/{campaign_id}/export and any snippet or preview route. Settle it by planting a truncated token and a zipped token in a toy route.
    location: >-
      src/backend/tests/ev4/families.py
    severity: medium (unverified)
  - summary: >-
      The canary seed has no tags, tag categories, NPC/quest entry links, embeddings or analytics data.
    evidence: |-
      seeds/ev4_canary.json covers every GM-only field that exists today, but /api/tags counts, /api/npcs/{id}/entries and retrieval paths have nothing to return. E0-QA.13 should extend the seed when it probes those routes.
    location: >-
      seeds/ev4_canary.json
    severity: medium
  - summary: >-
      Actor.may_see models only "GM of the canary's Campaign"; Members-only and Owner-private canaries cannot be expressed yet, so the ladder's Owner(other) rung is only partly checked.
    evidence: |-
      No visibility column exists until E0-Access.1. When it lands, canaries need an audience and may_see must read it.
    location: >-
      src/backend/tests/ev4/fixtures.py (Actor.may_see), families.py (assert_audience_ladder)
    severity: medium
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

### 2026-11-01 — Review pass
- verdicts: 43 findings — high 0, medium 17, low 12, false 9, maybe-false 5
- findings:
  - `[medium]` `patch` (verification-gap) is_api_location has no negative test — test added for /campaigns/123, /assets/app.js and None; rule tightened to `/api` or `/api/…`.
  - `[medium]` `patch` (verification-gap) no body-only hidden-vs-missing test — /thing/hidden-body toy route and test added.
  - `[medium]` `patch` (blind) a caught or swallowed leak leaves the build green — pytest_sessionfinish sets exit status 1 when leak_count > 0.
  - `[medium]` `patch` (blind) a probe that calls no family helper still counts as coverage — family_calls counter; the runner fails a probe that makes no family call.
  - `[medium]` `patch` (blind) vacuous passes in hidden_field, counts, ladder and downgrade — `_require_ok` raises ValueError on a 400+ response or an empty precondition.
  - `[medium]` `patch` (blind) the counts snapshot ignores headers — non-volatile headers (minus content-length) are now compared.
  - `[low]` `reject` (blind) hidden-equals-missing flags bodies that echo the id — AD-13 mandates a byte-identical `404 {"detail":"Not found"}`, so an echoed id is a real difference.
  - `[maybe-false]` `defer` (blind) truncated, compressed or archive canaries are not detected — deferred (medium, unverified); settle with planted truncated and zipped tokens.
  - `[false]` `reject` (blind) add a role-less member actor — the story says role actors skip until campaign_members.role exists, and D-1b migrates today's Members to Player.
  - `[false]` `reject` (blind) no admin, unpaid or suspended actor — E0-QA.13 lists admin routes as reasoned exemptions; not in this story's actor list.
  - `[medium]` `defer` (blind) the seed lacks tags, links, embeddings and analytics — deferred to E0-QA.13 (probes for those routes).
  - `[low]` `reject` (blind) is_api_location does not check proxy_pass — the story says the parser only needs location lines; the fix needs directive inheritance.
  - `[medium]` `patch` (blind) every path param is sampled as a UUID, including `{token}` — `{token}` now maps to a urlsafe 32-char sample.
  - `[low]` `patch` (blind) the orphan check covers only `=` locations — `^~` and regex /api locations must be chosen by some route.
  - `[medium]` `patch` (blind) the ladder never checks Members ⊆ GM — the gm_owner rung was added.
  - `[medium]` `defer` (blind/intent) Owner(other) and Members-only canaries cannot be modelled — deferred until visibility exists (E0-Access).
  - `[low]` `reject` (blind) a PR can grow FROZEN_PENDING alongside the baseline — this is the repo's frozen-ceiling ratchet convention (E0-QA.10), and the edit is visible in review.
  - `[low]` `patch` (blind) ev4_probe actors not validated, exemption method case not normalised, missing validation tests — validated, normalised and tested.
  - `[medium]` `patch` (blind) AC 1's summary numbers are untested, and _summary swallows errors — test added; a summary error fails the session.
  - `[medium]` `patch` (edge) DERIVED_REGISTRY missing from an existing module returns [] — importlib plus getattr; raises.
  - `[low]` `patch` (edge) registry entry missing derive_from or derived_type — ValueError.
  - `[low]` `patch` (edge) hidden_field passes on 4xx or an empty body — covered by `_require_ok`.
  - `[low]` `patch` (edge) counts passes when both snapshots error — covered by `_require_ok`.
  - `[low]` `patch` (edge) the ladder passes when Public errors — covered by `_require_ok`.
  - `[low]` `patch` (edge) capture yields None — TypeError.
  - `[maybe-false]` `reject` (edge) compressed bodies or URL-encoded tokens — duplicate of the truncated-canary item (deferred there); URL-encoding a token keeps its alphanumerics and dashes, so it is still found.
  - `[false]` `reject` (edge) /etc/nginx includes not in nginx/ are silently dropped — mime.types and proxy_common.conf are not in the repo by design, and include files hold no locations today; failing on them would break the real config.
  - `[medium]` `patch` (edge) `location ^~/a` with no space is misparsed — now parsed as NOREGEX.
  - `[medium]` `patch` (edge) is_api_location accepts `/apifoo` — tightened (same fix as the verification-gap row).
  - `[medium]` `patch` (edge) unknown seed keys are dropped silently — validate_seed raises.
  - `[medium]` `patch` (edge) the test asserts only a subset of minted tokens are stored — it now asserts all of them are.
  - `[maybe-false]` `reject` (edge) a role text column with a CHECK that allows `gm`, not `co_gm` — unknowable until E0-Access.1; it would only be low (the fix is a label tweak in `_ROLE_LABELS`).
  - `[low]` `patch` (edge) lowercase exemption method — normalised (same fix as above).
  - `[low]` `patch` (edge) actor typo found only at runtime — validated at registration.
  - `[false]` `reject` (edge-claim) `^~/x` vs the spec's "fails on unknown modifier" — `^~/x` is valid nginx, now parsed correctly.
  - `[false]` `reject` (edge-claim) downgrade_suite claim — fixed by the importlib change above.
  - `[false]` `reject` (edge-claim) /apifoo claim — fixed by the tightening above.
  - `[maybe-false]` `reject` (intent a) helper signatures differ from the story's shorthand — the actor and ev4 args are needed context; `fixtures.make_member` is now module-level, as E0-Access.13 expects.
  - `[false]` `reject` (intent b) cross_gm_player labels swapped — the structure is identical: GM in one Campaign, Player in the canary one.
  - `[low]` `patch` (intent d) the leak count did not count canary hits — record_leak(count=len(hits)).
  - `[false]` `reject` (intent e) synthetic sample paths — `{token}` sample fixed; the others are UUIDs, as the app uses.
  - `[false]` `reject` (intent f) extra gates — stale or orphan checks keep the shrink-only and route list honest; CI is green with them.
  - `[maybe-false]` `reject` (intent g) role paths only exercised up to the skip — the story specifies the skip; the make_member insert runs once E0-Access.1 adds the column.

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

## Auto Run Result

Status: done

**Summary:** EV-4 harness scaffold in `src/backend/tests/ev4/`:
- route enumeration from `app.routes`;
- an nginx parser and matcher that follows nginx's real order;
- a coverage gate: probe, reasoned exemption, or a line in the shrink-only `pending_baseline.txt` (122 routes);
- the canary seed `seeds/ev4_canary.json` and the actors;
- the seven probe families, with a leak counter that fails the session;
- a CI-12 step in `gates.yml`.

**Files:**
- `seeds/ev4_canary.json`: the canary Campaign.
- `tests/ev4/{nginx,routes,registry,report,fixtures,families,conftest}.py`: the harness.
- `exemptions.yaml`, `pending_baseline.txt`: coverage lists.
- `probes/__init__.py`: the append-point template.
- `test_{coverage,nginx,families,fixtures,probes}.py`: the tests.
- `.github/workflows/gates.yml`: the CI-12 step.

**Review:** 43 findings.
- 27 patched (13 medium, 14 low).
- 3 deferred (seed breadth, truncated or archive canaries, audience-aware canaries).
- 13 rejected, with reasons in the triage log.

**Follow-up review recommended:** true. Two or more medium entries were patched. The specific unverified risk is the DB-backed fixtures (seed-to-table coverage, module-level `make_member`): they run only in CI.

**Verification:**
- Local DB-free run (stubbed model packages): 98 passed, 1 skipped.
- GitHub CI on PR #34, first push: all checks green. `CI-12` gave 86 passed, 1 skipped, `EV-4: probes=0 exemptions=0 pending=122 leaks=0`.
- The patched push has been re-run on CI.
- The sprint-status sync was skipped, per the builder brief.

**Residual risks:**
- `make_member` guesses the role value (`co_gm` or `gm`) until E0-Access.1 lands.
- The `llm_provider.capture()` and `DERIVED_REGISTRY` shapes are assumed.

**Needs desktop verification:**
- `pytest tests/ev4` on the desktop needs the repo-root `seeds/` and `nginx/`. Rsync the whole repo, not just `src/backend`, then run the brief's docker command with `python -m pytest -q tests/ev4`.
