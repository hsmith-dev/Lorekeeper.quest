---
title: 'E0-Jobs.6: core/pubsub.py and core/sse.py'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '022cc28a38331b357971c6c76fde0dfd5f3506ef'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Streams have no "subscribed" signal or event ids, so events published between a client's REST snapshot and the listener's SUBSCRIBE are lost without trace.
    evidence: |-
      sse.py frames carry no `id:` and no ready event; the pump subscribes on its first iteration, after the headers are sent. E0-Jobs.7 / E0-Access.11 / E0-Jobs.9 should define the resync contract (for example, a `ready` event after SUBSCRIBE that makes the client refetch).
    location: >-
      src/backend/app/core/sse.py (stream_response), src/backend/app/core/pubsub.py (_listen)
    severity: medium
  - summary: >-
      job events are published inside commit(), so a hung Valkey can delay a commit that touches N Jobs by about 2-4 s x N.
    evidence: |-
      events._on_commit runs through after_commit (await_only) and publishes one at a time, each capped by PUBLISH_TIMEOUT_S (plus _acquire for progress). The grant publish works the same way. If a reaper batch is ever seen to stall, consider one overall budget per commit, or hand the publish off to a task.
    location: >-
      src/backend/app/jobs/events.py (_on_commit)
    severity: medium
  - summary: >-
      The close contract is: `event: access_changed`, then the client reconnects and stops on 401/404. The brief expects lib/sse.ts to stop retrying on the event itself.
    evidence: |-
      grant_watch also fires on an upgrade, so stopping on the event would strand a promoted user. lib/sse.ts belongs to E0-Jobs.9: on `access_changed` it should reconnect once, straight away, and stop on 401/404. The admin model-install stream also still uses a raw StreamingResponse.
    location: >-
      src/backend/app/core/sse.py; src/frontend/src/lib/sse.ts (E0-Jobs.9)
    severity: medium
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

