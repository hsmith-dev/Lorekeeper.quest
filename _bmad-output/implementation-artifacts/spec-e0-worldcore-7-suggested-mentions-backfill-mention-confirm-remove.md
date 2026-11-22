---
title: 'E0-WorldCore.7: Suggested Mentions backfill and Mention confirm/remove'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: '9b0f01a437d70660905892cede406e07943553c9'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/orchestration/builder-brief.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Old journal entries are not linked to the Entities they name. The GM has no way to see, confirm or remove Mentions, and the entry view cannot list the Entities an entry mentions.

**Approach:** Add a `backfill.mentions` cursor Job that consumes the existing `data_backfills` row `suggested_mentions_v1`. Per Campaign it walks the `kind = gm` entries in Session order and writes suggested Mentions (`confirmed = false`, `origin = migration`, `source_field = narrative`) through `apply_change(add_mention)`. Add a small Alembic revision with a partial unique index for suggested rows. Add four routes under `/api/entities`: the Entity's Mentions, an entry's Mentions, confirm and remove. Players only ever see confirmed Mentions that the binding audience formula allows.

## Boundaries & Constraints

**Always:**
- Every Mention write goes through `world_service.apply_change` (`AddMention` / `ConfirmMention` / `RemoveMention`). Every read goes through `scoped_select` / `scoped_get` and every response through `project_all`. Citations and titles come from `access.resolve_sources`.
- The backfill runs with the Campaign Owner's GM ctx, which the runner and the worker build. It never uses `as_system`.
- Suggested Mentions are GM-only. A non-GM ctx (a Player, or a GM in member preview) gets only `confirmed = true` rows, whatever `confirmed=` it sends.
- Only confirmed Mentions count. That covers `mention_count`, and also `world_matching`'s Mention counts for ranking and `candidates().mention_count`.
- Hidden ≡ missing: a hidden or other-Campaign Entity, entry or Mention, and a Mention of another Entity, all answer the uniform 404. A Player write route answers 404 and writes nothing.
- Re-running the backfill or resuming it after a crash never duplicates a Mention. It never re-creates a suggestion the GM removed, and never adds a suggestion where a Mention for the same (entry, Entity, `narrative`) already exists, confirmed or not and from any origin.
- Edits to `world_service.py` are additive: shared with E0-WorldCore.6 and E0-WorldCore.9.

**Never:**
- No on-save Mention suggestion. New entries get Mentions from E1 extraction. E0-Journal.2 owns the on-save hooks.
- No frontend work (E0-WorldCore.11).
- No baseline lines in `scripts/scoped_queries_baseline.txt` or `tests/ev4/pending_baseline.txt`. No `ignore_imports`.
- No joins to `journal_entries` inside a `scoped_select(EntityMention, ...)`. The registry's EXISTS clauses could auto-correlate to a joined table, so sort in Python instead.
- Never match on Shorthand or `gm_notes` in the backfill.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Backfill happy path | `suggested_mentions_v1` queued; Campaign with 3 gm entries (one names "Mira" twice, one names Mira and Bree, one names nobody) and 1 player entry naming Mira | One `backfill.mentions` Job per Campaign, 3 steps, stage "Entry 3 of 3", progress 1.0. Mentions: (e1, Mira) ×1 with the quote = the sentence of the FIRST match and span = the first match; (e2, Mira) and (e2, Bree). None for the player entry. All `confirmed=false, origin=migration, source_field=narrative`, each with an `add_mention` history row. The data_backfills row ends `done`. | — |
| Session order | Entries with session_dates 2026-03-02, NULL (created 2026-03-01), 2026-03-01 | Processed in key order `coalesce(session_date, created_at::date), created_at, id` | — |
| Re-run / resume | Run the handler again over the same Campaign (fresh payload, no cursor) | No new Mention and no new history row | — |
| Removed suggestion | GM removed (e1, Mira); handler re-run | (e1, Mira) is not re-created | — |
| Existing Mention | A manual confirmed Mention (e1, Mira, narrative) exists before the run | No suggestion is added for (e1, Mira) | — |
| Shorthand only | A name appears only in Shorthand (or gm_notes) | No Mention | — |
| Long sentence | The sentence holding the match is longer than 300 characters | The quote is ≤ 300 characters, contains the match surface and is stripped | — |
| Entity list (GM) | 25 Mentions of one Entity across entries | `GET /api/entities/{id}/mentions?page=1` → 20 items, newest Session first, then `?page=2` → 5; `total` 25, `page_size` 20. Each item has `quote`, `journal_id`, `entry_title`, `confirmed`, `origin`. `?confirmed=false` gives only suggested rows, `true` only confirmed rows. | page < 1 → 422 |
| Entity list (Player) | Same, with some confirmed and some suggested, plus a confirmed Shorthand-sourced Mention and one on a GM-visibility entry | Only confirmed rows the formula allows. `?confirmed=false` gives `items: []`, `total: 0`. | hidden Entity → 404 |
| Entry list | `GET /api/entities/mentions?journal_id=e2` | Mentions of the entry with `entity_name`, `entity_type`, `entry_title`, ordered by `span_start` (nulls last), then entity name, then id. Excludes deleted and merged Entities. Player: confirmed and allowed only. | hidden, other-Campaign or missing entry → the same 404 |
| Confirm | GM POSTs confirm on a suggested Mention | 200 with the Mention GM body, `confirmed: true`; one `confirm_mention` history row; `mention_count` goes up by 1 | Mention of another Entity → 404; already confirmed with no earlier op → 422 `invalid`; Entity deleted/merged → 409 |
| Remove | GM DELETEs a Mention | 204; the row is gone; one `remove_mention` history row | Mention of another Entity → 404 |
| Player write | Player confirm/remove on a visible confirmed Mention | Same answer as a missing Mention; nothing written | — |
| Merge dedupe | Absorbed and survivor both have a suggested Mention of entry e1 (same source_field) | The merge succeeds; the absorbed duplicate is deleted, the survivor's row is kept | — |

