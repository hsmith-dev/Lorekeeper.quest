---
title: 'E0-WorldCore.6: Legacy NPC and Quest adapters and old-link resolver'
type: 'feature'
created: '2026-11-21'
status: 'in-progress'
baseline_revision: '9b0f01a437d70660905892cede406e07943553c9'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-5-entity-api-gm-party-projections.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-2-f3-world-migration-legacy-npc-quest-copy.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** After F3-world copied `npcs`/`quests` into `entities`, the old NPC and Quest pages still read and write the legacy tables, so the two stores drift: rows created, edited or deleted on the old pages after the copy never reach the World, and anything made in the World never shows on the old pages. Old NPC/Quest links have no way to find their Entity. This is a v1.2 release blocker.

**Approach:** (1) Turn `api/routes/npcs.py` and `quests.py` into adapters over `entities` (same paths and legacy response shapes; reads through `scoped_select` + `project`; every write through `world_service.apply_change`). (2) Add `GET /api/entities/legacy/{npc|quest}/{id}`. (3) Re-copy what drifted with a one-shot `data_backfills` job `legacy_resync_v1` that reconciles every Campaign through `apply_change` as its Owner, under a three-way, privacy-first rule. (4) Empty the AD-18 freeze allowlist (the demo seeder writes Entities too).

## Boundaries & Constraints

**Always:**
- Owner decision (OD-1 A, privacy first): legacy NPCs and Quests stay GM-only. Every Entity the resync creates is `visibility = gm`, `field_visibility = {}`. The resync never changes visibility and never applies a legacy edit to an Entity that is not GM-only (except `gm_notes`, which is always GM); it records a GM-only `canon_note` instead.
- Every Canon write (adapters, resync, seeder) goes through `world_service.apply_change`. No raw SQL or ORM writes to `entities`/`entity_changes`; `npcs`/`quests` are never written or deleted by anything under `app/` or `scripts/` (ratchet allowlist empty).
- `world_service.py` edits are additive and small (siblings E0-WorldCore.7/.9 edit it): only the `CreateEntity` legacy-id pass-through.
- Reads via `scoped_select`/`scoped_get`; response bodies built only from `access.project(...)` output (a Party body is derived from the projected `EntityPartyResponse`, so it can never hold `gm_notes`); uniform `not_found()` for hidden ≡ missing ≡ wrong type ≡ deleted ≡ merged (item routes) ≡ other Campaign. CI-8 with no baseline growth; EV-4 `pending_baseline.txt` must not grow.
- Ids: a GM sees a copied Entity under its `legacy_npc_id`/`legacy_quest_id`, and any other Entity under its Entity id. Every item route accepts either id. A non-GM always gets Entity ids (Party schemas carry no legacy ids).
- Status maps: Character `alive→alive`, `deceased→dead`, `missing→unknown`, `unknown→unknown`; Faction `active→alive`, `disbanded→dead`, `unknown→unknown`; role: Character kind `npc→npc`, `pc→pc`, `creature→monster`, Faction → `faction`. Quest status is identical. Writes map the other way exactly as F3 (`dead→deceased`, faction `alive→active`/`dead→disbanded`, `monster→creature`). Locations and Items never appear in `/npcs`.
- The new Alembic revision sits on head `0f1c3b194a4b`, holds only set-based SQL, has a working downgrade.

