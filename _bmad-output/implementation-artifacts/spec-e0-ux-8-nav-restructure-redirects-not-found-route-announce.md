---
title: 'E0-UX.8 Nav restructure, route redirects, unified not-found and route announcements'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '2b74d89798a9d9ed3e96c125eeec0a4897d39df8'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      RouteAnnouncer's live-region text, first-load silence and h1 focus move have no CI check; only a throwaway Playwright run covers them.
    evidence: |-
      check-routes.mjs tests the pure helpers and the title store only. The repo has no DOM test runner and the story adds none, so timing and focus need a committed browser harness.
    location: >-
      src/frontend/src/components/shell/RouteAnnouncer.tsx
    severity: medium
  - summary: >-
      LegacyRedirectRule cannot express a role-conditional redirect, which E7.1's /dashboard -> /portal (Players only) will need.
    evidence: |-
      App.tsx mounts every active redirect for everyone and drops the redirected page route. The story says E7.1 adds this redirect "through the same table", so E7.1 has to add an audience field and an element that redirects only for that audience.
    location: >-
      src/frontend/src/lib/routes.ts (LEGACY_REDIRECTS), src/frontend/src/App.tsx (AppRoutes)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Routes are hand-listed in `App.tsx` and the nav in `NavBar.tsx`, so feature epics cannot add a page with one line; the owner-approved IA (World absorbs Characters and Quests, Analytics → Stats, Record → Live Session, a Player nav set) is not in place; unknown URLs render an empty `<main>`; and route changes are silent for screen-reader users.

**Approach:** A route registry in `lib/routes.ts` (pages, nav groups, Player nav set, legacy redirect table, `isRouteRegistered`) that `App.tsx` and `NavBar.tsx` both read; one `NotFoundPage` / `<NotFound />` used for unknown paths, role-gated routes and API 404s; and a `RouteAnnouncer` that sets `document.title`, announces the title politely and moves focus to the page `h1` on every route change.

## Boundaries & Constraints

**Always:**
- Story E0-UX.8 in `_bmad-output/planning-artifacts/epics.md` is the contract; follow its ACs exactly on what is live now vs gated: `/analytics` → `/stats` and `/record` → `/live?mode=record` are live now; `/characters` → `/world?type=character` and `/quests` → `/world?type=quest` switch on only when `/world` is registered (until then those paths serve `CharactersPage` / `QuestsPage`, and the nav keeps Characters and Quests).
- `/stats` renders the existing `AnalyticsPage`; `/live` renders today's `RecordSessionPage` (E4 later swaps that one registry line).
- Redirects preserve the query string and hash (target params override same-named incoming ones) and use `replace`.
- Not-found copy is exactly "This page doesn't exist or isn't shared with you." with one home link: `/dashboard` for GMs, `/portal` for Players only when `/portal` is registered (else `/dashboard`), `/` when logged out. Missing, forbidden (role-gated) and API-404 cases render the identical component, title and announcement.
- Document title format `"{title} · Lorekeeper"`; after every title write, re-apply any existing `(n) ` badge via `setTitleBadge(n)` from `components/ui/toast.tsx`.
- Announcement text `"{title}"` or `"{title}, {detail}"` in an `aria-live="polite"` region; focus to the page's first `main h1` (given `tabIndex=-1`), falling back to `<main>`.
- Semantic tokens only (`npm run lint:tokens` passes); existing primitives (Button, PageHeader look, nav dropdown look) are not restyled; no new npm dependency.
- Roles are cosmetic: route gating and nav sets only hide UI; the server stays the control.