</intent-contract>

## Code Map

Backend root: `src/backend/`. DB tests run only in CI (GitHub Actions; the desktop is offline). Never start Postgres or Valkey on this Mac.

- `app/services/world_service.py` -- the only Canon writer. `apply_change(db, ctx, change)` (~L1213) takes a CanonChange or a dict. `_add_mention` (~L788) is idempotent on (entity, journal, source_field, span, quote) and returns the earlier `add_mention` row. `_confirm_mention` (~L816) and `_remove_mention` (~L833, marks the Entity stale). The merge primitive `_merge` (~L901) has a mention move loop at ~L938 (`for mention in await run.all(scoped_select(EntityMention, ...))`). `CanonChangeError.code` values: `not_found, merged, deleted, invalid, ...`. It re-exports `match_names` and `candidates`.
- `app/schemas/entities.py` -- `AddMention` (~L401; fields `entity_id, journal_id, source_field, origin, confirmed, span_start, span_end`, plus `quote`, `source_journal_id` from `_Change`). `ConfirmMention(mention_id)` and `RemoveMention(mention_id)`. `EntityMentionGMResponse` (L101) and `EntityMentionPartyResponse` (L118; no origin, no source_field, no floor). `MAX_PAGE`.
- `app/db/models/entity.py` -- `EntityMention` (`__table_args__` at ~L130).
- `app/access/registry.py` L357 -- `EntityMention` is `derived` from entry and Entity, with `field="source_field"` and `floor=visibility_floor`. That is the binding formula, so `scoped_select(EntityMention, ctx)` already hides Shorthand/gm_notes-sourced rows, GM-visibility entries and GM-only/deleted/merged Entities from non-GMs. It does NOT know about `confirmed`.
- `app/access/sources.py` -- `resolve_sources(db, refs, ctx)` returns `ResolvedSource(ref, title, quote)`. Journal titles are `"Journal entry · <session_date>"` (kind `journal`, `where kind='gm'`) or `"Player journal · ..."` (kind `player_journal`). Use `SourceRef(kind=SourceKind.JOURNAL|PLAYER_JOURNAL, id=entry.id, field="narrative")` and take `.title`.
- `app/services/world_matching.py` -- `match_names(db, ctx, text)` returns `NameMatch(entity_id, surface, start, end, ...)` in text order. `_index` counts Mentions at ~L166 (`counts = scoped_select(EntityMention, ctx)...`); add `.where(EntityMention.confirmed.is_(True))` and update the docstring ("confirmed Mentions").
- `tests/services/test_world_matching.py` L253–330 -- tests that add unconfirmed `AddMention`s and expect them to count. Pass `confirmed=True` there, and add one assertion that an unconfirmed Mention does not count.
- `app/jobs/backfill.py` -- `run_cursor(job, ctx, db, *, select_next, process_one)`, `CursorStep(item, cursor, total)` and `register_backfill(name, kind)`. The runner enqueues with key `backfill:{name}:{campaign_id}` and payload `{"backfill": name}`. A continuation re-pushes the same Job id.
- `app/jobs/files_gc.py` -- the template for a cursor-Job handler module.
- `app/jobs/registry.py` -- `register(JobKind(...))`; `KIND_MODULES: tuple[str, ...] = ()` must list `"app.jobs.world"` (`tests/jobs/test_worker.py::test_kind_modules_cover_every_module_that_registers_a_kind`).
- `app/api/routes/entities.py` -- add routes here. Helpers: `_read_ctx` / `_gm_ctx` (`require_campaign_for(Entity, "entity_id", ...)`), `_write(db, work)`, `_canon_error` (409 superseded/deleted/merged, 422 invalid), `_rows`. Routes are matched in declaration order, so `GET /mentions` MUST be declared before `GET /{entity_id}`. Use `role_map_for_request` + `scoped_select_multi(JournalEntry, roles)` to find the entry's Campaign (it is cross-Campaign and visibility-checked), then `ctx_for_request(request, db, user, entry.campaign_id, "player")` for the full ctx with preview narrowing. Do NOT call `db.get` on a registered model (CI-8).
- `migrations/versions/0f1c3b194a4b_entity_changes_write_visibility.py` -- the current single head; a style reference.
- `tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check(REV)`, the revision constants (~L88) and the downgrade test pattern (`test_0f1c3b194a4b_downgrade_drops_its_column`, ~L936). `test_single_alembic_head`.
- `tests/test_migrations_match_models.py` -- model/migration drift gate: declare the index on the model too.
- `tests/jobs/test_backfill.py` -- test helpers to copy: `_campaign`, `_factory`, `ours` (monkeypatch `backfill.campaign_owners`), `_add_backfill`, `run_backfills`. In tests `JOBS_EAGER=1`, so an enqueue runs every step inside `commit()`.
- `tests/ev4/probes/entities.py` -- probe conventions: `_world`, `_create`, `_publish`, `_refused`, `WRITERS`, `MISSING`, `is_gm_of_a`, `authenticated`, `assert_same_answer`, `row_count`, `assert_counts_and_ranking_unchanged`, `assert_hidden_equals_missing`, `assert_no_canary`, `mint_canary`. `tests/ev4/probes/_support.py::add_entry(ev4, visibility=, kind=, canary=)` gives an entry whose narrative and shorthand are canaries (pass `canary=False` for plain narrative). Probe modules are auto-imported from `tests/ev4/probes/`, and `test_coverage.py` fails on an unprobed route.
- `tests/test_entities_api.py` -- GM route tests and their fixtures.
- `nginx/locations.conf` -- `location /api/entities/` already exists; nothing to add.

