---
title: 'E0-QA.6 (2.6): Migration-chain gates, and CI with no path filters'
type: 'chore'
created: '2026-11-01'
status: 'done'
baseline_revision: '5d44fc05a84c4e5ca60fde8556f2965c839ad3e8'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      The upgraded snapshot's schema is not compared with a fresh `upgrade head` schema.
    evidence: |-
      Blind review. A migration that behaves differently on a populated DB (a conditional DDL path, a server_default backfill) would produce a schema that differs from the empty-DB build. Today head equals the snapshot revision, so there is nothing to diverge yet. Worth adding with F1-core, e.g. by running compare_metadata (test_migrations_match_models) on the upgraded snapshot too.
    location: >-
      src/backend/tests/migrations/test_upgrade_snapshot.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Nothing proves that the Alembic chain has one head, or that `alembic upgrade head` works on a database that already holds data, which is what every self-hoster's boot runs. Backend CI and the licence gate also skip PRs that miss their `paths:` filters (AD-21, NFR-4).

**Approach:** Commit a seeded `pg_dump` of the schema at `a3e7c1f9d258` (made by `scripts/make_snapshot.py`). A new `tests/migrations/test_upgrade_snapshot.py` restores it, upgrades to head, checks row counts and runs the per-revision assertions registered in that file, and checks every FK's `ON DELETE` against an expected table. CI gains a single-head step and loses both workflows' `paths:` filters.

## Boundaries & Constraints

**Always:** The snapshot is built by migrating to the fixed revision `a3e7c1f9d258` (not `head`), so it stays the brownfield baseline after later revisions land. The seed is raw SQL with fixed ids and timestamps, independent of the ORM models, so the dump is deterministic. The fixture is restorable without `psql` (asyncpg simple-query execution), since the desktop test image has no Postgres client. The snapshot test leaves the session schema clean (rebuilt with `build_test_schema`) for the rest of the suite. The `_test` name guard runs before anything wipes a DB, in both the script and the test.

**Never:** No new migration and no model change. In `license-check.yml`, change only the `on:` filters (E0-QA.8 edits that file in parallel). Don't touch docker-compose*, `app/clients`, the ml sidecar, `llm_gate.py`, `pubsub.py`, `sprint-status.yaml` or `epics.md`. The 115-test CI baseline must not regress.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Snapshot upgrade | restored `snapshot_a3e7c1f9d258.sql` | upgrade reaches script head; every pre-existing table keeps its row count; registered checks pass | assertion names the table / check |
| Two heads | a branch adds a second head | CI step "Single Alembic head" and `test_single_alembic_head` fail | message lists the heads |
| New FK without stated action | revision adds an FK | `test_fk_on_delete_actions` fails, naming `table.column -> rule` | message tells the author to add it to `EXPECTED_FK_ON_DELETE` |
| Typo in check registry | key not a revision id | `test_post_upgrade_checks_name_real_revisions` fails | assertion lists the bad keys |
| Script on non-test DB | `--database-url .../lorekeeper` | exits non-zero before connecting | message names the rule |
| Newer pg_dump | emits `\restrict` meta-commands / version comments | stripped by the script, so output is stable and asyncpg can execute it | none |

</intent-contract>

## Code Map

- `src/backend/tests/conftest.py` -- reuse `TEST_DB_URL`, `_guard_test_database`, `alembic_config`, `build_test_schema`, `_reset_public_schema(url, with_vector=)`. Session fixture is the empty-DB `upgrade head` gate; `test_migrations_match_models.py::test_database_is_at_script_head` asserts it.
- `src/backend/tests/test_zz_schema_rebuild.py` -- precedent for a test that rebuilds the shared session schema mid-run.
- pytest collects `tests/migrations/` before `tests/test_*.py` ('m' < 't'), so the snapshot module must rebuild the clean schema in teardown.
- `src/backend/migrations/env.py` -- honours `attributes["sqlalchemy_url_locked"]` and `configure_logger=False`; imports `app.db.models`.
- `src/backend/migrations/versions/4b8f2d9e71c3_add_app_config.py` -- the only migration that inserts a row (`app_config` with `now()` timestamps); the seed pins those timestamps.
- `a3e7c1f9d258` -- `narrative_tsv = to_tsvector('english', shorthand || ' ' || narrative)`; the seed uses the same formula.
- Head schema (local probe): 27 tables, 41 FKs, all `CASCADE` except `chat_sessions.campaign_id` and `feedback.campaign_id` (`SET NULL`). Share token `kind ∈ {read_only, collaborate}`; Members are `campaign_members` rows; enums `genre`, `npcrole`, `npcstatus`, `queststatus`, `tagtype`.
- `src/backend/scripts/` -- backend scripts live here (`eval_retrieval.py`), so `scripts/make_snapshot.py` resolves to `src/backend/scripts/make_snapshot.py`, like the `tests/` paths.
- `.github/workflows/backend-tests.yml`, `.github/workflows/license-check.yml` -- `paths:` lists under `push` and `pull_request`.

