---
title: 'E0-Platform.8 (3.8): Per-user rate-limit keying in slowapi and nginx'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
warnings: []
deferred:
  - summary: >-
      Other LLM routes outside the story's enumerated list have no slowapi limit and no ai_gen nginx location.
    evidence: |-
      campaigns.py:55 POST /generate-concept, quests.py:118 POST /{quest_id}/generate, quests.py:153 POST /suggest,
      npcs.py:118 POST /{npc_id}/generate and npcs.py:154 POST /extract all depend on get_user_llm_config and call an LLM,
      but they predate this story and are not in E0-Platform.8's route list. They get only the generic 30r/s api zone.
      sources.py:49 upload (embeds documents) keeps the default IP key. A follow-up should apply
      @limiter.limit(..., key_func=user_or_ip) and add ai_gen locations (anchored regex for the {id} routes), plus a guard
      test that walks app.routes for get_user_llm_config dependants.
    location: >-
      src/backend/app/api/routes/campaigns.py:55
    severity: medium
  - summary: >-
      slowapi uses in-memory storage, so in production each of the 4 gunicorn workers keeps its own counters.
    evidence: |-
      Limiter(key_func=get_remote_address) has no storage_uri; docker-compose.prod.yml:164 runs gunicorn -w 4, so a
      per-user limit is effectively up to 4x the stated value. Pre-existing; Redis is already deployed (settings.redis_url).
    location: >-
      src/backend/app/core/limiter.py
    severity: medium
  - summary: >-
      No automated check of the nginx config or of the $lk_rate_key map's behaviour.
    evidence: |-
      No CI job runs nginx -t on nginx/** changes, and nothing asserts that `Bearer a.b.c` keys on `c` and that other
      headers fall back to the IP. Verified by hand for this story (nginx -t on nginx:alpine and nginx:1.27-alpine, plus a
      runtime map probe with return 200 $lk_rate_key). The EV-4 nginx harness is E0-QA.11's.
    location: >-
      nginx/nginx.conf
    severity: medium
---

<intent-contract>

## Intent

**Problem:** slowapi keys every limit on `get_remote_address` and nginx's `ai_gen` zone keys on `$binary_remote_addr`, so a GM and Players behind one home router share a single AI bucket (NFR-8, D-5, AD-20). Several AI routes (journals generate/generate-draft/autocomplete/recap/summarize-session, session-plans generate, settings test/evaluate) have no slowapi limit at all.

**Approach:** Add `user_or_ip(request)` to `app/core/limiter.py` (signature-checked JWT decode, no DB, `user:<sub>` else remote address) and apply `@limiter.limit(..., key_func=user_or_ip)` to every existing AI/streaming route. In nginx, key `ai_gen` on `map $http_authorization $lk_rate_key` (the bearer JWT's signature segment, i.e. an HMAC-SHA256 hash of the token, falling back to `$binary_remote_addr`) and add a commented template for future routes to `locations.conf`.

## Boundaries & Constraints

**Always:** `Limiter(key_func=get_remote_address)` stays the default, so auth, share and sources keep IP keying. `user_or_ip` never raises and never touches the DB. `limiter.reset()` in `tests/conftest.py` keeps working unchanged. The `api` and `auth` zones and every existing `location` keep their current shape. The bearer and its hash are never logged (the `json_combined` log format stays free of them). `nginx -t` passes.

**Never:** No change to auth semantics (`get_current_user` remains the access check; `user_or_ip` is only a bucket key). No new Python or nginx modules. No real `/_files/` location, job routes or regex locations (E0-Jobs and feature epics add those). No edits to `sprint-status.yaml` or `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid bearer | `Authorization: Bearer <valid HS256 JWT, sub=U>` | `user:U` | No error expected |
| No header | no `Authorization` | remote address | No error expected |
| Bad token | wrong signature, expired, malformed, no `sub`, non-Bearer scheme | remote address | Swallow `JWTError`/any decode error |
| Two users, one IP | users A and B, same client address, each at the route limit | neither gets 429; A's next request gets 429 | 429 via slowapi handler |
| nginx, JWT bearer | `Bearer h.p.sig` | `$lk_rate_key` = `sig` | n/a |
| nginx, other | missing or non-JWT header | `$lk_rate_key` = `$binary_remote_addr` | n/a |

</intent-contract>

## Code Map

- `src/backend/app/core/limiter.py` -- single `limiter = Limiter(key_func=get_remote_address)`; add `user_or_ip` here.
- `src/backend/app/core/security.py` -- `ALGORITHM = "HS256"`, `settings.secret_key`; `decode_token_payload` raises `HTTPException`, so `user_or_ip` calls `jose.jwt.decode` directly inside try/except.
- `src/backend/app/api/routes/chat.py:330,355` -- `/` and `/stream` already `@limiter.limit("20/minute")` with `request: Request`; add `key_func=user_or_ip`.
- `src/backend/app/api/routes/ingest.py:43,67` -- `/image`, `/voice` `@limiter.limit("10/minute")` with `request`; add key_func. `/image` returns 415 for a non-image content type inside the body (after the limiter), which makes it a cheap, LLM-free test target.
- `src/backend/app/api/routes/journals.py:38,58,230,253,279` -- generate-draft, generate, autocomplete, recap, summarize-session: no limit, no `request`; add both.
- `src/backend/app/api/routes/session_plans.py:35` -- `/generate`: add limit and `request`.
- `src/backend/app/api/routes/settings.py:151,211` -- `/test`, `/evaluate`: add limit and `request`.
- `src/backend/app/main.py:55-58` -- limiter state, `RateLimitExceeded` handler, `SlowAPIMiddleware` (read-only).
- `src/backend/tests/conftest.py` -- `client` fixture calls `limiter.reset()`; ASGITransport client address is fixed, so two tokens through one client is the "same IP" case. `promo_code` fixture gives `access_granted` (feature routers are gated by `require_active_account`).
- `nginx/nginx.conf:46-56` -- zones; `ai_gen` is `$binary_remote_addr` 10r/m. Needs a `map` in `http {}`.
- `nginx/locations.conf` -- exact-match `ai_gen` locations; append a commented template block.
- `nginx/Dockerfile` -- copies nginx.conf, locations.conf and proxy_common.conf to `/etc/nginx/` (validation mount layout).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/limiter.py` -- add `user_or_ip(request)`: read `Authorization`, require case-insensitive `Bearer ` scheme, `jwt.decode(token, settings.secret_key, algorithms=["HS256"])`, return `f"user:{sub}"` when `sub` is a non-empty string, else `get_remote_address(request)`; docstring notes it is a bucket key, not authentication. Keep the default key.
- `src/backend/app/api/routes/chat.py`, `ingest.py` -- add `key_func=user_or_ip` to the existing limits, values unchanged.
- `src/backend/app/api/routes/journals.py`, `session_plans.py`, `settings.py` -- add `request: Request` and `@limiter.limit("20/minute", key_func=user_or_ip)` (`/api/settings/evaluate`: `"5/minute"`, as it runs many completions per call), placed directly under `@router.post`.
- `src/backend/tests/test_rate_limit.py` -- unit tests for `user_or_ip` (valid, missing, wrong signature, expired, non-Bearer, no sub) and an integration test: two promo-registered users through one client each post 10 non-image files to `/api/ingest/image` (all 415), then user A's 11th gets 429 while B's 10 all stayed 415.
- `nginx/nginx.conf` -- add `map $http_authorization $lk_rate_key` in `http {}` with a regex capturing the JWT signature segment and `default $binary_remote_addr`; switch only `ai_gen` to `$lk_rate_key`; comment why and that the key is never logged.
- `nginx/locations.conf` -- append a commented template: anchored regex `ai_gen` location (`location ~ ^/api/x/[0-9a-f-]{36}/y$`), a generic-zone streaming form with `proxy_buffering off` for job/event/file routes, and `location /_files/ { internal; alias /data/files/; }`.

**Acceptance Criteria:**
- Given the AI/streaming routes listed in the story, when their decorators are inspected, then each uses `key_func=user_or_ip`.
- Given auth and share routes, when this lands, then they still use the default IP key.
- Given `nginx/`, when `nginx -t` runs in `nginx:alpine` with the files mounted at the Dockerfile's paths, then it passes.
- Given the full backend suite, when it runs, then the 26 baseline tests plus the new tests pass.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 27 findings — high 0, medium 6, low 12, false 9, maybe-false 0
- findings:
  - `[medium]` `[patch]` (edge) A new random three-segment Bearer on each request gets a fresh ai_gen bucket, removing the old per-IP ceiling — fixed: added `ai_gen_ip` per-IP zone (60r/m), applied with burst=20 next to every ai_gen limit_req and in the template.
  - `[low]` `[patch]` (edge) The nginx comment says slowapi falls back to IP for forged bearers, but get_current_user 401s before the slowapi wrapper counts them — fixed: comment corrected to point at ai_gen_ip.
  - `[low]` `[reject]` (edge) Trailing whitespace or a tab separator parses differently in nginx and the app — nginx trims trailing header whitespace, and the frontend always sends `Bearer <jwt>`. Fixing it would mean adding regex branches for a case no real client sends.
  - `[low]` `[reject]` (edge) The fixed-window minute boundary could flake the integration test — its ~22 requests take milliseconds, so the odds are tiny. A fix would need time-freezing infrastructure.
  - `[medium]` `[defer]` (edge) quests/npcs/campaigns LLM routes have no limit — they predate this story and are outside its enumerated route list. Deferred.
  - `[low]` `[defer]` (edge) The sources upload keeps the IP key — not in the story's list. Grouped into the deferred "other LLM routes" item.
  - `[medium]` `[defer]` (blind) Three AI routes are missed — same as above. Deferred.
  - `[medium]` `[patch]` (blind) The nginx key is bypassable with random signatures — same root cause as the first finding. Patched with ai_gen_ip.
  - `[low]` `[reject]` (blind) One user on several tokens gets several nginx buckets — by design: the comment says nginx is per token, and slowapi per user caps them. Only a comment-wording change would apply.
  - `[medium]` `[defer]` (blind) slowapi in-memory storage is per worker (gunicorn -w 4) — pre-existing, not caused by this story. Deferred.
  - `[low]` `[reject]` (blind) App limits (20/min) and nginx (10r/m + burst) disagree — intentional: the app limit is the only control in dev compose (no nginx) and must not be stricter than the proxy. The value choice isn't a defect.
  - `[low]` `[patch]` (blind) The keep-IP test skips sources — fixed: `app.api.routes.sources.` added to the asserted prefixes.
  - `[false]` `[reject]` (blind) No guard catches an unlimited AI route — the routes in scope are asserted, and the claim reduces to the deferred out-of-list routes.
  - `[low]` `[patch]` (blind) The integration test doesn't show B's bucket filling separately — fixed: B's 11th request asserted 429.
  - `[low]` `[defer]` (blind) No automated nginx map check — no nginx harness exists (E0-QA owns EV-4). Verified by hand. Deferred.
  - `[low]` `[reject]` (blind) user_or_ip decodes the JWT twice, and `except Exception` hides config errors — a second HS256 decode is microseconds. A shared helper would add surface, and failure is a safe fallback to IP.
  - `[medium]` `[defer]` (verification-gap) nginx ai_gen keying has no automated check — pre-verified gap with disposition defer. Grouped with the nginx-check deferred item.
  - `[low]` `[patch]` (verification-gap) Limit values on the newly limited routes aren't asserted — fixed: the decorator test now checks (amount, 60s) per route (5 evaluate, 10 ingest, 20 others).
  - `[false]` `[reject]` (verification-gap other) Forged bearer floods are no longer bounded by nginx — the same claim as the first finding, already patched by ai_gen_ip. Counted here as a duplicate row.
  - `[false]` `[reject]` (intent) Only slowapi has behavioural evidence; nginx is untested — nginx -t passed on nginx:alpine and nginx:1.27-alpine, and a runtime map probe returned `SIG_123-x` / `ccc` for JWT bearers and the binary IP otherwise.
  - `[false]` `[reject]` (intent) nginx -t has no evidence — run and passed (see Verification).
  - `[low]` `[reject]` (intent) "Hash of the bearer" is the JWT signature segment, not a hash — the signature is HMAC-SHA256 over the token, and nginx core has no hash function. Documented in Design Notes.
  - `[false]` `[reject]` (intent) Only one route is exercised behaviourally — the AC asks for a test with two tokens on one client address, and the decorator test covers key_func and limit value on all 12 routes.
  - `[false]` `[reject]` (intent) New limits go beyond re-keying — AR-20/NFR-8 require every AI route to have a slowapi limit keyed user_or_ip, and the AC's "at the per-route limit" requires one to exist.
  - `[false]` `[reject]` (intent) sources isn't asserted — now asserted (patched above). Duplicate row.
  - `[false]` `[reject]` (intent) A revoked but unexpired token gets its own bucket — the story mandates "decoded without a DB call". It's only a bucket key; get_current_user still rejects the request.
  - `[false]` `[reject]` (intent) A forged bearer gets its own nginx bucket — duplicate of the first finding, already patched.

## Design Notes

nginx core has no hash function, so the JWT's third segment stands in: it is HMAC-SHA256 over header and payload, unique per token and short (43 chars). Keying per token rather than per user is fine at the proxy layer, as slowapi gives the exact per-user bucket behind it. A forged bearer gets its own nginx bucket but is rejected with 401 by the app, and slowapi falls back to IP for it.

```nginx
map $http_authorization $lk_rate_key {
    "~*^Bearer\s+[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.(?<lk_sig>[A-Za-z0-9_-]+)$" $lk_sig;
    default $binary_remote_addr;
}
```

## Verification

**Commands:**
- Backend suite on the desktop per builder brief (lane `e0plat8`) -- expected: all pass, 26 baseline + new.
- `docker run --rm --add-host backend:127.0.0.1 -v <run>/nginx/nginx.conf:/etc/nginx/nginx.conf:ro -v <run>/nginx/locations.conf:/etc/nginx/locations.conf:ro -v <run>/nginx/proxy_common.conf:/etc/nginx/proxy_common.conf:ro -v <run>/certs:/etc/nginx/certs:ro nginx:alpine nginx -t` -- expected: `syntax is ok` / `test is successful`.

## Auto Run Result

Status: done

**Summary:** `user_or_ip` added to `app/core/limiter.py`. Every story-listed AI/streaming route now has `@limiter.limit(..., key_func=user_or_ip)`: chat/ingest are re-keyed, and journals ×5, session-plans generate and settings test/evaluate get new limits (20/min; evaluate 5/min). nginx `ai_gen` now keys on `map $http_authorization $lk_rate_key` (JWT signature segment, IP fallback). A per-IP `ai_gen_ip` backstop (60r/m) was added after review. `locations.conf` has the commented template for regex, generic-streaming and `/_files/` internal blocks.

**Files changed:**
- `src/backend/app/core/limiter.py` -- `user_or_ip` key func; default key unchanged.
- `src/backend/app/api/routes/{chat,ingest}.py` -- key_func added to existing limits.
- `src/backend/app/api/routes/{journals,session_plans,settings}.py` -- `request: Request` and new user-keyed limits.
- `src/backend/tests/test_rate_limit.py` -- 11 tests: unit tests for user_or_ip, decorator key/limit checks, and two users on one IP.
- `nginx/nginx.conf` -- `$lk_rate_key` map, `ai_gen` re-keyed, `ai_gen_ip` backstop zone.
- `nginx/locations.conf` -- `ai_gen_ip` on every AI location, plus the commented template.

**Review:** 27 findings. 6 patch rows covering 5 entries (the ai_gen_ip backstop, the forged-bearer comment, and three test gaps) were applied. 6 defer rows were grouped into 3 deferred items (other LLM routes, per-worker slowapi storage, no nginx CI check). The remaining 15 were rejected with reasons in the triage log.

**Follow-up review recommendation:** false. Patched at entry verdict: 1 medium (ai_gen_ip backstop, with duplicates grouped) and 4 low. No high, and fewer than two medium.

**Verification:** backend suite on the desktop (lane e0plat8): 37 passed (26 baseline + 11 new), both before and after the patches. `nginx -t` passed on nginx:alpine and nginx:1.27-alpine, with only the pre-existing `listen ... http2` deprecation warning. A runtime map probe gave the signature segment for `Bearer a.b.SIG` and `bearer a.b.ccc`, and `$binary_remote_addr` for a two-segment or missing header.

**Residual risks:** see `deferred`. slowapi counters are per worker in prod. Tests read slowapi's private `limiter._route_limits`, which works on the pinned 0.1.9. The sprint-status sync was skipped per the builder brief, because the orchestrator updates it.

