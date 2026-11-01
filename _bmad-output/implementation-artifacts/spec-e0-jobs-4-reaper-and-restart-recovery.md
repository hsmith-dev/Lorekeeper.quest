---
title: 'E0-Jobs.4: Reaper and restart recovery'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'af726450a8fd852728585e345403f8fa7e785e98'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The reaper is a thread inside each RQ worker parent, which forks a work horse per Job; a lock held by that thread at fork time could in theory deadlock a horse.
    evidence: |-
      maybe-false. CPython 3.11 re-inits the import and logging locks at fork, redis-py resets its pool in a child (pid check), and the thread's asyncpg engine and event loop are never used by a horse. The desktop runs (about 12 Jobs with the reaper live, including kills and restarts) showed no hang. A soak test of thousands of short Jobs with the reaper ticking would settle it; the fallback is running the reaper in the WorkerPool parent or as its own process.
    location: >-
      src/backend/app/jobs/worker.py (Reaper, LorekeeperWorker.work)
    severity: medium (unverified)
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

### 2026-11-01 — Review pass
- verdicts: 31 findings — high 0, medium 4, low 19, false 7, maybe-false 1
- findings:
  - `[medium]` `[patch]` VG: `_record_failure` ownership guard untested — added `taken_back` variants that raise retryable/terminal after the takeback; the row keeps the reaper's state.
  - `[low]` `[patch]` VG: reaper's own connection never distinguished from the outbox global — added a two-FakeServer test.
  - `[low]` `[patch]` VG: `repush` failure untested — added a test (with the stop-on-failure patch below).
  - `[low]` `[reject]` Blind: live snapshot taken before LPOS lets a just-dequeued Job get a second message — harmless (claim lets one attempt run; a duplicate id message meets a deleted hash and is skipped); a fix needs re-snapshot logic that still leaves a window.
  - `[false]` `[reject]` Blind: ownership by `worker_id` not attempt — the "worker alive, horse dead" row can only be re-claimed by that worker once its dead horse is gone; a worker never runs two horses, so no live earlier attempt exists to write late.
  - `[low]` `[patch]` Blind: retry delays rounded up to the reaper cadence — documented in the module docstring (by design: E0-Jobs.4 says retries rely on the reaper).
  - `[low]` `[patch]` Blind + Edge: slow pass can outlive the 25 s lock and overlap — documented as safe in `Reaper` (SKIP LOCKED, claim guard); the docstring's "one at a time" wording corrected.
  - `[low]` `[patch]` Blind: one LPOS per candidate — held ids now read once per queue per pass (LRANGE).
  - `[maybe-false]` `[defer]` Blind: thread in the RQ parent across horse forks could deadlock a horse — deferred (medium, unverified); settle with a soak test.
  - `[low]` `[reject]` Blind: interruptions use up attempts; three deploys during a long Job fail it — the AC prescribes "requeued if attempts remain, or failed interrupted".
  - `[low]` `[patch]` Blind: `Reaper.stop` neither joins nor closes — now joins (5 s) and closes the client it created.
  - `[low]` `[patch]` Blind: test gaps (repush failure, failure-path late outcome, batch limit) — covered by the tests above; other queues/lock expiry/_run loop not worth extra tests.
  - `[low]` `[reject]` Blind: the isolation fixture breaks parallel runs — the suite does not run in parallel (no xdist); the fixture only cancels rows other tests are done with.
  - `[low]` `[patch]` Blind: new log lines lack `kind`/`campaign_id` — `_owned` uses `_log_extra(job)`, `repush` logs `kind`.
  - `[low]` `[patch]` Blind: `connection or get_connection()` truthiness — now `is not None`.
  - `[false]` `[reject]` Blind: spec missing from the diff — by design, the spec goes only to the edge-case layer.
  - `[medium]` `[patch]` Edge: candidates limited to 500 before excluding RQ-held rows, so a large held backlog starves lost rows — the candidate select is unlimited (3 columns), held rows skipped, at most `REAPER_BATCH` pushed; test added.
  - `[false]` `[reject]` Edge: live-held stale rows fill the recover batch — live-held rows are at most one per RQ worker, far below 500.
  - `[medium]` `[patch]` Edge: a failing push per row could take 500 × 5 s — the pass now stops at the first failed push; test added.
  - `[low]` `[reject]` Edge: duplicate push of a dependent whose after-commit push is in flight — needs a dependent older than 60 s and a race of milliseconds; a duplicate message is harmless (claim).
  - `[low]` `[patch]` Edge: released dependents of a reaper-failed row push on the outbox global client — documented in the `Reaper` docstring (same Valkey; redis-py resets the pool in a forked child).
  - `[low]` `[reject]` Edge: requeue with `next_run_at = now` has no backoff for a horse-killing Job — detection already spaces attempts by ≥ 60 s and `max_attempts` caps it at 3.
  - `[low]` `[patch]` Edge claim: "nothing a forked horse uses" — docstring corrected (same patch as the release client).
  - `[low]` `[patch]` Edge claim: "one pass at a time" — wording corrected (same patch as the lock).
  - `[medium]` `[patch]` Edge claim: "none stays queued" under a large backlog — fixed by the unlimited candidate scan (same root cause as the batch finding).
  - `[false]` `[reject]` Intent: the FLUSHALL/registry cases are tested at the pass level, not the live stack — the desktop proof ran the live stack (`FLUSHALL` with a real worker container) and the forking test runs real RQ.
  - `[low]` `[reject]` Intent: the 30 s loop never runs for real in tests — the desktop proof logs show real ticks every 30 s ("job reaper: …" lines); a timed pytest would add 30 s+ for no extra signal.
  - `[low]` `[patch]` Intent: the web-restart test disposed the engine before the Job started — now disposes it while the Job is `running`, and a reaper pass meanwhile leaves it alone.
  - `[false]` `[reject]` Intent: the kill test kills the work horse, not the worker — the horse is the forked worker process that runs the Job; the desktop proof also stopped the whole worker container.
  - `[false]` `[reject]` Intent: registry rule widened beyond "absent from the registry" — required: a killed horse leaves its parent registered, so the literal rule never recovers it (Design Notes).
  - `[false]` `[reject]` Intent: code surface beyond worker.py/enqueue.py — the outbox connection argument and the wrapper guard are what make the re-push and "no duplicate done" work; compose is the story's restart concern.

