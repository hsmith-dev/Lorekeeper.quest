---
title: 'E0-Jobs.1: F2-jobs-files revision and models'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '6146e938c815b95c27db5665bc7653ff2ade3381'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Every Job-producing and file-producing epic needs one authoritative `jobs` row and one `stored_files`/`derived_sources` record, but none of the F2-jobs-files tables (AD-19) exist yet.

**Approach:** One Alembic revision on the current head (`c95acb56c595`, F1-core) creates `jobs`, `data_backfills`, `stored_files` and `derived_sources`, with CHECKs generated from new StrEnums; matching models are exported from `app/db/models`, and each model registers in `app/access/registry.py` with the class the story names.

## Boundaries & Constraints

**Always:**
- Columns exactly as the story lists them. Extras only where Postgres needs them: a surrogate `id uuid` PK on `derived_sources` (its listed columns include nullable `ref_field`, so they cannot be the PK) and `name` as the `data_backfills` PK (gives "name unique").
- `JobStatus {queued, running, done, failed, cancelled}`, `JobQueue {interactive, onsave, backfill}`, `JobErrorCode` in `app/domain/enums.py` (the models import them; AD-1 puts domain below db). `app/jobs/errors.py` re-exports `JobErrorCode` (AD-4: "a closed StrEnum in app/jobs/errors.py") and holds the terminal set.
- `JobErrorCode` = the story's list plus `prompt_too_large` (E0-LLM.1's `PromptBudgetError.code`; E0-Jobs.3 asserts every `LLMError.code` is a member, so adding it now avoids a CHECK-regenerating migration). Append-only.
- CHECKs via `check_sql` in the migration (frozen enum copies, like F1-core) and `check_expr` in the models: `jobs.status`, `jobs.queue`, `jobs.error_code`, `data_backfills.status` (JobStatus). All four move into CI-10 `ENUM_CHECKS`.
- Every FK's ON DELETE is stated in `EXPECTED_FK_ON_DELETE`. `stored_files.audience_owner_id` is CASCADE (SET NULL would widen the file's Audience).
- Registry: `jobs` = `always_gm(owner_field="created_by")` (non-GM Owner(u) ctx sees rows with `created_by = u`); `stored_files` = a new `derived_from_sources()` class (Audience = most restrictive of its `derived_sources` refs, fail-closed); `derived_sources`, `data_backfills` = `always_gm()`. The latter two have no `campaign_id`: the import check accepts `always_gm` without a Campaign scope, and `scoped_select` refuses them (existing `UnregisteredModel` "no Campaign scope" path).
- Downgrade drops exactly what upgrade created; the existing a3e7c1f9d258 round trip still passes.
- `app.jobs` joins the import-linter layers contract between `app.api` and `app.services` (spine layer table: jobs import services/access/schemas/domain/core; routes and hooks import jobs).

**Never:** no `enqueue`, worker, registry of kinds, file service, routes, compose or nginx changes (E0-Jobs.2–.8); no `SourceKind` enum (owned by E0-Access `schemas/sources.py`); no CHECK on open sets (`jobs.kind`, `stored_files.kind`, `derived_sources.derived_type/ref_kind`, `ctx_kind`, `ctx_audience`: their vocabularies belong to later stories).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Idempotency active | two `queued`/`running` jobs, same key | second insert rejected | IntegrityError |
| Idempotency after done | first job `done`, second `queued`, same key | both rows exist | none |
| Cache key fresh | two non-stale files, same (campaign, kind, cache_key) | second rejected | IntegrityError |
| Cache key stale | one stale + one fresh, same key | both exist | none |
| Bad enum value | `status='paused'` / `queue='x'` / `error_code='nope'` | rejected | CHECK violation |
| Job visibility | Player p; jobs by p, by q, by none | p sees own only; GM sees all in Campaign; anon/member preview see none | — |
| File visibility | non-GM; file with sources all visible / one hidden / none / unknown ref_kind / GM ref_field / stale / other owner | visible only when every source is visible, ≥1 source, kind registered, not stale, owner null or self | fail closed → hidden |

</intent-contract>

## Code Map

