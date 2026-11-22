---
title: 'E0-WorldCore.9: Merge two Entities'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: '9b0f01a437d70660905892cede406e07943553c9'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      A Player's entity_field citation of a merged-away Entity is dropped even when both sources were Party.
    evidence: |-
      access.resolve_sources filters by scoped visibility before the resolver; the absorbed row is GM via gm_when.
    location: >-
      src/backend/app/access/sources.py:228
    severity: medium
  - summary: >-
      Only GET /{id} and citations redirect an absorbed id; other {entity_id} routes use the absorbed row or answer merged.
    evidence: |-
      Intent "uniformly for GMs" may cover every id-taking route; needs an owner decision.
    severity: medium (unverified)
  - summary: >-
      Concurrent merges whose pair and ENTITY_REF holder sets overlap can deadlock (unmapped 500).
    evidence: |-
      _merge_work locks holders FOR UPDATE after the sorted pair lock.
    location: >-
      src/backend/app/services/world_service.py:_merge_work
    severity: medium (unverified)
  - summary: >-
      GM has no non-following read of an absorbed record; absorbed rows in survivor history cannot be reverted there.
    evidence: |-
      GET /{absorbed} redirects; revert route filters entity_id == path id. UI work for E0-WorldCore.10/11.
    severity: medium
  - summary: >-
      Merge undo record is unbounded and returned in GM history; superseded/force for non-alias kinds untested.
    evidence: |-
      new_value.undo holds every moved id and full dropped edges.
    severity: low
---

<intent-contract>

## Intent

**Problem:** A GM cannot merge a duplicate Entity ("Brother Aldric") into the real one. `world_service` has only the `op=merge` primitive (`_merge`). It has no GM wrapper, preview, API route, revert, or old-id redirect. It also leaks: aliases the absorbed Entity hid with `field_visibility.aliases` move unfloored onto a Party survivor, and ENTITY_REF attributes that point at the absorbed Entity are never repointed.

**Approach:** Add `world_service.merge_entities(db, ctx, survivor_id, absorbed_id, *, preview=False)` (alias `merge`). It builds `ctx.as_system("merge")` and runs one `apply_change(op=merge)`, or with `preview=True` a read-only plan. The merge row records an undo payload so that `revert_change` can un-merge. `POST /api/entities/{id}/merge` sits on top. An access-layer helper resolves a merged-away id to its survivor (any GM; for a non-GM, only an id the Party could see before the merge). The GET route and the `entity_field` citation resolver use it.

## Boundaries & Constraints

**Always:**
- Every Canon write goes through `apply_change` / `revert_change`. The only literal `visibility_floor` assignment stays in `apply_change`, so CI-8 needs no new allowance.
- The merge never widens what the Party saw of either source.
  - Each moved alias, Mention and edge gets a floor. For aliases it is the stricter of the absorbed Entity's `visibility` and its `field_visibility.aliases`. Mentions and edges use the absorbed Entity's `visibility`. An existing restrictive floor is kept.
  - The survivor's `visibility` and `field_visibility` are not changed.
  - The absorbed Entity's field values (description, status, attributes, gm_notes) are not copied.
  - The merge row and its revert row have field NULL, so they are GM-only.
