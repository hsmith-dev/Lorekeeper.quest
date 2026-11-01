---
title: 'E0-LLM.3: Backend detection and prompt budgets'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '2b74d89798a9d9ed3e96c125eeec0a4897d39df8'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred:
  - summary: >-
      The compose ollama service is not given OLLAMA_CONTEXT_LENGTH, so the budget's 4096 may not match the server's real window.
    evidence: |-
      docker-compose.prod.yml's ollama service sets only OLLAMA_MAX_LOADED_MODELS and OLLAMA_KEEP_ALIVE; .env goes to the backend only. Ollama's built-in default has varied by version (2048 on older releases). E0-Platform.7 owns the ollama env (OLLAMA_CONTEXT_LENGTH=4096, NUM_PARALLEL=1, MAX_LOADED_MODELS=1), so the fix lands there.
    location: >-
      docker-compose.prod.yml (ollama service environment)
    severity: medium
  - summary: >-
      The chars/3.2 estimate under-counts text with fewer characters per token (CJK, emoji, dense code), which could overflow the window.
    evidence: |-
      estimate_tokens uses one ratio for every code point; CJK is roughly 1 to 1.5 chars/token on Mistral's tokenizer. The intent fixes the formula and gives calibration to E0-LLM.6 (SPIKE-6 prompt_eval_count), which is where a per-script adjustment belongs.
    location: >-
      src/backend/app/services/prompt_budget.py (estimate_tokens)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** On Ollama, `ai_service.generate_narrative` always pays for a KoboldCpp-native `/api/v1/generate` request (three 404 attempts) before falling back, and no prompt builder knows the 4096-token context: long transcripts and entity lists are cut by ad-hoc character limits (`chat_service.py:276`) or overflow silently.

**Approach:** Add `llm_provider.detect_backend(api_url)` (cached `GET /api/version` probe) and use it to skip the native attempt on Ollama. Add `app/services/prompt_budget.py`: an offline token estimate, a `TASK_POLICIES` registry, `fit(task, parts)` that assembles messages under the task's policy and raises `PromptBudgetError` when the required parts can't fit, and `map_reduce(...)` for inputs larger than one window.

## Boundaries & Constraints

**Always:**
- `detect_backend(api_url) -> "ollama" | "openai_compat"`, async. `api_url` empty/None means `settings.kobold_url`; the cache key is the URL without a trailing `/`. `ollama` only when the probe returns 2xx with a JSON object holding a string `version` (KoboldCpp may serve HTML on unknown paths). Any answered response is cached for the process lifetime; a transport error or timeout returns `openai_compat` uncached, so an Ollama that was still starting is detected on a later call. Short probe timeout (3 s). Uses `llm_provider._client` (MockTransport in tests). Never acquires the gate, never raises.
- `generate_narrative`: when the config is kobold and `detect_backend` says `ollama`, go straight to `complete_messages`; the probe runs before the gate slot is taken. Otherwise behaviour is unchanged.
- Token estimate: `estimate_tokens(text) = ceil(ceil(len(text) / 3.2) * 1.1)` (0 for empty), plus a documented per-message chat-template overhead. Pure Python, no tokenizer, no network, no new dependency.
- Settings: `ollama_context_length: int = 4096` (env `OLLAMA_CONTEXT_LENGTH`, `ge=256`). Window for a task = context length − the task's `reserved_output`.
- `TASK_POLICIES: dict[str, TaskPolicy(policy, reserved_output)]` has `chat`, `narrative`, `structured`, `live_recap`, `live_draft` (`map_reduce`), `npc_chat`, `lookup_answer`, one line each, with a comment that E0-LLM.6 calibrates the ratio and that feature epics add one-line entries.
- `PromptParts`: `system: str`, `instructions: str`, `required: list[str]`, `optional: list[str]` (most relevant first), `history: list[dict]` (oldest first). Message layout: system message (if non-empty), kept history in order, then one final user turn = required blocks, kept optional blocks, then instructions (last, so grounding rules sit in the final user turn).
- `fit` trims only whole items: `drop_oldest` drops history from the front, then optional from the tail; `truncate_tail` drops optional from the tail, then history from the front; `map_reduce` drops nothing (all parts must fit; overflow raises `PromptBudgetError` naming `map_reduce`). If system + instructions + required exceed the window, raise `PromptBudgetError`. `fit_report` returns `FitResult(messages, tokens, budget, dropped_history, dropped_optional)` so callers can tell what was left out; `fit` returns `.messages`. A trim logs a JSON-style `prompt_budget_trimmed` line (task + counts, never text).
- `map_reduce(chunks, map_fn, reduce_fn, *, task, overhead_tokens=0)`: async; the task's policy must be `map_reduce` (else `ValueError`); every chunk goes to `map_fn` in order; results are packed in order into batches whose estimate fits `window − overhead_tokens`, each batch reduced, repeating until one batch fits, which gets the final `reduce_fn`. A single result that can't fit, or a round that doesn't shrink the total, raises `PromptBudgetError` (no infinite loop). `split_text(text, max_tokens)` splits on paragraph, then line, then word, then character boundaries so every chunk fits and none is lost.
- Unknown task → `ValueError`.

