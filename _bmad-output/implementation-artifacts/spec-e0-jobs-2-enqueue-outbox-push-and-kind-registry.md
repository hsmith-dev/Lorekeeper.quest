---
title: 'E0-Jobs.2: enqueue with outbox push and the kind registry'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '480244501bf4413ba673efaef41b9eb3c5335f26'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Held dependents are released only when a terminal status is written through the ORM; a Core UPDATE or a deleted dependency leaves them queued.
    evidence: |-
      outbox._note_finished_jobs reads ORM attribute history in after_flush. A cancel or reaper written as sa.update(Job), or a dependency row deleted (FK SET NULL), releases nothing. E0-Jobs.4's reaper must also push queued dependents whose dependency is terminal or gone, and E0-Jobs.7's cancel should write through the ORM.
    location: >-
      src/backend/app/jobs/outbox.py (_note_finished_jobs)
    severity: medium
  - summary: >-
      The RQ worker process imports only app.jobs.registry, so feature kinds registered in feature modules would fail there as unknown kinds.
    evidence: |-
      run_job calls get_kind(job.kind). Only system.noop is registered at import of app.jobs. E0-Jobs.3 (LorekeeperWorker and the worker service) must import every kind-registering module at worker start. No feature kind exists yet.
    location: >-
      src/backend/app/jobs/worker.py (run_job)
    severity: medium
  - summary: >-
      No rq worker runs in any deployment yet, and nothing re-pushes a Job whose push failed, so a production enqueue before E0-Jobs.3 and E0-Jobs.4 stays queued.
    evidence: |-
      jobs_eager defaults to False, and no compose service runs rq. A failed push is logged and left for the E0-Jobs.4 reaper. No production route calls enqueue in this story. E0-Jobs.3 adds the worker service and E0-Jobs.4 the reaper.
    location: >-
      src/backend/app/jobs/outbox.py
    severity: medium
  - summary: >-
      A handler cancelled with a BaseException (CancelledError, the RQ kill) leaves its row running.
    evidence: |-
      run_job catches Exception only. Heartbeats and timeouts come in E0-Jobs.3, and stale-row recovery in E0-Jobs.4.
    location: >-
      src/backend/app/jobs/worker.py (run_job)
    severity: low
---

<intent-contract>

## Intent

**Problem:** E0-Jobs.1 created the `jobs` table, but nothing creates a Job: there is no `enqueue`, no kind registry and no RQ push, so features can't start durable background work, and a Job could be lost to a rollback or run twice.

**Approach:** `app/jobs/registry.py` (JobKind + `system.noop`), `app/jobs/enqueue.py` (`enqueue` validates, dedupes by key within the Campaign, writes the row, records the id in `session.info`), `app/jobs/outbox.py` (SQLAlchemy `after_commit` listener that pushes only `job_id` to RQ on Valkey, or under `JOBS_EAGER=1` runs it inline, and releases dependents of Jobs that reached a terminal status), and a minimal `run_job` wrapper in `app/jobs/worker.py` that both paths use.

## Boundaries & Constraints

**Always:**
- Signature `enqueue(db, ctx, kind, payload, *, idempotency_key=None, depends_on_job_id=None) -> uuid.UUID`; no `queue` argument (queue from the registry). Every `ValueError` is raised before any write.
- ValueError cases: unregistered kind; payload not a JSON-serialisable dict; any key at any depth named like a secret (word `token`/`password`/`passwd`/`secret`, or `api_key`/`apikey`, case/camelCase-insensitive; `max_tokens` is allowed); missing/empty `idempotency_key`; a reduced (`read_only`) or user-less ctx; unknown dependency or one in another Campaign.
- Idempotency: an active (`queued`/`running`) Job with the key in ctx's Campaign → return its id, write nothing. The unique index is global (E0-Jobs.1 carry-over): an active Job with the key in another Campaign → ValueError (never return or reveal its id). Concurrent inserts are resolved through a savepoint + re-select.
- Stored ctx: `ctx_kind = ctx.role`, `ctx_user_id = created_by = ctx.user_id`, `ctx_audience = ctx.audience.level`, `access_epoch = ctx.access_epoch`.
- Outbox: the RQ message is exactly `perform(str(job_id))` on the queue named by `JobKind.queue` (RQ job id = Job id, `retry` unset, `result_ttl=0`); nothing is pushed on rollback (outermost rollback clears the pending list); a push failure is logged and swallowed (the Jobs.4 reaper re-pushes). Sync redis calls run off the event loop (`asyncio.to_thread`).
- Dependencies: the dependency row is read `FOR SHARE` (closes the race with a finishing worker). Active → row written `queued` with `depends_on_job_id`, not pushed. Terminal → pushed at once. When any Job's status is flushed to a terminal value (ORM change), the after-commit step pushes every `queued` dependent. `run_job` sets `job.dependency_status` before calling the handler.
- `JOBS_EAGER=1` (`settings.jobs_eager`): dispatch awaits `run_job` in-process (via `await_only` inside the commit), so after `await db.commit()` the row is final; handler errors become `failed` rows, never exceptions from `commit`.
- `rq==2.12.0` in `requirements.txt`; `rq`, `croniter`, `python-dateutil` rows in `licenses/register.yaml`.

