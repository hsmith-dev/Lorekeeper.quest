---
title: 'E0-Access.1: F1-core migration, with existing Members migrated to Player'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '3a3d08c3c0cf1f19b0c602cf7d88ad16d1c04e31'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred:
  - summary: >-
      New collaborate links created after F1-core store role NULL; create_share_token does not set role.
    evidence: |-
      app/api/routes/campaigns.py create_share_token builds CampaignShareToken without role; only pre-existing collaborate tokens are backfilled to player. epics.md assigns "new links store a Role (default Player)" to E0-Access.4/12; routes are out of scope for E0-Access.1.
    location: >-
      src/backend/app/api/routes/campaigns.py:234
    severity: medium
  - summary: >-
      Redis dedup key is still global (dedup:{entry_hash}), so AR-17 per-(campaign, user) uniqueness is not yet honoured at the API.
    evidence: |-
      app/services/dedup_service.py check_hash/store_hash, used by POST /journals/generate (journals.py:69); pre-existing, owned by E0-Journal writers.
    location: >-
      src/backend/app/services/dedup_service.py:6
    severity: low
  - summary: >-
      New or edited journal entries get no party_tsv / party_embedding until E0-Access.7 index_party_fields lands.
    evidence: |-
      journal_service writes only narrative_tsv; the story assigns party maintenance to E0-Access.7 (AD-18).
    location: >-
      src/backend/app/services/journal_service.py:114
    severity: medium
  - summary: >-
      chat_sessions.archived_at is written by the migration but no route filters or blocks archived sessions yet.
    evidence: |-
      No reader of ChatSession.archived_at in app/; enforcement belongs to the E0-Access chat ctx refactor (E0-Access.7/.10).
    location: >-
      src/backend/app/api/routes/chat.py
    severity: medium
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

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 32 findings — high 0, medium 6, low 9, false 9, maybe-false 0, descriptive 8 (intent-alignment divergences, no defect claimed)
- findings:
  - Edge-case hunter:
    - `[medium]` `[defer]` New collaborate links store role NULL — real (campaigns.py:234). New-link roles belong to E0-Access.4/12 and routes are outside this story's ACs. Deferred.
    - `[medium]` `[patch]` CHECKs were built from live EntryKind/TagSourceField, so a later member would rewrite history — now frozen local StrEnums passed to `check_sql`.
    - `[low]` `[patch]` A re-run after go-live archives post-migration Member chats — the docstring now states the step is one-time. Alembic never re-runs a revision.
    - `[false]` `[reject]` Former Members without a member row keep unarchived chats — the AC scopes archiving to current members of `campaign_id`. A non-member has no Campaign access, so nothing new leaks.
    - `[low]` `[reject]` `Mapped[EntryKind]` on a String column returns str — StrEnum compares equal to str. The fix adds a TypeDecorator for no observed harm.
    - `[medium]` `[patch]` The idempotency test only used unchanged seed rows — token 402 and member 301 are now promoted to co_gm before the re-run, and the test asserts they stay co_gm.
    - `[low]` `[patch]` The "no-op on re-run" claim was too broad — merged with the docstring patch above.
  - Blind hunter:
    - `[low]` `[defer]` The Redis dedup key is global — pre-existing service code (E0-Journal). Deferred.
    - `[medium]` `[defer]` New entries get no party_tsv — assigned to E0-Access.7 by the story. Deferred.
    - `[low]` `[patch]` Archive re-run safety — same root cause as the docstring patch.
    - `[medium]` `[patch]` The co_gm-demotion claim was untested — same root cause as the idempotency patch.
    - `[false]` `[reject]` New collaborate links get no Role (as a defect of this diff) — duplicate of the deferred edge-case finding. The column default makes join produce Players, which matches FR-7.
    - `[low]` `[patch]` expires_at/access_epoch were undocumented — added model comments naming E0-Access.4/.10.
    - `[medium]` `[patch]` CHECK values were not frozen — same as the edge-case patch.
    - `[low]` `[patch]` The GIN index was created before the backfill — it is now created after DATA_STEPS.
    - `[medium]` `[patch]` The ORM side of the PG enums was untested — added `test_join_stores_player_role_through_the_orm_enum` in tests/test_share.py.
    - `[low]` `[patch]` The `_baseline_schema` pg_type lookup had no namespace filter — it is now scoped to `current_schema()`.
    - `[low]` `[reject]` No DB guard that the Owner never has a member row — the app enforces it (share.py early return). A trigger adds surface outside the ACs.
    - `[false]` `[reject]` Type hints promise enums — duplicate of the rejected StrEnum finding.
    - `[medium]` `[defer]` archived_at is unread — enforcement belongs to the later E0-Access chat ctx stories. Deferred.
  - Verification gap:
    - `[medium]` `[patch]` CampaignMember.role was never exercised through the ORM — same as the ORM enum test patch.
    - `[medium]` `[patch]` The visibility server defaults for the four unseeded tables were untested — added post-upgrade check `visibility_server_defaults_follow_ad12`.
    - `[medium]` `[patch]` The idempotency test could not see the guards — same as the idempotency patch.
    - `[false]` `[reject]` (other) New links get role NULL — duplicate. Deferred above.
    - `[false]` `[reject]` (other) Redis dedup is global — duplicate. Deferred above.
  - Intent alignment (descriptive):
    - `[false]` `[reject]` (a) Members become Players by default, not UPDATE — deliberate. Proven by the `members_become_players` post-upgrade check.
    - `[false]` `[reject]` (b) Idempotency re-applies only the data step — this matches the AC wording "stamp back, re-apply the data step". Re-running `upgrade()` would fail on DDL by design.
    - `[false]` `[reject]` (c) Only Member A's chat is archived — the seed gives Member B a chat with no Campaign. The archive scope follows AD-19 ("in that Campaign").
    - `[false]` `[reject]` (d) Enums are in domain/enums.py — deliberate (AD-1 layering, the brief's CI-10 instruction, and E0-WorldCore.1 already put TagSourceField there).
    - `[false]` `[reject]` (e) The R3 behavioural goal is not shown — enforcement belongs to E0-Access.2–13.
    - `[low]` `[patch]` (f) The test_probes.py docstring was stale — updated.
    - `[false]` `[reject]` Gates relied on without being touched — CI ran them. See Auto Run Result.
    - `[false]` `[reject]` Uncommitted spec changes — workflow state, committed at finalize.

## Auto Run Result

Status: done

**Summary:** F1-core revision `c95acb56c595`, which revises `a3e7c1f9d258`. It adds:
- the `visibility` and `campaign_role` PG enums;
- every column from E0-Access.1, with NOT NULL and server defaults, the `kind` and `source_field` CHECKs built with `check_sql` from frozen labels, and the `ix_journal_party_fts` GIN index;
- the `entry_hash` uniqueness change to `(campaign_id, user_id, entry_hash)`;
- idempotent set-based data steps: Member chats in their Campaign are archived, collaborate tokens get `player`, and `party_tsv` is built from the Narrative. Members become Player through the column default;
- a dev-only downgrade.

There are no new tables and no new FKs, so CI-7 and `EXPECTED_FK_ON_DELETE` are unchanged.

**Files changed:**
- `src/backend/migrations/versions/c95acb56c595_f1_core_roles_visibility_party_search.py` -- the revision.
- `src/backend/app/domain/enums.py` -- `EntryKind`, `Visibility`, `CampaignRole`.
- `src/backend/app/db/base.py` -- the shared `VISIBILITY_ENUM` / `CAMPAIGN_ROLE_ENUM` (PG ENUM, `create_type=False`, `values_callable`).
- `src/backend/app/db/models/{journal,campaign_member,share_token,chat,tag,character_sheet,session_plan,source,shorthand,tag_category}.py` -- the new columns, constraints and index.
- `src/backend/tests/test_enum_check_sync.py` -- `TagSourceField` and `EntryKind` moved to `ENUM_CHECKS`; new `PG_ENUMS` plus `test_pg_enums_match`.
- `src/backend/tests/domain/test_enums.py` -- expected values for the three new enums.
- `src/backend/tests/migrations/test_upgrade_snapshot.py` -- post-upgrade checks for `c95acb56c595` (members are player, the Owner is untouched, the archive scope, token roles, entries and party_tsv, visibility defaults), plus an idempotency test (with promoted rows) and a downgrade-to-baseline schema test.
- `src/backend/tests/ev4/fixtures.py`, `tests/ev4/test_fixtures.py`, `tests/ev4/test_probes.py` -- the "roles not yet available" skip is removed, `gm`/`co_gm` map to `co_gm`, and the role actors are live.
- `src/backend/tests/test_share.py` -- an ORM role round-trip via the join route. The exact-field fixture now fills `party_tsv`, `party_embedding` and `journal_tags.source_field`.

**Review:**
- 14 patch rows across 9 distinct fixes: 6 medium-verdict rows (4 distinct fixes: frozen CHECKs, idempotency guard test, ORM role test, visibility defaults) and 8 low rows.
- 4 items deferred (see frontmatter).
- Rejected: the str-vs-StrEnum typing (low; no harm), the Owner-row DB trigger (low; app-enforced, outside the ACs), former-member chats (false; outside the AC scope), and the descriptive intent divergences (each deliberate, with reasons in the triage log).

**Follow-up review recommended:** true. Four distinct medium fixes were patched. The specific unverified risk is that the new patched tests (the guard-sensitive idempotency test, the visibility-default check, the ORM join test) were checked only by CI, never run locally.

**Verification:**
- `py_compile` is clean.
- `lint-imports` passes all 5 contracts.
- `check_table_owners.py` passes.
- The migration's offline SQL was exercised on a scratch copy of the snapshot.
- PR #39 CI: the first push had 662 passed, 3 skipped and 3 errors. The errors were the share exact-field fixture leaving the new nullable columns unfilled, which is fixed. After the fix, all 12 checks pass. The backend `test` job ran 667 tests: 667 passed and 3 skipped. The skips are the empty EV-4 probe set, the live-Ollama integration test and an empty LLM-schema parameter. None are role skips.

**Needs desktop verification:**
- On the desktop, run the full backend suite against `lorekeeper_test_<lane>`:
  `docker run ... lorekeeper-backend-test python -m pytest -q tests/migrations tests/test_enum_check_sync.py tests/test_share.py tests/ev4`
- Then run `alembic upgrade head` on a copy of the real production DB, and confirm that `SELECT role, count(*) FROM campaign_members GROUP BY role` shows only `player`.

**Residual risks:**
- Players' access is not enforced until E0-Access.2–13. The new columns are inert until then.
- The downgrade fails if the same `entry_hash` exists in two Campaigns (dev only).
