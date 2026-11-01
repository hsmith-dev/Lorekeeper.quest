---
title: 'E0-Access.2: CampaignContext, require_campaign and the Role map'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'f0431584b210413cf9f9812dc7a3f04ce3705998'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred:
  - summary: >-
      /me is fetched with the X-Lorekeeper-Preview header, so once E0-Access.3 narrows preview requests the cached "real" Role under ["campaignRole", id] would read Player while previewing.
    evidence: |-
      services/api.ts interceptor adds the header to every request; PreviewContext.enter() resets queries; useRoleFor documents the real (not preview-adjusted) role. E0-Access.3 owns the preview behaviour and must decide whether /me narrows or the client omits the header.
    location: >-
      src/frontend/src/hooks/useCampaignRole.ts
    severity: medium
  - summary: >-
      404 bodies are mixed: the deprecated wrapper now says "Not found" while inline checks in campaigns.py, share.py and journal_service.py still say "Campaign not found".
    evidence: |-
      Pre-existing inline checks; E0-Access.4 (uniform 404) and E0-Access.5 (callers move to require_campaign) own them.
    location: >-
      src/backend/app/api/routes/campaigns.py:38
    severity: medium
  - summary: >-
      CI-8 does not pair each allowed as_system site with its own reason (delete_journal_entry could pass "merge").
    evidence: |-
      ALLOWED_SYSTEM_SITES is checked per function only; neither allowed function exists yet. Pair the reason when E0-Journal.3 / E0-WorldCore.9 add the calls.
    location: >-
      scripts/check_scoped_queries.py
    severity: low
  - summary: >-
      No CORS preflight test for X-Lorekeeper-Preview in allow_headers.
    evidence: |-
      Only matters for a cross-origin VITE_API_URL; default dev/prod are same-origin. Add the preflight test with the E0-Access.3 preview behaviour.
    location: >-
      src/backend/app/main.py:73
    severity: low
  - summary: >-
      The CampaignSwitcher fetches /me once per campaign in the menu; role_map could serve them all in one call.
    evidence: |-
      CampaignRoleBadge calls useRoleFor per campaign. Performance only; a bulk field on the campaigns list is a later API decision.
    location: >-
      src/frontend/src/components/shell/CampaignSwitcher.tsx:63
    severity: low
  - summary: >-
      React-query keys (including ["campaignRole", id]) are not per user and the QueryClient is not cleared on logout.
    evidence: |-
      Pre-existing for every query (e.g. ["campaigns"], ["me"]); the AC fixes the key shape. Cosmetic only (backend enforces), but a shared tab could show the previous user's badge for up to staleTime.
    location: >-
      src/frontend/src/hooks/useAuth.ts
    severity: low
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

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 38 findings — high 0, medium 9, low 19, false 10, maybe-false 0 (intent-alignment divergences a–h counted as findings)
- findings:
  - `[medium]` `[patch]` (blind) A system ctx can be built by hand (`CampaignContext(actor="system")` / `dataclasses.replace`), bypassing as_system and CI-8 — `__post_init__` now requires actor in {user, system}, system_reason iff system, system ⇒ gm + user_id; CI-8 also flags `ACTOR_SYSTEM`, `actor="system"` and non-None `system_reason=` outside app/access; tests added.
  - `[low]` `[defer]` (blind) Reason not paired with its allowed site — deferred until the two call sites exist.
  - `[low]` `[patch]` (blind) Checker allows `as_system` in any nested def or method named like an allowed site — now only inside the module-level allowed function (not in a class); planted method/nested cases added.
  - `[medium]` `[patch]` (blind) `as_system` accepts an anon or already-system ctx — now raises ValueError; tested.
  - `[false]` `[reject]` (blind) `ctx_for` raising HTTP 404 in workers — the AC says `ctx_for` "raises not_found()"; NotFound is the contract.
  - `[low]` `[reject]` (blind) Missing `campaign_id` query, or a non-UUID id on a handler that also types it as UUID, gives 422 — malformed requests that reveal nothing about existence; no denial path returns 422.
  - `[low]` `[patch]` (blind) A wrong `id_param` silently 404s — now raises RuntimeError naming the missing path parameter; tested. Handing the row on is outside the contract's shape (returns a ctx) — not done.
  - `[false]` `[reject]` (blind) An unknown stored Role breaks access — `campaign_members.role` is the PG enum `campaign_role`; no other value can be stored.
  - `[medium]` `[defer]` (blind) Mixed 404 texts across routes — pre-existing inline checks, E0-Access.4/.5.
  - `[low]` `[defer]` (blind) `/me` cache not per user / not cleared at logout — pre-existing pattern for all keys; the AC fixes the key.
  - `[medium]` `[defer]` (blind) The preview header would overwrite the cached real Role — behaviour arrives in E0-Access.3.
  - `[low]` `[defer]` (blind) One `/me` per campaign in the switcher — performance only.
  - `[low]` `[reject]` (blind) A `/me` 404 falls back to the stub — cosmetic; a campaigns-list refetch drops the campaign through the lost-access path.
  - `[false]` `[reject]` (blind) `roleFromMe` keys on the display label — tested E0-UX.7 adapter the caller asked to keep consistent; `display_role` is a closed Literal in the schema.
  - `[low]` `[reject]` (blind) EV-4 probe / test assertion gaps (401 vs 403 accepted, no role content in the probe) — `tests/test_members_me.py` pins the roles; a missing bearer is HTTPBearer's existing 403 (brownfield notes).
  - `[false]` `[reject]` (blind) `scoped_select_multi` ignores the Role — the AC defers the per-Role predicate to E0-Access.3 ("until then only membership is applied").
  - `[medium]` `[patch]` (edge) Stale identity map in a long-lived session gives a stale Role/epoch from `ctx_for` — `_resolve` uses `populate_existing`; same-session grant-change test added.
  - `[low]` `[reject]` (edge) Missing `campaign_id` query gives 422 — same as above.
  - `[low]` `[patch]` (edge) `id_param` not in the route — same fix as above.
  - `[medium]` `[patch]` (edge) Hand-built system ctx — same fix as the first row.
  - `[low]` `[reject]` (edge) Indirect `as_system` through a dynamic getattr/attrgetter — needs deliberate obfuscation; the AST check covers every direct spelling.
  - `[low]` `[patch]` (edge) Nested or method look-alike of an allowed name — same fix as above.
  - `[low]` `[reject]` (edge) `--app` directory not named `app` — the CLI default is the real path; the option exists for tests that build an `app/` dir.
  - `[low]` `[reject]` (edge) A non-UTF-8 file crashes the checker — the traceback still fails CI loudly.
  - `[medium]` `[patch]` (edge) `as_system` on an anon ctx — same fix as above.
  - `[low]` `[reject]` (edge) Stale `/me` data after a refetch error — showing the last known role is the intended cosmetic behaviour.
  - `[low]` `[defer]` (edge) Mixed 404 texts — same as above.
  - `[low]` `[defer]` (verification-gap) No CORS preflight test — deferred to E0-Access.3 (filed disposition defer).
  - `[medium]` `[patch]` (verification-gap) The CI-8 bypass through a hand-built system ctx is untested — planted cases added (filed disposition patch).
  - `[medium]` `[patch]` (verification-gap, other) `__post_init__` does not validate `actor` — fixed with the first row.
  - `[false]` `[reject]` (intent a) Existing routes not migrated to `require_campaign` — the story says E0-Access.5 removes the callers; the dependency is tested on a toy app and on the real `/me`.
  - `[low]` `[defer]` (intent b) Mixed 404 bodies on live routes — same as the deferred row above.
  - `[false]` `[reject]` (intent c) `scoped_select_multi` interim form — matches the AC carve-out.
  - `[false]` `[reject]` (intent d) The allowlisted sites don't exist yet — the AC names them; the check proves no other site.
  - `[false]` `[reject]` (intent e) The frontend `role` returns `co_gm` — needed to keep `roleFromMe` consistent; `isGm` covers both.
  - `[false]` `[reject]` (intent f) CORS header without preview — the caller asked for the CORS addition; a harmless prerequisite.
  - `[false]` `[reject]` (intent g) Player audience as `Owner(self)` — in the lattice Owner(u) ⊂ Members, so "Members plus Owner(self)" is reading down to Owner(self); E0-Access.3 owns the mapping.
  - `[low]` `[reject]` (intent h) `__init__` exports a §3.1 subset plus helpers — the other §3.1 names belong to later stories; nothing exported contradicts §3.1.

