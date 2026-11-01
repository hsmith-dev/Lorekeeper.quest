---
title: 'E0-LLM.1: Typed LLM errors and one LLM-config resolver'
type: 'refactor'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: []
deferred:
  - summary: >-
      A personal kobold config with no llm_api_url (model or key only) runs on the platform model but is never metered.
    evidence: |-
      llm_provider._openai_compat falls back to settings.kobold_url when cfg.api_url is None, while is_hosted_default compares cfg.api_url (None) to the real URL and returns False, so meter() skips billing. Pre-existing (same check before this story); is_hosted_default is declared unchanged by the story.
    location: >-
      src/backend/app/services/llm_provider.py:30
    severity: medium
  - summary: >-
      A personal kobold config whose llm_api_url equals the platform kobold_url is metered as hosted usage.
    evidence: |-
      is_hosted_default matches on provider+api_url only. Pre-existing behaviour, unchanged by the move to meter().
    location: >-
      src/backend/app/services/llm_provider.py:30
    severity: low
  - summary: >-
      In open-access mode a user who still has a Subscription row is metered against their quota.
    evidence: |-
      resolve_llm_config returns the default config in open access; meter() then calls record_hosted_usage, which only no-ops without a subscription row. Same as before this story.
    location: >-
      src/backend/app/services/llm_config_service.py
    severity: low
  - summary: >-
      resolve_llm_config can commit the caller's session when the AppConfig row is missing (get_app_config's defensive create).
    evidence: |-
      Pre-existing in the old deps code; matters once the E0-Jobs worker calls the resolver with a session holding other pending changes.
    location: >-
      src/backend/app/services/app_config_service.py:7
    severity: low
  - summary: >-
      llm_provider still raises HTTPException(503) for outages, so a Job checking isinstance(exc, errors.RETRYABLE) won't match a real outage without a wrapper.
    evidence: |-
      AD-8 keeps complete_messages/stream_messages behaviour; the E0-Jobs wrapper (E0-Jobs.3) or a later E0-LLM story must translate provider 503s (and raw httpx.ConnectError, which the provider does not catch) into LLMUnavailable.
    location: >-
      src/backend/app/services/llm_provider.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** LLM-config resolution (BYOK, open access, hosted quota, 402) lives inside the FastAPI dependency `deps.get_user_llm_config`, so a Job worker cannot reuse it, and there is no typed LLM error family; every route copies `if is_hosted_default(config): record_hosted_usage(...)`.

**Approach:** Move the resolution into `services/llm_config_service.resolve_llm_config(db, user)` raising `LLMConfigError`, keep `get_user_llm_config` as a thin 402 wrapper, add `app/core/errors.py` (the `LLMError` family, `llm_error_response`, `RETRYABLE`/`TERMINAL`) with a handler registered in `main.py`, and route all existing metering through `llm_config_service.meter`.

## Boundaries & Constraints

**Always:** Same resolution order and same `LLMConfig` values as today (including the `hosted_model_variant=="base"` swap in both open-access and hosted-subscriber branches). Same three 402 messages, each with `X-Gate-Reason: llm-config`. Keep the "why" comment style when moving code. Error bodies from the typed handler are `{"detail": <readable text>, "code": <code>}`.

**Never:** No change to `llm_provider.py` (`complete_messages`/`stream_messages` keep raising `HTTPException(503)` per AD-8; `is_hosted_default` unchanged). No gate, prompt budget, fake provider or `complete_structured` (later E0-LLM stories). No new dependencies. No edits to `sprint-status.yaml` or `epics.md`. No test opens a socket to `KOBOLD_URL`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Personal config | UserSettings with non-kobold provider, or any of key/url/model set | `LLMConfig` from UserSettings fields | none |
| Open access | no personal config, `AppConfig.open_access_mode=True` | `get_default_config()`; model = `kobold_base_model` if variant `base` | none |
| Hosted with quota | open access off, sub `plan=hosted`, active, quota left | default config (base swap as above) | none |
| Hosted, quota spent | as above, `tokens_used >= included` | raises `LLMConfigError` | wrapper -> 402 quota message, header |
| BYOK plan, no key | active sub `plan=byok` | raises `LLMConfigError` | 402 "your plan doesn't include" message |
| Nothing | no settings, no sub, gating on | raises `LLMConfigError` | 402 "subscribe" message |
| meter hosted | `is_hosted_default(cfg)` true | `record_hosted_usage(db, user, *texts)` once | none |
| meter BYOK | personal config | no call, no DB write | none |

</intent-contract>

## Code Map

