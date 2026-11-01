---
title: 'E0-UX.8 Nav restructure, route redirects, unified not-found and route announcements'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '2b74d89798a9d9ed3e96c125eeec0a4897d39df8'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
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