## Tasks & Acceptance

**Execution:**
- `src/backend/scripts/make_snapshot.py` -- new. `--database-url` (test-named DB only), `--output` (default `tests/fixtures/snapshot_a3e7c1f9d258.sql`), `--pg-dump` (default `pg_dump`). Wipe `public`, create `vector`, `alembic upgrade a3e7c1f9d258`, insert the seed (1 Owner, 2 Members, 1 read-only + 1 collaborate token, 3 journal entries with Shorthand, 1 Shorthand term, 1 tag link, 2 NPCs, 2 Quests, 3 chat sessions: one per user), pin `app_config` timestamps, then `pg_dump --no-owner --no-privileges --column-inserts` and strip psql meta-commands and version comments.
- `src/backend/tests/fixtures/snapshot_a3e7c1f9d258.sql` -- generated by the script (local pgvector Postgres 16).
- `src/backend/tests/migrations/__init__.py`, `src/backend/tests/migrations/test_upgrade_snapshot.py` -- new. Module fixture: guard, restore the dump, record version + per-table counts, `upgrade head`, record again; teardown `build_test_schema`. Tests: single head; the restore is at `a3e7c1f9d258` with the seeded counts (not vacuous); upgraded to head; counts unchanged; parametrized `POST_UPGRADE_CHECKS` keyed by revision (seeded with an `a3e7c1f9d258` check that a Shorthand-only word still matches `narrative_tsv`); registry keys are real revisions; `EXPECTED_FK_ON_DELETE` equals the FKs in `information_schema.referential_constraints`.
- `.github/workflows/backend-tests.yml` -- drop `paths:`; add a "Single Alembic head" step (`alembic heads`, fail unless exactly one line) before the tests.
- `.github/workflows/license-check.yml` -- drop both `paths:` lists only.

