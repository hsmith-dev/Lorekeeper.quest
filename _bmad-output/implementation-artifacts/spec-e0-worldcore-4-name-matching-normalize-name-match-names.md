---
title: 'E0-WorldCore.4: Name matching with normalize_name and match_names'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: '59140bd9aa4997426bac8dc601b20e11ee1d93f0'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-3-apply-change-history-and-revert.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Legacy npcs.py/quests.py routes still find Narratives with ilike '%name%', a second name matcher (AR-9).
    evidence: |-
      Pre-existing (api/routes/npcs.py:155, quests.py:155). E0-WorldCore.6 turns these routes into adapters over entities; settle there by routing name lookups through match_names.
    location: >-
      src/backend/app/api/routes/npcs.py:155
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** Features that find Entities in text (E1 extraction, E0-WorldCore.7 suggested Mentions, E4 lookup and STT `initial_prompt`, B4 search) have no shared matcher. E0-WorldCore.3 stores alias keys with a temporary private rule (`_alias_key`: collapse whitespace, casefold), so "Brother Aldric", "aldric" and "Áldric" are still treated as different names.

**Approach:** Add the only name matchers (AD-9, AR-9):
- `normalize_name(text)`: pure, in `app/domain/names.py`.
- `match_names(ctx, text, *, types=None)`: exact name and alias spans in a Narrative.
- `candidates(ctx, surface, *, type=None, limit=3)`: RapidFuzz `WRatio` shortlist.

All three are exported from `app.services.world_service`. The matchers read names and aliases only through `access.scoped_select`. `world_service`'s `_alias_key` is replaced by `normalize_name` everywhere.

## Boundaries & Constraints

**Always:**
- `normalize_name` does the following, and is idempotent:
  - NFKC, then casefold;
  - strips diacritics (NFD, drops combining marks, recomposes);
  - collapses whitespace;
  - drops leading tokens in `NAME_PREFIXES` = (`the`, `a`, `an`, `brother`, `sister`, `lord`, `lady`, `sir`, `captain`, `king`, `queen`), repeatedly, but never the last token ("The King" → "king").
  - The stored `alias` keeps its surface form. Only `normalized_alias` takes the key.
- Matching works on word tokens, so "Mira" never matches inside "Miranda".
  - A name matches a run of consecutive text tokens equal to its normalized tokens. Between two matched tokens there may only be whitespace (no blank line), hyphens, apostrophes or periods.
  - A match extends back over directly preceding prefix tokens, so the surface is "Brother Aldric".
  - Conflicts resolve longest match first (by character length, then leftmost), with no overlapping spans. Results are returned in text order. `surface == text[start:end]`, `score=1.0`, `exact=True`.
- Visibility:
  - Entities come from `scoped_select(Entity, ctx)`, minus `deleted_at` rows.
  - Aliases come from `scoped_select(EntityAlias, ctx)`. They are also dropped when the Entity's `aliases` field is not visible to ctx (`parent_field_audience` + `visible_to`).
  - Alias keys are recomputed from `alias` at read time, so stale stored keys never matter.
  - A merged Entity's names resolve to its survivor, following the chain with a cycle guard. This happens only when ctx sees the merged row and a live survivor. Otherwise they are dropped. A merged id is never returned.
- If one span matches several Entities, one is picked deterministically: a name match beats an alias match, then more visible Mentions, then the earliest `created_at`, then id.
- `candidates`:
  - normalizes the surface and scores each visible Entity by its best `fuzz.WRatio` over its normalized name and aliases (score/100 ∈ [0,1], only > 0);
  - sorts by score desc, then mention_count desc, then name;
  - returns at most `limit` (1 ≤ limit ≤ 100, otherwise ValueError) `NameCandidate(entity_id, name, type, matched, score, mention_count)`;
  - counts `mention_count` over Mentions visible to ctx.
- `types`/`type` filter by `EntityType`. Each call builds its index from ctx-scoped queries, with no cache.
- `rapidfuzz==3.14.6` is pinned in `requirements.txt` (one file for the web and worker images) and has a register line (MIT, `images: [backend]`).

