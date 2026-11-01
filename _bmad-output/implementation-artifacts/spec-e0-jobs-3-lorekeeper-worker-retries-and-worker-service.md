---
title: 'E0-Jobs.3: LorekeeperWorker: ctx rebuild, LLM config, retries and the worker service'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '5ad0e3113f26a397cee6debe176bcbd239c5ba54'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** E0-Jobs.2's `run_job` is minimal: it never checks that the starter still holds the rights recorded at enqueue, resolves no LLM config, never retries, has no heartbeat, timeout or progress reporting, ignores the LLM gate class, and no process in any deployment consumes the RQ queues.

**Approach:** Extend `app/jobs/worker.py` into the full wrapper (rights check, LLM config, gate class + deadline contextvars, heartbeat thread, timeout, `job.report`, retry policy from `app/jobs/errors.py`), add `gate_class` to `JobKind`, add `LorekeeperWorker` (an `rq.Worker` that imports every kind-registering module) started as a 2-process RQ `WorkerPool` by `python -m app.jobs.worker`, and a `worker` service in both compose files.

## Boundaries & Constraints

**Always:**
- One wrapper (`run_job`) for both RQ and `JOBS_EAGER`. RQ side: fresh NullPool engine per RQ job inside the forked work horse, one session per Job, `asyncio.run`.
- Claim sets `status=running`, `started_at`, `worker_id`, `heartbeat_at`, `attempts+1`; a row whose `next_run_at` is in the future is not claimed.
- Rights check before the handler: `ctx_for` NotFound, a different `access_epoch`, or a current role ranked below the stored `ctx_kind` (gm > player > anon) → `failed`, `permission_changed`, no retry, handler never called.
- Kinds with `llm` in `resources`: `llm_config_service.resolve_llm_config(db, starter)`; `LLMConfigError` → `failed`, `llm_config`, message exactly "No AI model is configured for your account", no retry. The config and the starter are handed to the handler as `job.llm_config` / `job.starter` (non-mapped attributes), so the handler meters via `llm_config_service.meter` (→ `record_hosted_usage`).
- Classification: `LLMError` codes via `errors.RETRYABLE`/`TERMINAL` (code written as `error_code`); `ModelServiceUnavailable` → `model_unavailable`; handler exceeding `timeout_s` → `timeout`; anything else → `internal`. Codes in `TERMINAL_CODES` fail at once; the rest requeue while `attempts < max_attempts`: `status=queued`, `next_run_at = now + 10 s` after the 1st failure, `+60 s` after the 2nd, last `error_code`/`error_message` kept; 3rd failure → `failed`. `StructuredOutputError` message is "AI output unusable". Other messages are readable fixed text or the LLMError's `detail`, never the raw exception text.
- RQ pushes stay `retry` unset (E0-Jobs.2); the row owns retries. Re-pushing a requeued row after `next_run_at` is the E0-Jobs.4 reaper's.
- Gate: before the handler, `llm_gate.current_class` = kind's `gate_class` or `class_for_queue(queue)`, and `llm_gate.current_deadline` = `time.monotonic() + timeout_s`; both reset afterwards.
- Heartbeat: a daemon thread with its own event loop and engine writes `heartbeat_at` every `HEARTBEAT_INTERVAL_S` (10) while the handler runs (so a blocked event loop still beats); only for this row while `running` and owned by this `worker_id`.
- `job.report(progress, stage, eta_seconds)` writes those columns on the row immediately in its own short transaction (visible before the Job ends); progress must be in [0, 1].
- Logs from the wrapper and from code the handler calls carry `job_id`, `kind`, `campaign_id` (a logging filter fed by a contextvar); payload, tokens and Shorthand are never logged.
- A Job failing never touches the Journal Entry that triggered it (the handler's writes roll back, the caller's committed entry stays).
- Compose `worker` (dev + prod): backend image, `python -m app.jobs.worker` (RQ `WorkerPool`, 2 `LorekeeperWorker` processes, queues `interactive onsave backfill`), `depends_on: backend: service_healthy` (the web service is named `backend` here), memory `${WORKER_MEM_LIMIT:-1g}`, `# WORKER_MEM_LIMIT=1g` in `.env.example`; dev `backend` gains a healthcheck so `service_healthy` works. Memory sum stays ≤ 14.5 GiB.

**Never:** no reaper or re-push of requeued/stale rows, no handling of rows left `running` by a killed horse (E0-Jobs.4); no admission/leases/priority changes (E0-Jobs.5); no pubsub events (E0-Jobs.6); no Job routes (E0-Jobs.7); no RQ `retry`/scheduler-based delays; no new dependency.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | noop, starter unchanged | `done`, `worker_id`, `started_at`, `heartbeat_at` set | — |
| Demoted | stored ctx_kind gm, member now player | `failed` `permission_changed`, attempts 1, handler not called | no retry |
| Epoch bumped | grant `access_epoch` 1, stored 0 | `failed` `permission_changed` | no retry |
| Removed | no membership | `failed` `permission_changed` | no retry |
| LLM config missing | `llm` kind, no config | `failed` `llm_config`, "No AI model is configured for your account", handler not called | no retry |
| LLM config ok | `llm` kind, open access | handler sees `job.llm_config`, `job.starter` | — |
| Retryable 1st/2nd | handler raises LLMBusy / LLMUnavailable / ModelServiceUnavailable / RuntimeError | `queued`, `next_run_at` ≈ +10 s then +60 s, code kept | — |
| Retryable 3rd | third failure | `failed` with code + readable message | — |
| Structured output | StructuredOutputError | `failed` `ai_output_unusable`, "AI output unusable", attempts 1 | no retry |
| Timeout | handler sleeps > timeout_s | `queued` (retry) with `timeout`; `failed` `timeout` on the last attempt | — |
| Not yet due | `next_run_at` in future | not claimed (None) | — |
| Gate | kind gate_class live_recap / none on onsave | handler sees `current_class` live_recap / job_onsave and a deadline; reset after | — |
| Heartbeat | handler blocks loop > interval | `heartbeat_at` advances during the run | — |
| Report | `job.report(0.5, "Reading", 30)` | row shows it from another session mid-run | ValueError on progress outside [0,1] |
| Entry saved | entry + failing noop variant in one commit | entry unchanged, Job not `done` | — |