**Acceptance Criteria:**
- Given a PR touching only docs, when it opens, then both `Backend tests` and `Dependency licences` run.
- Given the snapshot, when CI runs the suite, then `tests/migrations/test_upgrade_snapshot.py` passes and the overall count is 115 + the new tests.
- Given `make_snapshot.py` run twice on a fresh DB, when the outputs are diffed, then they are identical.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 37 findings — high 0, medium 7, low 18, false 3, maybe-false 0, plus 9 descriptive intent-alignment observations (logged as rows below, no verdict needed beyond the grouping)
- findings:
  - `[medium]` `[patch]` (verification-gap) The a3e7c1f9d258 check tests the seed, not the migration — added `test_a3e7c1f9d258_backfills_shorthand`, which downgrades the seeded snapshot to 8c1d5f3a92e7, asserts the shorthand-only word no longer matches, upgrades to head and asserts it matches again. The registered check is kept and re-documented as a guard against later revisions dropping shorthand from the index.
  - `[low]` `[reject]` (verification-gap other) An empty registry makes the parametrized test report "skipped" — it holds one entry, and E0-Access.1 adds more.
  - `[medium]` `[patch]` (blind) The upgrade does nothing while a3e7c1f9d258 is head — the module docstring now says so, and names F1-core as the first revision the gate bites on.
  - `[medium]` `[patch]` (blind) The registered check re-checks the seed — same fix as the verification-gap row; the false comment in make_snapshot.py is corrected.
  - `[low]` `[reject]` (blind) Registry keys should come after SNAPSHOT_REVISION — the a3e7c1f9d258 guard entry is deliberately keyed to the revision whose invariant it protects.
  - `[medium]` `[defer]` (blind) No schema comparison between the upgraded snapshot and a fresh head — see the deferred entry. Nothing can diverge until a revision lands after the snapshot.
  - `[low]` `[reject]` (blind) Most tables have no seed rows — the story fixes the dataset (Owner, Members, tokens, entries, NPCs, Quests, chats); later revisions can extend the seed via the script.
  - `[low]` `[reject]` (blind) No test that the committed SQL matches the script — `test_seed_matches_the_snapshot_test_counts` ties seed to counts, and regenerating it needs pg_dump, which the desktop test image lacks; determinism is checked by hand (cmp).
  - `[low]` `[patch]` (blind) SNAPSHOT_REVISION is defined twice — `test_snapshot_revision_agrees_with_the_test_module` asserts the revision and the fixture path agree.
  - `[medium]` `[patch]` (blind) clean_dump's blank-line collapse and leading-backslash strip could alter multi-line literals — it now drops only whole `\restrict`/`\unrestrict`, version-comment and `SET transaction_timeout` lines; `test_clean_dump_keeps_literal_contents` covers it. The fixture was regenerated (header blank lines only).
  - `[low]` `[patch]` (blind) The byte-identical claim ignores the pg_dump version — the docstring names pg_dump major 16.
  - `[medium]` `[patch]` (blind) Password on pg_dump's argv — passed through PGPASSWORD; the URI is built without it; `test_password_goes_to_env_not_argv`.
  - `[low]` `[patch]` (blind) Missing pg_dump found only after the wipe — `shutil.which` check before any DB work; `test_refuses_missing_pg_dump_before_touching_the_db`.
  - `[low]` `[patch]` (blind) Unparseable-URL branch untested — `test_refuses_unparseable_url_without_echoing_it`. The pg_dump-nonzero branch is a plain return of the exit code; not tested (needs a fake pg_dump plus a DB).
  - `[low]` `[patch]` (blind) `_fk_rules` collapses two FKs on one column — rules are collected into sets and any column with more than one rule fails. Composite FKs appear as one key per column, which still states each column's rule.
  - `[low]` `[reject]` (blind) No declared exceptions for intended row-count changes — the AC says counts stay unchanged; a revision that must change them adds the mechanism with its reason.
  - `[low]` `[reject]` (blind) The CI head step duplicates the pytest check — the AC asks for a job that fails on `alembic heads`; the pytest copy covers local and desktop runs.
  - `[low]` `[reject]` (blind) license-check.yml gets no comment on why it has no filter — the brief keeps that file's change to the filter removal (E0-QA.8 overlap). pages.yml is a deployer, not a gate.
  - `[low]` `[reject]` (blind) The teardown can hide the original error; xdist would break the shared schema — xdist is not used; the same holds for test_zz_schema_rebuild.
  - `[low]` `[reject]` (blind) No downgrade round trip — the new a3e7c1f9d258 test runs one downgrade on seeded data; downgrades are not production paths (forward-only, AD-19).
  - `[medium]` `[patch]` (edge) The upgrade gate is vacuous today (claim) — same as the blind docstring row.
  - `[medium]` `[patch]` (edge) The a3e7c1f9d258 check tests the seed (claim) — same as the verification-gap row.
  - `[medium]` `[patch]` (edge) pg_dump 17+ emits `SET transaction_timeout`, which PG16 rejects — stripped by clean_dump; covered in `test_clean_dump_strips_meta_commands_and_version_comments`.
  - `[low]` `[patch]` (edge) Missing pg_dump — same as the blind row.
  - `[low]` `[reject]` (edge) asyncpg-only query params break pg_dump — the URI now carries no query params at all, and the script is a developer tool run against a local test DB.
  - `[low]` `[patch]` (edge) Password on argv — same as the blind row.
  - `[false]` `[reject]` (edge) Two FKs on different tables sharing a constraint_name would map wrongly — the 41 current FKs have distinct names (Alembic's `<table>_<col>_fkey` convention). A cross-product would add keys that fail the comparison, not a silent pass.
  - `[low]` `[patch]` (edge) Two FKs on one column with different rules — same as the blind `_fk_rules` row.
  - `[low]` `[reject]` (edge) No row-delta declaration — same as the blind row.
  - `[false]` `[reject]` (edge) get_current_head raises on multiple heads — `test_single_alembic_head` and the CI step report that case readably; a raise is still a failure.
  - `[false]` `[reject]` (intent) Script location — `src/backend/scripts/` holds the other E0-QA scripts named `scripts/eval_*.py` in the boundary map, and the `tests/` paths are also backend-relative.
  - `[low]` `[reject]` (intent) Gates mostly run as pytest in the backend job rather than as separate jobs — the head check is its own step; the others need the Postgres service and the suite's fixtures, and run in the same job on every PR.
  - `[low]` `[reject]` (intent) The empty-DB upgrade has no new named check — E0-QA.5's session fixture runs it on every CI run and `test_database_is_at_script_head` asserts it.
  - `[low]` `[reject]` (intent) The snapshot is built by upgrading to the revision, not by checking it out — equivalent while migrations are immutable (AD-19), and it keeps the script runnable from any later tree.
  - `[low]` `[reject]` (intent) No test of the workflow YAML itself — confirmed by CI: this docs-free PR triggers both workflows.
  - `[low]` `[reject]` (intent) Byte-identical regeneration is untested — same as the blind fixture-drift row.
  - `[low]` `[patch]` (intent) Registered check tests the seed — same as the verification-gap row.

## Auto Run Result

Status: done

**Summary:** CI now proves that the migration chain has one head and upgrades a seeded copy of today's schema, and both gate workflows run on every PR and on every push to `main`.

**Files changed:**
- `.github/workflows/backend-tests.yml`: no `paths:` filter; new "Single Alembic head" step.
- `.github/workflows/license-check.yml`: only the two `paths:` lists are removed.
- `src/backend/scripts/make_snapshot.py` (new): guarded `_test` DB, `upgrade a3e7c1f9d258`, raw-SQL seed with fixed ids and timestamps, `pg_dump --column-inserts` (password through PGPASSWORD), stable cleanup.
- `src/backend/tests/fixtures/snapshot_a3e7c1f9d258.sql` (new): the dump (local PG 16.2 + pgvector).
- `src/backend/tests/migrations/test_upgrade_snapshot.py` (new, 8 tests): single head, seeded restore, head reached, counts unchanged, `POST_UPGRADE_CHECKS` registry and key check, `EXPECTED_FK_ON_DELETE` (41 FKs), a3e7c1f9d258 downgrade/upgrade round trip on seeded rows.
- `src/backend/tests/migrations/test_make_snapshot.py` (new, 9 tests): dump cleanup, refusals, password handling, seed/count and revision agreement.

**Review:** 37 findings. 13 patched rows (7 medium, 6 low, several sharing a root cause), 1 deferred (schema comparison after a brownfield upgrade), the rest rejected with reasons above. Follow-up review recommended: false. No high was patched; the patched mediums share two root causes (the vacuous a3e7c1f9d258 check and the dump/argv handling), both covered by new tests.

**Verification:**
- `make_snapshot.py` run twice: byte-identical output; refused on `lorekeeper` (exit 2).
- Local suite without test_nlp: 129 passed.
- CI run of the first commit (PR #26): backend 126 passed, the "Single Alembic head" step printed `a3e7c1f9d258 (head)`, and the licence and frontend workflows ran and passed.

**Residual risks:**
- The row-count and registry gates only bite once a revision after `a3e7c1f9d258` lands.
- The snapshot was dumped by pg_dump 16.2. CI restores it into pgvector/pgvector:pg16 with a newer pgvector, which worked.
- Sprint-status sync skipped by orchestrator rule.

**Needs desktop verification:** run the suite with the brief's docker command against `lorekeeper_test_<lane>`. Expected: all pass, and `tests/migrations` restores the snapshot without `psql` (the test image has no Postgres client).

## Verification

**Commands:**
- Local throwaway pgvector Postgres 16 on `localhost:55436` (trust auth, user `lorekeeper`, DB `lorekeeper_test`, already running). The wrapper `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/qa6/py.sh <args>` runs the backend venv python from `src/backend` with `DATABASE_URL`/`TEST_DATABASE_URL` set to that DB and `pg_dump`/`psql` on PATH (a stub fakes `sentence_transformers`; never commit it); `.../scratchpad/qa6/psql.sh` opens psql on the DB. Run: `python scripts/make_snapshot.py --database-url postgresql+asyncpg://lorekeeper@localhost:55436/lorekeeper_test` twice, `diff` -- expected: identical.
- Same DB: `python -m pytest -q -p no:cacheprovider -W ignore --ignore=tests/test_nlp.py` -- expected: all pass.
- `python -m alembic heads | wc -l` -- expected: 1.
- CI on the draft PR -- expected: all workflows green.
