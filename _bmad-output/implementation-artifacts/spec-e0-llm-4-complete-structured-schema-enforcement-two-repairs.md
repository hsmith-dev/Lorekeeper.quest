---
title: 'E0-LLM.4: complete_structured with schema enforcement and at most two repairs'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: 'fc1e1c56bab6e0e805fdde4ff4ad87260eb9d39c'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred: []
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
- Gate: ONE slot (`gated(cfg, gate_class)`, default `llm_gate.current_class`) is held across the first call, the 4xx fallback and every repair turn, released on success or error. `detect_backend` runs before the slot is taken. BYOK never touches the gate. (This is the orchestrator's instruction and overrides the story's "each attempt acquires separately"; see Design Notes.)
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
| Gate | platform cfg | one acquire for all attempts, chosen class, released after success and after failure | `LLMBusy` if no slot, no request sent |
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

## Review Triage Log

## Design Notes

- **One slot vs per-attempt.** The story (and E0-LLM.2's note) says each attempt acquires separately, so a `live_recap` can slip between repairs. The orchestrator for this build directed one slot for the first call and its repairs. A repair turn shares its whole prefix with the previous request, so on `OLLAMA_NUM_PARALLEL=1` keeping the slot keeps Ollama's prompt cache warm; another call in between would evict it and make the repair pay full prompt evaluation again. Worst-case hold is 3 generations. E0-LLM.6's gate-contention measurement can revisit this.
- **No defaults in flat schemas.** If fields could have defaults, `{}` would validate as an empty result: a silent "nothing extracted". Requiring every property (empty string or empty list meaning "none") makes `{}` invalid, so it gets repaired. This is also what OpenAI strict mode needs.
- Semantic rules ("at least one entity", non-blank names) belong in the schema's pydantic validators. They raise `ValidationError`, so they get the same repair turns.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed .py>` -- expected: no output.
- Scratch venv (pydantic, httpx, fakeredis[lua], pytest-asyncio) running the new unit tests with conftest's DB fixture bypassed -- expected: pass.
- Draft PR, then `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.

**Needs desktop verification:** see the Auto Run Result.
