---
title: 'E0-LLM.3: Backend detection and prompt budgets'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '2b74d89798a9d9ed3e96c125eeec0a4897d39df8'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred: []
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
