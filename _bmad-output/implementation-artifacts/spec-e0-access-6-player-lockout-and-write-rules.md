---
title: 'E0-Access.6: Players are locked out of GM authoring and AI routes, and write rules are enforced'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '0e71df48f047b03fa4f8ad48d76ec76a218ea8c0'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Write rights are decided route by route. Players can still reach some AI helpers (generate-draft, summarize-session, one-step generate), create NPC/Quest/sheet rows they could see, and edit or delete Character Sheets and templates. Nothing refuses a reduced (preview / `audience_ctx`) ctx except the preview 404 in `require_campaign`. The router-level `require_active_account` also blocks an unpaid Player from Party reads and from redeeming a Player collaborate link.

**Approach:** Add `access.can_write(ctx, obj)`, the single write gate. Every write route calls it on the row it writes (creates call it through `check_create`). Declare `gm` on every route the story lists. Replace the router-level account gate with a fail-closed `account_gate` that exempts only routes marked Party-read. Let Player collaborate links be redeemed without a paid account. Prove all of this with EV-4 write probes.

## Boundaries & Constraints

**Always:**
- `can_write(ctx, obj)` raises `not_found()` (never 403) when: `ctx.read_only` (preview or any `audience_ctx` result), `ctx.role == anon`, or the row belongs to another Campaign. Otherwise `gm` (and a system ctx) may write any row of the Campaign. `player` may write only a `JournalEntry` with `kind=player` and `user_id = ctx.user_id`, and a `CharacterSheet` whose `pc_entity_id` resolves to an Entity with `linked_user_id = ctx.user_id`. That second check is always false until F3-world adds `entities`. `may_write` is the boolean form.
- `check_create` ends with `can_write`, so every create goes through the gate.
- These routes declare `gm` and refuse a Player with the missing-record 404 before any LLM config is resolved or any usage is metered: NPC / Quest generate, create, update and delete; NPC extract; Quest suggest; journal recap, summarize-session, autocomplete (with a Campaign), reindex, generate-draft and generate; session-plan generate and writes; shorthand, tag-category and source writes.
- Journal tag attach / detach and delete need `player` in the entry's Campaign, then `scoped_get`, then `can_write(ctx, entry)`. So a Player may tag, untag and delete their own `kind=player` entries. A GM-kind entry they wrote, another user's entry, and a hidden entry all return the same 404 as a missing one.
- Character Sheet and template writes keep `player` dependencies and call `can_write`. Today that means only GMs may write them.
- Management (PATCH / DELETE Campaign, Share Links, members) stays `require_campaign("owner")`; a Co-GM gets the 404.
- `account_gate` (app/api/deps.py) is the router-level dependency for feature routers. It applies `require_active_account` unless the matched route carries `openapi_extra=PARTY_READ`. PARTY_READ goes only on safe-method routes that take a `player` ctx (or a role map) and make no hosted-AI call. Each route module documents this. `POST /api/share/{token}/join` checks the account only when the link grants a Role other than `player` (a NULL Role counts as player).
- The only duplicate check (journal `entry_hash`) is now on a GM-only route and stays keyed per (Campaign, user), so no 409 can reveal another author's row.
- EV-4: write probes as described in the matrix. `leaks=0`. `pending_baseline.txt` shrinks by the routes newly probed (`POST /api/campaigns/`, `POST /api/campaigns/generate-concept`).
- Frontend gating is cosmetic and goes through `useEffectiveRole`. EntryDetailPage, DashboardPage (New Entry + Recap) and CharacterSheetsPage hide write controls for non-GMs.

**Never:** `set_visibility` / `visibility.py` or Visibility writers (E0-Access.9). Edits to `check_scoped_queries.py`, and new scoped-query baseline lines. `app/jobs`, stt. New Player Journal create routes (E7). Changing chat-session ownership rules (owner rows via `owned_get`, E0-Access.8). Members / Roles API (E0-Access.12). Schemas gaining `kind` / `user_id` / `can_write` fields. Models or migrations.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Player on a GM route | Player POST generate-draft / summarize / generate / NPC create in A | 404 byte-identical to a missing Campaign; no LLM call, no meter, no row | `not_found()` |
| Player own entry | Player DELETE / tag own `kind=player` entry | 204 / 201 | — |
| Player other entry | another Player's `kind=player` entry, own `kind=gm` entry | 404 like missing; row untouched | `not_found()` |
| Preview write | GM + `X-Lorekeeper-Preview: member` on any write | 404 like missing; nothing written | `not_found()` |
| Reduced ctx | `can_write(audience_ctx(...), row)` | refused | `NotFound` |
| Sheet write | Player PATCH / DELETE a visible sheet | 404 like missing | `not_found()` |
| Unpaid Player | GET journals / campaigns / me / tags in A | 200 | — |
| Unpaid Player AI | POST chat / generate-draft | 402 account-gate | existing |
| Join | unpaid user redeems Player link / co_gm link | 200 / 402 | existing 402 |

</intent-contract>

## Code Map

