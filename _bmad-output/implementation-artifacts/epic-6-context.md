# Epic 6 Context: E0-LLM: Reliable, prioritised local-LLM access with structured output

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give every AI feature one shared, reliable way to call the local LLM. Calls queue behind a single Redis priority gate, so a live Rolling Recap and interactive GM questions beat background Jobs. Every task uses the same loaded local model, so Ollama never reloads. Prompts fit the context window under an explicit per-task budget policy. Structured output comes back as a validated pydantic object or a clear "AI output unusable" error. Errors are typed and map to HTTP the same way everywhere. A deterministic fake provider and a context-capture hook make AI routes and Jobs testable in CI without a model. This is Phase 0, Wave 0 foundation: extraction, continuity, recaps, NPC chat and the Jobs wrapper all build on it.

## Stories

- Story E0-LLM.1: Typed LLM errors and one LLM-config resolver
- Story E0-LLM.2: One priority gate for the local LLM, and one fixed local model
- Story E0-LLM.3: Backend detection and prompt budgets
- Story E0-LLM.4: `complete_structured` with schema enforcement and at most two repairs
- Story E0-LLM.5: Deterministic fake LLM provider and the EV-4 context-capture hook
- Story E0-LLM.6: Act on SPIKE-6: calibrate prompt budgets, decide the extraction prompt shape, and measure gate contention

## Requirements & Constraints

- **Structured output:** AI features get schema-conforming output from the local LLM. Invalid output is rejected after at most 2 repair attempts, then "AI output unusable", and nothing is written. BYOK backends use the same validation. Target: at least 95% valid on the first or second attempt (measured by EV-1 and the opt-in `ollama` integration run).
- **Brownfield consistency:** AI routes keep today's BYOK resolution order, the per-Campaign access check and hosted metering. Metering happens once per completion, only for the hosted default config, and never for BYOK.
- **Single model, constrained box:** one resident LLM on a 16 GB Reference Box. Settings are `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1` and `OLLAMA_CONTEXT_LENGTH=4096`. No further resident LLM is added.
- **No silent truncation:** required prompt parts are never truncated. If they don't fit, the call raises an error.
- **Latency targets are provisional.** For example, each Rolling Recap update must take 45 s or less. The SPIKE-6 numbers inform proposed values, but changing a target needs owner sign-off in `.memlog.md`.
- **No new dependencies.** No tokenizer package. Unit tests use `httpx.MockTransport`.
- **CI stays model-free.** No test may open a socket to `KOBOLD_URL`. Real-Ollama tests run only behind the `ollama` marker with `OLLAMA_TEST_URL` set.

## Technical Decisions

- **The gate** (`app/core/llm_gate.py`): `async with llm_slot(cls)`.
  - It is a Redis priority semaphore with capacity `OLLAMA_NUM_PARALLEL`.
  - Classes in priority order: `live_recap` > `gm_interactive` > `player_interactive` > `job_onsave` > `job_backfill`. Waiters in the same class are served first in, first out.
  - Request callers wait up to `LLM_GATE_WAIT_S` (60 s), then get `LLMBusy`, which becomes 503 `llm_busy`. An SSE route raises it before the stream starts.
  - Jobs acquire the gate per call, not per Job. There is no preemption.
  - The gate uses Redis keys, not pub/sub, because the pub/sub module allows only three channels.
  - Holder entries carry a TTL, so a crashed holder's slot is recovered automatically.
  - BYOK calls bypass the gate.
- **Fixed local model:** `model_for(task, config)` returns `LOCAL_LLM_MODEL` for every task. The only exception is `narrative`, which honours `hosted_model_variant` and accepts the reload cost. Per-call `num_ctx`, `num_gpu` and `keep_alive` are always stripped.
- **Backend detection:** `detect_backend(api_url)` returns `ollama` if `GET /api/version` succeeds, and `openai_compat` otherwise. The result is cached per URL. `ai_service` uses it to skip the wasted KoboldCpp-native attempt on Ollama.
- **Prompt budgets:** every prompt builder calls `prompt_budget.fit(task, parts)` against the context length minus the task's reserved output tokens.
  - Each task has one policy: `drop_oldest`, `truncate_tail` or `map_reduce`.
  - Feature epics add their own tasks to the `TASK_POLICIES` registry as one-line additions.
  - Without a tokenizer, tokens are estimated as chars / 3.2 plus a 10% margin. E0-LLM.6 calibrates this ratio.
