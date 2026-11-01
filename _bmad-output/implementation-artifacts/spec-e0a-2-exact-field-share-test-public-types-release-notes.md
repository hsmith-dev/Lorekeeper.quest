---
title: 'E0a.2: Exact-field share test, frontend Public types and release notes'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred:
  - summary: >-
      Frontend Public* TS types are hand-mirrored from the backend share schemas; nothing mechanically ties them together.
    evidence: |-
      src/frontend/src/types/index.ts Public* interfaces match app/schemas/share.py today, but no generated OpenAPI types or contract test exist (pre-existing gap for all frontend types; no frontend test runner yet).
    location: >-
      src/frontend/src/types/index.ts
    severity: low
---

<intent-contract>

## Intent

**Problem:** E0a.1 stopped read-only Share Links leaking Shorthand and NPC/Quest notes, but the test only checks that those two named fields are absent (a newly added column could still leak), the share page still types share data with owner types (`JournalListResponse`, `NpcEntry`, `Quest`), nested journal tags reuse the owner `TagResponse`, and Owners have no release note explaining the change.

**Approach:** Assert the exact key set of every share response in `tests/test_share.py` using rows built with every column filled; give nested tags their own Public allow-list schema; add `PublicJournal`, `PublicJournalList`, `PublicNpc`, `PublicQuest` (and `PublicTag`) TS types matching the backend exactly and use them in the share API calls and `SharedCampaignPage.tsx`; narrow `JournalCard`'s prop type; add `docs/RELEASE_NOTES.md` linked from `README.md`.

## Boundaries & Constraints

**Always:** Public schemas stay allow-lists in `app/schemas/share.py`. The exact key lists are written literally in the test. The test fails if a model column is left unfilled (so "every column filled" stays true as models grow). The response wire shape for share routes is unchanged (same keys as after E0a.1) so issued links keep working.

**Never:** Widen the Public types to fit `JournalCard`. Add tables/columns/migrations. Touch Roles/Visibility, link expiry, chat/search leak paths. Edit `sprint-status.yaml` or `epics.md`. Add a frontend test runner.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Campaign metadata | `GET /api/share/{token}` | keys exactly `{id,name,genre,description,share_kind}` | n/a |
| Journal list/detail | entry with every column filled, one built-in tag + one custom-category tag | list keys `{items,total,page,limit}`; item keys `{id,campaign_id,narrative,session_date,tags,created_at}`; tag keys `{id,name,tag_type,custom_category}`; category keys `{id,name,campaign_id,created_at}` | no canary string in body |
| NPCs / quests | rows with every column filled, `notes` = canary | NPC keys `{id,campaign_id,name,role,status,description,created_at,updated_at}`; quest keys `{id,campaign_id,title,description,status,created_at,updated_at}` | no canary string in body |
| Collaborate token | content endpoints | 404 (existing test kept) | n/a |

</intent-contract>

## Code Map