## Design Notes

- RQ's registry alone cannot detect a killed horse: the parent worker survives and stays registered. So "absent from the registry" is widened to "no live worker has this Job as its current job". A worker whose container was SIGKILLed drops out of the registry when its key expires (90 s TTL while busy).
- A stale heartbeat is required as well: a Valkey flush empties the registry, but a live horse still beats every 10 s, so its row is never taken back.
- Requeued interrupted rows are due at once (`next_run_at = now`) and pushed in the same pass.

## Verification

**Commands:**
- `python -m pytest -q tests/jobs` (desktop container, `VALKEY_TEST_URL` set) -- expected: all pass, including the forking kill test.
- full `python -m pytest -q` -- expected: no regressions.
- `gh pr checks <n>` -- expected: all green.

## Auto Run Result

Status: done

**Summary:** A reaper pass (`reap`) and thread (`Reaper`) in every non-burst `LorekeeperWorker`, one pass per 30 s across workers (Valkey lock). It requeues or fails (`interrupted`) dead `running` attempts and re-pushes runnable `queued` rows RQ does not hold (retries past `next_run_at`, lost pushes, Valkey flushes, dependents of raw-SQL-finished or deleted dependencies). The wrapper's outcome writes now only land while the attempt owns the row.

**Files changed:**
- `src/backend/app/jobs/worker.py` -- `_owned` guard on `_finish`/`_record_failure`; reaper (`reap`, `_recover_running`, `_push_due`, `Reaper`); `LorekeeperWorker.work` starts it.
- `src/backend/app/jobs/enqueue.py` -- `repush` helper.
- `src/backend/app/jobs/outbox.py` -- `push(..., connection=None)`.
- `docker-compose.yml`, `docker-compose.prod.yml` -- worker `stop_grace_period: 60s`.
- `src/backend/tests/jobs/test_reaper.py` -- new: every I/O matrix row (fakeredis and real Valkey), plus a real forked work horse SIGKILLed mid-Job.

**Review:** 9 patches applied (`_record_failure` guard test; own-connection test; failed-push stops the pass + test; full candidate scan with held sets read once per queue and at most `REAPER_BATCH` pushes + test; docstrings for retry cadence, lock semantics and the outbox release client; `Reaper.stop` joins and closes its client; log fields; `is not None` connection check; web-restart test now restarts mid-run). 1 deferred (thread-and-fork, unverified). Rejected: see the triage log (false: ownership by attempt, live-row batch starvation, horse-vs-worker kill wording, widened registry rule; low and not worth the complexity: snapshot race, overlapping passes, duplicate dependent push, crash-loop backoff, test fixture under xdist, wider code surface, interruptions using attempts (the AC prescribes it); spec missing from the reviewer diff by design).

**Follow-up review:** true. Patched entries: 3 medium (failure-path ownership guard test; candidate scan no longer starved by RQ-held rows; pass stops at the first failed push), 9 low, 0 high. Unverified risk: the reworked `_push_due` (unlimited candidate select, LRANGE held sets, stop on failed push) has had no review pass of its own.

**Verification:**
- Desktop container (own Postgres + Valkey): `pytest tests/jobs` 32/32 for the reaper on first pass; full suite 1367 passed, 4 skipped; `lint-imports` 5 kept; `check_scoped_queries` and `check_memory_budget` OK.
- Real crash recovery on the desktop with `python -m app.jobs.worker` in a container (1 g limit): kill -9 of a work horse mid-Job → requeued `interrupted`, `done` on attempt 2 after ~68 s; `fail_once` retry → re-pushed when due, `done` on attempt 2; dependency row deleted → dependent released and `done`; dependency cancelled by raw SQL → dependent released and `done`, and the dependency's late outcome was dropped ("this attempt no longer owns the job"); `docker stop -t 60` mid-run → the 20 s Job finished in the grace period, the 150 s Job was killed, and after restart it was requeued and `done` on attempt 2; Valkey `FLUSHALL` with the worker down → re-pushed after 60 s, ran once. End state: 8 done, 1 cancelled (the raw-SQL dependency), 0 queued or running. Containers, network, image and files torn down.
- GitHub CI on PR #55: green (re-run after the review patches).

**Residual risks:** the thread-and-fork question (deferred); recovery latency is 60 s stale + up to 30 s tick (+ up to 90 s for a SIGKILLed container's RQ worker key to expire); worker healthcheck and worker logs in the admin log file stay out of scope, as E0-Jobs.3 recorded.
