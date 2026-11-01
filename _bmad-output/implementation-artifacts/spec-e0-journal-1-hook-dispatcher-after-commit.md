---
title: 'E0-Journal.1: Hook dispatcher on after_commit'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: 'a55c32d30ed3742c4ce99bc562a6dc79d7efcd53'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred: []
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

## Design Notes

Why background (not inline in `commit()`): the request must not wait on handlers, and a hung handler must not block `commit()` (deferred finding from E0-Access.9). Handlers are expected to be cheap (an `enqueue`); heavy work is the Job. Processes that own a short loop (`asyncio.run` in the worker and reaper) `await hooks.drain()` before the loop ends. Delivery is at-most-once: a crash between commit and dispatch loses the event; durable work is the outbox's job.

Handler shape: `async def on_entry_saved(db, event, payload): ctx = await ctx_for(db, payload.actor_ctx.user_id, payload.campaign_id); await enqueue(db, ctx, "extraction.run", {...}, idempotency_key=...)` -- the dispatcher commits `db` after it returns.

## Verification

**Commands:**
- `cd src/backend && python -m py_compile app/core/after_commit.py app/core/hooks.py app/hooks/__init__.py` -- expected: no output
- GitHub CI `backend-tests.yml` and `gates.yml` on the draft PR -- expected: green
