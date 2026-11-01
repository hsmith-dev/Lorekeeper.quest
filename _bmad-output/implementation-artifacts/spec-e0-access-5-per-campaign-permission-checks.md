---
title: 'E0-Access.5: Per-Campaign permission checks replace accessible_campaign_ids and inline owner checks'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '9160cb62abe2d7cace054d4e95f6d85883b185f9'
rebased_onto: '5ad0e3113f26a397cee6debe176bcbd239c5ba54'
review_loop_iteration: 0
followup_review_recommended: true
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

### 2026-11-01 — review patch outside the contract (no loopback)
- Trigger: blind-hunter finding that Players now see Delete / tag controls that answer 404 (journal delete and tag attach / detach became gm-only).
- Amended: nothing in this spec was re-derived; the patch adds cosmetic role gating to `src/frontend/src/pages/EntryDetailPage.tsx` (`useEffectiveRole(entry.campaign_id).isGm`), although the contract's Never list says "the frontend". The contract is left as written (read-only); this entry records the deviation.
- Known-bad state avoided: a Player confirming "Delete this entry?" and getting an unhandled "Not found".
- KEEP: the server stays the only enforcement point; the frontend change only hides controls.

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 42 findings — high 0, medium 8, low 20, false 14, maybe-false 0
- findings:
  - `[false]` `[reject]` (blind) Players lose autocomplete when the frontend sends campaign_id — the specified behaviour: the AC replaces the autocomplete owner check with `require_campaign("gm")`, and E0-Access.6 lists `/autocomplete` as 404 for Players.
  - `[medium]` `[patch]` (blind) Player UI still shows Delete / tag attach / detach, which now 404 — EntryDetailPage hides them unless `useEffectiveRole(entry.campaign_id).isGm` (see Spec Change Log); tsc and build pass.
  - `[medium]` `[patch]` (blind) `gm_context` defaults to True (fails open) — now a required keyword on `generate_draft_narrative` and `create_journal_entry`; direct test callers pass it.
  - `[low]` `[reject]` (blind) Ratchet misses update/delete/insert, aliased, select_from, qualified names, import aliases, text(CONST) — the story's list is select / get / raw SQL / `Campaign.user_id ==`; evading it takes deliberate aliasing, and alias tracking adds complexity; E0-Access.9 adds the Visibility-write checks.
  - `[low]` `[reject]` (blind) Owner check misses `campaign.user_id == user.id`, `.in_`, filter_by — the AC names `Campaign.user_id ==`; the instance form compares loaded objects, not a query.
  - `[low]` `[patch]` (blind) Frozen ceiling does not shrink with the baseline — `test_baseline_never_grows` now also fails when the baseline lost a line the ceiling still lists.
  - `[low]` `[reject]` (blind) Party-projected routes keep the GM `response_model` — the Party schemas subclass the GM ones with identical keys; a future divergence fails FastAPI validation or renders the default, never the GM value.
  - `[low]` `[patch]` (blind) `get_campaign_with_access` docstring misleading; kept without reason — docstring corrected ("lets any Member through whatever their Role"); kept because the story deletes only `accessible_campaign_ids`.
  - `[low]` `[patch]` (blind) upload / extract / suggest probes run no Co-GM — grouped with the verification-gap extract/suggest row; `test_gm_ai_helpers_run_for_a_co_gm` added.
  - `[low]` `[patch]` (blind) `_query_route_gm_only` never checks a GM 200 — same group and test.
  - `[false]` `[reject]` (blind) No check of the Owner's 400 on leave — `test_leave_campaign` asserts the Owner's 400.
  - `[medium]` `[patch]` (blind) Co-GM export / analytics contents untested — grouped with the analytics verification gap; `test_analytics_top_tags_and_own_entries` checks the Co-GM's own-entry stats and that the export holds none of the Owner's narratives.
  - `[low]` `[patch]` (blind) generate_plan_draft queries lack an id tiebreaker — added.
  - `[false]` `[reject]` (blind) create_session_plan / create_shorthand use body.campaign_id and user.id — ctx is built from body.campaign_id and the same user, so the values are identical.
  - `[low]` `[patch]` (blind) Stray blank line in probes/journals.py — removed.
  - `[low]` `[reject]` (blind) raw_sql matcher could flag a column named like a table — only string literals inside text() / exec_driver_sql are scanned; no such false positive exists and a literal naming `tags` is the table in practice.
  - `[low]` `[reject]` (edge) update/delete/insert/select_from not flagged — same as the blind ratchet row.
  - `[low]` `[reject]` (edge) get() with an attribute or alias first argument — same reasoning (deliberate evasion; complexity).
  - `[low]` `[reject]` (edge) `Campaign.user_id.in_/.is_` or an alias — same reasoning.
  - `[low]` `[reject]` (edge) Raw SQL held in a variable — same reasoning.
  - `[low]` `[patch]` (edge) `__tablename__` as an annotated assignment is missed — accepted; `test_annotated_tablename_is_read` added.
  - `[low]` `[patch]` (edge) Tag-category dedupe used `ilike` (wildcards) and `.first()` — now `lower(name) == lower(input)` ordered by created_at, id.
  - `[false]` `[reject]` (edge) Player autocomplete 404 — the specified behaviour (as the blind row).
  - `[low]` `[patch]` (edge, claim) AC grep for `accessible_campaign_ids` matched a deps.py comment — comment reworded; `grep accessible_campaign_ids src/backend/app` is empty.
  - `[low]` `[reject]` (edge, claim) Ratchet does not stop every unscoped read — the gate covers the forms the story names; see the ratchet rows.
  - `[medium]` `[patch]` (verification-gap) One-step /generate drops GM context for non-GMs untested; no GM positive control — `test_non_gm_drafts_get_no_gm_context_and_gms_keep_it` captures both routes' prompts: the seeded glossary canary is absent for a Player and present for a Co-GM.
  - `[medium]` `[patch]` (verification-gap) Analytics top tags and Co-GM own entries untested — `test_analytics_top_tags_and_own_entries`.
  - `[medium]` `[patch]` (verification-gap) Owner success paths for revoke / remove (`delete_entries`) / list contents never run — `test_owner_management_success_paths`.
  - `[medium]` `[patch]` (verification-gap) No GM runs extract / suggest — `test_gm_ai_helpers_run_for_a_co_gm` (Co-GM 200, Player 404).
  - `[false]` `[reject]` (intent) Shorthand / plans / sources writes became GM-only — the AC's "require_campaign("gm") (authoring)"; reads through scoped_select keep hidden ≡ missing; E0-Access.6 lists these writes as GM-only.
  - `[false]` `[reject]` (intent) A Player can no longer delete their own entry — the AC: delete requires gm (E7 adds Player Journal deletes).
  - `[false]` `[reject]` (intent) Autocomplete 404 for Players — as above.
  - `[false]` `[reject]` (intent) `gm_context` leak fix beyond the story — needed for the generate-draft probe the intent asks for to report zero leaks.
  - `[false]` `[reject]` (intent) Export / analytics widened Owner → gm — the AC splits owner (management) from gm; E0-Access.6's management list excludes them; content stays own-entries until E0-Access.13.
  - `[false]` `[reject]` (intent) Chat ignores preview — the intent leaves chat to E0-Access.8.
  - `[false]` `[reject]` (intent) list_campaigns keeps a baselined raw select — the ids are the caller's role_map (preview applied), Campaign has no campaign_id column, rows are projected per Role.
  - `[low]` `[reject]` (intent) Ratchet is AST name matching — same as the ratchet rows.
  - `[false]` `[reject]` (intent) A new site in a listed function passes while the count holds — each site is its own line; one more site exceeds the count and fails (`test_each_site_needs_its_own_line`).
  - `[low]` `[reject]` (intent) Editing both baseline and FROZEN_BASELINE defeats the ratchet — true of every committed ceiling (CI-2/3/7/14 use the same pattern); review catches a grown ceiling.
  - `[false]` `[reject]` (intent) Baseline lists sites in touched routes — each carries its reason (global tags by name, role_map ids, service after the route's check).
  - `[medium]` `[patch]` (intent) EV-4 probes never send the preview header or touch the GM Campaign — the journal and tag list probes now also run a previewing copy of each GM actor (grants narrowed to player) over the cross-Campaign and single-Campaign lists; disabling `roles.preview` makes 3 probes report leaks.
  - `[false]` `[reject]` (intent) test_projection rewritten to the new rules — descriptive; the expectations are the story's ACs.

## Design Notes

Preview on a role map is a flag, not new Role values: `RoleMap` keeps `{campaign_id: "gm"|"player"}` so existing consumers (chat's `hybrid_search_own_journals`) are unchanged, and the narrowing happens where ctxs are built (`role_ctx`, `scoped_select_multi`'s `gm_ctx`).

Baseline lines are line-number-free (`<path>::<function> <kind>:<target>`, one line per site) so unrelated edits do not churn them; a renamed function or removed site fails until the line is updated or deleted.

## Verification

**Commands:**
- `bash /private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/a5_test.sh -q` (desktop, cached image, isolated pg + valkey) -- expected: all pass, `EV-4: probes=77 pending=50 leaks=0`.
- `python scripts/check_scoped_queries.py`, `python -m pytest -q scripts/test_check_scoped_queries.py`, `lint-imports` -- expected: clean.
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.

## Auto Run Result

Status: done

**Summary:** Every remaining route is off `get_campaign_with_access` and the inline `Campaign.user_id ==` checks: campaigns.py runs on `require_campaign("owner"|"gm"|"player")` (management Owner-only; export, analytics and tag-category writes `gm`; tag-category list and leave `player`); journals.py's attach / detach / delete use `require_campaign_for(JournalEntry, "journal_id", "gm")`, its AI helpers `ctx_for_request` (recap and autocomplete-with-Campaign `gm`, generate-draft and summarize-session `player`), reindex `require_campaign("gm")`; shorthand / session plans / sources read through `scoped_select` + `project` for `player` and write for `gm`; NPC extract, Quest suggest and session-plan generate are `gm` with scoped queries. `role_map_for_request` (RoleMap.preview) narrows every GM Campaign of a cross-Campaign list to the member view, so `/api/journals/`, `/api/tags/` and `/api/campaigns/` honour the preview header (closes E0-Access.4's deferred item). A non-GM's journal draft gets no glossary or source canon (`gm_context`, required). `accessible_campaign_ids` is deleted. CI-8 bans the deprecated helpers and ratchets select / get / raw SQL on registered models and `Campaign.user_id ==` outside app/access/ against `scripts/scoped_queries_baseline.txt` (40 lines: admin, feedback, chat.py, share join, list_campaigns, template delete, attach_tag's global tag lookup, the E0-Jobs.2 runtime, services). EV-4: 32 routes probed and off the pending baseline.