**Never:** No change to gate semantics or `llm_gate.py`; every existing gate test stays green. No tokenizer package or runtime download. No migration of existing prompt builders (`summarize_session_transcript` moves in E4.7). No edits to `errors.py`, `tests/conftest.py`, CI gate scripts, demo seed/eval scaffold, frontend, `sprint-status.yaml`, `epics.md`. No test opens a socket to `KOBOLD_URL`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Ollama | `/api/version` → 200 `{"version":"0.4.3"}` | `ollama`, cached (second call makes no request) | none |
| KoboldCpp | `/api/version` → 404, or 200 HTML | `openai_compat`, cached | none |
| Down | transport error | `openai_compat`, not cached; next call probes again | swallowed |
| Narrative on Ollama | platform cfg, probe says ollama | no `/api/v1/generate` request; one chat-completions call, one gate slot | none |
| Narrative on KoboldCpp | probe 404 | native attempted first, as today | none |
| Everything fits | small parts | all parts in layout order, nothing dropped | none |
| History over | `chat`, long history | oldest turns dropped, newest kept | none |
| Optional over | `lookup_answer`, many snippets | least relevant (tail) dropped | none |
| Required over | required alone > window | — | `PromptBudgetError` |
| map_reduce task over | `live_draft` parts > window | — | `PromptBudgetError` |
| Big input | `live_draft`, text > 3 windows with sentinel at the end | sentinel reaches a `map_fn` call; reduce recurses; final reduce input fits | none |
| No progress | reduce output as big as input | — | `PromptBudgetError` |

</intent-contract>

## Code Map