### 2026-11-01 — Review pass
- verdicts: 35 findings — high 0, medium 9, low 18, false 4, maybe-false 4
- findings:
  - `[low]` `[reject]` Blind: a status event in one process can't cancel another process's trailing progress. Progress trails exist only in the work horse running that Job. Reaper and API status writes come after the horse is gone, or are for queued Jobs. A fix would need cross-process sequence state.
  - `[medium]` `[patch]` Blind: with k processes, losing trails re-send about 30 s apart. `_run_trail` now drops the trail when it loses the acquire after the window, because the other process's publish is newer. Test added.
  - `[medium]` `[patch]` Blind: the API never flushes pending trails on shutdown. The lifespan now awaits `pubsub.flush_pending()` before `close_valkey()`.
  - `[medium]` `[patch]` Blind: the reaper events were claimed but never shown. The reaper writes go through the ORM (`_recover_running`), so the listener sees them. A DB test now runs `Reaper.tick` and asserts the queued/interrupted event.
  - `[low]` `[reject]` Blind: `set_valkey` swaps the global client from the reaper thread. The parent worker process has no other async Valkey user, and a forked horse installs its own in `_perform`. No harm shown.
  - `[medium]` `[defer]` Blind: no ids and no ready event, so events in the gap between snapshot and subscribe are lost. The consumer stories own the resync contract.
  - `[low]` `[reject]` Blind: no Valkey gives a reconnect storm. Compose always runs valkey, and lib/sse.ts (E0-Jobs.9) backs off 1-30 s.
  - `[low]` `[patch]` Blind: the no-Valkey stream test asserts no ping. Renamed to `test_no_valkey_the_stream_ends`.
  - `[low]` `[patch]` Blind: `format_event` uses `splitlines`, which splits on non-SSE line breaks, and it rejects ':' in event names. It now splits only on CR LF, CR or LF, and rejects only CR/LF in names. Tests added.
  - `[medium]` `[patch]` Blind: `_settle` swallows the caller's own cancellation. It now re-raises when `current_task().cancelling()` is non-zero. The cleanup settles every task, then re-raises (the deferred pattern).
  - `[low]` `[reject]` Blind: the shield doesn't cover a native cancel. The deferred-cancel cleanup above covers this, and what remains is negligible.
  - `[low]` `[reject]` Blind: an aborted send leaves an unfinished response and a uvicorn log line. This is intentional for a stuck client, and the connection is closed either way.
  - `[low]` `[patch]` Blind: `register_close_watch` replaces or drops the check. It now raises unless the watch and the check are identical. Test added.
  - `[low]` `[reject]` Blind: the AST guard can false-positive, or miss a `getattr` call. A false positive fails CI loudly, and getting around it with `getattr` would be deliberate. It is good enough for a ratchet.
  - `[low]` `[reject]` Blind: a SELECT runs for every progress commit, before the throttle. Handlers report once per entry, not in tight loops, so the cost is negligible.
  - `[false]` `[reject]` Blind: deleted Jobs get no event. Jobs are deleted only by the DB-level Campaign cascade, which closes streams through the grant watch.
  - `[false]` `[reject]` Blind: `publish_job(job_id=None)` falls through. No caller passes None; events always carry the row id.
  - `[low]` `[patch]` Blind: the per-Job throttle test waits only 0.2 s, which is flaky. It now uses a 30 s window and a 2 s wait.
  - `[medium]` `[patch]` Blind: the docstring example holds the request session for the whole stream. The example now closes the session before returning, and says why.
  - `[low]` `[reject]` Edge: an older SET-NX winner can cancel a newer trail. That needs two publishes of the same key in one process within microseconds, and the next status or progress carries the current state anyway.
  - `[low]` `[reject]` Edge: `flush_pending` misses an in-flight trail. A final status event follows in the horse, so the lost progress doesn't matter.
  - `[low]` `[patch]` Edge: callers could override Content-Type or Content-Length. Both are now fixed headers.
  - `[low]` `[reject]` Edge: a burst of more than 256 buffered messages ends a fast client's stream. No producer emits at that rate (1 progress/s per Job), and the client reconnects.
  - `[low]` `[reject]` Edge: when the watch interrupts a blocked send, `access_changed` is skipped. A client that can't take a frame can't take that one either; it reconnects into the 404.
  - `[maybe-false]` `[reject]` Edge: the same watch registered with a different check. This duplicates the `register_close_watch` row and was patched there.
  - `[low]` `[patch]` Edge: the reporter queued an event even when its UPDATE matched 0 rows. It now queues only when rowcount is non-zero.
  - `[false]` `[reject]` Edge: deleted Jobs in `session.deleted`. Same refutation as the Blind row.
  - `[low]` `[patch]` Edge: if `valkey.aclose()` fails in the reaper, `engine.dispose()` is skipped. The close is now wrapped and logged.
  - `[medium]` `[patch]` VerifGap: the reaper events were untested. DB test added, as above.
  - `[medium]` `[patch]` VerifGap: no test observed the ORM status-vs-progress choice. DB test added with a 30 s window and a held key.
  - `[medium]` `[defer]` VerifGap (other): publishes inside commit can stall when Valkey hangs.
  - `[maybe-false]` `[defer]` Intent: the brief wants the client to stop on the access-closed event, but the diff uses reconnect-then-404. lib/sse.ts belongs to E0-Jobs.9; recorded in the deferred note on the close contract.
  - `[maybe-false]` `[reject]` Intent: the admin install stream isn't migrated to `sse_response`. That isn't in the story's ACs; it's noted in the deferred item.
  - `[false]` `[reject]` Intent: the brief says pubsub.py already exists and should be extended. It didn't exist on main, so it was created new.
  - `[maybe-false]` `[reject]` Intent: the "Needs desktop verification" list is missing. It was written at finalize, in the Auto Run Result and in the final report.

## Design Notes

- Job events read the row after commit (one SELECT per committing session, skipped when no Valkey) instead of snapshotting at flush: with JOBS_EAGER (and a fast RQ worker) the Job runs inside the enqueuing commit, so a flush snapshot "queued" would be published after "done". Reading current state makes the last event correct.
- Stream end on grant change sends `event: access_changed` `{"detail":"Not found"}` (the watch also fires on upgrades): clients reconnect once and stop on 401/404 (E0-Jobs.9). A `poll_failed` watch ends the stream without that event so a transient DB error doesn't look like revocation.
- Backpressure: the pump puts frames with `put_nowait`; a full queue ends the stream (client reconnects and refetches) — memory is bounded by `SSE_QUEUE_MAX` frames; Valkey's own `client-output-buffer-limit pubsub` bounds the server side.

