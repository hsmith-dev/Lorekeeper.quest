---
title: 'E0-Jobs.3: LorekeeperWorker: ctx rebuild, LLM config, retries and the worker service'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '5ad0e3113f26a397cee6debe176bcbd239c5ba54'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A requeued (retried) Job is never pushed again until the E0-Jobs.4 reaper ships, so a retryable failure leaves the row queued.
    evidence: |-
      _record_failure sets status=queued and next_run_at; nothing re-pushes it (RQ's current job holds the same id). epics.md E0-Jobs.4 says the retry delays rely on the reaper honouring next_run_at. Do not release between E0-Jobs.3 and E0-Jobs.4.
    location: >-
      src/backend/app/jobs/worker.py (_record_failure)
    severity: medium
  - summary: >-
      A work horse killed mid-run (the RQ job_timeout backstop, SIGKILL on deploy, a handler that blocks the loop past timeout_s) leaves its row running.
    evidence: |-
      asyncio.timeout is cooperative; RQ's job_timeout (timeout_s + 60) kills the horse without writing the row. Neither compose file sets stop_grace_period, so docker stop kills a Job after 10 s. The E0-Jobs.4 reaper recovers stale running rows (heartbeat older than 60 s, worker absent from RQ's registry; worker_id is the RQ worker name for that lookup).
    location: >-
      src/backend/app/jobs/worker.py (_run_claimed); docker-compose*.yml worker
    severity: medium
  - summary: >-
      The worker service has no healthcheck, and its prod logs go to stdout only, not to the backend log file the admin portal reads.
    evidence: |-
      restart: unless-stopped only covers a process exit; the admin System tab reads /var/log/lorekeeper/backend.log. Operational polish beyond the story's ACs; fits E0-Platform.7 or the admin System tab work.
    location: >-
      docker-compose.prod.yml (worker)
    severity: low
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

