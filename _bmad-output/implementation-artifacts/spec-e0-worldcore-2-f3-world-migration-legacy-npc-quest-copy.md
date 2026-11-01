---
title: 'E0-WorldCore.2: F3-world migration with the legacy NPC/Quest copy'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '4548731b8a7ea88d17d89ccc5b0e3b1f68711586'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-1-entity-type-registry-and-closed-set-enums.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Campaigns created after the upgrade get no default relationship_types.
    evidence: |-
      DATA_STEPS seeds the six types only for Campaigns existing at upgrade; app/api/routes/campaigns.py create_campaign does not seed them. The AC scopes seeding to the revision; campaign creation is outside this story. E3.1 (relationship type API) or E0-WorldCore.5 must seed on create.
    location: >-
      src/backend/app/api/routes/campaigns.py create_campaign
    severity: medium
  - summary: >-
      NPC/Quest rows created, edited or deleted through the legacy routes after the upgrade are not reflected in entities.
    evidence: |-
      The copy is insert-only and runs once; the legacy routes stay allowlisted writers (tests/test_legacy_frozen.py) until E0-WorldCore.6 turns them into adapters. WorldCore.6 must re-apply DATA_STEPS (idempotent) and reconcile edits/deletes; do not ship a release with WorldCore.2 but without WorldCore.6.
    location: >-
      src/backend/app/api/routes/npcs.py, quests.py, scripts/seed_demo.py
    severity: medium
  - summary: >-
      Hiding the `aliases` field through field_visibility does not hide entity_aliases rows.
    evidence: |-
      entity_types/projection render a hidden `aliases` as [], but EntityAlias is derived only from its Entity and floor; scoped_select(EntityAlias, player) still returns them. E0-WorldCore.5 (Entity API, aliases) must narrow alias rows by the parent's field_visibility["aliases"] or forbid hiding it.
    location: >-
      src/backend/app/access/registry.py EntityAlias registration
    severity: medium
  - summary: >-
      Soft-deleted or merged-away Entities keep their Audience in the registry.
    evidence: |-
      visible_clause(Entity) ignores deleted_at and merged_into_id, so a party Entity that is later soft-deleted stays visible (and so do its children). No Entity is deleted or merged until E0-WorldCore.3/.9; those stories (or .5's reads) must decide the Player view of deleted/merged rows.
    location: >-
      src/backend/app/access/registry.py Entity registration
    severity: medium
  - summary: >-
      Entity-reference attributes (location_entity_id, leader_entity_id, ...) and history values can name Entities the viewer cannot see.
    evidence: |-
      EntityPartyResponse.attributes passes reference ids through unless each key is hidden; nothing narrows them by the referenced Entity's Audience. Only copied Entities exist (attributes {} or completed_at), so no data is affected yet. E0-WorldCore.5 must resolve or drop references to Entities hidden from ctx.
    location: >-
      src/backend/app/schemas/entities.py EntityPartyResponse
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Every self-hoster's next boot must turn their NPCs and Quests into the World Model (F3-world, AD-19) with nothing lost and nothing exposed. None of the seven F3 tables, their models, their access registrations or the legacy copy exist yet.

**Approach:** One Alembic revision `03c0b504f1d1` on head `cf62d979bc8a` creating the seven tables (composite Entity FKs, CHECKs from `domain/enums.py`), the deferred `pc_entity_id`/`npc_entity_id` FKs, and an idempotent set-based copy (`DATA_STEPS`, `INSERT … SELECT … WHERE NOT EXISTS`) of `npcs`/`quests` into GM-only `entities`, one `migrated` history row each, default `relationship_types` per Campaign and the `suggested_mentions_v1` backfill row. Models in `app/db/models/entity.py`, registered in the access registry and given GM/Party projections.

## Boundaries & Constraints

**Always:**
- Owner decisions: every copied Entity is `visibility = gm`, `field_visibility = {}` (OD-1 option A; E0-Access.14 dropped). Faction-role NPCs become `faction` Entities (no kind). `notes → gm_notes`. Name matches become suggested Mentions only, later (E0-WorldCore.7): this story only inserts `data_backfills('suggested_mentions_v1', status 'queued')` (CHECK is JobStatus; "pending" in the AC means `queued`).
- Mapping exactly as the AC: role npc/pc/monster → character npc/pc/creature; NPC status alive/dead/unknown → alive/deceased/unknown; faction alive/dead → active/disbanded; Quest title → name, status unchanged, `completed` gets `attributes.completed_at = updated_at` (ISO 8601 UTC). description, created_by = user_id, created_at/updated_at preserved; `legacy_npc_id`/`legacy_quest_id` set. An unmappable value takes the type's default status (`unknown`; Quest `active`, Quest has no `unknown`) or kind `npc`, is logged, never fails.
- Copy is deterministic and idempotent: ids are `md5(<namespace>:<legacy id>)::uuid`, every insert guarded by `NOT EXISTS`/`ON CONFLICT DO NOTHING`; re-applying `DATA_STEPS` or downgrade+upgrade yields identical rows. Alembic holds only schema + set-based SQL (AD-18).
- Every Entity reference is the composite `(campaign_id, x) → entities(campaign_id, id)`; FKs to `campaigns` CASCADE, to `journal_entries` SET NULL, to `users` SET NULL. Nullable Entity links (`merged_into_id`, `character_sheets.pc_entity_id`, `chat_sessions.npc_entity_id`) use PG15+ `ON DELETE SET NULL (col)` so `campaign_id` is never nulled.
- Frozen enum copies in the revision (precedent `cf62d979bc8a`); CI-10 entries move from `ENUM_CHECKS_PENDING` to `ENUM_CHECKS`.
- Registry: `entities` stored (owner `created_by_user_id`, `field_visibility`, gm field `gm_notes`); `entity_relationships` stored, narrowed by `visibility_floor` and by both endpoint Entities; `entity_aliases` derived from Entity + floor; `quest_steps` derived from Entity; `entity_mentions` derived from entry + Entity + `source_field` + floor (AD-12 formula); `entity_changes` derived from Entity and its `field` (always-GM fields, the Entity's `field_visibility[field]`, and `field_visibility.*`/`visibility_floor` history are GM). CI-11 passes over all of them.

**Never:**
- No `apply_change`, no `world_service` edits (E0-Journal.1 sibling creates it; E0-WorldCore.3 fills it), no `set_visibility` kind/writer for Entities (E0-WorldCore.3/.5), no routes, no suggested-Mention rows, no Mention backfill kind (E0-WorldCore.7), no frontend.
- Never copy legacy visibility (option B not shipped). Never modify or delete `npcs`/`quests` rows. No FK from `legacy_*_id` to the legacy tables (a legacy delete must never cascade into the world).
- Do not touch sibling files: `app/hooks/*`, `app/services/journal_service.py`, `app/services/world_service.py`, files/stt code, `sprint-status.yaml`, `epics.md`; do not commit `epic-*-context.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Seeded snapshot | `a3e7c1f9d258` dump: pc + npc + faction NPC, active + completed Quest | 5 GM-only Entities, faction → `faction`/`disbanded` or `active`, completed_at set, notes in gm_notes, 5 `migrated` rows, 6 relationship types, 1 backfill row; legacy rows unchanged | none |
| Re-run | `DATA_STEPS` re-applied / downgrade+upgrade | identical row sets incl. ids | none |
| Duplicate names | two NPCs "Bob" in one Campaign | two Entities | none |
| Unicode / empty | name "Ælfrīð 竜", notes `''`, NULL description | copied byte-exact | none |
| Zero NPCs | Campaign with no NPCs/Quests | 0 Entities, still 6 relationship types | none |
| Unmappable | legacy enum gains value `zombie` | status `unknown` (Quest `active`), warning logged with ids | never raises |
| Cross-Campaign link | alias/mention/relationship naming an Entity of another Campaign | insert fails (composite FK) | IntegrityError |
| Campaign deleted | Campaign with entities, sheets linked to a PC, chats linked to an NPC | everything cascades; chat keeps row with NULLs | none |
| Non-GM read | Player / anon share / cross-GM Player after copy | sees no copied Entity, change, alias, mention or relationship | uniform not_found |

</intent-contract>

## Code Map

- `src/backend/migrations/versions/cf62d979bc8a_f2_jobs_files.py` -- head; frozen-enum + `check_sql` precedent.
- `src/backend/migrations/versions/c95acb56c595_f1_core_roles_visibility_party_search.py` -- `DATA_STEPS`/`apply_data_steps` precedent; added `pc_entity_id`, `npc_entity_id` without FKs.
- `src/backend/migrations/versions/00bc84d5d90c_add_npcs_and_quests_tables.py` -- legacy columns; role/status are PG enums `npcrole`/`npcstatus`/`queststatus` (cast `::text`).
- `src/backend/app/domain/enums.py`, `entity_types.py` -- enums, `check_expr`, statuses, `party_view`/`party_unset`.
- `src/backend/app/db/base.py` -- `VISIBILITY_ENUM`, `TimestampMixin`; `app/db/models/job.py` CHECK-in-model precedent; `__init__.py` registration + `__all__`.
- `src/backend/app/access/registry.py` -- `Stored`/`Derived`/`Parent`, `_stored_clause`, `_derived_clause`, `audience_of`, `_check_complete`. Needs: `owner_field=None`, `floor`, `narrowed_by` on Stored; `floor`, `field_rule="parent_field"` on Derived; GM sees orphan (NULL fk) derived rows.
- `src/backend/app/access/audience.py` -- `stored_audience`, `field_audience`, `ALWAYS_GM_FIELDS`, `most_restrictive`.
- `src/backend/app/access/projection.py` -- `PROJECTIONS`, `_check_row`, `_apply_field_visibility`, import-time `check_party_schemas`.
- `src/backend/app/access/visibility.py` -- reads `reg.owner_field` (guard None).
- `src/backend/tests/access/test_registry_property.py` -- CI-11 `SPECS` + `_build` must cover every model.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- `SEEDED_COUNTS`, `EXPECTED_FK_ON_DELETE` (keyed `table.column`; composite FKs need a constraint-level key), `@post_upgrade_check`, downgrade tests.
- `src/backend/scripts/make_snapshot.py` + `tests/fixtures/snapshot_a3e7c1f9d258.sql` -- seed has no faction NPC and no notes; extend seed and regenerate with pg_dump 16.
- `src/backend/tests/test_enum_check_sync.py` -- move the five enums to `ENUM_CHECKS`.
- `src/backend/tests/test_migrations_match_models.py` -- drift gate (PG reflects `SET NULL (col)` as `SET NULL`, so models declare `ondelete="SET NULL"`; models never emit DDL).
- `src/backend/tests/ev4/fixtures.py`, `families.py` (`canary_hits`), `test_job_rows.py` -- non-route EV-4 test precedent.
- `scripts/check_table_owners.py` (CI-7), `scripts/check_scoped_queries.py` (CI-8) -- must stay green.
- Legacy writers (freeze ratchet allowlist): `app/api/routes/npcs.py`, `app/api/routes/quests.py`, `scripts/seed_demo.py`.

## Tasks & Acceptance

**Execution:**
- `src/backend/migrations/versions/03c0b504f1d1_f3_world_entities_legacy_copy.py` -- tables, indexes, CHECKs, composite/SET NULL(col) FKs, the two deferred FKs, `DATA_STEPS` + `apply_data_steps`, unmapped-row warning (online mode only), dev-only downgrade.
- `src/backend/app/db/models/entity.py` -- `Entity`, `EntityAlias`, `EntityMention`, `RelationshipType`, `EntityRelationship`, `QuestStep`, `EntityChange` matching the migration; `app/db/models/__init__.py`, `character_sheet.py`, `chat.py` FK declarations.
- `src/backend/app/access/registry.py` (+ `visibility.py`, `projection.py` guards) -- registry options above and the seven registrations.
- `src/backend/app/schemas/entities.py` + `app/access/projection.py` -- GM/Party pairs for the seven models; Entity Party rendering of hidden fields via `entity_types.party_view`.
- `src/backend/tests/test_enum_check_sync.py` -- move enums.
- `src/backend/scripts/make_snapshot.py`, `tests/fixtures/snapshot_a3e7c1f9d258.sql`, `tests/migrations/test_upgrade_snapshot.py` -- seed faction NPC + notes; post-upgrade checks (all copied, nothing lost, all GM-only, faction→Faction, history, relationship types, backfill row), FK table, idempotency, F3 downgrade test.
- `src/backend/tests/migrations/test_world_copy_adversarial.py` -- adversarial dataset (duplicates, faction, unicode, empty notes, zero-NPC Campaign, unmappable enum value), cross-Campaign FK refusal, campaign delete cascade.
- `src/backend/tests/access/test_registry_property.py` -- specs/builders for the seven models.
- `src/backend/tests/access/test_world_registry.py` -- unit tests for floor, endpoint narrowing, change-field rules, Entity Party rendering.
- `src/backend/tests/ev4/test_world_rows.py` -- EV-4: copied Entities and rows invisible to player, anon_share, cross_gm_player; GM positive control.
- `src/backend/tests/test_legacy_frozen.py` -- AD-18 freeze ratchet: no module outside the shrink-only allowlist writes `npcs`/`quests`.
- `docs/UPGRADING.md` -- release note text from the AC.

**Acceptance Criteria:**
- Given CI, when backend-tests and gates run, then the full suite (incl. CI-6/7/8/10/11/12) passes with no regression.
- Given the seeded snapshot, when upgraded to head, then every seeded NPC and Quest has exactly one Entity with no field lost, all are `gm`, and the faction NPC is a Faction.
- Given the revision, when downgraded to `cf62d979bc8a`, then exactly the seven tables and two FKs are gone and `npcs`/`quests` are unchanged.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 43 findings — high 0, medium 17, low 17, false 9, maybe-false 0 (blind 15, verification-gap 4, edge 16, intent 8)
- findings:
  - `[medium]` `[defer]` (blind) new Campaigns get no relationship types — real; campaign creation is outside this story's AC (seeding is "when the revision runs"); deferred to E3.1/E0-WorldCore.5.
  - `[medium]` `[defer]` (blind) legacy rows written after the upgrade never reach entities — real and known (Design Notes); E0-WorldCore.6 re-applies DATA_STEPS; deferred with a release-coupling note.
  - `[low]` `[patch]` (blind) UPGRADING.md omits faction alive → active — doc corrected. "publish from World" sentence is the AC's verbatim release-note text: kept.
  - `[medium]` `[patch]` (blind) Party schema exposes merged_into_id — removed from EntityPartyResponse. Attribute/history entity-ref ids: `[medium]` `[defer]` to E0-WorldCore.5 (no copied Entity carries refs).
  - `[medium]` `[patch]` (blind) history rows with field NULL are PUBLIC; migrated row exposes legacy_id — field NULL is now GM unless op = migrated; migrated new_value no longer carries legacy_id.
  - `[medium]` `[patch]` (blind) whole-`attributes` / `attributes.x` changes bypass hiding — change narrowed by field_visibility of its top-level column too. Whole-blob vs `attributes.<key>` keys: `[low]` `[reject]` set_visibility only writes column-name keys today, so attribute sub-keys cannot exist. `visibility` change being Public: `[false]` `[reject]` a Party Entity's publish history reveals nothing hidden.
  - `[medium]` `[defer]` (blind) hiding `aliases` does not hide alias rows — real; alias reads belong to E0-WorldCore.5, which must add the rule.
  - `[low]` `[patch]` (blind) hidden required field (name) makes Party validation fail — required fields are no longer blanked (name is never hidden).
  - `[medium]` `[defer]` (blind) soft-deleted/merged Entities stay visible — no delete/merge path exists until E0-WorldCore.3/.9; deferred.
  - `[low]` `[patch]` (blind) hidden Quest status leaks via completed_at — completed_at dropped when status is hidden.
  - `[low]` `[patch]` (blind) unindexed SET NULL scans on journal delete — indexes on the three source_journal_id columns added; entity hard-deletes are campaign cascades only (rest rejected, low).
  - `[medium]` `[patch]` (blind) EV-4 never projects derived world rows — same root cause as the verification-gap finding; DB projection test added.
  - `[low]` `[reject]` (blind) freeze detector misses add_all/merge/bulk/f-string SQL — best-effort ratchet; extending it adds complexity for an unlikely bypass.
  - `[low]` `[patch]` (blind) chat trigger only on campaign_id updates — trigger now also on npc_entity_id updates. CHECK alternative: `[false]` would make campaign delete (SET NULL campaign_id) fail.
  - `[low]` `[patch]` (blind) downgrade deletes a backfill row it may not have inserted — now deletes only an untouched queued row.
  - `[medium]` `[patch]` (verification-gap) no test loads relationship/alias/mention/step/change parents via their `attr`s and projects — DB test added (GM succeeds, Player not_found with a gm endpoint/floor, attr-loaded audience_of equals the parents= oracle).
  - `[low]` `[patch]` (verification-gap other) check_create ignores floor/narrowed_by — applied both.
  - `[low]` `[patch]` (verification-gap other) hidden required Party field — same root cause as blind row 8.
  - `[medium]` `[patch]` (verification-gap other) migrated row legacy_id visible after publish — same root cause as blind row 5.
  - `[low]` `[patch]` (edge) check_create floor/endpoints — same as verification-gap other row 1.
  - `[false]` `[reject]` (edge) project(EntityRelationship) without loaded endpoints raises ValueError — a loud programming error documented in _check_row, not a leak or a reachable user path (no route reads edges yet).
  - `[low]` `[patch]` (edge) hidden required field — same as blind row 8.
  - `[low]` `[patch]` (edge) non-mapping attributes crash projection — CHECK jsonb_typeof(attributes)='object' (and field_visibility) added.
  - `[medium]` `[patch]` (edge) field='attributes' while attributes.<key> hidden — same root cause as blind row 6.
  - `[medium]` `[patch]` (edge) field NULL snapshot changes PUBLIC — same as blind row 5.
  - `[medium]` `[patch]` (edge) migrated legacy_id exposed — same as blind row 5.
  - `[low]` `[patch]` (edge) sources.field_visible raises on a bogus Visibility — now hidden (fail closed).
  - `[medium]` `[patch]` (edge) Party sees deleted Entities / hidden merge target id — merged_into_id removed (blind row 4); deleted part deferred with blind row 9.
  - `[low]` `[reject]` (edge) quest_steps may point at a non-Quest — no writer exists; E0-WorldCore.3's apply_change validates the target type; a trigger adds complexity.
  - `[low]` `[reject]` (edge) self-merge/self-loop/inverted span CHECKs — no writer yet; apply_change (E0-WorldCore.3/.9) validates; not met in everyday use.
  - `[medium]` `[patch]` (edge) existing non-NULL pc_entity_id/npc_entity_id would abort the boot at ADD CONSTRAINT — dangling values NULLed first (no app code writes them, but a crash loop on boot is intolerable).
  - `[low]` `[patch]` (edge) downgrade leaves dangling links — downgrade NULLs both columns.
  - `[low]` `[patch]` (edge) downgrade deletes a pre-existing backfill row — same as blind row 15.
  - `[medium]` `[defer]` (edge) new Campaigns lack relationship types — same as blind row 1.
  - `[low]` `[reject]` (edge) trigger silently drops npc_entity_id on a campaign-less insert — that is the stated rule ("a chat without a Campaign has no NPC"); no caller writes it.
  - `[false]` `[reject]` (intent) freeze is a source ratchet, not a runtime failure — Design Notes choice: a strict freeze breaks the legacy NPC/Quest UI until E0-WorldCore.6 (which owns the adapters); release coupling recorded as deferred.
  - `[false]` `[reject]` (intent) relationship_types registered membership, not stored — the AC's own column list has no Visibility column, so `stored` is unrealizable; decision recorded in Design Notes.
  - `[false]` `[reject]` (intent) boot tested through alembic command, not the web start command — the start command runs the same `alembic upgrade head`; CI-6 tests the chain, as E0-QA.6 established.
  - `[false]` `[reject]` (intent) snapshot regenerated — the schema is unchanged and the seed only gained rows needed to prove faction mapping and notes; the regenerated dump differs only by those rows.
  - `[false]` `[reject]` (intent) idempotency shown on seed/adversarial data, not production data — production data is not available to CI; the desktop adversarial run covers the hostile shapes.
  - `[false]` `[reject]` (intent) migration CHECKs use frozen enum copies — the established precedent (cf62d979bc8a); CI-10 proves they match domain/enums.py.
  - `[false]` `[reject]` (intent) additions beyond the AC (chat FK + trigger, projections, endpoint narrowing) — chat FK is AD-19's deferred F1-core FK; projections are the E0-Access.4 carry-over; endpoint narrowing implements FR-25 at the registry.
  - `[low]` `[reject]` (intent) EV-4 checks the access layer, not HTTP — no Entity route exists in this story; the scoped_select/project layer is the surface every future route uses.

## Design Notes

`relationship_types` is listed `stored` in the AC, but its AC column list has no Visibility column; it is a per-Campaign vocabulary like `character_sheet_templates`, so it is registered `membership(PUBLIC)` (constant Audience). Relationship edges are `stored` but also narrowed by both endpoints, so a Party edge can never reveal a GM-only Entity (FR-25) and the merge `visibility_floor` has meaning.

`migrated` history row: `field NULL`, `new_value {"from": "npcs"|"quests", "legacy_id": …}`, actor = Campaign Owner, `created_at` = the legacy row's `created_at` (deterministic, sorts first).

Freeze (AD-18): the AC's "a test fails when any service writes" is a ratchet: today's writers (legacy routes, demo seeder) are an allowlist that E0-WorldCore.6 empties; a new writer fails. Rows written through them after the upgrade are not in `entities` until E0-WorldCore.6 re-applies `DATA_STEPS` (idempotent) — release note for the orchestrator: do not ship WorldCore.2 without WorldCore.6. New Campaigns get no default relationship types until E3.1/WorldCore.5 adds them on create.

## Verification

**Commands:**
- `python scripts/check_table_owners.py && python scripts/check_scoped_queries.py` -- expected: exit 0.
- Desktop (own pg16 + valkey containers, `lorekeeper-backend-test`): `python -m pytest -q -p no:cacheprovider` -- expected: all pass.
- GitHub CI on the draft PR -- expected: green.

## Auto Run Result

Status: done

**Summary:** Revision `03c0b504f1d1` (on `cf62d979bc8a`) creates `entities`, `entity_aliases`, `entity_mentions`, `relationship_types`, `entity_relationships`, `quest_steps`, `entity_changes` with composite Entity FKs, CHECKs from frozen copies of the domain enums, `ON DELETE SET NULL (col)` for nullable Entity links, the deferred `character_sheets.pc_entity_id` / `chat_sessions.npc_entity_id` FKs (dangling values NULLed first; chat trigger clears the NPC of a campaign-less chat), and an idempotent, deterministic (md5 ids) set-based copy: NPCs/Quests to GM-only Entities (faction role to Faction, notes to gm_notes, completed_at stamped), one `migrated` history row each, six default relationship types per Campaign, and `data_backfills('suggested_mentions_v1', 'queued')`. Models in `app/db/models/entity.py`; access registry gains `floor`, `narrowed_by`, `owner_field=None`, the `parent_field` change rule and GM-visible orphans; GM/Party projections in `app/schemas/entities.py`.

**Files:**
- `src/backend/migrations/versions/03c0b504f1d1_f3_world_entities_legacy_copy.py` -- the F3-world revision and copy (`DATA_STEPS`).
- `src/backend/app/db/models/entity.py`, `__init__.py`, `character_sheet.py`, `chat.py` -- seven models, deferred FKs.
- `src/backend/app/access/registry.py`, `projection.py`, `sources.py` -- registrations, new registry options, Entity Party rendering, check_create narrowing.
- `src/backend/app/schemas/entities.py` -- GM/Party schema pairs.
- `src/backend/scripts/make_snapshot.py`, `tests/fixtures/snapshot_a3e7c1f9d258.sql` -- seed gains a faction NPC, notes, descriptions.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- F3 post-upgrade checks, constraint-level FK table, idempotency, downgrade.
- `src/backend/tests/migrations/test_world_copy_adversarial.py` -- duplicates, faction with quest text, unicode, empty notes, zero-NPC Campaign, unmappable enum value, cross-Campaign refusal, Campaign delete, dangling links.
- `src/backend/tests/access/test_registry_property.py`, `test_world_registry.py`, `test_audience.py` -- CI-11 over the new models, rule unit tests.
- `src/backend/tests/ev4/test_world_rows.py` -- EV-4: copied rows invisible to player, anon_share, cross_gm_player; loaded projections.
- `src/backend/tests/test_legacy_frozen.py` -- AD-18 freeze ratchet.
- `src/backend/tests/test_enum_check_sync.py` -- five enums moved to ENUM_CHECKS.
- `docs/UPGRADING.md` -- release note.

**Review:** 43 findings (blind 15, verification-gap 4, edge 16, intent 8). Patched 12 root causes (medium: history field-NULL / legacy_id exposure, dotted-field narrowing, merged_into_id in Party schema, boot-safety cleanup before deferred FKs, projected-row verification gap; low: required hidden field, completed_at leak, check_create narrowing, sources fail-closed, JSONB object CHECKs, journal indexes, trigger columns, downgrade backfill guard, UPGRADING faction mapping). Deferred 5 (relationship types for new Campaigns, legacy writes after upgrade until WorldCore.6, aliases field hiding, deleted/merged Entity audience, entity-ref ids in Party output). Rejected the rest with reasons in the triage log.

**Follow-up review:** false (no high patched; medium patches each have direct tests).

**Verification:** desktop full suite on own pg16 + valkey containers after rebasing on main (incl. E0-Access.10, E0-Jobs.8): 1820 passed, 90 skipped (VALKEY_TEST_URL-gated and pre-existing skips), EV-4 probes=85 pending=46 leaks=0. `check_table_owners.py`, `check_scoped_queries.py` OK; lint-imports 5 contracts kept. GitHub CI on the draft PR.

**Residual risks / carry-overs:** do not release WorldCore.2 without WorldCore.6 (legacy writers stay live); E0-WorldCore.3 must register `apply_change` as the Entity tables' `writer` and a set_visibility kind; projecting an `EntityRelationship` needs `source_entity`/`target_entity` loaded.

**Needs desktop verification:** none beyond what ran (the desktop was online for this story).

