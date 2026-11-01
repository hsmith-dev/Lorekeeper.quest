---
title: 'E0-QA.4 (2.4): The test database URL can be overridden from the environment'
type: 'chore'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred:
  - summary: >-
      The app's own engine (AsyncSessionLocal) still connects through DATABASE_URL, not TEST_DATABASE_URL, so the account gate and /api/health can read a different DB than the test schema when the two differ.
    evidence: |-
      app/db/session.py builds the engine from settings.database_url; app/api/deps.py:62 and app/main.py:92 open AsyncSessionLocal directly, bypassing the get_db override. This was already true before this story (the hardcoded test URL was independent of DATABASE_URL). This story documents "set DATABASE_URL to the same URL" in the README and CI sets both. A code fix (conftest forcing DATABASE_URL = TEST_DB_URL before importing app, or overriding the session factory) touches DATABASE_URL handling, which this spec excludes.
    location: >-
      src/backend/tests/conftest.py (imports app.main before any override); src/backend/app/db/session.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** `src/backend/tests/conftest.py` hardcodes `TEST_DB_URL` to `localhost:5432/lorekeeper_test`, so running the suite against the remote desktop Postgres, or one database per parallel worktree, means editing the file (today: a `sed` workaround). Nothing stops a mistyped URL from having its tables dropped by `setup_test_db`.

**Approach:** Read `TEST_DATABASE_URL` from the environment with the current URL as the default, and keep the module-level `TEST_DB_URL` name. Add a guard that refuses to run unless the database name is a test database. Set the variable explicitly in CI and document it in the README.

## Boundaries & Constraints

**Always:** Default stays exactly `postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test`. All fixtures (`setup_test_db`, `db`, `client` through `db`) use the one resolved URL. The guard runs before any engine is created or anything is dropped. Accepted DB names: ending in `_test`, or `_test_<lane>` where lane is `[A-Za-z0-9]+` (so `lorekeeper_test_e0qa4` passes; `lorekeeper` and `lorekeeper_testing` fail).

**Never:** No Alembic/schema changes (that is E0-QA.5). No path-filter changes in CI (E0-QA.6). Don't touch app code or `DATABASE_URL` handling.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Unset | no `TEST_DATABASE_URL` | default localhost `lorekeeper_test` URL used | none |
| Empty string | `TEST_DATABASE_URL=""` | treated as unset, default used | none |
| Lane DB | `.../lorekeeper_test_e0qa4` | suite runs on that DB | none |
| Non-test DB | `.../lorekeeper` or `.../lorekeeper_testing` | session aborts before connecting | `pytest.exit` with message naming the DB and the rule, returncode != 0 |
| No DB name | `postgresql+asyncpg://u:p@h:5432` | aborts | same |

</intent-contract>

## Code Map

- `src/backend/tests/conftest.py` -- `TEST_DB_URL` constant (line 13), used by `setup_test_db` (session, autouse, drops/creates all tables), `db`; `client` depends on `db`.
- `.github/workflows/backend-tests.yml` -- postgres service comment says values "must match tests/conftest.py's hardcoded TEST_DB_URL"; `Run tests` step env has `DATABASE_URL` only.
- `README.md` -- no "Running tests" section yet; add one before `## License`.
- Parallel plan: `_bmad-output/planning-artifacts/epics-parallel-plan.md` §4.3 "One machine" bullet -- one test DB per worktree, `lorekeeper_test_<lane>`.

## Tasks & Acceptance

**Execution:**
- `src/backend/tests/conftest.py` -- add `DEFAULT_TEST_DB_URL`, `TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or DEFAULT_TEST_DB_URL`, a pure `is_test_database_name(name)` helper, and a guard (via `sqlalchemy.engine.make_url`) called first in `setup_test_db` that `pytest.exit`s on failure -- env override plus wipe protection.
- `src/backend/tests/test_conftest_guard.py` -- unit-test the name helper over the matrix rows -- guard regressions are silent otherwise.
- `.github/workflows/backend-tests.yml` -- set `TEST_DATABASE_URL` in the `Run tests` env; rewrite the service comment to say the values match that variable, removing the "hardcoded" claim -- CI explicit.
- `README.md` -- add "Running tests" section: default, the variable, the `_test` guard, per-lane `lorekeeper_test_<lane>`, Tailscale example -- AC 3.