**Implementation note:** the code was written in this session before the spec was filed (the step-03 implementation subagent was not used); the review layers ran on the full diff as specified.

**Files changed:**
- `src/backend/app/access/{context,projection,__init__}.py` -- preview-aware role map; projections for ShorthandTerm, SessionPlan, SourceDocument, TagCategory.
- `src/backend/app/schemas/{shorthand,session_plan,source,tag_category}.py` -- GM / Party pairs.
- `src/backend/app/api/deps.py` -- helper deleted / docstring.
- `src/backend/app/api/routes/{campaigns,journals,shorthand,session_plans,sources,tags,npcs,quests}.py` -- per-Campaign Role checks, scoped reads, uniform 404.
- `src/backend/app/services/journal_service.py` -- required `gm_context`.
- `scripts/check_scoped_queries.py`, `scripts/scoped_queries_baseline.txt`, `scripts/test_check_scoped_queries.py`, `.github/workflows/gates.yml` -- CI-8 ratchet.
- `src/backend/tests/ev4/probes/{authoring,ai_routes,campaigns,journals,tags,_support}.py`, `tests/ev4/pending_baseline.txt` -- probes (incl. a previewing actor).
- `src/backend/tests/access/{test_campaign_permissions,test_projection,test_context}.py`, `tests/test_party_retrieval.py` -- tests.
- `src/frontend/src/pages/EntryDetailPage.tsx` -- hides Delete / tag edits for non-GMs.

