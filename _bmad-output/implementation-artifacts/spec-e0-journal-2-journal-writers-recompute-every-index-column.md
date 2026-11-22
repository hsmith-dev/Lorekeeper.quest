---
title: 'E0-Journal.2: Journal writers recompute every index column'
type: feature
created: '2026-11-21'
status: done
baseline_revision: 90c8ea18b688baa1306717a61e03e6f3b2007475
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings:
- oversized
deferred:
- summary: A detached derived tag reappears on the next text edit or reindex of the entry.
  evidence: detach deletes the link; _replace_derived_tags re-derives it from NER. A suppression record (or detaching
    as a negative manual row) is a product decision.
  location: src/backend/app/services/journal_service.py:_replace_derived_tags
  severity: low
- summary: Pre-existing rows keep their stored entry_hash (seed rows use the old seed hash); no recompute migration.
  evidence: Client hashes already equal sha256(trim.lower); only demo-seed rows differ. A recompute could collide
    with uq_journal_entries_campaign_user_entry_hash and needs a collision policy.
  severity: low
- summary: The generate route's Valkey check_hash is not best-effort (Valkey down is a 500); unchanged from before.
  evidence: Pre-existing; the service wrappers swallow Valkey errors but the route calls check_hash directly.
  location: src/backend/app/api/routes/journals.py:generate_journal
  severity: low
---

<intent-contract>

## Intent

**Problem:** Journal index columns (`narrative_tsv`, `party_tsv`, `embedding`, `party_embedding`, tags, `entry_hash`) are written ad hoc by the create path, the reindex route, `retrieval_service.index_party_fields`, the demo seed and the Party backfill script. There is no update or delete writer, no fallback when the `ml` sidecar is down, and the client supplies the dedup hash.

**Approach:** `journal_service` becomes the only module that assigns those columns. It has four public writers, `create_journal_entry`, `update_journal_entry`, `delete_journal_entry` and `reindex_entry`, and they share one recompute path (`_recompute_index`). If `ml` fails, the vectors are cleared and derived tags are dropped. A hook handler then enqueues a `journal.reembed` onsave Job, which re-runs `reindex_entry`.

## Boundaries & Constraints

**Always:**
- tsv columns are computed in SQL from the stored row: `narrative_tsv` covers Shorthand and Narrative, `party_tsv` covers Narrative only.
- Both vectors come from one `embed_many` call.
- Tags are derived from `ml /v1/ner` over the Narrative (`source_field=narrative`) and over the Shorthand (`shorthand`). Narrative wins when a tag comes from both.
- `manual` rows and unclassified legacy `NULL` rows are kept. A legacy `NULL` row whose tag is re-derived takes the derived `source_field`, which can only narrow who sees it.
- `entry_hash = sha256(shorthand.strip().lower())`, the same as `utils/hashNotes.ts`, and is computed on the server. Any hash the client sends is ignored.
- The Redis dedup key is `(campaign, user, hash)`. A collision on create or update returns 409.
- A save never blocks on `ml`.
- Writers emit `entry_saved`, `entry_updated` or `entry_deleted` with the exact refs the story gives. The `app/hooks/journal.py` handlers publish `{domain:"journal", id}` (delete: unkeyed) and enqueue `journal.reembed` when a vector is NULL.
- Offline-queue saves, and every one-step save with no reviewed narrative, land `visibility=gm`.
- Visibility edits go through `set_visibility`.

**Never:**
- No `as_system`, detach, PUT/edit routes or UI. Those are E0-Journal.3 and .4.
- No new migration, no new scoped-query baseline lines, no `ignore_imports`.
- Services never import `app.jobs`. The enqueue happens in the hook layer.
- Don't edit sibling files: compose, `tests/ev4/probes/*` other than additive `journals.py`, frontend SSE.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error |
|---|---|---|---|
| Create, ml up | notes + narrative | tsv, both vectors, derived tags set; `entry_saved` | — |
| Create, ml down | same | row saved, tsv set, vectors NULL, no derived tags, warning logged; handler enqueues `journal.reembed` (key `journal.reembed:{id}:{hash}`) | — |
| Create duplicate | same notes, same user+Campaign | — | 409 |
| Update text | `changes={"narrative": ...}` | all index columns recomputed; hash recomputed; `entry_updated` with `changed_fields`, `previous_entry_hash` | collision → 409, nothing written |
| Update date/visibility only | `{"session_date"}` / `{"visibility"}` | no recompute; visibility via `set_visibility` | — |
| Delete | id | row and links gone, dedup key dropped, `entry_deleted {journal_id, kind}` | hidden/forbidden → 404 |
| Reindex route | Campaign | `reindex_entry` per row, no hooks | ml down → 503, nothing changed |
| Reembed Job | entry hash unchanged | `reindex_entry(strict=True)` fills vectors and tags | ml down → raises, Job retries |
| Reembed Job, stale | entry edited/deleted since | no-op, `done` | — |
| Offline save | `offline: true` or no narrative | `visibility=gm` | — |

