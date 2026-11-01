---
title: 'E0-Access.2: CampaignContext, require_campaign and the Role map'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: 'f0431584b210413cf9f9812dc7a3f04ce3705998'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Nothing resolves a request to the caller's Role in a specific Campaign; routes use `get_campaign_with_access` / `accessible_campaign_ids`, which treat every Member alike and leak "GM here" into "GM everywhere" once Roles matter. E0-Access.3–13 and every feature epic need the `app/access/` names to exist.

**Approach:** Create `app/access/` (`context.py`, `policy.py`, `audience.py`, `identity.py`, `__init__.py`) exporting `CampaignContext`, `require_campaign`, `require_campaign_for`, `role_map`, `scoped_select_multi`, `ctx_for`, `not_found`, `SystemReason`; turn the two `deps.py` helpers into deprecated wrappers; add `GET /api/campaigns/{id}/me` (`api/routes/members.py`) and the frontend `useCampaignRole`, wired into `useRoleFor`; add the `as_system(` CI check.

## Boundaries & Constraints

**Always:** one 404 body `{"detail":"Not found"}` for too-low Role, non-member, missing Campaign, missing/invalid row id (via `not_found()`); Role is per Campaign (Owner → `gm`+`is_owner`, `co_gm` → `gm`, `player` → `player`); `min_role` order `player < gm < owner`; `require_campaign` never returns a system ctx; reuse `app.domain.enums.CampaignRole`; `app.access` sits between services and schemas in the import-linter layers (spine table: access imports db, schemas, domain, core; never clients/services/api); frontend role gating is cosmetic.