**Never:**
- Do not register `/world`, `/portal`, `/portal/journal` or `/keepsakes` (other epics do).
- Do not add `/dashboard` → `/portal` (E7.1 does, through the same table).
- Do not resolve NPC/Quest detail legacy links (E0-WorldCore).
- Do not edit `sprint-status.yaml`, `epics.md`, or `desktop-verification-queue.md`; do not commit `epic-*-context.md` changes.
- No frontend test runner; checks are node scripts like the existing `scripts/check-*.mjs`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Analytics redirect | `/analytics?range=30#top` | lands on `/stats?range=30#top` (replace), renders `AnalyticsPage`, title "Stats · Lorekeeper" | — |
| Record redirect | `/record?x=1` | `/live?x=1&mode=record` (mode set), renders `RecordSessionPage`, title "Live Session · Lorekeeper" | — |
| Target overrides param | `/record?mode=foo` | `/live?mode=record` | — |
| World not registered | `/characters`, `/quests` | serve `CharactersPage` / `QuestsPage`; no redirect | — |
| World registered (fixture) | `/characters?q=a` | `redirectTarget` gives `/world?q=a&type=character`; nav Campaign group = World, Character Sheets, Session Plans, Sources, Shorthand | — |
| GM nav, no World/Keepsakes | GM | Chronicle: Journal, History, Timeline, Live Session, Stats; Campaign: Characters, Character Sheets, Quests, Session Plans, Sources, Shorthand; Collaborate: Sharing, Feedback; Admin only if `is_admin` | — |
| Keepsakes registered (fixture) | GM | Keepsakes appears between Live Session and Stats | — |
| Player nav | effective role player (incl. GM previewing) | only registered among Portal, World, My Journal, Chronicler (`/chat`), Recaps (`/keepsakes`) — today just Chronicler; no Admin even for admins | — |
| No current campaign | campaigns loading or none | GM nav set and no route gating (no role in any campaign yet) | — |
| Unknown path | `/nope` (logged in or out) | `NotFoundPage`, title "Page not found · Lorekeeper" | — |
| Player opens GM route | player, `/sources` | same `NotFound` render and title as `/nope`; page chunk not loaded | — |
| API 404 | `/journal/missing-id`, GET 404 | `<NotFound />` | non-404 errors show `InlineError` with Retry |
| Title badge | `document.title = "(3) History · Lorekeeper"`, navigate to Stats | `"(3) Stats · Lorekeeper"` | — |
| Count detail | `usePageTitle("World", "214 entities")` | announce "World, 214 entities"; document title "World · Lorekeeper" | — |
| First load | initial render | document title set; no announcement, no focus move | — |

</intent-contract>

## Code Map