**Never:**
- No frontend changes (pages keep working unchanged). No share-route (`/api/share/...`) changes, no `feedback.py` changes (admin raw selects; deferred). No Mention backfill/confirm (E0-WorldCore.7), no merge route (E0-WorldCore.9).
- Never modify or delete legacy rows; never copy legacy visibility; never change an Entity's type.
- Do not edit `sprint-status.yaml`, `epics.md`, `desktop-verification-queue.md`, `scripts/scoped_queries_baseline.txt`; do not commit `epic-*-context.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM lists after upgrade | copied NPC (legacy id L), new Character E2, a Location | `/api/npcs/` = both NPC rows in legacy `NpcGMResponse` shape, ids `L` and `E2.id`, ordered by name; no Location | — |
| Player lists | only GM-only Entities | `[]`; after publishing one Character: exactly it, `NpcPartyResponse` (no `notes`, no timestamps), Entity id | — |
| Hidden status | published Character, `status` hidden | Party `status: "unknown"` (same as unset) | — |
| GM create | `POST /api/npcs/ {role: faction, status: dead}` | 201, Faction `disbanded`, `role: faction`, `status: dead`, id = Entity id, one `create_entity` row | — |
| GM update | `PUT` with unchanged role/status plus new name | only `update_field name` written; a `missing` Character sent `status: unknown` stays `missing` | role character↔faction → 422 `{detail, code: "invalid"}`, nothing written |
| Player write | any POST/PUT/DELETE | uniform 404, nothing written | — |
| Delete | GM `DELETE /api/npcs/{L}` | 204, `delete_entity` (soft); later GET → 404 | — |
| `/entries` | confirmed + unconfirmed Mentions | only confirmed Mentions' entries visible to ctx (Mention audience), newest first, max 20, LITE | — |
| Resolver | `GET /api/entities/legacy/npc/{L}` | `{entity_id, type}`; merged → visible survivor | hidden/missing/deleted/wrong kind → 404 `{"detail":"Not found"}` |
| Resync: legacy-only edit | legacy name changed after copy, Entity GM-only, `name` untouched in World | `update_field name` by the Owner | — |
| Resync: both sides | legacy and World both changed `description` differently | World kept; one `canon_note` with the legacy value | — |
| Resync: published | Entity `party`, legacy description changed | not applied; `canon_note` | — |
| Resync: new legacy row | NPC created on the old page after the copy | GM-only Entity, id `md5('f3-world:npc:'‖id)`, `legacy_npc_id` set | — |
| Resync: legacy deleted | legacy row gone, Entity has only its `migrated` row | `delete_entity` | Entity touched in World → kept + `canon_note` |
| Resync: fresh upgrade | v1.1 → v1.2 in one boot | zero new `entity_changes` rows | — |
| Resync re-run / crash | step fails or job retried | no duplicate writes (idempotent ops, cursor per step) | retries per step |

</intent-contract>

## Code Map

Backend root `src/backend/`. DB tests run only in CI (desktop may be offline). Light venv: `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/wc5venv/bin/python` (stubs for heavy imports: `scratchpad/stubimport.py`, `scratchpad/wc5stub`). Put new scratch files under `scratchpad/wc6/`.

- `app/api/routes/npcs.py`, `app/api/routes/quests.py` -- the legacy routes to convert (list, create, put, delete, get, entries, generate, extract / suggest). `_npc_gm = require_campaign_for(NpcEntry, ...)` must become an Entity-or-legacy-id resolver. Keep `NPC_EXTRACT_MAX_CHARS`, LLM metering, `_visible_*` dependency order (404 before LLM 402).
- `app/schemas/npc.py`, `app/schemas/quest.py` -- legacy shapes; drop `created_at`/`updated_at` from `NpcPartyResponse`/`QuestPartyResponse` (privacy: WC.5 removed them from `EntityPartyResponse`; no Player ever received legacy rows).
- `app/access/context.py` L308 `require_campaign_for` (uses `db.get(model, id)`) -- add an additive sibling for Entities that resolves the Campaign from `Entity.id == x OR Entity.legacy_npc_id/legacy_quest_id == x` (raw select is allowed inside `app/access/`). Export via `app/access/__init__.py`.
- `app/access/projection.py` L375 `project(obj, ctx, ...) -> BaseModel` (EntityGM/PartyResponse; applies `field_visibility` and Party unset values). Use `project_all` for lists (ENTITY_REF ids). 
- `app/schemas/entities.py` L278 `CreateEntity` -- add `legacy_npc_id`/`legacy_quest_id: UUID | None = None` (at most one; npc → character/faction, quest → quest; validated). `EntityCreate` (HTTP body) must NOT get them.
- `app/services/world_service.py` L524 `_create_entity` -- pass the two legacy ids into `Entity(...)`; `_entity()` L347 takes `FOR UPDATE`. Ops available: `UpdateField(field ∈ name|description|gm_notes|attributes.<k>)`, `SetStatus`, `SetKind`, `DeleteEntity`, `CanonNote(note)` (field NULL → GM-only, idempotent by note text). `CanonChangeError.code`.
- `app/api/routes/entities.py` L81 `_canon_error` / L89 commit helper -- error mapping to reuse (import it or a tiny shared helper; do not restructure entities.py, siblings edit it).
- `app/db/models/entity.py` -- `Entity` (`legacy_npc_id`, `legacy_quest_id` unique, `deleted_at`, `merged_into_id`, `gm_notes`, `kind`, `type`), `EntityMention` (`confirmed`, `journal_id`, `entity_id`), `EntityChange` (`op`, `field`, `old_value`, `created_at`).
- `app/domain/entity_types.py` -- statuses (Character alive/missing/unknown/deceased; Faction active/disbanded/unknown; Quest active/completed/failed/abandoned), `default_status`, `status_category`.
- `migrations/versions/03c0b504f1d1_f3_world_entities_legacy_copy.py` L160–262 -- id namespace `f3-world` (`md5('f3-world:npc:' || id)::uuid`), the copy's value mapping (`_NPC_KIND`, `_CHARACTER_STATUS`, `_FACTION_STATUS`, `_QUEST_STATUS`; Quest completed → `attributes.completed_at` = `updated_at`), downgrade pattern for a backfill row (delete only while untouched).
- `migrations/versions/0f1c3b194a4b_entity_changes_write_visibility.py` -- current head; header style.
- `app/jobs/backfill.py` -- `run_cursor`, `CursorStep`, `register_backfill`, runner (Owner ctx per Campaign, key `backfill:{name}:{cid}`); `app/jobs/files_gc.py` L51 -- handler template; `app/jobs/registry.py` L55 `JobKind`, L120 `KIND_MODULES` (add the new module; `tests/jobs/test_worker.py` checks it).
- `app/api/routes/session_plans.py` L66–79 -- reads `Quest`/`NpcEntry` for the plan prompt; switch to Entities (frozen tables would make it stale).
- `scripts/seed_demo.py` L362–384 -- writes `NpcEntry`/`Quest`; move to `apply_change(CreateEntity)` with `ctx_for(session, user.id, campaign.id)`; idempotent by live (type, name). `tests/seeds/test_demo_seed.py` L52, L211–276 assert legacy rows: update to Entities.
- `tests/test_legacy_frozen.py` -- `LEGACY_WRITERS` → `{}`, `FROZEN_CEILING` → `frozenset()`; docstring updated.
- `tests/ev4/probes/npcs.py`, `quests.py`, `retrieval.py` L165–195, `write_rules.py` L110, `ai_routes.py` L89–96, `probes/__init__.py` L16 -- existing probes; they use `ev4.a.ids["npcs"]` (legacy rows only, no Entity) and `_support.add_npc/add_quest` (legacy writes). Make them hit real GM-only Entities: a helper creating, through `apply_change`, the Entity of a seeded legacy row (deterministic id + legacy id, canary text) and new GM-only Entities. `tests/ev4/test_world_rows.py` L44 `_copy` runs F3 `DATA_STEPS`.
- `tests/ev4/registry.py` -- probes auto-discovered from `tests/ev4/probes/*`; `test_coverage.py` fails on any unprobed route.
- `tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check(REV)`, single-head test, downgrade-test pattern.
- `nginx/locations.conf` -- `location /api/entities/` already exists (covers the resolver).
- `docs/UPGRADING.md` -- release note to extend.

## Tasks & Acceptance

**Execution:**
- `app/access/context.py` (+ `__init__.py`) -- `require_campaign_for_entity(id_param, min_role="player", *, legacy: Literal["npc","quest"] | None = None)`: same contract as `require_campaign_for` (non-UUID, missing, too-low Role → `not_found()`, preview narrows), matching `Entity.id` or the chosen legacy column.
- `app/schemas/entities.py`, `app/services/world_service.py` -- `CreateEntity` legacy ids (validator: at most one; type compatible) passed to the new row; docstring line.
- `app/api/routes/_legacy_world.py` (new) -- shared adapter helpers: id lookup `legacy_entity(db, ctx, id, kind)` (scoped, types `{character, faction}` or `{quest}`, live only, else `not_found()`), the status/role maps both ways, `as_npc(projected, entity, ctx)` / `as_quest(...)` building the legacy GM or Party schema from `project()` output (GM: `id = legacy id or entity id`, `notes = gm_notes`, timestamps; Party: Entity id, no notes/timestamps), `legacy_writes(...)` turning a legacy body into `CanonChange`s that skip fields whose legacy view would not change, and `confirmed_entries(db, ctx, entity)`.
- `app/api/routes/npcs.py`, `quests.py` -- adapters. List: `scoped_select(Entity, ctx)` live rows of the types, `project_all`, then map; order NPCs by `(lower(name), id)`; Quests GM by `(status order active,completed,failed,abandoned; created_at desc; id)`, non-GM by `(projected status order, lower(name), id)` (no hidden value or timestamp drives a Party ranking). Create/put/delete: `apply_change` + one commit, rollback and `_canon_error` mapping on `CanonChangeError`; create 201. Entries: confirmed Mentions (`scoped_select(EntityMention, ctx)`) → `scoped_select(JournalEntry, ctx).where(id IN ...)` newest first (`created_at desc, id`), limit 20, `variant=LITE`; no ILIKE. Generate/extract/suggest: same behaviour, Entity data (generate reads name and mapped role; extract excludes names of live Characters/Factions visible to the GM).
- `app/schemas/npc.py`, `quest.py` -- Party schemas without timestamps; update comments.
- `app/api/routes/entity_legacy.py` (new; mounted in `app/main.py` at prefix `/api/entities` before `entities.router`) -- `GET /legacy/{legacy_type}/{legacy_id}` (`legacy_type` ∈ `npc|quest` else 404; `openapi_extra=PARTY_READ`): resolve via `require_campaign_for_entity(..., "player")`, follow `merged_into_id` (≤ 10 hops, cycle-safe) on the scoped rows, return `{"entity_id", "type"}` of the first live survivor ctx can see via `scoped_select`, else `not_found()`. Schema `LegacyLinkResponse` in the new module.
- `app/jobs/legacy_resync.py` (new; add to `KIND_MODULES`) -- `register(JobKind(name="backfill.legacy_resync", queue=BACKFILL, timeout_s=120, resources={}, live_safe=True, result_audience="gm"))` + `register_backfill("legacy_resync_v1", ...)`; handler `run_cursor` in three phases (cursor `{"phase", "after"}`): `entity` (each copied Entity by id), `npc`, `quest` (legacy rows with no Entity, by id). See Design Notes for the rules.
- `migrations/versions/9c4fbee4bdd1_legacy_resync_backfill.py` (new, `down_revision = '0f1c3b194a4b'`) -- `INSERT INTO data_backfills (name, status) VALUES ('legacy_resync_v1', 'queued') ON CONFLICT (name) DO NOTHING`; downgrade deletes it only while `queued` with `job_id` and `cursor` NULL. Docstring carries the data-safety summary.
- `app/api/routes/session_plans.py` -- open Quests = live `quest` Entities with status `active` (newest first, 10); NPC names = live Character/Faction Entities (`updated_at desc`, 15).
- `scripts/seed_demo.py`, `tests/seeds/test_demo_seed.py` -- seeder writes Entities through `apply_change`; counts and the no-GM-secret check use Entities and `project()` for a Party ctx.
- `tests/test_legacy_frozen.py` -- empty allowlist and ceiling.
- `tests/test_legacy_adapters.py` (new) -- GM/Player route behaviour of the matrix (ids, maps both ways, skip-unchanged, 422 type change, soft delete, entries, Location/Item excluded, deleted/merged 404, generate/extract read Entities with the fake LLM/NER).
- `tests/jobs/test_legacy_resync.py` (new) -- every resync row of the matrix, plus: idempotent re-run (second run writes nothing), crash mid-Campaign resumes without duplicates, runner end-to-end (`run_backfills` → row `done`), fresh-upgrade no-op on F3-copied data, legacy rows never modified (compare before/after).
- `tests/ev4/probes/npcs.py`, `quests.py`, `retrieval.py`, `write_rules.py`, `ai_routes.py`, `__init__.py`, `_support.py` -- probes against GM-only Entities (canary-bearing), Player sees `[]`, counts/ranking unchanged by a GM-only create, Player writes 404 with Entity rows unchanged, published Entity with hidden status equals unset.
- `tests/ev4/probes/entity_legacy.py` (new) -- resolver: hidden ≡ missing (GM-only, deleted, missing, other Campaign, wrong kind), merged → survivor only when visible, audience ladder, GM positive control.
- `tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check('9c4fbee4bdd1')` (row queued) and a downgrade test (row gone, re-upgrade restores it).
- `docs/UPGRADING.md` -- old NPC/Quest pages now show World data; edits made on them after the F3 copy are re-copied once; conflicts kept as GM-only notes.

**Acceptance Criteria:**
- Given CI, when `backend-tests.yml` and `gates.yml` run, then all pass (CI-2, CI-3, CI-7, CI-8 with no baseline growth, CI-10, CI-11, CI-12 with zero leaks and no `pending_baseline.txt` growth, single head, drift, snapshot upgrade and downgrade).
- Given any module under `app/` or `scripts/`, when `tests/test_legacy_frozen.py` runs, then none writes `npcs`/`quests` (allowlist empty).
- Given `frontend` unchanged, when `CharactersPage`/`QuestsPage` call the adapters as a GM, then every field they read (`id, campaign_id, name, role, status, description, notes, created_at, updated_at` / `title`) is present with legacy enum values.

## Design Notes

**Resync rule (per copied Entity E with legacy row L, Owner GM ctx, E locked `FOR UPDATE` first).** Fields compared: `name` (Quest `title`), `description`, `gm_notes` (`notes`), `status` (mapped exactly like F3), `kind` (Characters), and type (role faction ↔ character). For field f: `legacy = map(L.f)`, `current = E.f`, `rows = E's entity_changes with field = f` (any op, incl. revert). If `legacy == current` → nothing. Else if `rows` empty (World never touched f) → apply (`UpdateField`/`SetStatus`/`SetKind`), but only when `E.visibility == gm` or f is `gm_notes`. Else `base = rows[0].old_value` (status rows may hold `{status, ...}`: compare the status) — if `legacy == base`, the old page did not change f → nothing; otherwise both sides changed → World wins. Every not-applied legacy change (both-sides, non-GM-only Entity, type change) goes into one `canon_note` per Entity: `"Old NPC page edit not applied (World version kept): description = '…'; status = dead"`. A Quest moved into `completed` by the resync also gets `UpdateField("attributes.completed_at", L.updated_at ISO UTC)` so it matches the F3 rule. E deleted or merged → skip. L missing: `delete_entity` when E's only history row is `migrated`, else a `canon_note` ("Deleted on the old NPC page; kept because it was changed in World").

**Phases 2–3:** legacy rows with no Entity (`legacy_*_id`) get `CreateEntity(entity_id=uuid(md5("f3-world:npc:"+id)), legacy_npc_id=id, type/kind/status/gm_notes mapped, attributes {completed_at} for completed Quests)`, GM-only by default.

**Data safety (for the independent review).**
- *Idempotency:* the migration is one `INSERT … ON CONFLICT DO NOTHING`. Each resync step's writes and its cursor commit together; re-running a step finds `legacy == current` (or the same `canon_note`, which `apply_change` treats as a repeat) and writes nothing; creates use the F3 deterministic id, so `apply_change` returns the earlier create, and `uq_entities_legacy_*` is the backstop.
- *Re-run safety:* the backfill row runs once (`done`). A manual re-run (row reset to `queued`) is a no-op on already-synced data. Re-applying F3 `DATA_STEPS` afterwards inserts nothing (same ids, `NOT EXISTS` on legacy id).
- *Edited on both sides:* World wins; the legacy value is preserved in the untouched legacy row and quoted in a GM-only `canon_note`. Nothing is published, nothing deleted that the World touched.
- *Locks / rewrites:* no DDL, no table rewrite; the migration takes one row lock in `data_backfills`. The job locks one Entity row per step (`FOR UPDATE`) in a short transaction; legacy rows are read unlocked (no writer remains after this release). A GM edit via the adapters or the World API during the resync is serialized by the row lock and then counts as a World change.
- *Downgrade:* Alembic downgrade removes only an untouched queued row; Entities written by the resync stay (forward-only, NFR-8) and each write is a normal history row the GM can revert. Running the pre-.6 image again shows the frozen legacy rows; edits made through the adapters live only in `entities`.
- *Gap:* between boot and the job finishing (first reaper pass at worker start, seconds per Campaign), the old pages show the World state; affects only installs that ran F3 before this release.

**Why a job, not SQL:** the owner rule that every Canon write goes through `apply_change` (history, write-time visibility, hooks), and the three-way comparison needs history; set-based SQL would bypass both.

## Verification

**Commands** (from `src/backend`, light venv; no database on this Mac):
- `python -m compileall -q app tests migrations scripts` -- expected: no errors
- `PYTHONPATH=. lint-imports --no-cache` -- expected: all contracts kept
- `python ../../scripts/check_scoped_queries.py && python ../../scripts/check_table_owners.py` -- expected: exit 0, no baseline line
- `python -m pytest --noconftest tests/test_legacy_frozen.py -q` -- expected: pass
- `import app.main` with heavy deps stubbed -- expected: imports; EV-4 coverage check finds every route probed
- `alembic heads` -- expected: one head `9c4fbee4bdd1`
- GitHub CI on the draft PR -- expected: backend-tests, gates, frontend-ci, license-check green

## Spec Change Log

## Review Triage Log
