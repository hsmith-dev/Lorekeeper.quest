---
title: 'E0-QA.10 Structural CI gates: layers, model packages, table owners, enum sync, memory sum'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '180fe80caa1ce32d048d9bb6fe40e05acd6c1c3c'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      CI-10 only checks registered (StrEnum, table, column) pairs; an unregistered StrEnum-backed CHECK passes.
    evidence: |-
      ENUM_CHECKS is opt-in. app/domain/enums.py does not exist yet; when E0-WorldCore adds it, a completeness check (every StrEnum there registered or exempted) settles it.
    location: >-
      src/backend/tests/test_enum_check_sync.py
    severity: medium (unverified)
  - summary: >-
      CI-3 reads package names as written, so a model package pulled in transitively is invisible.
    evidence: |-
      E0-Platform.6's AC adds the `pip list` check inside the built web/worker image; until then the Dockerfiles' own torch import guard is the only image-level check.
    location: >-
      scripts/check_model_packages.py
    severity: medium (unverified)
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

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 39 findings — high 0, medium 10, low 21, false 3, maybe-false 5
- findings:
  - `[medium]` `[patch]` blind: torchvision/torchaudio not forbidden in CI-3 — added to FORBIDDEN, torchvision baselined (goes with torch), test fixed.
  - `[medium]` `[patch]` blind: app.clients could import model packages — app.clients added to the `models` contract sources.
  - `[low]` `[patch]` blind: nothing stops schemas/db/core/domain importing app.clients — new `clients_callers` contract.
  - `[medium]` `[patch]` blind: ratchet does not freeze the full forbidden_modules list — source/forbidden sets frozen by equality.
  - `[medium]` `[patch]` blind: CI-14 ignores literal compose limits — literal limits now detected; the five prod literals sit in shrink-only `scripts/memory_literal_limits_baseline.txt` (E0-Platform.7 moves them to variables), reported outside the sum.
  - `[low]` `[reject]` blind: legacy "no longer created" can never fire (append-only migrations) — harmless dead branch; rename case handled by the rename_table patch below.
  - `[low]` `[patch]` blind: raw-SQL regex over whole file with re.I — restricted to non-docstring string constants, `(` required.
  - `[low]` `[patch]` blind: StopIteration on renamed epics.md column — ValueError with the gate message.
  - `[maybe-false]` `[defer]` blind: CI-10 is opt-in, unregistered StrEnum passes — app/domain/enums.py does not exist yet; settle when E0-WorldCore adds it (completeness check over its StrEnums).
  - `[low]` `[reject]` blind: database job duplicates backend-tests install — deliberate: AC wants every gate as a named gates.yml step; cost ~3 min.
  - `[medium]` `[patch]` blind: `spacy download en_core_web_trf` installs a model package unscanned — counted as an install, spaCy pipelines forbidden, en-core-web-trf baselined.
  - `[false]` `[reject]` blind: spec says 26 legacy tables vs 27 — fix would edit this build's spec.
  - `[false]` `[reject]` blind: spec has session-only tooling paths — fix would edit this build's spec.
  - `[low]` `[patch]` blind: GB vs GiB unstated — docstring/message now say AD-7 is read as GiB (Docker `g` is binary), test pins it.
  - `[low]` `[reject]` blind: static job only pins direct tools — transitive drift of click/rich is unlikely to change gate results; fix adds a lockfile.
  - `[low]` `[reject]` intent: layers put core below db although the spine's table lists db → domain only — `app/db/session.py` reading `app.core.config` is engine wiring every layer needs; story AC names only api → services → db.
  - `[medium]` `[patch]` verification-gap: literal compose `memory:` never counted — same fix as the CI-14 literal-limit patch above.
  - `[medium]` `[patch]` verification-gap: torchvision/torchaudio missing from CI-3 — same fix as above.
  - `[maybe-false]` `[defer]` verification-gap other: name-only scan cannot see transitive installs — E0-Platform.6 adds the `pip list` image check per its AC.
  - `[medium]` `[patch]` edge: literal compose limits — same fix as above.
  - `[low]` `[reject]` edge: one variable shared by several services counted once — no shared variable exists; would add per-service counting.
  - `[low]` `[patch]` edge: `_REF` misses `:?`, `:+`, unbraced — regex widened.
  - `[low]` `[patch]` edge: compose.yaml names not globbed — glob widened.
  - `[low]` `[patch]` edge: PEP 508 direct reference returns None — name before `@` parsed.
  - `[low]` `[reject]` edge: exec-form RUN not scanned — no exec-form RUN in the repo; adds a parser branch.
  - `[low]` `[reject]` edge: heredoc RUN not scanned — none in the repo; adds a parser.
  - `[low]` `[reject]` edge: `-rmore.txt` without space skipped — unidiomatic, not used.
  - `[medium]` `[patch]` edge: torchvision/torchaudio unflagged — same fix as the CI-3 patch above.
  - `[low]` `[patch]` edge: inline ignore_imports value skipped by ratchet parser — captured with reason None so both checks fail.
  - `[medium]` `[patch]` edge: forbidden_modules deletion passes — same fix as the frozen-set patch.
  - `[low]` `[patch]` edge: `"public"."widgets"` captures `public` — schema qualifier stripped.
  - `[low]` `[patch]` edge: rename_table / non-literal create_table bypass — rename_table new name counted.
  - `[low]` `[patch]` edge: StopIteration/IndexError on malformed epics table — ValueError, short rows skipped.
  - `[low]` `[reject]` edge: second Markdown table in a section — not present in the docs; parser fails loudly on bad headers anyway.
  - `[maybe-false]` `[reject]` edge: mixed cell (new table + dotted column) drops the new table — documented cell rule (Design Notes); needed so `recap_now` etc. are not read as tables; would be low.
  - `[low]` `[reject]` edge: non-class ENUM_CHECKS entry gives TypeError — loud failure is acceptable.
  - `[maybe-false]` `[patch]` edge claim: gate claims AD-7 coverage it lacks — docstring and gates.yml comment now state literals are baselined, not summed.
  - `[maybe-false]` `[patch]` edge claim: inline ignore line escapes ratchet — same fix as above.
  - `[false]` `[reject]` intent: gates.yml other-epic slots are comments, not steps — AC says they become steps "when those epics land their scripts"; slots are reserved.