**Never:** no retries/backoff, heartbeats, timeouts, permission-epoch checks, LLM config or `gate_class` (E0-Jobs.3); no reaper (E0-Jobs.4); no priority/admission (E0-Jobs.5); no pubsub/routes/compose worker service (E0-Jobs.6/7/3); no `BackgroundTasks`/`create_task`/threads for job work.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy (RQ) | eager off, enqueue + commit | one RQ job on `interactive` with args `(job_id,)` | — |
| Rollback | enqueue + rollback | no row, nothing pushed | — |
| Savepoint rollback | enqueue A, nested(enqueue B) rolled back, commit | only A dispatched | — |
| Dedupe | active job with key K in same Campaign | same id, row count unchanged | — |
| Reuse after done | job with K is `done` | new row | — |
| Cross-Campaign key | active job with K in Campaign X, enqueue in Y | no write | ValueError |
| Bad input | unknown kind / `{"api_key":…}` / nested `{"a":{"accessToken":…}}` / no key / read-only ctx | no write | ValueError |
| Eager | JOBS_EAGER, commit | row `done` after commit; failing handler → `failed`, `error_code=internal` | swallowed |
| Dependency active | dep `queued` | dependent `queued`, not pushed; dep → `failed`/`done`/`cancelled` + commit → dependent pushed; handler sees `dependency_status` | — |
| Dependency terminal | dep `done` | dependent pushed at once | — |
| Dependency other Campaign / unknown | — | no write | ValueError |
| Push fails | Valkey down | commit succeeds, row stays `queued` | logged |

</intent-contract>

## Code Map