- `src/frontend/src/App.tsx` -- hand-written `<Routes>` (lines ~92-118), `PrivateRoute` (lazy `localStorage lk_token` check), lazy-page adapter comment (core loop Home/Login/Register/Forgot/Reset/Dashboard/History stays eager; everything else lazy). No catch-all route today. Provider order: ThemeProvider > QueryClientProvider > BrowserRouter > CurrentCampaignProvider > TourProvider; `<main className="flex-1 flex flex-col">`.
- `src/frontend/src/components/NavBar.tsx` -- local `NAV_GROUPS` (lines 13-42) and admin group (208-211); `current` lookup via `startsWith`; the dropdown is a disclosure of `<Link>`s with no `aria-expanded`/Esc. Must keep: menu button `aria-label="Menu…"` *before* the switcher's `aria-haspopup="menu"` (so do not add `aria-haspopup` to the nav button), `min-h-11` on every button and closed-state link, `gap-2 sm:gap-3`, `<span class="hidden sm:inline max-w-[10rem] truncate">` -- all asserted by `scripts/check-campaign-switcher.mjs:490-508`.
- `src/frontend/src/components/shell/CampaignSwitcher.tsx` -- menu-button pattern to mirror for keyboard (pushLayer Esc, outside pointerdown, blur-close, focus return).
- `src/frontend/src/lib/layers.ts` -- `pushLayer(onEscape)` returns remover.
- `src/frontend/src/hooks/useEffectiveRole.ts` -- `useEffectiveRole()` → `{role, isGm, previewing, …}` (`role ∈ gm|co_gm|player`, forced `player` in preview); `isGmRole`.
- `src/frontend/src/hooks/useCurrentCampaign.ts` -- `useCurrentCampaign()` → `{current, campaigns, ready}`; throws outside the provider.
- `src/frontend/src/components/ui/toast.tsx:151-160` -- `setTitleBadge(n)` strips/re-adds `/^\(\d+\) /`.
- `src/frontend/src/components/PageHeader.tsx` -- renders the page `h1` (26 pages use it or an `h1`); `EntryDetailPage` has no `h1` (fallback to `main`).
- `src/frontend/src/pages/EntryDetailPage.tsx:42-115` -- `useQuery(["journal", id])`, renders "Entry not found." when `!entry`; switch to `<NotFound />` on 404.
- `src/frontend/src/components/ui/inline-error.tsx` -- `InlineError({error, onRetry})`.
- `src/frontend/src/components/ui/button.tsx` -- `Button` (`asChild` via radix Slot) for the not-found home link.
- `src/frontend/src/pages/AnalyticsPage.tsx:132` -- `PageHeader` title "Analytics" → rename to "Stats" (owner-approved rename; nothing else changes).
- `src/frontend/scripts/check-campaign-switcher.mjs` -- esbuild+node:test+SSR harness to copy (`renderShell`, FakeStorage, externals, `define`). It bundles `NavBar.tsx`; once NavBar imports `lib/routes.ts` the bundle pulls pages, so add `"import.meta.env.DEV": "false"` to its `define` if needed (SlideOver reads it).
- `.github/workflows/frontend-ci.yml` -- append a step for the new check script.
- `src/frontend/src/index.css` -- global CSS (epic-owned) for the focused-heading outline rule.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/lib/routes.ts` -- NEW. Exports: `PageRoute { path; title; page: ComponentType; navGroup?: NavGroupLabel; navLabel?; roles: readonly NavAudience[]; auth?: "public" | "private" }` (`NavAudience = "gm" | "player"`, `auth` default private); `PAGE_ROUTES` (one line per page, every route App has today, with `/stats` → AnalyticsPage "Stats", `/live` → RecordSessionPage "Live Session"; GM-only `roles: ["gm"]` for `/live`, `/session-plans`, `/sources`, `/shorthand`; everything else `["gm","player"]`); `lazyPage(load, exportName)` adapter; `isRouteRegistered(path, routes = PAGE_ROUTES)` (strips query/hash, `matchPath` against each `path`); `findRoute(pathname, routes?)`; `NAV_GROUPS` (ordered path lists per GM group: Chronicle `/dashboard,/history,/timeline,/live,/keepsakes,/stats`; Campaign `/world,/characters,/character-sheets,/quests,/session-plans,/sources,/shorthand`; Collaborate `/sharing,/feedback`; Admin `/admin` admins only) with explicit labels (Journal, History, Timeline, Live Session, Keepsakes, Stats, World, Characters, Character Sheets, Quests, Session Plans, Sources, Shorthand, Sharing, Feedback, Admin); `PLAYER_NAV` (Portal `/portal`, World `/world`, My Journal `/portal/journal`, Chronicler `/chat`, Recaps `/keepsakes`); `LEGACY_REDIRECTS` (`{from, to, whenRegistered?}`: `/analytics→/stats`, `/record→/live?mode=record`, `/characters→/world?type=character` and `/quests→/world?type=quest` with `whenRegistered: "/world"`); pure helpers `gmNavGroups({isAdmin}, routes?)` (drops unregistered links; drops Characters and Quests when `/world` is registered), `playerNav(routes?)`, `navAudience({hasCampaign, isGm})` (player only when a current campaign exists and the effective role is not GM), `activeRedirects(routes?)`, `redirectTarget(to, search, hash)`, `canView(route, audience)`, `formatDocumentTitle(title)`. -- one shared append point for every epic.
- `src/frontend/src/components/shell/RouteAnnouncer.tsx` -- NEW. A tiny external title store (`setRouteTitle`, override stack) + `usePageTitle(title, detail?)` hook (page overrides beat the route default regardless of effect order); `announcementText(title, detail?)`; `applyDocumentTitle(title)` (writes `formatDocumentTitle`, then `setTitleBadge` with the badge count read from the old title); `RouteAnnouncer` component: visually hidden `role="status" aria-live="polite" aria-atomic="true"` region always mounted; on each `location.key` change after the first render, once the title settles (~150 ms debounce) set the region text (clear first so repeats re-announce) and move focus to the first `main h1` (`tabIndex=-1` if absent, `preventScroll`), else `main`; skip the focus move when focus is already on an element inside `main` that is not the body. Document title always tracks the effective title.
- `src/frontend/src/components/shell/RouteGate.tsx` -- NEW. `RoutePage({route})`: sets the route's default title, renders `<NotFound />` without loading the page when `!canView(route, audience)`, wraps private routes in the existing login check; `LegacyRedirect({to})`: `<Navigate replace>` to `redirectTarget(to, location.search, location.hash)`.
- `src/frontend/src/pages/NotFoundPage.tsx` -- NEW. `NotFound` (copy above, `h1` "Page not found", `usePageTitle("Page not found")`, home link per role/login) and `NotFoundPage` (same, for the `*` route); uses tokens only and an EmptyState-like centred layout. It always renders under `CurrentCampaignProvider` (also for logged-out users, where the campaign list is disabled).
- `src/frontend/src/App.tsx` -- build `<Routes>` from `activeRedirects()` (first) and `PAGE_ROUTES` (skipping paths an active redirect owns) plus `<Route path="*" element={<NotFoundPage />} />`; mount `<RouteAnnouncer />` inside the router; give `<main>` `id="main" tabIndex={-1}` with no visible outline; remove the hand-written page imports/routes.
- `src/frontend/src/components/NavBar.tsx` -- read groups from `gmNavGroups` / `playerNav` by `navAudience` (`useEffectiveRole` + `useCurrentCampaign`); Admin only in the GM set; disclosure keyboard support: `aria-expanded`, `aria-controls`, `nav aria-label="Main"`, Esc (via `pushLayer`) closes and returns focus to the button, ArrowDown/ArrowUp/Home/End move between links, Tab out or focus leaving closes; visible focus ring on links (`focus-visible:` classes only, no look change otherwise).
- `src/frontend/src/pages/EntryDetailPage.tsx` -- 404 (or no entry after load) → `<NotFound />`; other errors → `InlineError` with Retry; `usePageTitle` not needed (route default "Journal entry").
- `src/frontend/src/pages/AnalyticsPage.tsx` -- PageHeader title "Stats".
- `src/frontend/src/index.css` -- `h1[tabindex="-1"]:focus, main[tabindex="-1"]:focus { outline: none; }`.
- `src/frontend/scripts/check-routes.mjs` -- NEW (same harness as `check-campaign-switcher.mjs`). Covers every matrix row that is pure or SSR-renderable: registry shape (unique paths, every page route has a title and roles), `isRouteRegistered` (`/world` false today, `/stats` true, query stripped, `/journal/x` true), GM/Player nav with real registry and with fixtures adding `/world`, `/keepsakes`, `/portal`; admin; `navAudience`; `activeRedirects` today vs with `/world`; `redirectTarget` (query/hash preserved, target overrides); `canView`; title format + badge preservation; `announcementText`; title store precedence (override beats default, pop restores); SSR of `NotFound` for GM, Player (portal fixture absent → `/dashboard`) and logged out (`/`), with exact copy; SSR of `NavBar` for an owned (GM) and a shared (Player) current campaign; SSR `RoutePage` for a Player on a GM-only route renders the not-found copy.
- `.github/workflows/frontend-ci.yml` -- add step `node scripts/check-routes.mjs`.

**Acceptance Criteria:**
- Given the built app with a mocked API, when a user opens `/analytics`, `/record`, `/characters`, `/quests` and `/nope`, then they land on `/stats` (AnalyticsPage), `/live?mode=record` (RecordSessionPage), Characters, Quests and the not-found page respectively, and Back from `/stats` does not return to `/analytics`.
- Given any in-app navigation, when the new page mounts, then the polite live region contains the page title, `document.title` is `"{title} · Lorekeeper"` (badge kept), and focus is on the page `h1`.
- Given a GM, when they open the nav with the keyboard (Enter, arrows, Esc), then the groups match the matrix, arrows move between links, Esc closes and focus returns to the menu button; given a Player, the dropdown shows only Chronicler.
- Given a 375 px viewport, when the nav and the not-found page render, then there is no horizontal scroll.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 35 findings — high 0, medium 13, low 16, false 6, maybe-false 0
- findings:
  - Blind Hunter
    - `[medium]` `[patch]` A query-only or hash-only change re-announces the page and moves focus to the h1. Fixed: the announcer keys on pathname, using a last-settled-pathname ref.
    - `[false]` `[reject]` Players now see only Chronicler. The AC says the dropdown shows only Portal, World, My Journal, Chronicler and Recaps, each only when registered.
    - `[false]` `[reject]` A 403 on an entry shows an error. `app/api/routes/journals.py:153,165` returns 404 for both missing and unshared entries.
    - `[low]` `[reject]` /live ignores `mode`, and RecordSessionPage's heading wasn't renamed. The AC says /live renders today's RecordSessionPage, and E4 adds the mode branch.
    - `[false]` `[reject]` No skip link targets `main#main`. `tabIndex=-1` is the announcer's focus fallback, not a skip-link target, and a skip link is not in this story.
    - `[medium]` `[patch]` On pages with their own loading state, the route default is announced and focus lands on main; an API 404's not-found title is never announced. Fixed: EntryDetailPage's skeleton has `data-route-loading` so the announcer waits for it.
    - `[low]` `[reject]` The previous title stays while a GM-only route waits for campaigns. The wait is brief, and a neutral title adds a state branch.
    - `[low]` `[patch]` Menu inconsistencies. Fixed: link highlight now uses the same longest match as aria-current. Not fixed: null relatedTarget on blur (mirrors CampaignSwitcher; pointerdown covers clicks) and the profile dropdown's mousedown (pre-existing).
    - `[medium]` `[patch]` Tests skip the App route table, LegacyRedirect, the EntryDetailPage split and the announcer. Grouped with the Verification Gap rows below.
    - `[false]` `[reject]` navGroup only feeds the GM nav. The Player set is a fixed five-link list in the story, so it is listed, not appended.
    - `[low]` `[patch]` The interface and the component are both named LegacyRedirect. Fixed: the interface is renamed `LegacyRedirectRule`.
    - `[low]` `[reject]` The outer Suspense is redundant. It is a harmless safety net for any non-RoutePage element that suspends.
  - Verification Gap
    - `[medium]` `[patch]` App route wiring and LegacyRedirect are never rendered. Fixed: `AppRoutes` is exported and check-routes covers redirect order, the last `*` route, the /analytics replace redirect keeping query and hash, /characters served, and /nope not found.
    - `[medium]` `[patch]` The EntryDetailPage 404-vs-error split and its retry rule are untested. Fixed: SSR cases for 404, 422 and 500, plus `retryEntry` and `isNotFoundError` asserted directly.
    - `[medium]` `[defer]` Announcer timing and focus have only the manual harness. A DOM runner is out of scope, so this is deferred (see frontmatter).
    - `[medium]` `[patch]` An API 404 is announced as "Journal entry" and the not-found h1 is never focused. Same root cause as the Blind Hunter loading-state row.
  - Intent Alignment
    - `[medium]` `[patch]` R2 surfaces (redirect navigation, the open dropdown, announcements) are tested only at the pure/SSR level. Same entries as the Verification Gap rows: wiring is now tested, announcer behaviour is deferred.
    - `[medium]` `[patch]` A gated route showed "Loading…" while an unknown path rendered not-found immediately, which is a timing hint. Fixed: a shared `useRoleSettling` hold applies to both GM-only routes and the `*` route; check-routes asserts identical markup during the wait.
    - `[medium]` `[defer]` The redirect table cannot express E7.1's Player-only /dashboard → /portal. The story assigns that redirect to E7.1, so it is deferred with the shape it needs.
    - `[false]` `[reject]` /live is already registered. The AC requires /live to render RecordSessionPage now, and E4 changes that one line.
    - `[low]` `[reject]` Only EntryDetailPage was converted to `<NotFound />`. It is the only authenticated single-record page; the share and join token pages are public and have their own flows.
    - `[low]` `[reject]` /admin is open to Players. Admin is a platform role, not a campaign role, and AdminPage self-guards. The nav hides it from the Player set as the AC requires.
    - `[low]` `[reject]` AnalyticsPage's heading was renamed to "Stats". This applies the owner-approved rename so the h1 matches the route title and announcement; nothing else on the page changed.
  - Edge Case Hunter
    - `[low]` `[patch]` A previous user's cached list leaves `current` null, so the audience is gm and a GM-only chunk loads. Fixed: the hold now uses `!ready` from useCurrentCampaign (via `useRoleSettling`).
    - `[medium]` `[patch]` Query-only change re-announces. Same as the Blind Hunter row.
    - `[medium]` `[patch]` An in-page loading state is announced too early. Same as the Blind Hunter row.
    - `[low]` `[reject]` A navigation within 150 ms of first load is not announced. A human click that fast is unlikely.
    - `[low]` `[reject]` /journal/a → /journal/b from a link in main keeps focus on the old link. No page links entry to entry today.
    - `[low]` `[patch]` A malformed id returns 422 and shows an error box. Fixed: 422 is treated as not-found and not retried.
    - `[low]` `[patch]` A failed background refetch replaces a loaded entry. Fixed: InlineError shows only when there is no entry.
    - `[low]` `[reject]` The Player nav is filtered by registration, not roles. Every registered Player link today is open to both roles; the epics registering /world, /portal and /keepsakes set their roles.
    - `[low]` `[reject]` Re-serialising through URLSearchParams changes the encoding. No reader depends on exact encoding, and parsed values are preserved.
    - `[false]` `[reject]` Blur with a null relatedTarget leaves the menu open. Clicks outside are handled by pointerdown, and focus leaving the window does not need to close it (same pattern as CampaignSwitcher).
    - `[medium]` `[patch]` Claim: focus is on the h1 after navigation. Same root cause as the loading-state row; pages without their own loading state focus the h1 (Playwright verified).
    - `[low]` `[patch]` Claim: the gated page never loads. Same root cause as the stale-list row.

