---
title: 'E0-Jobs.8: File service, access-checked file route and backups'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '4548731b8a7ea88d17d89ccc5b0e3b1f68711586'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Nothing stores derived binaries (recap audio, Chronicles, Map tiles) or serves them through an access check, so a Player could fetch a GM-only or stale file by guessing a URL, and the backup plan covers only Postgres.

**Approach:** `app/services/file_service.py` owns the `files_data` volume (`put`, `put_tree`, `open`, `read_bytes`, `delete`, `accel_response`, the `files.gc` cursor Job and its stale marker). `app/access/files.py` holds every `stored_files`/`derived_sources` read: the loader of ALL of a file's source rows and the double (SQL + Python) visibility check. `GET /api/files/{file_id}` answers with `X-Accel-Redirect`; nginx serves bytes only from an `internal` location. Backups cover `files_data`.

## Boundaries & Constraints

**Always:**
- Hidden, missing, other-Campaign, malformed id, stale-for-non-GM and bytes-missing all give the one `404 {"detail":"Not found"}` with identical headers (`Vary: Authorization, X-Lorekeeper-Preview` from the middleware).
- A file is served only when `scoped_get` (SQL) AND `audience_of(file, parents=<all source rows>)` (Python) both allow it; a mismatch is a 404 and a `file_visibility_mismatch` warning.
- Success: empty body, `X-Accel-Redirect: /_files/<storage_key>[/<subpath>]`, `Content-Type` from the row (or the manifest extension for a tree), `Cache-Control: private, no-cache`, `ETag: "<sha256[:32]>-e<access_epoch>"`, `X-Content-Type-Options: nosniff`, `Content-Disposition` (`inline` only for audio, raster images, PDF and plain text; else `attachment`), `Content-Security-Policy: default-src 'none'; sandbox`. `If-None-Match` equal to the ETag gives 304 with no accel header.
- `put`/`put_tree` refuse HTML, SVG, XML, XHTML and JS content types (ValueError); `accel_response` serves any such row as `application/octet-stream` + `attachment` anyway.
- Storage keys are generated (`{campaign_id}/{kind}/{uuid4}`); every key and subpath is validated (regex segments, no `..`, no absolute, no backslash/NUL, realpath stays under `files_root`) before any filesystem or header use.
- `delete` removes the file's `derived_sources` rows and the row in the caller's transaction; bytes are unlinked after the root commit (put bytes are unlinked on rollback).
- The stale marker is registered with `register_stale_marker`: any Visibility change of a source marks every non-stale file deriving from it stale, in the same transaction.

**Never:** no migration, no new dependency, no change to `app/access/visibility.py`, `registry.py` semantics or `app/access/__init__.py`, no widening of CI-8 `OWNER_INFRA` or the scoped-query baseline, no frontend, no feature `DERIVED_REGISTRY` entries (owning epics add them), no tile route (E10).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM fetch | GM, fresh or stale file | 200 empty, accel + safe headers | — |
| Player visible | Party sources, not stale | 200 accel | — |
| Player hidden | any GM-only source / gm_field ref / unknown ref kind / no sources | same as missing | uniform 404 |
| Stale | Player, file marked stale by a downgrade | same as missing | uniform 404 |
| Preview | GM + `X-Lorekeeper-Preview: member`, GM-only file | same as missing | uniform 404 |
| Tree subpath | `../x`, `/etc`, `a\\b`, not in manifest, `.manifest.json` | — | uniform 404 |
| Direct nginx | `GET /_files/<key>` | `location /_files/` is `internal` (nginx 404); app has no `/_files` route | 404 |
| Cache key reuse | put with a fresh file's cache_key | old one stale (superseded), new one fresh | — |

</intent-contract>

## Code Map

