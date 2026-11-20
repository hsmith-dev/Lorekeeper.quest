---
title: 'E0-Jobs.7: Job routes and the SSE stream'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: '8466b141fb4db647a3e5aceb4d588cacf01c6979'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Retry's 409 "The same work is already queued or running" can tell a Player that an active Job they cannot see holds the same idempotency key.
    evidence: |-
      retry_job checks for an active holder of the key with a select over every Job (keys are global and content-derived), so a Player retrying their own failed Job learns one bit about a hidden Job. This is the existing global-key design: enqueue() already returns an active holder's id to any starter in the same Campaign. A fix needs per-starter keys or a different dedup rule (E0-Jobs.2's design).
    location: >-
      src/backend/app/jobs/control.py retry_job
    severity: medium
  - summary: >-
      queue_position orders by created_at, so a retried Job (keeping its original created_at) reads as ahead of Jobs pushed before it.
    evidence: |-
      retry_job keeps created_at, and RQ dispatches in push order. A fix needs a requeue timestamp column (a migration). queue_position is already a lower bound by design.
    location: >-
      src/backend/app/access/jobs.py queue_positions
    severity: low
  - summary: >-
      Each job event costs one short DB session and query per connected viewer.
    evidence: |-
      job_event_stream opens a session per event per stream (progress is at most 1/s per Job). This is unmeasured: a burst benchmark with many viewers would show whether a per-stream memo of visible job ids is needed (created_by never changes). Same shape as E0-Access.11's deferral.
    location: >-
      src/backend/app/access/jobs.py job_event_stream
    severity: medium (unverified)
  - summary: >-
      The admin System tab shows Job counts but no sidecar status next to them.
    evidence: |-
      E0-Platform.6 (sidecar /v1/status through admin.py) is not merged; that story adds the status beside this card.
    location: >-
      src/frontend/src/pages/AdminPage.tsx JobCountsCard
    severity: low
---

<intent-contract>

## Intent

**Problem:** Jobs exist (E0-Jobs.1–6) and publish `job` events on `jobs:{campaign_id}`, but nothing lets a GM or Player read, list, retry or cancel a Job, or receive its events. The frontend tray (E0-Jobs.9/.10) has no contract to build on.

**Approach:** Add `app/api/routes/jobs.py` (`GET /api/jobs/{id}`, `GET /api/jobs/?campaign_id=&status=`, `POST /api/jobs/{id}/retry`, `POST /api/jobs/{id}/cancel`, SSE `GET /api/jobs/stream?campaign_id=`) and an admin `GET /api/admin/jobs/stats`. All reads go through a new `app/access/jobs.py` (scoped reads, `result_ref` visibility, `queue_position`, the per-event stream filter); state changes (race-safe cancel and retry) and admin counts live in a new `app/jobs/control.py`. Schemas in `app/schemas/jobs.py`. nginx gets an exact streaming location, EV-4 gets `tests/ev4/probes/jobs.py`, and the admin System tab shows Job counts by status and queue.

## Boundaries & Constraints

**Always:**
- Every Job read uses `scoped_select`/`scoped_get(Job, ctx)` (GM: every Job of the Campaign; Player: only Jobs with `created_by == user`; member view/anon: none). Hidden, missing, another Campaign's and malformed ids are the one `404 {"detail":"Not found"}`.
- `result_ref` reaches a non-GM (or any read-only ctx) only when it is `{"kind", "id"}` of a registered result kind whose row is visible to the ctx now, and then only as `{"kind","id"}`; anything else is `null`. A writable GM gets it unchanged.
- `queue_position` (queued Jobs only, else `null`) counts only Jobs the ctx can see that sit ahead in the same `queue` (queued, earlier `created_at`, id as tie-break). It never counts hidden Jobs or another Campaign's.
- Stream: first frame `event: subscribed` (`listen_jobs(announce=True)`); each `job` event is delivered only if the ctx could `GET /api/jobs/{job_id}` now, payload rebuilt from `JOB_EVENT_FIELDS` with `result_ref` filtered as above; other event names dropped; a check failure ends the stream. Watch on the real ctx, filter with `stream_ctx` (preview narrows). Clients refetch on every `subscribed`.
- Cancel: only `queued` Jobs; row locked `FOR UPDATE`, ORM status write (`cancelled`, `finished_at`) so outbox releases dependents and events publish. Worker claim's conditional UPDATE then fails, the reaper only touches `running`/`queued`; a cancelled Job never runs. Running/terminal → `409 {"detail":"Only queued Jobs can be cancelled"}`.
- Retry: only `failed` Jobs; same row back to `queued`, `attempts=0`, run state and errors cleared, pushed after commit via `outbox.record_pending`; `202 {"job_id"}`. Not failed → `409`. Key now held by another active Job → `409`.
- Writes need a writable ctx (preview write → 404 via `require_campaign_for`); only the starter or a GM (a Player can only reach their own Job).
- Limiter `user_or_ip` on every route; stream in nginx `api` zone with buffering off, 1 h read timeout, gzip off.