- `src/backend/app/api/deps.py:152-260` -- `get_user_llm_config`: source of the logic to extract; becomes wrapper. Called as a dependency by journals/quests/npcs/campaigns/chat/session_plans/settings routes and directly at `journals.py:75` (`get_user_llm_config(user=user, db=db)`), so its signature stays.
- `src/backend/app/services/llm_provider.py:9,19,30` -- `LLMConfig`, `get_default_config`, `is_hosted_default` (read-only reuse).
- `src/backend/app/services/billing_service.py:405` -- `record_hosted_usage(db, user, *texts)` (read-only; no-op without a subscription row).
- `src/backend/app/services/app_config_service.py:25` -- `is_open_access(db)` (creates AppConfig row id=1 if missing).
- `src/backend/app/db/models/subscription.py:56-74` -- `is_active`, `has_quota_remaining`, `hosted_model_eligible`.
- `src/backend/app/main.py:52-54` -- exception-handler registration point (append the `LLMError` handler next to the RateLimitExceeded one).
- Metering call sites to convert: `routes/journals.py:53,87,248,274,294`, `routes/quests.py:148,174`, `routes/npcs.py:149`, `routes/campaigns.py:66`, `routes/session_plans.py:80`, `routes/chat.py:326`, `routes/settings.py:247`.
- `src/backend/tests/conftest.py` -- `db`, `client` fixtures (real Postgres); tests create rows directly.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/errors.py` -- create `LLMError(Exception)` (attrs `code`, `status_code`, `detail`, `headers`), `LLMConfigError(detail, reason="llm-config")` (code `llm_config`, 402, header `X-Gate-Reason: <reason>`), `LLMBusy` (`llm_busy`, 503), `LLMUnavailable` (`llm_unavailable`, 503), `StructuredOutputError(detail, attempts, errors)` (`ai_output_unusable`, 422), `PromptBudgetError` (`prompt_too_large`, 422); `llm_error_response(exc) -> JSONResponse`; async `llm_exception_handler(request, exc)`; `RETRYABLE = (LLMBusy, LLMUnavailable)`, `TERMINAL = (LLMConfigError, StructuredOutputError, PromptBudgetError)` -- typed errors per AD-8/AD-4.
- `src/backend/app/services/llm_config_service.py` -- create `resolve_llm_config(db, user)` (moved logic, raising `LLMConfigError` with today's messages) and `meter(db, user, config, *texts)` -- single resolver for routes and Jobs.
- `src/backend/app/api/deps.py` -- `get_user_llm_config` calls the resolver and maps `LLMConfigError` to `HTTPException(402, exc.detail, headers=exc.headers)` -- thin wrapper, body unchanged.
- `src/backend/app/main.py` -- `app.add_exception_handler(LLMError, llm_exception_handler)` -- one mapping everywhere.
- Route files listed in the Code Map -- replace each `if is_hosted_default(cfg): await billing_service.record_hosted_usage(...)` with `await llm_config_service.meter(db, user, cfg, ...)` (keep extra guards like `body.narrative is None`, `result.get("sample_size")`); drop now-unused imports -- metering through one helper.
- `src/backend/tests/test_llm_config_service.py` -- unit tests for the matrix, the deps wrapper 402 + header, `llm_error_response` statuses/bodies for each class (also via a throwaway route on a fresh FastAPI app with the handler), and `RETRYABLE`/`TERMINAL` membership.

**Acceptance Criteria:**
- Given the backend suite, when run on the desktop against `lorekeeper_test_e0llm1`, then all 26 baseline tests plus the new ones pass.
- Given the real desktop Ollama (`http://100.119.62.5:11434`, model `lorekeeper`), when a scratch script resolves a config through `resolve_llm_config` (open access) and calls `complete_messages`, then a reply comes back; and with a nonexistent model, the provider's 503 wrapped as `LLMUnavailable` renders through `llm_error_response` as 503 `{"code":"llm_unavailable"}`.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 20 findings — high 0, medium 4, low 12, false 4, maybe-false 0
- findings:
  - `[low]` `[defer]` (edge) Personal kobold config with api_url == platform URL is metered — pre-existing is_hosted_default semantics; deferred.
  - `[low]` `[defer]` (edge) Open access + existing Subscription row is metered — pre-existing; deferred.
  - `[low]` `[defer]` (edge) get_app_config's defensive create commits the caller's session — pre-existing; relevant to E0-Jobs; deferred.
  - `[low]` `[reject]` (edge) StructuredOutputError loses attempts/errors when pickled — classification happens in-process; RQ stores tracebacks as text; fix adds a `__reduce__` for an unshown path.
  - `[medium]` `[patch]` (verification-gap) No route-level test proves converted call sites meter — added `test_generate_draft_route_meters_hosted_only` (hosted increments, BYOK unchanged) through `/api/journals/generate-draft`.
  - `[medium]` `[defer]` (blind) kobold personal config with model/key only uses platform URL unmetered — pre-existing billing hole in is_hosted_default (story keeps it unchanged); deferred.
  - `[low]` `[patch]` (blind) errors.py docstring claims one body shape everywhere though the deps 402 keeps legacy `{"detail"}` — docstring sentence added.
  - `[low]` `[patch]` (blind) deps re-raise drops the exception chain — added `from exc`.
  - `[low]` `[patch]` (blind) Stale docstrings in billing_service/app_config_service/llm_provider — billing_service and app_config_service updated; llm_provider left untouched (story: unchanged).
  - `[low]` `[patch]` (blind) meter() "once per completion" and call-site comment inaccurate — wording fixed.
  - `[low]` `[reject]` (blind) evaluate_model builds the "x"*n string for BYOK too — negligible cost (a few KB per evaluation).
  - `[medium]` `[defer]` (blind) Typed errors unused; provider 503s won't match RETRYABLE — AD-8 keeps provider behaviour; translation belongs to E0-Jobs.3/later E0-LLM; deferred.
  - `[low]` `[reject]` (blind) No Retry-After on 503s — adds public surface the story does not ask for.
  - `[medium]` `[patch]` (blind) No tests for the changed call sites — same root as the verification-gap finding; covered by the same route test.
  - `[false]` `[reject]` (blind) test_meter_hosted_updates_quota leaves rows in the shared DB — conftest's session fixture drops all tables at teardown, and the lane DB is per-worktree.
  - `[low]` `[patch]` (blind) Two assertions in test_meter_byok_skips_billing cannot fail — deleted.
  - `[low]` `[reject]` (blind) Duplicated base-variant swap block — moved verbatim from deps.py by design (story: extract code, keep comments).
  - `[false]` `[reject]` (intent) deps 402 bypasses the typed handler — the story explicitly requires the wrapper to map LLMConfigError to 402 with the header and existing tests unchanged.
  - `[false]` `[reject]` (intent) Worker classification exists only as exported tuples — the story says the mapping "is exported as errors.RETRYABLE and errors.TERMINAL for the E0-Jobs wrapper to import"; no worker exists yet.
  - `[false]` `[reject]` (intent) Resolver not called by any Job — no Job system exists yet (E0-Jobs.3 consumes it); deps uses it.

