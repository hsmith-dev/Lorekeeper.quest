---
title: 'E0-Access.5: Per-Campaign permission checks replace accessible_campaign_ids and inline owner checks'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '9160cb62abe2d7cace054d4e95f6d85883b185f9'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Routes still on the deprecated helpers (`get_campaign_with_access`, `accessible_campaign_ids`) and inline `Campaign.user_id ==` owner checks treat every Member alike, ignore the caller's Role in the record's own Campaign and ignore the preview header; cross-Campaign lists (`/api/journals/`, `/api/tags/`, `/api/campaigns/` without a Campaign) ignore preview too. Nothing stops new code from reading registered rows outside `app/access/`.

**Approach:** Move every remaining route onto `require_campaign(min_role)` / `require_campaign_for` / `ctx_for_request`, `scoped_select` / `scoped_get` / `scoped_select_multi` and `project`; add `role_map_for_request` so cross-Campaign lists narrow under preview; delete `accessible_campaign_ids`; extend `scripts/check_scoped_queries.py` (CI-8) with a deprecated-helper ban and a shrink-only scoped-query ratchet against `scripts/scoped_queries_baseline.txt`; prove the moved routes with EV-4 probes (`cross_gm_player` the main actor).

## Boundaries & Constraints

**Always:**
- Each list / get / tag / delete route applies the caller's Role in the record's own Campaign (GM in A grants nothing in B). Every denial is the one `404 {"detail":"Not found"}`.
- Journal tag attach / detach and journal delete need `gm` in the entry's Campaign (Owner or Co-GM). A Player gets the 404 even on a visible or own entry.
- `tags.py` counts and lists only tags on links visible to the ctx (kept from E0-Access.4; the tag rows themselves are now read through `scoped_select(_multi)(Tag, ...)`).
- Inline owner checks become `require_campaign("owner")` for management (PATCH / DELETE Campaign, Share Links list / create / revoke, members list / remove) and `require_campaign("gm")` for authoring and GM reads (export, analytics, tag-category create / delete, autocomplete with a Campaign, recap, session-plan generate, NPC extract, Quest suggest, shorthand / session-plan / source writes, reindex). Party reads (`shorthand`, `session-plans`, `sources`, `tag-categories` lists, session-plan get) and leave / summarize-session / generate-draft need `player` and read through `scoped_select` / `scoped_get` + `project`.
- Autocomplete with `campaign_id` works for a Co-GM (Campaign name and genre as context); without `campaign_id` it gives no Campaign context to anyone.
- A non-GM's journal draft (generate-draft, and /generate without a narrative) gets no GM-only LLM context (no Shorthand glossary, no source canon).
- Preview: `role_map_for_request(request, db, user)` with `X-Lorekeeper-Preview: member` narrows every GM Campaign of the map to the member view (`role_ctx` and `scoped_select_multi`); Player Campaigns unchanged; a non-safe method is 404 when it narrows anything. The header only narrows, never widens. `/api/campaigns/{id}/me` keeps `preview=False`.
- CI-8: `check_scoped_queries.py` fails on any reference to `get_campaign_with_access` / `accessible_campaign_ids` under app/ (the deprecated definition of `get_campaign_with_access` in `app/api/deps.py` excepted), and on any `select(<registered model>)`, `<session>.get(<registered model>)`, raw SQL naming a registered table or `Campaign.user_id ==` / `!=` outside `app/access/` that is not in the baseline. Stale baseline lines fail; `scripts/test_check_scoped_queries.py` freezes the ceiling. Registered models are read from `REGISTRY` in `app/access/registry.py`, tables from `__tablename__`.
- `accessible_campaign_ids` is deleted. `get_campaign_with_access` stays as a deprecated thin wrapper (no callers).
- EV-4: every moved route gets a probe and leaves `pending_baseline.txt`; zero leaks.

