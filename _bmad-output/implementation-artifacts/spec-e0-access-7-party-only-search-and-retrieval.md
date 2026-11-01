---
title: 'E0-Access.7: Party-only search and retrieval using party_tsv and party_embedding'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '6146e938c815b95c27db5665bc7653ff2ade3381'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Keyword search, chat retrieval and the entries-for-NPC/Quest lists match and rank on `narrative_tsv`/`embedding`, which include the GM's Shorthand, and filter only by Campaign. So a Shorthand-only word changes what a Player finds and in what order, and GM-only text reaches a Player's chat prompt, sources and trace. Nothing writes `party_tsv`/`party_embedding` after migration `c95acb56c595`, and the Valkey duplicate check keys `entry_hash` globally while the DB is unique per (campaign, user, hash).

**Approach:** Make `retrieval_service.hybrid_search_journal` take a `CampaignContext` and pick `party_tsv`/`party_embedding` plus `visible_clause` for non-GM (or `narrative_only=True`), keep the GM path byte-for-byte; add `entry_ids`, `register_source` providers (`journal`, `player_journal`, `source_documents`), and `index_party_fields` called from every journal write/reindex; add an idempotent backfill script for both party columns; switch the three search routes and chat to the ctx path; key the dedup check per (campaign, user, hash).

## Boundaries & Constraints

**Always:** GM ctx keeps today's columns, Campaign filter, proper-noun haystack (shorthand + narrative) and the 0.65 gate. Non-GM never touches `narrative_tsv`, `embedding` or `shorthand` for matching, ranking, gating or output, and vector search skips NULL `party_embedding` (no fallback). `narrative_only` and `entry_ids` only narrow. Embedding failure leaves `party_embedding` NULL (a stale vector is cleared) and never blocks a save. `party_tsv` is computed in SQL from the stored `narrative` (`to_tsvector('english', narrative)`) in the same transaction as the write. EV-4 probes for every route touched; GM retrieval eval unchanged.

