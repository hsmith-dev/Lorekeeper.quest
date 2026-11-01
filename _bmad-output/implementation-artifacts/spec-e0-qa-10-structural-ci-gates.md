---
title: 'E0-QA.10 Structural CI gates: layers, model packages, table owners, enum sync, memory sum'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '180fe80caa1ce32d048d9bb6fe40e05acd6c1c3c'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Six lanes merge in parallel and nothing in CI enforces AD-1 layering, the no-model-packages rule, one-owner-per-table (AD-19), StrEnum/CHECK sync (AD-9) or the AD-7 14.5 GB memory sum, so any of them can drift silently.

**Approach:** One small script (or contract file) per gate, each with unit tests and a failure message that says what to do, plus a new `.github/workflows/gates.yml` (no path filter) where every structural gate is one named step. Where today's code misses the target architecture, the gap is an explicit, reasoned, shrink-only baseline.

## Boundaries & Constraints

**Always:**
- Every gate passes on today's `main` (after E0-Platform.3 / PR #27) and fails on a planted violation in its unit tests.
- Baselines are shrink-only: a test holds a frozen ceiling, and a baseline entry that no longer matches anything fails ("remove it").
- Every baseline or allowlist entry carries a reason.
- `import-linter` (and its `grimp` engine) are pinned in `requirements-dev.txt` and registered in `licenses/register.yaml` (BSD-2-Clause, dev only).

**Never:**
- Edit `ARCHITECTURE-SPINE.md`, `epics.md` or `sprint-status.yaml`, or app code (code that fails a gate goes into a baseline).
- Touch `docs/RETRIEVAL_EVAL.md`, `prompt_budget.py` or frontend nav (wave siblings).
- Implement the other epics' gates (CI-5, 8, 9, 11, 13, 15); only reserve their slots in `gates.yml`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Layer break | `app.db` module imports `app.services` | `lint-imports` exits 1 naming the import | contract name in output |
| Ratchet grows | a line added to an `ignore_imports` list | ratchet test fails | names the new line |
| Model pkg | `torch` pinned in requirements or a Dockerfile `pip install`, not in baseline | exit 1 | names file and package |
| Stale baseline | baseline lists `easyocr` but it is gone | exit 1 | "remove it from the baseline" |
| Double owner | a table in two epics' "Owns (tables)" | exit 1 | names both owners |
| Unowned table | migration `create_table('maps_x')` with no owner and not legacy | exit 1 | names migration file |
| Enum drift | registered StrEnum has a member missing from the CHECK | test fails | lists missing/extra values |
| No enum pairs | registry empty | passes | — |
| Memory over | `*_MEM_LIMIT` sum > 14.5 GiB | exit 1 | prints each limit and the sum |
| No limits | no `*_MEM_LIMIT` in `.env.example` | passes vacuously | — |
| Compose drift | compose uses `${X_MEM_LIMIT:-d}` not declared in `.env.example`, or with a different default | exit 1 | names the variable |

</intent-contract>

## Code Map

- `src/backend/app/{api,services,schemas,db,core}` -- today's layer graph: api > services > schemas > db > core > domain holds with no violations (checked with import-linter 2.15).
- `src/backend/app/services/{nlp,embedding,transcription,vision}_service.py` -- the only direct model imports today (spacy, sentence_transformers, whisper, easyocr): the import ratchet baseline; E0-Platform.6 removes them.
- `src/backend/app/clients/`, `src/backend/app/domain/` -- arrive with PR #27 (E0-Platform.3; this branch is temporarily based on its head, so they exist locally); `ml.py` imports only `app.core` and `app.domain`. Forbidden contracts need these packages to exist.
- `src/backend/requirements.txt`, `src/backend/Dockerfile`, `src/backend/Dockerfile.prod` -- the web/worker image; torch comes from a Dockerfile `pip install`, the rest from requirements.
- `src/backend/migrations/versions/*.py` -- 26 legacy `op.create_table` calls, none owned in the boundary map.
- Spine `## Capability → Architecture Map` table (column "Owns (tables)") and AD-19 Foundation bullets (F1-core: columns/enums only; F2: 4 tables; F3: 7 tables). `epics.md` "New tables and columns beyond the spine" adds owners (mostly columns).
- `.env.example`, `docker-compose*.yml` -- PR #27 adds `# ML_MEM_LIMIT=2560m` (commented default) and `memory: ${ML_MEM_LIMIT:-2560m}`.
- `scripts/test_check_licenses.py` -- pattern for script unit tests (importlib load from `scripts/`).
- `src/backend/tests/conftest.py` -- `db` fixture (AsyncSession on the migrated test DB) for the enum sync test.