## Design Notes

Table-name extraction in AD-19 bullets: backticked tokens are grouped when joined only by `,`/`and`; a group is columns, not tables, if any member is dotted (`table.column`) or the next word is `enum(s)`, `column(s)`, `uniqueness` or `index`. F1-core therefore yields no tables, matching AD-19 ("enums and columns on existing tables").

## Verification

**Commands:**
- `cd src/backend && lint-imports` -- expected: all contracts kept
- `python -m pytest -q scripts/test_import_ratchet.py scripts/test_check_model_packages.py scripts/test_check_table_owners.py scripts/test_check_memory_budget.py` -- expected: pass
- `python scripts/check_model_packages.py && python scripts/check_table_owners.py && python scripts/check_memory_budget.py` -- expected: exit 0
- CI: `gates.yml`, `backend-tests.yml`, `license-check.yml` green on the draft PR

**Local tooling (no desktop):** `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/il-venv/bin/` has Python 3.11 with import-linter 2.15 (grimp 3.18), pytest and pyyaml; run `lint-imports` from `src/backend` with `PYTHONPATH=.`. Backend runtime deps and Postgres are not available locally, so `tests/test_enum_check_sync.py` gets `python -m py_compile` locally and runs for real in CI. Do not commit, push or open PRs; the orchestrating agent does that.

## Auto Run Result

Status: done

**Summary:** New `.github/workflows/gates.yml` (no path filter) holds every structural gate as one named step: CI-2 import-linter AD-1 contracts plus a shrink-only `ignore_imports` ratchet, CI-3 model-package ratchet, CI-7 one owner per table, CI-10 StrEnum/CHECK sync (empty registry, reader self-tested on Postgres), and CI-14 memory sum <= 14.5 GiB. Commented slots are reserved for CI-5/8/9/11/12/13/15. Rebased onto main after E0-Platform.3 (#27): `app.clients`/`app.domain` are in the contracts, and `ML_MEM_LIMIT` (2.5 GiB) is summed.

**Files:**
- `.github/workflows/gates.yml` -- static job (CI-2, CI-3, CI-7, CI-14 + gate unit tests) and database job (CI-10); reserved slots.
- `src/backend/.importlinter` -- 5 contracts: layers, domain, clients, clients_callers, models (4 ratcheted model imports).
- `scripts/test_import_ratchet.py` -- frozen ceiling, reasons, contract shapes, planted violations via real lint-imports.
- `scripts/check_model_packages.py`, `scripts/model_packages_baseline.txt`, `scripts/test_check_model_packages.py` -- requirements + Dockerfile pip installs + `spacy download`; baseline of 7 with reasons.
- `scripts/check_table_owners.py`, `scripts/table_owners_legacy.txt`, `scripts/test_check_table_owners.py` -- spine map + AD-19 + epics additions; 27 legacy tables with reasons.
- `scripts/check_memory_budget.py`, `scripts/memory_literal_limits_baseline.txt`, `scripts/test_check_memory_budget.py` -- `*_MEM_LIMIT` sum, compose drift, baselined literal compose limits (five prod literals, E0-Platform.7 removes them).
- `src/backend/tests/test_enum_check_sync.py` -- CI-10.
- `src/backend/requirements-dev.txt`, `licenses/register.yaml` -- import-linter 2.15 and grimp 3.18 (BSD-2-Clause, dev only).

**Review:** 39 findings. 25 patched (10 medium, 15 low/maybe-false), 2 deferred (see frontmatter), 12 rejected with reasons in the triage log. Follow-up review recommended: true. Ten medium entries were patched; the reworked memory-literal and table-owner parsing landed after the review pass and has not been reviewed independently.

**Verification:** locally, the gate unit tests pass (114), `lint-imports` keeps 5 contracts, the three check scripts exit 0, and `scripts/test_check_licenses.py` passes 97. PR #29's first CI run was all green, including the database job (enum sync, 6 passed) and the backend suite. The post-review push goes back through CI.

**Needs desktop verification:** none. Every gate is static or runs in CI against Postgres.

**Residual risks:** the AD-7 sum covers only variable limits until E0-Platform.7 converts the five literal compose limits; the literal baseline makes them visible and shrink-only. Sprint-status sync was skipped per the builder brief (the orchestrator owns `sprint-status.yaml`).