**Never:** no `lib/sse.ts`, hooks or tray UI (E0-Jobs.9/.10); no raw `select(Job)` outside `app/access/` / `app/jobs/`; no new pub/sub channel; no sidecar status (E0-Platform.6, not merged).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM detail | GM, own-Campaign Job | 200 JobResponse incl. raw `result_ref` | — |
| Player own | Player, Job they started, result GM-only | 200, `result_ref: null` | — |
| Player other's | Player, GM's/another Player's Job | 404 identical to missing id | uniform 404 |
| List | `?campaign_id=` default | running+queued+finished ≤24 h, newest first, `queue_position` on queued | bad status → 422 |
| Queue position Player | 2 hidden queued Jobs ahead, 1 own ahead | `queue_position: 1` | — |
| Cancel queued | starter / GM | 200 JobResponse `cancelled`; worker `run_job` returns None | — |
| Cancel running/done | | 409 "Only queued Jobs can be cancelled" | — |
| Cancel race | claim committed first | 409; cancel first → claim skips | row lock |
| Retry failed | | 202 `{job_id}`, row queued, attempts 0 | non-failed 409 |
| Stream Player | events for own + other's Jobs | `subscribed`, then only own (result_ref filtered) | check error ends stream |
| Stream preview | GM + preview header | member view: no job events | — |

</intent-contract>

## Code Map

