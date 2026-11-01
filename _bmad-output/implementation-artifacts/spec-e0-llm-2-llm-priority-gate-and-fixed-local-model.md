---
title: 'E0-LLM.2: One priority gate for the local LLM, and one fixed local model'
type: 'feature'
created: '2026-10-31'
status: 'in-progress'
baseline_revision: 'fc1806a9a15f2da98765b946e20d733d46fb2114'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-6-context.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Every local-LLM call goes straight to Ollama with no ordering, so a background Job can delay a Live recap or a GM question, and each call may name a different model (per-user variant, per-call options), making Ollama reload models.

**Approach:** Add `app/core/llm_gate.py`, a Redis priority semaphore (`async with llm_slot(cls)`, atomic Lua acquire, holder TTL + renewal, waiter ZSET ordered by class priority then arrival). Make `complete_messages`/`stream_messages` acquire it for platform-LLM configs only, add `llm_provider.model_for`/`uses_platform_llm`/option stripping, and have the SSE chat route reserve its slot before the stream starts.

## Boundaries & Constraints

**Always:**
- Classes (StrEnum `GateClass`), priority high→low: `live_recap`, `gm_interactive`, `player_interactive`, `job_onsave`, `job_backfill`. Same class is FIFO.
- Redis keys (default prefix `llm_gate`): `llm_gate:holders` (ZSET, score = expiry ms), `llm_gate:waiters` (ZSET, score = `priority*10**13 + arrival_ms`), plus `llm_gate:waiters_seen` (ZSET, score = last poll ms) for waiter liveness. Keys, not pub/sub.
- Acquire is one Lua script: purge expired holders and stale waiters, then grant if free slots > 0 and the caller's waiter rank < free slots; otherwise stay queued. Waiters poll every 100 ms, re-submitting their original score (so a briefly evicted waiter keeps its place).
- Holder TTL 30 s, renewed every 10 s by a background task while held; release removes the token from all three keys and cancels renewal, in a `finally` (also on cancellation/client disconnect).
- Wait budget: explicit `wait_s` argument, else the contextvar `llm_gate.current_deadline` (a `time.monotonic()` deadline the E0-Jobs wrapper sets from the Job's remaining `timeout_s`), else `settings.llm_gate_wait_s` (60). On expiry the waiter is removed and `errors.LLMBusy` is raised.
- Reentrant: inside a held slot (contextvar), a nested `llm_slot`/acquire is a no-op, so `async with llm_slot(...)` around `complete_messages` (B3 pattern) never deadlocks at capacity 1.
- BYOK (`uses_platform_llm(config)` false) never touches Redis.
- If Redis is uninitialised or errors, the gate fails open: log a warning (`llm_gate_unavailable`) and run the call ungated (the gate orders work; it must not block AI features).
- `model_for(task, config)`: platform config → `settings.local_llm_model` for every task; `task == "narrative"` → `config.model or settings.local_llm_model` (variant honoured via the resolver's swap). Non-platform → `config.model` (provider fallbacks unchanged).
- `num_ctx`, `num_gpu`, `keep_alive` are removed from per-call `options` (and never reach any payload) for every provider.

**Never:** No preemption of a running call. No pub/sub. No change to `errors.py`, `llm_config_service.py`, `is_hosted_default`, or provider error behaviour (HTTPException 503 stays). No `prompt_budget`, `detect_backend`, `complete_structured`, fake provider (later stories). No SPIKE-6 measurement. No edits to `tests/conftest.py`, `docker-compose*.yml`, `env.py`, Dockerfiles, `scripts/check-licenses.py`, `sprint-status.yaml`, `epics.md`. No test opens a socket to `KOBOLD_URL`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Free slot | capacity 1, no holders | granted at once, holder entry with expiry now+30 s | none |
| Priority order | capacity 1 held; waiters arrive `job_backfill`, `gm_interactive`, `live_recap`; holder releases repeatedly | grants: `live_recap`, `gm_interactive`, `job_backfill` | none |
| FIFO in class | 3 `job_onsave` waiters arrive a, b, c | granted a, b, c | none |
| Capacity 2 | 2 free slots, 3 arrivals | two granted at once, third waits | none |
| Request timeout | slot held, waiter `wait_s` elapses | waiter removed from Redis | `LLMBusy` (503 `llm_busy` via handler) |
| Job deadline | `current_deadline` set to now+0.3 s | waits ≈0.3 s, not 60 s | `LLMBusy` |
| Dead holder | holder entry not renewed, clock passes expiry | next acquire succeeds (within 30 s) | none |
| Renewal | holder held past TTL with renewal running | still holder; others keep waiting | none |
| Dead waiter | waiter stops polling > stale window | purged; does not block later arrivals | none |
| Cancel while waiting | waiting task cancelled | waiter entry removed | CancelledError propagates |
| Reentrant | `llm_slot` nested inside held slot, capacity 1 | inner returns at once, one holder | none |
| BYOK | `provider="openai"` (or kobold at own URL) | gate never called | none |
| Redis down | `get_redis()` raises / RedisError | call proceeds ungated, warning logged | none |
| Gate class default | `complete_messages(...)` without `gate_class` | uses `current_class` (default `gm_interactive`) | none |
| class_for_queue | `onsave`/`backfill`/`interactive` | `job_onsave`/`job_backfill`/`gm_interactive` | unknown → `ValueError` |
| model_for | platform cfg, task `None`/`chat`; task `narrative` with base cfg | `local_llm_model`; `kobold_base_model` | none |
| Option strip | options `{num_ctx, num_gpu, keep_alive, top_p}` | payload has `top_p`, none of the three | none |
| SSE busy | `/api/chat/stream`, gate busy | normal 503 `{"code":"llm_busy"}`, no stream started | `LLMBusy` before `StreamingResponse` |

</intent-contract>

## Code Map

- `src/backend/app/core/errors.py` -- read-only: `LLMBusy` (code `llm_busy`, 503), `llm_exception_handler` already registered in `app/main.py:61`.
- `src/backend/app/core/redis_client.py:19` -- `get_redis()` (raises `RuntimeError` if not initialised; `decode_responses=True`). Initialised in `main.py` lifespan; not initialised in tests.
- `src/backend/app/core/config.py` -- `Settings`; add `local_llm_model`, `llm_gate_wait_s`, `llm_gate_capacity` near the Kobold block. `kobold_model` default `"lorekeeper"`, `kobold_base_model` `"lorekeeper-base"`.
- `src/backend/app/services/llm_provider.py` -- `complete_messages` (line ~41), `stream_messages` (~62, an async generator; kobold branch builds `model = cfg.model or kobold_model`), `_openai_compat` (~137, same model line), `test_provider_connection` (~319). Uses `httpx.AsyncClient(timeout=...)` directly; add a module `_transport = None` passed as `transport=` (pattern of `ollama_service._transport`, see `tests/test_ollama_install.py:72`).
- `src/backend/app/services/llm_config_service.py:62,81` -- the resolver swaps `model` to `kobold_base_model` for variant `base`; this is how `narrative` "honours hosted_model_variant".
- `src/backend/app/services/ai_service.py:86-125` -- `generate_narrative`: kobold-native attempt (`_generate_kobold_native`, platform URL) then `complete_messages` fallback. Both are local-LLM calls.
- `src/backend/app/services/eval_service.py:80` -- validation-set narrative generation per variant (Settings' Fine-Tuned/Base compare via `routes/settings.py:_hosted_variant_config`).
- `src/backend/app/api/routes/settings.py:181` -- Test Connection with base variant sets `cfg.model`; goes through `test_provider_connection`.
- `src/backend/app/api/routes/chat.py:360-410` -- `chat_stream`: `event_stream()` yields `meta` then iterates `stream_messages`, catching only `HTTPException`.
- `src/backend/app/services/chat_service.py` -- many `complete_messages` callers; unchanged (default class + local model).
- `src/backend/tests/conftest.py` -- session-autouse Postgres setup; do not edit. `pytest.ini`: `asyncio_mode = auto`.
- `.github/workflows/backend-tests.yml` -- Postgres service only; add a Redis-compatible service.
- `licenses/register.yaml` -- one-line flow-style python rows (e.g. line 288); dev deps are not scanned by CI but register them anyway.
- `.env.example` -- append point for new settings.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/config.py` -- add `local_llm_model: str = ""` (a `model_validator(mode="after")` fills it from `kobold_model` when empty, so `settings.local_llm_model` is always a model name), `llm_gate_wait_s: float = 60.0`, `llm_gate_capacity: int = Field(1, ge=1, validation_alias=AliasChoices("LLM_GATE_CAPACITY", "OLLAMA_NUM_PARALLEL", "llm_gate_capacity"))`, each with a short "why" comment.
- `src/backend/app/core/llm_gate.py` -- create: `GateClass` StrEnum + `PRIORITY`; contextvars `current_class` (default `gm_interactive`), `current_deadline` (default `None`), private `_held`; `class_for_queue(queue)`; `LLMGate(redis, *, capacity, wait_s, key_prefix="llm_gate", holder_ttl_s=30, renew_every_s=10, poll_s=0.1, waiter_stale_s=5, clock=<ms wall clock>)` with `acquire(cls, *, wait_s=None) -> Slot`, `snapshot() -> {"capacity", "holders": {cls: n}, "waiters": {cls: n}}`; `Slot` (`release()` idempotent, `held()` context manager setting `_held`; a no-op Slot for bypass/fail-open/reentrant); Lua acquire + Lua renew via `redis.register_script`; tokens `f"{cls}:{time_ns:020d}:{hex8}"` (class parseable for snapshot, ns breaks same-ms ties). Module helpers: `get_gate()` (built lazily from `get_redis()` + settings, rebuilt if the redis client object changes), `async acquire(cls=None, *, wait_s=None) -> Slot` (reentrant, fail-open, coerces `str` to `GateClass`), `llm_slot(cls=None, *, wait_s=None)` async context manager, `async snapshot()`. Log JSON-style lines via `logging` (`llm_gate_granted` with `gate_class`/`waited_ms` when it waited, `llm_gate_busy`, `llm_gate_unavailable`); never log keys or tokens of users.
- `src/backend/app/services/llm_provider.py` -- add `uses_platform_llm(cfg)` (provider `kobold` and `api_url` empty or equal to `settings.kobold_url` ignoring a trailing `/`); `model_for(task, cfg)`; `strip_local_options(options) -> dict` (drops `num_ctx`, `num_gpu`, `keep_alive`); `gated(cfg, gate_class=None)` async CM (`llm_slot` for platform configs, no-op otherwise); `async reserve_slot(cfg, gate_class=None) -> Slot` (for SSE routes; no-op Slot for BYOK). `complete_messages` and `stream_messages` gain keyword-only `task: str | None = None`, `gate_class: GateClass | str | None = None`, `options: dict | None = None`; they run inside `gated(...)` (stream: the whole upstream stream is inside it, released in the generator's `finally`), use `model_for(task, cfg)` for the kobold model (keep `or settings.kobold_model` fallback), and merge `strip_local_options(options)` into the OpenAI-compatible payload top level (ignored for anthropic/gemini). `test_provider_connection` passes `task="narrative"` (it checks the variant the user picked). Add `_transport` and pass it to every `httpx.AsyncClient`. Update the module/function docstrings.
- `src/backend/app/services/ai_service.py` -- `generate_narrative`: wrap the platform path (native attempt + fallback) in one `llm_provider.gated(cfg)` and pass `task="narrative"` to `complete_messages` (reentrancy keeps it to one slot).
- `src/backend/app/services/eval_service.py` -- pass `task="narrative"` (the validation set is narrative generation; the Fine-Tuned/Base compare must keep its model).
- `src/backend/app/api/routes/chat.py` -- `chat_stream`: `slot = await llm_provider.reserve_slot(config)` before building `StreamingResponse` (so `LLMBusy` becomes a normal 503 via the registered handler); inside `event_stream` use `with slot.held():` around the stream and `await slot.release()` in `finally`.
- `src/backend/requirements-dev.txt` -- add `fakeredis[lua]==2.26.2` and `lupa==2.8` (Lua for fakeredis EVAL), with a comment.
- `licenses/register.yaml` -- add flow-style python rows for `fakeredis` (BSD-3-Clause), `lupa` (MIT), `sortedcontainers` (Apache-2.0; fakeredis dependency), `editions: [agpl, commercial]`, no `images`, notes "dev/test only (requirements-dev.txt); not shipped". Keep alphabetical placement if the python block is sorted.
- `.github/workflows/backend-tests.yml` -- add service `redis` with image `valkey/valkey:8-alpine` (comment: BSD, Redis 7.4+ is RSALv2/SSPL, owner deciding), port 6379, health-cmd `valkey-cli ping`; add `REDIS_TEST_URL: redis://localhost:6379/15` to the Run tests env.
- `.env.example` -- append `LOCAL_LLM_MODEL`, `LLM_GATE_WAIT_S`, `OLLAMA_NUM_PARALLEL` (gate capacity) with one-line comments.
- `src/backend/tests/test_llm_gate.py` -- gate tests over a fixture parametrised `["fake", "real"]`: `fake` = `fakeredis.FakeAsyncRedis(decode_responses=True)` (fresh per test), `real` = `redis.asyncio.from_url(REDIS_TEST_URL)` skipped when unset; each test uses a unique `key_prefix` and deletes its keys after. Cover every gate row of the matrix (priority order, FIFO, capacity 2, timeout + waiter removed, deadline contextvar, dead holder via injected clock, renewal with small TTL/renew values, dead waiter, cancel, reentrant, snapshot counts, class_for_queue, `str` class coercion, fail-open when `get_redis` raises). Use asyncio events/short sleeps; no test may take > 2 s.
- `src/backend/tests/test_llm_provider_gate.py` -- provider tests with `llm_provider._transport = httpx.MockTransport(...)` (monkeypatched) and a monkeypatched `llm_gate.get_gate` returning a fake-Redis `LLMGate`: platform call acquires with default class `gm_interactive`, explicit `gate_class`, `current_class` contextvar; BYOK (openai, kobold at own URL) never calls the gate (gate factory raises if touched); `model_for` rows; option stripping asserted on the captured JSON payload for `complete_messages` and `stream_messages`; `stream_messages` releases on normal end and on `aclose()` mid-stream; `/api/chat/stream` returns 503 `{"code":"llm_busy"}` when `reserve_slot` raises `LLMBusy` (monkeypatch `llm_provider.reserve_slot` and the chat prep so no DB-heavy setup or model is needed, or create the minimal user/campaign rows via existing fixtures).

**Acceptance Criteria:**
- Given the backend CI workflow on the PR, when it runs with the Postgres and Valkey services, then the 99 baseline tests and all new tests pass, and the `real` parametrisations of the gate tests run (not skipped).
- Given capacity 1 against real Valkey with a held slot and waiters `job_backfill`, `gm_interactive`, `live_recap`, when the holder releases and each grantee releases in turn, then grants go `live_recap`, `gm_interactive`, `job_backfill`.
- Given the licence workflow, when it runs, then it passes with the three new register rows.

## Design Notes

- Third key `waiters_seen`: without waiter liveness, a process that dies while waiting would sit at the head of `waiters` forever and block every later caller. The story names two keys; this one is additive and internal.
- Fail-open on Redis errors is a deliberate choice: Ollama still serialises requests itself, so losing the gate loses only ordering, not correctness.
- Reentrancy is required by later stories: B3/E2 do `async with llm_slot(cls)` and then call `complete_structured`, which also acquires.
- `current_deadline` is how E0-Jobs.3 passes "remaining `timeout_s`" into calls it doesn't make directly: `current_deadline.set(time.monotonic() + remaining)`.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile` on every changed `.py` -- expected: no output.
- Scratch venv (fastapi, httpx, pydantic-settings, redis==5.1.0, fakeredis[lua]==2.26.2, pytest, pytest-asyncio) running the `fake` gate tests with a stub conftest is optional; CI is the real runner.
- Push the story branch, open a draft PR, `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: Backend tests and Dependency licences green.

**Needs desktop verification (record in Auto Run Result):**
- Priority ordering under real contention against the desktop Ollama and Redis (a scratch script holding a `job_backfill` call while `gm_interactive` and `live_recap` calls queue).
- Wait time of an interactive call behind a running background Job. (SPIKE-6 measurement itself belongs to E0-Platform.10.)

## Spec Change Log

## Review Triage Log