- `src/backend/app/access/write.py` (new) -- `can_write`, `may_write`; imports policy/context only.
- `src/backend/app/access/projection.py:193` `check_create` -- append `can_write(ctx, obj)`.
- `src/backend/app/access/__init__.py` -- export `can_write`, `may_write`.
- `src/backend/app/api/deps.py` -- `PARTY_READ`, `account_gate(request, user)` (reads `request.scope["route"].openapi_extra`).
- `src/backend/app/main.py:136-160` -- `gate = [Depends(account_gate)]` plus a comment.
- `src/backend/app/api/routes/journals.py` -- `_entry_gm` becomes `_entry_player` + `can_write`; generate-draft / generate / summarize get `"gm"`; reindex calls `can_write` per entry; PARTY_READ on list / get.
- `src/backend/app/api/routes/{npcs,quests}.py` -- `_npc_gm` / `_quest_gm` for put / delete / generate (`_visible_*` uses gm); create `"gm"`; `can_write`; PARTY_READ on reads.
- `src/backend/app/api/routes/{shorthand,session_plans,sources,campaigns,character_sheets}.py` -- `can_write` after each `scoped_get` on writes; PARTY_READ on Party reads.
- `src/backend/app/api/routes/{tags,members,chat}.py` -- PARTY_READ on reads (chat sessions list / get).
- `src/backend/app/api/routes/share.py:118` -- join: `get_current_user`, gate only non-player links.
- `src/backend/tests/ev4/probes/{journals,ai_routes,npcs,quests,character_sheets}.py` -- expectations follow the new rules; `probes/write_rules.py` (new) adds preview-write probes and the two campaign-create probes; `tests/ev4/pending_baseline.txt` and `test_coverage.py` FROZEN_PENDING minus 2.
- `src/backend/tests/access/test_write_rules.py` (new) -- `can_write` unit matrix, account gate, join gate.
- Existing tests expecting Player writes/AI (test_campaign_permissions, test_journals, test_party_*) -- update to the new rules.
- `src/frontend/src/pages/{EntryDetailPage,DashboardPage,CharacterSheetsPage}.tsx` -- `useEffectiveRole(...).isGm` gating.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/write.py` + `projection.py` + `__init__.py` -- write gate.
- Route modules in the Code Map -- gm declarations, `can_write`, PARTY_READ.
- `deps.py`, `main.py`, `share.py` -- account gate.
- EV-4 probes + pending baseline -- write probes.
- `tests/access/test_write_rules.py` -- unit and route tests for the matrix.
- Frontend pages -- cosmetic gating.

**Acceptance Criteria:**
- Given CI (backend-tests, gates incl. EV-4 and CI-8, frontend-ci, licence), when it runs, then everything is green with `leaks=0`.
- Given `grep -rn "read_only" src/backend/app/access/write.py`, then the reduced-ctx refusal is in `can_write`, not only in the preview 404.
- Given `scripts/scoped_queries_baseline.txt`, then no line was added.

## Spec Change Log

## Review Triage Log

## Design Notes

The tech note asks for a per-route `require_campaign_paid()` on AI routes. Instead, the router-level gate stays and is fail-closed: a route is ungated only if it opts in with `PARTY_READ`. The effect on today's routes is the same: AI routes, GM authoring and management stay gated, and Party reads are open. The difference is that a new route is gated by default, which matches the spine's "the exemption covers Party routes only".

`can_write` is sync and takes the loaded row. The sheet rule returns False without a query until F3-world adds `entities`, and E7 / F3 can widen it there.

## Verification

**Commands:**
- `bash /private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/a6_test.sh -q` -- expected: all pass, `EV-4: ... leaks=0`.
- `python scripts/check_scoped_queries.py`; `lint-imports` -- expected: clean.
- `cd src/frontend && npx tsc --noEmit && npm run build` -- expected: pass.
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: green.

## Auto Run Result

Status: in-review (implemented and verified; the step-04 review layers have not run yet, because the orchestrator asked for commit, rebase and PR first).

**Summary:** `access.can_write` / `may_write` (`app/access/write.py`) is the single write gate. It refuses reduced (read_only) and anon ctxs and rows from another Campaign. GMs may write any row. Players may write only their own `kind=player` entries; the linked-PC sheet check stays false until F3-world. `check_create` ends with `can_write`. The story's GM-only routes declare `gm` before any LLM config is resolved. Journal delete and tag attach / detach are `player` + `can_write`. Sheet and template writes go through `can_write`. `account_gate` fails closed and exempts only `PARTY_READ` safe-method routes. Join gates only non-Player links. Rebased onto origin/main (E0-Access.9, E0-Jobs.4/5, E0-QA.15, v1.1); the only conflict was the `app/access/__init__.py` exports.

**Verification:** desktop full suite (cached image, isolated pg + valkey, removed afterwards): 1738 passed, 4 skipped; `EV-4: probes=91 exemptions=1 pending=44 leaks=0`. `check_scoped_queries.py` ok, with no baseline lines added and no script edits. Frontend `tsc --noEmit` and `npm run build` pass. CI runs on PR #61.

**Needs desktop verification:** nothing specific (no Ollama, GPU, compose or nginx surface).

**Residual risks / follow-ups:** E0-Access.9's `set_visibility` (bulk route, GM-only) does not call `can_write` itself, so E0-Access.9's owner may want to fold it in. The frontend still sends unpaid users to /subscribe on login, so a Party-read-only Player's UI path needs E7 / billing UX. The UI shows Players no entry write controls, because no route creates `kind=player` entries until E7.
