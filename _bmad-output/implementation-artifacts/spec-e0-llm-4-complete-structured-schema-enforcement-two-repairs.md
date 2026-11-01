---
title: 'E0-LLM.4: complete_structured with schema enforcement and at most two repairs'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'fc1e1c56bab6e0e805fdde4ff4ad87260eb9d39c'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred:
  - summary: >-
      A reply cut off at max_tokens (done_reason/finish_reason "length") is repaired under the same limit, so both repairs are likely wasted.
    evidence: |-
      complete_structured treats truncated JSON as ordinary invalid output; the repair turn keeps the same num_predict/max_tokens. A distinct outcome needs a policy (raise the limit, or fail fast), and E0-LLM.6 sizes per-task reserves from SPIKE-6.
    location: >-
      src/backend/app/services/llm_provider.py (complete_structured loop, _send_ollama/_send_openai_schema)
    severity: medium
  - summary: >-
      No measured FR-3 validity rates or docs/BENCHMARKS.md row yet.
    evidence: |-
      Needs the desktop Ollama (no-desktop mode); tests/integration/test_llm_structured_ollama.py is ready to run.
    location: >-
      docs/BENCHMARKS.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** AI features (F1 extraction first, then continuity and rolling recaps) need model output that matches a pydantic schema. Today every feature would parse JSON by hand, and backends differ: Ollama can constrain output with `format`, OpenAI-compatible servers with `response_format`, and Anthropic/Gemini only by prompting.

**Approach:** Add `llm_provider.complete_structured(messages, schema, config, *, task, timeout, gate_class, max_tokens)`. It picks the enforcement per backend, validates every reply with `schema.model_validate_json`, runs at most two repair turns that quote the validation errors, and otherwise raises `StructuredOutputError` (`ai_output_unusable`). Add `app/schemas/llm/__init__.py` with `FlatModel` and a flatness checker, plus a CI lint test, and an opt-in `ollama` integration test.

## Boundaries & Constraints