## Tasks & Acceptance

**Execution:**
- `migrations/versions/<12-hex>_suggested_mentions_unique.py` -- new revision, `down_revision = '0f1c3b194a4b'`. The docstring carries the Data safety rules below. `upgrade()`: (1) dedupe, deleting every suggested row that has an older suggested twin: `DELETE FROM entity_mentions m USING entity_mentions d WHERE NOT m.confirmed AND NOT d.confirmed AND m.journal_id = d.journal_id AND m.entity_id = d.entity_id AND m.source_field = d.source_field AND (d.created_at, d.id) < (m.created_at, m.id)`; (2) `op.create_index('uq_entity_mentions_suggested', 'entity_mentions', ['journal_id', 'entity_id', 'source_field'], unique=True, postgresql_where=sa.text('NOT confirmed'))`. `downgrade()` drops the index.
- `app/db/models/entity.py` -- add `Index("uq_entity_mentions_suggested", "journal_id", "entity_id", "source_field", unique=True, postgresql_where=sql_text("NOT confirmed"))` to `EntityMention.__table_args__`, and update the module docstring.
- `app/jobs/world.py` -- new module. Constants `BACKFILL_NAME = "suggested_mentions_v1"`, `KIND = "backfill.mentions"`, `QUOTE_LIMIT = 300`. Register `JobKind(name=KIND, queue=JobQueue.BACKFILL, timeout_s=120, handler="app.jobs.world:handle", resources=frozenset(), live_safe=True, result_audience="gm")` and `register_backfill(BACKFILL_NAME, KIND)`. `def step_key(campaign_id, cursor) -> str` returns `f"backfill.mentions:{campaign_id}:{cursor}"`; see Design Notes for why the runner's key is the one used. `async def handle(job, ctx, db)` calls `run_cursor` with:
  - `select_next`: the `scoped_select(JournalEntry, ctx).where(JournalEntry.campaign_id == ctx.campaign_id, JournalEntry.kind == "gm")` rows, sorted in Python by `(session_date or created_at.date(), created_at, id)`. The cursor is `[key_date_iso, created_at_iso, str(id)]`; return the first row whose key is greater than the decoded cursor, with `total` = the gm entry count.
  - `process_one`: `suggest_mentions(db, ctx, entry)`.

  `async def suggest_mentions(db, ctx, entry) -> int` (public; returns the number of Mentions it added):
  1. Run `match_names(db, ctx, entry.narrative)` and keep the first match per `entity_id`.
  2. For each, skip when `scoped_select(EntityMention, ctx)` already has a row (entry, Entity, `narrative`), or when `scoped_select(EntityChange, ctx)` has a `remove_mention` row for the Entity whose `old_value` has `journal_id == str(entry.id)`, `source_field == "narrative"` and `origin == "migration"` (JSONB `->>`).
  3. Otherwise call `apply_change(db, ctx, AddMention(entity_id, journal_id=entry.id, source_journal_id=entry.id, source_field=NARRATIVE, origin=MIGRATION, confirmed=False, span_start=m.start, span_end=m.end, quote=sentence_quote(entry.narrative, m.start, m.end)))`.
  4. Catch `CanonChangeError` (log at info with `job`-free extras `campaign_id`, `entity_id` and the code, never the text) and continue.

  `def sentence_quote(text, start, end, limit=QUOTE_LIMIT) -> str`: the sentence holding `[start, end)`. It starts after the last `[.!?]` followed by whitespace, or after a newline, before `start` (else 0), and ends at the first `[.!?]` after `end` that is followed by whitespace or the end of the text (inclusive), or before a newline (else len). Strip it. If it is longer than `limit`, return a `limit`-character window that contains the match: start at `max(sentence_start, min(start, end - limit))`, then strip.