- `src/backend/app/core/pubsub.py` -- `listen_jobs(cid, announce=True)`, `JOB_EVENT`, `SUBSCRIBED_EVENT`, `JOB_EVENT_FIELDS` (reuse, read-only).
- `src/backend/app/core/sse.py` -- `sse_response(gen, ctx=, bind=)`; close the request session first.
- `src/backend/app/access/events.py` -- pattern for the stream filter + `stream_ctx`; `api/routes/events.py` pattern for the route.
- `src/backend/app/access/registry.py:312` -- `Job: always_gm(owner_field="created_by")`; `scoped_select`/`scoped_get`.
- `src/backend/app/access/files.py:71` -- `visible_file` for the `file` result kind.
- `src/backend/app/access/context.py` -- `require_campaign`, `require_campaign_for(Job, "job_id")`.
- `src/backend/app/jobs/worker.py:151` -- `_claim`'s conditional UPDATE `WHERE status='queued'` (cancel safety); reaper `_recover_running`/`_push_due` only touch running/queued.
- `src/backend/app/jobs/outbox.py` -- `record_pending` (retry push), after_flush dependents release on ORM terminal writes.
- `src/backend/app/jobs/registry.py` -- `get_kind` (retry of an unregistered kind → 409).
- `scripts/check_scoped_queries.py` -- OWNER_INFRA lets `app/jobs/**` read `Job`.
- `nginx/locations.conf` -- events location to copy; `tests/ev4/test_nginx.py`, `tests/ev4/probes/events.py`, `tests/access/test_campaign_events.py` -- test patterns.
- `src/frontend/src/pages/AdminPage.tsx` `SystemTab`, `hooks/useAdmin.ts`, `services/api.ts`, `types` -- admin counts card.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/jobs.py` -- `JobResponse` (+`queue_position`), `JobListResponse`, `JobStatsResponse`.
- `src/backend/app/access/jobs.py` -- `get_job`, `list_jobs`, `queue_positions`, `register_result_kind` (+ built-ins `journal`, `entity`, `file`), `visible_result_ref`, `job_response`, `job_event_stream`; export from `app/access/__init__.py`.
- `src/backend/app/jobs/control.py` -- `cancel_job`, `retry_job`, `job_counts`; `JobConflict`.
- `src/backend/app/api/routes/jobs.py` + `app/main.py` -- the five routes, limits, 409 mapping; admin `GET /api/admin/jobs/stats` in `admin.py`.
- `nginx/locations.conf` -- `location = /api/jobs/stream` streaming block; update template comment.
- `src/backend/tests/test_job_routes.py` -- matrix above end to end (incl. uvicorn stream, cancel race, worker skip, limiter).
- `src/backend/tests/ev4/probes/jobs.py` -- hidden vs nonexistent ids (GET/cancel/retry), `result_ref` suppression, list/queue_position leak, SSE filtering, nginx location.
- `src/frontend/src/{types,services/api.ts,hooks/useAdmin.ts,pages/AdminPage.tsx}` -- "Background jobs" card on the System tab.

**Acceptance Criteria:**
- Given the routes, when EV-4 runs, then the jobs probes pass with zero leaks and the coverage gate lists every new route as probed (admin stats exempted as admin-only).
- Given the admin System tab, when an admin opens it, then Job counts by status and queue are shown.

## Design Notes

`queue_position` is a lower bound by design (owner's privacy-first rule): a Player may see "0 ahead" while hidden Jobs run first. Result kinds are registered like event domains; features add theirs with `register_result_kind(kind, model)`.

## Verification

**Commands:**
- GitHub CI `backend-tests.yml`, `frontend-ci.yml`, `license-check.yml` -- expected: green.
- `python -m py_compile` on changed files; `npx tsc --noEmit && npm run build` in `src/frontend` -- expected: success.

## Spec Change Log

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 36 findings — high 0, medium 8, low 19, false 7, maybe-false 2
- findings:
  - `medium` `patch` (blind) Retry keeps the stored ctx fields, so a Job that failed permission_changed fails again — patched: when the starter retries their own Job it takes their current access_epoch; ctx_kind and ctx_user_id stay (test added).
  - `low` `defer` (blind) Retry keeps created_at, so queue_position misorders retried Jobs — needs a requeue column; deferred.
  - `false` `reject` (blind) Retry ignores dependents — under the enqueue contract (E0-Jobs.2) dependents always run once their dependency reaches any terminal status, so nothing is lost.
  - `medium` `patch` (blind) The retry savepoint IntegrityError branch is untested — patched: a new test bypasses the pre-check and asserts a 409, the row still failed and nothing pushed.
  - `low` `reject` (blind) A Player's queue_position goes stale when hidden Jobs finish — it is a lower bound by design, and the client refetches on `subscribed` (E0-Jobs.9); a fix needs new events.
  - `low` `reject` (blind) queue_position counts backoff Jobs and scans the queue — those Jobs are queued and will run, and a per-Campaign scan is small.
  - `medium` `patch` (blind) LIST_LIMIT can silently drop queued/running Jobs — patched: active Jobs are never limited, finished ones are capped, and the two are merged newest first (test added).
  - `low` `patch` (blind) `status=` stays bound to the 24 h window — patched: an explicit status has no window (test added).
  - `maybe-false` `defer` (blind) Per-event DB queries per stream — needs a burst benchmark; deferred as medium (unverified).
  - `false` `reject` (blind) The stream probe's GM check differs from is_gm_of_a — is_gm_of_a is exactly `actor.grants.get(cid) == "gm"`.
  - `low` `reject` (blind) No access_changed test on the job stream — the route uses the shared sse_response watch, which tests/test_sse.py and the events route tests cover; adding one is not a direct correction.
  - `false` `reject` (blind) The admin card hard-codes the queues — the ck_jobs_queue CHECK allows only the three JobQueue values.
  - `false` `reject` (blind) The admin text claims a priority order — E0-Jobs.5 enforces interactive > onsave > backfill in the worker.
  - `low` `reject` (blind) Inconsistent status comparison in the list route — JobStatus is a StrEnum and both forms compare equal; cosmetic.
  - `low` `reject` (blind) The spec matrix omits shipped 409 and admin cases — the fix would edit this build's spec.
  - `low` `reject` (blind) The admin-only test accepts 403 or 404 — negligible; require_admin and the EV-4 exemption are unchanged.
  - `maybe-false` `reject` (blind) test_retry_runs_again_under_jobs_eager relies on the default — conftest runs with JOBS_EAGER=1, and even if true it would only be low.
  - `low` `reject` (blind) `__all__` ordering and inline type imports — cosmetic.
  - `medium` `patch` (verification-gap) Retry savepoint branch untested — same group as the blind finding above; patched there.
  - `low` `patch` (verification-gap) Retry's reset of queue/result_ref/eta/heartbeat is not asserted — patched: the row now starts on another queue with run state set, and the test asserts the reset.
  - `medium` `defer` (intent) Retry's key-in-use 409 reveals a hidden Job holding the same key — pre-existing global-key design (enqueue already hands out the holder's id); deferred.
  - `low` `reject` (intent) Stream filtering is proven with hand-made messages — the filter reads only `job_id` from a message, and a real-commit test exists (test_a_real_job_change_reaches_the_starter).
  - `false` `reject` (intent) queue_position does not match the AC's true position — the invocation intent explicitly requires that it not reveal hidden Jobs ahead.
  - `medium` `patch` (intent) Reaper safety for cancelled Jobs is untested — patched: a reaper pass leaves two cancelled Jobs untouched, unpushed and unrun.
  - `false` `reject` (intent) nginx settings are checked in two places — both tests run in CI (EV-4 and test_job_routes).
  - `low` `defer` (intent) The admin AC is delivered without sidecar status — E0-Platform.6 is not merged; deferred.
  - `low` `reject` (intent) Retry returns the same id, not a new Job — the AC's `202 {"job_id"}` is met, and a same-row retry keeps the history and the tray key.
  - `low` `reject` (intent) The client refetch half of the resync contract is untested — E0-Jobs.9 owns lib/sse.ts (excluded by the intent).
  - `medium` `patch` (edge) A permission_changed retry keeps the old epoch — same group as the first blind finding; patched there.
  - `false` `reject` (edge) A GM's retry runs under the starter's grant — intended: a GM retry must not raise a Player's Job to GM rights.
  - `low` `defer` (edge) A retried Job keeps created_at for queue order — same group as the deferred created_at finding.
  - `low` `reject` (edge) Deferred or blocked queued Jobs count as ahead — they are queued, and queue_position is a lower bound.
  - `medium` `patch` (edge) LIST_LIMIT drops active Jobs — same group as the blind list-cap finding; patched there.
  - `low` `reject` (edge) A race between the list and positions queries gives queue_position null — rare and harmless (null means unknown), and the client refetches.
  - `low` `reject` (edge) Event fields other than result_ref come from the event — the publisher reads the committed row at publish time (app/jobs/events.py).
  - `low` `defer` (edge) Claim: ordering by created_at versus dispatch order — same group as the deferred created_at finding.

## Auto Run Result

Status: done

**Summary.** Added the Job API (B2 contract):
- `GET /api/jobs/{id}`
- `GET /api/jobs/?campaign_id=&status=` with `queue_position`
- `POST /api/jobs/{id}/retry` and `POST /api/jobs/{id}/cancel`
- SSE `GET /api/jobs/stream?campaign_id=`: `subscribed` first, then a per-event access filter
- admin `GET /api/admin/jobs/stats` and a "Background jobs" card on the System tab
- the nginx streaming location and EV-4 probes

**Files changed.**
- `src/backend/app/access/jobs.py` — every Job read, result_ref visibility and the result-kind registry, queue_position, the stream filter.
- `src/backend/app/jobs/control.py` — race-safe cancel, retry (same row; a starter's own retry takes the current epoch), admin counts.
- `src/backend/app/api/routes/jobs.py`, `app/main.py`, `app/api/routes/admin.py` — routes, limits, mounting.
- `src/backend/app/schemas/jobs.py` — JobResponse, JobListResponse, JobStatsResponse.
- `src/backend/app/access/__init__.py` — exports.
- `nginx/locations.conf` — `location = /api/jobs/stream` (api zone, buffering/cache/gzip off, 1 h timeouts).
- `src/backend/tests/test_job_routes.py`, `tests/ev4/probes/jobs.py`, `tests/ev4/test_nginx.py`, `tests/ev4/exemptions.yaml` — tests and EV-4.
- `src/frontend/src/{types/index.ts,services/api.ts,hooks/useAdmin.ts,pages/AdminPage.tsx}` — the admin counts card.

**Review.** 36 findings. Six patch entries were applied: the epoch refresh, the savepoint test and the list cap (each also reported by a second reviewer), plus the status window, the retry-reset asserts and the reaper test. Four items were deferred: the retry key-in-use bit, created_at ordering, per-event queries and the sidecar status. The rest were rejected; each reason is in the triage log. Patched entries by verdict: medium 4, low 2.

**Follow-up review: recommended.** Four medium entries were patched after the review. Two of those patches, the `list_jobs` rewrite (split into active and finished queries) and the starter epoch refresh, were tested in CI but not reviewed again.

**Verification.**
- GitHub CI on PR #69, first push: all checks green. Backend 2190 passed, 4 skipped; EV-4 probes=91, exemptions=2, pending=46, leaks=0.
- Review-fix push: see the PR #69 checks.
- Locally: py_compile on the changed files, scripts/check_scoped_queries.py, `npx tsc --noEmit` and `npm run build`.

**Needs desktop verification.**
- nginx in front of the app streams `/api/jobs/stream` unbuffered. Run `docker compose -f docker-compose.prod.yml up -d`, then `curl -N -H "Authorization: Bearer <token>" "https://<host>/api/jobs/stream?campaign_id=<id>"`. Expect `event: subscribed` at once and a `job` frame within 5 s of starting a `system.noop` Job; `nginx -t` should pass.
- A real worker skips a cancelled Job. Stop the `worker` service, enqueue a Job, cancel it, start the worker, and check that the row stays `cancelled` and nothing runs.

**Residual risks.** queue_position is a lower bound (privacy first). Retry's key-in-use 409 can reveal one bit about a hidden Job (deferred).