## Design Notes

- **Nav audience with no campaign.** `useEffectiveRole()` stubs `player` when there is no current campaign. A brand-new user (or campaigns still loading) has no Role anywhere, so treating that as Player would hide almost the whole app and flicker on every load. `navAudience` therefore returns `player` only when a current campaign exists and the effective role is not GM; the same audience drives route gating.
- **Route roles vs nav.** The Player *nav* set is the story's five links. Route *gating* (`roles`) only blocks the GM-only pages EXPERIENCE.md names for the Player shell (Sources, Shorthand, Session Plans, Live Session); other pages stay reachable by URL so existing members do not lose pages that work for them today. Admin stays visible only in the GM set; `AdminPage` self-guards.
- **Title precedence.** React runs child effects before parent effects, so the route default (set by `RoutePage`) and page overrides (`usePageTitle`, incl. `NotFound`) live in separate slots: `effective = topOverride ?? routeDefault`. A gated route never sets its default to its own title before rendering `NotFound` (same title as a missing page).
- **Redirect merge example:** `redirectTarget("/live?mode=record", "?mode=foo&x=1", "#h")` → `"/live?mode=record&x=1#h"` (incoming params kept, target params override; parameter order is not significant).

## Verification

**Commands:**
- `cd src/frontend && npm run build` -- expected: success (tsc strict + vite)
- `cd src/frontend && npm run lint:tokens && node scripts/check-ui-tokens.mjs --self-test && node scripts/check-semantic-fallback.mjs && node scripts/check-ui-primitives.mjs && node scripts/check-focus-trap.mjs && node scripts/check-spoiler-safety.mjs && node scripts/check-campaign-switcher.mjs && node scripts/check-routes.mjs` -- expected: all pass

