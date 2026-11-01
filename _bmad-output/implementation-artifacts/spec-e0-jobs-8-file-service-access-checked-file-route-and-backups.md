---
title: 'E0-Jobs.8: File service, access-checked file route and backups'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '4548731b8a7ea88d17d89ccc5b0e3b1f68711586'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      Two concurrent puts with the same cache_key may give the second writer an IntegrityError.
    evidence: |-
      The supersede UPDATE cannot see the other transaction's uncommitted fresh row, and uq_stored_files_cache_key_fresh then fails one insert. Settle with a two-session concurrency test on Postgres.
    location: >-
      src/backend/app/services/file_service.py (_insert)
    severity: medium (unverified)
  - summary: >-
      In dev compose (no nginx) GET /api/files/{id} returns an empty 200, so files cannot be viewed in dev.
    evidence: |-
      docker-compose.yml mounts files_data only in backend and worker; X-Accel-Redirect needs nginx. A dev fallback that streams bytes would be new surface.
    location: >-
      docker-compose.yml
    severity: medium
  - summary: >-
      backup-db.sh / restore-db.sh file handling and compose volume wiring have no automated test.
    evidence: |-
      No test runs either script or asserts the files_data mounts; a typo in the archive-name derivation would only show in a real restore.
    location: >-
      scripts/backup-db.sh, scripts/restore-db.sh, docker-compose.prod.yml
    severity: medium
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

### 2026-11-01 — Review pass
- verdicts: 35 findings — high 0, medium 9, low 18, false 6, maybe-false 2
- findings:
  - `[medium]` `[patch]` Blind: restore empties the volume and so deletes Live audio the backup left out — restore now keeps `*/live_audio` directories; doc says so.
  - `[low]` `[reject]` Blind: rows whose bytes are missing after a restore are never removed — they answer the uniform 404; auto-deleting rows on missing bytes would also fire on a transient mount problem, so the fix is riskier than the 404.
  - `[medium]` `[patch]` Blind: a failed restore leaves backend and worker stopped — EXIT trap restarts them.
  - `[low]` `[patch]` Blind: deleted Campaigns' directories never swept when no live Campaign has a directory — schedule_daily enqueues one Job for the first live Campaign in that case.
  - `[medium]` `[patch]` Blind: the day key is set before work, so a DB error skips gc for the day — key deleted on failure.
  - `[low]` `[reject]` Blind: gc cost grows with file count (rows reloaded per candidate) — self-hosted Campaigns hold few rows (a tile tree is one row); `done` is advanced by run_cursor.
  - `[medium]` `[patch]` Blind: stale-marker query filters on ref_id alone and cannot use `(ref_kind, ref_id)` — now `ref_kind IN SOURCE_KIND_MODELS` (other kinds already make the file GM-only).
  - `[maybe-false]` `[defer]` Blind: two concurrent puts with the same cache_key give the second an IntegrityError — needs a concurrency test on real Postgres; if true medium (deferred).
  - `[low]` `[patch]` Blind: Content-Disposition has no filename — adds `filename="<kind>-<id><ext>"`.
  - `[low]` `[reject]` Blind: charset dropped from text/plain — no text producer exists yet; keeping parameters means parsing and whitelisting them.
  - `[maybe-false]` `[patch]` Blind: inline PDF probably blank under `CSP: sandbox` in Chromium — PDF removed from the inline list (a deletion; downloads always work).
  - `[low]` `[reject]` Blind: If-Range against nginx with `etag off` returns full 200 — browsers seek with plain Range; only resumed downloads send If-Range.
  - `[low]` `[reject]` Blind: accel_response stats the file on the event loop — a few stat calls, no reads for plain files; the manifest read is cached.
  - `[low]` `[reject]` Blind: nightly full tar of the volume on the same disk — ops sizing; Tier 2 in the doc already covers offsite copies.
  - `[low]` `[patch]` Blind: missing tests (reaper wiring, read_bytes mismatch) — added (see VG rows); script tests deferred (VG row).
  - `[medium]` `[defer]` Blind: dev compose has no nginx, so a 200 reaches the browser empty in dev — a dev byte-serving fallback is new surface; deferred.
  - `[low]` `[patch]` Blind: `_campaign_dir_path` checks the root, not the path — now checks the path.
  - `[low]` `[patch]` Blind: gc ORPHAN calls `_entry_path` before the Campaign check (UnsafePath) — grouped with Edge row 3.
  - `[low]` `[reject]` Blind: doc lines exceed the wrap width — cosmetic.
  - `[medium]` `[patch]` VG: no test that a Reaper pass schedules files.gc — test added.
  - `[medium]` `[patch]` VG: closing a session with an uncommitted put not tested — test added.
  - `[low]` `[patch]` VG: read_bytes hash-mismatch branch untested — test added.
  - `[medium]` `[defer]` VG: backup/restore scripts and compose volume wiring have no automated check — needs Docker; deferred (desktop check listed).
  - `[low]` `[patch]` VG other: day key set before work — grouped with Blind row 5.
  - `[low]` `[patch]` VG other: deleted-only directories never swept — grouped with Blind row 4.
  - `[medium]` `[patch]` Edge: regexes use `.match` with `$`, so a trailing newline passes subpath/key validation — `.fullmatch` everywhere, test added.
  - `[low]` `[patch]` Edge: a `<uuid>\n` directory makes campaign_dirs raise — fixed by fullmatch.
  - `[low]` `[patch]` Edge: an orphan with a backslash in its name fails every gc step — gc_one returns False on UnsafePath.
  - `[low]` `[patch]` Edge: day key set before work — grouped with Blind row 5.
  - `[low]` `[patch]` Edge: deleted-only directories never swept — grouped with Blind row 4.
  - `[low]` `[defer]` Edge: concurrent same cache_key IntegrityError — grouped with Blind row 8.
  - `[medium]` `[patch]` Edge: a Player put with a GM file's cache_key supersedes it — non-GM puts are narrowed to themselves and supersede only rows with the same audience_owner_id; because the unique index has no owner column (no migration allowed), an owned file stores its cache_key as `<owner id>:<cache_key>`.
  - `[medium]` `[patch]` Edge: corrupt archive found only after the volume is emptied — archive verified before the prompt.
  - `[false]` `[reject]` Intent: nginx runtime (accel headers, internal 404) never exercised — verified on the desktop with real nginx 1.27: ETag, Vary, nosniff, CSP, Content-Type, Content-Disposition survive; direct `/_files/` 404; `..` in X-Accel 404.
  - `[false]` `[reject]` Intent: staleness on any change, not only downgrades — the stale marker gets no old/new value; marking on every change fails closed, as the spec states.

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