**Always:**
- Backend choice: provider `kobold` → `detect_backend(cfg.api_url)`. `ollama` → `POST {base}/api/chat` with `format=<flat schema>`, `stream=false`, `options={"temperature":0,"num_predict":max_tokens}`, model `model_for(task, cfg)`. `openai_compat` (KoboldCpp) and providers `openai`/`custom` → `POST {base}/v1/chat/completions` with `response_format={"type":"json_schema","json_schema":{"name":<task>,"schema":...,"strict":true}}`, `temperature=0`, `stream=false`. On a 4xx reply, retry that same attempt once without `response_format` (prompted JSON), and stay prompted for the rest of the call. Every other provider (`anthropic`, `gemini`, anything else) → prompted JSON through the existing `_anthropic`/`_gemini`/`_openai_compat` senders at temperature 0.
- The schema (`schema_prompt(schema)`: the flat JSON schema plus "reply with only one JSON object") is appended to the final user turn of a copy of the caller's messages, or added as a new user turn if the last message is not a user turn. The caller's list is never mutated.
- Shared validation on every path: strip one surrounding markdown code fence, or else take the text from the first `{` to the last `}`, then `schema.model_validate_json`. Malformed JSON, missing fields, extra keys and pydantic validators (the place for "semantically empty" rules) all count as invalid.
- Repair: at most 2. Each repair prompt = the schema-bearing messages + the last raw output as an assistant turn + a user turn listing the validation errors (`loc: msg` lines, truncated to 1,000 characters) and asking for corrected JSON only. Not cumulative: only the latest bad output is echoed, which keeps the prompt bounded on a 4096 context. After attempt 3 fails: `StructuredOutputError(attempts=3, errors=[{loc,msg,type}...])`.
- Gate: each attempt (the first call and each repair) acquires and releases its own slot through `gated(cfg, cls)`, as the story says ("each attempt acquires `llm_slot` separately with the caller's gate class"). `cls` is resolved once per call (`gate_class`, else `llm_gate.current_class`), so every attempt uses the same class. The 4xx prompted retry belongs to its attempt's slot. Validation and repair-prompt building run with no slot held. If the caller already holds a slot, the gate's reentrancy reuses it. `detect_backend` runs before any slot is taken. BYOK never touches the gate.
- Budget (platform LLM only): if the first attempt's messages exceed `prompt_budget.window_tokens(task)` (`structured` when `task` isn't in `TASK_POLICIES`), raise `PromptBudgetError` before any request. A repair prompt that would exceed it shortens the echoed output, or drops it, rather than letting Ollama front-truncate.
- Each attempt logs one JSON line `{"event":"structured_attempt","task","attempt","valid","backend","ms"}` (never message text). `llm_provider.structured_stats[task]` counts `first_try_valid`, `valid_after_repair`, `failed`.
- Backend failures (transport error, timeout, 5xx, a 4xx on the prompted path, an empty Ollama body) raise `LLMUnavailable`. A missing BYOK key (the senders' 400) raises `LLMConfigError`. Neither counts as an attempt, and neither triggers a repair.
- `FlatModel(BaseModel)` uses `extra="forbid"`. Its `model_json_schema()` inlines nested `$defs`/`$ref`, so nested FlatModels such as `entities: list[Entity]` stay flat. `flatness_problems(json_schema) -> list[str]` reports `$ref`, `$defs`, `anyOf`, `oneOf`, `allOf`, an object without `additionalProperties: false`, and a property missing from `required` (a field with a default, which OpenAI strict mode rejects). `complete_structured` raises `ValueError` on a non-flat schema before any request.

**Never:** No change to `llm_gate.py` semantics, to `complete_messages`/`stream_messages`/`detect_backend` behaviour, or to `errors.py`. No new dependency (pydantic only, no jsonschema). No migration of existing callers. No test opens a socket to `KOBOLD_URL`. No feature schemas (feature epics add `app/schemas/llm/<feature>.py`). No edits to sibling-wave files (stt/transcription/compose, CI gate scripts, demo seed/eval scaffold, frontend), `sprint-status.yaml`, `epics.md` or `desktop-verification-queue.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid first try | Ollama returns valid JSON | model instance; 1 request; stats first_try_valid+1 | none |
| Repair on turn 1 | invalid, valid | instance; request 2 carries raw output + errors | none |
| Repair on turn 2 | invalid, invalid, valid | instance; 3 requests; valid_after_repair+1 | none |
| Exhausted | invalid ×3 | no DB write in sample handler; failed+1 | `StructuredOutputError(attempts=3)` |
| Malformed JSON | `{"entities": [` | repaired like any invalid output | as above |
| Semantically empty | `{"entities":[]}` against a validator rejecting empty | repaired | as above |
| Fenced / chatty | ```` ```json {...}``` ```` or `Here: {...}` | parsed | none |
| KoboldCpp 4xx | response_format → 400 | same attempt retried prompted; repairs stay prompted | none |
| BYOK openai | provider openai | response_format strict; gate untouched | none |
| Anthropic/Gemini | provider anthropic/gemini | prompted, schema in final user turn | none |
| Backend down | 5xx / transport error | — | `LLMUnavailable` |
| Gate | platform cfg, N attempts | N acquire/release pairs in one class; a `live_recap` queued during attempt 1 is served before the repair | `LLMBusy` on any attempt (including a repair) with no further request, no stat, no leftover waiter |
| Too big | platform prompt > window | no request | `PromptBudgetError` |
| Non-flat schema | Optional field / nested non-forbid model | no request | `ValueError` |

</intent-contract>

## Code Map

- `src/backend/app/services/llm_provider.py` -- add `complete_structured` and helpers after `complete_messages`. Reuse `_client` (MockTransport hook), `gated`, `uses_platform_llm`, `model_for`, `_openai_compat_target`, `detect_backend`/`BACKEND_OLLAMA`, `_anthropic`/`_gemini` (they raise `HTTPException` 400/503, to be wrapped as typed errors). Do not edit the existing functions.
- `src/backend/app/core/errors.py` -- read-only: `StructuredOutputError(detail, attempts, errors)` code `ai_output_unusable` 422; `LLMUnavailable`, `LLMConfigError`, `PromptBudgetError`.
- `src/backend/app/core/llm_gate.py` -- read-only. `llm_slot` is reentrant; `current_class` is the default class.
- `src/backend/app/services/prompt_budget.py` -- read-only: `TASK_POLICIES`, `window_tokens`, `estimate_messages`, `estimate_tokens`.
- `src/backend/tests/test_llm_provider_gate.py:41-105` -- patterns to copy: `Backend` MockTransport handler, `RecordingGate` on fakeredis, the `no_gate` fixture.
- `src/backend/tests/test_backend_detection.py` -- reset the detection cache with `monkeypatch.setattr(llm_provider, "_backend_cache", {})`.
- `src/backend/tests/conftest.py:139` -- `db` fixture (real Postgres in CI). `app/db/models/promo_code.py` `PromoCode` is a simple row for the no-write test.
- `src/backend/pytest.ini` -- append the `ollama` marker.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/llm/__init__.py` -- create `FlatModel`, `flat_json_schema`, `flatness_problems`.
- `src/backend/app/services/llm_provider.py` -- add `structured_stats`, `schema_prompt`, `complete_structured` and private send/parse/repair helpers; update the module docstring.
- `src/backend/pytest.ini` -- register the `ollama` marker.
- `src/backend/tests/test_llm_structured.py` -- every matrix row (MockTransport and fakeredis gate), log line and stats, and the sample-handler no-DB-write test.
- `src/backend/tests/test_llm_schemas_flat.py` -- import every module under `app/schemas/llm/` and lint each FlatModel; negative cases (Optional, a default, a nested non-forbid model, recursion) and a positive nested case.
- `src/backend/tests/integration/__init__.py`, `src/backend/tests/integration/test_llm_structured_ollama.py` -- `@pytest.mark.ollama`, skipped without `OLLAMA_TEST_URL`. 50 calls over 3 flat schemas (an E1-shaped entity list `entities[{name,type,status}]` + `relationships[{source,target,kind}]`, a recap update, a yes/no verdict with a quote). Model from `OLLAMA_TEST_MODEL` (default `lorekeeper`). Optional `OLLAMA_TEST_PARAGRAPHS` (a JSON list of strings). Prints first-try, after-repair and failed rates plus latency; asserts ≥ 95% valid within the attempts.

**Acceptance Criteria:**
- Given the PR's backend CI, when it runs, then every existing test and the new tests pass, and the `ollama` suite is skipped.
- Given the licence workflow, when it runs, then it passes unchanged (no new dependency).

## Spec Change Log

### 2026-11-01 — Coordinator correction: per-attempt gate slot
- **Trigger:** the coordinator retracted the brief's "hold ONE slot across the first call and its repair turns" and directed the story's per-attempt acquire.
- **Amended:**
  - The intent-contract Gate bullet and Gate matrix row.
  - Design Notes.
  - The code: each attempt has its own `gated(cfg, cls)`, with the class resolved once per call.
  - Tests:
    - N acquire/release pairs.
    - A `live_recap` served between attempts (fakeredis).
    - `LLMBusy` on a repair attempt with no partial state.
- **Known-bad state avoided:** a structured call holding the only local-LLM slot through up to 3 generations while a Rolling Recap waits.
- **KEEP:**
  - The 4xx prompted retry stays inside its attempt's slot.
  - `detect_backend` runs before any slot.
  - The caller-held slot is reused by reentrancy.
  - Everything else in the review-patched behaviour is unchanged.

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 34 findings — high 0, medium 5, low 25, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` (verification-gap) Repair-turn PromptBudgetError path untested — added `test_repair_over_window_is_unusable` (grouped with the edge row on the same path).
  - `[low]` `[patch]` (verification-gap) Strict-path null/"" content untested — `kobold-null`/`kobold-empty` cases added to `test_backend_down_is_unavailable`.
  - `[low]` `[patch]` (verification-gap) json_schema `name` sanitisation untested — added `test_json_schema_name_sanitised` (space/dot and 72-char task).
  - `[low]` `[reject]` (verification-gap other) Every 4xx triggers the prompted retry, including 401/429 — the story AC says "on a 4xx response it retries once as prompted JSON". Narrowing it would depart from the story, and the cost is one extra request on a call that is failing anyway.
  - `[low]` `[patch]` (verification-gap other) The docstring claims LLMConfigError for a missing BYOK key, but a key-less openai call gets LLMUnavailable — docstring reworded (anthropic/gemini only).
  - `[low]` `[reject]` (blind) 4xx fallback too broad — same as the row above.
  - `[low]` `[reject]` (blind) The format rejection isn't cached per URL — adds process state for one cheap 4xx per call on servers without json_schema. No such deployment shown.
  - `[low]` `[reject]` (blind) Ollama path has no prompted fallback — the desktop runs Ollama 0.40.3 (schema `format` supported since 0.5), and the runtime flatness check stops the schemas Ollama could reject. A 4xx there means a real config problem (for example a missing model), so LLMUnavailable is right.
  - `[low]` `[reject]` (blind) A bad BYOK key surfaces as LLMUnavailable, which is retryable — this is the existing senders' mapping (`_anthropic`/`_gemini`/`_openai_compat` raise 503), shared with complete_messages. Changing it means editing the senders or errors.py, which is out of this story.
  - `[medium]` `[patch]` (blind) An explicit max_tokens isn't reflected in the budget window — the window is now `ollama_context_length - max(mt, reserved_output)`; added `test_large_max_tokens_shrinks_window`.
  - `[medium]` `[defer]` (blind) Truncated replies (finish/done_reason "length") are repaired under the same limit and likely fail again — real, but a distinct outcome needs a new error branch and policy (raise max_tokens? fail fast?). E0-LLM.6 sizes reserves from SPIKE-6.
  - `[low]` `[patch]` (blind) Validation errors are never logged — invalid attempts' log lines now carry `errors: [{loc,type}]` (max 10, no msg or input); the log test is updated and `test_attempt_log_caps_errors` added.
  - `[low]` `[reject]` (blind) Backend failures mid-loop leave no attempt line or stat — stats measure output validity (FR-3), and LLMUnavailable propagates to the caller's error handling. A fourth counter isn't in the story.
  - `[false]` `[reject]` (blind) structured_stats is unreachable and unbounded — the story defines it as an in-process counter that eval scripts read (EV-1 runs in-process). Keys are the code-defined task names.
  - `[low]` `[patch]` (blind) The flatness lint doesn't report prefixItems — reported now; a tuple negative case was added. Constraint keywords (pattern/minLength) are rejected: Ollama ignores them and pydantic still validates, so nothing is silently accepted.
  - `[low]` `[reject]` (blind) The 50-call integration run has 15 distinct prompts — this is an opt-in desktop run, and `OLLAMA_TEST_PARAGRAPHS` takes the ~20 demo paragraphs once E0-QA.12 lands (listed under desktop verification).
  - `[false]` `[reject]` (blind) The no-write test can't fail — it would fail if complete_structured returned an instance (partial or default) on unusable output, because the handler would then write. That is exactly the regression it guards.
  - `[low]` `[patch]` (blind) test_budget_uses_task_policy depends on "extraction" being absent — it now uses `zz_unknown_task`.
  - `[low]` `[reject]` (blind) Missing tests for timeout, BYOK 4xx, recursive schema at runtime and multimodal content — TimeoutException is an httpx.HTTPError, which the tested branches already catch. The recursive schema goes through the same `_checked_schema` the lint tests exercise, and no caller sends list content.
  - `[false]` `[reject]` (blind) The spec isn't in the diff — the spec was deliberately kept out of the review diff (the edge layer gets it separately).
  - `[low]` `[reject]` (blind) The schema is recomputed per call — microseconds against a multi-second LLM call; caching adds state.
  - `[low]` `[reject]` (edge) 401/403/429 trigger the prompted retry — same as the verification-gap row.
  - `[low]` `[reject]` (edge) No Ollama 4xx fallback — same as the blind row.
  - `[low]` `[patch]` (edge) Prompted null content raises a raw AttributeError — `_prompted_sender` maps AttributeError/TypeError to LLMUnavailable; added `test_prompted_null_content_is_unavailable`.
  - `[low]` `[reject]` (edge) A validator raising TypeError crashes instead of repairing — a schema-author bug that fails loudly. Pydantic's own contract is ValueError/AssertionError.
  - `[medium]` `[patch]` (edge) A repair prompt that doesn't fit raised PromptBudgetError after requests had gone out, with no stat — it now counts `failed` and raises StructuredOutputError(attempts=attempts made). Test added (grouped with the first row).
  - `[medium]` `[patch]` (edge) A max_tokens above the reserve overflows the context — same fix as the blind row.
  - `[low]` `[reject]` (edge) One slot can be held for up to ~4× timeout — `timeout` is per request by design (an attempt on the CPU box can take tens of seconds), and holder renewal keeps the slot valid. Since the coordinator's correction, a slot is held per attempt, so this concern no longer applies. Job deadlines belong to E0-Jobs (current_deadline).
  - `[low]` `[reject]` (edge) A `{` in prose before the object breaks extraction — only on the prompted path, and it costs one repair. A raw_decode scan adds branching for a pattern not seen with temperature-0 JSON prompts.
  - `[low]` `[patch]` (edge, claim) The integration test could report a model it doesn't send — it now prints `model_for(task, cfg)` and skips with a reason when that differs from OLLAMA_TEST_MODEL.
  - `[low]` `[reject]` (intent) An empty or whitespace reply is LLMUnavailable, not a repairable attempt — the spec settles this (empty Ollama body → LLMUnavailable). "Semantically empty" means schema-valid content, which is covered by validators and the no-defaults rule.
  - `[low]` `[defer]` (intent) No BENCHMARKS.md FR-3 row and no measured rates — this needs the desktop Ollama; listed under Needs desktop verification.
  - `[low]` `[reject]` (intent) The lint is vacuous until feature schemas exist — it imports whatever lands in app/schemas/llm/, so E1's first schema module is checked automatically, and the checker itself is tested on positive and negative fixtures.
  - `[false]` `[reject]` (intent) A per-attempt gate (story) vs one slot (diff) — at review time the intent said ONE slot. Superseded by the coordinator's correction (see Spec Change Log): the code now acquires per attempt, as the story says.

## Design Notes

- **A gate slot per attempt.** This follows story E0-LLM.4 ("each attempt acquires `llm_slot` separately with the caller's gate class") and E0-LLM.2's technical note ("Each call through `complete_structured` acquires separately, so a `live_recap` call can slip in between repair turns").
  - Live-session latency is a PRD priority, and it outranks the warm prompt cache a held slot would keep for the repair.
  - A repair that loses the slot to a higher-priority call pays full prompt evaluation again. That cost is accepted.
- **No defaults in flat schemas.** If fields could have defaults, `{}` would validate as an empty result: a silent "nothing extracted". Requiring every property (empty string or empty list meaning "none") makes `{}` invalid, so it gets repaired. This is also what OpenAI strict mode needs.
- Semantic rules ("at least one entity", non-blank names) belong in the schema's pydantic validators. They raise `ValidationError`, so they get the same repair turns.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed .py>` -- expected: no output.
- Scratch venv (pydantic, httpx, fakeredis[lua], pytest-asyncio) running the new unit tests with conftest's DB fixture bypassed -- expected: pass.
- Draft PR, then `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.

**Needs desktop verification:** see the Auto Run Result.

## Auto Run Result

Status: done

**Summary:**
- `llm_provider.complete_structured(messages, schema, config, *, task, timeout, gate_class, max_tokens)` picks how to enforce the schema from the backend:
  - Ollama (`detect_backend`): `/api/chat` with `format=<flat schema>`, temperature 0, `stream=false`, model from `model_for`.
  - KoboldCpp, openai and custom: strict `response_format` json_schema. On a 4xx the attempt is retried once as prompted JSON, and the call stays prompted after that.
  - anthropic, gemini and anything else: prompted JSON.
- The schema is restated in the final user turn on every path.
- All paths share one validation step, `model_validate_json`, after a code fence or chatter around the object is stripped.
- At most 2 repairs. Each echoes the latest bad output and the errors (cut to 1,000 characters). After that it raises `StructuredOutputError` (`ai_output_unusable`, `attempts=3`).
- Each attempt acquires and releases its own gate slot, in one class per call, so a `live_recap` can run between repairs. This follows the story; see the Spec Change Log for the coordinator's correction. BYOK calls bypass the gate.
- Budget checks:
  - A platform prompt over `ctx - max(max_tokens, reserve)` raises `PromptBudgetError` before any request is sent.
  - A repair prompt that wouldn't fit is cut down first. If it still can't fit, the call ends with `StructuredOutputError`.
- Each attempt logs a JSON line `{task, attempt, valid, backend, ms[, errors(loc,type)]}`, and `structured_stats[task]` counts outcomes.
- `app/schemas/llm`: `FlatModel` (`extra="forbid"`, nested models inlined) and `flatness_problems`, which reports `$ref`, `$defs`, `anyOf`, `oneOf`, `allOf`, `prefixItems`, a missing `additionalProperties:false`, and fields with defaults. The same check runs at runtime and raises `ValueError` before any request.

**Files changed:**
- `src/backend/app/services/llm_provider.py` -- `complete_structured`, `schema_prompt`, `structured_stats` and private senders/helpers. No existing function changed.
- `src/backend/app/schemas/llm/__init__.py` -- new: `FlatModel`, `inline_refs`, `flat_json_schema`, `flatness_problems`.
- `src/backend/pytest.ini` -- registers the `ollama` marker.
- `src/backend/tests/test_llm_structured.py` -- every matrix row, the log line and stats, gate/slot behaviour, and the sample handler that writes nothing (Postgres).
- `src/backend/tests/test_llm_schemas_flat.py` -- lints every module under `app/schemas/llm/`, plus positive and negative fixtures.
- `src/backend/tests/integration/__init__.py`, `src/backend/tests/integration/test_llm_structured_ollama.py` -- the opt-in 50-call desktop run.

**Review:** 1 pass, 34 findings (high 0, medium 5, low 25, false 4).
- **Patched, 11 rows:**
  - A repair prompt that won't fit now gives `StructuredOutputError` and a `failed` stat (medium, two rows).
  - `max_tokens` shrinks the window (medium, two rows).
  - The prompted sender's null content becomes `LLMUnavailable`.
  - Invalid attempts log error loc/type.
  - The lint reports `prefixItems`.
  - The docstring now says which provider gives which error class.
  - Tests for strict-path null and empty content, and for sanitising the `json_schema` name.
  - The budget test uses an unknown task name.
  - The integration test reports the model it actually sent.
- **Deferred:**
  - Truncated (`length`) replies get repaired under the same limit. Medium, for E0-LLM.6.
  - The BENCHMARKS FR-3 row needs the desktop.
- **Rejected:**
  - Narrowing the 4xx fallback (the story says 4xx).
  - A per-URL fallback cache.
  - An Ollama 4xx fallback (Ollama 0.40.3 supports schema format, and the flatness check runs first).
  - The BYOK 401 to `LLMUnavailable` mapping (existing senders, shared with `complete_messages`).
  - An attempt line for backend failures.
  - Bounding the stats dict (false).
  - Constraint keywords in the lint.
  - The integration run's distinct-input count (`OLLAMA_TEST_PARAGRAPHS` covers it).
  - "The no-write test can't fail" (false).
  - Extra timeout and recursive-schema tests.
  - The spec missing from the diff (false).
  - Caching the schema.
  - A validator raising `TypeError`.
  - Slot hold time (timeout is per request).
  - A `{` in prose before the object.
  - An empty reply as `LLMUnavailable` (as the spec says).
  - The lint being vacuous with no feature schemas yet.
  - Per-attempt gate vs one slot (false at review time; later superseded by the coordinator's correction to per-attempt).

**Follow-up review:** true. Two medium entries were patched.
- The unverified risk is the repair-prompt trimming and the window maths against the real tokenizer.
- The estimate is uncalibrated until E0-LLM.6. A repair prompt that is underestimated could still be front-truncated by Ollama.

**Verification:**
- `py_compile` is clean.
- Scratch venv with `--noconftest`: new tests plus the gate, detection and budget suites, 84 passed and 2 skipped on the final patch run. The earlier full set was 191 passed.
- PR #32 CI is all green. The backend `test` job ran 402 tests, all passed, with 2 skipped: the Ollama suite and the empty-package lint case. The DB-backed sample-handler test passed. The licence, image-licence, database, static and build jobs passed.

**Needs desktop verification:**
- **Real structured extraction on `lorekeeper`:**
  ```
  docker run --rm --network host -v $PWD:/app -w /app -e TEST_DATABASE_URL=... -e DATABASE_URL=... -e SECRET_KEY=x \
    -e OLLAMA_TEST_URL=http://100.119.62.5:11434 -e OLLAMA_TEST_MODEL=lorekeeper \
    lorekeeper-backend-test bash -c "pip install -q -r requirements-dev.txt; python -m pytest -m ollama -s tests/integration/test_llm_structured_ollama.py"
  ```
  - It reports first-try, after-repair and failed rates plus latency over 50 calls on 3 flat schemas. The E1-shaped one is `entities[{name,type,status}]` plus `relationships[{source,target,kind}]`. It expects at least 95% valid.
  - Once E0-QA.12 lands, write ~20 paragraphs from `demo_campaign.json` to a JSON list of strings and pass `OLLAMA_TEST_PARAGRAPHS=<file>`.
  - Record the rates, the Ollama version and latency in `docs/BENCHMARKS.md` as an FR-3 row.
- **The same run with `OLLAMA_TEST_MODEL=lorekeeper-base`.** Keep `KOBOLD_URL` different from `OLLAMA_TEST_URL`, or set `LOCAL_LLM_MODEL`. Otherwise `model_for` sends the platform model and the test skips.
- **Ollama silently ignoring schema features.** Check the logs for `structured_attempt` lines with `valid:false`, and look at which error `loc` values recur.

**Residual risks:**
- A repair that loses its slot to a higher-priority call re-evaluates the whole prompt (cold KV cache). E0-LLM.6's gate-contention measurement shows the cost.
- Token estimates are uncalibrated.
- Sprint-status sync was skipped, per the orchestrator brief.
