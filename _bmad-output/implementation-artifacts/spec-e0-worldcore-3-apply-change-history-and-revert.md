---
title: 'E0-WorldCore.3: apply_change, history and revert'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '64eb9886df50b4d9cc6b942368e726036b1071f5'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-2-f3-world-migration-legacy-npc-quest-copy.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Merge leaves duplicate Mentions/edges, colliding Quest step positions and ENTITY_REF attributes that still name the absorbed Entity.
    evidence: |-
      The merge primitive re-points rows without de-duplication or renumbering and does not rewrite other Entities' attributes. E0-WorldCore.9 owns merge semantics (wrapper, preview, MergeResult) and must handle these.
    location: >-
      src/backend/app/services/world_service.py _merge
    severity: medium
  - summary: >-
      A merge does not move the absorbed Entity's entity_changes history to the survivor.
    evidence: |-
      entity_changes has no visibility_floor, so moving GM-only history onto a Party survivor would widen it. E0-WorldCore.9 (or .11 History via merged_into_id) must decide how merged history is shown.
    location: >-
      src/backend/app/services/world_service.py _merge
    severity: medium
  - summary: >-
      CanonChange.quote is persisted only on Mentions.
    evidence: |-
      entity_changes has no quote column; E1 keeps the quote on its proposal rows.
    location: >-
      src/backend/app/schemas/entities.py
    severity: low
  - summary: >-
      canon_changed publishes ids and timing of GM-only Entity changes on campaign:{id}:events.
    evidence: |-
      Per E0-Jobs.6 the channel is consumed only through E0-Access's visibility-aware GET /api/campaigns/{id}/events (not built). That story must filter `entities` invalidations by the viewer's Audience.
    location: >-
      src/backend/app/hooks/world.py
    severity: medium
  - summary: >-
      The can_write path in apply_change is unexercised until E0-Access.6 (PR #61) merges.
    evidence: |-
      world_service imports app.access.write.can_write only if present; it is absent on main, so tests run without it. Settle: rerun the suite once #61 merges.
    location: >-
      src/backend/app/services/world_service.py _gate
    severity: medium (unverified)
  - summary: >-
      Concurrent apply_change races (opposite-order merges, two creates under one proposal_id) are untested.
    evidence: |-
      Row locks are taken per lookup in call order; a deadlock is aborted by Postgres and two creates could both pass _repeat. Settle with two-session tests; E1.4 should apply a proposal under its own row lock.
    location: >-
      src/backend/app/services/world_service.py _merge, _create_entity
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** F3-world tables exist, but nothing may write them: there is no `world_service.apply_change`, no history, no revert, and no `set_visibility` writer for Entities. E1 extraction, E2 retcons, merges and the E7 portal all need this single Canon write path. Players must never reach it, and GM-only history must never leak to them.

**Approach:** Add `app/services/world_service.py` with `apply_change(db, ctx, change)` and `revert_change(db, ctx, change_id, *, force=False)`. `CanonChange` is a discriminated pydantic union of the 19 public ops, in `app/schemas/entities.py`. Each op runs in a savepoint. It validates the change, writes the owning table, appends exactly one `entity_changes` row, marks dependents stale when the change narrows, and emits `canon_changed` (delivered after commit). Register the `entity` and `entity_relationship` Visibility kinds with `apply_change`'s writer through a new registry `register_writer`. Add value-type checks to `validate_attributes`, and add the `canon_changed` handler in `app/hooks/world.py`.

## Boundaries & Constraints

**Always:**
- Who may call it: a writable GM user ctx may use every public op except `merge`, `source_deleted` and `migrated`. A system ctx is accepted only for `as_system("merge")` → `merge`, and `as_system("entry_deleted")` → `remove_mention` or `source_deleted`. Every other ctx (Player, anon, preview/`audience_ctx`, a wrong op for the reason) gets `not_found()` and nothing is written. Each row written also passes `can_write` (E0-Access.6, imported when present) and the module's own GM rule.
- Target lookups go through `scoped_select`. Another Campaign or a missing id → `CanonChangeError("not_found")`. A merged target → `merged`, a soft-deleted one → `deleted`, a bad status → `invalid_status`, a bad field or value → `invalid`. Every error writes nothing (savepoint).
- One history row per applied change (`op, field, old_value, new_value, source_journal_id, proposal_id, canon_note_id, actor_user_id, reverted_change_id`). History `field` drives Player visibility (registry `parent_field` rule):
  - Entity fields use their own name (`name`, `description`, `status`, `kind`, `attributes.<k>`, `gm_notes`, `aliases`, `quest_steps`).
  - Relationship, Mention, create, delete, merge and canon-note rows use `field=None`, which is always GM.
  - `field_visibility.<k>` rows are GM.
- Idempotent (no new row; return the earlier change): re-adding the same alias or Mention, confirming a confirmed Mention, ending an ended Relationship, `create_entity` with an existing `entity_id`, and any op repeated with the same `proposal_id` + op + entity + field.
- Quest `set_status` into `closed_success` stamps `attributes.completed_at` (UTC ISO). Leaving it clears the stamp. For Quests, old/new hold `{status, completed_at}`.
- Narrowing ops (`delete_entity`, `remove_alias`, `remove_mention`, `merge`, and reverts that remove a row) call `access.mark_dependents_stale(db, [RecordRef(kind="entity_field", id=entity_id)])` in the transaction.
- The only literal `visibility_floor` write is inside `apply_change`, on the merge branch. Visibility values reach `apply_change` only through the registry writer, guarded by a private token. A `visibility_floor` path from `set_visibility` → 422.
- `validate_attributes` checks value types: TEXT is a str, DATETIME an ISO 8601 str with a timezone, ENTITY_REF a UUID, CHOICE one of its choices (None = unset). `apply_change` also checks that an ENTITY_REF names a live Entity of the same Campaign and of an allowed type.
- Deleted or merged Entities are GM-only: a registry `gm_when=("deleted_at", "merged_into_id")` on `entities`, mirrored in SQL and Python and covered by CI-11.

**Never:**
- No routes, API schemas for HTTP, or frontend (E0-WorldCore.5/.10/.11). No `world_service.merge`/`merge_entities` wrapper, `MergeResult` or preview (E0-WorldCore.9). No `detach_entry` (E0-WorldCore.8). No `normalize_name`/`match_names` (E0-WorldCore.4).
- No migration. Don't edit `core/pubsub.py`/`core/sse.py` (E0-Jobs.6), `access/write.py` (E0-Access.6), stt code, `epics.md`, `sprint-status.yaml`. Don't commit `epic-*-context.md`.
- Never take a visibility value from a `CanonChange`. Never build `as_system` in `app/` (tests may). Never widen CI-8 allowlists.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM create | `create_entity` character npc "Mira" | Entity gm-visible, default status, 1 `create_entity` row (field None), `canon_changed` after commit | — |
| Player/anon/preview | any op | nothing written, no event | `NotFound` |
| Wrong system reason | `as_system("entry_deleted")` + `update_field` | nothing written | `NotFound` |
| Bad status / cross-Campaign / merged / deleted | `set_status` "zombie"; other Campaign's id; merged; deleted | nothing written | `CanonChangeError` invalid_status / not_found / merged / deleted |
| Quest completes | active → completed → active | completed_at stamped, then cleared; both in rows | — |
| ENTITY_REF | Item `holder_entity_id` = a Location, or another Campaign's Character | refused | `invalid` |
| Revert | revert `update_field` description | value restored, `revert` row with `reverted_change_id` | — |
| Superseded | later change touched field | refused unless `force=True` | `superseded` |
| Revert create / merge / visibility | — | create → soft delete; merge and visibility changes refused | `not_revertible` |
| set_visibility entity | GM publishes an Entity, or hides `description` | written by the writer, one `update_field` row (`visibility` / `field_visibility.description`) | Player → 404 |
| Merge | `as_system("merge")`, GM-only absorbed into Party survivor | aliases/mentions/edges re-pointed with floor `gm`, absorbed name added as alias, self-loops dropped, `merged_into_id` set, both marked stale | — |
| Rollback | apply then rollback | no row, no event | — |
| EV-4 | GM-only Entity history, GM-only field changes, relationship/mention rows on a Party Entity | none visible to player / anon_share / cross_gm_player; canaries absent | — |

</intent-contract>

## Code Map

- `src/backend/app/db/models/entity.py` -- the 7 models; `EntityChange` columns (no `quote` column).
- `src/backend/app/schemas/entities.py` -- add `CanonChange` union. The GM/Party response pairs already exist.
- `src/backend/app/domain/entity_types.py:304` `validate_attributes` -- add value-type checks. `AttributeDef.value_kind/target_types/choices`. `attribute()`, `validate_status`, `validate_kind`, `status_category`.
- `src/backend/app/domain/enums.py` `EntityChangeOp` -- 19 ops + `migrated`.
- `src/backend/app/access/registry.py:130` `Stored` (frozen; `writer` slot), `:290` Entity registration, `_stored_clause`, `audience_of`/`narrowed_audience`, `_parent_field_audience` (history field rule). Add `gm_when` + `register_writer(model, fn)`.
- `src/backend/app/access/visibility.py` -- `_write` calls `reg.writer(db, ctx, row, path, value)`. Also `register_visibility_kind`, `mark_dependents_stale`, `field_path`, `VisibilityError`.
- `src/backend/app/access/context.py:56` `CampaignContext` (`is_system`, `system_reason`, `read_only`, `role`). `policy.py` `SystemReason`, `GM`, `not_found`.
- `src/backend/app/core/hooks.py` -- `emit(db, HookEvent.CANON_CHANGED, campaign_id=, refs=, actor_ctx=)`. `app/hooks/__init__.py` `HANDLERS` append point.
- `origin/story/e0-jobs-6-sse:src/backend/app/core/pubsub.py` -- `async publish_campaign_event(campaign_id, domain, id)` (not on main yet: lazy import).
- `origin/story/e0-access-6-write-rules:src/backend/app/access/write.py` -- `can_write(ctx, obj)` (not on main yet: optional import).
- `src/backend/app/services/file_service.py:741` -- the registered stale marker (matches `ref.id`).
- `scripts/check_scoped_queries.py` -- CI-8: as_system sites, `VISIBILITY_WRITE_ALLOWED` (`apply_change` → `visibility_floor`), the scoped-query ratchet.
- `src/backend/tests/access/test_registry_property.py:143` `entity_spec` -- CI-11 property specs.
- `src/backend/tests/ev4/test_world_rows.py`, `tests/ev4/fixtures.py` (`ev4`, actors, `canary_hits`) -- EV-4 patterns.
- `src/backend/tests/access/test_set_visibility.py` -- ctx fixtures and writer-slot test precedent.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/domain/entity_types.py` -- value-type validation in `validate_attributes`, normalising ENTITY_REF to a canonical UUID str.
- `src/backend/app/access/registry.py` -- `Stored.gm_when`, which is used in `_stored_clause`/`audience_of`/`narrowed_audience`. Entity gets `gm_when=("deleted_at","merged_into_id")`. Add `register_writer(model, fn)` (stored models only; idempotent for the same fn, raises for a different one). Export it from `app/access/__init__.py`.
- `src/backend/app/schemas/entities.py` -- `CanonChange` and its 19 members (shared optional `source_journal_id`, `proposal_id`, `canon_note_id`, `quote`).
- `src/backend/app/services/world_service.py` -- `CanonChangeError`, `apply_change`, `revert_change`, the visibility writer, `register_writer` + `register_visibility_kind("entity"/"entity_relationship")`.
- `src/backend/app/hooks/world.py` + `app/hooks/__init__.py` -- the `canon_changed` handler, which publishes `("entities", id)` per ref through `core.pubsub` when present (logs and skips otherwise). It is registered in `HANDLERS`, and its import also loads world_service's registrations.
- `src/backend/tests/services/test_world_service.py` -- every op, the matrix, idempotency, atomicity, revert, hooks after commit / dropped on rollback, the as_system grep test.
- `src/backend/tests/ev4/test_world_changes.py` -- EV-4 probes.
- `src/backend/tests/domain/test_entity_types.py`, `tests/access/test_registry_property.py` -- value types; deleted/merged in specs.

**Acceptance Criteria:**
- Given CI, when backend-tests and gates run, then all pass with no regression (CI-8 green, no allowlist change).
- Given `set_visibility` on kind `entity`, when a GM publishes an Entity, then `entities.visibility` changes and exactly one `update_field` row with field `visibility` exists.
- Given a Player ctx, when it reaches `apply_change`, `revert_change` or `set_visibility(entity)`, then `NotFound` and the row counts are unchanged.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 55 findings — high 0, medium 27, low 14, false 8, maybe-false 6 (verification-gap 3, blind 18 incl. sub-claims, intent 5, edge 29 incl. claims)
- findings:
  - `[medium]` `[patch]` (vgap) reverts that remove a row (add_relationship/add_mention/add_alias) have no stale-ref test — tests added with the `stale` fixture.
  - `[medium]` `[patch]` (vgap) superseded/force never exercised for row-based reverts (update_relationship, update_quest_step) — tests added.
  - `[medium]` `[patch]` (vgap) `_earlier` falls back to an unrelated newest row — returns None now; pre-existing state with no matching history raises `invalid` without writing.
  - `[medium]` `[patch]` (blind) delete_entity/merge proposal repeats raise deleted/merged — repeat checked before liveness; merge repeat matches absorbed_id.
  - `[medium]` `[patch]` (blind) proposal repeats ignore the payload — field changes match new_value, canon_note matches note; create with an existing id checks type/name/liveness.
  - `[medium]` `[patch]` (blind) `_earlier` unrelated row / duplicate insert — same fix as vgap row 3.
  - `[medium]` `[patch]` (blind) revert of added rows ignores later edits — compares the row to new_value, superseded unless force.
  - `[low]` `[patch]` (blind) floor restored in revert constructors contradicts "only floor write" — kept (dropping it would bring a floored alias/Mention back unfloored, a leak); the docstring now names the constructor restore; CI-8 allows constructors by design.
  - `[medium]` `[defer]` (blind) merge leaves duplicate Mentions/edges and ENTITY_REF attributes naming the absorbed Entity — merge semantics belong to E0-WorldCore.9.
  - `[low]` `[reject]` (blind) quest step positions not renumbered — ordering ties are cosmetic (renumbering UI is E0-WorldCore.11) and the fix adds branches.
  - `[maybe-false]` `[reject]` (blind) source_deleted bulk sa.update bypasses `_gate` — runs only under `as_system("entry_deleted")` (a GM ctx) and is Campaign-filtered; settle with E0-Access.6's system-ctx rule; low if true.
  - `[medium]` `[patch]` (blind) on_canon_changed has no per-ref error handling — try/except per publish, logged without refs.
  - `[medium]` `[defer]` (blind) campaign events channel gives Players ids/timing of GM-only Entity changes — per E0-Jobs.6 the channel is consumed only through E0-Access's visibility-aware events route (not built yet).
  - `[false]` `[reject]` (blind) hook imports pubsub unconditionally against the spec — E0-Jobs.6 merged (#65) and the coordinator asked for direct publishing.
  - `[medium]` `[patch]` (blind) EV-4 misses merge row, quest_steps on a GM Quest, revert of a hidden field, hidden status and source_deleted rows — probes added.
  - `[low]` `[patch]` (blind) whitespace-only create name accepted — validator added.
  - `[low]` `[reject]` (blind) ended_at before started_at not checked — GM data, no named harm; adds branches.
  - `[false]` `[reject]` (blind) malformed history uuid raises ValueError — history rows are written only by apply_change with canonical ids.
  - `[low]` `[patch]` (blind) spec bookkeeping (deferred empty, docstring omits migrated) — deferred filled, docstring fixed; the session-local Verification path is kept (session tooling).
  - `[medium]` `[patch]` (blind) missing tests list — covered by the added tests where behaviour changed.
  - `[medium]` `[patch]` (blind) source_deleted new_value lacks field/current_value (E0-WorldCore.8 contract) — now `{journal_id, field, current_value, flagged}`.
  - `[low]` `[reject]` (intent) Quest status row carries completed_at even when attributes are hidden — the stamp equals the row's own created_at, so it adds nothing a viewer of the status row lacks.
  - `[maybe-false]` `[defer]` (intent) can_write path never exercised (app/access/write.py not on main) — settle by rerunning the suite after PR #61 merges.
  - `[false]` `[reject]` (intent) stale tests use a fake marker, not derived_sources — the real marker is E0-Jobs.8's and tested there; apply_change's contract is the RecordRef it passes.
  - `[false]` `[reject]` (intent) relationship visibility recorded as update_relationship — the story's update_field form is for Entities; an edge row needs field NULL so it stays GM.
  - `[false]` `[reject]` (intent) no EV-4 write probes — test_non_gm_ctxs_write_nothing covers the only existing indirect path (set_visibility); routes are E0-WorldCore.5.
  - `[medium]` `[patch]` (edge) _earlier fallback (L326) — as vgap row 3.
  - `[medium]` `[patch]` (edge) alias exists with no history → duplicate insert (L523) — raises invalid.
  - `[medium]` `[patch]` (edge) ended edge without an end row is overwritten (L616) — raises invalid.
  - `[medium]` `[patch]` (edge) Mention exists without history → duplicate (L707) — raises invalid.
  - `[medium]` `[patch]` (edge) create_entity existing id with another type/name (L450) — checked.
  - `[maybe-false]` `[reject]` (edge) floored alias removed twice under one proposal raises not_found (L534) — a floored remove writes field NULL so the "aliases" repeat misses it; settle with a test; low if true (a retried GM cleanup errors without writing).
  - `[medium]` `[patch]` (edge) merge repeat collapses two absorbed Entities (L813) — matches absorbed_id.
  - `[medium]` `[patch]` (edge) a second canon note under one proposal is dropped (L792) — matches note.
  - `[medium]` `[patch]` (edge) revert add_relationship after an edit (L993) — superseded check.
  - `[medium]` `[patch]` (edge) revert add_quest_step after an edit (L1018) — superseded check.
  - `[medium]` `[patch]` (edge) revert add_mention after confirm (L1036) — superseded check.
  - `[low]` `[patch]` (edge) a gone row in revert answers not_found, not superseded (L1004) — mapped to superseded.
  - `[low]` `[patch]` (edge) naive datetime shifted by the local offset (L149) — naive treated as UTC.
  - `[low]` `[patch]` (edge) int4 overflow on position/span (schemas L356) — bounded.
  - `[low]` `[patch]` (edge) whitespace create name (schemas L269) — validator.
  - `[low]` `[reject]` (edge) completed_at set by update_field on an open Quest — an explicit GM edit; refusing it adds a rule the story does not ask for.
  - `[low]` `[defer]` (edge) merged steps collide in position (L859) — E0-WorldCore.9.
  - `[medium]` `[defer]` (edge) ENTITY_REF attributes not re-pointed on merge (L864) — E0-WorldCore.9.
  - `[maybe-false]` `[defer]` (edge) opposite-order concurrent merges deadlock (L807) — settle with a two-session test; Postgres aborts one (no corruption); medium if true (unverified).
  - `[maybe-false]` `[defer]` (edge) concurrent create_entity with one proposal_id both pass `_repeat` (L458) — settle with two sessions; medium if true (unverified).
  - `[medium]` `[patch]` (edge) set_visibility on a deleted/merged Entity raises CanonChangeError (L895) — allow_deleted/allow_merged.
  - `[false]` `[reject]` (edge) source_deleted fails when the journal is gone (L296) — E0-WorldCore.8 calls it before the row is removed, in the delete transaction, under a system ctx that sees the entry.
  - `[low]` `[patch]` (edge) a hook publish failure stops later refs — per-ref try/except.
  - `[false]` `[reject]` (edge) register_writer fails on module reload (registry L345) — no process reloads modules; not reachable.
  - `[medium]` `[patch]` (edge, claim) a Player with a malformed payload gets invalid, not 404 — ctx checked before parsing.
  - `[false]` `[reject]` (edge, claim) hook has no pubsub fallback — pubsub merged (#65); intended.
  - `[medium]` `[patch]` (edge, claim) add_* reverts destroy later edits — as above.
  - `[low]` `[patch]` (edge, claim) revert floor constructor writes — docstring, as the blind row.
  - `[maybe-false]` `[reject]` (edge, claim) source_deleted bulk updates skip can_write — as the blind row; low if true.

## Design Notes

- **Merge primitive only:** op `merge` (target = absorbed, `survivor_id`) does the row moves and floors that E0-WorldCore.9's wrapper calls. The floor is `gm`/`private` from a non-party absorbed Entity, and the existing floor is kept when it is more restrictive. Quest steps move only when that cannot widen them (absorbed is party or survivor is not party). `entity_changes` rows stay on the absorbed Entity: moving them could widen GM-only history (no floor column). This is recorded in `deferred`. The single merge row goes on the survivor with `field=None`.
- **Visibility-change history:** relationship rows store `field=None` because their audience is not the Entity's. Visibility changes are `not_revertible`: the GM re-sets them through `set_visibility`.
- **quote:** stored on Mentions. For other ops there is no column, so it is not persisted; E1 keeps it on the proposal (deferred).

## Verification

**Commands:**
- `python scripts/check_scoped_queries.py && python scripts/check_table_owners.py` -- expected: exit 0
- `cd src/backend && lint-imports` -- expected: contracts kept
- `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/wc3-test.sh -q [paths]` -- rsyncs the worktree to the desktop and runs pytest in the cached `lorekeeper-backend-test` image against private containers `wc3-pg` (127.0.0.1:55433) / `wc3-valkey`; expected: all pass (full suite with no args after `-q`)
- `cd src/backend && uv run --python 3.11 --with import-linter lint-imports` (or run `lint-imports` inside the desktop image) -- expected: contracts kept

## Auto Run Result

Status: done

**Summary.** `app/services/world_service.py` is now the single Canon write path:
- `apply_change(db, ctx, change)` and `revert_change(db, ctx, change_id, *, force=False)` cover the 19 public `EntityChangeOp` ops as a discriminated `CanonChange` (`app/schemas/entities.py`).
- Each op runs in one savepoint, writes the owning table, appends exactly one `entity_changes` row, marks the dependents of narrowing changes stale (`mark_dependents_stale`, `entity_field` refs), and emits `canon_changed`. The hook dispatcher delivers it after commit; a rollback drops it.
- Callers: a writable GM user ctx; `as_system("merge")` for `merge` only; `as_system("entry_deleted")` for `remove_mention`/`source_deleted` only. Anything else gets the uniform 404 and writes nothing. `can_write` (E0-Access.6) is called when `app/access/write.py` is present; PR #61 is still open, so it is the guarded import for now.
- Visibility for `entity` and `entity_relationship` goes only through `set_visibility` → the registry writer (`register_writer`, new) → `apply_change` with a private token.
- The only literal `visibility_floor` write is the merge branch of `apply_change`. Reverting `remove_alias`/`remove_mention` also restores the earlier floor through the constructor, so a floored row never comes back unfloored.
- `validate_attributes` now checks value types. `apply_change` also checks that an ENTITY_REF names a live Entity of the same Campaign and of an allowed type.
- A registry `gm_when=("deleted_at","merged_into_id")` makes deleted or merged Entities, and everything derived from them, GM-only. This is covered by CI-11.
- `app/hooks/world.py` publishes one keyed `("entities", id)` invalidation per Entity through `core.pubsub.publish_campaign_event` after commit (E0-Jobs.6, merged as #65). A failing publish is logged and skipped.

**Files changed**
- `src/backend/app/services/world_service.py` -- new: apply_change, revert_change, merge primitive, visibility writer, registrations.
- `src/backend/app/schemas/entities.py` -- CanonChange union (19 ops), parse helper, bounds and validators.
- `src/backend/app/domain/entity_types.py` -- value-type validation (TEXT, DATETIME, ENTITY_REF, CHOICE).
- `src/backend/app/access/registry.py`, `app/access/__init__.py` -- `Stored.gm_when`, `register_writer`.
- `src/backend/app/hooks/world.py`, `app/hooks/__init__.py` -- canon_changed → publish_campaign_event, registered in HANDLERS.
- `src/backend/tests/services/test_world_service.py` -- every op, matrix, idempotency, atomicity, revert, hooks/pubsub end to end, as_system grep test.
- `src/backend/tests/ev4/test_world_changes.py` -- EV-4: GM-only history and changes invisible to player / anon_share / cross_gm_player.
- `src/backend/tests/domain/test_entity_types.py`, `tests/access/test_registry_property.py`, `tests/access/test_world_registry.py` -- value types; deleted/merged specs in CI-11.

**Review findings.** 55 rows (high 0, medium 27, low 14, false 8, maybe-false 6). Patched 38 (0 high, 26 medium, 12 low). Deferred 6 items (frontmatter `deferred`):
- merge dedupe/ENTITY_REF/step positions → E0-WorldCore.9;
- merged history placement;
- `quote` persisted only on Mentions;
- the campaign-events channel must be audience-filtered by E0-Access;
- the can_write path is unexercised until #61;
- concurrency races.

Rejected, each with its reason in the triage log:
- step renumbering;
- end-before-start;
- malformed history uuid;
- completed_at in Quest status rows (equals the row's own created_at);
- completed_at via update_field;
- source_deleted bulk update gate (system ctx only);
- floored remove_alias repeat;
- module reload;
- the pubsub fallback claims (superseded by #65);
- stale tests using a fake marker;
- relationship visibility op naming;
- EV-4 write probes (no routes yet).

**Follow-up review recommendation: true.** 26 medium entries were patched in one pass. The idempotency and revert rules were reworked by those patches (`_earlier`/`_already`, payload-matched proposal repeats, superseded checks on added rows), and they have only had the implementer's own tests. E1.4's proposal replay depends on them, so it is worth a second look.

**Verification**
- `python scripts/check_scoped_queries.py` -- ok, including the allowed merge floor. `python scripts/check_table_owners.py` -- ok.
- `lint-imports` (desktop image) -- 5 contracts kept, 0 broken.
- Full backend suite on the desktop (`wc3-test2.sh -q`, private `wc3-pg`/`wc3-valkey` containers) -- 2068 passed, 4 skipped, EV-4 probes=85 leaks=0. Main baseline was 1931 passed in CI before #65; nothing regressed.
- The `tests/test_pubsub.py` `[real]` cases (from #65) were flaky against the desktop's redis:7 stand-in when run alone, unrelated to this change. CI uses valkey 8.

**Needs desktop verification:** none. All tests ran on the desktop; there is no GPU, Ollama or compose work in this story.

**Residual risks:** the deferred items above. In particular, E0-Access's events route must filter `entities` invalidations by Audience before any Player subscribes to `campaign:{id}:events`.