## Auto Run Result

Status: done

**Summary:** `app/services/file_service.py` owns the `files_data` volume (`put`, `put_tree`, `open`, `read_bytes`, `delete`, `accel_response`, the stale marker registered with `register_stale_marker`, gc helpers). `app/access/files.py` holds every `stored_files`/`derived_sources` read: `file_sources` loads ALL of a file's source rows, and `visible_file` requires both the SQL (`scoped_get`) and Python (`audience_of`) checks. `GET /api/files/{file_id}` answers an empty 200 with `X-Accel-Redirect` and safe headers (nosniff, sandbox CSP, Content-Disposition with filename, no inline HTML/SVG/XML/JS/PDF), 304 on a matching ETag, and the uniform 404 otherwise. `delete` removes the `derived_sources` rows. `files.gc` is a cursor Job scheduled daily by the reaper. nginx has an internal `^~ /_files/` location; `files_data` is rw in backend/worker, ro in nginx. Backups archive `files_data` after the dump (Live audio only with the per-Campaign opt-in marker); restore verifies the archive, keeps `live_audio`, restarts services on exit.

**Files changed:**
- `src/backend/app/services/file_service.py` -- new: the volume owner.
- `src/backend/app/access/files.py` -- new: loader and double visibility check.
- `src/backend/app/api/routes/files.py`, `app/main.py` -- the file route.
- `src/backend/app/jobs/files_gc.py`, `registry.py`, `worker.py` -- `files.gc` kind, handler, daily scheduling.
- `src/backend/app/core/config.py` -- `files_root`.
- `nginx/locations.conf`, `docker-compose.yml`, `docker-compose.prod.yml`, `src/backend/Dockerfile.prod` -- internal location and volume.
- `scripts/backup-db.sh`, `scripts/restore-db.sh`, `docs/DATABASE_BACKUPS.md` -- backups of stored files.
- `src/backend/tests/test_file_service.py`, `tests/ev4/probes/files.py`, `tests/conftest.py` -- tests, EV-4 probes, temp FILES_ROOT.

**Review:** 35 findings. Patched 21 rows (9 medium entries, the rest low/maybe-false). Deferred 3 (concurrent cache_key IntegrityError, unverified; no dev byte serving without nginx; no automated test of the backup scripts or compose mounts). Rejected 9 lows and 2 false (see the triage log for each reason).

**Follow-up review:** true. Patched entries at medium: 9 (no high), so "two or more medium" applies. Specific unverified risk: the owner-namespaced `cache_key` (`<owner id>:<key>`) introduced by the patch changes what callers must pass to look a file up by key, and it was not re-reviewed.

**Verification:** Implementer ran the full backend suite against a throwaway local Postgres (1645 passed, 89 skipped, EV-4 0 leaks) before the patches, then `tests/test_file_service.py` + the files probes after them (85 passed); `check_scoped_queries.py`, `lint-imports`, ruff clean. Real nginx 1.27 on the desktop (throwaway containers, removed): ETag, Vary, nosniff, CSP, Content-Type, Content-Disposition survive the X-Accel redirect; a direct `/_files/...` request is 404; `..` in X-Accel-Redirect is 404. GitHub CI on PR #62 is the gate.

**Needs desktop verification:**
- `docker compose -f docker-compose.prod.yml config -q` -- valid.
- Prod bring-up: `GET /api/files/{id}` through nginx returns the bytes for a GM; `curl -k https://<host>/_files/<key>` is 404.
- `scripts/backup-db.sh` then `scripts/restore-db.sh <dump>` on a throwaway stack: `lorekeeper_files_*.tar.gz` written next to the dump, `live_audio` excluded without `.backup-live-audio`, restore brings files back and restarts backend and worker.

**Residual risks:** concurrent same-`cache_key` puts (deferred); dev compose cannot show file bytes; any Visibility change of a source (upgrades included) marks its files stale.