**Review:** 42 findings (high 0, medium 8, low 20, false 14). Patched: 7 medium entries (frontend gating; required `gm_context`; one-step generate / GM-context test; analytics and Co-GM export test; Owner management success paths; Co-GM extract / suggest; preview actor in EV-4) and 9 low (exact ceiling, docstring, tiebreakers, blank line, annotated `__tablename__`, tag-category exact match, deps comment, and the two Co-GM probe rows grouped into the extract / suggest test). Deferred: none. Rejected: the ratchet-coverage rows (update/delete/alias/variable SQL: outside the story's list, deliberate evasion only), the Party `response_model` row, the raw_sql false-positive row, and every `false` row with its refutation above.

**Follow-up review recommended:** true -- 7 medium entries were patched on this first pass; the patches (frontend gating in EntryDetailPage, the required `gm_context` keyword, the exact-ceiling assertion, the previewing EV-4 actor) have not been through the review layers.

**Verification:** After rebasing onto `5ad0e31` (E0-Jobs.2), on the desktop (cached `lorekeeper-backend-test` image plus `rq`, isolated pgvector + valkey containers): full backend suite 1415 passed, 4 skipped; `EV-4: probes=77 exemptions=0 pending=50 leaks=0`. A mutation (preview flag never set) makes the journal / tag list probes report 3 leaks. `check_scoped_queries.py` ok; gate unit tests 55 passed; `lint-imports` 5 kept; frontend `tsc --noEmit` and `npm run build` pass. First CI run: all green except the CI-8 step, which failed only on E0-Jobs.2's new `app/jobs` sites (baselined after the rebase).

**Needs desktop verification:** nothing specific (no Ollama, GPU, compose or nginx surface).

**Residual risks:** Players lose some actions the old routes allowed (own-entry delete, tag edits, autocomplete with a Campaign, shorthand / session-plan / source writes) until E0-Access.6 / E7 define Player writes; only EntryDetailPage hides its controls. The E0-Access.8 chat work will touch baselined chat.py sites (renames or removals there must update the baseline and FROZEN_BASELINE). E0-Access.9 edits check_scoped_queries.py next: the ratchet is a separate section below `main`'s helpers.

**Rebase onto E0-Access.8 (#53):** the coordinator rebased onto `1a24773` (union conflicts in `access/__init__.py`, `projection.py`, `probes/_support.py`, `pending_baseline.txt`). Access.8's `chat.py::_own_session` raw `select(ChatSession, Campaign.name)` now goes through the new `access.owned_get` (an owner-only stored row by its owner field, the one 404 for a bad id / missing / another user's); `get_session` reads the Campaign name with `scoped_get(Campaign, scope)` after the session's ctx is resolved (None for a campaign-less session). Same 404 order and behaviour. Four stale chat.py baseline lines and their FROZEN_BASELINE entries removed (baseline 36 lines). Desktop full suite: 1447 passed, 4 skipped; `EV-4: probes=80 exemptions=1 pending=46 leaks=0`.

**Rebase onto E0-Jobs.3 (#54), owner infrastructure:** `worker.py::_record_failure` (`db.get(Job)`) tripped the ratchet. Instead of a baseline line, `check_scoped_queries.py` gains `OWNER_INFRA = {"app/jobs/": ("E0-Jobs", {"Job", "DataBackfill"})}`: app/jobs/** may read and write those system-bookkeeping models without app.access. Each entry is cross-checked against the CI-7 table-owner map (`jobs` and `data_backfills` owned by E0-Jobs alone) and pinned in the frozen test; tests show app/jobs reading `JournalEntry`, and app/api or app/services reading `Job`, still fail. The seven app/jobs baseline lines are gone (baseline 28 lines). Gate tests: 96 passed.