- `src/backend/app/schemas/share.py` -- Public* schemas; `PublicJournalResponse.tags` uses owner `TagResponse` from `app/schemas/tag.py` -> replace with new `PublicTagResponse` + `PublicTagCategoryRef` (same fields).
- `src/backend/app/api/routes/share.py` -- read-only; routes already return Public* via `response_model` with `from_attributes`, eager-loading `Tag.custom_category`.
- `src/backend/tests/test_share.py` -- existing E0a.1 tests (named-field absence, collaborate 404); extend with exact-key-set tests.
- `src/backend/app/db/models/{journal,npc,quest,tag,tag_category}.py` -- columns to fill: JournalEntry (shorthand, narrative, narrative_tsv, entry_hash, session_date, embedding[384], user_id, campaign_id, timestamps), NpcEntry/Quest (incl. notes), Tag (tag_type XOR custom_category_id; unique (name, tag_type)), JournalTag link table.
- `src/backend/tests/conftest.py` -- schema via `Base.metadata.create_all`; `db`, `client`, `promo_code` fixtures.
- `src/frontend/src/types/index.ts` -- owner types `Tag`, `TagCategoryRef`, `JournalEntry`, `JournalListResponse`, `NpcEntry`, `Quest`; add Public types near `PublicCampaign`.
- `src/frontend/src/services/api.ts:123-137` -- share calls typed with owner types -> Public types.
- `src/frontend/src/pages/SharedCampaignPage.tsx` -- switch to Public types.
- `src/frontend/src/components/JournalCard.tsx` -- `entry: JournalEntry` -> narrowed structural type (id, narrative, session_date, created_at, tags with name/tag_type/custom_category.name); other callers (`JournalList`, `HistoryPage`, `JournalInput`) pass `JournalEntry`, which still satisfies it.
- `README.md` (line ~125 "See `docs/`") -- add link to `docs/RELEASE_NOTES.md`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/share.py` -- add `PublicTagCategoryRef`, `PublicTagResponse`; use in `PublicJournalResponse.tags` -- nested tags are allow-listed too.
- `src/backend/tests/test_share.py` -- add a fixture building a campaign whose journal entry, NPC, quest, tags (built-in + custom category) have every column set, inserted via ORM; assert every mapped column is non-null after refresh; assert exact key sets (literal lists) for campaign, journal list + item + nested tag + category, journal detail, NPC, quest; assert canary absent -- locks FR-9(a).
- `src/frontend/src/types/index.ts` -- add `PublicTagCategory`, `PublicTag`, `PublicJournal`, `PublicJournalList`, `PublicNpc`, `PublicQuest` mirroring the backend fields exactly.
- `src/frontend/src/services/api.ts` -- type share getters with Public types.
- `src/frontend/src/pages/SharedCampaignPage.tsx` -- use `PublicJournalList`, `PublicNpc`, `PublicQuest`.
- `src/frontend/src/components/JournalCard.tsx` -- export a narrowed `JournalCardEntry` prop type.
- `docs/RELEASE_NOTES.md` -- new; entry for the Share Link fix.
- `README.md` -- link to release notes.

**Acceptance Criteria:**
- Given the frontend, when `npx tsc --noEmit` runs, then it passes, and adding `entry.shorthand`, `npc.notes` or `q.notes` to the share page would fail compilation.
- Given `docs/RELEASE_NOTES.md`, when an Owner reads it, then one entry says read-only Share Links no longer show Shorthand or NPC/Quest notes, collaborate links were never readable, and already-issued links keep working; `README.md` links to it.
- Given the backend suite, when it runs, then all prior tests still pass plus the new exact-key tests.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 14 findings — high 0, medium 0, low 9, false 5, maybe-false 0
- findings:
  - `[low]` `[patch]` (blind) Fill-check comment overclaims: columns with defaults are never NULL — reworded comment in tests/test_share.py; exact key sets are what catch new keys.
  - `[low]` `[reject]` (blind) Owner user_id / entry_hash / embedding values not asserted absent from bodies — exact key sets already exclude those fields and no allowed field is derived from them; extra asserts add little.
  - `[false]` `[reject]` (blind) Nested PublicTagCategoryRef wider than the page needs — campaign_id/created_at are non-sensitive (campaign_id is already on every item) and the spec requires the wire shape unchanged so issued links keep working.
  - `[low]` `[defer]` (blind) No contract check tying TS Public types to backend — pre-existing gap for all frontend types; no frontend test runner allowed in this story. Deferred.
  - `[false]` `[reject]` (blind) Collaborate token lacks exact-key test — `GET /api/share/{token}` uses one response_model (PublicCampaignResponse) for both kinds; the read_only exact-key test pins the same schema.
  - `[low]` `[reject]` (blind) Fixture data not cleaned up — matches the suite-wide pattern (conftest drops all tables per session; register/promo tests commit too); teardown adds complexity for no named harm.
  - `[low]` `[patch]` (blind) Release notes entry has no release heading — added `## Unreleased` heading, entry demoted to `###`.
  - `[low]` `[patch]` (blind) Release notes say "NPCs" but share tab says "Characters" — bullet now says "NPCs (shown on the Characters tab)". The "narrative only" wording is accurate (narrative vs shorthand), preview truncation is not a privacy claim.
  - `[low]` `[reject]` (blind) JournalCard `linkable` would link share viewers to owner route — no share caller sets `linkable`; guarding it adds a parameter for an unreachable case.
  - `[low]` `[reject]` (blind) Positive value checks thin — existing E0a.1 tests assert narrative/description values; extra value asserts are additions, not corrections.
  - `[low]` `[patch]` (intent-alignment) "adding any column" proven per-column after a manual step; default/non-null columns pass the fill guard — same root cause as row 1; comment reworded, key-set assertions still catch any new key.
  - `[false]` `[reject]` (intent-alignment) Production schema changed beyond the AC (nested tag allow-list) — permitted by E0a ownership and epic context ("nested tags ... must also be allowlisted"); wire keys unchanged and pinned by TAG_KEYS/TAG_CATEGORY_KEYS.
  - `[false]` `[reject]` (intent-alignment) tsc failure on shorthand/notes not demonstrated — implementer temporarily added entry.shorthand, npc.notes, q.notes and tsc failed on all three; strict build passes without them.
  - `[false]` `[reject]` (intent-alignment) Release entry not tied to a version — same as row 7, now under `## Unreleased`; repo has no version scheme to cite.

