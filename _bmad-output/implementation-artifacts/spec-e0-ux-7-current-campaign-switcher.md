---
title: 'E0-UX.7 Global current Campaign and the CampaignSwitcher'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '7336dd0386f2630aab091b8ee82f87c6cb3c3b74'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: [oversized]
deferred:
  - summary: >-
      Switcher keyboard, Esc-layer and focus behaviour have no CI coverage, only the scratchpad Playwright harness.
    evidence: |-
      check-campaign-switcher.mjs renders with renderToStaticMarkup (no effects, no events). The repo has no DOM test runner and E0-UX forbids new deps. Removing the pushLayer effect would pass CI.
    location: >-
      src/frontend/src/components/shell/CampaignSwitcher.tsx
    severity: medium
  - summary: >-
      Client-only effects are untested in CI: CampaignSelector tab-follow and ?new=1, Dashboard ?campaign= deep link and tag reset, and the provider's in-place user switch.
    evidence: |-
      Each lives in a useEffect or a render-time re-read that SSR never runs. The scratchpad harness covers ?new=1 and a fresh-mount user switch only. Needs a client-render harness (e.g. when E0-QA adds a DOM runner).
    location: >-
      src/frontend/src/components/CampaignSelector.tsx, src/frontend/src/pages/DashboardPage.tsx, src/frontend/src/hooks/useCurrentCampaign.ts
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Every page picks its own campaign (DashboardPage via `CampaignSelector`, eleven other pages via inline tab rows), so there is no app-wide current Campaign, the nav cannot show the user's Role, and E0-UX.6's "Preview as Player" has no entry point.