</intent-contract>

## Code Map

- `src/backend/app/services/journal_service.py`: the writers. Remove the raw SQL, `select(Tag)` and `select(JournalEntry)` in favour of ORM `update()`, a `pg_insert ... on_conflict ... returning` upsert, and `scoped_get`. Drop the 3 `create_journal_entry` lines from `scripts/scoped_queries_baseline.txt` and lower the matching counts in `scripts/test_check_scoped_queries.py` `FROZEN_BASELINE`.
- `src/backend/app/services/retrieval_service.py:290` `index_party_fields`: becomes a lazy delegate to `journal_service` (EV-4 probes still import it).
- `src/backend/app/api/routes/journals.py`: `/generate` computes the hash and `offline`. `/reindex` (`:368`) uses `reindex_entry`. Delete uses `delete_journal_entry`. `attach_tag` writes `source_field=manual`.
- `src/backend/app/schemas/journal.py` `GenerateRequest`: `entry_hash` becomes optional and ignored. Add `offline: bool = False`.
- `src/backend/app/services/dedup_service.py`: add `drop_hash`.
- `src/backend/app/jobs/registry.py`: register `JOURNAL_REEMBED` (onsave, `cpu_heavy`, `live_safe=False`, handler `app.services.journal_service:reembed_job`).
- `src/backend/app/hooks/journal.py` (new) and `app/hooks/__init__.py`: handlers that publish and enqueue the fallback.
- `src/backend/scripts/seed_demo.py`: entries go through `create_journal_entry(..., hooks=False, tags=False, embed=...)` and `reindex_entry`. Idempotency is looked up by (Campaign, author, Shorthand).
- `src/backend/scripts/backfill_party_embeddings.py`: writes through the `journal_service` helpers.
- `src/frontend/src/hooks/useOfflineQueue.ts` and `types`: send `offline: true`.
- Read-only. Ingest (discord/voice/image) only returns text. Character Sheets and session plans don't write journals. `set_visibility` touches no index column.

## Tasks & Acceptance

**Execution:**
- `journal_service.py`: writers, `compute_entry_hash`, `_recompute_index`, `reembed_job`, backfill helpers.
- `journals.py`, `schemas/journal.py`, `dedup_service.py`, `registry.py`, `hooks/journal.py`, `hooks/__init__.py`, seed and backfill scripts, `retrieval_service.py`, frontend offline queue: as mapped above.
- `tests/test_journal_writers.py` (new): covers the matrix, plus a grep test over `app/` and `scripts/` (excluding `make_snapshot.py`, which writes a historic schema snapshot) that fails on assignments to `narrative`, `shorthand`, `narrative_tsv`, `embedding`, `party_tsv`, `party_embedding` or `entry_hash` on a JournalEntry outside `journal_service`.
- Update existing tests for the new signatures.

**Acceptance Criteria:**
- Given the full backend suite and gates on CI, when run, then they are green with no new baseline lines.

## Spec Change Log

