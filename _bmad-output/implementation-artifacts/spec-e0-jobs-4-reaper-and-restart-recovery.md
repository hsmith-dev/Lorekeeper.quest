---
title: 'E0-Jobs.4: Reaper and restart recovery'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: 'af726450a8fd852728585e345403f8fa7e785e98'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Nothing re-pushes a `queued` Job once its RQ message is gone. A retried Job (`next_run_at` +10 s / +60 s from E0-Jobs.3) never runs again, a lost after-commit push or a Valkey flush strands a row, a dependent whose dependency ended by raw SQL or was deleted is never released, and a row left `running` by a killed work horse (RQ timeout backstop, deploy, OOM) stays `running` forever.

**Approach:** A reaper pass `reap()` in `app/jobs/worker.py`, run every 30 s from a thread in every `LorekeeperWorker`, one pass at a time via a Valkey lock. It recovers dead `running` attempts (requeue or `failed`/`interrupted`) and re-pushes runnable `queued` rows that RQ does not hold, through a re-push helper in `app/jobs/enqueue.py`. Outcome writes in the wrapper only land while the attempt still owns the row, so a taken-back attempt cannot write a second outcome.

## Boundaries & Constraints

**Always:**
- Postgres is the authority; RQ messages still carry only `job_id`. The reaper touches only `jobs` rows directly (CI-8 `OWNER_INFRA` allows `Job`/`DataBackfill` under `app/jobs/`).
- Lock: `SET lorekeeper:jobs:reaper NX EX (interval-5)`, never released early; a pass that loses the lock does nothing. First pass at worker start, then every 30 s. Burst workers (tests) start no reaper. A failing pass is logged and never kills the loop.
- Dead `running` row = heartbeat (or `started_at`) older than 60 s AND no live RQ worker is running it (its `worker_id` is absent from RQ's worker registry, or present but its current job is not this Job — the worker survived, its horse died). Rows locked by a live attempt are skipped (`FOR UPDATE SKIP LOCKED`). Attempts left → `queued`, `next_run_at = now`; none left → `failed`, `finished_at`; both `error_code=interrupted`, `error_message="Interrupted by a restart"`, run state (progress, stage, ETA, worker_id, heartbeat) cleared. ORM commit, so a `failed` row releases its dependents via the outbox.
- Runnable `queued` row = not waiting on an active dependency (none, deleted → FK SET NULL, or terminal however it got there) AND (`next_run_at <= now`, or no `next_run_at` and older than 60 s). Pushed only when RQ does not hold it: its id is not in its queue list and no live worker is running it.
- `_finish` / `_record_failure` lock the row and write only while it is `running` with this attempt's `worker_id`; otherwise roll the attempt's writes back and return the row's current status.
- Compose `worker` (dev + prod): `stop_grace_period: 60s` so `docker stop` lets short Jobs finish; longer ones are recovered by the reaper.

**Never:** no RQ `retry`, scheduler or `rq suspend`; no new dependency; no queue priority/leases/backfill changes (E0-Jobs.5); no pubsub (E0-Jobs.6); no routes (E0-Jobs.7); no memory-limit changes; no worker healthcheck or log-file routing (deferred to E0-Platform.7 / admin System tab, as E0-Jobs.3 recorded).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Lost push | queued, >60 s, Valkey flushed | pushed once; runs once to `done`; next pass pushes nothing | — |
| Still held | queued, >60 s, id in RQ queue | not pushed | — |
| Young | queued, <60 s, no next_run_at | not pushed | — |
| Retry not due | next_run_at future | not pushed; pushed once it has passed | — |
| Live worker on it | queued row id is a live worker's current job | not pushed | — |
| Dependency active | dependent of a running Job | not pushed | — |
| Dependency raw-SQL terminal | dependency set `cancelled` by SQL | dependent pushed once, runs | — |
| Dependency deleted | dependency row deleted | `depends_on_job_id` NULL, dependent pushed | — |
| Dead attempt, attempts left | running, heartbeat 61 s, worker gone | `queued` `interrupted`, pushed, then `done` attempt 2 | — |
| Dead last attempt | attempts = max | `failed` `interrupted` "Interrupted by a restart"; dependents released | — |
| Fresh heartbeat | heartbeat 30 s | untouched | — |
| Worker alive, on it | stale heartbeat, worker's current job = this Job | untouched; recovered once the worker's current job clears | — |
| Late outcome | attempt taken back mid-run | no `done`; the attempt's writes roll back | logged |
| Web restart | enqueuing engine disposed | Job finishes normally, reaper does nothing | — |
| Lock | two reapers, one interval | second pass skipped | — |
| Killed horse (real fork, Valkey) | SIGKILL work horse mid-Job | row `running` → reaper requeues → `done`, attempts 2, one row | — |

</intent-contract>

## Code Map

- `src/backend/app/jobs/worker.py` -- `_owned` (new ownership guard), `_finish`/`_record_failure`/`_fail_attempt`/`_prepare` take `worker_id`; new reaper section: `REAPER_INTERVAL_S`, `STALE_AFTER_S`, `QUEUED_GRACE_S`, `REAPER_LOCK_KEY`, `INTERRUPTED_MESSAGE`, `ReapResult`, `_live_workers` (RQ `Worker.all` → current job ids), `_in_rq_queue` (`LPOS`), `_recover_running`, `_push_due`, `reap`, `Reaper` (thread + lock); `LorekeeperWorker.work` starts the reaper when not burst.
- `src/backend/app/jobs/enqueue.py` -- `repush(job_id, queue, kind, connection)` re-push helper (swallows and logs push errors).
- `src/backend/app/jobs/outbox.py` -- `push(..., connection=None)`; after-commit dependents release (reused for reaper-failed rows).
- `src/backend/app/db/models/job.py` -- `depends_on_job_id` FK `ON DELETE SET NULL` (read-only evidence for the deleted-dependency case).
- `docker-compose.yml`, `docker-compose.prod.yml` -- worker `stop_grace_period`.
- `src/backend/tests/jobs/test_reaper.py` -- new; fake + real Valkey params; real forking-horse kill test.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/jobs/worker.py` -- ownership guard on outcome writes; reaper pass, thread and lock; worker hook -- the story's reaper loop.
- `src/backend/app/jobs/enqueue.py` -- `repush` helper -- story names it as the re-push home.
- `src/backend/app/jobs/outbox.py` -- `connection` argument on `push` -- the reaper pushes on its own client.
- `docker-compose.yml`, `docker-compose.prod.yml` -- `stop_grace_period: 60s` on `worker` -- graceful deploys.
- `src/backend/tests/jobs/test_reaper.py` -- every I/O matrix row.

**Acceptance Criteria:**
- Given the full backend suite on CI (Postgres + Valkey), when it runs, then it is green with no regressions, and the `static` gates (import-linter, CI-8 scoped queries, memory sum ≤ 14.5 GiB) pass.
- Given a real worker container stack (Postgres, Valkey, `python -m app.jobs.worker`), when a work horse is `kill -9`ed mid-Job, a retry's `next_run_at` passes, a dependency row is deleted, and the worker container is stopped mid-run, then every row ends `done` or `failed` with a code (or the dependent runs) and none stays `queued`/`running`.

## Spec Change Log

## Review Triage Log

## Design Notes

- RQ's registry alone cannot detect a killed horse: the parent worker survives and stays registered. So "absent from the registry" is widened to "no live worker has this Job as its current job". A worker whose container was SIGKILLed drops out of the registry when its key expires (90 s TTL while busy).
- A stale heartbeat is required as well: a Valkey flush empties the registry, but a live horse still beats every 10 s, so its row is never taken back.
- Requeued interrupted rows are due at once (`next_run_at = now`) and pushed in the same pass.

## Verification

**Commands:**
- `python -m pytest -q tests/jobs` (desktop container, `VALKEY_TEST_URL` set) -- expected: all pass, including the forking kill test.
- full `python -m pytest -q` -- expected: no regressions.
- `gh pr checks <n>` -- expected: all green.
