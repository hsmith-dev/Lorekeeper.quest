---
title: 'E0-Jobs.1: F2-jobs-files revision and models'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '6146e938c815b95c27db5665bc7653ff2ade3381'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      audience_of(StoredFile) trusts the caller to pass every derived_sources row; a partial list widens the Python Audience.
    evidence: |-
      _sources_audience computes most_restrictive over the pairs it is given. The SQL twin reads all rows itself. No caller exists yet; E0-Jobs.8 (file service, GET /api/files/{id}) should ship a loader that fetches all (derived_source, source_row) pairs, or read through scoped_select only.
    location: >-
      src/backend/app/access/registry.py (_sources_audience)
    severity: medium
  - summary: >-
      uq_jobs_idempotency_key_active is global, not per Campaign, as the story specifies.
    evidence: |-
      Keys embed content ids (uuids), so cross-Campaign collisions need a key without a Campaign-unique part. E0-Jobs.2's enqueue must return an existing job_id only when it is in ctx's Campaign (or require keys to carry ids unique across Campaigns), so dedupe never reveals another Campaign's Job.
    location: >-
      src/backend/migrations/versions/cf62d979bc8a_f2_jobs_files.py
    severity: medium
  - summary: >-
      derived_sources rows are not removed when their derived record (or its Campaign) is deleted.
    evidence: |-
      derived_sources has no FK by design (polymorphic derived_id). E0-Jobs.8's file_service.delete and the files.gc backfill must delete a file's derived_sources rows and sweep orphans.
    location: >-
      src/backend/app/db/models/stored_file.py
    severity: low
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