**Never:** a new Alembic revision (both party columns already exist; backfill is the script, AD-18); `access.project`/Party schemas for non-search responses, the uniform-404 work or route migration to `require_campaign` (E0-Access.4/.5); `ChatPartyResponse`/`SourceRef`, stored-message refs, archived sessions (E0-Access.8 — chat here only switches retrieval to the ctx path and stops GM-only text reaching a non-GM prompt/response); moving `index_party_fields` into a `reindex_entry` or a reembed Job (E0-Journal); E0-Jobs.1, E0-Platform.5, QA.9a/9b; editing `sprint-status.yaml`, `epics.md`, the desktop-verification queue.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Shorthand-only word | Player ctx, query word only in an entry's shorthand | entry not matched; result list identical before/after editing shorthand | — |
| Same, GM | GM ctx | entry matched via `narrative_tsv` (today's behaviour) | — |
| Visibility | Player p; entries `party`, `private` by p, `private` by q, `gm`, `party` kind=player | first, second, fifth are candidates; others never appear | — |
| No party vector | Player; row with `embedding` set, `party_embedding` NULL | not a vector candidate (lexical only) | — |
| `entry_ids` | `{a}` / `set()` | only a (if visible) / nothing | — |
| `narrative_only=True` | GM ctx | party columns, narrative-only haystack; result ids ⊆ the call without it | — |
| Write | create / reindex | `party_tsv` = narrative tsvector; `party_embedding` = embed(narrative) | embed raises → NULL, save succeeds |
| Backfill | rows with NULL/stale `party_tsv`, NULL `party_embedding` | filled in batches of 50; second run changes nothing | embed failure → row left NULL, run continues, reported |
| Dedup | same hash, other Campaign or other author | not a duplicate (no 409) | same (campaign, user, hash) → 409 |
| Canon for non-GM | Player chat | `source_documents` provider returns nothing | — |
| No-campaign chat | user with GM and Player Campaigns | only the user's own entries in Campaigns where they are GM | — |

</intent-contract>

## Code Map

- `src/backend/app/services/retrieval_service.py` -- `hybrid_search_journal(db, q, *, campaign_id, user_id, ...)`: vector block (`JournalEntry.embedding`), lexical block (`narrative_tsv`, proper-noun haystack `f"{shorthand} {narrative}"` ~L162), RRF fuse. Refactor into one `_search(db, q, base_filter, party, ...)`.
- `src/backend/app/services/embedding_service.py` -- `embed()` (sync; raises RuntimeError when no model, which is the test default — tests monkeypatch it with `app.clients.fakes.fake_vector`). Call it as `embedding_service.embed` so patches apply.
- `src/backend/app/services/journal_service.py:68-131` -- `create_journal_entry`: flush, tags, raw `narrative_tsv` UPDATE, `embedding`, commit, `store_hash(entry_hash)`.
- `src/backend/app/api/routes/journals.py` -- `generate_journal` (`check_hash`, L69), `list_journals` (search on `narrative_tsv`, cross-Campaign via `accessible_campaign_ids`), `reindex_journal_embeddings` (~L305).
- `src/backend/app/api/routes/npcs.py:94`, `quests.py` (same shape) -- `/{id}/entries` ILIKE on shorthand OR narrative, `list[JournalLiteResponse]`.
- `src/backend/app/api/routes/chat.py:_prepare_chat` -- `hybrid_search_journal(campaign_id=, user_id=)`, candidates/sources carry `shorthand`, `journal_context` carries shorthand, `retrieve_canon_context`, `get_glossary`, `retrieval_debug().system_prompt`.
- `src/backend/app/services/chat_service.py:build_chat_messages` -- prints `Notes: {j['shorthand']}` per journal_context item.
- `src/backend/app/services/source_service.py:retrieve_canon_context` -- canon provider body (no ctx today).
- `src/backend/app/services/dedup_service.py` -- `dedup:{hash}` keys.
- `src/backend/app/access/` -- `ctx_for`, `role_map`/`RoleMap`, `scoped_select_multi`, `visible_clause(JournalEntry, ctx)` (registry: `stored(kind_field="kind", gm_fields=("shorthand",))`), `GM`. Read-only for this story.
- `src/backend/app/schemas/journal.py` -- `JournalResponse`, `JournalListResponse`, `JournalLiteResponse`. Frontend `JournalCard` reads `entry.tags.length`, so Party list items keep `tags`.
- `src/backend/app/schemas/sources.py` -- does not exist; E0-Access.8 extends it (append-only).
- `src/backend/scripts/eval_retrieval.py:hybrid` -- calls with `campaign_id=, user_id=uuid4()`; `CampaignData.campaign.user_id` is the owner. `scripts/seed_demo.py:~336` writes entries without party columns.
- `src/backend/tests/ev4/` -- `families.assert_counts_and_ranking_unchanged`, `assert_captured_context_clean` (`llm_provider.capture()`), `assert_no_canary`; `fixtures.EV4` actors and `seeds/ev4_canary.json` (canaries in shorthand, glossary, source docs, NPC/Quest notes; NPC "Barnaby", Quest "Find the missing caravan"); `pending_baseline.txt` (shrink-only; delete probed lines); probes in `tests/ev4/probes/<feature>.py` with `@ev4_probe`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/sources.py` -- new: `SourceKind` StrEnum (`journal, player_journal, canon_note, entity_field, live_segment, recap`) only.
- `src/backend/app/services/retrieval_service.py` -- ctx signature `hybrid_search_journal(db, query_text, *, ctx, limit=3, max_distance=RAG_RELEVANCE_MAX_DISTANCE, entry_ids=None, narrative_only=False)`; `hybrid_search_own_journals(db, q, *, roles, ...)` for campaign-less chat; `index_party_fields(db, entry)`; `register_source`/`retrieve_sources` with `journal`, `player_journal`, `source_documents` registered.
- `src/backend/app/services/journal_service.py` -- call `index_party_fields` before commit; `store_hash(campaign_id, user_id, hash)`.
- `src/backend/app/services/dedup_service.py` -- `check_hash`/`store_hash(campaign_id, user_id, entry_hash)`, key `dedup:{campaign_id}:{user_id}:{hash}`.
- `src/backend/app/schemas/journal.py` -- add `JournalLitePartyResponse` (id, campaign_id, narrative, session_date, tags, created_at; no shorthand) and `JournalListPartyResponse`.
- `src/backend/app/api/routes/journals.py` -- dedup args; `list_journals`: ctx per Campaign (`ctx_for`/`role_map`), non-GM rows filtered by `visible_clause` and searched/ranked on `party_tsv`; a search with any non-GM scope returns Party items; reindex sets party fields.
- `src/backend/app/api/routes/npcs.py`, `quests.py` -- `/entries`: non-GM matches `narrative ILIKE` + `visible_clause`, returns `JournalLitePartyResponse`.
- `src/backend/app/api/routes/chat.py` -- build ctx with `ctx_for`; retrieval via ctx (or `hybrid_search_own_journals`); canon via `retrieve_sources(kinds=[source_documents])`; non-GM: no shorthand in context/sources/candidates, no glossary, `system_prompt=None`.
- `src/backend/app/services/chat_service.py` -- `build_chat_messages` omits the Notes line when an item has no `shorthand`.
- `src/backend/scripts/backfill_party_embeddings.py` -- new: set-based `party_tsv` recompute (NULL or stale), then `party_embedding` in batches of 50 `WHERE party_embedding IS NULL`, commit per batch, `--dry-run`, `--database-url`, counts printed.
- `src/backend/scripts/eval_retrieval.py`, `scripts/seed_demo.py` -- GM ctx via `ctx_for(owner)`; seed writes party columns.
- `src/backend/tests/test_party_retrieval.py` -- matrix rows above, write paths, backfill idempotency, dedup, providers, hypothesis narrow-only property (`narrative_only`, `entry_ids`).
- `src/backend/tests/ev4/probes/retrieval.py` + `pending_baseline.txt` -- probes for `GET /api/journals/` (search), `GET /api/npcs/{npc_id}/entries`, `GET /api/quests/{quest_id}/entries`, `POST /api/chat/`, `POST /api/chat/stream`, `POST /api/journals/reindex`; delete those lines.
- `src/backend/tests/test_eval_common.py` -- adjust only if the eval call shape forces it.

**Acceptance Criteria:**
- Given a Player in Campaign A, when they search, ask the Chronicler (blocking and streaming) or list NPC/Quest entries, then no GM-only canary (Shorthand, glossary, source docs, GM-only/private-other entries) appears in the response or in any captured LLM call, and a GM-only change (Shorthand edit, GM-only entry) leaves their results, counts and order unchanged.
- Given the GM of Campaign A, when they chat, then the captured system prompt still holds Shorthand and glossary (positive control) and the eval scaffold's hybrid@0.65 numbers are unchanged with fake embeddings.
- Given CI, when backend-tests and gates run, then all pass with no regression.

## Spec Change Log

## Review Triage Log

## Design Notes

Why no migration: the columns exist and no release ships between E0-Access.1 and .13 (release unit), so the backfill script run once after deploy covers rows written since `c95acb56c595`; avoiding a revision also keeps a single head against E0-Jobs.1.

Search for a non-GM, per Campaign: `scope AND visible_clause(JournalEntry, ctx) AND party_tsv @@ q`, ranked by `ts_rank(party_tsv, q)`. Cross-Campaign list: `or_(and_(campaign IN gm_ids, narrative_tsv @@ q), and_(campaign IN player_ids, visible(player), party_tsv @@ q))` with rank on `case(gm → narrative_tsv, else party_tsv)`.

```python
party = narrative_only or ctx.role != GM
tsv, vec = (JournalEntry.party_tsv, JournalEntry.party_embedding) if party else (JournalEntry.narrative_tsv, JournalEntry.embedding)
base = and_(JournalEntry.campaign_id == ctx.campaign_id, visible_clause(JournalEntry, ctx))
if entry_ids is not None: base = and_(base, JournalEntry.id.in_(entry_ids) if entry_ids else false())
haystack = entry.narrative if party else f"{entry.shorthand} {entry.narrative}"
```

Providers: `async fn(db, query_text, *, ctx) -> Any`, keyed by `SourceKind` or the provider name `"source_documents"`; `journal`/`player_journal` return the `RetrievedEntry` list filtered by entry kind; `source_documents` returns `(None, [])` to non-GM.

## Verification

**Commands:**
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: backend-tests, gates, frontend-ci, licence checks green.
- desktop: builder-brief backend pytest command on `tests/test_party_retrieval.py tests/ev4 tests/test_eval_common.py tests/test_journals.py tests/test_share.py` -- expected: pass.
- desktop: `python scripts/eval_retrieval.py --embeddings fake` and with the real MiniLM model, before (main) and after -- expected: identical hybrid@0.65 row.