- `src/backend/app/db/models/job.py` -- `Job`, `ACTIVE_STATUSES`; add a non-mapped `dependency_status = None` class attribute.
- `src/backend/app/domain/enums.py` -- `JobStatus`, `JobQueue`, `JobErrorCode` (reuse; `INTERNAL`, `PERMISSION_CHANGED`).
- `src/backend/app/jobs/__init__.py`, `errors.py` -- package exports (extend).
- `src/backend/app/access/context.py` -- `CampaignContext` (`read_only`, `user_id`, `role`, `audience`, `access_epoch`), `ctx_for` (raises NotFound) for the wrapper.
- `src/backend/app/core/config.py` -- `Settings`; add `jobs_eager: bool = False`; `valkey_url`.
- `src/backend/app/core/errors.py` -- `LLMError.code` (wrapper maps LLMError codes to `error_code`).
- `src/backend/tests/conftest.py` -- sets `JOBS_EAGER=1`; `db` fixture (`expire_on_commit=False`), `client` fixture.
- `src/backend/tests/test_jobs_files_schema.py` -- `_user`/campaign fixture pattern.
- `src/backend/tests/test_llm_gate.py` -- fakeredis + `VALKEY_TEST_URL` dual-backend pattern.
- `src/backend/app/services/llm_provider.py` -- `capture()` for the "route does no model work" assertion.
- `licenses/register.yaml` -- python rows are one flow-style line each.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/jobs/registry.py` -- `JobKind` dataclass (queue, timeout_s>0, resources ⊆ RESOURCES, live_safe, result_audience ∈ {gm, derived}, handler "module:attr"), `register`, `get_kind`, `KINDS`; `system.noop`.
- `src/backend/app/jobs/builtin.py` -- `noop` handler.
- `src/backend/app/jobs/enqueue.py` -- `enqueue`, payload secret check, `job_accepted(job_id)` → `202 {"job_id"}`.
- `src/backend/app/jobs/outbox.py` -- `after_flush`/`after_commit`/`after_soft_rollback` listeners, `dispatch`, RQ push, eager path, dependents release.
- `src/backend/app/jobs/worker.py` -- `run_job(job_id, session_factory, worker_id)` and sync RQ entrypoint `perform(job_id)`.
- `src/backend/app/core/config.py` -- `jobs_eager`.
- `src/backend/requirements.txt`, `licenses/register.yaml` -- rq and its deps.
- `src/backend/tests/jobs/test_enqueue.py` -- the I/O matrix (eager and RQ via fakeredis; real Valkey when `VALKEY_TEST_URL`), and the 202 route test.

**Acceptance Criteria:**
- Given a test-local route that enqueues `system.noop` and commits, when it is called, then it returns `202 {"job_id"}` in < 1 s, the row is `done`, and `llm_provider.capture()` records no call.
- Given the full backend suite, when CI runs, then it is green with no regressions and `lint-imports` keeps all contracts.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 49 findings — high 0, medium 9, low 24, false 7, maybe-false 0 (9 intent-alignment divergence rows triaged alongside)
- findings:
  - (blind) `[medium]` `[defer]` worker imports no feature kinds — no feature kind exists yet; E0-Jobs.3's worker start must import them (deferred).
  - (blind) `[low]` `[reject]` rq_timeout falls back silently for an unknown kind — the pushing process validated the kind at enqueue; the case is the same root as the deferred worker-import item.
  - (blind) `[medium]` `[defer]` dependents released only on ORM status writes — Core cancel and reaper paths don't exist yet; deferred to Jobs.4 reaper and Jobs.7 cancel.
  - (blind) `[medium]` `[patch]` dedupe returns an active Job of another kind — `_active_with_key` selects kind; mismatch is ValueError; test `test_same_key_of_another_kind_is_refused`.
  - (blind) `[false]` `[reject]` idempotency_key should be a required kw-only str — the story's AC requires a missing key to raise ValueError, which a required parameter (TypeError) would not.
  - (blind) `[medium]` `[patch]` secret-key filter misses plurals and pairs (private_key, access_key, credentials, authorization, access_tokens…) — word list and (api|private|access|secret)+key, (access|refresh|auth|id|bearer|session)+token pairs added; tests both ways. Value scanning rejected: the AC is about key names.
  - (blind) `[low]` `[reject]` no guard against JOBS_EAGER in a deployment — documented in config; the guard adds a validator for a misconfiguration nobody has hit.
  - (blind) `[medium]` `[patch]` no socket timeouts on the RQ connection — `socket_timeout=5, socket_connect_timeout=2`.
  - (blind) `[low]` `[patch]` worker docstring overstates the ctx rebuild — reworded: current ctx via ctx_for; the stored-ctx comparison is E0-Jobs.3's. The behaviour itself (role/epoch checks) is E0-Jobs.3's AC, rejected here.
  - (blind) `[low]` `[patch]` a handler that commits breaks the done-atomicity contract — registry docstring states handlers must not commit; enforcement rejected (adds surface).
  - (blind) `[low]` `[defer]` BaseException leaves a row running — deferred to Jobs.3/.4.
  - (blind) `[medium]` `[defer]` no rq worker in any deployment — worker service is E0-Jobs.3's; no production route enqueues yet (deferred).
  - (blind) `[false]` `[reject]` croniter needs pytz — croniter 6.2.4's metadata requires only python-dateutil (checked with `importlib.metadata.requires`).
  - (blind) `[low]` `[patch]` untested paths (perform, permission_changed, unknown kind, …) — same root as the verification-gap rows; tests added there. Chain A→B→C, insert exhaustion and the no-greenlet branch rejected as low.
  - (blind) `[low]` `[reject]` timing-sensitive tests / real fixture empties queue names — the < 1 s bound is the AC (a noop runs in ms); VALKEY_TEST_URL is a dedicated DB (15) in CI.
  - (blind) `[low]` `[reject]` job_accepted has no response schema — the Job routes and their schemas are E0-Jobs.7's.
  - (blind) `[low]` `[reject]` perform discards run_job's result / failure_ttl interplay — the row is the authority (AD-2); RQ results are deliberately discarded.
  - (edge) `[medium]` `[defer]` Core update or deletion never releases held dependents — same root as the deferred ORM-only release.
  - (edge) `[low]` `[defer]` deleted dependency (SET NULL) strands the dependent — same deferred item (reaper pushes it).
  - (edge) `[false]` `[reject]` a cancel during a run is overwritten — no cancel exists; E0-Jobs.7's cancel is for queued Jobs only.
  - (edge) `[low]` `[reject]` run_job reports DONE when the row vanished mid-run — the Campaign cascade deleted it; nothing reads the return value in production.
  - (edge) `[low]` `[reject]` ctx_for raising a non-NotFound exception leaves a row running — ctx_for only constructs ctxs that pass their own shape checks; unreachable.
  - (edge) `[low]` `[defer]` BaseException leaves a row running — same deferred item.
  - (edge) `[low]` `[reject]` a sync handler is not rejected at registration — it fails loudly as `internal` at first run; the guard adds code for a developer error.
  - (edge) `[low]` `[patch]` handler calling db.commit() — same root as the blind row; docstring rule.
  - (edge) `[medium]` `[patch]` same key, different kind — same root as the blind row; patched.
  - (edge) `[low]` `[reject]` dedupe against a Job from a savepoint that later rolls back — needs one caller to enqueue the same key twice across a savepoint it rolls back; not a real pattern.
  - (edge) `[low]` `[reject]` an over-long key raises DBAPIError, not ValueError — keys are short `<kind>:<id>:<hash>` strings; the guard adds a branch.
  - (edge) `[medium]` `[patch]` plural/provider secret keys — same root as the blind row; patched.
  - (edge) `[medium]` `[patch]` hung Valkey blocks commit — same root as the blind row; patched.
  - (edge) `[low]` `[reject]` nested eager chains may exhaust the pool — eager is tests-only and chains are one level deep.
  - (edge) `[low]` `[reject]` Connection-bound sessions inside an outer test transaction — no such caller; the db fixture binds to an engine.
  - (edge) `[low]` `[reject]` resources passed as str gives a misleading message — it still raises ValueError at registration; cosmetic.
  - (edge) `[false]` `[reject]` the global index blocks another Campaign's enqueue — the index is E0-Jobs.1's by story; keys embed Campaign-owned ids, so a collision is a caller bug and raising is the fail-closed reading of the carry-over note.
  - (edge) `[medium]` `[defer]` claim: dependents release only on ORM writes — same deferred item.
  - (verification-gap) `[medium]` `[patch]` perform never runs and the pushed function isn't resolved — `rq_job.func is worker.perform` asserted; `test_perform_runs_the_job_on_its_own_engine` added.
  - (verification-gap) `[low]` `[patch]` held-dependent guard in _claim unexercised — `test_run_job_skips_a_dependent_whose_dependency_is_active` added.
  - (verification-gap) `[low]` `[patch]` permission_changed / unknown-kind branches untested — `test_run_job_fails_when_the_starter_has_no_access` (outsider, None) and `test_run_job_fails_an_unregistered_kind` added.
  - (verification-gap) `[low]` `[patch]` handler writes vs done/failed atomicity untested — `test_handler_writes_commit_with_done_and_roll_back_with_failed` added.
  - (verification-gap other) `[low]` `[reject]` wall-clock 1 s assertion — the AC's own bound; the noop run is milliseconds.
  - (intent) `[false]` `[reject]` "never lost to a Redis flush" needs the reaper — that is E0-Jobs.4's AC; this story keeps the row queued so the reaper can recover it (deferred item records the gap).
  - (intent) `[low]` `[reject]` the 202 route is test-local — no production Job-starting route is in scope (E0-Jobs.7 owns the routes); `job_accepted` is the shared helper.
  - (intent) `[low]` `[patch]` pushes are never consumed by a worker in tests — same root as the perform gap; patched. Also verified by a real `rq worker --burst` run on the desktop.
  - (intent) `[low]` `[reject]` the minimal wrapper has permission_changed and LLM-code mapping — a handler needs a ctx, so a lost membership has to end somewhere; E0-Jobs.3 extends this wrapper.
  - (intent) `[medium]` `[defer]` ORM-only dependent release — same deferred item.
  - (intent) `[false]` `[reject]` an already-terminal dependency's dependent is pushed "at enqueue" — record_pending only queues it; the push still happens after commit.
  - (intent) `[low]` `[reject]` a race retry can raise after the caller's own changes were flushed — those are the caller's changes in the caller's transaction, rolled back with it.
  - (intent) `[low]` `[reject]` enqueue flushes the caller's pending changes — no Job row is written before validation, which is what "writes nothing" means.
  - (intent) `[false]` `[reject]` JobKind adds name/handler and invents result_audience values — a kind needs a name and a handler to run; {gm, derived} matches every result_audience later stories name (gm, or a record's derived Audience).

## Design Notes

Dispatch runs inside `after_commit`, which SQLAlchemy calls inside the AsyncSession's greenlet, so `sqlalchemy.util.await_only(coro)` can await the eager `run_job` (or `asyncio.to_thread(push)`) before `commit()` returns. Eager and dependents queries use a fresh `AsyncSession` on `AsyncEngine(session.get_bind())` (same pool, new connection: the committed transaction is over). Terminal status changes are captured in `after_flush` from attribute history, so any ORM write (worker, future cancel/reaper) releases dependents.

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- all contracts kept (CI gates.yml)
- GitHub CI `backend-tests.yml` -- full suite green incl. the new tests against Postgres and Valkey
- `license-check.yml` -- register covers rq, croniter, python-dateutil

## Auto Run Result

Status: done (draft PR #51; CI is the gate)

**Summary:** `enqueue` with Campaign-scoped idempotency over the global active-key index, the kind registry with `system.noop`, the after-commit outbox (RQ push of `job_id` only, JOBS_EAGER inline run, release of dependents) and a minimal `run_job`/`perform` wrapper.

**Files changed:**
- `src/backend/app/jobs/registry.py` -- JobKind, register/get_kind, system.noop.
- `src/backend/app/jobs/builtin.py` -- noop handler.
- `src/backend/app/jobs/enqueue.py` -- enqueue, secret-key check, job_accepted.
- `src/backend/app/jobs/outbox.py` -- session listeners, dispatch, RQ push (timeout = kind timeout_s + 60).
- `src/backend/app/jobs/worker.py` -- run_job, perform.
- `src/backend/app/jobs/__init__.py` -- exports; installs the listeners.
- `src/backend/app/db/models/job.py` -- non-mapped `dependency_status`.
- `src/backend/app/core/config.py` -- `jobs_eager`.
- `src/backend/requirements.txt`, `licenses/register.yaml` -- rq 2.12.0, croniter 6.2.4, python-dateutil 4.0.0.
- `src/backend/tests/jobs/test_enqueue.py` -- I/O matrix, worker paths, 202 route.

**Review:** 49 findings. Patched 7 entries (medium: kind mismatch on dedupe, secret-key coverage, Valkey socket timeouts, perform/func verification; low: docstrings, held-dependent / permission / unknown-kind / handler-atomicity tests). Deferred 4 (ORM-only dependent release, worker kind imports, no worker/reaper yet, BaseException leaves rows running). Rejected the rest with reasons in the triage log.

**Follow-up review recommended:** true -- four medium entries were patched; the broadened secret-key matcher is a heuristic, and only the parametrised cases pin it.

**Verification:**
- Desktop (`harrison@100.119.62.5`, throwaway pgvector + Valkey 8.1.11 containers, since removed): full backend suite 1029 passed, 4 skipped (before the review patches); `lint-imports` 5 contracts kept.
- A real `rq worker --burst` ran a `system.noop` Job and its dependent to `done`, the dependent pushed by the worker's after-commit release.
- First commit's CI on PR #51: backend tests, gates, licences and frontend all green. The patch commit is verified by CI on the PR.

**Residual risks:** see `deferred`. Needs desktop verification: none beyond what was already run (no compose or worker service changes in this story).