**Manual checks (if no CLI):**
- Throwaway Playwright run (scratchpad, headless Chromium against `vite preview` with routed API mocks): each redirect incl. query and Back, not-found for unknown path and for a Player on `/sources`, live region text + `document.title` + focused `h1` after a nav click, keyboard through the nav menu, 375 px no horizontal scroll.

## Auto Run Result

Status: done

**Summary:** Route registry in `lib/routes.ts`: pages `{path, title, page, navGroup?, roles, auth?}`, `NAV_GROUPS`, `PLAYER_NAV`, `LEGACY_REDIRECTS`, `isRouteRegistered` and pure helpers. `App.tsx` builds its routes from it through `AppRoutes`, with redirects first and a `*` not-found route last.
- **Redirects:** `/analytics` → `/stats` (AnalyticsPage) and `/record` → `/live?mode=record` (RecordSessionPage) are live, using replace and keeping the query and hash. `/characters` and `/quests` → `/world?type=…` wait for `/world` to be registered; until then they serve their pages and the nav keeps Characters and Quests.
- **Nav:** the GM groups and the Player set come from the registry; today a Player sees only Chronicler. The menu is a keyboard disclosure: arrows, Home/End, Esc returns focus, `aria-expanded`/`aria-controls`.
- **Not found:** one `NotFound` is used for unknown paths, GM-only routes (Live Session, Session Plans, Sources, Shorthand) opened by a Player, and journal-entry 404/422. Copy, title and wait are the same in every case.
- **Announcer:** `RouteAnnouncer` sets "{title} · Lorekeeper" (the `(n)` badge is re-applied via `setTitleBadge`), announces politely on a path change, and focuses the page h1. `usePageTitle(title, detail)` gives "World, 214 entities".