- `app/jobs/registry.py` -- `KIND_MODULES = ("app.jobs.world",)` with a comment.
- `app/services/world_service.py` -- additive change in `_merge`'s mention loop. Before moving an unconfirmed mention whose `journal_id` is not NULL, check whether the survivor already has an unconfirmed Mention with the same `journal_id` and `source_field` (`run.first(scoped_select(EntityMention, run.ctx).where(...))`). If it does, `await run.delete(mention)` and `continue`; do not count it in `moved`. Add one docstring sentence. Touch nothing else.
- `app/services/world_matching.py` -- count confirmed Mentions only (Code Map), docstring included.
- `app/schemas/entities.py` -- add `entry_title: str | None = None`, `entity_name: str | None = None` and `entity_type: EntityType | None = None` to BOTH Mention response schemas (the route fills them as `extra`). Add `EntityMentionListGMResponse` / `EntityMentionListPartyResponse {items, total, page, page_size}` and `EntryMentionsGMResponse` / `EntryMentionsPartyResponse {items}`.
- `app/api/routes/entities.py` -- four routes, docstring table updated:
  - `GET /mentions` (declared before `/{entity_id}`; `journal_id: uuid.UUID` query, required). Find the entry with `scoped_select_multi(JournalEntry, roles)`, else `not_found()`. Then `ctx = await ctx_for_request(...)`. Mentions come from `scoped_select(EntityMention, ctx).where(EntityMention.journal_id == journal_id)`, plus `confirmed IS TRUE` when `ctx.role != GM`. Entities come from `scoped_select(Entity, ctx).where(id in ...)`, dropping deleted/merged ones and their Mentions. Names come from `project_all` of the Entities. Order by `(span_start is None, span_start, entity_name.lower(), id)`. `entry_title` comes from `resolve_sources`. Return `{items}`.
  - `GET /{entity_id}/mentions` (`_read_ctx`; `confirmed: bool | None = None`, `page: int = Query(1, ge=1)`, `PAGE_SIZE = 20`). Call `scoped_get` on the Entity. Mentions come from `scoped_select(EntityMention, ctx).where(entity_id == ...)`; for non-GMs force `confirmed IS TRUE`, and when a non-GM asks `confirmed=false` return an empty page. Load the entries with `scoped_select(JournalEntry, ctx).where(id in ...)` and drop any Mention whose entry is not returned (fail closed). Sort newest first by `(key_date, entry.created_at, mention.created_at, mention.id)` descending, where `key_date = session_date or created_at.date()`. Rows with a NULL `journal_id` (GM only) go last. Page in Python. Use `entry_title` from `resolve_sources` (kind by `entry.kind`). Return `{items, total, page, page_size}`.
  - `POST /{entity_id}/mentions/{mention_id}/confirm` (`_gm_ctx`). Load the Mention by `scoped_select(EntityMention, ctx).where(id == mention_id, entity_id == entity_id)`, else `not_found()`. Apply `ConfirmMention` through `_write` and return the projected GM body (`scoped_get` + `refresh` + `project_all`, with `entry_title`).
  - `DELETE /{entity_id}/mentions/{mention_id}` (`_gm_ctx`). Same lookup, `RemoveMention`, 204.
  - Every GET carries `openapi_extra=PARTY_READ` and `responses=` docs, like the existing routes.
