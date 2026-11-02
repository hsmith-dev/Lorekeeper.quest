---
title: 'E0-Jobs.7: Job routes and the SSE stream'
type: 'feature'
created: '2026-11-02'
status: 'in-review'
baseline_revision: '8466b141fb4db647a3e5aceb4d588cacf01c6979'
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
