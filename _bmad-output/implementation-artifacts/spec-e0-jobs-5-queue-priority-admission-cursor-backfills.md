---
title: 'E0-Jobs.5: Queue priority, per-model serialisation, cursor backfills and Live admission'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '8e7fd97b574409f9019baa7edfc972024a340592'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Workers already listen `interactive` > `onsave` > `backfill`, but nothing proves the one-Job bound, nothing stops two heavy-model Jobs (nli/stt/tts/ocr/cpu_heavy) running at once, a Live Session cannot keep background model work off the box, there is no cursor-backfill helper (one row, per-entry progress, re-enqueue itself), and nothing runs `data_backfills` rows (RC-2, needed by E0-WorldCore.2/.7).

**Approach:** `app/jobs/admission.py` (resource leases `res:<resource>`, named holds `hold/renew/release`, and a short-delay push set), `app/jobs/backfill.py` (`run_cursor`, `register_backfill`, the `data_backfills` runner), and wrapper hooks in `app/jobs/worker.py`: admission before the handler (defer = back to `queued`, attempt not used), and a continuation outcome for cursor Jobs (back to `queued`, pushed again at once with the same `job_id`). The runner runs on every reaper tick (the first tick is at worker start).

## Boundaries & Constraints

**Always:**
- Postgres stays the authority; RQ messages carry only `job_id`. A push of a Job id from inside its own running RQ job uses a distinct RQ id `<job_id>_<hex>` (RQ ids allow `[A-Za-z0-9_-]`); the reaper's "RQ holds it" checks map RQ ids back to the Job id (`outbox.job_id_of`).
- Resource leases: kinds whose `resources` include any of `nli, stt, tts, ocr, cpu_heavy` take `res:<r>` for each (SET NX, value = Job id, TTL = `rq_timeout(kind)`), released compare-and-delete after the outcome is written. Not admitted → `queued`, `next_run_at` = now + 5 s, `stage = "Waiting for the model"`, `attempts` restored (a wait is not an attempt), run state cleared. `llm` is never leased here.
- Live admission: while `lease:live` exists, a kind whose `resources` intersect `{llm, nli, tts, cpu_heavy}` and is not `live_safe` is put back with `next_run_at` + 15 s, `stage = "Paused for the Live Session"`; checked before resource leases. `hold(name, ttl)` sets it (refreshing, not exclusive), `renew(name)` re-sets it with its stored TTL, `release(name)` deletes it.
- A deferred row is pushed again when due through the delayed set `lorekeeper:jobs:delayed` (sorted by due time), drained every second by each non-burst worker's reaper thread; the reaper's `next_run_at` re-push stays the backstop. Under `JOBS_EAGER` nothing is pushed (the row stays `queued`).
- Valkey unavailable (not initialised, or a Redis error) → admission fails open with a warning log, like `llm_gate`.
- `run_cursor(job, ctx, db, *, select_next, process_one)`: `select_next(db, ctx, cursor) -> CursorStep(item, cursor, total) | None`; on a step it calls `process_one(db, ctx, item)`, stores `payload.cursor`/`payload.done`, sets `progress = done/total` and `stage = "Entry {done} of {total}"`, updates `data_backfills.cursor.entries[<campaign_id>]` when the payload names a `backfill`, and asks the wrapper to continue. The entry's writes, cursor and `queued` row commit together. A continuation resets `attempts` to 0 and clears the error; `None` from `select_next` ends the Job `done`.
- Runner: `register_backfill(name, kind)` (kind registered, queue `backfill`). For every `data_backfills` row in `queued` (the schema's "pending": the status CHECK is `JobStatus`) or `running`: snapshot the Campaigns created at or before the row's `updated_at` into `cursor.campaigns` on first sight; enqueue the kind per Campaign not yet in `cursor.jobs` with `ctx_for(owner, campaign)`, payload `{"backfill": name}`, key `backfill:{name}:{campaign_id}`; record finished (`done`/`cancelled`/deleted Job, deleted Campaign) and `cursor.failed`; status `running`, then `done` when every Campaign is terminal. One transaction per row (`FOR UPDATE SKIP LOCKED`). Unregistered name → log `backfill_unregistered` once per process, row untouched.
- The Campaign-owner enumeration lives in `app/access/owners.py` (CI-8: registered `Campaign` reads only inside `app/access/`).

**Never:** no `rq suspend` anywhere (grep test); no RQ scheduler or RQ retry; no new dependency, migration or route; no pubsub/SSE (E0-Jobs.6/7); no change to `app/access/write.py`/`visibility.py`; no change to `llm_gate`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Priority | 5 backfill queued, 1 onsave pushed while the 1st backfill runs | start order B1, O, B2..B5 | — |
| Priority at rest | both pushed before start | O first | — |
| Lease contention | two `nli` Jobs run concurrently | one `done`; other `queued`, +5 s, "Waiting for the model", attempts 0, in delayed set | — |
| Multi-resource | kind `{nli, llm}` | only `res:nli` taken | — |
| Lease released | after any outcome (done, failed, retry) | `res:nli` gone; another Job's lease never deleted | — |
| Live held | non-safe `{llm}` kind, `lease:live` set | `queued`, +15 s, paused stage | — |
| Live-safe / unaffected | `live_safe` kind, or `{ocr}`/`{}` kind | runs | — |
| Live lapsed | TTL expired or released | runs | — |
| Delayed drain | entry due | pushed once (RQ id `<id>_<hex>`); not yet due → stays | — |
| Cursor step | 3 items | 3 steps on one row; progress 1/3…; stage "Entry 2 of 3"; final `done`, progress 1 | — |
| Cursor step fails | `process_one` raises | entry writes roll back, cursor unchanged, normal retry | — |
| Continuation push | non-eager | row `queued`, pushed with a distinct RQ id; reaper sees it held | — |
| Runner | 2 Campaigns, row `queued` | 2 Jobs (Owner ctx, key `backfill:{name}:{cid}`); later ticks: no new Jobs; row `done` | — |
| Runner failed | one Job `failed` | `cursor.failed` = [cid]; row `done`; Job visible to that Owner | — |
| Runner restart | cursor.jobs already set | no second Job for a Campaign | — |
| Late Campaign | created after the row | not enqueued | — |
| Unregistered | no kind for name | logged once, row stays `queued` | — |
| Valkey missing | eager tests, no client | admission no-op | warning |

</intent-contract>

## Code Map

- `src/backend/app/jobs/worker.py` -- `run_job`/`_run_claimed` (admission after `_prepare`, before the handler; continuation outcome; lease release in `finally`), `_owned` guard reused for every new outcome write, `_live_workers`/`_rq_queued_ids` (map RQ ids with `outbox.job_id_of`), `Reaper._run`/`tick`/`_reap` (1 s drain of the delayed set; backfill runner after `reap`), `main` (queue order already `JobQueue` order).
- `src/backend/app/jobs/outbox.py` -- `push(..., rq_id=None)`, new `job_id_of`, `_dispatch_one` eager loop while a cursor Job continues.
- `src/backend/app/jobs/admission.py` -- new: `LEASED_RESOURCES`, `LIVE_BLOCKED`, `hold/renew/release/is_held`, `acquire_resources/release_resources`, `defer_push`, `drain_delayed`.
- `src/backend/app/jobs/backfill.py` -- new: `CursorStep`, `run_cursor`, `register_backfill`, `BACKFILLS`, `run_backfills`.
- `src/backend/app/access/owners.py` -- new: `campaign_owners(db, *, created_before)`.
- `src/backend/app/jobs/registry.py` -- `RESOURCES` (read-only), `KIND_MODULES` docstring; `app/jobs/__init__.py` docstring/exports.
- `src/backend/app/db/models/job.py` -- `DataBackfill` (status = `JobStatus`, `updated_at` onupdate), unmapped Job attributes pattern (`dependency_status`) for the new `_continue` flag.
- `src/backend/app/core/valkey_client.py` -- `get_valkey` raises RuntimeError when not initialised (fail-open trigger).
- `src/backend/tests/jobs/test_reaper.py`, `test_worker.py` -- fixtures to copy (`conn`, `_campaign`, `_job`, `_InProcessWorker`).
- `scripts/check_scoped_queries.py` -- CI-8: `Campaign` select outside `app/access/` fails; `Job`/`DataBackfill` allowed in `app/jobs/`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/owners.py` -- owner enumeration -- CI-8.
- `src/backend/app/jobs/admission.py` -- leases, holds, delayed set -- AC 2, 4.
- `src/backend/app/jobs/backfill.py` -- `run_cursor`, runner -- AC 3, 5.
- `src/backend/app/jobs/outbox.py`, `worker.py` -- RQ-id mapping, admission and continuation in the wrapper, reaper thread drain + runner -- wiring.
- `src/backend/tests/jobs/test_admission.py`, `test_backfill.py`, `test_priority.py` -- every matrix row, fake and real Valkey; `rq suspend` grep test.
- `src/backend/tests/ev4/test_job_rows.py` -- rows this story creates (runner Jobs with progress, deferred rows) are invisible to a Player/cross-GM through `scoped_select(Job, ctx)`, a Player's own Job stays visible to them.

**Acceptance Criteria:**
- Given the full backend suite on CI, when it runs, then it is green with no regressions and the static gates (import-linter, CI-8, memory sum) pass.
- Given a real worker on the desktop (own Postgres + Valkey), when two `cpu_heavy` test Jobs and a cursor Job run, then one heavy Job waits "Waiting for the model" and runs ~5 s later, and the cursor Job shows one row stepping through its entries to `done`.

## Spec Change Log

## Review Triage Log

## Design Notes

- Distinct RQ ids: the running RQ job has id = Job id and is deleted after it returns (`result_ttl=0`), so re-pushing the same id from inside it would be deleted with it. The first push keeps id = Job id.
- Leases are not renewed by the heartbeat: TTL = `timeout_s + 60` (the RQ backstop), so a killed horse's lease lapses no later than its RQ kill.
- `hold` is not exclusive: two Live Sessions share `lease:live`; one `release` lifts it until the other's next `renew` (E4 renews well within 90 s).

## Verification

**Commands:**
- `python -m pytest -q tests/jobs tests/ev4/test_job_rows.py` (desktop container, `VALKEY_TEST_URL`) -- expected: all pass.
- `lint-imports`, `python scripts/check_scoped_queries.py` -- expected: OK.
- `gh pr checks <n>` -- expected: green.