### 2026-11-01 — Review pass
- verdicts: 42 findings — high 0, medium 17, low 18, false 7, maybe-false 0
- findings:
  - (intent) `[low]` `[reject]` handler receives the live ctx, not one narrowed to the stored ctx_kind/ctx_audience; a promoted starter runs with current rights — the story says "as me with my current permissions"; the rights check fails only on loss.
  - (intent) `[medium]` `[defer]` retries recorded on the row but never re-run — epics E0-Jobs.4 owns re-pushing by next_run_at (deferred item 1).
  - (intent) `[false]` `[reject]` WorkerPool entrypoint instead of `rq worker`; `backend` instead of `web` — `python -m app.jobs.worker` runs RQ's own WorkerPool (the code behind `rq worker-pool`) with 2 LorekeeperWorkers; the web service is named `backend` in both compose files; a real desktop run showed 2 RQ workers.
  - (intent) `[false]` `[reject]` "keeps the sum" not met — the CI-14 gate sums *_MEM_LIMIT variables only (literals are baselined); sum 3.5 GiB, gate passes.
  - (intent) `[low]` `[reject]` no `to_thread` helper — `asyncio.to_thread` is the stdlib call handlers use; the module docstring now states the rule.
  - (intent) `[medium]` `[defer]` cooperative timeout cannot stop a loop-blocking handler — docstring patched; recovery of the killed row is E0-Jobs.4 (deferred item 2).
  - (intent) `[low]` `[reject]` record_hosted_usage not called — no handler exists; job.starter/job.llm_config are exposed for llm_config_service.meter.
  - (intent) `[low]` `[patch]` handler-raised LLMConfigError stored its detail, not the AC's reason — `_failure` maps every LLMConfigError to LLM_CONFIG_MESSAGE; test updated.
  - (intent) `[low]` `[reject]` entry-saved test checks after the first attempt — no attempt touches the entry; the handler's writes roll back each time.
  - (verification-gap) `[medium]` `[patch]` per-run Valkey install never observed — added `test_perform_installs_its_own_valkey_and_restores_the_previous`.
  - (verification-gap) `[medium]` `[patch]` configure_logging filter not verified — added `test_configure_logging_puts_job_fields_on_handler_logs`.
  - (verification-gap) `[medium]` `[patch]` report lock fallback untested — added `test_report_while_the_handler_holds_the_row_is_saved_with_the_job`.
  - (verification-gap) `[medium]` `[patch]` rollback-failure path untested — added `test_failed_rollback_still_records_the_outcome`.
  - (verification-gap) `[medium]` `[patch]` main() wiring untested — added `test_main_starts_a_worker_pool`.
  - (verification-gap other) `[low]` `[reject]` JSONFormatter drops arbitrary `extra` keys — pre-existing; the job fields this story needs are emitted.
  - (verification-gap other) `[false]` `[reject]` WorkerPool.start signature unchecked — checked against rq 2.12.0 source, and the desktop run started the pool.
  - (blind) `[medium]` `[defer]` retried Jobs never run again — same root as the intent row (deferred item 1).
  - (blind) `[medium]` `[patch]` exceptions outside the handler try (ctx_for, db.get, resolve_llm_config, done commit) leave the row running — `_prepare` + `_fail_attempt` record `internal`; added `test_pre_handler_failure_requeues_instead_of_staying_running`.
  - (blind) `[medium]` `[patch]` report fallback catches every DBAPIError; non-str stage — fallback narrowed to SQLSTATE 55P03; `Job.report` validates stage.
  - (blind) `[medium]` `[defer]` no stop_grace_period; a deploy kills long Jobs — recovery is the reaper's (deferred item 2).
  - (blind) `[low]` `[defer]` worker has no healthcheck — deferred item 3.
  - (blind) `[low]` `[defer]` worker logs not in the support log file — deferred item 3.
  - (blind) `[false]` `[reject]` logging in pool children unverified — the desktop worker run emitted JSON lines with job_id/kind/campaign_id from the forked horses.
  - (blind) `[medium]` `[defer]` asyncio.timeout cannot stop a blocking handler — same root as the intent row; docstring patched, recovery deferred (item 2).
  - (blind) `[low]` `[reject]` stale error stays on a retried row — documented contract (last attempt's error); run-state fields are now cleared on requeue.
  - (blind) `[low]` `[patch]` worker_processes accepts 0/negative — `Field(default=2, ge=1)`.
  - (blind) `[low]` `[patch]` untested paths (rollback, report fallback, main, max_attempts=1) — tests added incl. `test_single_attempt_job_fails_on_its_first_retryable_error`; heartbeat-after-finish and empty-detail cases rejected as low (the thread is joined on stop; the detail fallback is one branch).
  - (blind) `[low]` `[patch]` decrypted credential stays on job.llm_config — cleared with job.starter in the finally.
  - (blind) `[low]` `[patch]` per-Job Valkey client swaps a process global — docstring states one Job per work horse (RQ forks per Job).
  - (edge) `[medium]` `[defer]` requeued row never re-pushed — deferred item 1.
  - (edge) `[low]` `[patch]` requeued row keeps progress/stage/eta/worker_id/heartbeat_at — cleared in `_record_failure`; asserted in the retry test.
  - (edge) `[medium]` `[patch]` DataError from a bad stage swallowed by the fallback — same root as the blind report row; patched.
  - (edge) `[medium]` `[patch]` done-commit failure leaves row running — same root as the blind pre-handler row; patched.
  - (edge) `[medium]` `[patch]` pre-handler exceptions leave row running — same root; patched.
  - (edge) `[medium]` `[defer]` loop-blocking handler past timeout_s — deferred item 2.
  - (edge) `[low]` `[patch]` handler swallowing the timeout's cancellation recorded done — `timeout.expired()` after the block is a timeout.
  - (edge) `[low]` `[patch]` fresh session may wait on a lock held by the broken session — `await db.invalidate()` before the fresh session.
  - (edge) `[false]` `[reject]` system-ctx Jobs started by a Player fail permission_changed — no caller enqueues with an as_system ctx (sites fixed by check_scoped_queries.py).
  - (edge) `[false]` `[reject]` re-added member (new grant, epoch 0) passes — that user holds those rights now; the Job runs with current rights, which is the story's rule.
  - (edge) `[low]` `[patch]` worker_processes 0/negative — same root as the blind row; patched.
  - (edge) `[low]` `[patch]` starter deleted between check and fetch — now `permission_changed`.
  - (edge) `[false]` `[reject]` worker_id has no hostname — the RQ worker name is what the E0-Jobs.4 registry lookup needs; RQ's registry records each worker's hostname.

## Design Notes

Retry delays use `RETRY_DELAYS_S = (10, 60)` indexed by `attempts - 1`. A requeued row is not pushed: RQ's current job has the same id, and E0-Jobs.4's reaper is the designed re-pusher (until it lands, a requeued Job waits). The heartbeat thread builds its engine from the session factory's bind URL, so tests and production use the same code.

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- all contracts kept
- `python3 scripts/check_memory_budget.py` -- sum ≤ 14.5 GiB, no drift
- desktop: full pytest in `lorekeeper-backend-test` against throwaway pgvector + Valkey -- green
- desktop: real `python -m app.jobs.worker` run picks up a noop Job -- `done`
- GitHub CI on the draft PR -- green

## Auto Run Result

Status: done (draft PR #54; CI is the gate)

**Summary:** `run_job` is now the full Job wrapper:
- the claim honours `next_run_at`;
- a rights check against the stored ctx (`permission_changed`);
- LLM config for `llm` kinds (`llm_config`, with the fixed reason);
- gate class and deadline contextvars;
- a heartbeat thread;
- a cooperative `timeout_s`;
- `job.report`;
- the retry policy (+10 s, then +60 s, then `failed`; terminal codes fail at once);
- every pre-handler or commit failure is recorded instead of leaving the row `running`.

`LorekeeperWorker` imports `KIND_MODULES` and writes its RQ worker name as `worker_id`. `python -m app.jobs.worker` runs a 2-process RQ WorkerPool. A compose `worker` service exists in dev and prod, with `WORKER_MEM_LIMIT=1g`.

**Files changed:**
- `src/backend/app/jobs/worker.py` -- the wrapper, LorekeeperWorker, main().
- `src/backend/app/jobs/registry.py` -- `gate_class`, `KIND_MODULES`, `load_kind_modules`.
- `src/backend/app/db/models/job.py` -- non-mapped `starter`, `llm_config`, `report()`.
- `src/backend/app/core/logging.py` -- job fields on every log line while a Job runs.
- `src/backend/app/core/valkey_client.py` -- `set_valkey`.
- `src/backend/app/core/config.py` -- `worker_processes` (>= 1).
- `src/backend/app/jobs/__init__.py` -- docstring.
- `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example` -- worker service, dev backend healthcheck, `WORKER_MEM_LIMIT`/`WORKER_PROCESSES`.
- `src/backend/tests/jobs/test_worker.py` (new), `src/backend/tests/jobs/test_enqueue.py` -- matrix tests; a generic failure now requeues.

**Review:** 42 findings, triaged in the log above.
- Patched: pre-handler and done-commit failures, the narrowed report fallback with stage validation, the swallowed timeout, credential cleanup, the rollback invalidate, the requeue state reset, the fixed LLMConfigError reason, the worker_processes bound, docstrings, and eight new tests.
- Deferred: 3 items (see frontmatter).
- Rejected: every rejected row carries its reason in the log.

**Follow-up review recommended:** true. Patched entries: 10 medium, 10 low, 0 high. The failure path was restructured after review (`_prepare`/`_fail_attempt`), and only the new targeted tests cover it.

**Verification:**
- Desktop (`lorekeeper-backend-test`, throwaway pgvector + Valkey 8.1.11 containers, removed afterwards): full suite 1304 passed, 4 skipped after the review patches (1297 passed, 4 skipped before them). `lint-imports`: 5 contracts kept.
- Desktop real run: `python -m app.jobs.worker` (2 LorekeeperWorkers) ran three `system.noop` Jobs to `done`. `worker_id` was the RQ worker name, and the JSON log lines carried job_id, kind and campaign_id.
- `docker compose config -q` passes for both compose files. `scripts/check_memory_budget.py` is OK (sum 3.5 GiB).
- GitHub CI on PR #54: the first commit passed every check. CI on the PR verifies the patch commit.

**Needs desktop verification:**
- Bring up the compose `worker` on a real host: `docker compose up -d backend worker`, then check that `docker compose logs worker` shows "starting 2 job workers" and that the dev backend healthcheck reports healthy.

**Residual risks:** until E0-Jobs.4 lands, retried Jobs wait in `queued`, and the rows of killed work horses stay `running` (deferred).