- `src/backend/migrations/versions/c95acb56c595_f1_core_roles_visibility_party_search.py` -- current single head; pattern for frozen StrEnum copies + `check_sql`.
- `src/backend/app/domain/enums.py` -- add the three StrEnums; docstring "Where each CHECK lives".
- `src/backend/app/db/models/__init__.py` -- export new models in imports and `__all__`.
- `src/backend/app/db/models/journal.py` -- pattern: `CheckConstraint(check_expr(...), name=...)` in `__table_args__`.
- `src/backend/app/access/registry.py` -- `AlwaysGM`, `visible_clause`, `audience_of`, `_check_complete`, `DERIVED_REGISTRY`/`_derived_type`; add owner rule + `DerivedFromSources` + `SOURCE_KIND_MODELS` (`journal` → `JournalEntry`, extended later via `register_source_kind`).
- `src/backend/app/access/audience.py` -- `owner`, `most_restrictive`, `field_audience`, `ALWAYS_GM_FIELDS` (reuse).
- `src/backend/app/core/errors.py` -- LLMError codes (`llm_config`, `llm_busy`, `llm_unavailable`, `ai_output_unusable`, `prompt_too_large`).
- `src/backend/tests/test_enum_check_sync.py` -- `ENUM_CHECKS` gains 4 entries.
- `src/backend/tests/domain/test_enums.py` -- `EXPECTED` gains the 3 enums.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- `EXPECTED_FK_ON_DELETE`, `@post_upgrade_check`, downgrade test.
- `src/backend/tests/access/test_registry_property.py` -- `SPECS` must equal `REGISTRY` (CI-11); add Job and StoredFile builders; global models tested separately.
- `src/backend/tests/test_migrations_match_models.py` -- drift gate (no edit expected).
- `src/backend/.importlinter`, `scripts/test_import_ratchet.py` (`REQUIRED_LAYERS`) -- add `app.jobs`.
- `scripts/check_table_owners.py` -- AD-19 F2 bullet already owns the 4 tables (no edit expected).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/domain/enums.py` -- add `JobStatus`, `JobQueue`, `JobErrorCode`; docstring rows.
- `src/backend/app/jobs/__init__.py`, `src/backend/app/jobs/errors.py` -- new package; re-export `JobErrorCode`, `TERMINAL_CODES` (AD-4), `RETRYABLE_CODES`.
- `src/backend/app/db/models/job.py` -- `Job`, `DataBackfill`.
- `src/backend/app/db/models/stored_file.py` -- `StoredFile`, `DerivedSource`.
- `src/backend/app/db/models/__init__.py` -- export them.
- `src/backend/migrations/versions/<rev>_f2_jobs_files.py` -- revision (`down_revision='c95acb56c595'`), upgrade + downgrade.
- `src/backend/app/access/registry.py` -- owner rule on `always_gm`, `derived_from_sources`, global `always_gm`, registrations.
- Tests: enum sync + domain enums; snapshot (FKs, post-upgrade check, F2 downgrade round trip); new `tests/test_jobs_files_schema.py` (I/O matrix DB constraints, `app/jobs/errors` sets); property test extensions; `tests/access/test_audience.py` style unit tests for global always_gm refusal.
- `src/backend/.importlinter`, `scripts/test_import_ratchet.py` -- `app.jobs` layer.

**Acceptance Criteria:**
- Given an empty DB and the seeded a3e7c1f9d258 snapshot, when `alembic upgrade head` runs, then the four tables, the partial unique indexes and the two `jobs` indexes and `(ref_kind, ref_id)` index exist, row counts are unchanged, single-head and FK-action tests pass, and downgrading to `c95acb56c595` removes exactly the four tables.
- Given the migrated DB, when CI-10 runs, then each of the four CHECKs matches its StrEnum.
- Given `app.access.registry` imports, then the completeness check passes with the four models registered as the story says, and CI-11 agrees for `jobs` and `stored_files`.
- Given the models and the migration, when the drift test runs, then there are no diffs.

## Spec Change Log

## Review Triage Log

## Design Notes

`stored_files` non-GM SQL (GM: `true`): `NOT stale AND kind IN <registered file types> AND (audience_owner_id IS NULL OR = viewer owner) AND EXISTS(ds) AND NOT EXISTS(ds WHERE NOT ok(ds))`, `ok(ds)` = ref_field not always-GM AND ref_kind allowed by the type's `derive_from` AND ref_kind has a model in `SOURCE_KIND_MODELS` whose row (same Campaign) passes its own `visible_clause`. Python twin: GM if stale / unregistered kind / no sources / any unresolvable or disallowed source; else `most_restrictive(source auds, field auds, Owner(audience_owner_id)?)`. Both fail closed, and `covers(meet) == AND(covers)` on this lattice, so they agree.

## Verification

**Commands:**
- `python scripts/check_table_owners.py` -- exit 0
- `cd src/backend && lint-imports` -- contracts kept (CI)
- GitHub CI `backend-tests.yml` -- full suite green incl. migrations, CI-10, CI-11, drift