**Files:**
- `src/frontend/src/lib/routes.ts`: registry, nav sets, redirect table, helpers (new)
- `src/frontend/src/components/shell/RouteAnnouncer.tsx`: title store, `usePageTitle`, announcer (new)
- `src/frontend/src/components/shell/RouteGate.tsx`: `RoutePage` (login, role gate, title, hold) and `LegacyRedirect` (new)
- `src/frontend/src/components/shell/RouteLoading.tsx`: route loading fallback with `data-route-loading` (new)
- `src/frontend/src/hooks/useNavAudience.ts`: `useNavAudience`, `useRoleSettling`, `isLoggedIn` (new)
- `src/frontend/src/pages/NotFoundPage.tsx`: `NotFound`, `NotFoundPage`, `notFoundHome` (new)
- `src/frontend/src/App.tsx`: `AppRoutes` from the registry; announcer mounted; `main#main` focus fallback
- `src/frontend/src/components/NavBar.tsx`: registry-driven menu, keyboard disclosure; mobile panel anchored to the gutter
- `src/frontend/src/pages/EntryDetailPage.tsx`: 404/422 → `NotFound`; other errors → InlineError with Retry
- `src/frontend/src/pages/AnalyticsPage.tsx`: heading "Stats"
- `src/frontend/src/index.css`: no outline on the focused route h1/main
- `src/frontend/scripts/check-routes.mjs` and `.github/workflows/frontend-ci.yml`: new check (45 tests) and CI step

