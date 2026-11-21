---
title: 'E0-Journal.2: Journal writers recompute every index column'
type: 'feature'
created: '2026-11-21'
status: 'in-progress'
baseline_revision: '90c8ea18b688baa1306717a61e03e6f3b2007475'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
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
