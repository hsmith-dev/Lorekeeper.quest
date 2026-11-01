---
title: 'E0-WorldCore.1: Entity Type registry and closed-set enums'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '56a28028dbe46f881bb3e9f3bc72253051acf028'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/src/backend/.importlinter'
  - '{project-root}/src/backend/tests/test_enum_check_sync.py'
warnings: []
deferred:
  - summary: >-
      validate_attributes checks attribute keys only, not values against their declared ValueKind (text, entity_ref, datetime).
    evidence: |-
      entity_types.validate_attributes returns dict(attrs) after the key check; ValueKind is declared but unused for validation. The spec scoped it to keys; value and target-type checks belong with apply_change (E0-WorldCore.3), which has the Campaign context to resolve entity refs.
    location: >-
      src/backend/app/domain/entity_types.py validate_attributes
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The living world model (F3-world, E0-WorldCore.2 onwards) needs one source of truth for Entity Types, Character kinds, per-type status vocabularies with categories, typed attribute keys, the Party "unset" rendering of hidden fields (AD-13), and the closed-set StrEnums whose CHECK constraints migrations generate (AD-9). None of it exists yet, and CI-10's enum registry is empty waiting for it.

**Approach:** Add two pure modules, `app/domain/enums.py` (StrEnums plus `check_sql`) and `app/domain/entity_types.py` (the registry plus `validate_status`, `validate_kind`, `party_unset`), with unit tests in `tests/domain/`. Make CI-10 enforce that every StrEnum in `domain/enums.py` is either registered against its CHECK column or listed as pending with the story that adds that column.

## Boundaries & Constraints

**Always:**
- `app/domain/*.py` imports only the stdlib and other `app.domain` modules (import-linter `domain` contract; AD-1).
- Exactly five types `character, location, faction, item, quest`; kinds `pc, npc, creature` for Characters only.
- Statuses and categories exactly as E0-WorldCore.1 lists them; default status `unknown` except Quest `active`.
- `MentionSourceField {narrative, shorthand, gm_notes}` and `TagSourceField {shorthand, narrative, manual}` are distinct classes (RC-12).
- `EntityChangeOp` holds exactly the 19 E0-WorldCore.3 ops plus `migrated`.
- `check_sql(enum, column)` returns `CHECK (column IN ('a', 'b', ...))` in enum definition order, single quotes doubled.

**Never:**
- No migration, no table, no ORM model (E0-WorldCore.2 creates `entities` etc.; E0-Access.1 creates `journal_tags.source_field`).
- Do not touch `app/domain/embedding.py`, `narrators.py`, `achievements.py`, `seeds/`, or wave-sibling files (EV-4 harness, llm_provider, ml/stt sidecars, frontend).
- No PG enums; no imports of `app.core`, `app.db`, `app.schemas`, `app.services`, `app.api`, `app.clients` from domain.
- Do not edit `sprint-status.yaml`, `epics.md`, or commit `epic-*-context.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid status | `validate_status("character", "deceased")` | returns `"deceased"`; `status_category` gives `closed_other` | none |
| Status from another type | `validate_status("quest", "alive")` | rejected | raises `InvalidStatusError` (a `ValueError`) |
| Unknown type | `validate_status("dragon", "alive")` | rejected | raises `ValueError` |
| Kind on Character | `validate_kind("character", "creature")` / `None` | ok / rejected | `ValueError` for missing or unknown kind |
| Kind on non-Character | `validate_kind("item", "npc")` | rejected; `None` accepted | `ValueError` |
| Party unset, status | `party_unset("quest", "status")`, `party_unset("faction", "status")` | `"active"`, `"unknown"` | none |
| Party unset, other fields | `description` / `aliases` / `attributes.region` on location | `None` / `[]` / `ABSENT` sentinel | unknown field or attribute key raises `ValueError` |
| Party projection | `party_view("location", {...}, hidden={"description","attributes.region"})` | description `None`, `region` key removed from `attributes`, input not mutated | none |
| check_sql quoting | enum member containing `'` | quote doubled inside literal | none |
| check_sql round-trip | temp table using `check_sql(E, "c")` for each enum | CI-10 reader `check_values` returns exactly the enum's values | none |
| Unregistered enum | a StrEnum in `domain/enums.py` absent from both `ENUM_CHECKS` and `ENUM_CHECKS_PENDING` | CI-10 test fails naming it | assertion message |