</intent-contract>

## Code Map

- `src/backend/app/jobs/worker.py` -- `run_job`, `_claim`, `_finish`, `_failure`, `_perform`, `perform`; becomes the full wrapper + `LorekeeperWorker` + `main()` (`python -m app.jobs.worker`).
- `src/backend/app/jobs/registry.py` -- `JobKind` (frozen dataclass, `__post_init__` validation); add `gate_class: GateClass | None = None`; add `KIND_MODULES` (modules the worker imports at start; empty today).
- `src/backend/app/jobs/errors.py` -- `TERMINAL_CODES`, `RETRYABLE_CODES` (reuse for the retry decision).
- `src/backend/app/core/errors.py` -- `LLMError` family, `RETRYABLE`, `TERMINAL`.
- `src/backend/app/clients/errors.py` -- `ModelServiceUnavailable` (app.jobs may import app.clients per `.importlinter`).
- `src/backend/app/core/llm_gate.py` -- `current_class`, `current_deadline`, `class_for_queue`, `GateClass`; read-only.
- `src/backend/app/core/valkey_client.py` -- global async client; the RQ horse needs its own per `asyncio.run` (add `set_valkey`).
- `src/backend/app/core/logging.py` -- `JSONFormatter` emits only `record.extra`; add the job fields.
- `src/backend/app/services/llm_config_service.py` -- `resolve_llm_config(db, user)`, `meter` (read-only).
- `src/backend/app/access/context.py` -- `ctx_for`, `CampaignContext.access_epoch/role`; `app/access/policy.py` `GM/PLAYER/ANON`.
- `src/backend/app/db/models/job.py` -- non-mapped attrs (`dependency_status`); add `llm_config`, `starter`, `report`.
- `src/backend/app/jobs/outbox.py` -- `rq_timeout` (kind timeout + 60 s backstop), eager path calls `run_job`.
- `src/backend/tests/jobs/test_enqueue.py` -- existing expectations that a generic failure is `failed` after one run must become "requeued"; reuse fixtures.
- `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`, `scripts/check_memory_budget.py` -- worker service; memory gate reads `*_MEM_LIMIT` refs.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/jobs/registry.py` -- `gate_class` field + validation; `KIND_MODULES`; `load_kind_modules()`.
- `src/backend/app/db/models/job.py` -- non-mapped `llm_config`, `starter`; `report()` delegating to an injected reporter.
- `src/backend/app/core/valkey_client.py` -- `set_valkey(client) -> previous`.
- `src/backend/app/core/logging.py` -- JSONFormatter includes `job_id`, `kind`, `campaign_id` record attributes.
- `src/backend/app/jobs/worker.py` -- full wrapper per Boundaries; `LorekeeperWorker` (stamps its RQ worker name as `worker_id`); `main()`; `__main__` guard.
- `src/backend/app/core/config.py` -- `worker_processes: int = 2`.
- `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example` -- worker service, dev backend healthcheck, `WORKER_MEM_LIMIT`.
- `src/backend/tests/jobs/test_worker.py` -- the I/O matrix; every `LLMError.code` is a `JobErrorCode`; `KIND_MODULES` covers every module that registers a kind; `LorekeeperWorker` imports them.
- `src/backend/tests/jobs/test_enqueue.py` -- adjust generic-failure expectations to the retry policy.

**Acceptance Criteria:**
- Given the full backend suite, when CI runs, then it is green with no regressions and `lint-imports` keeps all contracts; the memory-budget gate passes.
- Given the desktop stack with Postgres, Valkey and `python -m app.jobs.worker`, when a `system.noop` Job is enqueued, then a real RQ worker runs it to `done` with a `worker_id` of that host.

## Spec Change Log

## Review Triage Log

## Design Notes

Retry delays use `RETRY_DELAYS_S = (10, 60)` indexed by `attempts - 1`. A requeued row is not pushed: RQ's current job has the same id, and E0-Jobs.4's reaper is the designed re-pusher (until it lands, a requeued Job waits). The heartbeat thread builds its engine from the session factory's bind URL, so tests and production use the same code.

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- all contracts kept
- `python3 scripts/check_memory_budget.py` -- sum ≤ 14.5 GiB, no drift
- desktop: full pytest in `lorekeeper-backend-test` against throwaway pgvector + Valkey -- green
- desktop: real `python -m app.jobs.worker` run picks up a noop Job -- `done`
- GitHub CI on the draft PR -- green