**Acceptance Criteria:**
- Given `TEST_DATABASE_URL` points at `lorekeeper_test_e0qa4` on the desktop, when the suite runs without editing `conftest.py`, then all tests pass and the tables are created in that DB.
- Given the variable is unset, when `TEST_DB_URL` is imported, then it equals the localhost default CI uses.
- Given a non-test DB name, when the session starts, then pytest exits with a clear message and no tables are dropped.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 22 findings — high 0, medium 4, low 16, false 2, maybe-false 0
- findings:
  - `[medium]` `[patch]` (verification-gap) Guard and env override only tested as helpers; deleting the guard call in `setup_test_db` or hardcoding `TEST_DB_URL` would pass every test — added subprocess tests: full pytest run with `TEST_DATABASE_URL=.../lorekeeper` must exit non-zero with the guard message; `import tests.conftest` must print the env URL.
  - `[medium]` `[defer]` (blind) App engine still uses `DATABASE_URL`, so gate/health paths can read another DB — pre-existing (hardcoded URL was always independent of it); README now says set both; code fix deferred (spec excludes DATABASE_URL handling).
  - `[low]` `[patch]` (blind) CI comment names only TEST_DATABASE_URL though DATABASE_URL must match too — comment now names both. YAML anchor suggestion not taken (adds indirection).
  - `[medium]` `[patch]` (blind) Parse-failure message interpolated SQLAlchemy's ArgumentError, which echoes the URL with password — exception text dropped.
  - `[low]` `[patch]` (blind) Parse-failure branch untested — added `"not a url"` test asserting exit code 1 and that the input is not echoed.
  - `[low]` `[patch]` (blind) No end-to-end "nothing dropped" proof — same fix as the verification-gap row (subprocess test).
  - `[low]` `[reject]` (blind) Pure guard unit tests still need a live Postgres via autouse `setup_test_db` — the whole suite already requires one; moving helpers to a new module adds structure for no everyday benefit.
  - `[low]` `[patch]` (blind) README lacks required env vars, dependency install and spaCy model — added.
  - `[low]` `[patch]` (blind) README does not say where/as whom to run CREATE DATABASE or that `vector` must be available — added one sentence.
  - `[low]` `[patch]` (blind) README overstates the guard — added "checks only the database name, not host or credentials".
  - `[low]` `[patch]` (blind) E302 blank lines and untyped `environ` — fixed, annotated `Mapping[str, str]`.
  - `[medium]` `[defer]` (edge) TEST_DATABASE_URL set while DATABASE_URL differs → gate/health on another DB — same root cause as the deferred blind row.
  - `[low]` `[reject]` (edge) Sync driver URL passes guard then create_async_engine errors — SQLAlchemy's error ("asyncio extension requires an async driver") is already explicit; adding a dialect check is extra branching for a rare mistake.
  - `[low]` `[reject]` (edge) Guard tests need a DB — duplicate of the rejected blind row, same reason.
  - `[low]` `[patch]` (edge) CI comment should name both URLs — same fix as blind CI-comment row.
  - `[low]` `[defer]` (edge, claim) Lane runs with mismatched DATABASE_URL hit wrong DB — same root cause as deferred row.
  - `[low]` `[patch]` (edge, claim) README Tailscale example omitted DATABASE_URL — example now sets TEST_DATABASE_URL, DATABASE_URL, POSTGRES_PASSWORD, SECRET_KEY.
  - `[low]` `[patch]` (intent) Tests exercise helpers, not the fixture surface — covered by the subprocess tests above.
  - `[low]` `[reject]` (intent) CI exercises only the default URL — by design: CI's service is the default; the non-default path is now covered by the subprocess tests and the remote lane run.
  - `[low]` `[reject]` (intent) Lane restricted to alphanumerics — documented in README and guard message; lanes in use (`e0qa4`) fit; widening weakens the guard for no current need.
  - `[false]` `[reject]` (intent) CI comment replaced rather than removed — the AC targets the comment claiming a hardcoded URL; that claim is gone and the replacement is accurate.
  - `[false]` `[reject]` (intent) `or` instead of `os.environ.get(..., default)` — the spec's I/O matrix requires empty-as-unset; behaviour matches the default otherwise.