## Design Notes

`require_campaign` resolves `campaign_id` like any FastAPI param: from the path when the route template has `{campaign_id}`, else the query string (collection routes). `require_campaign_for` reads `request.path_params[id_param]`, `db.get(Model, id)`, then the row's `campaign_id`. `not_found()` raises itself, so both `not_found()` and `raise not_found()` work. Moving `get_current_user` into `app.access` is the only way the dependency can depend on the user without `app.access` importing `app.api` (layer violation); `app.api.deps` re-exports the same function object.

## Verification

**Commands:**
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: backend-tests, gates (static + database), frontend-ci, license-check green.
- `cd src/frontend && npx tsc --noEmit && npm run build && node scripts/check-campaign-switcher.mjs` -- expected: pass locally.

## Auto Run Result

Status: done

**Summary:** New `app/access/` package (`policy.py`, `context.py`, `audience.py`, `identity.py`, `__init__.py`): frozen `CampaignContext` with `as_system` (only `SystemReason {entry_deleted, merge}`), `require_campaign(player|gm|owner)`, `require_campaign_for(Model, id_param, min_role)`, `ctx_for`, `role_map`, `scoped_select_multi` (membership only until E0-Access.3), and one `not_found()` giving `404 {"detail":"Not found"}`. `GET /api/campaigns/{id}/me` plus the frontend `useCampaignRole`, wired into `useRoleFor`. Deprecated wrappers in `api/deps.py`. CI-8 `as_system` check. `app.access` joins the import-linter layers between services and schemas.

