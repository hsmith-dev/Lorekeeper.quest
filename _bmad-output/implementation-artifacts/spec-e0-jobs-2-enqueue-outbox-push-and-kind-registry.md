---
title: 'E0-Jobs.2: enqueue with outbox push and the kind registry'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '480244501bf4413ba673efaef41b9eb3c5335f26'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
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

## Design Notes

Dispatch runs inside `after_commit`, which SQLAlchemy calls inside the AsyncSession's greenlet, so `sqlalchemy.util.await_only(coro)` can await the eager `run_job` (or `asyncio.to_thread(push)`) before `commit()` returns. Eager and dependents queries use a fresh `AsyncSession` on `AsyncEngine(session.get_bind())` (same pool, new connection: the committed transaction is over). Terminal status changes are captured in `after_flush` from attribute history, so any ORM write (worker, future cancel/reaper) releases dependents.

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- all contracts kept (CI gates.yml)
- GitHub CI `backend-tests.yml` -- full suite green incl. the new tests against Postgres and Valkey
- `license-check.yml` -- register covers rq, croniter, python-dateutil
