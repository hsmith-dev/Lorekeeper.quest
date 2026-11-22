---
title: 'E0-Platform.9: Multi-arch images, upgrade-safe boot and OCI deploy'
type: 'feature'
created: '2026-11-21'
status: 'in-review'
baseline_revision: '9b0f01a437d70660905892cede406e07943553c9'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/OCI_DEPLOYMENT.md'
  - '{project-root}/docs/UPGRADING.md'
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** The prod `web` service runs `alembic upgrade head` on boot with no backup, so a bad migration on a v1.1 install cannot be rolled back. Nothing builds the images for `linux/arm64`, and `deploy-oci.sh` knows nothing about editions, image tags or rollback.

**Approach:** Add a `docker-bake.hcl` with `web`, `ml`, `stt` (cpu) and `nginx` targets, and a new `images.yml` workflow that builds them for amd64 and arm64 on every PR and on `main`. The `web` command becomes a boot step, `scripts/boot_migrate.py`, that runs before gunicorn. It takes a Postgres advisory lock. When a migration is pending and the database is not empty, it runs `pg_dump -Fc` to the `backups` volume as `pre-upgrade_<UTC stamp>_<revision>.dump`, then runs `alembic upgrade head`. If the dump fails, it exits non-zero and does not migrate. `deploy-oci.sh` builds tagged images from source, pulls the upstream multi-arch images, applies the edition rule for `COMPOSE_PROFILES`, and keeps the model import. `restore-db.sh` and `docs/OCI_DEPLOYMENT.md` give the rollback path.

## Boundaries & Constraints

**Always:**
- Distribution is source only (owner decision, scope-input.md). Never push an image to any registry, and never log in to one. "Pulls the multi-arch tags" means `docker compose pull --ignore-buildable` for the upstream images (postgres, valkey, ollama). Lorekeeper's own images are built on the host with bake.
- The advisory lock makes a second web replica wait. Once it gets the lock it finds the schema at head and skips both the dump and the migration.
- Log lines are plain and prefixed `boot-migrate:`. The password is never put in argv or in a log line: pg_dump gets it through `PGPASSWORD`.
- Every new apt package in the backend image gets an entry in `licenses/register.yaml`. The backend image scan in `license-check.yml` keeps covering the image.
- The ops scripts call compose services only by their real names (`web`; the `test_ops_scripts_name_real_prod_services` regex). Don't use `--entrypoint`.

**Never:**
- Don't edit E0-QA's workflows (`backend-tests.yml`, `gates.yml`, `license-check.yml`), `epics.md`, sprint-status, the dev compose service names, or the `worker` start order (E0-Jobs owns that).
- Don't add a `tts` service (that is E5's).
- Don't add a migrate-at-import path in `migrations/env.py`.

## I/O & Edge-Case Matrix

| Scenario | State | Behaviour | Exit |
|---|---|---|---|
| Upgrade (v1.1 data) | DB at an older known revision | Writes the dump `pre-upgrade_<stamp>_<rev>.dump` (written as `.partial`, renamed only when it is non-empty), then upgrades to head and prunes old dumps beyond `PRE_UPGRADE_BACKUPS_KEEP` (default 5) | 0 |
| Already at head | current == heads | Logs "at head"; no dump, no alembic | 0 |
| Fresh install | no user tables | Logs "empty database, nothing to back up"; upgrades | 0 |
| Dump fails | pg_dump missing, rc≠0, empty output, or backup dir not writable | Removes the partial file; logs `boot-migrate: pre-upgrade backup failed (...); not migrating`; alembic is never run | 1 |
| Unknown revision | DB rev not in this image's scripts | Readable line naming the rev and pointing at the rollback doc; no dump | 1 |
| Migration fails | alembic rc≠0 | Logs which dump to restore | 1 |
| Two web boots at once | both see a pending migration | Exactly one dump and one upgrade; both exit 0 | 0 |
| Commercial + tts | `LOREKEEPER_EDITION=commercial`, `COMPOSE_PROFILES` contains `tts` | deploy-oci.sh refuses, logs AD-16 reason | 1 |
| AGPL | edition agpl/unset | deploy adds `tts` to `COMPOSE_PROFILES` | — |

</intent-contract>

## Code Map