- `src/backend/app/services/llm_provider.py` -- `_client(timeout)` (MockTransport hook), `uses_platform_llm`, `get_default_config`. Add `detect_backend` + module cache `_backend_cache`. Do not touch `gated`/`reserve_slot`/`complete_messages`/`stream_messages`.
- `src/backend/app/services/ai_service.py:86-125` -- `generate_narrative`: native attempt inside `llm_provider.gated(...)`; the comment at ~111 describes the wasted 404.
- `src/backend/tests/test_llm_provider_gate.py:256` -- `test_generate_narrative_one_slot_base_model`: its Backend handler raises on a bodiless GET to `/api/version` (JSON decode), so the probe must swallow handler exceptions and that test keeps `native_calls == 3`.
- `src/backend/app/core/errors.py` -- read-only: `PromptBudgetError` (`prompt_too_large`, 422, TERMINAL).
- `src/backend/app/core/config.py:37-76` -- Kobold/gate settings block; add `ollama_context_length`.
- `src/backend/app/services/ollama_service.py:357` -- precedent for `GET {base}/api/version`.
- `.env.example` -- append point (the "Local LLM gate" block at the end).
- `_bmad-output/planning-artifacts/epic-stories/B5.md:434,505,697` -- consumers: `live_recap` needs a "didn't fit" report, `live_draft` uses `map_reduce` with a sentinel test, `npc_chat` drops oldest history.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/config.py` -- add `ollama_context_length` with a why-comment.
- `src/backend/app/services/llm_provider.py` -- add `BACKEND_OLLAMA`, `BACKEND_OPENAI_COMPAT`, `_backend_cache`, `async detect_backend(api_url)` per the Always rules; mention it in the module docstring.
- `src/backend/app/services/ai_service.py` -- in `generate_narrative`, probe before the gate block and skip `_generate_kobold_native` on `ollama`; update the comment.
- `src/backend/app/services/prompt_budget.py` -- create: `CHARS_PER_TOKEN`, `SAFETY_MARGIN`, `MESSAGE_OVERHEAD_TOKENS`, `estimate_tokens`, `estimate_messages`, `TaskPolicy`, `TASK_POLICIES`, `policy_for`, `window_tokens(task, context_length=None)`, `PromptParts`, `FitResult`, `fit_report`, `fit`, `split_text`, `map_reduce`.
- `.env.example` -- append `OLLAMA_CONTEXT_LENGTH=4096` with a comment.
- `src/backend/tests/test_backend_detection.py` -- every detection row of the matrix plus the two narrative rows (MockTransport on `llm_provider._transport`, fakeredis gate as in `test_llm_provider_gate.py`, cache reset via `monkeypatch.setattr(llm_provider, "_backend_cache", {})`).
- `src/backend/tests/test_prompt_budget.py` -- estimate formula, registry entries, every fit/map_reduce row of the matrix, `split_text` loses nothing, unknown task.

**Acceptance Criteria:**
- Given the PR's backend CI, when it runs, then all existing tests (including every gate test) and the new tests pass.
- Given the licence workflow, when it runs, then it passes unchanged (no new dependency).

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 31 findings — high 0, medium 6, low 18, false 5, maybe-false 2
- findings:
  - `[false]` `[reject]` (blind) No prompt builder uses fit yet — the story's technical notes scope the fix to "callers that adopt fit" and move summarize_session_transcript to E4.7; feature epics adopt it.
  - `[medium]` `[defer]` (blind) OLLAMA_CONTEXT_LENGTH isn't passed to the Ollama container — real; the ollama env is owned by E0-Platform.7 (epics.md:1353). Deferred.
  - `[low]` `[reject]` (blind) Trimming history can break role alternation — Ollama's Go templates don't reject non-alternating roles. The fix (pair-wise drops) adds branching for an unshown failure.
  - `[low]` `[patch]` (blind) Context length can be below the reserves, giving a window of zero or less — ollama_context_length is now ge=2048, with a comment.
  - `[low]` `[reject]` (blind) map_reduce has no context_length — it adds public surface; no caller needs it yet.
  - `[low]` `[reject]` (blind) map_reduce has no round cap — a reduce that shrinks by one token per round isn't a realistic LLM behaviour; the no-shrink guard stops the real failure.
  - `[low]` `[reject]` (blind) The backend cache never expires and is unbounded — the intent says the result is cached for the process lifetime; entries are tiny, one per distinct kobold URL.
  - `[low]` `[reject]` (blind) A down backend costs a probe on every call — connection-refused fails at once, and the call is failing anyway; negative caching adds state for an outage path.
  - `[maybe-false]` `[reject]` (blind) Something that mimics Ollama's /api/version is taken for Ollama — the intent defines detection as /api/version succeeding. If true, the call still works through chat completions, so it would only be low. Settled by probing KoboldCpp's Ollama emulation on the desktop.
  - `[low]` `[patch]` (blind) generate_narrative's config=None and BYOK-kobold branches are untested — tests added (grouped with the verification-gap row).
  - `[low]` `[patch]` (blind) test_default_context_length depends on the environment — it now builds Settings(_env_file=None) after delenv.
  - `[false]` `[reject]` (blind) estimate_messages assumes string content — every message builder in app/ uses string content; no list-part content exists.
  - `[false]` `[reject]` (blind) The spec isn't in the diff — the spec was deliberately kept out of the review diff; PromptBudgetError already exists on main.
  - `[medium]` `[patch]` (edge) A 5xx probe answer was cached — a 5xx now returns openai_compat uncached; test added.
  - `[low]` `[reject]` (edge) A stale cache after a backend swap — same as the blind cache row (process lifetime is the intent).
  - `[low]` `[reject]` (edge) An unbounded cache from BYOK URLs — same as the blind cache row.
  - `[maybe-false]` `[reject]` (edge) KoboldCpp's Ollama emulation is misread as Ollama — same as the blind mimic row.
  - `[low]` `[patch]` (edge) Context length set between 256 and the reserves — same fix as the blind row (ge=2048).
  - `[low]` `[reject]` (edge) Empty PromptParts give [] — a caller bug that fails loudly at the provider; a guard adds a branch for no shown caller.
  - `[low]` `[reject]` (edge) drop_oldest leaves an assistant turn first — same as the blind alternation row.
  - `[false]` `[reject]` (edge) List content under-counted — same refutation as the blind row.
  - `[medium]` `[defer]` (edge) The CJK/emoji estimate is too low — real for non-English text; the formula is fixed by the intent and calibrated in E0-LLM.6. Deferred.
  - `[low]` `[reject]` (edge) overhead_tokens defaults to 0 — reduce_fn's own call goes through fit, which raises rather than truncating, so nothing is silently lost.
  - `[low]` `[reject]` (edge) map_fn returning None — a caller bug that fails loudly with TypeError.
  - `[low]` `[reject]` (edge) map_reduce has no context_length — same as the blind row.
  - `[medium]` `[patch]` (verification-gap) The probe URL for a user's own kobold endpoint is untested — tests added for both directions (own.test Ollama / KOBOLD_URL KoboldCpp, and the mirror), plus config=None.
  - `[medium]` `[defer]` (verification-gap other) Ollama is never given the context length — same as the blind compose row; deferred to E0-Platform.7.
  - `[low]` `[reject]` (verification-gap other) The cache never forgets a URL — same as the blind cache row.
  - `[low]` `[patch]` (verification-gap other) A test depends on the local .env — same fix as the blind row.
  - `[false]` `[reject]` (intent) Prompt builders don't adopt fit (reading R2) — the story's technical notes choose R1 ("for callers that adopt fit"; migration in E4.7).
  - `[medium]` `[defer]` (intent) The app's context length isn't tied to the server's — same as the compose row; E0-Platform.7.

## Design Notes

- Not caching a transport failure is the one refinement over "caches the result per URL": caching a miss from an Ollama that was still booting would bring back the wasted native request for the life of the process. An answered probe is a definitive answer and is cached.
- Trimming whole items only (never mid-text) keeps "never truncates silently" simple to check: anything not sent is listed in `FitResult`.
- The per-message overhead (role markers of the chat template) is separate from the 10% margin; E0-LLM.6 calibrates both against `prompt_eval_count`.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile` on changed `.py` files -- expected: no output.
- Scratch venv running `tests/test_prompt_budget.py` (pure module) -- expected: pass.
- Draft PR, `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.

**Needs desktop verification (record in Auto Run Result):**
- Budget estimates vs the real `lorekeeper` model tokenizer and context window on the desktop Ollama.
- `detect_backend` against a real Ollama vs an OpenAI-compatible BYOK endpoint.
