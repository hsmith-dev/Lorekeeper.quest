---
title: 'E0-Jobs.6: core/pubsub.py and core/sse.py'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '022cc28a38331b357971c6c76fde0dfd5f3506ef'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** There is no shared publisher or SSE helper, so each feature (Job progress, campaign events, Live, recaps) would invent its own channel, polling endpoint and stream framing, and nothing guarantees a stream pings, defeats proxy buffering or closes when access is revoked (AD-5, AD-13).

**Approach:** Add `app/core/pubsub.py` (the only publisher, exactly three channels plus matching subscribe generators, with Valkey-backed leading+trailing throttles) and `app/core/sse.py` (`sse_response(gen, *, ctx)`: headers, 15 s ping, bounded queue, closes on `grant_watch`). Publish a `job` event after every commit that changes a Job row.

## Boundaries & Constraints

**Always:**
- Only `publish_job(campaign_id, event)`, `publish_campaign_event(campaign_id, domain, id|None)` and `publish_live(live_session_id, msg)` publish, to `jobs:{campaign_id}`, `campaign:{campaign_id}:events`, `live:{id}:out`. A guard test fails on any `.publish(`/`.spublish(`/`PUBLISH` call in `app/` outside `app/core/pubsub.py` — the single exception is `app/access/grants.py` (the `access:` channel is AD-13's, published only by app/access, Decision B1-D7).
- Subscribing likewise only in `pubsub.py` (and `app/access/grants.py`).
- Job event = `{job_id, kind, status, progress, stage, eta_seconds, error_code, error_message, result_ref}`, published after commit from the committed row; status changes never throttled; progress-only at most one per Job per second (trailing edge keeps the latest).
- `publish_campaign_event(..., id=None)`: at most one per (Campaign, domain) per 30 s, with one trailing publish so a later downgrade is never lost.
- `sse_response`: `Content-Type: text/event-stream`, `X-Accel-Buffering: no`, `Cache-Control: no-cache`; `event: ping` every 15 s; closes within 2 s of the ctx grant's `access:` message; bounded memory for a slow client; no Valkey subscriber left after disconnect.
- `app.core` must not import `app.access` (.importlinter): `app/access/__init__.py` registers `grant_watch` into `sse` at import; `sse_response` fails closed (RuntimeError) if none is registered. No `access:`/`cache:` literals outside app/access.
- Publish errors / no Valkey: logged, never raised (2 s timeout).

**Never:** migrate the chat stream or admin install stream (not in the ACs); add routes (`/api/jobs/stream` is E0-Jobs.7, `/api/campaigns/{id}/events` E0-Access.11); frontend `lib/sse.ts` (E0-Jobs.9); filter by visibility in the publisher (consumers do); touch the LLM gate.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Job status change | worker commits running/done/failed/queued | one `job` event on `jobs:{cid}` with current row state | none |
| Progress burst | 5 `job.report` within 1 s | 1 immediate + 1 trailing (latest values) | trailing cancelled by a status event |
| Rollback | Job change rolled back | nothing published | — |
| Unkeyed invalidation burst | 3 × `publish_campaign_event(c, "visibility", None)` in 30 s | 1 now, 1 at window end | — |
| Stream event | message on subscribed channel | client receives `event: <name>` frame | bad JSON skipped + logged |
| Grant change | `access:` publish for ctx grant (poll 30 s) | `event: access_changed` then stream ends < 2 s | watch failure → stream ends (fail closed) |
| Client disconnect | client closes | gen closed, pubsub + grant_watch unsubscribed (`PUBSUB NUMSUB` 0) | cleanup bounded 2 s |
| Slow client | send blocked, producer fast | queue ≤ SSE_QUEUE_MAX, pulled items bounded, stream ends | blocked send > SEND_TIMEOUT_S → abort |
| No Valkey | `get_valkey` raises | publish no-op; listen gen ends | logged |

</intent-contract>

## Code Map

- `src/backend/app/access/grants.py:311-397` -- `grant_watch(*ctxs, bind=)`, `_check_watchable`, `_subscribe`/`_close` pattern to mirror; publishes `access:` (allowed exception).
- `src/backend/app/access/__init__.py` -- add one registration of `grant_watch` + check into `app.core.sse`.
- `src/backend/app/core/valkey_client.py` -- `get_valkey()` (RuntimeError when absent), `set_valkey` for tests.
- `src/backend/app/core/after_commit.py` -- `register_channel`/`defer`/`committed_bind`: use for job events (no hand-rolled listener plumbing).
- `src/backend/app/jobs/outbox.py:224-233` -- `after_flush` history pattern (`attributes.get_history`) for Job rows.
- `src/backend/app/jobs/worker.py` -- `_claim` (raw `sa.update` → queue explicit status event), `_reporter.write` (raw update in own session → queue progress-only event); other writers are ORM (listener covers).
- `src/backend/app/api/routes/chat.py:505-595` -- reference for racing a gen against `grant_watch` and cancel/cleanup; read-only.
- `src/backend/tests/access/test_grants.py:56-70,845-875` -- `valkey`/`no_valkey` fixtures, reserved-literal guard; `VALKEY_TEST_URL` real-Valkey pattern (`tests/test_llm_gate.py:25-38`).
- `.importlinter` -- layers api > hooks > jobs > services > access > schemas > db > core.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/pubsub.py` -- channel registry, three publishers, `listen_jobs`/`listen_campaign_events`/`listen_live` async generators (subscribe on first iteration, unsubscribe+close in finally), throttle helper (Valkey `SET NX PX` leading + in-process trailing task) -- AD-5 single publisher.
- `src/backend/app/core/sse.py` -- `format_event`, `register_close_watch`, `SSEResponse(StreamingResponse)` overriding `stream_response` (pump task → bounded queue, ping timer, watch task, send-with-timeout racing the watch), `sse_response(gen, *, ctx, bind=None, headers=None)` -- AD-5 one SSE pattern.
- `src/backend/app/jobs/events.py` -- `job_event(job)`, `queue_job_event(session, job_id, *, status_changed)`, `after_flush` listener on Job rows, after-commit channel `job_events` that reads the committed rows and calls `publish_job` -- job events after commit.
- `src/backend/app/jobs/__init__.py`, `src/backend/app/jobs/worker.py` -- import events (installs listener); explicit queue in `_claim` and `_reporter.write`.
- `src/backend/app/access/__init__.py` -- `sse.register_close_watch(grant_watch, check=_check_watchable)`.
- `src/backend/tests/test_pubsub.py`, `src/backend/tests/test_sse.py` -- matrix above; fake + real Valkey (`VALKEY_TEST_URL`) parametrisation; in-process uvicorn on 127.0.0.1 for the end-to-end stream and disconnect tests (stopped in teardown); PUBLISH/subscribe AST guard.

**Acceptance Criteria:**
- Given the repo, when the guard test scans `app/`, then any publish/subscribe outside `pubsub.py` (and grants.py) fails it.
- Given a test route returning `sse_response(listen_jobs(cid), ctx=ctx)`, when a client connects and `publish_job` runs, then the client receives the `job` frame; when the ctx's grant changes, then `event: access_changed` arrives and the stream ends within 2 s; when the client disconnects, then `PUBSUB NUMSUB` for `jobs:{cid}` and the grant channel is 0 (real Valkey in CI).
- Given a worker run of a Job, when it commits, then `jobs:{cid}` receives running and done events with the row's fields.

## Spec Change Log

## Review Triage Log

## Design Notes

- Job events read the row after commit (one SELECT per committing session, skipped when no Valkey) instead of snapshotting at flush: with JOBS_EAGER (and a fast RQ worker) the Job runs inside the enqueuing commit, so a flush snapshot "queued" would be published after "done". Reading current state makes the last event correct.
- Stream end on grant change sends `event: access_changed` `{"detail":"Not found"}` (the watch also fires on upgrades): clients reconnect once and stop on 401/404 (E0-Jobs.9). A `poll_failed` watch ends the stream without that event so a transient DB error doesn't look like revocation.
- Backpressure: the pump puts frames with `put_nowait`; a full queue ends the stream (client reconnects and refetches) — memory is bounded by `SSE_QUEUE_MAX` frames; Valkey's own `client-output-buffer-limit pubsub` bounds the server side.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed files>` -- expected: no errors
- GitHub CI `backend-tests.yml` (pytest with Postgres + Valkey, `VALKEY_TEST_URL`) and gates (import-linter) -- expected: green, no regressions