### 2026-11-22 — Coordinator follow-up before merge (two deferrals made in-scope)
- **Trigger:** the coordinator required two deferrals fixed before merge: the reembed fallback must be durable and race-free, and a GM edit's 409 must not reveal a hidden entry.
- **Amended (outside the intent contract):**
  - **Durable reembed.** `journal.reembed_sweep` (`app/jobs/journal.py`) is a cursor Job (`run_cursor`, backfill queue, `cpu_heavy`) over entries with a NULL vector. It runs once through the `journal_reembed_v1` data backfill (`register_backfill`) and daily through `schedule_daily` on the reaper pass.
    - When ml is down it is a no-op: the scheduler probes ml once and re-arms in 10 minutes, a step's failed probe ends the Job `done`, and a row's ml error skips that row.
  - **Race.** `_recompute_index` is a compare-and-set: the tsv UPDATE matches only the text that was embedded. If the text changed, it writes nothing and raises `EntryTextChanged`. The reembed Job retries on the new text, and `/reindex` and the sweep skip the row.
  - **409 only for visible duplicates.** `visible_duplicate` (`scoped_select`), under a per-(Campaign, author, hash) advisory lock, replaces both the Valkey check and the unique constraint as the 409 decision.
    - Migration `7d1e2a9c4b6f` turns `uq_journal_entries_campaign_user_entry_hash` into the plain index `ix_journal_entries_campaign_user_entry_hash` and queues the backfill row.
    - The constraint was per author, not Campaign-wide. The reachable leak was an author who cannot see one of their own entries (for example a demoted GM's GM-only entry). Another Player's Private entry could never collide.
- **Known-bad state avoided:**
  - an entry left unembedded forever after a lost hook;
  - stale vectors overwriting an edit;
  - a 409 revealing that a hidden entry exists.
- **KEEP:**
  - one recompute path;
  - the hash rule;
  - search-only reindex;
  - one-step saves are GM-only (owner-approved);
  - the hook-based fast fallback.

## Data safety (migration 7d1e2a9c4b6f and the reembed backfill)

- **Upgrade changes no row.** Dropping the unique constraint and adding a non-unique index on the same three columns loses no data, and queries keep an index.
- **Behaviour change:** two entries by one author may now share a hash, but only when one of them is hidden from the writer. Every 409 decision happens in `journal_service` under an advisory lock, so two visible duplicates cannot race in. A Valkey key no longer decides a 409.
- **The backfill writes only through `reindex_entry`.** It fills NULL vectors and that entry's derived tags (manual and legacy links are kept). It never changes text, hash or Visibility.
  - It writes nothing while ml is down.
  - The compare-and-set guard means it never overwrites a newer edit.
  - It is idempotent: a filled row is no longer selected.
- **Re-running the upgrade is safe:** the backfill row insert is `ON CONFLICT DO NOTHING`.
- **downgrade()** (development only, NFR-8) restores the unique constraint and removes the backfill row. If rows now share a hash it refuses with a clear error and deletes nothing.
- **Merge order:** the revision's `down_revision` is `eed202f2eead` (E0-WorldCore.7, main at rebase). A later sibling migration on main needs a rebase, or this `down_revision` re-pointed.


## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 33 findings — high 1, medium 9, low 12, false 7, maybe-false 4
- findings:
  - `[false]` `[reject]` Blind: reembed key ignores Narrative — enqueue dedups only active Jobs; a finished Job frees the key, and a queued one re-reads the current row.
  - `[low]` `[reject]` Blind: NER failure also clears vectors — deliberate: one failure signal (NULL vector) drives the reembed fallback, which redoes both.
  - `[medium]` `[patch]` Blind/Edge: /reindex lost batching — restored one embed_many for the Campaign before any write; per-row reindex_entry with precomputed vectors.
  - `[medium]` `[patch]` Blind/Edge/VerifGap: /reindex 500 on ValueError — now caught with ModelServiceError: rollback, 503.
  - `[low]` `[defer]` Blind: generate route check_hash not best-effort — pre-existing.
  - `[low]` `[reject]` Blind: create skips the service Valkey check — the route checks first and the unique constraint backs it.
  - `[maybe-false]` `[reject]` Blind: JS/Python normalization parity on exotic Unicode — only client UX dedup; the server hash is authoritative.
  - `[low]` `[defer]` Blind: existing rows' hashes not recomputed — see deferred.
  - `[false]` `[reject]` Blind: update_journal_entry has no caller — the PUT route is E0-Journal.3 by the epic's own story split.
  - `[low]` `[patch]` Blind: session_date not validated — `_normalize_changes` rejects a non-date.
  - `[maybe-false]` `[reject]` Blind: _reload fallback unloaded tags — fallback only when ctx cannot see its own write, which no writer path produces.
  - `[medium]` `[patch]` Blind/Edge: Tag upsert lock order — keys sorted before the multi-row upsert.
  - `[medium]` `[defer]` Blind: no sweep behind the at-most-once hook — deferred.
  - `[false]` `[reject]` Blind: visibility silently overridden for unreviewed saves — the rule is the intended safe default and is documented.
  - `[low]` `[reject]` Blind: missing-tests list — covered by the VerifGap patches below; the 503 route test exists (tests/test_ml_callers.py).
  - `[low]` `[reject]` Blind: `test_dedup_drop_hash_exists` is weak — harmless.
  - `[medium]` `[patch]` VerifGap: entry_updated hook path untested — added test_update_with_ml_down_enqueues_reembed_and_publishes.
  - `[medium]` `[patch]` VerifGap: publish-failure guard untested — added test_failed_publish_still_enqueues_the_reembed.
  - `[low]` `[reject]` VerifGap: multi-entry reindex rollback untested — vectors are now computed before any write, so the partial-write case cannot occur.
  - `[high]` `[patch]` Edge: attach_tag of a hidden (shorthand) link raises PK IntegrityError (500) — attach is now an upsert that sets `manual`.
  - `[medium]` `[patch]` Edge: manual attach of a derived link stays derived and is dropped on the next edit — same upsert promotes it to `manual`.
  - `[low]` `[defer]` Edge: detached derived tag reappears on recompute — deferred (product decision).
  - `[medium]` `[defer]` Edge: running reembed Job vs Narrative-only edit race — deferred.
  - `[low]` `[reject]` Edge: Valkey drop failure leaves stale key — logged, expires with DEDUP_TTL; unique constraint is the authority.
  - `[false]` `[reject]` Edge: reindex non-ml failure (dup of the patched 503 row) — patched above.
  - `[false]` `[reject]` Edge: reindex large Campaign (dup of batching row) — patched above.
  - `[false]` `[reject]` Edge: tag deadlock (dup) — patched above.
  - `[low]` `[patch]` Edge: seed lookup misses case/whitespace variants — lookup also matches compute_entry_hash(shorthand).
  - `[maybe-false]` `[reject]` Edge (claim): routes still write journal_tags — manual links are route-owned by design; journal_service owns derived links only.
  - `[low]` `[reject]` Intent: grep test maps `notes` to `shorthand` — `notes` is the API name; the column is `shorthand`.
  - `[low]` `[reject]` Intent: enqueue after commit, not in-transaction — forced by the layer contract (services never import app.jobs); documented.
  - `[maybe-false]` `[reject]` Intent: unreviewed saves broader than offline — the one-step path exists only for the offline queue.
  - `[false]` `[reject]` CI EV-4 probe_reindex leak — not a leak of GM content: the reindex re-derived tags and dropped fixture tags; fixed by reindex updating search columns only (tags=False).

## Design Notes

**Why the fallback Job is enqueued from a hook.** The layer contract forbids services importing jobs. Hooks are at most once, so if the process crashes between commit and dispatch, the Job is lost. The entry then keeps NULL vectors until the next `/reindex` or a script rerun. That is noted as deferred: a cursor backfill (`register_backfill`) over NULL-embedding rows is the durable follow-up.

**Why seeds skip hooks.** The demo seed is a bulk loader with no request, and `--embeddings skip` must never call `ml`.

**Data safety.**
- No migration and no rewrite of existing rows.
- Existing client hashes already equal the server hash. Seeded rows keep their old seed hash until they are edited. The seed's lookup by Shorthand prevents duplicates on rerun.
- Legacy `NULL` tag links are never deleted.

**Known leak to decide later.** A GM editing a Player's entry into a collision with that Player's hidden entry gets a 409. This is flagged for E0-Journal.3 and E0-QA.14.

## Verification

**Commands:**
- `cd src/backend && python -m py_compile app/services/journal_service.py app/hooks/journal.py`: expected no output.
- GitHub CI `backend-tests.yml`, `gates.yml`, `frontend-ci.yml`: expected green.

## Auto Run Result

Status: done. Draft PR #80 (branch `story/e0-journal.2-index-recompute`), GitHub CI green on 43dcc345f24d44ebf80e15b0409086141ab06542.

**Summary:** `journal_service` holds the four journal writers, `create_journal_entry`, `update_journal_entry`, `delete_journal_entry` and `reindex_entry`, and they share one recompute path. The hash is computed on the server and collisions return 409. If `ml` fails, the save still goes through and the `journal.reembed` onsave fallback fills the index later; it is enqueued from `app/hooks/journal.py`. Each write emits its hook event and publishes a campaign event. Offline and unreviewed saves land GM-only. The seed and the Party backfill script now write through `journal_service`, and a new grep test enforces the single writer.

**Files:**
- `app/services/journal_service.py`: the writers, the recompute path, the reembed Job handler and the backfill helpers.
- `app/hooks/journal.py` (new) and `app/hooks/__init__.py`: publish on every write, and enqueue the reembed fallback.
- `app/jobs/registry.py`: `journal.reembed` is registered here.
- `app/api/routes/journals.py`: `/generate` uses the server hash and the `offline` flag. `/reindex` updates search columns only and embeds in one batch. Delete calls `delete_journal_entry`. attach_tag upserts a `manual` link.
- `app/schemas/journal.py`: `entry_hash` is optional and ignored; adds `offline`.
- `app/services/dedup_service.py`: adds `drop_hash`.
- `app/services/retrieval_service.py`: `index_party_fields` now delegates to `journal_service`.
- `scripts/seed_demo.py` and `scripts/backfill_party_embeddings.py`: now write through `journal_service`.
- `scripts/scoped_queries_baseline.txt` and `scripts/test_check_scoped_queries.py`: 3 baseline lines removed.
- Frontend `useOfflineQueue.ts` and `types/index.ts`: the offline queue sends `offline: true`.
- Tests: `tests/test_journal_writers.py` is new. `tests/conftest.py` now drains hook tasks before the engine is disposed. Updated `test_party_retrieval.py` and `seeds/test_demo_seed.py`.

**Review:** 33 findings.
- **Patched (9):** 1 high, 6 medium, 2 low:
  - attach_tag no longer fails with a 500 on a hidden link;
  - reindex embeds in one batch, updates search columns only, and returns 503 on a ValueError;
  - the Tag upsert takes locks in a fixed order;
  - `session_date` is validated;
  - the seed looks entries up by hash;
  - two missing hook tests added.
- **Deferred (6):** see the frontmatter.
- **Rejected:** the rest, with reasons in the triage log.
- **Also fixed from CI:** the EV-4 reindex probe failure (reindex re-derived tags) and a 6-hour backend-test hang (hook tasks outliving their test).

**Follow-up review recommended: true.** A high finding was patched (attach_tag upsert), and an independent review of the tag-link ownership between routes and `journal_service` is worthwhile.

**Verification:** GitHub CI is green for `backend-tests` (full pytest), `gates` (database/EV-4 and static), frontend CI and licences. Local checks passed: py_compile, `check_scoped_queries`, `lint-imports` and `pytest scripts/`.

**Residual risks:**
- Hook delivery is at most once, and no durable NULL-vector sweep backs it up.
- A reembed Job can race a Narrative-only edit.
- One-step saves are now always GM-only.

### Follow-up (2026-11-22): durable reembed, race guard, privacy-first duplicates

- **New files:**
  - `app/jobs/journal.py`: the sweep kind, the backfill and `schedule_daily`.
  - `migrations/versions/7d1e2a9c4b6f_journal_hash_visible_dedup_reembed.py`.
  - `tests/jobs/test_journal_sweep.py`.
- **Changed:**
  - `journal_service`: `visible_duplicate`, `_lock_hash`, `EntryTextChanged` with the compare-and-set, and the sweep helpers `ml_available`, `has_unembedded` and `next_unembedded`.
  - `journals.py`: the route pre-check uses `visible_duplicate`; `/reindex` skips a changed row.
  - The `JournalEntry` model's index.
  - `registry.py`: `KIND_MODULES`.
  - `worker.py`: the reaper calls `schedule_daily`.
  - `dedup_service` comment.
  - `test_upgrade_snapshot.py`: the new revision check and its downgrade test.
- **Tests added:**
  - Hidden duplicate on create and on update never 409s; a visible one does.
  - The reindex race writes nothing, and the Job retry embeds the new text.
  - Sweep: fill, ml-down no-op, per-row skip, daily schedule and its ml-down retry.
  - EV-4 probe `probe_generate_hidden_duplicate_is_never_a_409` (`tests/ev4/probes/journals.py`, additive).
- **Tests updated:** three `tests/access` tests had their now-obsolete `check_hash` monkeypatch removed.