## Tasks & Acceptance

**Execution:**
- `src/backend/.importlinter` -- contracts: `layers` (api > services > schemas > db > core > (domain)), `domain` (forbidden: every other app package), `clients` (forbidden: api, services, schemas, db, main), `models` (forbidden external model packages from all non-client app code, direct imports only) with today's four imports in `ignore_imports`, each under a `# ratchet:` comment line.
- `scripts/test_import_ratchet.py` -- the ratchet: every `ignore_imports` line is in a frozen ceiling and has a `# ratchet` reason; the contracts named in the AC exist.
- `scripts/check_model_packages.py` + `scripts/model_packages_baseline.txt` + `scripts/test_check_model_packages.py` -- scan requirements and Dockerfile `pip install` lines (PEP 503 names) for the forbidden list (plus AD-16's kokoro-onnx, misaki, phonemizer, espeakng-loader); baseline `torch, spacy, sentence-transformers, openai-whisper, easyocr` with reasons.
- `scripts/check_table_owners.py` + `scripts/table_owners_legacy.txt` + `scripts/test_check_table_owners.py` -- parse spine table + AD-19 + epics additions, fail on two owners, on an unowned `create_table`/`CREATE TABLE`, or on a legacy entry that is also owned or no longer created; legacy list frozen in the test.
- `src/backend/tests/test_enum_check_sync.py` -- `ENUM_CHECKS` registry (empty), a `pg_constraint` reader, a self-test of the reader on a temporary CHECK table, and the per-pair comparison.
- `scripts/check_memory_budget.py` + `scripts/test_check_memory_budget.py` -- sum active and commented `*_MEM_LIMIT=` defaults in `.env.example` (binary units), limit 14.5 GiB inclusive; compose `${X_MEM_LIMIT:-d}` must be declared with the same value.
- `.github/workflows/gates.yml` -- jobs `static` (one named step per gate + the gate unit tests) and `database` (Postgres; enum sync); commented slots for CI-5/8/9/11/12/13/15 with owning stories.
- `src/backend/requirements-dev.txt`, `licenses/register.yaml` -- pin and register import-linter and grimp.

**Acceptance Criteria:**
- Given today's main, when `gates.yml` runs, then every step passes.
- Given a planted violation for each gate, when its unit tests run, then each fails with a message naming the offender and the fix.

## Design Notes

Table-name extraction in AD-19 bullets: backticked tokens are grouped when joined only by `,`/`and`; a group is columns, not tables, if any member is dotted (`table.column`) or the next word is `enum(s)`, `column(s)`, `uniqueness` or `index`. F1-core therefore yields no tables, matching AD-19 ("enums and columns on existing tables").

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- expected: all contracts kept
- `python -m pytest -q scripts/test_import_ratchet.py scripts/test_check_model_packages.py scripts/test_check_table_owners.py scripts/test_check_memory_budget.py` -- expected: pass
- `python scripts/check_model_packages.py && python scripts/check_table_owners.py && python scripts/check_memory_budget.py` -- expected: exit 0
- CI: `gates.yml`, `backend-tests.yml`, `license-check.yml` green on the draft PR

**Local tooling (no desktop):** `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/il-venv/bin/` has Python 3.11 with import-linter 2.15 (grimp 3.18), pytest and pyyaml; run `lint-imports` from `src/backend` with `PYTHONPATH=.`. Backend runtime deps and Postgres are not available locally, so `tests/test_enum_check_sync.py` gets `python -m py_compile` locally and runs for real in CI. Do not commit, push or open PRs; the orchestrating agent does that.