## Design Notes

The story text says "does not end in `_test`", but the same story mandates `lorekeeper_test_<lane>` lane DBs, which a strict suffix check would reject. The guard therefore accepts `_test` as the last name segment or followed by one alphanumeric lane segment. It still rejects the dev/prod `lorekeeper` DB and near-misses like `lorekeeper_testing`. `pytest.exit` (not an assertion) is used so the run stops once with a readable message, not as one error per test.

## Verification

**Commands:**
- remote docker pytest with only `-e TEST_DATABASE_URL=...lorekeeper_test_e0qa4` (no `sed`) -- expected: 26 baseline + new guard tests pass; `psql` shows tables in `lorekeeper_test_e0qa4` during the run.
- `python -c "import tests.conftest as c; print(c.TEST_DB_URL)"` with the var unset -- expected: the localhost default.
- run with `TEST_DATABASE_URL=.../lorekeeper` -- expected: non-zero exit, guard message, nothing dropped.
- YAML parse of `backend-tests.yml` -- expected: valid.

## Auto Run Result

Status: done

**Summary:** `tests/conftest.py` resolves `TEST_DB_URL` from `TEST_DATABASE_URL` (unset or empty → the localhost `lorekeeper_test` default) and aborts the session with `pytest.exit` before connecting unless the DB name ends in `_test` or `_test_<alphanumeric lane>`. CI sets the variable explicitly, and the README gains a "Running tests" section.

**Files changed:**
- `src/backend/tests/conftest.py` -- env override, `resolve_test_db_url`, `is_test_database_name`, `_guard_test_database` (first call in `setup_test_db`).
- `src/backend/tests/test_conftest_guard.py` -- new: 24 tests (name rules, env fallback, guard exits, two subprocess tests for the real fixture chain and the import-time constant).
- `.github/workflows/backend-tests.yml` -- `TEST_DATABASE_URL` in "Run tests"; the "hardcoded" comment replaced with one naming both URLs.
- `README.md` -- "Running tests" section (default, variable, DATABASE_URL note, guard, per-lane DBs, Tailscale example).

**Review:** 22 findings. Patched 13 rows (entries: 2 medium, the rest low): end-to-end guard/env tests, password-safe parse error, parse-failure test, CI comment, README prerequisites/DATABASE_URL/guard scope, lint. Deferred 1 entry (3 rows): app engine still uses DATABASE_URL (pre-existing; documented). Rejected 6 with reasons in the triage log. Follow-up review recommended: true (two medium entries patched; the specific unverified risk is that the subprocess tests had only run on the remote desktop, not in GitHub CI).

**Verification:**
- Remote desktop, `lorekeeper-backend-test` image, no `sed`, `-e TEST_DATABASE_URL=...@100.119.62.5:5432/lorekeeper_test_e0qa4` and `DATABASE_URL` left at the CI localhost default: 50 passed (26 baseline + 24 new). `pg_stat_database` delta during the run: `lorekeeper_test_e0qa4` +81 commits, +1804 rows inserted; `lorekeeper_test` unchanged.
- Variable unset and empty: `TEST_DB_URL` = `postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test`.
- `TEST_DATABASE_URL=.../lorekeeper_nottest_probe`: "no tests ran", guard message, exit 1.
- `actionlint .github/workflows/backend-tests.yml`: clean.

**Residual risks:** the deferred DATABASE_URL item. The guard checks only the DB name. `epic-2-context.md` was compiled for planning but not committed, to avoid clashes with parallel Epic 2 lanes.