**Never:**
- No routes, schemas for HTTP, migration, frontend, embedding shortlist (E1 builds on `candidates`), suggested-Mentions backfill (E0-WorldCore.7) or 7B adjudication.
- No raw `select` of registered tables outside `app/access/` (CI-8). No cache.
- Don't edit `epics.md`, `sprint-status.yaml`, `access/write.py`, `access/events.py` or stt code. Don't commit `epic-*-context.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normalize | "  Brother   Áldric ", "ALDRIC", "The King" | "aldric", "aldric", "king" | — |
| Exact name + alias | Aldric (alias "Old Smith"); "Brother Aldric met the old smith." | 2 NameMatch, surfaces "Brother Aldric", "the old smith" | — |
| Longest first | Entities "Mira" and "Mira Vale"; "Mira Vale and Mira" | "Mira Vale" (one span), then "Mira" | — |
| Word boundary | "Miranda" | no match | — |
| Player ctx | GM-only Entity; Party Entity with a GM-floored alias; Party Entity with `aliases` field hidden | only the Party Entity's name matches | — |
| Deleted / merged | deleted Entity; merged M → Party survivor S | deleted never; GM: M's name → S; Player: nothing from M | — |
| Two Campaigns | both have "Mira" | only ctx's Campaign's Mira | — |
| candidates | "Aldrik" | Aldric first, score ∈ (0,1], mention_count = visible Mentions | limit 0 → ValueError |
| Benchmark | 300 Entities, 600 aliases, 500 words | median ≤ 200 ms | — |

</intent-contract>

## Code Map

- `src/backend/app/services/world_service.py:183` `_alias_key`. Used at L538, 544, 561, 873-876, 1027, 1036. Replace it with `normalize_name`, delete the private rule, and re-export the matchers.
- `src/backend/app/db/models/entity.py` -- `Entity` (name, type, deleted_at, merged_into_id, created_at, field_visibility), `EntityAlias` (alias, normalized_alias, unique per Campaign+Entity+key), `EntityMention.entity_id`.
- `src/backend/app/access/registry.py:545` `scoped_select(model, ctx)`, `:953` `parent_field_audience(Entity, e, "aliases")`. `app/access/audience.py:138` `visible_to`. Entity `gm_when` makes deleted/merged GM-only.
- `src/backend/app/domain/` -- pure. The contract forbids other app packages, but stdlib is fine.
- `src/backend/tests/services/test_world_service.py` -- `gm`/`_player`/`_create` fixtures on `ev4`. L370 expects `("The Grey","the grey")`, which becomes `"grey"`.
- `src/backend/scripts/eval_benchmarks.py:67` `ROWS` (+`tests/test_eval_benchmarks.py` counts 12, 9 NFR-6). `docs/benchmarks.json`, `docs/BENCHMARKS.md` (generated region).
- `licenses/register.yaml` -- one flow-style line per python package.
- `src/backend/requirements.txt`, `.github/workflows/backend-tests.yml` (installs requirements).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/domain/names.py` -- `NAME_PREFIXES`, `fold`, `normalize_name`, `name_tokens` (word tokens with spans). This is the pure part.
- `src/backend/app/services/world_matching.py` -- `NameMatch`, `NameCandidate`, `match_names`, `candidates`, plus a ctx-scoped index builder (Entities, aliases, merged → survivor, mention counts).
- `src/backend/app/services/world_service.py` -- import and re-export the four matchers, and use `normalize_name` for every alias key.
- `src/backend/requirements.txt`, `licenses/register.yaml` -- pin rapidfuzz 3.14.6 and add its MIT line.
- `src/backend/scripts/eval_benchmarks.py`, `tests/test_eval_benchmarks.py`, `docs/benchmarks.json`, `docs/BENCHMARKS.md` -- add the `match_names` row (FR-14, target ≤ 200 ms CPU, GPU n/a, E0-WorldCore) and record the desktop measurement.
- `src/backend/tests/domain/test_names.py` -- normalize rules, idempotence, tokens.
- `src/backend/tests/services/test_world_matching.py` -- the matrix, visibility (Player, share, preview), two Campaigns, merged/deleted, ambiguity, candidates, the benchmark test (asserting ≤ 200 ms), and a guard that only `world_matching.py` imports rapidfuzz.
- `src/backend/tests/services/test_world_service.py` -- update the alias-key expectations.