</intent-contract>

## Code Map

- `src/backend/app/domain/embedding.py` -- existing pure-domain precedent (module docstring style, constants only). Read-only.
- `src/backend/app/domain/__init__.py` -- empty package marker; leave as is.
- `src/backend/.importlinter` -- `domain` forbidden contract + `layers` contract; new modules must satisfy them (no edit needed).
- `src/backend/tests/test_enum_check_sync.py` -- CI-10 gate. `ENUM_CHECKS` (empty, line ~26), `check_values(db, table, column)`, `compare(...)`, `parse_check_values`. Reuse the reader for the round-trip test; extend with a pending map and a completeness test.
- `src/backend/tests/conftest.py:140` -- `db` AsyncSession fixture (real Postgres in CI); `asyncio_mode = auto` in `pytest.ini`.
- `src/backend/app/db/models/npc.py`, `quest.py` -- legacy roles `npc/pc/monster/faction`, statuses `alive/dead/unknown`, Quest `active/completed/failed/abandoned`. The E0-WorldCore.2 copy maps them (monster→creature, dead→deceased, faction alive→active / dead→disbanded).
- `seeds/demo_campaign.json` -- 13 npcs (roles pc/npc/monster/faction, statuses alive/dead/unknown via `status_history`), 3 quests (completed/active), 8 locations (name/description only). No items in the seed.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/domain/enums.py` -- create: `EntityType`, `CharacterKind`, `EntityChangeOp`, `MentionOrigin`, `MentionSourceField`, `TagSourceField` (StrEnums); `check_sql(enum, column)` and `check_expr(enum, column)` (the inner `column IN (...)` for `sa.CheckConstraint`). Docstring: AD-9, RC-12, where each enum's CHECK will live, and that `TagSourceField` is the home F1-core's `journal_tags.source_field` enum moves to.
- `src/backend/app/domain/entity_types.py` -- create: `StatusCategory` StrEnum; frozen dataclasses `StatusDef(key, category, label)`, `AttributeDef(key, value_kind, label, target_types)`, `EntityTypeDef(type, label, statuses, default_status, attributes, kinds)`; `REGISTRY: Mapping[EntityType, EntityTypeDef]` (read-only, in the spec's type order); `ABSENT` sentinel; functions `get(type)`, `statuses(type)`, `validate_status(type, status)`, `status_category(type, status)`, `is_closed(type, status)`, `default_status(type)`, `validate_kind(type, kind)`, `attribute_keys(type)`, `validate_attributes(type, attrs)` (unknown key → `ValueError`), `party_unset(type, field)`, `party_view(type, fields, hidden)`. `InvalidStatusError(ValueError)`. Attribute keys: character `species`, `occupation`, `location_entity_id`; location `region`, `parent_location_entity_id`; faction `headquarters_entity_id`, `leader_entity_id`; item `holder_entity_id`, `location_entity_id`; quest `giver_entity_id`, `completed_at`. `value_kind ∈ {text, entity_ref, datetime}`; entity refs name allowed target types.
- `src/backend/tests/domain/__init__.py` -- create (empty).
- `src/backend/tests/domain/test_entity_types.py` -- create: unit tests for every matrix row on the registry, exact type/status/category/default tables, kinds, attribute keys incl. the three named examples, `party_view` non-mutation, and that every demo-seed npc/quest/location maps (via the WorldCore.2 legacy mapping written in the test) to a valid type, kind and status.
- `src/backend/tests/domain/test_enums.py` -- create: exact member sets for each enum (EntityChangeOp = 20 ops), RC-12 distinctness, `check_sql`/`check_expr` text and quoting, DB round-trip of every enum's `check_sql` through `tests.test_enum_check_sync.check_values` on a `TEMP` table, and an AST check that `app/domain/*.py` imports nothing from `app.*` outside `app.domain`.
- `src/backend/tests/test_enum_check_sync.py` -- update module docstring/comments; add `ENUM_CHECKS_PENDING: dict[type[StrEnum], str]` (enum → the story that adds its CHECK column: `EntityType`/`CharacterKind`/`EntityChangeOp`/`MentionOrigin`/`MentionSourceField` → E0-WorldCore.2, `TagSourceField` → E0-Access.1) and `test_every_domain_enum_is_registered` (each StrEnum defined in `app.domain.enums` is in exactly one of `ENUM_CHECKS` or `ENUM_CHECKS_PENDING`; nothing else is pending).

**Acceptance Criteria:**
- Given the backend, when `lint-imports` runs from `src/backend`, then all AD-1 contracts stay kept.
- Given CI, when backend tests run, then the previous suite plus the new tests pass with no regressions.
- Given a later story adds the `entities.type` CHECK, when its author moves `EntityType` from `ENUM_CHECKS_PENDING` to `ENUM_CHECKS`, then CI-10 compares it against `pg_constraint` with no other change.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 33 findings — high 0, medium 4, low 19, false 10, maybe-false 0
- findings:
  - `[medium]` `[patch]` (verification-gap) legacy-mapping test never reads NpcRole/NpcStatus/QuestStatus — added test_legacy_mapping_covers_every_legacy_enum_value over the real legacy enums; removed hand-typed loops.
  - `[low]` `[patch]` (verification-gap) party_view with no `attributes` key untested — added missing/None attributes tests.
  - `[medium]` `[patch]` (blind) hidden attribute survives when `attributes` is a non-dict Mapping — Mapping normalised to dict before deepcopy; other types raise TypeError; tests added.
  - `[false]` `[reject]` (blind) gm_notes not always hidden by party_view — Party schemas omit gm_notes structurally (AD-13, E0-WorldCore.4); party_view is a renderer for listed hidden fields, not the gate.
  - `[low]` `[reject]` (blind) hideable fields split across three places / kind undecided — cosmetic; the set is documented in one docstring and unknown fields raise.
  - `[medium]` `[defer]` (blind) validate_attributes ignores value kinds — deferred to E0-WorldCore.3 (see frontmatter).
  - `[low]` `[patch]` (blind) Quest attribute label "Completed" collides with status label — renamed "Completed on".
  - `[low]` `[reject]` (blind) post_init lacks "default is open" invariant — every default is open and tests pin defaults; extra guard not worth it.
  - `[medium]` `[patch]` (blind) legacy test comment unproven — same root cause as the first row; fixed there.
  - `[false]` `[reject]` (blind) legacy maps should live in app.domain — migrations must not import mutable app code; E0-WorldCore.2 writes the mapping in SQL; the test pins it.
  - `[low]` `[reject]` (blind) seed location loop is a no-op — locations carry no type/status data in the seed; harmless.
  - `[low]` `[patch]` (blind) AD-1 AST gate non-recursive — rglob now used. Third-party import part rejected: import-linter is the gate, the test message is advisory.
  - `[low]` `[patch]` (blind) pending story regex only accepts E0 — widened to r"E\d+(-[A-Za-z]+)?\.\d+".
  - `[low]` `[patch]` (blind) TagSourceField docstring cites non-existent app/access/enums.py — reworded.
  - `[low]` `[reject]` (blind) tests/domain imports helpers from tests.test_enum_check_sync — a deliberate reuse of the CI-10 reader so the round-trip tests the real gate code.
  - `[low]` `[reject]` (blind) len(EntityChangeOp)==20 redundant — harmless.
  - `[medium]` `[patch]` (edge) non-dict Mapping attributes leak — same root cause as blind row 3.
  - `[low]` `[patch]` (edge) hidden passed as bare str — TypeError guard + test.
  - `[low]` `[patch]` (edge) deepcopy TypeError on MappingProxyType — same root cause as blind row 3.
  - `[low]` `[reject]` (edge) sorted() on mixed-type keys — attributes come from JSONB (str keys); unlikely.
  - `[low]` `[reject]` (edge) attribute value kinds unchecked — same as the deferred row.
  - `[low]` `[reject]` (edge) non-str field_name raises AttributeError — internal callers pass literals; unlikely.
  - `[low]` `[reject]` (edge) EntityTypeDef kinds invariants — registry is a fixed literal pinned by tests.
  - `[false]` `[reject]` (edge) check_sql column injection — column is an author-written constant in a migration, never user input.
  - `[low]` `[patch]` (edge) pending regex E0-only — same as blind row.
  - `[low]` `[patch]` (edge) level>1 relative import treated as domain — now mapped to "app" and flagged.
  - `[low]` `[patch]` (edge) glob skips subpackages — rglob.
  - `[low]` `[patch]` (edge) legacy keys not checked against enums — same as first row.
  - `[low]` `[patch]` (edge) docstring claim about app/access/enums.py — same as blind row.
  - `[false]` `[reject]` (intent) CI-10 does not check the migrated schema — the CHECK columns are created by E0-WorldCore.2 / E0-Access.1; ENUM_CHECKS_PENDING makes moving each enum in a required step, and the round-trip test exercises the reader on generated DDL.
  - `[false]` `[reject]` (intent) RC-12 "move" not done — nothing exists to move (no app/access); TagSourceField defined at its target home.
  - `[false]` `[reject]` (intent) gm_notes fifth unset value / ABSENT sentinel / invented attribute keys and helpers — the AC asks for "typed attributes keys"; the extra API is additive and the four AC unset values are exact.
  - `[false]` `[reject]` (intent) entity_types imports app.domain.enums against "no imports" — the layer rule (AD-1, import-linter) forbids other app packages; intra-domain imports are within the layer.

## Design Notes

`party_unset` keys: `status`, `description`, `aliases`, `gm_notes` (→ `None`), and `attributes.<key>` (→ `ABSENT`, meaning "drop the key"). `ABSENT` is a module-level singleton with a readable repr, so `access.project` (E0-Access) can write `if v is ABSENT: attrs.pop(k)`. Fields not in that list (e.g. `name`) raise `ValueError` rather than guess: name is never hidden.

## Verification

**Commands:**
- `cd src/backend && uv run --python 3.11 --with pytest python -m pytest -q tests/domain -k "not round_trip"` -- expected: all pure tests pass locally (DB tests run in CI).
- `cd src/backend && uv run --python 3.11 --with import-linter==$(grep -i '^import-linter==' requirements-dev.txt | cut -d= -f3) lint-imports` -- expected: contracts kept.
- GitHub CI on the draft PR (`backend-tests.yml`, `gates.yml`) -- expected: green.

## Auto Run Result

Status: done

**Summary:** Added the pure domain modules `app/domain/enums.py` (EntityType, CharacterKind, EntityChangeOp with 20 ops, MentionOrigin, MentionSourceField, TagSourceField; `check_sql`/`check_expr`) and `app/domain/entity_types.py` (registry of the five types with statuses/categories/labels, defaults, kinds, typed attribute keys; `validate_status`, `status_category`, `is_closed`, `validate_kind`, `validate_attributes`, `party_unset`, `party_view`, `ABSENT`). CI-10 now requires every domain StrEnum to be in `ENUM_CHECKS` or `ENUM_CHECKS_PENDING` (all six pending: five on E0-WorldCore.2, TagSourceField on E0-Access.1). No migration (no table in this story).

**Files:**
- `src/backend/app/domain/enums.py` -- new: closed-set StrEnums and CHECK generators.
- `src/backend/app/domain/entity_types.py` -- new: Entity Type registry and Party unset rendering.
- `src/backend/tests/domain/__init__.py` -- new package marker.
- `src/backend/tests/domain/test_entity_types.py` -- new: registry, validation, party rendering, seed/legacy mapping tests.
- `src/backend/tests/domain/test_enums.py` -- new: members, RC-12, check_sql text/quoting, DB round-trip through the CI-10 reader, domain import isolation.
- `src/backend/tests/test_enum_check_sync.py` -- pending registry + completeness test.

**Review:** 13 patch rows applied (4 medium-root-cause groups incl. legacy-enum coverage and non-dict attributes leak), 1 deferred (attribute value validation, medium), 19 rejected (10 false, 9 low with reasons in the triage log). Follow-up review: false (no high patched; two medium root causes patched, both directly covered by new tests — legacy enum coverage and Mapping attributes).

**Verification:** `lint-imports` 5 contracts kept; pure tests pass locally on Python 3.11 (41 of 42 in test_entity_types without DB deps; the legacy-enum test needs pgvector and runs in CI); implementer ran 69 tests incl. DB round-trips against a local Postgres TEMP-table fixture. Full suite: GitHub CI on the draft PR.

**Residual risks:** attribute key set beyond the three AC examples and entity-ref target types are design choices later stories may revise.

**Needs desktop verification:** none (pure domain code; CI's Postgres covers the DB tests).
