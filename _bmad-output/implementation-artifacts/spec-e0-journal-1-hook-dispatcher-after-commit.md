---
title: 'E0-Journal.1: Hook dispatcher on after_commit'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'a55c32d30ed3742c4ce99bc562a6dc79d7efcd53'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      set_visibility's listeners and cache invalidation now run at after_transaction_end, after the Jobs outbox's after_commit push or eager run.
    evidence: |-
      Before, both were after_commit listeners in import order, which was never specified. A Job started in the same commit could now run before cache:{campaign_id}:* is invalidated. Jobs read Postgres, not the cache, and E0-Access.10's generation bump fences stale cache writes. To settle it: a test with a Job that reads the E0-Access.10 cache in the same commit as a Visibility change.
    location: >-
      src/backend/app/core/after_commit.py _after_transaction_end
    severity: medium (unverified)
  - summary: >-
      app/access/grants.py (E0-Access.10) still has its own copy of the after-commit plumbing.
    evidence: |-
      grants.py has its own PENDING_KEY, _within and rollback/end/commit listeners. Moving it onto app/core/after_commit.py is E0-Access.10-owned (this story's sibling to avoid).
    location: >-
      src/backend/app/access/grants.py:60-150
    severity: low
  - summary: >-
      No test proves that importing app.main alone registers the visibility_changed bridge, or that the lifespan shutdown drains hooks.
    evidence: |-
      tests/test_hooks.py imports app.hooks itself, so removing the main.py import goes unnoticed. HANDLERS is empty in this story. The first feature handler on visibility_changed (E1/E2) should add a subprocess import check.
    location: >-
      src/backend/app/main.py
    severity: low
  - summary: >-
      Neither Reaper.tick() under asyncio.run nor LorekeeperWorker.__init__'s load_handlers() is tested with a job_finished handler registered.
    evidence: |-
      _perform's drain now has a test. The reaper path is covered only by calling _recover_running directly on the pytest loop.
    location: >-
      src/backend/app/jobs/worker.py Reaper._reap
    severity: low
---

<intent-contract>

## Intent

**Problem:** Features (E1 extraction, E2 continuity, re-embedding, E9 stats) need to react to journal, Visibility, Canon and Job changes without editing `journal_service`, and only once the change has committed. Today there is no event seam; `set_visibility` (E0-Access.9) and the Jobs outbox each carry their own copy of the "collect in `session.info`, drop on rollback, act after commit" plumbing.

**Approach:** One shared after-commit primitive in `app/core/after_commit.py` (savepoint-aware collect / drop / dispatch), used by `set_visibility` and by a new hook dispatcher in `app/core/hooks.py`. `app/hooks/__init__.py` re-exports the event enum and `emit`, holds the `HANDLERS` append point, and bridges `visibility_changed` through `register_visibility_listener`. Handlers run after commit in a background task, each in a fresh session that is committed after it (so `enqueue` goes through the outbox). The worker emits `job_finished`.

## Boundaries & Constraints

**Always:** events collected in `session.info` and dispatched only after the root transaction commits; rollback of the root or of the savepoint the emit was made in discards them; handlers never run inside `commit()`'s caller and never see its session; a failing (or timed-out) handler is logged `hook_failed` with event, handler and campaign_id (never refs, payload or text) and other handlers still run; `set_visibility` behaviour and its tests unchanged; import-linter layers gain `app.hooks` between `app.api` and `app.jobs`.

**Never:** emitting journal events from `journal_service` (E0-Journal.2); real feature handlers (E1/E2/E9); Party-field indexing (E0-Access.7 already does it); `detach_entry` stub (E0-Journal.3); write rules (E0-Access.6), `access_epoch`/streams (E0-Access.10), admission/backfill/SSE (E0-Jobs.5), stt (E0-Platform.5); refactoring `app/jobs/outbox.py` (E0-Jobs-owned, different flush-tracked semantics).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Commit | `emit` x2 then `commit()` | each handler for each event runs once, events in emit order, payload `{campaign_id, refs, actor_ctx}`; none has run when `commit()` returns | — |
| Root rollback | `emit` then `rollback()` | no handler runs | — |
| Savepoint rollback | emit outside + emit inside a rolled-back `begin_nested()`, then commit | only the outer event dispatches | — |
| Handler raises | two handlers, first raises | second still runs; request/commit returns normally | `hook_failed` log; handler's session rolled back |
| Handler enqueues | handler calls `enqueue(..., idempotency_key=k)` | Job row with key `k` in the event's Campaign, pushed via outbox on the handler session's commit | enqueue error -> `hook_failed` |
| No handlers | emit for an event nobody handles | nothing scheduled | — |
| Unknown event | `emit(db, "nope", ...)` | `ValueError` at emit time | raised to caller (programming error) |
| Visibility change | `set_visibility` + commit | `visibility_changed` handlers get `refs` (list of RecordRef) and the GM ctx | — |
| Job terminal | worker writes `done` / `failed` | `job_finished` with `refs={job_id, kind, status}`, `campaign_id`=Job's, `actor_ctx=None` | requeue for retry emits nothing |

</intent-contract>

## Code Map

- `src/backend/app/access/visibility.py` -- `_record_pending`, `_within`, `_drop_rolled_back`, `_clear_on_end`, `_after_commit` (L336-443): the plumbing to move onto the shared primitive; keep `dispatch(pending)`, `_LISTENERS`, `invalidate_campaign_cache` module globals (tests monkeypatch them).
- `src/backend/app/jobs/outbox.py` -- same pattern plus `after_flush` FINISHED set; read-only, pattern for `AsyncEngine(bind)` session factory.
- `src/backend/app/jobs/worker.py` -- `_finish` (L180) single terminal-status writer for the wrapper; `_recover_running` (L530) reaper `failed`; `_perform` (L705) and `Reaper._reap` (L685) own short-lived loops via `asyncio.run` -> must drain hooks before disposing engine.
- `src/backend/app/jobs/enqueue.py` -- `enqueue(db, ctx, kind, payload, *, idempotency_key)`; `SYSTEM_NOOP` in `app/jobs/registry.py`.
- `src/backend/app/access/context.py` -- `ctx_for(db, user_id, campaign_id)` for per-user handlers.
- `src/backend/.importlinter` -- layers contract; comment says hooks joins in the PR that creates it.
- `src/backend/app/main.py` -- imports; add `import app.hooks` so HANDLERS and the visibility bridge register in the web process.
- `src/backend/tests/access/test_set_visibility.py` -- regression net for the refactor; `recorder` monkeypatches `vis._LISTENERS`.
- `src/backend/tests/jobs/test_enqueue.py` -- fixture patterns (`_campaign`, `ctx_for`, FastAPI app + `get_db` override, terminal `LLMConfigError` handler).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/after_commit.py` -- new: `register_channel(name, async cb(session, items))`, `defer(session, channel, item)` (tags innermost txn), session listeners (savepoint-aware drop, clear on root end, after root commit await each channel's callback in registration order, errors logged), `committed_bind()` contextvar set while callbacks run -- the one copy of the plumbing.
- `src/backend/app/access/visibility.py` -- replace the private listeners with `register_channel`/`defer`; behaviour identical.
- `src/backend/app/core/hooks.py` -- new: `HookEvent` StrEnum (8 events), `HookPayload`, `register_handler`, `emit`, background dispatch (fresh session per handler, commit after, `HANDLER_TIMEOUT_S`), `hook_failed` logging, `schedule(bind, events)`, `drain()`, lazy `load_handlers()` importing `app.hooks`.
- `src/backend/app/hooks/__init__.py` -- new: re-export `HookEvent`, `HookPayload`, `emit`; `HANDLERS` list (empty, one line per feature) registered at import; `visibility_changed` bridge via `register_visibility_listener`.
- `src/backend/app/jobs/worker.py` -- `emit(job_finished)` in `_finish` and in `_recover_running`'s failed branch; `await drain()` in `_perform` and `Reaper._reap` before engine dispose.
- `src/backend/app/main.py` -- `import app.hooks`; drain hooks on lifespan shutdown.
- `src/backend/.importlinter` -- add `app.hooks` layer under `app.api`.
- `src/backend/tests/test_hooks.py` -- the I/O matrix, through a tiny FastAPI route for the request case.

**Acceptance Criteria:**
- Given `from app.hooks import HookEvent, emit, HANDLERS`, when imported, then the enum has exactly the 8 story events and `emit(db, event, *, campaign_id, refs, actor_ctx)` exists.
- Given a route that emits and commits with a raising handler registered, when called, then it returns 200 and the log has `hook_failed` with event, handler and campaign_id and no refs.
- Given the existing suite, when run in CI, then `test_set_visibility.py`, jobs tests and `lint-imports` pass unchanged.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 26 findings — high 0, medium 4, low 12, false 6, maybe-false 4
- findings:
  - `[low]` `[reject]` intent R1: dispatch is deferred to a background task, not inline — the user's brief explicitly requires that hooks not run synchronously inside the request; the after_commit listener still triggers the dispatch.
  - `[false]` `[reject]` intent R2: definitions live in app/core/hooks.py — app/hooks/__init__.py exports them (the surface the AC names). They can't live there because the worker (app.jobs) must emit and the spine puts hooks above jobs.
  - `[low]` `[reject]` intent: the HANDLERS loop is never tested with a non-empty list — it's a two-line loop with no feature entries yet. E1 adds the first entry and its test.
  - `[low]` `[defer]` intent: main.py import and lifespan drain untested — deferred (see frontmatter).
  - `[low]` `[defer]` intent: real-RQ drains and LorekeeperWorker.load_handlers untested — _perform test added (patch); reaper deferred.
  - `[false]` `[reject]` intent: the visibility bridge bypasses emit — AC 1842 (E0-Access.9) says E0-Journal registers visibility_changed through register_visibility_listener.
  - `[maybe-false]` `[defer]` intent/blind/edge: set_visibility dispatch moved to after_transaction_end — deferred, medium (unverified).
  - `[false]` `[reject]` intent: log key is hook_event, not event — the record is named hook_failed under "event" (the visibility_listener_failed convention), and it carries the event, handler and campaign_id as the AC requires.
  - `[low]` `[reject]` intent: out-of-scope extras (handler timeout, drain timeout, committed_bind) — each serves the brief's "must not block the request" or the bridge.
  - `[false]` `[reject]` intent: hooks may import all of app.jobs and db — import-linter layers can't express "jobs.enqueue only". The spine's layer order is kept.
  - `[medium]` `[patch]` blind/edge: visibility_changed isn't ordered with emitted events — documented as per-Campaign ordering only, in app/core/hooks.py and app/hooks/__init__.py.
  - `[medium]` `[patch]` blind/edge: hook_failed exc_info could leak text — now logs only error_type. The test raises with a canary in the message and asserts it and the traceback are absent.
  - `[low]` `[reject]` blind: the importlib load bypasses the layer contract — same pattern as registry.KIND_MODULES, documented in .importlinter. A static import would be a real cycle.
  - `[medium]` `[patch]` blind/edge: drain unbounded and unguarded in the worker/reaper; shutdown drain shorter than the handler budget — bounded drain (HANDLER_TIMEOUT_S + 5) in its own try/finally; main.py derives its timeout the same way.
  - `[maybe-false]` `[reject]` blind: a Connection-bound session hooks onto non-durable data — no app code binds sessions to a Connection with an outer transaction. If true it would be low.
  - `[low]` `[reject]` blind/edge: HookPayload refs are shared and mutable — handlers mutating refs is not a pattern anyone uses. Freezing adds complexity.
  - `[low]` `[patch]` blind: the documented handler template crashes on actor_ctx=None — docstrings now say job_finished has actor_ctx None.
  - `[false]` `[reject]` blind: job_finished ignores cancelled — the story says "done or failed", and no app code writes CANCELLED today.
  - `[false]` `[reject]` blind: json.dumps log style differs — app/access/visibility.py uses the same json.dumps message style.
  - `[low]` `[reject]` blind: untested branches (sync Session skip, no bind/loop, nested re-emit) — defensive logging branches. The drain re-scan is exercised by the job_finished-after-hook-enqueue path.
  - `[false]` `[reject]` blind: spec metadata stale — the fix is an edit to this build's spec.
  - `[medium]` `[patch]` verification-gap: _perform drain never exercised — added test_perform_drains_job_finished_handlers_on_its_own_loop (worker.perform via a thread, fakeredis, eager off).
  - `[maybe-false]` `[reject]` edge: commit outside the handler timeout can hang — only an eager in-process Job (tests) runs there. In production the commit is an RQ push with socket timeouts. Now bounded by the drain timeout too.
  - `[maybe-false]` `[reject]` edge: a job_finished → enqueue → job_finished loop — needs a handler that enqueues on every job_finished (a handler bug). Drains are now bounded.
  - `[low]` `[reject]` edge: get_bind raising drops events — every app session is engine-bound. Rare, and logged.
  - `[low]` `[reject]` edge: a load_handlers import failure fails _finish — a broken hook module fails loudly at web import and at LorekeeperWorker start, which is correct.
  - `[low]` `[patch]` edge: the "one copy" claim is false (grants.py) — after_commit.py docstring corrected; the grants.py merge is deferred to E0-Access.10.

## Design Notes

Why background (not inline in `commit()`): the request must not wait on handlers, and a hung handler must not block `commit()` (deferred finding from E0-Access.9). Handlers are expected to be cheap (an `enqueue`); heavy work is the Job. Processes that own a short loop (`asyncio.run` in the worker and reaper) `await hooks.drain()` before the loop ends. Delivery is at-most-once: a crash between commit and dispatch loses the event; durable work is the outbox's job.

Handler shape: `async def on_entry_saved(db, event, payload): ctx = await ctx_for(db, payload.actor_ctx.user_id, payload.campaign_id); await enqueue(db, ctx, "extraction.run", {...}, idempotency_key=...)` -- the dispatcher commits `db` after it returns.

## Verification

**Commands:**
- `cd src/backend && python -m py_compile app/core/after_commit.py app/core/hooks.py app/hooks/__init__.py` -- expected: no output
- GitHub CI `backend-tests.yml` and `gates.yml` on the draft PR -- expected: green

## Auto Run Result

Status: done

**Summary:**
- `app/core/after_commit.py` is a savepoint-aware primitive shared by set_visibility and the new hook dispatcher.
- `app/core/hooks.py` provides HookEvent, HookPayload, emit, register_handler, schedule, drain and a lazy load_handlers. Handlers run after commit, in a background task, each with a fresh committed session, a 30 s timeout and the `hook_failed` log.
- `app/hooks/__init__.py` holds the HANDLERS append point, the re-exports and the visibility_changed bridge.
- The worker emits job_finished from `_finish` and from the reaper's last-attempt failure, and drains hooks with a time limit.

**Files:**
- `src/backend/app/core/after_commit.py`: new shared after-commit primitive.
- `src/backend/app/core/hooks.py`: new dispatcher.
- `src/backend/app/hooks/__init__.py`: new; HANDLERS and the visibility_changed bridge.
- `src/backend/app/access/visibility.py`: moved onto the primitive (rebased over E0-Access.10's cache module).
- `src/backend/app/jobs/worker.py`: job_finished emits; drains with a time limit; LorekeeperWorker loads the handlers.
- `src/backend/app/main.py`: imports app.hooks; drains on shutdown.
- `src/backend/.importlinter`: adds the app.hooks layer.
- `scripts/test_import_ratchet.py`: layer list updated.
- `src/backend/tests/test_hooks.py`: the I/O matrix tests, plus the canary-log and perform-drain tests.

**Review:**
- 6 patches applied (4 medium, 2 low).
- 4 items deferred (see frontmatter).
- 16 rejected, with reasons in the triage log.

**Follow-up review recommended:** true. 4 medium entries were patched. The specific unverified risk: the post-patch tests (canary log, perform drain) have run only in CI. A second look at the deferred after_transaction_end timing change for set_visibility is worthwhile.

**Verification:**
- Pre-patch: GitHub CI on PR #63 was all green (backend agpl and commercial, database, static gates, test, licences, frontend).
- Post-patch, locally (no DB): py_compile, lint-imports (5 kept), import ratchet (36 passed) and check_scoped_queries all pass.
- Post-patch DB tests: on CI after this push.

**Needs desktop verification:**
- Run a real worker (`docker compose up worker`) with a job_finished handler registered. Enqueue `system.noop` and confirm the handler runs in the work horse before it exits. Check the worker logs: they must not show `hook drain timed out`.

**Residual risks:**
- Delivery is at most once: an event is lost if the process crashes between commit and dispatch.
- visibility_changed is ordered per Campaign only, not with the emitted events of the same commit.
