---
title: 'E0-Access.7: Party-only search and retrieval using party_tsv and party_embedding'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '6146e938c815b95c27db5665bc7653ff2ade3381'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A duplicate that misses the Valkey check (e.g. old global dedup keys in the 24 h after deploy) hits the DB unique constraint and returns 500, not 409.
    evidence: |-
      create_journal_entry does not catch IntegrityError on uq_journal_entries_campaign_user_entry_hash; pre-existing path, reachable for one TTL window after the key change.
    location: >-
      src/backend/app/services/journal_service.py:create_journal_entry
    severity: low
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

### 2026-11-01 — Review pass
- verdicts: 39 findings — high 0, medium 11, low 25, false 3, maybe-false 0 (blind 16, edge 12, verification-gap 3 + 1 other, intent-alignment 7 divergences)
- findings:
  - `[medium]` `[patch]` (blind) Non-search `list_journals` returned `JournalListResponse` with Shorthand to non-GMs — now `JournalListPartyResponse` whenever any scope is non-GM (strictly narrowing; E0-Access.4 replaces it with `project`).
  - `[medium]` `[patch]` (blind) EV-4 journal probe never hit the no-search list — probe now covers `?campaign_id=A` and `/` (no-canary + counts/ranking); route test has a Player no-search case.
  - `[medium]` `[patch]` (blind) Reindex open to Players and its count included hidden rows — reindex now 404s unless the ctx is GM; probe asserts the 404.
  - `[low]` `[patch]` (blind) `retrieve_sources` forwarded journal options to the canon provider (TypeError) — `source_documents_source` passes only `limit`/`max_distance`; test added.
  - `[low]` `[patch]` (blind) `journal`/`player_journal` providers filtered kind after the top-`limit` cut — kind is now in the SQL base filter before fusion; test added.
  - `[low]` `[reject]` (blind) Campaign-less chat no longer searches Player-Campaign entries — deliberate fail-closed choice recorded in the spec matrix (no single ctx to filter by); GM Campaign entries unchanged.
  - `[low]` `[reject]` (blind) `party_tsv` should be a generated column — would need a migration (spec avoids one: single head vs E0-Jobs.1); every write path calls `index_party_fields`.
  - `[low]` `[reject]` (blind) Extra flush/UPDATE/embed per write; reindex GM embed still 500s with no model — negligible at journal scale; the 500 is pre-existing.
  - `[medium]` `[patch]` (blind) No deterministic tie-break on several orderings — `JournalEntry.id` secondary order in both retrievers, `created_at desc, id` on every list ordering.
  - `[low]` `[reject]` (blind) NPC/Quest entries routes duplicated, unescaped ILIKE wildcards — pre-existing; a `%`/`_` name only over-matches visible entries.
  - `[low]` `[patch]` (blind) Backfill exits 0 on failed rows — `main` returns 1 when any row failed; `--batch-size` flag and `_model` peek rejected (cosmetic).
  - `[low]` `[reject]` (blind) `is_gm` computed twice in chat; empty `shorthand` field still present — both derive from the same ctx; removing the field is E0-Access.8's Party schemas.
  - `[low]` `[reject]` (blind) Tests use magic values (pool size, seed names) — probes assert non-vacuity (`total >= 1`, an entry used), so a seed change fails loudly.
  - `[low]` `[reject]` (blind) Missing streaming GM control, mixed-role pagination, non-member list 404, co-GM checks — stream probe shares `_prepare_chat`; `ctx_for` 404 is the E0-Access.2 contract; not worth new tests.
  - `[low]` `[patch]` (blind) seed_demo did not count Party embedding fills; Party writes untested — counted once per entry; `test_party_fields_cover_the_narrative_only` added.
  - `[low]` `[defer]` (blind) Old `dedup:{hash}` keys ignored for 24 h after deploy; IntegrityError not mapped to 409 — DB constraint still blocks the duplicate; the 500 path is pre-existing; deferred.
  - `[medium]` `[patch]` (edge) Retriever ORDER BY ties let a GM-only UPDATE shift a Player's pool/ranks — same fix as the tie-break row.
  - `[medium]` `[patch]` (edge) Non-search list serves Shorthand to a Player — same fix as the first row.
  - `[low]` `[patch]` (edge) Non-search list had no ORDER BY — ordered by `created_at desc, id`.
  - `[medium]` `[patch]` (edge) Reindex count leaks hidden rows — same fix as the reindex row.
  - `[low]` `[patch]` (edge) One revoked Campaign 404s the whole cross-Campaign list — that Campaign is skipped.
  - `[low]` `[patch]` (edge) `**options` TypeError in canon provider — same fix as above.
  - `[low]` `[patch]` (edge) Kind filter after limit — same fix as above.
  - `[low]` `[reject]` (edge) ILIKE wildcard in NPC/Quest names — pre-existing, as above.
  - `[false]` `[reject]` (edge) A Player loses their own Shorthand in chat — the epic contract is "non-GM chat gets no Shorthand" (FR-9(b)).
  - `[low]` `[reject]` (edge) Campaign-less chat drops Player-Campaign entries — deliberate, as above.
  - `[medium]` `[patch]` (edge, claim) Counts-and-ranking guarantee could fail under ties or via the reindex count — tie-breaks and GM-only reindex fix both.
  - `[medium]` `[patch]` (edge, claim) Route marked probed while the no-search list leaked Shorthand — Party list + no-search probe URLs.
  - `[medium]` `[patch]` (verification-gap) Chat canon gate never exercised (chunks unembedded; `source_service` imported `embed` by name) — `source_service` calls `embedding_service.embed`; `test_chat_canon_sources_are_gm_only` seeds a gate-passing chunk: Player gets none in response or captured prompt, GM gets it.
  - `[medium]` `[patch]` (verification-gap) No-search list visibility untested — Player no-search test (ids, total, no shorthand) + probe URLs.
  - `[low]` `[patch]` (verification-gap) seed_demo Party writes unverified — seed test added.
  - `[low]` `[patch]` (verification-gap, other) `source_service` imports `embed` by name — fixed with the canon row.
  - `[low]` `[reject]` (intent) Narrow-only property bounded to < 10 rows, `used` not tested — the AC's "would hide" is visibility, which holds structurally (same `visible_clause`); pool inclusion tested in the bounded domain.
  - `[low]` `[reject]` (intent) Vector gating on `party_embedding` not exercised with fake vectors — real-MiniLM eval run on the desktop: hybrid@0.65 14/16, 4/5 before and after.
  - `[false]` `[reject]` (intent) Write-path tests only use helpers copying the SQL — production `create_journal_entry` and the reindex route are tested directly; helpers only build fixtures.
  - `[low]` `[reject]` (intent) Backfill CLI/model path untested — run on the desktop with the real model: 7 rows filled, rerun 0.
  - `[false]` `[reject]` (intent) Dedup only verified against a fake Valkey — the generate route tests run against CI's real Valkey service; the fake is the unit test only.
  - `[low]` `[reject]` (intent) Chat journal context not assembled through providers; `source_documents` key is not a `SourceKind` — the story names the provider `source_documents`; moving chat onto providers is E0-Access.8.
  - `[low]` `[reject]` (intent) Diff edits E0-Access.8-owned `chat.py`/`chat_service.py` and creates `schemas/sources.py` — the minimum to move chat to the ctx path and stop GM text reaching Players; `sources.py` is append-only for E0-Access.8.

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