**Never:** registry/Audience predicates, `scoped_select`, `audience_ctx`, the `X-Lorekeeper-Preview` behaviour (all E0-Access.3); migrating existing route callers off the deprecated helpers (E0-Access.5); Members management API (E0-Access.12); `app/access/enums.py`; touching `fake_llm.py`, `llm_provider.py`, the stt sidecar, `sprint-status.yaml`, `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Owner | Owner of C, `require_campaign("owner")` | ctx role `gm`, `is_owner=True`, `grant_id=None`, `access_epoch=0` | — |
| Co-GM | member role `co_gm`, epoch 3, `require_campaign("gm")` | role `gm`, `is_owner=False`, `grant_id=member.id`, `access_epoch=3` | `"owner"` → 404 |
| Player | member role `player`, `require_campaign("player")` | role `player` | `"gm"`/`"owner"` → 404 |
| Cross-Campaign | Owner of B, Player in A | A: role `player`; B: `gm` | `gm` route on A → 404 |
| Non-member / missing | not a member, or random UUID | — | identical 404 `{"detail":"Not found"}` |
| Item route | `require_campaign_for(JournalEntry, "journal_id", "player")` | ctx for the row's Campaign | missing row / non-UUID id → same 404 |
| `/me` | Owner / Co-GM / Player | `{campaign_id, role, is_owner, display_role: Owner/Co-GM/Player}` | non-member → 404 |
| `as_system` | `"entry_deleted"`/`"merge"` | role `gm`, `actor="system"`, same ids, `system_reason` set | other reason → `ValueError` |
| `ctx_for` | user still Owner/Member | same ctx as `require_campaign` now | removed → `not_found()` |
| `role_map` + `scoped_select_multi` | Owner of B, Player in A, nothing in C | rows of A and B only; `{A: player, B: gm}` | empty map → no rows |

</intent-contract>

## Code Map

- `src/backend/app/api/deps.py` -- `get_current_user`/`bearer_scheme` (move to `app/access/identity.py`, re-export same objects so `dependency_overrides[get_current_user]` in `tests/test_llm_provider_gate.py` keeps working); `get_campaign_with_access` (:104-136) and `accessible_campaign_ids` (:139-149) become wrappers over `ctx_for`/`role_map` (55 call sites stay until E0-Access.5).
- `src/backend/app/db/models/campaign_member.py` -- `role: CampaignRole`, `access_epoch`; `campaign.py` -- `Campaign.user_id` is the Owner.
- `src/backend/app/domain/enums.py` -- `CampaignRole {co_gm, player}` (reuse).
- `src/backend/.importlinter` + `scripts/test_import_ratchet.py` -- layers contract (add `app.access` under `app.services`), domain/clients/clients_callers/models contracts gain `app.access`; ratchet test pins `REQUIRED_LAYERS` and source sets.
- `src/backend/app/main.py` -- router registration (:125-149, `gate`), CORS `allow_headers` (:73) gains `X-Lorekeeper-Preview`.
- `src/backend/tests/ev4/` -- `fixtures.py` actors (`co_gm` stored `co_gm`, grants `gm`), `probes/__init__.py` template, `families.assert_hidden_equals_missing`, `test_coverage.py` (new route needs a probe; pending baseline untouched).
- `src/backend/tests/conftest.py` -- `db`, `client` fixtures (override `get_db`).
- `.github/workflows/gates.yml` -- reserved CI-8 slot and "Gate unit tests" step.
- `src/frontend/src/hooks/useEffectiveRole.ts` -- `roleFromMe`, `isGmRole`, `roleStateFor`, `useRoleFor` seam; `scripts/check-campaign-switcher.mjs` tests them via the `effective-role` bundle and server render (no fetch on SSR).
- `src/frontend/src/services/api.ts` -- default-export axios instance; `components/ui/role-badge.tsx` -- `CampaignRole = "gm"|"co_gm"|"player"`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/policy.py` -- `NotFound`/`not_found()` (raises), `MinRole`, role constants, `SystemReason` StrEnum, `ctx_role(CampaignRole)`, `meets(ctx, min_role)`, `display_role(ctx)`.
- `src/backend/app/access/audience.py` -- minimal `Audience` (level + user) and `ctx_audience(role, user_id)`; E0-Access.3 extends.
- `src/backend/app/access/identity.py` -- moved `bearer_scheme`, `get_current_user` (unchanged behaviour).
- `src/backend/app/access/context.py` -- frozen `CampaignContext` (+`actor`, `system_reason`, `as_system`), `_resolve`, `ctx_for`, `require_campaign`, `require_campaign_for`, `role_map`, `scoped_select_multi`.
- `src/backend/app/access/__init__.py` -- export the contract names.
- `src/backend/app/api/deps.py` -- re-export identity; deprecated wrappers.
- `src/backend/app/schemas/members.py`, `src/backend/app/api/routes/members.py`, `src/backend/app/main.py` -- `/me` route mounted under `/api/campaigns` with `gate`; CORS header.
- `src/backend/.importlinter`, `scripts/test_import_ratchet.py` -- add the access layer + planted-violation cases.
- `scripts/check_scoped_queries.py`, `scripts/test_check_scoped_queries.py`, `.github/workflows/gates.yml` -- AST check: `as_system` referenced only in `journal_service.delete_journal_entry` / `world_service.merge_entities` (definition in `app/access/context.py` exempt); E0-Access.5 adds the baseline ratchet.
- `src/backend/tests/access/test_context.py`, `src/backend/tests/test_members_me.py`, `src/backend/tests/ev4/probes/members.py` -- matrix tests and the EV-4 probe.
- `src/frontend/src/types/members.ts`, `src/frontend/src/services/api/members.ts`, `src/frontend/src/hooks/useCampaignRole.ts`, `src/frontend/src/hooks/useEffectiveRole.ts` -- `/me` client, `useCampaignRole` (key `["campaignRole", id]`), `useRoleFor` uses it with the stub as loading/error fallback; `roleFromMe` moves to `useCampaignRole.ts` and is re-exported.
- `src/frontend/scripts/check-campaign-switcher.mjs` -- assert `campaignRoleState` mapping and `useRoleFor` reading seeded `["campaignRole", id]` data.

**Acceptance Criteria:**
- Given a route `Depends(require_campaign(min))`, when the caller lacks the Role, then the body and status equal those for a random campaign id.
- Given `lint-imports` and `python scripts/check_scoped_queries.py`, when CI runs, then both pass, and a planted `ctx.as_system("merge")` in another module fails the check.
- Given the frontend, when `/me` returns `{role:"gm", display_role:"Co-GM"}`, then `useRoleFor` yields `co_gm` with `isGm=true`.

## Design Notes

`require_campaign` resolves `campaign_id` like any FastAPI param: from the path when the route template has `{campaign_id}`, else the query string (collection routes). `require_campaign_for` reads `request.path_params[id_param]`, `db.get(Model, id)`, then the row's `campaign_id`. `not_found()` raises itself, so both `not_found()` and `raise not_found()` work. Moving `get_current_user` into `app.access` is the only way the dependency can depend on the user without `app.access` importing `app.api` (layer violation); `app.api.deps` re-exports the same function object.

## Verification

**Commands:**
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: backend-tests, gates (static + database), frontend-ci, license-check green.
- `cd src/frontend && npx tsc --noEmit && npm run build && node scripts/check-campaign-switcher.mjs` -- expected: pass locally.
