---
title: 'E0-WorldCore.5: Entity API with GM and Party projections'
type: 'feature'
created: '2026-11-20'
status: 'in-review'
baseline_revision: '0d71955bfb4845679b134717f820267a0d79656d'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-worldcore-3-apply-change-history-and-revert.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Player history keeps `attributes.<ref>` rows with null values when the referenced Entity is hidden.
    evidence: |-
      No id leaks (values are nulled), but the row shows a hidden reference was set; hiding such rows changes history semantics. E0-WorldCore.11 (history UI) should decide.
    location: >-
      src/backend/app/access/projection.py
    severity: low
  - summary: >-
      Non-GM list with a status filter (and any q search) loads and projects every matching Entity, then paginates in Python; q keeps only the top 100 candidates.
    evidence: |-
      Correct and leak-free, but O(Campaign) per request; SQL-side filtering of hidden status needs field_visibility-aware SQL.
    location: >-
      src/backend/app/api/routes/entities.py list_entities
    severity: medium
  - summary: >-
      Duplicate-name check on create is check-then-insert without a lock.
    evidence: |-
      Two concurrent GM creates of the same normalized name and type can both pass; needs pg_advisory_xact_lock(campaign, type) or a unique index on a normalized-name column.
    location: >-
      src/backend/app/api/routes/entities.py create_entity
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The World Model (entities, aliases, steps, history) has a write path (`world_service.apply_change`) but no HTTP API, so GMs cannot edit their world and Players cannot read what was published. Four leaks/gaps are also open: history written while an Entity or field was hidden becomes readable once it is published; `aliases` cannot be hidden; ENTITY_REF attribute values (and their history) show ids of Entities the viewer cannot see; and new Campaigns get no relationship types.

