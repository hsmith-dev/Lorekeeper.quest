---
title: 'E0-Access.1: F1-core migration, with existing Members migrated to Player'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '3a3d08c3c0cf1f19b0c602cf7d88ad16d1c04e31'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Roles, Visibility and Party-only search columns do not exist, so the privacy layer (E0-Access.2–13, F2, F3) has nothing to build on, and existing Members implicitly have full write access.

**Approach:** One Alembic revision `c95acb56c595` (F1-core, `down_revision = a3e7c1f9d258`) adds the two PG enums and every F1-core column from AD-19 / epics.md E0-Access.1, runs set-based idempotent data steps (members → player by column default, members' in-Campaign chats archived, collaborate tokens → player, `party_tsv` from Narrative), swaps `entry_hash` uniqueness to `(campaign_id, user_id, entry_hash)`, with a dev-only downgrade. Models, CI-10 enum registry, snapshot checks and the EV-4 `make_member` follow.

## Boundaries & Constraints

**Always:** schema + set-based SQL only (AD-18); every data `UPDATE` has an idempotent `WHERE`; CHECK text from `app.domain.enums.check_sql`; Owner never gets a `campaign_members` row; NOT NULL + server defaults so raw/ORM inserts that omit the new columns still work; downgrade restores the exact `a3e7c1f9d258` schema (incl. `journal_entries_entry_hash_key`).

**Never:** new tables; FKs on `npc_entity_id` / `pc_entity_id` (F3 adds them); `visibility` on `npcs`/`quests` (OD-1 option A, E0-Access.14 out of scope); `party_embedding` backfill (E0-Access.7); any route/service behaviour change; files of E0-Platform.4/5 or E0-UX.9.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Members | snapshot members 301, 302 | `role = player`, `access_epoch = 0`; Owner has no row | — |
| Member chat in Campaign | chat 902 (Member A, campaign 101) | `archived_at` set | — |
| Owner chat | chat 901 (Owner, campaign 101) | `archived_at IS NULL` | — |
| Member chat, no Campaign | chat 903 (Member B, `campaign_id NULL`) | not archived (not a member *of its* Campaign) | — |
| Tokens | 401 read_only, 402 collaborate | 401 `role NULL`; 402 `role = player` | — |
| Entries | 3 entries | counts/Narratives unchanged, `kind=gm`, `visibility=party`, `party_tsv = to_tsvector('english', narrative)`; shorthand-only word not in `party_tsv` | — |
| Re-run data step | stamp back to baseline, re-apply data step, stamp head | every F1-core column value identical | — |
| Downgrade | `downgrade 8c1d5f3a92e7` round trip | succeeds, upgrade head again succeeds | duplicate `entry_hash` across campaigns would fail the global unique (dev-only, documented) |

</intent-contract>

## Code Map

- `src/backend/migrations/versions/a3e7c1f9d258_index_shorthand_in_tsv.py` -- current head; new revision revises it.
- `src/backend/migrations/versions/fc4226e829a0_initial_schema.py:66` -- unnamed `UniqueConstraint('entry_hash')` → PG name `journal_entries_entry_hash_key` (see snapshot SQL line 928).
- `src/backend/app/domain/enums.py` -- StrEnums + `check_sql`/`check_expr`; `TagSourceField` already here (RC-12). Only layer below `app.db` (import-linter `.importlinter`), so model-facing enums must live here, not in a new `app/access`.
- `src/backend/tests/test_enum_check_sync.py` -- `ENUM_CHECKS`, `ENUM_CHECKS_PENDING`, `test_every_domain_enum_is_registered`.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check`, `EXPECTED_FK_ON_DELETE` (no new FKs), round-trip test downgrading to `8c1d5f3a92e7`.
- `src/backend/tests/test_migrations_match_models.py` -- autogenerate diff (types, indexes, uniques; not CHECKs/server defaults).
- `src/backend/tests/ev4/fixtures.py:309-360,430-452` + `tests/ev4/test_fixtures.py:148-189` -- role skip and label guessing to remove.
- Models: `app/db/models/{journal,campaign_member,share_token,chat,tag,character_sheet,session_plan,source,shorthand,tag_category}.py`.
- `scripts/check_table_owners.py` / `table_owners_legacy.txt` -- unaffected (no new tables; legacy reasons already mention F1-core columns).
- `src/backend/app/api/routes/share.py:165` -- `CampaignMember(...)` relies on the new default `player` (correct per FR-7).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/domain/enums.py` -- add `Visibility {party,gm,private}`, `CampaignRole {co_gm,player}` (PG-enum mirrors) and `EntryKind {gm,player}` (CHECK); update docstring map -- models need them below `app.db`.
- `src/backend/migrations/versions/c95acb56c595_f1_core_roles_visibility_party_search.py` -- create; `DATA_STEPS` + `apply_data_steps(bind)` reused by the test; full downgrade.
- models listed above -- declare new columns (`Mapped[]`, PG ENUM `create_type=False` with `values_callable`, defaults + server defaults, CheckConstraints via `check_expr`, `ix_journal_party_fts` GIN, new `UniqueConstraint`).
- `src/backend/tests/test_enum_check_sync.py` -- `TagSourceField` and `EntryKind` into `ENUM_CHECKS`; new `PG_ENUMS` registry (`Visibility`, `CampaignRole`) checked against `pg_enum` labels; registration test accepts it.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- `@post_upgrade_check("c95acb56c595")` checks per I/O matrix; idempotency test.
- `src/backend/tests/ev4/fixtures.py`, `tests/ev4/test_fixtures.py` -- drop skip, map `gm`/`co_gm` → `co_gm`; tests assert live roles.

**Acceptance Criteria:**
- Given an empty DB, when `upgrade head` runs, then schema matches the models (E0-QA.5) and CI-10 passes with `journal_tags.source_field` and `journal_entries.kind` registered.
- Given the snapshot, when `upgrade head` runs, then the I/O matrix rows hold and row counts are unchanged.
- Given the EV-4 harness, when `player`, `player_2`, `co_gm`, `cross_gm_player` resolve, then they no longer skip.

## Design Notes

- Enums go straight to `domain/enums.py` (the AC's end state; `app/access/enums.py` would force `app.db → app.access`, inverting AD-1). `app/access/` is created by E0-Access.2.
- Members → player happens via `ADD COLUMN ... NOT NULL DEFAULT 'player'`; no `UPDATE` that a re-run could use to demote a later Co-GM.
- Chat archive `WHERE archived_at IS NULL`, token `WHERE kind='collaborate' AND role IS NULL`, `party_tsv WHERE party_tsv IS NULL`.

## Verification

**Commands:**
- `python -m py_compile` on changed files -- expected: no errors.
- GitHub CI `backend-tests.yml`, `gates.yml` on the draft PR -- expected: green.