**Review:** 35 findings. 20 rows patched, grouped into 11 entries. 2 deferred: announcer behaviour has no CI DOM check, and the redirect table has no role-conditional rule for E7.1. 13 rejected; reasons are in the triage log. Patched entries by verdict: medium 5 (query-only re-announce, in-page loading announce/focus, route-wiring tests, EntryDetail tests, gated-vs-missing timing), low 6.

**Follow-up review recommended:** true. Five medium entries were patched. Unverified risks:
- The pathname-keyed announcer and the `useRoleSettling` hold are checked only by SSR and the throwaway browser harness.
- The `*` route now waits for the campaign list when logged in, so if `/api/campaigns` hangs, an unknown URL shows "Loading…" until the request settles.

**Verification:**
- `npm run build` ok.
- `lint:tokens` 114/114; token self-test ok; semantic-fallback ok; ui-primitives 25/25; focus-trap ok; spoiler-safety 24/24; check-campaign-switcher 39/39; check-routes 45/45.
- Throwaway Playwright harness against `vite preview` with a mocked API (headless Chromium), 42/42 after the patches. It covered:
  - `/analytics?range=30#top` → `/stats?range=30#top`, and Back skips it.
  - `/record?x=1` → `/live?x=1&mode=record`, and the target overrides `mode`.
  - `/characters` and `/quests` are served.
  - `/nope` and journal 404 show not-found with the same title.
  - A Player on `/sources` gets markup and title identical to `/nope`.
  - After a nav click: the live region says "Stats", the title is "(3) Stats · Lorekeeper", and the h1 is focused.
  - Keyboard: Enter, arrows, Home/End, Esc returns focus, and Enter on a link navigates and announces.
  - GM groups match the spec; Admin shows only for admins; the Player menu shows only Chronicler.
  - 375 px: no horizontal scroll, with the menu open as well.
- Frontend CI on PR #31.

**Residual risks:**
- Announcer timing and focus have no CI regression protection; there is no DOM runner.
- Pages with their own loading state, other than the journal entry page, focus `main` rather than their late-rendered h1.
- A Player sees only Chronicler until Portal, World and Keepsakes land. Journal and History remain reachable by URL and from the wordmark.

**Needs desktop verification:** none beyond the normal UI pass. Optional: `cd src/frontend && npm run dev`, then with one owned and one joined campaign try `/analytics`, `/record?x=1` and `/nope`. Switch to the joined campaign and open `/sources`. Use VoiceOver to confirm the route announcement.