- `docker-compose.prod.yml` -- `web.command` (one-line `sh -c`, currently `python -m alembic upgrade head && gunicorn …`). Replace the alembic part with `python scripts/boot_migrate.py && exec gunicorn …`. Add a `backups` volume at `/backups` on web. Add `image: lorekeeper-<svc>:${LOREKEEPER_TAG:-latest}` to web/worker (one shared image), ml, stt and nginx. ml and stt keep their names, so `sidecar_smoke.sh` defaults still match `:latest`.
- `src/backend/Dockerfile.prod` -- trixie base (python:3.11-slim; register versions are `deb13`). Add apt `postgresql-client` (pg_dump/pg_restore 17, which can read a pg16 server). Run `mkdir /backups` and `chown appuser`, like `/var/log/lorekeeper`.
- `src/backend/scripts/boot_migrate.py` (new) -- asyncpg connection (the URL is DATABASE_URL with `+asyncpg` stripped, via `sqlalchemy.engine.make_url`). Take `pg_advisory_lock(hashtext('lorekeeper.boot_migrate'))`. Read `alembic_version` when `to_regclass` finds it. Get heads from `alembic.script.ScriptDirectory` (`alembic.ini` sits next to `scripts/`). pg_dump and alembic run as subprocesses. Second subcommand `restore` resets the `public` schema and pipes stdin to `pg_restore --no-owner --exit-on-error --single-transaction`. Tests import it as `scripts.boot_migrate`, the way `test_eval_common` does.
- `migrations/env.py` -- read-only. It runs every pending migration in one transaction.
- `app/jobs/backfill.py:run_backfills` -- read-only. Backfills run in the worker with `FOR UPDATE SKIP LOCKED`, so they are already safe with several runners. No boot change is needed.
- `scripts/restore-db.sh` -- today it runs `pg_restore --clean` in the postgres container (pg16 client, which can't read a pg17-made archive, and `--clean` leaves newer tables behind). Change it to: resolve a `pre-upgrade_*` name from the `backups` volume; restore through `docker compose … run --rm --no-deps -T web python scripts/boot_migrate.py restore`; add `--no-restart` for rollback.
- `scripts/deploy-oci.sh` -- steps 4–6. Add: edition/profile check; `TAG` (`LOREKEEPER_TAG`, else `git describe`, else `latest`); `docker buildx bake --load` (falls back to `compose build`); `pull --ignore-buildable`; `up -d --no-build --remove-orphans`. The model import stays as it is.
- `docker-bake.hcl` (new); `.github/workflows/images.yml` (new) -- arm64 on the native runner `ubuntu-24.04-arm` (the repo is public), amd64 on `ubuntu-latest`. A third job runs `bake --print` with the combined `--set *.platform=linux/amd64,linux/arm64` to prove that all four targets resolve with both platforms.
- `nginx/Dockerfile` -- builder stage `--platform=$BUILDPLATFORM`. The static bundle is arch-independent, so arm64 doesn't build node under emulation.
- `src/backend/tests/test_compose_sidecars.py` -- add asserts for the boot command, the backups volume and image tags. `src/backend/tests/test_boot_migrate.py` (new).
- `licenses/register.yaml` -- `postgresql-client*` plus closure; add `backend` to the existing krb5/ldap/sasl/libpq rows. `.github/license-policy.toml` is not edited: `os_aggregate_allowlist` already has libpq5/ldap/sasl/krb5/perl. The client itself is PostgreSQL-licensed.
- `docs/OCI_DEPLOYMENT.md`, `docs/UPGRADING.md`, `docs/DATABASE_BACKUPS.md`, `.env.example` -- boot dump, rollback, `LOREKEEPER_EDITION`/`LOREKEEPER_TAG`/`PRE_UPGRADE_BACKUPS_KEEP`.

## Tasks & Acceptance

**Execution:**
- `src/backend/scripts/boot_migrate.py` -- boot and restore as described above -- AC 2.
- `src/backend/Dockerfile.prod`, `docker-compose.prod.yml` -- client, volume, command, tags -- AC 2.
- `docker-bake.hcl`, `.github/workflows/images.yml`, `nginx/Dockerfile` -- AC 1.
- `scripts/deploy-oci.sh`, `scripts/restore-db.sh`, docs, `.env.example` -- AC 3, 4.
- `src/backend/tests/test_boot_migrate.py` -- unit tests for each matrix row (fake pg_dump paths). Integration test on the real test DB: restore the a3e7c1f9d258 snapshot, run boot with real `pg_dump` (skip if absent), check the dump name, that the DB is at head, and that the dump restores to the old revision; then a failing pg_dump leaves the revision unchanged; then two concurrent boots make one dump. In teardown, rebuild the session schema (`build_test_schema`).
- `src/backend/tests/test_compose_sidecars.py`, a deploy-script test -- compose wiring, deploy edition rule (run the edition function in bash with a stubbed docker).
- `licenses/register.yaml` -- entries from the CI scan's `--emit-missing`.

**Acceptance Criteria:**
- Given `docker-bake.hcl`, when `docker buildx bake --set *.platform=linux/amd64,linux/arm64` runs, then `web`, `ml`, `stt` (cpu target, never `gpu`) and `nginx` build for both platforms, and `images.yml` runs on every PR and on `main` with no path filter.
- Given a web container booting a newer image against a DB at an older revision, then a `pre-upgrade_<stamp>_<rev>.dump` exists in `/backups` before `alembic upgrade head` runs. When the dump fails, the revision is unchanged and the container exits non-zero with a `boot-migrate:` line.
- Given `deploy-oci.sh` on the arm64 OCI host, then it builds native images from source, pulls the upstream multi-arch images, uses only `docker-compose.prod.yml` and `.env`, runs the Ollama model import, and pushes nothing. `docs/OCI_DEPLOYMENT.md` documents rollback: `restore-db.sh --no-restart <pre-upgrade dump>`, then redeploy the previous tag.
- Given `LOREKEEPER_EDITION=commercial`, then the deploy script never sets `COMPOSE_PROFILES=tts`, and refuses with an AD-16 log line when one is requested.

## Spec Change Log

## Review Triage Log

## Design Notes

pg_dump 17 (trixie) writes archive format 1.16, which the pg16 postgres container's `pg_restore` can't read. So both the dump and the restore use the web image's client, and the target server stays 16. Restore resets `public` instead of using `--clean`, because `--clean` can't drop the tables a newer migration added (they have FKs into old tables). The dump is the safety net, so it is made under the same lock that guards the migration. Otherwise a second replica could migrate between the first replica's dump and its upgrade.

## Verification

**Commands:**
- `cd src/backend && python -m pytest -q tests/test_boot_migrate.py tests/test_compose_sidecars.py` -- expected: pass (the DB tests run in CI)
- `python3 scripts/check_memory_budget.py` -- expected: OK, 14.50 GiB
- `bash -n scripts/deploy-oci.sh scripts/restore-db.sh` -- expected: ok
- GitHub CI: `images.yml` green on both arches; `license-check.yml` backend image scan green.