### 2026-11-01 — Review pass
- verdicts: 33 findings — high 0, medium 8, low 14, false 11, maybe-false 0
- findings:
  - (verification-gap) `[low]` `[patch]` scoped_select_multi's DerivedFromSources branch untested — added test_scoped_select_multi_stored_files_match_scoped_select_per_campaign.
  - (verification-gap) `[medium]` `[patch]` register_source_kind accepts parent-derived models whose audience_of needs parents — now rejects every Derived/DerivedFromSources model and unscoped models; test covers Tag, SourceChunk, JournalTag.
  - (intent) `[false]` `[reject]` stored_files uses a new DerivedFromSources class, not `derived(...)` — the existing class needs parent links and cannot express typed polymorphic provenance; the spec chose this, and CI-11 proves SQL/Python agreement.
  - (intent) `[false]` `[reject]` "derived at creation" vs live predicate — a live, fail-closed predicate is strictly narrower than a creation-time snapshot (sources that become hidden hide the file, matching AD-13's stale rule).
  - (intent) `[false]` `[reject]` SOURCE_KIND_MODELS parallel to SourceKind — SourceKind does not exist yet (E0-Access.8 owns schemas/sources.py); the mapping is string-keyed so it can adopt it.
  - (intent) `[false]` `[reject]` jobs owner rule only at the Owner level — Owner(u) is exactly a Player ctx; member preview/anon have no user; matches "created_by = ctx.user_id for non-GMs".
  - (intent) `[false]` `[reject]` global tables refused by scoped_select — they have no campaign_id; refusing is the fail-closed reading of always_gm.
  - (intent) `[false]` `[reject]` JobErrorCode lives in domain — AD-1 forbids app.db importing app.jobs; app/jobs/errors.py re-exports it, satisfying AD-4.
  - (intent) `[false]` `[reject]` app.jobs import-linter placement — spine layer table puts jobs above services and below transport; db access goes via services/access as allowed by the layers contract.
  - (intent) `[false]` `[reject]` revision hand-written — id is alembic-format (12 hex, uuid4); body follows the F1-core house style.
  - (intent) `[false]` `[reject]` upgrade paths not newly tested — conftest upgrades an empty DB to head and the snapshot fixture upgrades a3e7c1f9d258 to head; CI ran both green.
  - (edge) `[medium]` `[patch]` register_source_kind / parent-derived (same root as above) — same fix.
  - (edge) `[low]` `[reject]` a single unwrapped (ds, row) tuple is split — caller error, raises TypeError loudly; fix adds a branch.
  - (edge) `[medium]` `[defer]` partial parents widen Python Audience — no caller yet; loader belongs to E0-Jobs.8 (deferred).
  - (edge) `[low]` `[reject]` pair[0] None gives AttributeError — loud failure on an unreachable input.
  - (edge) `[low]` `[reject]` scoped_get on a global model raises instead of 404 — no route reads these tables through a ctx; raising is a developer error, not a user path.
  - (edge) `[low]` `[reject]` visible_clause on a global model returns true for GM — visible_clause never adds Campaign scope by contract (documented); scoped_select refuses these models.
  - (edge) `[medium]` `[defer]` idempotency index global across Campaigns — story specifies this index; enqueue (E0-Jobs.2) owns cross-Campaign dedupe (deferred).
  - (edge) `[low]` `[patch]` retryable LLM codes not import-checked — errors.py now also builds JobErrorCode for llm_errors.RETRYABLE.
  - (blind) `[medium]` `[defer]` idempotency global (same root as above) — deferred.
  - (blind) `[low]` `[patch]` app.jobs missing from clients/domain contracts — added to both forbidden lists; planted violations added; ratchet 30 passed, lint-imports 5 kept.
  - (blind) `[medium]` `[patch]` register_source_kind (same root) — same fix.
  - (blind) `[medium]` `[patch]` ref_field ignores the source model's gm_fields — both twins now use ALWAYS_GM_FIELDS ∪ gm_fields(src) per ref_kind; pure test added.
  - (blind) `[low]` `[patch]` EV-4 leak scan vacuous for jobs/stored_files — added test_jobs_and_files_do_not_leak_to_player_or_anon with GM/other-Player Jobs and stale, GM-sourced, other-owner, sourceless files, plus a positive control.
  - (blind) `[false]` `[reject]` Player sees payload/result_ref of own Jobs — row visibility only; field exposure is JobResponse (E0-Jobs.7), which omits payload/worker_id and gates result_ref.
  - (blind) `[low]` `[reject]` no CHECKs for attempts/progress/size ranges — not in the story; writers (enqueue/worker/file service) own these invariants; adding CHECKs is extra surface.
  - (blind) `[low]` `[reject]` FKs without indexes / no reaper index — tables are empty at creation; Jobs.4/.5 add indexes for their query shapes.
  - (blind) `[low]` `[defer]` derived_sources orphans/duplicates — E0-Jobs.8 delete/gc (deferred).
  - (blind) `[medium]` `[defer]` no loader for a file's source pairs (same root as partial parents) — deferred to E0-Jobs.8.
  - (blind) `[low]` `[reject]` Mapped[StrEnum] on String columns — same convention as existing models (journal kind); equality works.
  - (blind) `[low]` `[reject]` two test definitions of "global model" — agree today; a shared export adds public surface for tests only.
  - (blind) `[false]` `[reject]` `internal` retryable — AD-4: "other exceptions retry after 10 s, then 60 s".
  - (blind) `[low]` `[patch]` snapshot test gaps (FK map order, ix_derived_sources_derived unchecked) — reordered and added the index check; the _ACTIVE_WHERE drift point rejected (drift test compares index columns; the migration literal is frozen by design).

## Design Notes

`stored_files` non-GM SQL (GM: `true`): `NOT stale AND kind IN <registered file types> AND (audience_owner_id IS NULL OR = viewer owner) AND EXISTS(ds) AND NOT EXISTS(ds WHERE NOT ok(ds))`, `ok(ds)` = ref_field not always-GM AND ref_kind allowed by the type's `derive_from` AND ref_kind has a model in `SOURCE_KIND_MODELS` whose row (same Campaign) passes its own `visible_clause`. Python twin: GM if stale / unregistered kind / no sources / any unresolvable or disallowed source; else `most_restrictive(source auds, field auds, Owner(audience_owner_id)?)`. Both fail closed, and `covers(meet) == AND(covers)` on this lattice, so they agree.

## Verification

**Commands:**
- `python scripts/check_table_owners.py` -- exit 0
- `cd src/backend && lint-imports` -- contracts kept (CI)
- GitHub CI `backend-tests.yml` -- full suite green incl. migrations, CI-10, CI-11, drift

## Auto Run Result

Status: done (PR #48, draft; CI is the gate)

**Summary:** Revision `cf62d979bc8a` (down `c95acb56c595`) creates `jobs`, `data_backfills`, `stored_files`, `derived_sources` with the listed indexes and enum-generated CHECKs; models exported; access registry entries (jobs owner rule, stored_files derived from sources, two global always_gm tables); `app.jobs` package with error codes; `app.jobs` joins the import contracts.

**Files changed:**
- `src/backend/migrations/versions/cf62d979bc8a_f2_jobs_files.py` -- the F2 revision (upgrade/downgrade).
- `src/backend/app/db/models/job.py`, `stored_file.py`, `__init__.py` -- the four models and their export.
- `src/backend/app/domain/enums.py` -- JobStatus, JobQueue, JobErrorCode.
- `src/backend/app/jobs/__init__.py`, `errors.py` -- JobErrorCode re-export, TERMINAL/RETRYABLE code sets.
- `src/backend/app/access/registry.py`, `context.py`, `__init__.py` -- owner rule on always_gm, derived_from_sources, SOURCE_KIND_MODELS/register_source_kind, global always_gm, scoped_select_multi branch.
- `src/backend/.importlinter`, `scripts/test_import_ratchet.py` -- app.jobs layer and forbidden lists.
- Tests: `test_enum_check_sync.py`, `domain/test_enums.py`, `migrations/test_upgrade_snapshot.py`, `access/test_registry_property.py`, `access/test_scoped_select.py`, `access/test_audience.py`, new `test_jobs_files_schema.py`.

**Review:** 33 findings. Patched 9 rows (5 entries: register_source_kind derived models [medium], model-specific gm_fields [medium], retryable codes import check, import contracts, tests for multi/EV-4/snapshot). Deferred 3 (partial-parents loader, global idempotency index, derived_sources cleanup) to E0-Jobs.2/.8. Rejected the rest with reasons in the triage log.

**Follow-up review recommended:** true -- two medium patches; the model-specific gm_fields narrowing is proven only by a compiled-SQL + Python unit test, not by CI-11 on real rows.

**Verification:** `python3 scripts/check_table_owners.py` exit 0; `lint-imports` 5 contracts kept; import ratchet 30 passed; first commit's full CI (backend tests on Postgres+pgvector, gates, licences, frontend) green; patch commit verified by CI on the PR.

**Residual risks:** see `deferred`. Needs desktop verification: none (schema-only story; no compose/runtime changes).