- `src/backend/app/db/models/stored_file.py` -- `StoredFile`, `DerivedSource` (read-only; columns fixed by E0-Jobs.1).
- `src/backend/app/access/registry.py:524-608` -- `_sources_clause` / `_sources_audience`: SQL and Python twins; `audience_of(file, parents=[(ds,row)])` requires every pair; `SOURCE_KIND_MODELS` maps ref_kind -> model.
- `src/backend/app/access/visibility.py:160` -- `register_stale_marker(fn(db, ref))`; refs are `RecordRef` (kind is a Visibility kind, e.g. `player_journal`, which may differ from the stored `ref_kind`), so match on `ref_id`.
- `src/backend/app/access/visibility.py:410-440` -- session event pattern (`after_soft_rollback`, `after_commit`, `_within`) to copy for byte cleanup.
- `src/backend/app/access/context.py` -- `require_campaign_for(StoredFile, "file_id", "player")` (preview narrowing included), `ctx.access_epoch`.
- `src/backend/app/access/owners.py` -- `campaign_owners` for the deleted-Campaign directory sweep.
- `src/backend/app/jobs/backfill.py` -- `run_cursor`, `CursorStep`; `app/jobs/registry.py` -- `register(JobKind(...))`, built-ins live here.
- `src/backend/app/jobs/worker.py:828` -- `Reaper._reap`: add the daily `files.gc` scheduling after the backfill runner.
- `scripts/check_scoped_queries.py` -- CI-8: `select(StoredFile|DerivedSource)` / `db.get` outside `app/access/` fails; `update`/`delete` statements are not flagged.
- `src/backend/tests/ev4/` -- `ev4_probe`, `assert_hidden_equals_missing`, `DowngradeCase`, `nginx.https_locations().resolve()`; probes go in `tests/ev4/probes/files.py`.
- `src/backend/tests/access/test_registry_property.py:176` -- `file_types` fixture pattern for test-only derived types.
- `nginx/locations.conf`, `docker-compose.yml`, `docker-compose.prod.yml`, `src/backend/Dockerfile.prod`, `scripts/backup-db.sh`, `scripts/restore-db.sh`, `docs/DATABASE_BACKUPS.md`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/config.py` -- `files_root: str = "/data/files"` -- volume root setting.
- `src/backend/app/access/files.py` -- new: `file_sources` (ALL rows, ordered, each with its source row or None), `file_audience`, `visible_file(db, ctx, file_id)` (SQL + Python), `files_derived_from(db, ref_id)`, `campaign_files(db, ctx)` (GM ctx only) -- the access side.
- `src/backend/app/services/file_service.py` -- new: `put`, `put_tree`, `open`, `read_bytes`, `delete`, `accel_response`, `not_modified`, gc helpers (`gc_candidates`, `gc_one`), stale marker, session byte hooks -- the volume owner.
- `src/backend/app/jobs/files_gc.py` -- new: `files.gc` handler on `run_cursor`, `schedule_daily(factory, redis)` (Valkey `SET NX` per UTC day, one Job per Campaign with a directory, key `files.gc:{cid}`); `app/jobs/registry.py` registers `files.gc` (backfill queue, no resources, live_safe); `worker.py` calls `schedule_daily` in `_reap`.
- `src/backend/app/api/routes/files.py` + `app/main.py` -- `GET /api/files/{file_id}` under the `gate`.
- `nginx/locations.conf` -- `location /_files/ { internal; alias /data/files/; ... }` re-adding ETag/Vary from upstream and the security headers, `etag off`, `if_modified_since off`.
- `docker-compose.yml`, `docker-compose.prod.yml`, `Dockerfile.prod` -- `files_data` rw in backend/worker, ro in nginx; `/data/files` owned by appuser.
- `scripts/backup-db.sh`, `scripts/restore-db.sh`, `docs/DATABASE_BACKUPS.md` -- files archive after the dump, `live_audio` kind excluded unless the Campaign directory holds the `.backup-live-audio` opt-in marker; restore both.
- `src/backend/tests/conftest.py` -- `FILES_ROOT` temp dir for the session.
- `src/backend/tests/test_file_service.py` -- matrix + put/put_tree/delete/gc/stale marker/loader/headers.
- `src/backend/tests/ev4/probes/files.py` -- EV-4 probes for `GET /api/files/{file_id}` (hidden vs missing, stale for Players, preview, downgrade, `/_files/` direct path).

**Acceptance Criteria:**
- Given a stored file with N source rows, when `file_sources` runs, then it returns all N pairs (no visibility filter, no limit), and a source row the SQL rejects makes `visible_file` 404 for that viewer.
- Given a Party-sourced file a Player can fetch, when the GM downgrades that source through `set_visibility`, then the file is stale in the same transaction and the Player's fetch equals a missing id; the GM still gets 200.
- Given `delete(db, ctx, file)` then commit, then the row, its `derived_sources` rows and the bytes (tree recursively) are gone.
- Given `put_tree`, then the tree appears only by rename, one row has `size` = total and `sha256` = hash of the manifest file, and `accel_response(row, "z/0/0.jpg")` gives `/_files/<key>/z/0/0.jpg`.
- Given a superseded file, a row-less entry older than the grace period, and a deleted Campaign's directory, when `files.gc` runs for the Campaign, then all three are removed and a fresh file is untouched.

## Spec Change Log

## Review Triage Log

## Design Notes

- CI-8 forbids `select(StoredFile)`/`select(DerivedSource)` outside `app/access/`, so reads live in `app/access/files.py`; `file_service` writes with `insert`/`update`/`delete` and the ORM, and enumerates rows through `scoped_select` with the Owner ctx.
- Manifest: `.manifest.json` inside the tree, bytes = `json.dumps({"files": [[path, size, sha256], ...]}, sort_keys, separators=(",",":"))`; row `sha256` = sha256 of those bytes, re-checked on read (cached by key+sha). Names starting with `.` are rejected in a tree, so the manifest is never servable.
- nginx drops ETag/Vary/X-Content-Type-Options from an X-Accel response and a location `add_header` disables server-level ones, so the location re-adds them from `$upstream_http_*` and literals.
- Backup order: `pg_dump` first, then the files tar: every row in the dump existed before the tar started, so only files deleted in between can be missing (they 404 for everyone); stray bytes are swept by `files.gc`.

## Verification

**Commands:**
- `cd src/backend && python -m pytest tests/test_file_service.py tests/ev4 tests/access -q` -- expected: pass (CI, real Postgres).
- `python scripts/check_scoped_queries.py` and `lint-imports` -- expected: clean.
- `docker compose -f docker-compose.prod.yml config -q` -- expected: valid.