**Never:** chat routes or `chat_service.py` (E0-Access.8; its sites stay baselined); `app/jobs`, stt, benchmarks; `can_write` and Player write rules beyond the gm requirement (E0-Access.6); `set_visibility` or Visibility writes (E0-Access.9); export / analytics widening to every Member (E0-Access.13); collaborate-link join (E0-Access.12); models or migrations; the frontend.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Cross-Campaign GM/Player | cross_gm_player attaches / deletes in A (Player) and B (GM) | A: 404, nothing written; B: 201 / 204 | `not_found()` |
| Co-GM management | PATCH / DELETE Campaign, share list / create, members list | 404; Owner 200 | `not_found()` |
| Co-GM authoring | export, analytics, tag-category create / delete, autocomplete with Campaign | 200 / 201 / 204; Player 404 | `not_found()` |
| Preview, cross-Campaign | GM of B with header on `/api/journals/`, `/api/tags/`, `/api/campaigns/` | B's GM-only entries, Shorthand, Shorthand-only tags absent; search ignores Shorthand words | — |
| Preview never widens | Player with header on lists | identical bodies to no header | — |
| Preview write | header + POST via role_map_for_request / require_campaign | 404 | `not_found()` |
| Party reads | Player lists shorthand / plans / sources / tag-categories | only party-visible rows; GM-only rows change nothing | — |
| Authoring writes | Player PUT / DELETE on a party-visible term or plan | 404, row untouched | `not_found()` |
| Player draft | Player generate-draft in A | 200; LLM context holds no glossary / source canary | — |
| Leave | Owner / Member / ex-Member | 400 / 204 / 404 | `not_found()` |
| CI-8 | new `select(JournalEntry)` in a route; stale baseline line; deprecated helper import | check fails with a hint | exit 1 |

</intent-contract>

## Code Map

- `src/backend/app/access/context.py` -- `RoleMap.preview`, `role_map_for_request`, preview-aware `role_ctx` and `scoped_select_multi` (member view via `audience_ctx`).
- `src/backend/app/access/projection.py` -- PROJECTIONS gain ShorthandTerm, SessionPlan, SourceDocument, TagCategory (Party schema = GM keys today).
- `src/backend/app/schemas/{shorthand,session_plan,source,tag_category}.py` -- `<X>GMResponse` / `<X>PartyResponse`; old names alias GM.
- `src/backend/app/api/deps.py` -- `accessible_campaign_ids` deleted; `get_campaign_with_access` reads through `scoped_get`.
- `src/backend/app/api/routes/campaigns.py` -- every route on `_owner` / `_gm` / `_player`; export / analytics scoped to the caller's own entries via `scoped_select`.
- `src/backend/app/api/routes/journals.py` -- list on `scoped_select(_multi)` + `role_map_for_request`; `_entry_gm` for attach / detach / delete; AI routes on `ctx_for_request`; reindex `require_campaign("gm")`.
- `src/backend/app/api/routes/{shorthand,session_plans,sources,tags,npcs,quests}.py` -- moved routes.
- `src/backend/app/services/journal_service.py` -- `gm_context` keyword on `generate_draft_narrative` / `create_journal_entry`.
- `scripts/check_scoped_queries.py`, `scripts/scoped_queries_baseline.txt`, `scripts/test_check_scoped_queries.py`, `.github/workflows/gates.yml` -- CI-8 ratchet.
- `src/backend/tests/ev4/probes/{authoring,ai_routes,campaigns,journals,_support}.py`, `tests/ev4/pending_baseline.txt` -- probes; 32 pending lines removed.
- `src/backend/tests/access/test_campaign_permissions.py`, `tests/access/{test_projection,test_context}.py` -- unit / route tests.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/context.py` -- preview-aware role map -- cross-Campaign preview.
- Routes listed in the Code Map -- move onto require_campaign / scoped queries / project -- per-Campaign Role, uniform 404.
- `scripts/check_scoped_queries.py` + baseline + tests + `gates.yml` comment -- CI-8 ratchet and helper ban.
- `src/backend/tests/ev4/probes/*` + `pending_baseline.txt` -- probes for the moved routes.
- `src/backend/tests/access/test_campaign_permissions.py` -- matrix rows.

**Acceptance Criteria:**
- Given CI, when backend-tests, gates (lint-imports, check_scoped_queries and its unit tests, EV-4, CI-11) and frontend-ci run, then all pass.
- Given EV-4, then `leaks=0`, `pending` is 50 (82 minus the 32 moved routes) and every moved route has a probe.
- Given `grep accessible_campaign_ids src/backend/app`, then nothing matches.

## Spec Change Log

## Review Triage Log

## Design Notes

Preview on a role map is a flag, not new Role values: `RoleMap` keeps `{campaign_id: "gm"|"player"}` so existing consumers (chat's `hybrid_search_own_journals`) are unchanged, and the narrowing happens where ctxs are built (`role_ctx`, `scoped_select_multi`'s `gm_ctx`).

Baseline lines are line-number-free (`<path>::<function> <kind>:<target>`, one line per site) so unrelated edits do not churn them; a renamed function or removed site fails until the line is updated or deleted.

## Verification

**Commands:**
- `bash /private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/a5_test.sh -q` (desktop, cached image, isolated pg + valkey) -- expected: all pass, `EV-4: probes=77 pending=50 leaks=0`.
- `python scripts/check_scoped_queries.py`, `python -m pytest -q scripts/test_check_scoped_queries.py`, `lint-imports` -- expected: clean.
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.
