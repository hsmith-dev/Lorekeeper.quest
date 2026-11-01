---
title: 'E0-QA.5 (2.5): Tests build the schema from Alembic migrations'
type: 'chore'
created: '2026-10-31'
status: 'in-review'
baseline_revision: 'fc1806a9a15f2da98765b946e20d733d46fb2114'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
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

## Design Notes

The DB is reset at setup as well as at teardown. Desktop lane DBs still carry create_all tables with no `alembic_version`, so a bare upgrade would fail on the first `CREATE TABLE`. A bare `DROP SCHEMA` takes the `vector` extension with it, so setup recreates it. The guard already limits this to `_test` DBs.

The app_config seed is reset to `settings.open_access_mode` (env `OPEN_ACCESS_MODE`, default False). That reproduces exactly what `get_app_config`'s defensive create gave the suite under create_all, so test behaviour is unchanged.

## Verification

**Commands:**
- A throwaway local pgvector Postgres is already running on `localhost:55432` (user `lorekeeper`, trust auth, DB `lorekeeper_test`), with a venv that has the backend deps minus torch. From `src/backend`: `PYTHONPATH=/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/stubs TEST_DATABASE_URL=postgresql+asyncpg://lorekeeper@localhost:55432/lorekeeper_test DATABASE_URL=postgresql+asyncpg://lorekeeper@localhost:55432/lorekeeper_test POSTGRES_PASSWORD=x SECRET_KEY=x /private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/qa5venv/bin/python -m pytest -q -p no:cacheprovider -W ignore --ignore=tests/test_nlp.py` -- expected: 96 baseline tests plus the new ones pass. test_nlp needs the spaCy trf model, so it is skipped locally and covered by CI. The stubs dir fakes `sentence_transformers` and is never committed.
- `grep -n "create_all\|drop_all" src/backend/tests/conftest.py` -- expected: no output.
- CI `backend-tests.yml` on the draft PR -- expected: green, more than 99 passed.
