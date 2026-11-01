---
title: 'E0-QA.6 (2.6): Migration-chain gates, and CI with no path filters'
type: 'chore'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '5d44fc05a84c4e5ca60fde8556f2965c839ad3e8'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
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

## Verification

**Commands:**
- Local throwaway pgvector Postgres 16 on `localhost:55436` (trust auth, user `lorekeeper`, DB `lorekeeper_test`, already running). The wrapper `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/qa6/py.sh <args>` runs the backend venv python from `src/backend` with `DATABASE_URL`/`TEST_DATABASE_URL` set to that DB and `pg_dump`/`psql` on PATH (a stub fakes `sentence_transformers`; never commit it); `.../scratchpad/qa6/psql.sh` opens psql on the DB. Run: `python scripts/make_snapshot.py --database-url postgresql+asyncpg://lorekeeper@localhost:55436/lorekeeper_test` twice, `diff` -- expected: identical.
- Same DB: `python -m pytest -q -p no:cacheprovider -W ignore --ignore=tests/test_nlp.py` -- expected: all pass.
- `python -m alembic heads | wc -l` -- expected: 1.
- CI on the draft PR -- expected: all workflows green.