- `tests/migrations/test_upgrade_snapshot.py` -- add a revision constant and `@post_upgrade_check`: the index exists, is unique and is partial (`pg_indexes.indexdef` contains `WHERE (NOT confirmed)`). Add `test_<rev>_downgrade_drops_its_index` (downgrade to `0f1c3b194a4b`, index gone, upgrade back). Update the module docstring.
- `tests/jobs/test_world_backfill.py` -- new file. The DB tests cover every backfill matrix row:
  - the happy path through `run_backfills` with `ours` (one Job, kind/queue/key `backfill:suggested_mentions_v1:{cid}`, stage/progress, `cursor.entries`, row `done` after the second pass);
  - Session order (capture via monkeypatching `suggest_mentions` or by checking the `add_mention` history `created_at` order);
  - re-run: call `suggest_mentions` again, and also run `handle` on a fresh Job, with counts unchanged;
  - a removed suggestion is not re-created, and an existing manual Mention blocks a suggestion;
  - Shorthand/gm_notes only creates nothing, and player entries are skipped;
  - the partial unique index rejects a second suggested row inserted through `apply_change` with a different quote (`CanonChangeError("invalid")`).

  Pure tests cover `sentence_quote` (first sentence, the middle of three, a newline boundary, > 300 characters, the match at the end of the text) and the registration values (`get_kind("backfill.mentions")` fields, `BACKFILLS["suggested_mentions_v1"]`, `step_key`).