## Verification

**Commands:**
- `uv run --python 3.11 python -m py_compile <changed files>` -- expected: no errors
- GitHub CI `backend-tests.yml` (pytest with Postgres + Valkey, `VALKEY_TEST_URL`) and gates (import-linter) -- expected: green, no regressions

## Auto Run Result

Status: done

**Summary:**
- **Publisher:** `app/core/pubsub.py` is the only publisher, with exactly three channels: `jobs:{cid}`, `campaign:{cid}:events` and `live:{id}:out`. It has matching `listen_*` subscribers.
- **Throttles:** these are leading plus trailing and backed by Valkey. Job progress is limited to 1 per second per Job. Unkeyed invalidations are limited to 1 per 30 s per Campaign and domain.
- **SSE helper:** `app/core/sse.py: sse_response(gen, *, ctx)` sets fixed headers, pings every 15 s, uses a bounded queue of 256 frames and a 10 s send timeout. It closes within 2 s when `grant_watch` fires, sending `event: access_changed`.
- **Job events:** a `job` event goes out after every commit that changes a Job row (`app/jobs/events.py`).

**Files:**
- `src/backend/app/core/pubsub.py` (new): publishers, subscribers, throttles and `flush_pending`.
- `src/backend/app/core/sse.py` (new): `sse_response`, `SSEResponse`, `format_event` and `register_close_watch`.
- `src/backend/app/jobs/events.py` (new): the after_flush listener, `queue_job_event`, and the after-commit publish of the committed rows.
- `src/backend/app/jobs/__init__.py`: imports `events`, which installs the listener.
- `src/backend/app/jobs/worker.py`: explicit events for the raw UPDATEs (claim and report), a trailing flush in the work horse, and a Valkey client of its own for each reaper pass.
- `src/backend/app/access/__init__.py`: registers `grant_watch` as the SSE close watch, since `app.core` may not import `app.access`.
- `src/backend/app/main.py`: calls `flush_pending` on shutdown.
- `src/backend/tests/test_pubsub.py` and `src/backend/tests/test_sse.py` (new): cover the matrix on fake and real Valkey, with an in-process uvicorn on 127.0.0.1.

**Review:**
- 35 findings: 14 patched, 3 deferred and 18 rejected, with reasons in the triage log.
- Patched entries by verdict: medium 7, low 7.
- Follow-up review recommended: true. Several medium patches landed in two places: the cancel and cleanup path of `SSEResponse.stream_response`, and the logic that drops a throttle trail. The multi-process throttle behaviour is only covered by single-process tests.

**Verification:**
- `py_compile` passes on all changed files.
- `lint-imports` keeps every contract.
- Locally, the tests that need no database pass: 32 passed, 14 skipped (the real-Valkey ones).
- GitHub CI on PR #65 (Postgres plus Valkey, with `VALKEY_TEST_URL` set) is the gate for the DB and real-Valkey tests, including the `CLIENT LIST` check.

- CI result on PR #65 at d467cf1: all checks green. The backend suite was 1988 passed, 4 skipped on the run before last. The last run fixed one real-Valkey failure: a trail now waits out PTTL rounding before it takes the next window.

**Needs desktop verification:**
- **Buffering behind nginx.** Run `curl -N -H "Authorization: Bearer <t>" https://<host>/api/<stream route>`. You should see `event: ping` within 15 s, and each event as soon as it is published. Check that the response carries `X-Accel-Buffering: no`. The location for each stream route needs `proxy_buffering off` and `proxy_read_timeout 1h`. Do this when E0-Jobs.7 or E0-Access.11 adds the first real stream route.
- **Long-lived connections.** Hold a stream open through nginx for at least 30 minutes. Pings should keep arriving, with no nginx 504 and no cut after 60 s idle.
- **No subscriber left after a disconnect.** On the real host, `valkey-cli CLIENT LIST | grep -c "sub=[1-9]"` should return to its baseline.
- **Revocation.** Revoke a member, or demote a co-GM. Their open stream should end with `event: access_changed` within 2 s.

**Residual risks:** see `deferred`. They cover the resync gap, the publish latency inside commit, and the client's close contract for E0-Jobs.9.