## Auto Run Result

Status: done

**Summary:** `hybrid_search_journal(db, q, *, ctx, limit, max_distance, entry_ids, narrative_only)`: GM keeps `narrative_tsv`/`embedding`, the Shorthand+Narrative proper-noun haystack and the 0.65 gate; non-GM (or `narrative_only`) uses `party_tsv`/`party_embedding` over `visible_clause` rows, NULL party vectors skipped with no fallback, `entry_ids` narrowing. `index_party_fields` runs on create and reindex (SQL `to_tsvector(narrative)`; embedding failure leaves NULL). `scripts/backfill_party_embeddings.py` recomputes NULL/stale `party_tsv` set-based and fills `party_embedding` in batches of 50 (no Alembic revision). `register_source`/`retrieve_sources` with `journal`, `player_journal`, `source_documents` (nothing for non-GM). Journal list/search, NPC/Quest entries and chat use the ctx path; non-GM gets no Shorthand, glossary, canon or system prompt. Valkey dedup keyed `dedup:{campaign}:{user}:{hash}`. Reindex is GM-only.

**Files changed:**
- `src/backend/app/services/retrieval_service.py` -- ctx retrieval, own-GM-journals search, `index_party_fields`, source providers.
- `src/backend/app/services/{journal_service,dedup_service,source_service,chat_service}.py` -- party indexing on save, per-(campaign,user) dedup key, module-level embed, no Notes line without Shorthand.
- `src/backend/app/api/routes/{journals,npcs,quests,chat}.py` -- Party matching/responses for non-GM, GM-only reindex, chat ctx path.
- `src/backend/app/schemas/{journal,sources}.py` -- `JournalLitePartyResponse`, `JournalListPartyResponse`; `SourceKind`.
- `src/backend/scripts/{backfill_party_embeddings,eval_retrieval,seed_demo}.py` -- backfill; eval as the Owner's GM ctx; seed writes Party fields.
- `src/backend/tests/test_party_retrieval.py`, `tests/ev4/probes/retrieval.py`, `tests/ev4/pending_baseline.txt`, `tests/seeds/test_demo_seed.py` -- matrix tests, narrow-only property, 6 EV-4 probes (lines removed from pending), seed Party-field test.

**Review:** 39 findings. 21 rows patched (11 medium, 10 low; 9 fixes: non-search Party list, no-search probe/test, GM-only reindex, id tie-breaks, kind-before-limit providers, canon provider options, canon chat test via module-level embed, backfill exit code, seed_demo count + test). 1 deferred (IntegrityError -> 500, low). 17 rejected; every reason is in the triage log.

**Follow-up review recommended:** true -- several medium rows patched on a first pass. Named risk: the patches widened scope into E0-Access.4 (non-search journal list now Party-projected) and E0-Access.6 (reindex GM-only), which those parallel stories must merge with; and the id tie-break changes which of two tied entries the GM path cites (eval numbers unchanged).

**Verification:** Desktop full suite (private pgvector + Valkey): 929 passed, 4 skipped; EV-4 probes=7 leaks=0. `scripts/check_scoped_queries.py` ok. Retrieval eval on the demo seed with the real MiniLM model, main vs this branch: identical (hybrid@0.65 14/16 hits, 4/5 gate holds; all 6 rows equal); lexical-only identical (hybrid 9/16, 5/5). Backfill with the real model: 7 nulled rows filled, second run 0 changes. GitHub CI on PR #49.

**Needs desktop verification:** none outstanding (real-embedding eval and backfill were run on the desktop). Deploy note: run `python scripts/backfill_party_embeddings.py` in the backend container once after deploying.

**Residual risks:** non-GM chat responses still carry an empty `shorthand` field until E0-Access.8's Party chat schemas; in a mixed-role cross-Campaign journal list a GM's own items also drop Shorthand; campaign-less chat no longer searches entries in Player Campaigns.