## Design Notes

`PromptBudgetError` is in `TERMINAL`: retrying the same prompt cannot make it fit. Only the four named classes are in the story text; this is the only additive choice. `StructuredOutputError.errors` holds the last validation errors as a list (JSON-safe); the response body stays `{"detail","code"}` so validation internals are not leaked to clients.

## Verification

**Commands:**
- Desktop backend tests (brief's docker command, lane `e0llm1`) -- expected: 0 failures, >= 26 + new tests passing.
- `python -m pyflakes`-style import check is covered by the test import of every converted route module (app import in conftest).

**Manual checks (if no CLI):**
- Scratch script against real Ollama as in the second AC; record output in the Auto Run Result.

## Auto Run Result

Status: done

**Summary:** Added the typed `LLMError` family and its single HTTP mapping (`app/core/errors.py`, handler registered in `main.py`), moved LLM-config resolution into `llm_config_service.resolve_llm_config` (deps wrapper keeps the legacy 402 + `X-Gate-Reason: llm-config`), and routed all 13 hosted-metering call sites through `llm_config_service.meter`.

**Files changed:**
- `src/backend/app/core/errors.py` -- new: LLMError family, `llm_error_response`, `llm_exception_handler`, `RETRYABLE`/`TERMINAL`.
- `src/backend/app/services/llm_config_service.py` -- new: `resolve_llm_config`, `meter`.
- `src/backend/app/api/deps.py` -- `get_user_llm_config` is a thin 402 wrapper.
- `src/backend/app/main.py` -- registers the LLMError handler.
- `src/backend/app/api/routes/{journals,quests,npcs,campaigns,session_plans,chat,settings}.py` -- metering via `meter()`.
- `src/backend/app/services/{billing_service,app_config_service}.py` -- docstrings only.
- `src/backend/tests/test_llm_config_service.py` -- 35 new tests.
- `_bmad-output/implementation-artifacts/epic-6-context.md` -- compiled epic context.

**Review:** 1 pass. Patched 6 entries (2 medium sharing one root cause: route-level metering test; 5 low: docstrings, `from exc`, comment wording, dead assertions). Deferred 5 (pre-existing metering/URL semantics in `is_hosted_default`, open-access metering with a sub row, AppConfig defensive commit, provider 503 -> `LLMUnavailable` translation for Jobs). Rejected: pickling of StructuredOutputError (in-process classification), BYOK string build in evaluate (negligible), Retry-After (new surface), duplicated base-swap (verbatim move), test DB residue (false: tables dropped at teardown), three intent-audit divergences (false: story text requires them). Follow-up review: false (no high patched; one medium root cause).

**Verification:**
- Desktop backend suite against `lorekeeper_test_e0llm1`: 61 passed (26 baseline + 35 new), 0 failed.
- Real Ollama (`http://100.119.62.5:11434`, model `lorekeeper`, scratch script, not committed): `resolve_llm_config` in open-access mode -> `kobold http://100.119.62.5:11434 lorekeeper`; `complete_messages` replied `'OK.'`. With model `no-such-model-e0llm1`, the provider raised 503 (Ollama 404); wrapped as `LLMUnavailable` it is retryable and `llm_error_response` renders 503 `{"code": "llm_unavailable", "detail": "AI model unavailable: ... 404 Not Found ..."}`. No models created or deleted.

**Residual risks:** The provider still raises `HTTPException(503)` (and lets `httpx.ConnectError` through unwrapped), so nothing yet produces `LLMUnavailable` in production; E0-Jobs.3 / later E0-LLM stories must translate. Sprint-status sync skipped per the orchestrator's brief.
