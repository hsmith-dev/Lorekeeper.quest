---
title: 'E0-UX.7 Global current Campaign and the CampaignSwitcher'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '7336dd0386f2630aab091b8ee82f87c6cb3c3b74'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: [oversized]
deferred: []
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

## Design Notes

Role degradation: `useRoleFor` is the single seam. Today it returns `stubRole(campaign)` synchronously; E0-Access.2 replaces its body with `useCampaignRole(campaignId)` mapped through `roleFromMe` (already written and tested against the `/me` contract). No speculative `/me` calls: they would 404 today, and 404 also means "not a member", so probing could not tell "no endpoint" from "no access".

Picking anywhere sets the global campaign (one source of truth), so the pages' existing tab rows "default to it" and stay in step. Toast text renders the name in plain text (toast takes a string); the asterisks in the AC denote emphasis, so the message omits them.

## Verification

**Commands:**
- `cd src/frontend && npm run build` -- expected: success
- `cd src/frontend && npm run lint:tokens && node scripts/check-ui-tokens.mjs --self-test && node scripts/check-semantic-fallback.mjs && node scripts/check-ui-primitives.mjs && node scripts/check-focus-trap.mjs && node scripts/check-spoiler-safety.mjs && node scripts/check-campaign-switcher.mjs` -- expected: all pass

**Manual checks (if no CLI):**
- Scratchpad Playwright harness, headless Chromium, mocked API: switching, reload persistence, lost-access toast, keyboard flow, preview entry, 375 px layout.