**Acceptance Criteria:**
- Given CI, when backend-tests, gates and license-check run, then all pass with no regression.
- Given a Player ctx, when it calls `match_names` or `candidates`, then no GM-only Entity, alias or merged id is returned (an EV-4 style canary test).

## Spec Change Log

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 30 findings — high 0, medium 0, low 19, false 10, maybe-false 1 (blind 10, intent 7, edge 11, vgap 2)
- findings:
  - `[low]` `[reject]` (blind) No backfill of stored `normalized_alias` for old-rule rows. No rows can exist yet: the F3 copy writes no aliases and no route writes them before E0-WorldCore.5, and every comparison recomputes from `alias`.
  - `[low]` `[reject]` (blind) The dedup key (keeps punctuation) differs from the match key (word tokens), so "Mira-Vale" and "Mira Vale" are two alias rows. Both match the same spans for the same Entity, so there is no user-visible harm. Unifying them would change `normalize_name` beyond the story's rule list.
  - `[false]` `[reject]` (blind) A merged Entity's name skips the survivor's `aliases` gate. Merged rows are GM-only (registry `gm_when`), so only a GM ctx reaches this path, and a GM sees every field. A Player or preview ctx never sees the merged row.
  - `[low]` `[reject]` (blind) "Mira. Vale" joins across a sentence. This is the spec's separator rule, which keeps "St. Cuthbert" matching. It needs a multi-token name split exactly at a sentence boundary, and a fix would add a capitalisation heuristic.
  - `[low]` `[reject]` (blind) A name or alias that is only a prefix ("The", "Lady") matches every such word. This follows directly from the story's never-drop-last-token rule. It is GM-authored data, and a guard adds branches.
  - `[low]` `[reject]` (blind) Prefix extension pulls lowercase articles into surfaces ("the old smith"). This is the spec's span rule (I/O matrix row 2) and is cosmetic for highlighting.
  - `[low]` `[reject]` (blind) `candidates` has no score cutoff and `min(score, 1.0)` is dead. The story sets no cutoff, and E1 takes the RapidFuzz top 20 and re-ranks them by embeddings. The dead clamp is harmless.
  - `[low]` `[reject]` (blind) `populate_existing` could overwrite unflushed changes. Autoflush (the default) flushes them before the query. Only an explicit `no_autoflush` block is exposed, and no caller exists.
  - `[low]` `[reject]` (blind) The benchmark is a hard 200 ms assert, GM ctx only, and was recorded by hand. The AC says "≤ 200 ms on the test runner". The measured median is 13.3 ms (15x headroom), and the Player path runs the same three queries.
  - `[low]` `[patch]` (blind) Weak tests: the type filter is trivially true, and `quiet.id != loud.id` is a no-op. The location-vs-character filter test was added and the no-op assert removed.
  - `[false]` `[reject]` (intent) `match_names`/`candidates` take `db` first, unlike the story. The functions need a session, and this follows the `apply_change(db, ctx, ...)` convention. The PR flags it for E1, B4, B5 and E0-WorldCore.7.
  - `[low]` `[reject]` (intent) Stored data is not migrated (D2). Same as blind row 1.
  - `[maybe-false]` `[defer]` (intent) Legacy `npcs.py`/`quests.py` routes still find Narratives with `ilike '%name%'` (AR-9). This predates this story, and E0-WorldCore.6 turns those routes into adapters. Settle it there. Unverified medium.
  - `[false]` `[reject]` (intent) Never dropping the last token and extending spans over prefixes diverge from the story. Both are readings the story allows ("The King" must stay matchable; "Brother Aldric" is the story's own example), and both are pinned in the spec.
  - `[false]` `[reject]` (intent) The merged rule is stricter than the story. AD-9 binds it ("Resolvers follow it only for a ctx that could see the merged Entity").
  - `[false]` `[reject]` (intent) `score > 0` and limit 1..100 go beyond the story. A score of 0 is no candidate, and the bounds only refuse misuse.
  - `[false]` `[reject]` (intent) Tests run at the service surface only. The story adds no route, and the service is the outermost surface it names.
  - `[low]` `[reject]` (edge) An NFKC fold that expands a token ("½") splits name tokens but not text tokens. Names with such characters are negligible, and the fix adds a re-split path.
  - `[low]` `[reject]` (edge) A one-letter or prefix-only alias key. Same as blind row 5.
  - `[low]` `[reject]` (edge) A period plus space crosses a sentence. Same as blind row 4.
  - `[low]` `[reject]` (edge) U+2028/U+2029/\f/\v paragraph breaks are not treated as blank lines. Browser textareas submit `\n`/`\r\n` (both handled), so these characters are not met in practice.
  - `[low]` `[reject]` (edge) A prefix-extended short name can beat a longer name ("Sir Captain Ash Bell" vs "Bell Cox Dunn"). This needs overlapping multi-token names plus stacked honorifics, and the fix changes the ranking key.
  - `[false]` `[reject]` (edge) A merged own-name bypasses the survivor's `aliases` field. Same refutation as blind row 3.
  - `[false]` `[reject]` (edge) An intermediate merged Entity's hidden `aliases` field. Merged rows are GM-only, and a GM sees every field.
  - `[false]` `[reject]` (edge) Old-rule duplicate rows ("The Grey" + "Grey") make remove/revert pick an arbitrary row. No old-rule alias rows exist (blind row 1).
  - `[low]` `[reject]` (edge) A non-CampaignContext with empty text returns [] instead of raising. Callers are typed, and nothing is read or leaked.
  - `[low]` `[reject]` (edge, claim) `normalized_alias` is not backfilled. Same as blind row 1.
  - `[false]` `[reject]` (edge, claim) The signature takes db first. Same as intent row 1.
  - `[low]` `[patch]` (vgap) No merge test tells the new key from the old (prefix-only differences, `normalized_alias` after a move). `test_merge_dedupes_by_normalize_name` was added.
  - `[low]` `[patch]` (vgap) The U+2019 apostrophe and U+2010/U+2011 hyphen separators are untested. "O’Brien" and "Jean‐Luc" cases were added.

## Design Notes

- "Longest match first" is read as the overlap rule, as in Aho-Corasick leftmost-longest. Results are returned in text order, because E0-WorldCore.7 quotes "the sentence holding the first match".
- Dropping prefixes changes alias identity: "Brother Aldric" and "Aldric" share the key `aldric`, so adding the second alias is an idempotent repeat. No alias rows exist in production yet: the F3 migration copied none and no route writes them before E0-WorldCore.5. That is why no data migration is needed, and read-time recomputation covers any stray row.

## Verification

**Commands:**
- `python scripts/check_scoped_queries.py && python scripts/check_table_owners.py` -- expected: exit 0
- `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/wc4-test.sh -q [pytest paths]` -- desktop pytest in `lorekeeper-backend-test` (with rapidfuzz installed) against private containers `wc4-pg`/`wc4-valkey`. Expected: all pass.
- `lint-imports` (desktop image) -- expected: contracts kept
- GitHub CI on the draft PR -- expected: green

## Auto Run Result

Status: done

**Summary.** The only name matchers (AD-9, AR-9) are in place:
- `normalize_name` and `NAME_PREFIXES` live in `app/domain/names.py`, which is pure.
- `match_names(db, ctx, text, *, types=None)` and `candidates(db, ctx, surface, *, type=None, limit=3)` live in `app/services/world_matching.py`.
- `app.services.world_service` re-exports all of them.

What the matchers do:
- They read only through `scoped_select` plus the Entity's `aliases` field Audience, and build the index per call with no cache.
- A merged Entity resolves to its survivor only when the ctx can see it. Deleted Entities never match.
- `candidates` ranks by RapidFuzz `WRatio` and adds visible Mention counts.

Other changes:
- The temporary `_alias_key` rule from E0-WorldCore.3 is gone. Every alias key in `world_service` (add, remove, merge, revert) is now `normalize_name`, recomputed from the surface form, and a merge rewrites a moved alias's stored key.
- `rapidfuzz==3.14.6` is pinned in `requirements.txt` (one file for the web and worker images) and has an MIT line in the register.
- There is a new benchmark row `match_names` (FR-14, ≤ 200 ms). On the desktop test image, 300 Entities, 600 aliases and a 500-word Narrative take 13.3 ms median (n=7).

**Signature note.** `match_names` and `candidates` take `db` first. That differs from the epic text (`match_names(ctx, text)`). E1, B4, B5 and E0-WorldCore.7 must call the db-first form.

**Files changed**
- `src/backend/app/domain/names.py` (new) -- `normalize_name`, `fold`, `name_tokens`, `key_tokens`, `NAME_PREFIXES`.
- `src/backend/app/services/world_matching.py` (new) -- `NameMatch`, `NameCandidate`, `match_names`, `candidates`.
- `src/backend/app/services/world_service.py` -- `_alias_key` replaced by `normalize_name`, matchers re-exported.
- `src/backend/requirements.txt`, `licenses/register.yaml` -- the rapidfuzz pin and its licence line.
- `src/backend/scripts/eval_benchmarks.py`, `docs/benchmarks.json`, `docs/BENCHMARKS.md`, `src/backend/tests/test_eval_benchmarks.py` -- the FR-14 row and its measurement.
- `src/backend/tests/domain/test_names.py`, `src/backend/tests/services/test_world_matching.py` (new), `src/backend/tests/services/test_world_service.py` -- tests.

**Review findings.** 30 findings: high 0, medium 0, low 19, false 10, maybe-false 1.
- Patched 3, all low and all test gaps: merge dedupe by the new key, Unicode separators, and a real type-filter test.
- Deferred 1: the legacy `ilike` name matching in `npcs.py`/`quests.py` goes to E0-WorldCore.6.
- Rejected 26. Each one has its reason in the triage log: old-key backfill (no rows exist), punctuation key vs token key, sentence-crossing periods, prefix-only names, article surfaces, candidate cutoff, populate_existing, the benchmark assert, NFKC expansion, Unicode paragraph separators, the prefix-extension ranking, the ctx type check order, the db-first signature, and the merged-visibility claims, which are false because merged rows are GM-only.

**Follow-up review recommendation: false.** Only three low test-only patches were made, with 0 high and 0 medium.

**Verification**
- Full backend suite on the desktop (`wc4-test.sh`, private `wc4-pg`/`wc4-valkey`): 2191 passed, 4 skipped, EV-4 leaks 0. After the review patches, `test_world_matching.py` plus `test_world_service.py` gave 98 passed.
- `check_scoped_queries.py` ok. `check_table_owners.py` ok. `lint-imports` contracts kept.
- GitHub CI on the draft PR is the final gate.

**Needs desktop verification:** none. All tests ran on the desktop, and there is no GPU or compose work.

**Residual risks**
- `aliases` is not in `world_service.HIDEABLE_FIELDS`, so `set_visibility` cannot hide the aliases field yet. The matcher already honours `field_visibility["aliases"]`. E0-WorldCore.5 must make the field hideable and hide alias rows.
- Matching rules that are deliberate but debatable:
  - A period plus a space may join the tokens of one name ("St. Cuthbert").
  - Prefix-only names match every such word.
  - Spans extend over lowercase articles.