## Design Notes

"Every column filled" is enforced, not assumed: after insert the test iterates `Model.__table__.columns` and asserts each attribute is not None, so a new column added later must be filled in the test, which then proves it does not reach the share response.

## Verification

**Commands:**
- remote backend pytest per builder brief (lane `e0a2`) -- expected: 26 baseline + new tests pass
- `cd src/frontend && npx tsc --noEmit && npm run build` -- expected: success

## Auto Run Result

Status: done

**Summary:** Share responses are now pinned by exact key-set tests built on rows with every column filled (plus a fill guard and canary checks); nested journal tags use share-owned `PublicTagResponse`/`PublicTagCategoryRef` allow-lists (same wire keys); the frontend share page and share API calls use new `PublicJournal`/`PublicJournalList`/`PublicNpc`/`PublicQuest`/`PublicTag`/`PublicTagCategory` types; `JournalCard` takes a narrowed `JournalCardEntry`; release notes added and linked from README.

**Files changed:**
- `src/backend/app/schemas/share.py` -- nested tag allow-list schemas.
- `src/backend/tests/test_share.py` -- fully-filled fixture, fill guard, 3 exact-key tests.
- `src/frontend/src/types/index.ts` -- Public* types.
- `src/frontend/src/services/api.ts` -- share getters typed with Public* types.
- `src/frontend/src/pages/SharedCampaignPage.tsx` -- uses Public* types.
- `src/frontend/src/components/JournalCard.tsx` -- narrowed `JournalCardEntry` prop type.
- `docs/RELEASE_NOTES.md` -- new; Share Link entry under Unreleased.
- `README.md` -- link to release notes.

**Review:** 14 findings. Patched 4 low (3 fixes: test comment, Unreleased heading, Characters-tab wording). Deferred 1 low (TS/backend contract check). Rejected 9 (5 false, 4 low) with reasons in the triage log. Follow-up review: false (no high or ≥2 medium patched).

**Verification:** remote backend pytest (lane e0a2, `lorekeeper_test_e0a2`): 29 passed (26 baseline + 3 new), before and after patches. `npx tsc --noEmit` and `npm run build`: pass. Negative check: adding `entry.shorthand`/`npc.notes`/`q.notes` to the share page fails `tsc`.

**Residual risks:** a new model column with a default passes the fill guard unfilled (key sets still catch any new key). Frontend types are hand-mirrored (deferred). Sprint-status sync skipped per builder brief (orchestrator updates it at merge).