**Approach:** Add `api/routes/entities.py` (the story's 13 routes) on top of `apply_change`, `scoped_select`/`scoped_get`, `project_all` and `set_visibility`. Record each history row's write-time visibility in a new `entity_changes.write_visibility` column (migration, every existing row backfilled `gm`) and narrow history by it as a registry floor. Make `aliases` hideable and make alias rows follow it. Redact ENTITY_REF ids in `access.project`. Register the `entity_field` source resolver. Default relationship types for new Campaigns stay with E3.1 (its first AC seeds them lazily on the first GM read).

## Boundaries & Constraints

**Always:**
- Every Canon write goes through `world_service.apply_change` / `revert_change`, every Visibility write through `access.set_visibility` / `set_visibility_many`, every read through `scoped_select` / `scoped_get` (no raw selects on registered tables outside `app/access/`, CI-8, no baseline lines), and every response body through `access.project` / `project_all`.
- Hidden, deleted (for non-GMs), merged (for non-GMs), missing, cross-Campaign and Player-forbidden all give the identical `404 {"detail":"Not found"}` (`access.not_found()`).
- Write-time audience: a history row is visible to a non-GM only when it was written while the row would already have been visible to that audience (both before and after the change) AND it is visible now. Fail closed: any row whose write-time state is unknown is `gm`.
- A non-GM never receives the id of an Entity it cannot see (in `attributes`, or in history `old_value`/`new_value`).
- Search on `q` uses `world_service.candidates(db, ctx, ...)` (db first).
- Migration sits on the single head `03c0b504f1d1`, has a working downgrade, is set-based, and passes the snapshot, FK-action, CI-7 and drift gates.

**Never:**
- No frontend work (E0-WorldCore.10), no share-link (`/api/share/...`) entity routes, no relationship or relationship-type routes (E3.1), no Mention confirm/remove routes (E0-WorldCore.7), no merge route (E0-WorldCore.9).
- Do not edit `sprint-status.yaml`, `epics.md`, `desktop-verification-queue.md`, `scripts/scoped_queries_baseline.txt`, or the EV-4 `pending_baseline.txt` (except it must not grow).
- Do not take a Visibility value from `EntityPatch`/`EntityCreate`; do not let `PATCH` set `visibility`/`field_visibility`.
- Do not widen any existing rule to make a test pass; a failing leak test means the code is wrong.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Post-upgrade Player list | Campaign with only migrated GM-only Entities; Player `GET /api/entities/?campaign_id=` | `200 {"items":[],"total":0,"limit":50,"offset":0}`, byte-identical to a Campaign with no Entities | — |
| Player item reads | GM-only, deleted, nonexistent, other-Campaign id | identical `404 {"detail":"Not found"}` (same headers) | — |
| Publish then read | GM publishes 2 of 3 (bulk route) | Player list `total` 2, exactly those ids | — |
| Hidden field | Party Character with `status` hidden | Party body `status: "unknown"`, same as an unset status | — |
| Hidden aliases | Party Entity, `field_visibility.aliases = gm` | Party `aliases: []`; alias rows absent from every scoped read; alias history absent | — |
| Pre-publish history | GM-only Entity edited (canary), then published, then renamed | Player history shows only the rename (no canary, no publish row) | — |
| Pre-unhide history | Party Entity, `description` hidden, edited (canary), un-hidden | Player never sees the hidden-time description rows | — |
| Hidden ENTITY_REF | Party Quest whose `location_entity_id` names a GM-only Location | Party `attributes` lacks the key; history values for that field show `null`; the Location id appears nowhere in the body | — |
| Duplicate create | GM POSTs a name whose `normalize_name` equals a live visible Entity of the same type | `409 {"detail":"An Entity with this name exists","existing_id":"<id>"}` | only ctx-visible rows count |
| Player write | Player calls any write route (visible or hidden target) | `404 {"detail":"Not found"}`, nothing written | — |
| Canon errors (GM) | `superseded` / `deleted` / `merged` | `409 {"detail", "code"}` | `invalid`, `invalid_status`, `not_revertible` → `422 {"detail","code"}`; `not_found` → uniform 404 |
| Bulk visibility | > 500 ids, or any id missing/other Campaign | 422 (schema) / uniform 404, nothing written | all-or-nothing |

</intent-contract>

## Code Map

Backend root: `src/backend/`. Tests run against Postgres (CI); `tests/conftest.py` builds the schema from Alembic.

- `app/services/world_service.py` -- the only Canon writer. `_Run.history()` (~L265) is the single place `EntityChange` rows are built; `_entity()` (~L292) loads Entities with `FOR UPDATE`; `_create_entity` uses `run.add(Entity(...))`; `apply_change` (~L1156) runs each change in `db.begin_nested()` then `await db.flush()`; `HIDEABLE_FIELDS` (L127) gates `field_visibility.<key>` in `_visibility` (~L943); registrations at the bottom (`register_writer`, `register_visibility_kind`). `candidates`/`match_names` are re-exported here. `CanonChangeError.code` values: `invalid_status, not_found, merged, deleted, superseded, not_revertible, invalid`.
- `app/db/models/entity.py` -- `EntityChange` (L226). Add `write_visibility`. `VISIBILITY_ENUM` from `app.db.base`.
- `migrations/versions/03c0b504f1d1_f3_world_entities_legacy_copy.py` -- current single head; style reference (header docstring, `revision`/`down_revision` typed). Data step for `migrated` rows inserts without the new column (server default covers it).
- `app/access/registry.py` -- `Derived` (L175) and `derived()` (L272); `EntityAlias`/`EntityChange` registrations (L334–349); `_derived_clause` (L500), `_floor_clause` (L420), `_vis_clause` (L405), `audience_of` (L830), `parent_field_audience` (L953). `floor=` on `derived` already works for SQL and Python (NULL/`party` → Public, `gm`/`private` → GM).
- `app/access/projection.py` -- `project` (L327; sync), `project_all` (async; loads parents via `_value_field_parents`), `_apply_field_visibility`/`_render_entity_unset` (L264–325; already maps hidden `aliases` → `[]` when `aliases` is in `data`), `_redact_value_fields`. `data.update(extra)` currently runs after field visibility.
- `app/access/sources.py` -- `register_resolver(kind, fn, model=, where=)`, `field_visible` (rejects dotted fields today), `resolve_sources` calls `fn(row, ref)`.
- `app/access/visibility.py` -- `set_visibility(db, ctx, RecordRef, value)` returns the projected row; `set_visibility_many(db, ctx, refs, value) -> int`; `VisibilityError` (422 `{detail, code}`, handler registered in `app/main.py`).
- `app/access/context.py` -- `require_campaign(min_role)` (query/path `campaign_id`), `require_campaign_for(model, id_param, min_role)` (item routes; resolves Campaign from the row), `ctx_for_request(request, db, user, campaign_id, min_role)` (body `campaign_id`). Preview header narrows and refuses writes.
- `app/schemas/entities.py` -- GM/Party response pairs; `CanonChange` members (`CreateEntity`, `UpdateField`, `SetStatus`, `SetKind`, `AddAlias`, `RemoveAlias` (by alias text), `AddQuestStep`, `UpdateQuestStep`, `DeleteEntity`, `Revert`). `UPDATABLE_FIELDS = {name, description, gm_notes}`; attributes as `attributes.<key>`.
- `app/domain/entity_types.py` -- `attribute(type, key)` (`.value_kind`, `.label`), `ValueKind.ENTITY_REF`, `attribute_keys`, `party_unset` (`aliases → []`), `default_status` (Character/Location/Faction/Item `unknown`, Quest `active`). ENTITY_REF keys: `location_entity_id`, `parent_location_entity_id`, `headquarters_entity_id`, `leader_entity_id`, `holder_entity_id`, `giver_entity_id`.
- `app/domain/names.py` -- `normalize_name`.
- `app/services/world_matching.py` -- `candidates(db, ctx, surface, *, type=None, limit=3)` → `NameCandidate(entity_id, name, type, matched, score in (0,1], mention_count)`; `limit` 1..100. Already hides aliases of an Entity whose `aliases` field ctx may not see.
- `app/api/routes/character_sheets.py` -- route conventions to copy: `PARTY_READ` on GET routes (`app/api/deps.py`), `_GM_OR_PARTY` response docs, grouped counts via `scoped_select(...).with_only_columns(col, func.count(...)).group_by(col)`.
- `app/api/routes/visibility.py` -- bulk-visibility route pattern (commit/rollback).
- `app/main.py` (L151–182) -- mount: `app.include_router(entities.router, prefix="/api/entities", tags=["entities"], dependencies=gate)`.
- `nginx/locations.conf` -- generic `location /api/ { limit_req zone=api burst=20 nodelay; include /etc/nginx/proxy_common.conf; }` (L119). Add an explicit `location /api/entities/` with the same two lines just above it.
- `tests/ev4/` -- `registry.ev4_probe(method, path, actors=)`, default actors `anon_share, player, cross_gm_player` (+ `gm_owner`, `co_gm`, `player_2`); `families.py` (`assert_no_canary`, `assert_hidden_equals_missing`, `assert_hidden_field_equals_unset`, `assert_counts_and_ranking_unchanged`, `assert_audience_ladder`); `probes/_support.py` (`MISSING`, `outsider`, `row_count`, `assert_same_answer`, `is_gm_of_a`, `authenticated`); `probes/character_sheets.py` = template for write probes; `test_world_changes.py` = template for apply_change-driven fixtures (`ctx_for`, `share_ctx`, `mint_canary`). `anon_share` has no bearer header (401 on these routes, which is fine: it must still show no canary). `test_coverage.py` fails on any unprobed route.
- `tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check(REV)`, `test_single_alembic_head`, `test_fk_on_delete_actions` (no new FK here), downgrade-test pattern (`test_03c0b504f1d1_downgrade_drops_its_tables`), `_f3_values` compares `to_jsonb(entity_changes)` before/after re-running F3 (the new column is in it; stays `gm`).
- `tests/test_migrations_match_models.py` -- model/migration drift gate.
- `tests/access/test_registry_property.py` -- CI-11: `FIELD_NAMES` (L72), `change_fields` (L74), `EntityChange` spec (L185) and builder (L276).
- `tests/access/test_world_registry.py` -- unit registry tests (transient rows, `audience_of(..., parents=[entity(...)])`).
- `tests/services/test_world_service.py`, `tests/ev4/test_world_changes.py` -- existing world tests; their Party-visible history rows are all written after publication, so they must still pass.

## Tasks & Acceptance

**Execution:**
- `migrations/versions/<12-hex>_entity_changes_write_visibility.py` -- new revision, `down_revision = '03c0b504f1d1'`. Upgrade: `op.add_column('entity_changes', sa.Column('write_visibility', postgresql.ENUM(name='visibility', create_type=False), nullable=False, server_default='gm'))`. That single statement is the backfill: every existing row becomes `gm`. Downgrade: `op.drop_column('entity_changes', 'write_visibility')`. Module docstring states the backfill rule and its proof (see Design Notes).
- `app/db/models/entity.py` -- `EntityChange.write_visibility: Mapped[Visibility] = mapped_column(VISIBILITY_ENUM, nullable=False, default=Visibility.GM, server_default=Visibility.GM.value)` with a comment; update the module docstring.
- `app/access/registry.py` -- (1) `Derived.as_parent_field: str | None` (+ `derived(..., as_parent_field=None)`; needs a stored parent with `field_visibility`): the row is narrowed by `parent_field_audience(parent_model, parent, as_parent_field)`; SQL inside the first parent's EXISTS: `per_field = parent.field_visibility ->> name` is NULL or passes `_vis_clause`; Python in `audience_of` (needs the parent row, not an Audience: raise ValueError like `_parent_field_audience`). (2) `audience_of(obj, *, parents=None, floor=True)`: `floor=False` skips the row's own floor (used only to compute write-time visibility). (3) `EntityAlias: derived([...], floor=VISIBILITY_FLOOR, as_parent_field="aliases")`; `EntityChange: derived(..., floor="write_visibility", ...)` (keep every existing option). Update docstrings; `_check_complete` validates `as_parent_field`.
- `app/services/world_service.py` -- `HIDEABLE_FIELDS = {"status", "description", "attributes", "aliases"}`. `_Run` keeps `before: dict[id, Entity]` (a transient `Entity` copy of `visibility`, `field_visibility` (dict copy), `created_by_user_id`, `deleted_at`, `merged_into_id`, `type`, `campaign_id`, `id`, taken the first time an Entity is loaded by `_entity()`), `after: dict[id, Entity]` (the live objects from `_entity()` and `_create_entity`) and `rows: list[EntityChange]`. `history()` sets `write_visibility=Visibility.GM.value` and appends to `rows`. In `apply_change`, after the handler and before the final `flush`, `_stamp_write_visibility(run)`: for each row, `party` iff both `before` and `after` exist for its `entity_id` and `audience_of(row, parents=[snap], floor=False)` is not GM-level and not Owner-level for both; otherwise `gm`. Register the `entity_field` resolver (below). Update the module docstring ("History", "Visibility").
- `app/access/projection.py` -- (1) merge `extra` into `data` before `_apply_field_visibility` (so a hidden `aliases` extra renders `[]`). (2) `project(..., visible_entity_ids: frozenset[uuid.UUID] | None = None)`: for a non-GM ctx, on an `Entity` drop every ENTITY_REF attribute whose value is not in the set; on an `EntityChange` whose `field` is `attributes.<k>` with `k` an ENTITY_REF key of any type, replace every UUID-shaped string inside `old_value`/`new_value` (any depth) that is not in the set by `None`. `None` set = nothing visible (fail closed). GM: unchanged. (3) `project_all` collects those ids from the rows, loads the visible ones with `scoped_select(Entity, ctx).where(Entity.id.in_(ids))` (per Campaign for a role map), and passes the set. Docstring step 5 updated.
- `app/access/sources.py` -- `register_resolver(..., with_ctx: bool = False)`; `resolve_sources` calls `fn(row, ref, row_ctx)` for those. `field_visible`: for a model with `field_visibility`, accept `head.rest` when `head` is a column, checking per-field visibility of both the full name and `head` (gm rules apply to `head`).
- `app/schemas/entities.py` -- add to `EntityGMResponse`: `aliases: list[EntityAliasGMResponse] = []`, `steps: list[QuestStepGMResponse] = []`, `mention_count: int = 0`; to `EntityPartyResponse`: `aliases: list[EntityAliasPartyResponse] = []`, `steps: list[QuestStepPartyResponse] = []`, `mention_count: int = 0` (use `Field(default_factory=list)`). `EntityChangeGMResponse.write_visibility: Visibility`. New HTTP bodies: `EntityCreate {campaign_id, type, kind?, name (non-blank), description?, status?, attributes={}, gm_notes?}`, `EntityPatch {name?, description?, gm_notes?, status?, kind?, attributes?: dict[str, Any]}` (at least one field; `extra="forbid"`), `AliasCreate {alias}`, `StepCreate {text, position?, done=False}`, `StepPatch {text?, done?, position?}` (at least one), `RevertRequest {force=False}`, `EntityVisibilityRequest {visibility, field?}`, `BulkEntityVisibilityRequest {campaign_id, entity_ids: list[UUID] (1..500), visibility}`, `EntityListGMResponse/EntityListPartyResponse {items, total, limit, offset}`, `EntityHistoryGMResponse/PartyResponse {items, total, limit, offset}`, `UpdatedResponse {updated}`.
- `app/api/routes/entities.py` -- new module (see Design Notes for route behaviour).
- `app/main.py` -- mount the router (above).
- `nginx/locations.conf` -- the `/api/entities/` location.
- `tests/ev4/probes/entities.py` -- one `@ev4_probe` per route (13 path+method pairs); writes use `actors=(*DEFAULT_ACTORS, "co_gm")`. Families: canary (GM-only Entity with canary name/description/gm_notes/aliases/history), hidden ≡ missing (GM-only, deleted, missing, other Campaign), hidden field ≡ unset (`status` hidden → `"unknown"`, control: a Party Entity with default status), counts (`total` equals the Party-only fixture; `assert_counts_and_ranking_unchanged` around a GM-only create), audience ladder (`player`, `player_2`, `gm_owner`; anon_share gets 401 with no canary), Player writes 404 and row counts unchanged; GM writes succeed.
- `tests/ev4/test_entity_api_history.py` -- EV-4 proofs over HTTP: pre-publish history stays GM-only (publish a GM-only Entity edited with a canary, then rename; Player history = only the rename), pre-unhide field history, hidden aliases (rows, body, history), hidden ENTITY_REF in attributes and in history, and the post-upgrade empty list (run F3 data steps like `test_world_rows._copy`, add a Player, compare with an empty Campaign's response bytes).
- `tests/test_entities_api.py` -- GM route behaviour: create/duplicate 409 (case/whitespace via `normalize_name`, only visible rows), list filters (`type`, `status`, `visibility`, `q`, pagination, deleted/merged excluded), patch multi-field in one transaction (a failing field writes nothing), delete soft, aliases add/remove (alias of another Entity → 404), steps on non-Quest → 422, history order, revert (superseded 409, force), visibility single and bulk (> 500 → 422, a missing id → 404 and nothing changed), `entity_field` resolver (title, quote via project, hidden field dropped, ENTITY_REF quote redacted for a Player).
- `tests/services/test_world_service.py` -- `write_visibility` per op: publish row `gm`, hide row `gm`, edit of a Party visible field `party`, edit of a hidden field `gm`, create `gm`, edits of a GM-only Entity `gm`, revert of a pre-publish change after publish follows the rule (visible field → `party`).
- `tests/access/test_world_registry.py`, `tests/access/test_registry_property.py` -- alias hidden by `field_visibility.aliases`; `write_visibility` floor; add `"aliases"` to `FIELD_NAMES` and `change_fields`; EntityChange spec gets `"write": visibilities` and the builder passes `write_visibility=s["write"]`.
- `tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check(<new rev>)`: column exists, NOT NULL, default `'gm'::visibility`, every row `gm`; `test_<rev>_downgrade_drops_its_column` (downgrade to `03c0b504f1d1`, column gone, `entity_changes` rows otherwise unchanged, upgrade back, all `gm`). Update the module docstring.
- `_bmad-output/implementation-artifacts/spec-e0-worldcore-5-entity-api-gm-party-projections.md` -- fill Verification results and the "Needs desktop verification" list (below).

**Acceptance Criteria:**
- Given CI, when `backend-tests.yml` and `gates.yml` run, then all pass (CI-2, CI-3, CI-7, CI-8 with no baseline growth, CI-10, CI-11, CI-12, single head, drift, snapshot upgrade, downgrade).
- Given the app, when `tests/ev4/test_coverage.py` runs, then every `/api/entities` route is probed and `pending_baseline.txt` did not grow; every route resolves to the `/api/entities/` nginx location in zone `api`.
- Given `resolve_sources` with `SourceRef(kind="entity_field", id=e, field="description")`, when a Player may see the field, then title is `"<name> · Description"` and quote the projected value; when it is hidden, the ref is dropped.

## Design Notes

**Write-time visibility (owner decision, round 4).** A history row is shown to the Party only if the Party could already see that row's field both just before and just after the change. Example: publish row (`visibility gm→party`): before-state GM → `gm`. Edit of a Party Entity's visible `name` → `party`. Edit while `description` was hidden → `gm` forever, even after un-hiding. Rows with field NULL are GM by the existing rule anyway. Stored as `party`/`gm` only; it acts as a floor (`most_restrictive(current rule, floor)`), so a row never becomes wider than the Entity is now.

**Backfill rule (for the data-safety review).** `ADD COLUMN ... NOT NULL DEFAULT 'gm'` sets every pre-existing row to `gm` (metadata-only on PG 11+; no rewrite, no per-row SQL). Proof it loses nothing a Player should see: before this revision no HTTP route wrote Entity fields, so the only rows that can exist are (a) F3-world `migrated` rows, written while every copy was GM-only by construction, and (b) rows written by `POST /api/campaigns/{id}/visibility` (publish/hide/field-hide rows), whose before- or after-state is GM. Both are `gm` under the new rule, so the backfill is exact, not just conservative. Consequence: Players no longer see the `migrated` row of a published Entity (it was public via `public_null_ops`); the GM still does. Future re-runs of the F3 copy (E0-WorldCore.6) insert `gm` via the server default.

**Routes** (`prefix=/api/entities`; GETs carry `openapi_extra=PARTY_READ`, `response_model=None` with `responses=` docs like character_sheets):
- `GET /` (`require_campaign("player")`; `type`, `status`, `q`, `visibility`, `limit` 1..200 default 50, `offset` ≥ 0): `scoped_select(Entity, ctx)` minus deleted/merged, filters, ordered by `lower(name), id`; with `q`, `candidates(db, ctx, q, type=type, limit=100)` keeping `score >= 0.6`, ordered by score then name (total capped at 100). `total` counts the filtered visible rows. Items through `project_all` with `aliases`, `steps`, `mention_count` extras (each from `scoped_select` + `project_all`; counts grouped).
- `POST /` (`ctx_for_request(request, db, user, body.campaign_id, "gm")`): duplicate check over `scoped_select(Entity, ctx)` live rows of the type by `normalize_name(name)`; then `CreateEntity`; commit; 201 GM body.
- `GET /{entity_id}` (`require_campaign_for(Entity, "entity_id", "player")` + `scoped_get`); `PATCH`/`DELETE` and every other write use `require_campaign_for(..., "gm")`. PATCH applies `name`/`description`/`gm_notes` as `UpdateField`, `status` as `SetStatus`, `kind` as `SetKind`, each `attributes[k]` as `UpdateField(field="attributes.k")`, all before one commit (rollback on any error). DELETE → `DeleteEntity`, 204.
- `POST /{id}/aliases` → `AddAlias`, 201 alias GM body; `DELETE /{id}/aliases/{alias_id}` → load alias by `scoped_select(EntityAlias, ctx)` with `entity_id == id` (else 404) → `RemoveAlias(alias=row.alias)`, 204.
- `POST /{id}/steps` → `AddQuestStep` 201; `PATCH /{id}/steps/{step_id}` → step must belong to the Quest (else 404) → `UpdateQuestStep` 200.
- `GET /{id}/history` (`player`): `scoped_get` the Entity, then `scoped_select(EntityChange, ctx).where(entity_id == id)` newest first (`created_at desc, id desc`), paginated, `project_all`.
- `POST /{id}/history/{change_id}/revert` (`gm`): change must belong to the Entity (else 404) → `revert_change(force=body.force)`, 200 GM change body.
- `POST /{id}/visibility` → `set_visibility(db, ctx, RecordRef(kind="entity", id=id, field=body.field), body.visibility)`; `POST /visibility` → `ctx_for_request(..., "gm")` + `set_visibility_many` with one `RecordRef` per id; both commit and return `{updated}`.
- Error mapping in one helper: `CanonChangeError` codes `superseded`, `deleted`, `merged` → 409, `invalid`, `invalid_status`, `not_revertible` → 422 (`{"detail", "code"}`), `not_found` → `not_found()`. Always `await db.rollback()` before re-raising.

**`entity_field` resolver** (`register_resolver(SourceKind.ENTITY_FIELD, resolve_entity_field, model=Entity, with_ctx=True)` in world_service): title `f"{entity.name} · {label}"` (attribute label from `entity_types.attribute`, else the field name capitalised, `attributes` → `Attributes`); quote = the field's value from `project(entity, ctx)` (`attributes.k` → that key; dicts/lists JSON-dumped; missing → `""`), truncated to the module's `QUOTE_MAX`.

**Relationship-type defaults (carry-over d):** not built here. E3.1's first AC creates the defaults idempotently on a GM's first `GET /api/relationship-types/`, which covers every Campaign created after the upgrade; seeding at Campaign creation would duplicate that contract.

## Verification

**Commands** (from `src/backend`; a ready Python 3.11 venv with the light backend deps (no spacy/torch/whisper/weasyprint) is `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/wc5venv/bin/python`; never install anything globally or start a database on this Mac. DB tests run in CI only — the desktop is offline):
- `python -m compileall -q app tests migrations` -- expected: no errors
- `PYTHONPATH=. lint-imports --no-cache` -- expected: all contracts kept
- `python ../../scripts/check_scoped_queries.py && python ../../scripts/check_table_owners.py` -- expected: exit 0
- `SECRET_KEY=x POSTGRES_PASSWORD=x DATABASE_URL=postgresql+asyncpg://u:p@127.0.0.1:1/x python -c "import app.main"` -- expected: imports (registry completeness and Party-schema checks run at import)
- GitHub CI on the draft PR -- expected: backend-tests, gates, frontend-ci, license-check green

**Verification results** (2026-11-20, local light venv; no database on this Mac):
- `python -m compileall -q app tests migrations` -- ok.
- `PYTHONPATH=. lint-imports --no-cache` -- 5 contracts kept, 0 broken.
- `python ../../scripts/check_scoped_queries.py && python ../../scripts/check_table_owners.py` -- exit 0 (no baseline line added; `scripts/scoped_queries_baseline.txt` and `tests/ev4/pending_baseline.txt` untouched).
- Gate unit tests (`scripts/test_check_*.py`, `scripts/test_import_ratchet.py`) -- 240 passed.
- `import app.main` -- the light venv lacks spacy, sentence-transformers, PIL and weasyprint, so the plain command fails at `app.services.nlp_service` (pre-existing, unrelated). With those four stubbed by a scratch meta-path finder, `app.main` imports (registry completeness and the Party-schema check pass) and mounts the 13 `/api/entities` routes.
- With the app imported: `check_coverage` (tests/ev4/test_coverage.py's check) reports no error, all 13 routes probed; each route resolves to nginx `location /api/entities/` with `limit_req zone=api`.
- `alembic heads` -- one head, `0f1c3b194a4b`; offline SQL is `ALTER TABLE entity_changes ADD COLUMN write_visibility visibility DEFAULT 'gm' NOT NULL` / `DROP COLUMN write_visibility`.
- `pytest --noconftest tests/access/test_world_registry.py` (no DB) -- 72 passed.
- Not run here: every DB-backed test (EV-4 probes, `tests/test_entities_api.py`, `tests/ev4/test_entity_api_history.py`, the new `tests/services/test_world_service.py` cases, CI-11, the snapshot upgrade/downgrade). They run in CI on the draft PR.

**Needs desktop verification:** none beyond CI (no new service, model or image).

## Spec Change Log

## Review Triage Log

### 2026-11-20 — Review pass
- verdicts: 32 findings — high 0, medium 11, low 10, false 8, maybe-false 3
- findings:
  - `[medium]` `[patch]` (blind) entity_field resolver blanks visible ENTITY_REF quotes for a Player — resolver is async with db, loads visible ids via scoped_select and passes them to project.
  - `[medium]` `[patch]` (blind) resolver still cites a hidden ENTITY_REF (title + empty quote) — the ref is now dropped (None) when the target is not visible.
  - `[low]` `[defer]` (blind) Player history keeps the `attributes.<ref>` row with null values — no id leaks; hiding the rows changes history semantics; deferred to E0-WorldCore.11.
  - `[false]` `[reject]` (blind) ENTITY_REF detection ignores the Entity type — every ENTITY_REF key ends in `_entity_id` and is a ref on every type defining it.
  - `[false]` `[reject]` (blind) whole-`attributes` history rows not redacted — no op writes `field="attributes"` (UpdateField requires `attributes.<key>`; create/merge rows are field NULL, GM).
  - `[low]` `[patch]` (blind) dotted citation of an undefined attribute key survives — resolver returns None for a key the type does not define.
  - `[medium]` `[defer]` (blind) non-GM status filter and q search load the whole filtered Campaign — correct and leak-free; deferred (needs field_visibility-aware SQL).
  - `[medium]` `[defer]` (blind) duplicate-name check has no lock — concurrent GM creates can both pass; needs an advisory lock or unique index (schema). Missing `code` patched (`"duplicate"`).
  - `[low]` `[patch]` (blind) PATCH `{"attributes": {}}` commits nothing with 200 — EntityPatch rejects an empty attributes dict (422).
  - `[false]` `[reject]` (blind) add_alias returns an arbitrary row — aliases are unique per Entity by normalize_name, so at most one row matches.
  - `[false]` `[reject]` (blind) bulk route double-counts duplicate ids — set_visibility_many dedupes via dedupe_targets.
  - `[false]` `[reject]` (blind) migration "exact" claim misses source_deleted rows — nothing outside world_service emits source_deleted yet (E0-WorldCore.8 unbuilt).
  - `[false]` `[reject]` (blind) moving `data.update(extra)` changes other models — only Entity has field_visibility and only EntityChange has value_fields.
  - `[low]` `[reject]` (blind) missing tests for bogus aliases floor, merge-row stamping, None row_ctx — merge rows are field NULL (GM regardless); floor_audience fails closed; low value.
  - `[false]` `[reject]` (blind) nginx `/api/entities/` duplicates `/api/` — the story AC requires a locations.conf line in the api zone.
  - `[medium]` `[patch]` (vgap) route mention_count never checked non-zero or per audience — test added (GM 2, Player 1).
  - `[medium]` `[patch]` (vgap) hidden `attributes` head does not drop a dotted citation, untested — test added.
  - `[low]` `[patch]` (vgap) Player status filter positive match untested — probe asserts `status=unknown` returns exactly the two Entities.
  - `[medium]` `[patch]` (vgap) resolver blanks visible refs — same fix as blind row 1.
  - `[low]` `[patch]` (vgap) undefined attribute key citation survives — same fix as blind row 6.
  - `[medium]` `[patch]` (edge) resolver lacks visible ids — same fix as blind row 1.
  - `[medium]` `[patch]` (edge) non-GM `visibility` filter reveals stored Visibility — filter is GM-only; probe asserts identical bodies.
  - `[low]` `[defer]` (edge) q matches past the top 100 candidates are lost — documented cap; deferred with the list-performance item.
  - `[medium]` `[defer]` (edge) non-GM status filter loads every Entity — same as blind row 7.
  - `[medium]` `[defer]` (edge) concurrent duplicate creates — same as blind row 8.
  - `[low]` `[patch]` (edge) PATCH `{"attributes": {}}` — same fix as blind row 9.
  - `[false]` `[reject]` (edge) add_quest_step result may lack step_id — `_step_values` always includes step_id.
  - `[low]` `[patch]` (edge) field_visible accepts unknown dotted fields — handled in the resolver (the only dotted-field caller).
  - `[low]` `[patch]` (edge) register_visibility_kind ignores different fields= — now raises ValueError.
  - `[maybe-false]` `[reject]` (intent) anon Share Link holders get 401 on /api/entities — no non-share route accepts share tokens; anon Party projection is exercised via share_ctx + project in EV-4 world tests; share routes are not in the story's route list. Settled by an owner ruling; low if true.
  - `[maybe-false]` `[reject]` (intent) one prefix nginx block vs per-route lines — every route resolves to it in zone api; low if true.
  - `[maybe-false]` `[reject]` (intent) (d) deferral not in the diff — recorded in this spec and PR #75 (the audit saw a code-only diff).
- CI follow-up: the first run failed `tests/ev4/test_world_rows.py::test_loaded_rows_project_and_narrow`, which expected a Player to see the F3 `migrated` rows after publication; updated to assert they stay GM-only (owner decision).