- An ENTITY_REF attribute of another live Entity X that names the absorbed Entity is repointed to the survivor only when that cannot widen what the Party sees: the absorbed Entity was `party` and not deleted, or the survivor is not `party`. Otherwise the value is left on the absorbed id, and for a GM it redirects at read time. X is marked stale. No ref that would point X at itself is written.
- History stays on the absorbed Entity. `GET /{survivor}/history` also selects the rows of Entities merged into it, recursively, through `scoped_select`. A Player never sees them, because the absorbed Entity is GM via `gm_when`. Party totals don't move.
- Rows are locked in sorted-id order, so concurrent A→B and B→A merges cannot deadlock.
- Merge is revertible (orchestrator override of the story's "not revertible" line). A revert of a merge:
  - restores `merged_into_id = NULL`;
  - moves the moved aliases, Mentions, edges and steps back, with the floors they had before;
  - re-creates the deleted duplicate aliases and self-loop edges with their ids and values;
  - deletes the added name alias;
  - puts the repointed attribute refs back;
  - marks the survivor, the absorbed Entity and each X stale.
  A moved row that is gone or no longer on the survivor, or a ref no longer equal to the survivor id, is `superseded` unless `force` (force skips it). Reverting a merge whose survivor was merged or deleted since then is `merged` / `deleted`.
- In the route, a non-GM gets the uniform 404 for an absorbed id unless the absorbed row was stored `party`, was not deleted, and the survivor is visible to it. The response is then byte-identical to `GET /{survivor}`.

**Never:** no new migration; no change to `HIDEABLE_FIELDS`, the registry or CI-8 allowlists; no baseline lines; no `created_at`/`updated_at` in Party schemas; no edits to `sprint-status.yaml`/`epics.md`; no frontend (E0-WorldCore.10 owns the Merge… UI); no legacy npc/quest link resolution (E0-WorldCore.6). Edits to `world_service.py` and `entities.py` are additive. The new access helper is its own module.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Merge | GM, same type and Campaign | 200 `{downgrades, moved_counts, warning}`; absorbed `merged_into_id` = survivor; its aliases, Mentions and edges on the survivor; absorbed name is an alias | — |
| Preview | `preview: true` | Same result plus `aliases`, `mention_count`, `relationships`; history row count unchanged | — |
| GM-only into Party | absorbed `gm`, survivor `party` | `downgrades` non-empty, `warning = "party_with_gm_only"`; Player sees none of the moved aliases, Mentions or edges | — |
| Hidden aliases field | absorbed `party`, `field_visibility.aliases = gm` | moved aliases floored `gm`; Player can't see them | — |
| Attribute ref | Item X `holder_entity_id` = absorbed | repointed to survivor when safe, else unchanged | — |
| Type mismatch / self | different types, or absorbed = survivor | 422 `invalid` | nothing written |
| Other Campaign / merged / deleted / missing absorbed | — | 404 | nothing written |
| Player calls merge | any | 404, like a missing Entity | nothing written |
| Revert | GM reverts the merge row | absorbed live again; rows back with their old floors; refs back | `superseded` 409 if touched, unless `force` |
| Old id, GM | `GET /{absorbed}` | the survivor's body | — |
| Old id, Player | absorbed was `gm` (or survivor hidden) | 404 identical to a missing id | — |
| Old id, Player | absorbed was `party`, survivor visible | the survivor's Party body | — |
| Citation | `entity_field` ref to absorbed, GM | resolves with the survivor's name and value | dropped for a Player |

</intent-contract>

## Code Map

- `src/backend/app/services/world_service.py`
  - `_merge` (~L901) already moves aliases, Mentions, edges and safe steps, drops self-loops, adds the name alias, sets `merged_into_id`, marks both stale and writes one `merge` row on the survivor.
  - `apply_change` (~L1213) writes the floors from `_MergePlan`.
  - `_NOT_REVERTIBLE` (L147) contains MERGE.
  - `_revert` (~L1045).
  - `_entity()` locks `FOR UPDATE`.
  - `_check_ref` (L429) refuses merged targets for new writes.
  - `resolve_entity_field` (~L1289) is the citation resolver.
  - The docstring's "Merge primitive" and "Revert" paragraphs must be updated.
- `src/backend/app/access/context.py:120` — `as_system`. `scripts/check_scoped_queries.py:110` allows it only in `world_service.merge_entities`, so the wrapper must have that exact name.
- `scripts/check_scoped_queries.py` — constructor keywords `Model(visibility=..., visibility_floor=...)` pass; attribute assignments pass only inside `apply_change`.
- `src/backend/app/access/registry.py`
  - Entity `gm_when=("deleted_at","merged_into_id")` (L343).
  - `floor_audience` treats `private` as GM.
  - `scoped_get` raises `not_found()`.
  - Raw selects are allowed only under `app/access/`.
- `src/backend/app/access/projection.py:431` — `ENTITY_REF_KEYS`, `entity_ref_ids`. Values are single UUID strings.
- `src/backend/app/services/world_matching.py:131` — the existing merged-chain walk with a cycle guard. Reuse its approach.
- `src/backend/app/api/routes/entities.py`
  - `_gm_ctx` / `_read_ctx`.
  - `_canon_error` (`merged`/`deleted` → 409; the merge route maps them to 404).
  - `get_entity`, `entity_history`, `_project_entities`.
- `src/backend/app/schemas/entities.py:435` — `Merge`. Add request and response schemas here.
- `nginx/locations.conf:121` — `location /api/entities/` already covers `/merge`. Mention the route in its comment.
- `src/backend/tests/ev4/probes/entities.py` — probe patterns (`assert_hidden_equals_missing`, `_refused`, `WRITERS`). EV-4 coverage (`tests/ev4/test_coverage.py`) needs a probe for every route.
- `src/backend/tests/services/test_world_service.py:504` — asserts merge is `not_revertible`; update it. Merge tests are at ~L597–700.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/services/world_service.py`
  - Floor moved aliases by the stricter of the absorbed Entity's `visibility` and `field_visibility.aliases`.
  - Lock both Entities in id order.
  - Repoint safe ENTITY_REF attributes on other live Entities of the Campaign (selected via `scoped_select`).
  - Record the undo payload in the merge row's `new_value`: moved ids with their prior floors and prior edge ends, dropped alias and edge rows in full, the name alias id, moved step ids, and repointed `{entity_id, key}`.
  - Remove MERGE from `_NOT_REVERTIBLE` and add the merge branch to `_revert`. It returns a `_MergePlan`, so floor restores happen in `apply_change`; generalize that branch to any handler result that is a `_MergePlan`.
  - Add `MergeResult` and `merge_entities(...)` (+ `merge = merge_entities`). The preview path validates like the merge and writes nothing.
  - In `resolve_entity_field`, follow a merged Entity to its survivor (GM-visible only) through the new helper.
  - Export the new names and update the docstring.
- `src/backend/app/access/merged.py` (new; export from `app/access/__init__.py`) — `resolve_merged(db, ctx, entity_id) -> Entity`.
  - Follow `merged_into_id` within ctx's Campaign: at most 16 hops, cycle guard.
  - A GM may follow any hop.
  - A non-GM may follow a hop only from a row with stored `visibility == "party"` and `deleted_at IS NULL`.
  - The final row must be live and pass `scoped_get` for ctx. Anything else is `not_found()`.
- `src/backend/app/schemas/entities.py` — `MergeRequest{absorbed_id, preview=False}` and `MergeResponse{downgrades:[{kind,id,from,to}], moved_counts, warning: str|None, survivor_id, change_id: uuid|None, aliases?, mention_count?, relationships?}` (GM-only response).
- `src/backend/app/api/routes/entities.py` — `POST /{entity_id}/merge` (GM ctx; `merged`/`deleted`/`not_found` → 404, `invalid` → 422; commit through `_write`). `get_entity` uses `resolve_merged`. `entity_history` includes the merged-into rows. Update the docstring.
- `nginx/locations.conf` — comment line naming the merge route.
- `src/backend/tests/services/test_world_service.py` — update the not_revertible assertion; add tests for:
  - the aliases-field floor;
  - repointing (safe and unsafe);
  - revert (full, superseded, force);
  - lock order;
  - preview writing nothing.
- `src/backend/tests/test_entities_api.py` — GM route tests: merge, preview, 422/404, `GET` old id, history includes absorbed rows, citation redirect.
- `src/backend/tests/ev4/probes/entities.py` — `@ev4_probe("POST", "/api/entities/{entity_id}/merge", actors=WRITERS)`:
  - a non-GM is refused like missing and nothing is written;
  - the downgrade probe: after a GM merges GM-only into Party, a Player sees none of the moved aliases, Mentions or edges, and there's no canary;
  - a Player's `GET /{absorbed}` for a hidden absorbed id equals the missing-id answer.

**Acceptance Criteria:**
- Given the full backend suite and gates in CI, when the PR runs, then `backend-tests.yml` and `gates.yml` (CI-8, CI-12 EV-4) are green.
- Given a merge and then its revert, when a Player reads the survivor and the absorbed id, then every body equals the one before the merge.

## Spec Change Log

### 2026-11-21 — Coordinator note (E0-WorldCore.7, PR #82)
- Trigger: #82 adds `uq_entity_mentions_suggested` (migration `eed202f2eead`) and a twin check in the old `_merge` Mention loop.
- Amended: `_merge_work` keeps that check. An absorbed suggested Mention whose (entry, source field) the survivor already has a Mention of, suggested or confirmed, is deleted. It is recorded in `undo.dropped_mentions` and re-created on revert. `moved.mentions_dropped` counts it. Confirmed duplicates move, since they have no unique index.
- Known-bad state avoided: a merge failing on the unique index after #82 lands.
- KEEP: when rebasing onto #82, keep the twin check in `_merge_work`, not in the removed loop. This story adds no migration.

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 34 findings — high 1, medium 6, low 13, false 9, maybe-false 5
- findings:
  - `[low]` `[patch]` VG: multi-hop resolve_merged untested — added chain A→B→C, Player middle-gm 404, hand-set loop 404 tests.
  - `[low]` `[patch]` VG: recursive `_merged_family` untested — chain history test asserts A, B, C rows and total.
  - `[low]` `[patch]` VG: quest-step un-merge untested — added quest merge+revert test.
  - `[low]` `[defer]` VG: superseded/force for non-alias kinds untested — shared `touched()` pinned by alias case; deferred.
  - `[false]` `[reject]` VG other: GM GET of an old id whose survivor was deleted is 404 — documented in merged.py ("row reached must be live"); intended.
  - `[maybe-false]` `[defer]` Intent: other `{entity_id}` routes (history, aliases, steps, writes) do not redirect an absorbed id for a GM — GET and citations redirect; writes answer `merged`. Settle with the owner whether "uniformly" covers every route (medium unverified).
  - `[medium]` `[defer]` Intent: a Player's `entity_field` citation of a merged id is dropped even when both were Party — `resolve_sources` drops it before the resolver; fixing needs an access/sources change outside this story.
  - `[low]` `[reject]` Intent: unsafe refs/steps stay on the absorbed id — by design (no widening); GM reads redirect; now counted as `attribute_refs_left`.
  - `[low]` `[patch]` Intent: only one visibility direction probed — added GM-only→Party merge+revert byte-identity test.
  - `[false]` `[reject]` Intent: history decision — implemented as specified, narrowing only.
  - `[false]` `[reject]` Intent: preview bypasses apply_change — by design, writes nothing, tested.
  - `[low]` `[patch]` Blind: downgrade `to` hard-coded `gm`; rows already floored reported — `to` now uses the real floor; already-floored rows skipped. The GM-only→Party "downgrade" report itself is the story's AC.
  - `[low]` `[reject]` Blind: preview/merge `downgrades` ids UUID vs str — both serialise identically through `MergeResponse`.
  - `[low]` `[reject]` Blind: redirect has no explicit signal — body `id` is the survivor's; adding a header adds surface.
  - `[medium]` `[defer]` Blind: GM can no longer GET the absorbed record itself — its history stays readable at `/{absorbed}/history`; a non-following read is UI work (E0-WorldCore.10).
  - `[medium]` `[defer]` Blind: absorbed rows shown in survivor history cannot be reverted from there — they are not revertible while merged anyway; mark read-only in E0-WorldCore.10/11.
  - `[low]` `[patch]` Blind: refs left on the absorbed id unreported — added `moved_counts.attribute_refs_left`.
  - `[medium]` `[patch]` Blind+Edge: "cannot deadlock" overclaims (holders locked after the pair) — docstring narrowed; deadlock remains a 500 in a rare overlap (deferred below).
  - `[maybe-false]` `[defer]` Edge: holder/pair lock overlap between concurrent merges can deadlock → unmapped 500 — settle with a concurrency test on Postgres (medium unverified).
  - `[low]` `[defer]` Blind: undo record unbounded and served to GMs — GM-only; size limit or separate store later.
  - `[low]` `[patch]` Blind+Edge: duplicated depth constant, list scan, silent cutoff — import `MAX_HOPS`, set membership.
  - `[low]` `[patch]` Blind: resolve_merged lacks tests — covered by the VG patch tests above.
  - `[false]` `[reject]` Blind: citation of a merged Entity quotes the survivor — that is the redirect the intent asks for.
  - `[false]` `[reject]` Blind: Players lose access through private grants — Entities are created by GMs; `private` is Owner(GM), no Player ever saw it.
  - `[false]` `[reject]` Blind: merge route maps merged/deleted to 404 — the story AC requires 404.
  - `[low]` `[reject]` Blind: `merge` alias — the story names `world_service.merge`.
  - `[high]` `[patch]` Edge: reverting m1 after m1 was reverted and the pair re-merged (m2) replays m1's stale undo — revert now refuses when a revert row for the target exists (even with force); test added.
  - `[low]` `[patch]` Edge: downgrades listed for rows never Party-visible — same fix as the Blind downgrade row.
  - `[low]` `[patch]` Edge: `to: gm` when the floor is private — same fix.
  - `[maybe-false]` `[defer]` Edge: `_merged_family` silently stops at 16 levels — needs a >16-deep tree to matter (low if true; noted).
  - `[low]` `[patch]` Edge: moved alias's `normalized_alias` not restored on revert — recorded in undo and restored; test added.
  - `[medium]` `[patch]` Edge: a GM publishing a merged-away row afterwards widens the Player old-id redirect — the hop now also requires the merge row to have recorded no floor; test added.
  - `[maybe-false]` `[reject]` Edge: preview skips as_system/can_write — `_check_ctx` + `is_system` refuse every ctx as_system would; preview writes nothing.
  - `[maybe-false]` `[reject]` (dup of the cutoff row, Blind) — same as above.

## Design Notes

Downgrades are entity-level. For each moved alias, Mention or edge, `party_before` = the row was Party-visible on the absorbed Entity (absorbed `party`, and for aliases `field_visibility.aliases` not restrictive). `party_survivor` = survivor `party` (and its aliases field not hidden, for aliases). When they differ, report `{kind, id, from: "party", to: "gm"}`. `warning = "party_with_gm_only"` when one source is `party` and the other is not.

Old-id rule: the stored `visibility` column of the absorbed row is never changed by a merge, so it is the pre-merge Party audience.

## Verification

**Commands:**
- `python3 scripts/check_scoped_queries.py` -- expected: ok
- `cd src/backend && python -m pyflakes app/services/world_service.py app/access/merged.py app/api/routes/entities.py` (if available) -- expected: no errors
- GitHub CI `backend-tests.yml`, `gates.yml` -- expected: green (no Postgres on the Mac; the desktop may be offline)

## Needs desktop verification
- None beyond CI; optionally rerun `pytest tests/services/test_world_service.py tests/test_entities_api.py tests/ev4 -q` on the desktop with own pgvector/valkey containers.

## Auto Run Result

Status: done. A GM merge (`merge_entities`/`merge`, `POST /api/entities/{id}/merge`, with a preview) goes through `apply_change(op=merge)` under `as_system("merge")`. Moved rows are floored, including by the `aliases` field. Safe ENTITY_REF attributes are repointed. The merge can be reverted from its undo record, and a second revert is refused. `access.resolve_merged` sends an old id to the survivor: any GM follows it, and a non-GM follows it only from an id the Party could see at merge time. Survivor history includes the absorbed rows, which stay GM-only. There is an EV-4 merge probe.
Files changed:
- world_service.py
- access/merged.py (new) and access/__init__.py
- routes/entities.py
- schemas/entities.py
- nginx/locations.conf (a comment)
- tests: test_world_service.py, test_entities_api.py and ev4/probes/entities.py

Review: 34 findings.
- 16 patch rows: 1 high, 2 medium, 13 low (some rows share one fix).
- 6 deferred.
- 12 rejected, with their reasons in the log.

followup_review_recommended: true. The high double-revert fix and the two medium fixes (deadlock docstring, the old-id redirect after a later publish) went through no second review pass. CI exercises them only through the new tests.

Verification:
- `check_scoped_queries.py` passes and `py_compile` is clean.
- CI on eb22484: 2702 passed. The only failure was the known flaky `test_campaign_delete_mid_stream_closes_the_stream`.
- The patch round's tests have not run yet; CI on the next push runs them.

Residual risks: the deferred items above.
