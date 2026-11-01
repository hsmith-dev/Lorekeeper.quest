---
title: 'E0-QA.5 (2.5): Tests build the schema from Alembic migrations'
type: 'chore'
created: '2026-10-31'
status: 'done'
baseline_revision: 'fc1806a9a15f2da98765b946e20d733d46fb2114'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      Two models omit the UniqueConstraint that their migrations create, which leaves a redundant unique constraint on top of a unique index.
    evidence: |-
      compare_metadata reports remove_constraint for password_reset_tokens.token_hash and promo_codes.code. The migrations f5e6a7b8c9d0 and b1a2c3d4e5f6 add both sa.UniqueConstraint and a unique index, while the models declare unique=True, index=True. The story allows no fix migration, so both are in IGNORED_DIFFS.
    location: >-
      src/backend/tests/test_migrations_match_models.py IGNORED_DIFFS
    severity: low
  - summary: >-
      Twelve columns have server defaults in the migrations that the models do not declare, so they show up only with compare_server_default=True.
    evidence: |-
      With compare_server_default=True there are 12 modify_default diffs, among them users.is_admin/access_granted/is_suspended/has_completed_tutorial/failed_login_attempts, user_settings.llm_provider/llm_temperature/llm_max_tokens/hosted_model_variant, promo_codes.grants_plan and training_samples.is_validated. Fixing them means editing the models, which is out of E0-QA.5 scope.
    location: >-
      src/backend/app/db/models/*
    severity: low
  - summary: >-
      Migration 4b8f2d9e71c3 seeds app_config.open_access_mode=true, but Settings.open_access_mode defaults to False. The test fixture resets the row to the settings value.
    evidence: |-
      Under create_all, get_app_config created the row from settings (False), and the suite was written against that gated state. A fresh production migrate is open-access. Whether the two should agree is an owner/product question.
    location: >-
      src/backend/tests/conftest.py _reset_app_config
    severity: low
---

<intent-contract>

## Intent

**Problem:** `tests/conftest.py` builds the test schema with `Base.metadata.drop_all/create_all`, so the suite never exercises the migration chain production boots with, and model/migration drift goes unnoticed. `migrations/env.py` imports only five models, and `AppConfig` is missing from `app.db.models.__all__`.

**Approach:** The session fixture resets the `public` schema, creates `vector`, and runs `alembic.command.upgrade(cfg, "head")` with `sqlalchemy.url` set to `TEST_DB_URL`. Teardown drops and recreates `public`. `env.py` imports the whole models package and honours a programmatically set URL. A new test runs `compare_metadata` against the migrated DB. `conftest.py` sets `ENVIRONMENT=test` and `JOBS_EAGER=1` before importing `app.main`.

## Boundaries & Constraints

**Always:** Keep `TEST_DATABASE_URL` resolution and the `_test` name guard (E0-QA.4) unchanged. The guard runs before any connection. `create_all`/`drop_all` disappear from `conftest.py`. `env.py` keeps working unchanged for the CLI (`alembic upgrade head` from `DATABASE_URL`/`.env`). Leave `REDIS_URL` alone. The 99-test CI baseline must not regress.

**Never:** No new migration and no model change to resolve drift. Drift goes into the commented ignore list and is reported. Don't touch `DATABASE_URL` handling in the app, the Dockerfiles, licence tooling, `llm_gate.py`/`pubsub.py`, or the CI path filters (E0-QA.6).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Empty DB | fresh `lorekeeper_test` (CI) | `vector` created, migrated to head (`a3e7c1f9d258`), suite runs | none |
| Leftover create_all tables | lane DB from an older run, no `alembic_version` | schema reset first, so the upgrade does not hit "already exists" | none |
| `.env` has another `DATABASE_URL` | env.py loads repo `.env` | migration still targets `TEST_DB_URL` | none |
| Password contains `%` | `TEST_DATABASE_URL` with `%` | escaped for ConfigParser, connects | none |
| Non-test DB name | `.../lorekeeper` | aborts before connecting (unchanged) | `pytest.exit` |
| Model/migration drift | model differs from migrated DB | `test_migrations_match_models` fails, listing the diffs | assertion message |

</intent-contract>

## Code Map

- `src/backend/tests/conftest.py` -- `setup_test_db` (session, autouse) runs `drop_all/create_all`. Guard `_guard_test_database`, `TEST_DB_URL`. `app.main` is imported at module top (line 13), so the env vars must be set above it.
- `src/backend/migrations/env.py` -- `fileConfig` at line 15 (would reset pytest's loggers). It loads `.env` via `setdefault`, overwrites `sqlalchemy.url` from `DATABASE_URL` (line 30), and imports five models at line 34. Online mode uses `asyncio.run`, which is safe from a sync fixture.
- `src/backend/alembic.ini` -- `script_location = migrations` (relative to the ini dir), `sqlalchemy.url = %(DATABASE_URL)s`.
- `src/backend/app/db/models/__init__.py` -- `AppConfig` is imported after `__all__` (line 33) and not listed.
- `migrations/versions/4b8f2d9e71c3_add_app_config.py` -- seeds `app_config(id=1, open_access_mode=true)`. Under create_all no row existed and `app_config_service.get_app_config` created one from `settings.open_access_mode` (False). The fixture must restore that gated baseline, because tests were written against it.
- `migrations/versions/7ffedba22a12` -- also creates `vector` (IF NOT EXISTS).
- Local drift probe (pgvector 0.6.2, head): `compare_metadata` reports only two diffs. `password_reset_tokens.token_hash` and `promo_codes.code` each have a `UniqueConstraint` in the migration plus a unique index, while the model declares `unique=True, index=True` (index only), giving `remove_constraint`. The constraint is redundant but harmless. With `compare_server_default` turned on, 12 more appear (migrations have server defaults that the models lack). That option is off by default in autogenerate, so it is not used.
- `.github/workflows/backend-tests.yml` -- CI service `pgvector/pgvector:pg16` with superuser `lorekeeper`, so `DROP SCHEMA`/`CREATE EXTENSION` are allowed.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/db/models/__init__.py` -- move the `AppConfig` import with the others and add it to `__all__` -- AR-19 registration.
- `src/backend/migrations/env.py` -- `import app.db.models` (whole package). Skip the `DATABASE_URL` override when `config.attributes["sqlalchemy_url_locked"]` is set, and skip `fileConfig` when `config.attributes["configure_logger"]` is False -- programmatic callers keep their URL and their loggers.
- `src/backend/tests/conftest.py` -- set `ENVIRONMENT=test` and `JOBS_EAGER=1` before importing `app.main`. Add `alembic_config(url)`, which builds a Config from `alembic.ini` by absolute path, `%`-escapes the URL and sets the attributes. The fixture runs guard, `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`, `CREATE EXTENSION vector`, `command.upgrade(cfg, "head")`, then `UPDATE app_config SET open_access_mode = <settings default>`. Teardown runs `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`. Remove the `Base` import, `create_all` and `drop_all`.
- `src/backend/tests/test_migrations_match_models.py` -- new. `compare_metadata(MigrationContext(conn, compare_type=True), Base.metadata)` over the migrated DB, minus a commented ignore list (the two redundant unique constraints), asserting no diffs. Also assert that the DB is at the script head, and add a sanity test that an extra model table is detected, so the check is not vacuous. Matrix coverage in the same file: (a) `alembic_config` escapes `%` and sets the lock attribute; (b) `command.current(alembic_config(TEST_DB_URL))` still succeeds with `DATABASE_URL` monkeypatched to an unreachable non-test URL, which shows env.py honours the locked URL; (c) create a stray table `zz_leftover_create_all` and empty `alembic_version`, then call the conftest's schema-build helper on `TEST_DB_URL`. Afterwards the stray table is gone, `alembic_version` is at head and `app_config.open_access_mode` equals the settings default. Put (c) last in the file. It rebuilds the session schema, so later tests must not depend on rows committed earlier (none do; `promo_code` re-creates its row).

**Acceptance Criteria:**
- Given an empty test DB, when the session fixture runs, then `alembic_version` equals the script head and every existing test passes in CI (99 or more).
- Given `tests/conftest.py`, when grepped, then neither `create_all` nor `drop_all` appears.
- Given a model column that is added without a migration, when `test_migrations_match_models.py` runs, then it fails and names the difference.
- Given pytest starts, when `app.main` is imported, then `os.environ["ENVIRONMENT"] == "test"` and `JOBS_EAGER == "1"`.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 27 findings: high 0, medium 3, low 11, false 8, maybe-false 0. Rejected lows are all either rare in everyday use or would need added complexity to fix; specific reasons below.
- findings:
  - `[low]` `[patch]` (blind) The leftover-rebuild test rebuilds the schema mid-session, and later files (test_nlp, test_share, ...) run on the result. Moved it to `tests/test_zz_schema_rebuild.py`, which is collected last.
  - `[medium]` `[patch]` (blind) The recovery test left only a table no migration touches, so it never hit "already exists". The test now drops `alembic_version`, replaces `users` with a model-style leftover, and asserts that the migrated `users.email` column exists.
  - `[low]` `[defer]` (blind) The migration seeds `open_access_mode=true` but `Settings` defaults to False, and the fixture overwrites the row silently. The overwrite is deliberate and commented: it is the gated baseline the suite ran on under create_all. The seed and settings mismatch is pre-existing, so it is deferred.
  - `[medium]` `[patch]` (blind) Server defaults are not compared. Kept autogenerate's default (off) and added a comment above `_diffs_against` that names the 12 known server-default diffs and why they are out of scope. They are also reported in the PR. Their fix is deferred, see below.
  - `[false]` `[reject]` (blind) The CLI autogenerate lacks `compare_type`. Alembic 1.13 defaults `compare_type=True`, so the CLI and the test compare the same way.
  - `[low]` `[reject]` (blind) `DROP SCHEMA public` needs ownership. The story names this teardown explicitly, and CI and lane DBs connect as the container superuser.
  - `[false]` `[reject]` (blind) The ENVIRONMENT/JOBS_EAGER lines are scope creep and overwrite env. The story's AC requires setting them, and forcing them is intended, so an exported ENVIRONMENT=development can't leak in.
  - `[low]` `[reject]` (blind) The env test mostly checks itself. Its `get_settings().environment` assertion is the meaningful part, and the consumers don't exist yet.
  - `[low]` `[reject]` (blind) Downgrade is untested. Migration-chain gates are E0-QA.6, and the story picks the DROP SCHEMA teardown.
  - `[low]` `[reject]` (blind) The `%` escape is checked only via a getter. `get_section` uses the same interpolation as `get_main_option`, so a further test adds nothing.
  - `[low]` `[reject]` (blind) The locked-URL test has no explicit assert. A connection error fails the test loudly, and the implementer confirmed that it fails when the lock is removed.
  - `[false]` `[reject]` (blind) The CI comment is stale. The fixture still runs CREATE EXTENSION, and the app engine still uses DATABASE_URL, so the comment is accurate.
  - `[medium]` `[patch]` (verification-gap) The `configure_logger` opt-out had no test. Added `test_migration_run_keeps_app_loggers`, which runs `command.current` and then asserts that the `app.main` logger is not disabled and the root handlers are unchanged.
  - `[low]` `[reject]` (edge) env.py copies `.env` into `os.environ` in-process. Settings already reads the same `.env` via `env_file`, so the effective values are the same. Only quoted values differ, and that is pre-existing CLI parsing.
  - `[low]` `[reject]` (edge) env.py doesn't strip quotes from `.env`. This is pre-existing CLI behaviour, not caused by this change.
  - `[low]` `[reject]` (edge) A CLI `DATABASE_URL` containing `%` breaks ConfigParser. This is pre-existing (the line is unchanged apart from the lock check), and the tests take the escaped path.
  - `[low]` `[reject]` (edge) DROP SCHEMA can block on locks held by other sessions. Each lane has its own DB, and adding a lock_timeout is extra machinery for a case no one has hit.
  - `[low]` `[reject]` (edge) `vector` might be installed in a non-public schema. No compose, CI or lane DB does that.
  - `[false]` `[reject]` (edge) The role is not the owner of public. This duplicates the blind ownership row; superuser in CI and on lanes.
  - `[false]` `[reject]` (edge) The app_config row could be missing after upgrade. Migration 4b8f2d9e71c3 always inserts it, and the recovery test asserts it.
  - `[low]` `[patch]` (edge) Ordering "keep last" held only within its file. Same fix as the first blind row.
  - `[false]` `[reject]` (edge) `modify_*` list diffs crash the column negative-control. That test builds metadata identical to Base apart from one column, and the main test only `repr`s diffs, so no list diff reaches the indexing.
  - `[false]` `[reject]` (edge) `_diff_key` crashes on an expression index. It reads `obj.columns`, which is an empty collection for an expression index, not an error.
  - `[low]` `[defer]` (intent) The seeded app_config value is replaced, so the suite does not run on production's seeded state. Same root cause as the blind app_config row.
  - `[low]` `[patch]` (intent) The 12 server-default diffs were recorded only in the spec. Same fix as the blind server-default row (code comment and PR body).
  - `[false]` `[reject]` (intent) The fakes switch is unverified at its consumers. The consumers don't exist yet, and the story says they activate "when they land".
  - `[low]` `[reject]` (intent) Tests exercise helpers, and teardown and the CLI path are untested. Teardown is the same `_reset_public_schema` that setup's recovery test exercises. The CLI path was checked by hand (`alembic upgrade head` via DATABASE_URL reports `a3e7c1f9d258 (head)`).

## Design Notes

The DB is reset at setup as well as at teardown. Desktop lane DBs still carry create_all tables with no `alembic_version`, so a bare upgrade would fail on the first `CREATE TABLE`. A bare `DROP SCHEMA` takes the `vector` extension with it, so setup recreates it. The guard already limits this to `_test` DBs.

The app_config seed is reset to `settings.open_access_mode` (env `OPEN_ACCESS_MODE`, default False). That reproduces exactly what `get_app_config`'s defensive create gave the suite under create_all, so test behaviour is unchanged.

## Verification

**Commands:**
- A throwaway local pgvector Postgres is already running on `localhost:55432` (user `lorekeeper`, trust auth, DB `lorekeeper_test`), with a venv that has the backend deps minus torch. From `src/backend`: `PYTHONPATH=/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/stubs TEST_DATABASE_URL=postgresql+asyncpg://lorekeeper@localhost:55432/lorekeeper_test DATABASE_URL=postgresql+asyncpg://lorekeeper@localhost:55432/lorekeeper_test POSTGRES_PASSWORD=x SECRET_KEY=x /private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/qa5venv/bin/python -m pytest -q -p no:cacheprovider -W ignore --ignore=tests/test_nlp.py` -- expected: 96 baseline tests plus the new ones pass. test_nlp needs the spaCy trf model, so it is skipped locally and covered by CI. The stubs dir fakes `sentence_transformers` and is never committed.
- `grep -n "create_all\|drop_all" src/backend/tests/conftest.py` -- expected: no output.
- CI `backend-tests.yml` on the draft PR -- expected: green, more than 99 passed.

## Auto Run Result

Status: done

**Summary:** The test schema is now built by `alembic upgrade head`. The session fixture runs the guard, drops and recreates `public`, creates `vector`, runs `command.upgrade` with a locked `sqlalchemy.url` equal to `TEST_DB_URL`, and resets the `app_config` seed to the settings default (gated, as the suite ran under create_all). Teardown drops and recreates `public`. `create_all`/`drop_all` are gone. `env.py` imports the whole models package, honours a locked URL, and skips `fileConfig` for programmatic runs. `conftest.py` sets `ENVIRONMENT=test` and `JOBS_EAGER=1` before importing `app.main`.

**Files changed:**
- `src/backend/app/db/models/__init__.py`: `AppConfig` is imported with the other models and listed in `__all__`.
- `src/backend/migrations/env.py`: imports the whole package, adds the `sqlalchemy_url_locked` and `configure_logger` attributes, and leaves the CLI path unchanged.
- `src/backend/tests/conftest.py`: adds the env vars, `alembic_config()`, `build_test_schema()` and `drop_test_schema()`; the fixture is rewritten.
- `src/backend/tests/test_migrations_match_models.py` (new, 8 tests): the drift check with a commented ignore list, a check that the DB is at head, two negative controls (an extra table and an extra column are detected), `%` escaping and the lock, locked URL beating `DATABASE_URL`, the env vars, and logger preservation.
- `src/backend/tests/test_zz_schema_rebuild.py` (new, 1 test): recovery from a leftover create_all schema; it is collected last.

**Review:** 27 findings: 0 high, 3 medium, 11 low, 8 false.
- Patched 3 medium and 2 low entries: the recovery test now really collides with migrated tables, the rebuild test moved to a last-collected file, a logger-preservation test was added, and the server-default exclusion is documented.
- Deferred 3 low items (see frontmatter): the redundant unique constraints, the 12 server-default diffs, and the app_config seed vs settings mismatch.
- Rejected the rest; each reason is in the triage log.

Follow-up review recommended: false. Two medium entries were patched, which meets the rule's threshold, but there is no specific unverified risk left to name: CI and local runs check both patches, and the logger test was shown to fail with the env.py guard removed.

**Verification:**
- Local throwaway Postgres 16 with pgvector 0.6.2, running everything except test_nlp: 105 passed (96 baseline + 9 new).
- CI on draft PR #21 (pgvector/pgvector:pg16, the pre-patch commit): 115 passed.
- The comparison without the ignore list reports exactly the two `remove_constraint` diffs.
- The CLI `alembic upgrade head` via `DATABASE_URL` reaches `a3e7c1f9d258 (head)`.
- Deleting env.py's `configure_logger` clause makes `test_migration_run_keeps_app_loggers` fail.
- `grep create_all|drop_all tests/conftest.py` finds nothing.

**Residual risks:**
- The DROP SCHEMA reset needs a role that owns `public` (true for the CI and lane superusers).
- The `%`-in-password escaping is tested only at the config level, not against a real password login.
- Sprint-status sync was skipped by orchestrator rule.

**Needs desktop verification:** run the suite on a lane DB that still holds create_all tables from an older run. Use the brief's docker command with `-e TEST_DATABASE_URL=...lorekeeper_test_<lane>` and the same value for `DATABASE_URL`. Expected: all pass, and `psql -d lorekeeper_test_<lane> -c 'select * from alembic_version'` shows that the DB was rebuilt.