- `tests/services/test_world_service.py` -- a merge where both Entities have a suggested Mention of the same entry succeeds, and the survivor keeps exactly one.
- `tests/test_entities_api.py` -- GM tests for the four routes: paging (25 → 20 + 5, `page=0` → 422), order, the `confirmed` filter, item fields, the entry list order and deleted-Entity exclusion, confirm (200, history row, `mention_count` +1, another Entity's Mention 404, double confirm), remove (204, history row), and a Player getting only confirmed and allowed rows.
- `tests/ev4/probes/entity_mentions.py` -- new probe module (a separate file so it cannot conflict with E0-WorldCore.9's merge probe in `entities.py`). It has one `@ev4_probe` per route (writes use `actors=WRITERS`). The fixture is built through `apply_change` and `suggest_mentions`:
  - a Party Character "Mira Party"; a Party gm entry whose narrative is plain and names Mira (backfill → a suggested Mention with a plain quote); a confirmed Narrative Mention on a second Party entry (plain quote);
  - a Party entry whose narrative does NOT name Mira but whose Shorthand is `"Mira " + canary` (backfill → nothing), plus a GM-added confirmed Mention with `source_field=shorthand` and a canary quote;
  - a GM-visibility entry (canary narrative) with a confirmed Mention; a GM-only Entity (canary name) with a confirmed Mention on a Party entry;
  - an outsider Campaign's Party Entity, entry and Mention.

  Assertions:
  - a Player sees exactly the one plain confirmed Mention, and `?confirmed=false` is empty;
  - `assert_counts_and_ranking_unchanged` on the Entity's Mention list, the entry list, `GET /api/entities/{party}` (`mention_count`) and `GET /api/entities/?campaign_id=&q=Mira` around a GM-only write: a Shorthand-only canary entry run through `suggest_mentions`, a new suggested Mention, and a GM-only Entity Mention;
  - hidden ≡ missing for the GM-only Entity, the outsider Entity, the GM-visibility entry, the outsider entry and a Mention of another Entity;
  - Player confirm/remove go through `_refused`-style checks with history and Mention counts unchanged;
  - a GM confirm returns 200 and a GM remove 204.
- `_bmad-output/implementation-artifacts/spec-e0-worldcore-7-suggested-mentions-backfill-mention-confirm-remove.md` -- fill in the Verification results.

**Acceptance Criteria:**
- Given CI, when `backend-tests.yml` and `gates.yml` run, then all pass: single head, drift, snapshot upgrade/downgrade, CI-2, CI-7, CI-8 with no baseline growth, CI-10, CI-11 and CI-12 with every new route probed and 0 leaks.
- Given the worker starts, when it imports `KIND_MODULES`, then `backfill.mentions` and the `suggested_mentions_v1` backfill are registered, and the next runner pass moves the row from `queued` to `running`/`done`.
- Given a Player, when any Mention route or `mention_count` is read, then no suggested Mention, no Shorthand/gm_notes-sourced Mention and no Mention of a hidden entry or Entity is reflected in any body or count.

## Design Notes

**Data safety (migration + backfill).**
- *Migration.* Before this story no route or Job wrote `entity_mentions` (no add-mention route existed; merge had no route). So production has no rows, and the dedupe `DELETE` is a no-op there. It exists only so `CREATE UNIQUE INDEX` can never fail at boot on a dev database. It deletes only *suggested* rows that have an older suggested twin; suggested rows carry no Canon. Re-running the upgrade is safe because the dedupe is idempotent and the index is created once by Alembic. The downgrade drops only the index.
- *Backfill.* It is idempotent: each step skips an (entry, Entity, narrative) pair that already has any Mention or a removed migration suggestion, and the partial unique index backs that up (a conflicting insert becomes `CanonChangeError("invalid")` inside the savepoint, which is caught and skipped).
- *Resumable.* Each step's Mentions, cursor and progress commit together (`run_cursor` / worker `_continue`). A crash rolls the step back and retries from the same cursor.
- *Re-run safe.* Running it again over a Campaign adds nothing. The runner never starts a second Job per Campaign (idempotency key), and the `data_backfills` row ends `done` and is never touched again.
- *Scope.* Campaigns created after the row are not backfilled (the runner's `created_before`). Only `kind = gm` entries are read and only the Narrative is matched. It never writes Visibility and never runs as system.

**Idempotency key.** The story's `backfill.mentions:{campaign_id}:{cursor}` describes a per-step key. The B2 contract (E0-Jobs.5) instead re-pushes one Job id per Campaign under the runner's `backfill:{name}:{campaign_id}`, so there is no per-step enqueue to key. `step_key()` documents the story's form for any future direct enqueue. The runner key is what actually dedupes.

**Why confirmed-only counts in `world_matching`.** The registry formula does not know about `confirmed`, so a suggested Narrative Mention of a Party entry and a Party Entity passes `scoped_select` for a Player. Counting it would let a GM-only suggestion change a Player's ranking or `mention_count`. The routes filter `confirmed` themselves for the same reason.

**Merge dedupe.** The partial unique index would otherwise make `merge` fail with `invalid` whenever both Entities have a suggestion for the same entry. Deleting the absorbed duplicate never widens anything: the survivor's own row and its floor are kept.

## Verification

**Commands** (from `src/backend`, with `PY=/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/wc5venv/bin/python`; never install anything globally or start a database here):
- `$PY -m compileall -q app tests migrations` -- expected: no errors
- `PYTHONPATH=. $PY -m importlinter.cli lint` or `PYTHONPATH=. <venv>/bin/lint-imports --no-cache` -- expected: all contracts kept
- `$PY ../../scripts/check_scoped_queries.py && $PY ../../scripts/check_table_owners.py` -- expected: exit 0
- `PYTHONPATH=. $PY -m pytest --noconftest -q tests/jobs/test_world_backfill.py -k "quote or registration"` -- expected: the pure tests pass (they must not need a DB)
- `alembic heads` (offline) -- expected: one head, the new revision
- GitHub CI on the draft PR -- expected: backend-tests, gates, frontend-ci and license-check green

**Results (local, 2026-11-21):**
- `compileall` -- no errors.
- `lint-imports --no-cache` -- 5 contracts kept, 0 broken.
- `check_scoped_queries.py` -- ok (no baseline growth); `check_table_owners.py` -- OK, 27 owned tables.
- Pure tests (`-k "quote or registration"`, with dummy `POSTGRES_PASSWORD`/`DATABASE_URL`/`SECRET_KEY` env
  because `app.core.config` needs them at import; no DB) -- 8 passed.
- `alembic heads` -- `eed202f2eead (head)`.
- Route order checked by import: `GET /mentions` is declared before `GET /{entity_id}`; 17 entity routes.
- DB tests (backfill, API, merge, matching, migration snapshot) and EV-4 were NOT run locally (no database on
  this Mac); they run in GitHub CI.

**Test isolation note.** Registering `suggested_mentions_v1` makes the real `data_backfills` row (queued in the
test DB) live for every runner pass. `tests/jobs/test_backfill.py`'s autouse fixture now parks feature backfill
rows (`done`), and `tests/jobs/test_world_backfill.py::mention_backfill` re-queues the row for its one test and
parks it afterwards.

## Spec Change Log

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 34 findings (33 from the review layers plus 1 from the first CI run): high 0, medium 3, low 23, false 8, maybe-false 0.
- findings:
  - **Blind Hunter**
    - `[low]` `reject` `run_backfills` in `tests/ev4/test_job_rows.py` does not park `suggested_mentions_v1`. That test monkeypatches `campaign_owners` to one Campaign, so the real backfill touches only its own fresh Campaign. `test_world_backfill` re-queues the row itself. CI passed (2726 passed).
    - `[low]` `reject` `select_next` reloads every gm entry on each step (O(n²)). It reads three columns; at 10k entries that is about 20 ms a step against a 120 s timeout. A SQL keyset rewrite is more than a direct correction.
    - `[low]` `patch` The docstring says `created_at::date` (session TZ) but the code uses the UTC date. Fixed: the `app/jobs/world.py` docstring now says "the UTC date of created_at".
    - `[medium]` `patch` Merge dedupe only matched a *suggested* survivor twin, so a survivor with a confirmed Mention kept a redundant suggestion (a later confirm would double-count). Fixed: the twin lookup in `_merge` matches any survivor Mention of the (entry, field). New test `test_merge_drops_an_absorbed_suggestion_the_survivor_has_confirmed`. The missing history row for the dropped duplicate matches the existing alias-dedupe pattern in `_merge`, so it is not changed.
    - `[low]` `patch` `_was_removed` only honoured migration-origin removals. Fixed by deleting the `origin` condition: any removed `narrative` Mention of the pair blocks a suggestion. New test `test_a_removed_manual_mention_also_blocks_a_suggestion`; a removed `shorthand` Mention does not block. The merged-Entity history part is a separate entry (EC #2).
    - `[low]` `reject` Confirm does not refuse a second confirmed Mention of the same pair. After the merge patch this is reachable only through E1's extraction proposals, which own their own dedupe. Adding a guard is more than a correction.
    - `[low]` `reject` `GET /{id}/mentions` has no upper bound on `page`. An out-of-range page returns an empty list. Python paging over one Entity's Mentions follows the E0-WorldCore.5 deferred-medium pattern.
    - `[low]` `reject` `sentence_quote` heuristics (abbreviations, no centring, closing quote marks). The quote always contains the sentence's match context and the GM sees the entry link; better heuristics add complexity.
    - `[low]` `patch` Untested behaviours. Added tests for: a Mention on a player entry gets the "Player journal" title; an entry-less (NULL `journal_id`) Mention sorts last for the GM and is hidden from the Player; `mention_count` drops after a remove; the list updates after confirm and remove. Merged-Entity 409 and member-preview reads stay untested (low): the code paths are shared with the deleted case and `ctx.role != GM`, which are tested.
    - `[low]` `reject` Weak test lines (`assert mira`; a fresh Job with payload `{}`). The meaningless assert was replaced by a real test (see above). The payload shape does not change `handle`: it reads only `cursor`/`done`, and `backfill` matters only to `_record_entry`, which the runner test covers.
    - `[low]` `patch` The `remove_mention` docstring omitted the 409. Fixed in `app/api/routes/entities.py`.
    - `[low]` `reject` Spec bookkeeping (untracked context file, a scratchpad path, status). Fixing it means editing this build's spec.
    - `[low]` `reject` `step_key` is dead code. It is kept on purpose to document the story's key form next to the deviation (Design Notes); it is harmless.
  - **Edge Case Hunter**
    - `[low]` `patch` A removed non-migration narrative Mention did not block. Same fix as Blind Hunter #5.
    - `[low]` `reject` A suggestion removed on an absorbed Entity is re-suggested for the survivor after a merge. This needs a backfill re-run after a merge; `suggested_mentions_v1` runs once at upgrade, before any merge route exists. Chasing the merge chain is more than a correction.
    - `[medium]` `patch` Survivor confirmed plus absorbed suggestion. Same root cause and fix as Blind Hunter #4.
    - `[false]` `reject` A match span longer than 300 characters truncates the surface. `match_names` spans are Entity names plus prefixes; nothing in `entity_types` allows a 300-character name in practice, and the quote is still bounded.
    - `[low]` `reject` "Mr. Mira" boundary loses context. Same as Blind Hunter #8.
    - `[false]` `reject` Claim: the long-sentence quote misses the surface. Only when `end - start > limit`, as in EC #4; for real names the window always contains `[start, end)` because `window <= start`.
    - `[low]` `reject` Claim: removal after a merge. Same as EC #2.
  - **Verification Gap**
    - `[low]` `patch` The player-journal `entry_title` was untested. Added `test_player_entry_titles_and_entryless_mentions`.
    - `[low]` `patch` The NULL-`journal_id` branch was untested. Same test; the Player-hidden part is asserted too.
    - `[low]` `patch` The `_was_removed` negative case was untested. Added the shorthand removal case, which still suggests.
    - `[low]` `reject` The migration dedupe runs on an empty table in the tests. Production has no `entity_mentions` rows before this revision (no writer existed); a seeded-twin migration test is more than a correction for a dev-only path.
  - **Intent Alignment** (descriptive)
    - `[low]` `reject` (a) The idempotency key is not `backfill.mentions:{campaign_id}:{cursor}`. The B2 runner contract (E0-Jobs.5, a dependency named by the story) re-pushes one Job id under `backfill:{name}:{cid}`, so a per-step key is never enqueued. This is documented in Design Notes and the PR.
    - `[false]` `reject` (b) "Upsert on conflict" is not an SQL `ON CONFLICT`. On conflict the observable effect is the story's: no duplicate, no failure. An `ON CONFLICT` would have to bypass `apply_change`, the only writer.
    - `[false]` `reject` (c) Crash and resume are not exercised. `tests/jobs/test_backfill.py::test_a_failed_step_rolls_back_and_retries_from_the_same_cursor` covers `run_cursor`'s rollback and resume, and the per-entry skip makes a retried entry add nothing (`test_rerun_adds_nothing`).
    - `[false]` `reject` (d) The probe file name differs. It is a separate module in the same package (auto-imported); `test_coverage.py` sees every route probed.
    - `[false]` `reject` (e) Players get no `origin`. The story's field list is in the GM clause; the Party schema carries no provenance (AD-13).
    - `[false]` `reject` (f) The named stats surfaces do not exist yet. Every count that exists is confirmed-only, and later epics read confirmed rows.
    - `[low]` `patch` (g) No re-read of the list after confirm or remove. Added to `test_remove_mention` and the new `test_remove_lowers_mention_count_and_confirm_updates_the_list`.
    - `[false]` `reject` (h) Scope additions. The merge dedupe and the confirmed-only counts follow directly from the story's index and its "only confirmed count" AC.
    - `[low]` `reject` (i) Only pure tests ran locally. CI then ran the whole suite (2726 passed); the one failure is the next row.
  - **CI**
    - `[medium]` `patch` `tests/access/test_write_rules.py::test_party_read_routes_are_safe_reads_with_no_hosted_ai` did not list the two new Party-read routes. Added them.

## Auto Run Result

Status: done. Draft PR #82; CI green on b2a9191 and later.

**Summary.**
- A `backfill.mentions` cursor Job (`app/jobs/world.py`) consumes `suggested_mentions_v1`. It runs one Job per Campaign as the Owner GM and handles one gm entry per step, in Session order. It runs `match_names` on the Narrative only and writes suggested Mentions through `apply_change(add_mention)`. The quote is the sentence of the first match, at most 300 characters.
- It never re-creates a removed pair and never adds a suggestion where a Mention already exists.
- Migration `eed202f2eead` adds the partial unique index `uq_entity_mentions_suggested`, after an idempotent dedupe that is a no-op in production.
- Four routes:
  - `GET /api/entities/{id}/mentions?confirmed=&page=` (20 per page, newest Session first)
  - `GET /api/entities/mentions?journal_id=`
  - `POST .../mentions/{mention_id}/confirm`
  - `DELETE .../mentions/{mention_id}`
- Non-GMs see only confirmed Mentions that the formula allows. `world_matching` counts are confirmed-only. Merge drops an absorbed suggestion when the survivor already has a Mention of the pair.

**Files** (under `src/backend/`):
- `app/jobs/world.py`: new; the kind, the backfill, `sentence_quote`, `suggest_mentions`, `handle`.
- `app/jobs/registry.py`: `KIND_MODULES`.
- `migrations/versions/eed202f2eead_suggested_mentions_unique.py`: new.
- `app/db/models/entity.py`: the index.
- `app/api/routes/entities.py`: the four routes.
- `app/schemas/entities.py`: the Mention extras and list schemas.
- `app/services/world_matching.py`: confirmed-only counts.
- `app/services/world_service.py`: merge dedupe, additive.
- Tests:
  - `tests/jobs/test_world_backfill.py` (new)
  - `tests/ev4/probes/entity_mentions.py` (new)
  - `tests/test_entities_api.py`
  - `tests/services/test_world_service.py`
  - `tests/services/test_world_matching.py`
  - `tests/migrations/test_upgrade_snapshot.py`
  - `tests/jobs/test_backfill.py` (parks feature backfill rows)
  - `tests/access/test_write_rules.py` (Party-read route list)

**Review.** 34 findings.
- 13 patch rows: the merge twin covers any Mention, removal blocking covers any origin, the docstrings, 6 test additions, and the CI route list.
- 21 rejected, with reasons in the triage log. Nothing deferred.

**Follow-up review recommended:** true. Two medium entries were patched: the merge twin and the CI route list. The unverified risk is the `_merge` change, which overlaps E0-WorldCore.9's merge wrapper; an independent look at the combined merge path after both land is worthwhile.

**Verification.**
- GitHub CI on b2a9191:
  - Backend tests: 2731 passed, 4 skipped.
  - Structural gates green (CI-2, CI-3, CI-7, CI-8, CI-10, CI-11, CI-14).
  - EV-4: probes=158, exemptions=11, pending=0, leaks=0.
  - Frontend CI and licences green.
- Local: compileall, lint-imports (5 kept), CI-8/CI-7 ok, 8 pure tests passed, one alembic head.

**Residual risks.**
- The `_merge` edit is shared with E0-WorldCore.9 (a merge conflict there needs the twin check kept).
- No on-save suggestion: new entries rely on E1 extraction.
- The story's per-step idempotency key is replaced by the B2 runner key (Design Notes).
- Sibling migrations from E0-WorldCore.6/9 may also revise `0f1c3b194a4b` → rebase `down_revision` at merge.

**Needs desktop verification:** none beyond CI (no new service, model or image).