- **`complete_structured(messages, schema, config, *, task, timeout)`:** the schema is always restated in the final user turn, at `temperature=0`. By backend:
  - Ollama: native `/api/chat` with `format=<json schema>`.
  - openai, custom and KoboldCpp: strict `response_format` json_schema, retried once as prompted JSON on a 4xx.
  - anthropic and gemini: prompted JSON.
  - Validation is pydantic, with at most 2 repair turns, then `StructuredOutputError`.
  - Each attempt logs a JSON line and updates a per-task stats counter.
  - Each attempt acquires the gate separately.
- **Flat schemas:** schemas live in `app/schemas/llm/<feature>.py` and subclass `FlatModel` (`extra="forbid"`). They have no `$ref`, `$defs`, `anyOf`, `oneOf` or `allOf`, and no `Optional` fields (use enums or empty strings instead). A CI test enforces this.
- **Errors** (`app/core/errors.py`): the `LLMError` family is `LLMConfigError`, `LLMBusy`, `LLMUnavailable`, `StructuredOutputError` and `PromptBudgetError`.
  - One registered handler maps them to 402, 503, 503, 422 and 422, with body `{"detail", "code"}`.
  - The 402 for `LLMConfigError` keeps the `X-Gate-Reason: llm-config` header.
  - For Jobs, config and structured-output errors are terminal, while busy and unavailable errors are retried. The mapping is exported as `RETRYABLE`/`TERMINAL`.
- **Config resolution:** `services/llm_config_service.resolve_llm_config(db, user)` is the single resolver, used by both the route dependency and the Jobs worker. `meter(...)` is the shared metering helper.
- **Fake and capture hook:**
  - Under `ENVIRONMENT=test`, `provider="fake"` answers deterministically, keyed on a hash of the messages. It is schema-aware: with no script it returns a minimal valid instance. It streams in several chunks and supports scripted outputs.
  - `llm_provider.capture()` is a contextvar hook. It records each call's messages, task, gate class and model (never `api_key`). It is off by default and costs nothing when off.
- **Conventions:**
  - New settings go in `app/core/config.py`: `local_llm_model`, `llm_gate_wait_s` and `llm_gate_capacity`.
  - Log JSON lines and never log keys or tokens.
  - In request paths, auxiliary AI failures are caught with a "must not block X" comment. Inside Jobs, exceptions propagate.

## Cross-Story Dependencies

- **Order within the epic:** .1 → .2 → .3 → .4 → .5 and .6. Story .5 fakes the structured path from .4. Story .6 needs .4 and the SPIKE-6 results measured in E0-Platform.10, and does not re-measure them.
- **E0-Jobs** imports `errors.RETRYABLE`/`TERMINAL`, `resolve_llm_config` and `llm_gate.class_for_queue`. Its `jobs/errors.py` enum must include `llm_config`, `ai_output_unusable`, `llm_busy` and `llm_unavailable`.
- **E0-QA:**
  - Its conftest imports `tests/fixtures/fake_llm.py` with a one-line addition.
  - EV-4 captured-context probes (E0-QA.14) use `capture()`.
  - Story .4's remote run uses E0-QA.4's `TEST_DATABASE_URL` once it lands.
  - `docs/BENCHMARKS.md` rows follow E0-QA.15's format.
- **Soft dependency on E0-Access:** the capture hook works with any ctx.
- **Consumers:** E1 (extraction, and the shortlist-vs-full-Entity-list decision from .6), E2 (continuity), E4 (the `live_recap` class and summarizer migration in E4.7, plus any `job_backfill` output cap that .6 proposes), and E5 and E6. Each adds its own `TASK_POLICIES` entry and schemas.