**Approach:** Add `hooks/useCurrentCampaign.ts` (`CurrentCampaignProvider`, `useCurrentCampaign`, `usePageCampaign`) persisting the choice per device under `lk-current-campaign:{userId}`, `hooks/useEffectiveRole.ts` (stubbed role source shaped like E0-Access.2's `useCampaignRole`, forced to `player` in preview), and `components/shell/CampaignSwitcher.tsx` in the NavBar between the grouped dropdown and the avatar. Pages with a campaign picker read and write the global current Campaign.

## Boundaries & Constraints

**Always:** Semantic/theme tokens only (`lint:tokens` clean). Lucide icons with `aria-hidden`. Menu registers with `pushLayer` so Esc closes only it and returns focus to the trigger; it never exits preview. Every storage access in try/catch, memory fallback. Roles are cosmetic; comments say the server enforces them (AD-13). Unknown role values degrade to `player` (privacy-first, D-1b). Toast via existing `toast()`; RoleBadge, `usePreview` reused as-is. 375 px: no horizontal scroll, nav controls ≥ 44px. `tsc` strict.

**Never:** Create `hooks/useCampaignRole.ts`, `services/api/members.ts` or call `GET /api/campaigns/{id}/me` (E0-Access.2 owns them; endpoint does not exist yet). Backend changes. New npm deps. Restyle Button/Card/Badge/nav dropdown beyond the 44px/375px fixes. Change page layouts or query keys beyond swapping the local `selected` state. Fill the JobTrayButton slot (E0-Jobs.10). Nav group restructure (E0-UX.8).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First load | no stored id, campaigns [A,B] | current = A, stored `A`, no toast | -- |
| Stored valid | stored `B`, list [A,B] | current = B | -- |
| Pick | switcher/page picks B | stored `B`; pages and `[domain, B]` queries follow; open preview of another campaign exits | -- |
| Reload | after pick B | current still B | storage throws: memory only, no crash |
| Lost access | stored `X`, fetched list [A,B] | current = A, stored `A`, toast "You no longer have access to that campaign. Switched to *A*." once | -- |
| Just created | pick new C before list refetch | current = C, no toast | toast only if a list fetched after the pick lacks C |
| None left | list [] | trigger "No campaign", menu shows "Create a campaign" link to `/dashboard?new=1`; storage cleared | -- |
| List loading/error | query pending or failed | stored id kept, no fallback, no toast | -- |
| Role stub | `is_owner` true / false | `gm` / `player` | -- |
| `/me` adapter | `{role:"gm",display_role:"Co-GM"}` / `{role:"gm"}` / other | `co_gm` / `gm` / `player` | unknown → `player` |
| Preview | preview active | `useEffectiveRole()` = `player`; trigger badge "Player" | -- |
| GM menu | real role gm or co_gm, not previewing | "Preview as Player" item calls `usePreview().enter(campaignId)` | absent for players |
| Per user | user u2 logs in on same device | reads `lk-current-campaign:u2` only | no user id: memory only |

</intent-contract>

## Code Map

- `src/frontend/src/hooks/useCampaigns.ts` -- `["campaigns"]` query; provider reuses the key with `enabled` only when logged in (a logged-out 401 would redirect).
- `src/frontend/src/hooks/useAuth.ts` -- `lk_user` JSON `{id, display_name}` is the userId source.
- `src/frontend/src/App.tsx` -- mount `CurrentCampaignProvider` inside `BrowserRouter`, wrapping NavBar and routes.
- `src/frontend/src/components/NavBar.tsx:240-300` -- insert switcher between menu `div` and profile `div`; menu button `py-1.5` and avatar `p-0.5` are < 44px; `gap-3` + 10rem label overflow 375 px.
- `src/frontend/src/components/ui/visibility-badge.tsx` -- menu pattern to mirror (roving focus, Home/End, Tab close, outside pointerdown, `pushLayer`).
- `src/frontend/src/components/ui/role-badge.tsx` -- `RoleBadge`, `CampaignRole` type.
- `src/frontend/src/contexts/PreviewContext.tsx` -- `usePreview()` `{active, campaignId, enter, exit}`.
- `src/frontend/src/components/ui/toast.tsx` -- `toast({text})`; text is a plain string.
- `src/frontend/src/components/CampaignSelector.tsx` -- props `selected`/`onSelect`; tab initialiser runs once.
- Pages with local `useState<Campaign | null>(null)` selection: `DashboardPage`, `CharactersPage`, `CharacterSheetsPage`, `QuestsPage`, `SessionPlansPage`, `TimelinePage`, `SourcesPage`, `RecordSessionPage`, `AnalyticsPage`, `ShorthandPage`, `SharingPage` (owner-only list). `SettingsPage`/`FeedbackPage` use optional id dropdowns, not a selector: unchanged.
- `src/frontend/scripts/check-spoiler-safety.mjs` -- esbuild + node:test + SSR harness to copy; `.github/workflows/frontend-ci.yml` -- add step.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/hooks/useCurrentCampaign.ts` -- NEW: `currentCampaignKey(userId)`, pure `resolveCurrentCampaign(...)`, storage helpers, `CurrentCampaignProvider`, `useCurrentCampaign()`, `usePageCampaign(accept?)` -- one source of truth, testable logic.
- `src/frontend/src/hooks/useEffectiveRole.ts` -- NEW: `stubRole`, `roleFromMe`, `useRoleFor(campaign)` (stub, same `{role,isOwner,isGm,isLoading}` shape as `useCampaignRole`), `useEffectiveRole(campaignId?)`.
- `src/frontend/src/components/shell/CampaignSwitcher.tsx` -- NEW: trigger (icon, truncated name, RoleBadge, 44px) + menu (`menuitemradio` per campaign with RoleBadge, Preview item, create link, empty state).
- `src/frontend/src/components/NavBar.tsx` -- mount switcher; 44px menu/avatar targets; icon-only menu label and tighter gap below `sm`.
- `src/frontend/src/App.tsx` -- mount provider.
- `src/frontend/src/components/CampaignSelector.tsx` -- `selected`/`onSelect` default to global; tab follows selection; `?new=1` opens the create form.
- The eleven pages above -- replace local selection state with `usePageCampaign()` (`SharingPage`: `usePageCampaign(c => c.is_owner)`).
- `src/frontend/scripts/check-campaign-switcher.mjs` + CI step -- matrix rows via pure functions and SSR.

**Acceptance Criteria:**
- Given a logged-in user on any page with a picker, when they pick in the switcher, then the page's picker and data follow without reload, and after reload the same campaign is current.
- Given the switcher is focused, when the user presses Enter/ArrowDown, arrows, Enter, and Esc, then the menu opens on the checked item, moves, selects, and Esc closes only the menu with focus back on the trigger.
- Given a 375 px viewport, when the nav renders with switcher and avatar, then `scrollWidth <= clientWidth` and every nav control is ≥ 44px.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 36 findings — high 0, medium 14, low 19, false 3, maybe-false 0
- findings:
  - Intent Alignment
    - `[medium]` `[defer]` CI exercises pure functions and SSR markup, while the runtime surfaces (keyboard, effects, page wiring, 375 px layout) are covered only by the scratchpad Playwright harness — the repo has no DOM runner and the story forbids new deps; deferred together with the Verification Gap rows below.
    - `[false]` `[reject]` the diff goes beyond the literal reading (11 pages, and page picks are global) — EXPERIENCE.md:32 says that existing pages' "own campaign tab row keep it, but it defaults to the current Campaign", and the dispatcher framed it as each page. One source of truth is the only reading where the switcher and the page tab rows never disagree.
    - `[low]` `[reject]` the toast drops the italics on *{name}* — `toast()` takes a plain string (toast.tsx), so italics would mean widening the shared Toast API; the copy is otherwise verbatim.
    - `[false]` `[reject]` "use useCampaignRole when it exists" is a code seam, not a runtime check — `useCampaignRole` does not exist, and `/me` 404s for non-members as well, so a runtime probe could not tell "no endpoint" from "no access". The `useRoleFor` seam plus the tested `roleFromMe` is what the AC asks for.
  - Verification Gap
    - `[medium]` `[patch]` the persist/toast effect never runs in CI — the effect body was extracted to `settleResolution`, tested with fake storage and the real toast/preview stores (persist, toast once, clear).
    - `[medium]` `[patch]` setCurrent's storage write and preview exit are never called — extracted to `applyPick` and tested (writes the key, exits another campaign's preview, keeps the same campaign's preview).
    - `[medium]` `[defer]` CampaignSelector's tab-follow and `?new=1` effects are untested — they need a client render; the harness covers `?new=1`.
    - `[medium]` `[defer]` Dashboard's `?campaign=` deep link and tag reset are untested — no page-render harness exists.
    - `[medium]` `[defer]` a user switch within one provider is only tested as a fresh mount — needs a client re-render; the stale-list gate was tightened (see the Edge Case row).
    - `[medium]` `[defer]` switcher keyboard, Esc layer and focus run only in the scratchpad harness — needs a DOM runner (no new deps allowed).
    - `[low]` `[reject]` leaving the current campaign on purpose shows "You no longer have access…" — the message is still true after leaving, and telling a leave from a removal would add new state across useLeaveCampaign and the provider.
  - Blind Hunter
    - `[medium]` `[patch]` RecordingPanel keeps its transcript/draft when the nav switches campaign, so it could save into the wrong campaign — added `key={selected.id}` (the unmount cleanup stops the mic tracks).
    - `[medium]` `[patch]` the other pages' panels carry local state across campaigns — same root cause; `key={selected.id}` on all ten panels.
    - `[medium]` `[patch]` a lost-access fallback or a none-left clear does not exit preview — `settleResolution` exits a preview whose campaign is not the new persisted id; tested.
    - `[low]` `[reject]` voluntary-leave toast — same as the Verification Gap row.
    - `[low]` `[patch]` the menu says "You don't have a campaign yet." while loading or after a failure — that text now needs `ready`; otherwise "Loading campaigns…".
    - `[low]` `[patch]` CampaignSelector's defaults are unused in production and duplicate Dashboard's handleSelect — removed handleSelect; Dashboard relies on the defaults.
    - `[medium]` `[patch]` the toast is never tested — same root cause as the first Verification Gap row; `settleResolution` tests.
    - `[low]` `[patch]` the NavBar check asserts exactly 3 buttons, which breaks when JobTrayButton lands — now `>= 3`.
    - `[low]` `[patch]` no `role="group"` around the radio items, and a separator with no campaigns — added the group (aria-label "Campaigns") and a conditional separator. The "stray space" part is false: the sr-only ", role " reads correctly.
    - `[low]` `[reject]` activeIndex is not clamped when the item count shrinks while open — needs a refetch or a preview change during an open menu; the fix adds an effect.
    - `[low]` `[reject]` no cross-tab sync — not required (the AC is "per device"); a storage listener adds complexity.
    - `[low]` `[reject]` the user id is re-read only on navigation — login and logout navigate, and the 401 handler does a full `location.href` reload; other-tab logins are rare.
    - `[low]` `[reject]` the spec page count is inconsistent — fixing it means editing this build's spec.
  - Edge Case Hunter
    - `[medium]` `[patch]` preview enter/exit `resetQueries` blanks current and unmounts the page panels — `resolveCurrentCampaign` takes `lastKnown`, kept while the list is not ready and the id matches; tested.
    - `[low]` `[patch]` the previous user's cached list is used to find the new user's stored id — the list is passed only when `dataUpdatedAt >= since`.
    - `[medium]` `[patch]` the fallback leaves preview on a lost campaign — same root cause as the Blind Hunter preview row.
    - `[low]` `[reject]` reloading with a tab-scoped preview of X while localStorage holds Y — needs two tabs to diverge; reconciling them adds logic.
    - `[low]` `[reject]` voluntary-leave toast — same as above.
    - `[low]` `[patch]` `isOwner` stays true while previewing — now false; tested.
    - `[false]` `[reject]` `useEffectiveRole(b)` is forced to player while previewing a — the AC says "returns `player` while preview is active, whatever the real Role".
    - `[low]` `[reject]` activeIndex not clamped — same as the Blind Hunter row.
    - `[low]` `[patch]` `?campaign=` plus `?new=1` can clobber each other — the deep-link effect uses the functional `setSearchParams`.
    - `[low]` `[reject]` a `?campaign=X` not in the list leaves the param in place — rare, and stripping it would break a deep link while the list is stale.
    - `[medium]` `[patch]` RecordingPanel carries state across campaigns — same root cause as the Blind Hunter key row.
    - `[low]` `[patch]` a failing setItem lets an older stored id win — memory is read first when it has the user; tested.

## Design Notes

Role degradation: `useRoleFor` is the single seam. Today it returns `stubRole(campaign)` synchronously; E0-Access.2 replaces its body with `useCampaignRole(campaignId)` mapped through `roleFromMe` (already written and tested against the `/me` contract). No speculative `/me` calls: they would 404 today, and 404 also means "not a member", so probing could not tell "no endpoint" from "no access".

Picking anywhere sets the global campaign (one source of truth), so the pages' existing tab rows "default to it" and stay in step. Toast text renders the name in plain text (toast takes a string); the asterisks in the AC denote emphasis, so the message omits them.

## Verification

**Commands:**
- `cd src/frontend && npm run build` -- expected: success
- `cd src/frontend && npm run lint:tokens && node scripts/check-ui-tokens.mjs --self-test && node scripts/check-semantic-fallback.mjs && node scripts/check-ui-primitives.mjs && node scripts/check-focus-trap.mjs && node scripts/check-spoiler-safety.mjs && node scripts/check-campaign-switcher.mjs` -- expected: all pass

**Manual checks (if no CLI):**
- Scratchpad Playwright harness, headless Chromium, mocked API: switching, reload persistence, lost-access toast, keyboard flow, preview entry, 375 px layout.

## Auto Run Result

Status: done

**Summary:** App-wide current Campaign (`useCurrentCampaign`: `CurrentCampaignProvider`, `useCurrentCampaign`, `usePageCampaign`), stored per device under `lk-current-campaign:{userId}`. It falls back to the first remaining campaign with the lost-access toast and shows "No campaign" plus a "Create a campaign" link to `/dashboard?new=1`. `useEffectiveRole` uses an `is_owner` stub with the same `{role,isOwner,isGm,isLoading}` shape as E0-Access.2's `useCampaignRole`; it is forced to `player` (and `isOwner:false`) while previewing. `CampaignSwitcher` sits in the NavBar between the grouped dropdown and the avatar (RoleBadge per campaign, "Preview as Player" for GMs, `pushLayer` Esc). Every page with a campaign picker now follows the global choice.

**Role degradation:** `useRoleFor(campaign)` is the single seam. Today it returns the stub (owner → `gm`, else `player`, D-1b). E0-Access.2 swaps its body to `useCampaignRole(id)` mapped through `roleFromMe`, which is already tested against the `/me` contract (`Co-GM` → `co_gm`, `gm` → `gm`, anything else → `player`). No `/me` call is made today: it would 404, and 404 also means "not a member".

**Files:**
- `src/frontend/src/hooks/useCurrentCampaign.ts`: global current campaign, pure resolver, `settleResolution`, `applyPick` (new)
- `src/frontend/src/hooks/useEffectiveRole.ts`: role stub, `/me` adapter, preview override (new)
- `src/frontend/src/components/shell/CampaignSwitcher.tsx`: nav menu button (new)
- `src/frontend/src/components/NavBar.tsx`: mounts the switcher; 44px wordmark, menu and avatar; icon-only menu below `sm`; reserved JobTrayButton slot comment
- `src/frontend/src/App.tsx`: mounts the provider
- `src/frontend/src/hooks/useCampaigns.ts`: optional `enabled`
- `src/frontend/src/components/CampaignSelector.tsx`: global defaults, tab follows the selection, `?new=1`
- `src/frontend/src/pages/{Dashboard,Analytics,CharacterSheets,Characters,Quests,RecordSession,SessionPlans,Sharing,Shorthand,Sources,Timeline}Page.tsx`: use `usePageCampaign`; panels keyed by campaign id
- `src/frontend/scripts/check-campaign-switcher.mjs` + `.github/workflows/frontend-ci.yml`: new check (39 tests) and CI step

**Review:** 36 findings: 20 rows patched (8 root causes), 2 deferred entries (covering 5 rows), 14 rejected (reasons in the triage log). Patched entries by verdict: medium 4 (testable persist/pick side effects, preview exit on fallback, panel keys, lastKnown during cache reset), low 4+.

**Follow-up review recommended:** true. Four medium entries were patched. Unverified risks: the provider's render-time `lastKnown` ref and its effect dependencies are covered only by the browser harness; and keying the panels means switching campaign mid-recording discards the recording (the mic stops) instead of saving it anywhere.

**Verification:** `npm run build` ok; `lint:tokens` 114/114; token self-test ok; semantic-fallback ok; ui-primitives 25/25; focus-trap ok; spoiler-safety 24/24; check-campaign-switcher 39/39. Throwaway Playwright harness (headless Chromium, mocked API, built app) 18/18: switching, reload persistence, page↔switcher sync, keyboard (Enter/arrows/Home/End/Esc/Tab), Preview as Player entry and Esc not exiting it, preview exit on switch, `?new=1`, lost-access toast once, per-user keys, throwing storage, none left, Sharing owner filter, 375 px (no horizontal scroll, every nav control 44px, menu on screen). Frontend CI on PR #25 green.

**Residual risks:** no DOM runner, so keyboard and effect behaviour have no CI regression protection (deferred). A deliberate leave also shows the lost-access toast. Two tabs can disagree after a switch until they navigate. The 375 px trigger truncates long names to a few characters.

**Needs desktop verification:** none beyond the normal UI pass. Optional: `cd src/frontend && npm run dev`, log in with two campaigns (one owned, one joined), switch from the nav, reload, then check DevTools at 375 px.