**Files changed:**
- `src/backend/app/access/*` -- the package (`identity.py` holds the moved `get_current_user` / `bearer_scheme`).
- `src/backend/app/api/deps.py` -- re-exports identity; deprecated `get_campaign_with_access` / `accessible_campaign_ids` wrappers.
- `src/backend/app/api/routes/members.py`, `src/backend/app/schemas/members.py`, `src/backend/app/main.py` -- `/me`, router mount, CORS `X-Lorekeeper-Preview`.
- `src/backend/.importlinter`, `scripts/test_import_ratchet.py` -- access layer and planted violations.
- `scripts/check_scoped_queries.py`, `scripts/test_check_scoped_queries.py`, `.github/workflows/gates.yml` -- CI-8 system-ctx check.
- `src/backend/tests/access/test_context.py`, `src/backend/tests/test_members_me.py`, `src/backend/tests/ev4/probes/members.py` -- tests and the EV-4 probe.
- `src/frontend/src/{types/members.ts,services/api/members.ts,hooks/useCampaignRole.ts,hooks/useEffectiveRole.ts}`, `src/frontend/scripts/check-campaign-switcher.mjs` -- `/me` client, hook, seam, checks.

**Review:** 38 findings. Patched entries: hand-built system ctx / `as_system` guards (medium), stale identity map (medium), checker nesting (low), miswired `id_param` (low). 6 items deferred (frontmatter). Every rejected finding and its reason is in the triage log.

**Follow-up review recommended:** true -- two medium entries were patched on a first pass. Named risk: the new `CampaignContext.__post_init__` constraints and the CI-8 keyword rule could reject a legitimate ctx a later story builds (E0-Access.3 `audience_ctx`, share ctx); only that story's CI will show it.

**Verification:** PR #42 CI was green on the first push (backend tests, gates static + database, frontend CI, licence checks). After the patches, `pytest scripts/test_check_scoped_queries.py scripts/test_import_ratchet.py` passed locally (46) and `python scripts/check_scoped_queries.py` is clean; the backend DB tests re-run in CI on the patch push.

**Needs desktop verification:** nothing specific (no Ollama, GPU or compose surface). Optional re-run on the desktop: the backend suite command from the builder brief, limited to `tests/access tests/test_members_me.py tests/ev4`.

**Residual risks:** the deprecated wrapper's 404 text is now "Not found" for its 55 callers; how preview interacts with `/me` is left to E0-Access.3.
