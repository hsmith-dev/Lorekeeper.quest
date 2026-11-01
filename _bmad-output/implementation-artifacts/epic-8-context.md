# Epic 8 Context: A consistent, accessible app shell for the expansion

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->
<!-- Epic 8 is the numeric alias of epic "E0-UX" in epics.md; stories 8.1–8.9 = E0-UX.1–E0-UX.9. -->

## Goal

Give every user (GM or Player) an app shell that looks like it was always this way and works fully by keyboard and screen reader, so the ten expansion features can build on it. The epic adds six semantic colour tokens and table-reading type roles to all six built-in themes, fixes the known contrast and hardcoded-colour defects (gated in CI), makes SlideOver trap and return focus, adds global reduced-motion handling, ships the shared primitives (SegmentedControl, Tabs, Combobox, Toast, EmptyState, ModelMissingNotice, spoiler-safety badges, Preview shell), and makes the shell aware of the current Campaign and the user's Role in it, with a restructured nav, redirects, one not-found page and route announcements. It is Phase 0, Wave 0, owns no tables, and lands before feature epics edit the same files.

## Stories

- Story 8.1: Semantic colour tokens and type roles in all six themes
- Story 8.2: Fix destructive-text contrast, migrate hardcoded colours, and gate them in CI
- Story 8.3: SlideOver focus trap, wide and full-screen variants, push header, and reduced motion
- Story 8.4: SegmentedControl, Tabs and Combobox primitives
- Story 8.5: Toast, EmptyState, ModelMissingNotice and shared state patterns
- Story 8.6: Spoiler-safety components and the Preview shell
- Story 8.7: Global current Campaign and the CampaignSwitcher
- Story 8.8: Nav restructure, route redirects, unified not-found and route announcements
- Story 8.9: Shortcut registry, help overlay and touch-target audit

## Requirements & Constraints

- WCAG 2.2 AA on every new surface; works at 375 px with no horizontal scroll; uses only the six themes' tokens. The six built-in themes are the contract (no seventh theme).
- **Colour never carries meaning alone.** Every semantic colour comes with an icon and a word (lock + "GM only", skull + "Deceased", dot + "REC").
- Contrast rule for the new tokens: each is text/icon-safe, **≥ 4.5:1 against that theme's `card`, its `background`, and its own 14% wash composited over `card`**. Wash compositing is `0.14·token + 0.86·card` in sRGB; ratio uses the WCAG relative-luminance formula.
- Dark-theme `destructive` (lightness 30–35%) fails AA as text. Readable error text/icons use `text-danger`; `destructive` survives only as a fill (`bg-destructive`, `bg-destructive/10`, `border-destructive`) or `text-destructive-foreground` on a destructive fill.
- Other inherited contrast notes: Arcane `primary` on `card` is 3.84:1 (fills and large text only; new small primary-coloured text in Arcane uses `foreground`). Light `muted-foreground` on white is 4.75:1 (don't use it under 12px).
- Hardcoded `green-*`/`amber-*`/`red-*` classes and hex/`rgb(` colour literals are debt; the migration is in scope (overrides DESIGN's "optional" note). Mapping: green → `success`, amber → `warning`, red text/icons → `danger`, red fills → `destructive`; washes `/14`, borders `/40`.
- CI-15: `scripts/check-ui-tokens.mjs` (grep mode) fails on `(text|bg|border|ring|fill|stroke|from|to|via)-(green|amber|red)-\d+`, hex or `rgb(` in `className`/`style` colour properties, and `text-destructive` not followed by `-foreground`; empty allowlist. `--contrast` mode parses HSL triplets from `themes/*.ts` and exits non-zero naming theme, token and ratio. `npm run lint:tokens` runs both, on every PR and on `main`, no path filter (wired into E0-QA's frontend job).
- Touch targets ≥ 44px (56px in Live Session/Table view, enforced by E4); no hover-only affordances below `md`.
- Reduced motion (`prefers-reduced-motion: reduce`): SlideOver and sheets don't slide, skeletons don't pulse, REC dot and Job ring static, no foil shimmer, captions jump-scroll, graph never animates layout/zoom. None exists today; it is new global CSS plus a `useReducedMotion()` hook.
- No new npm dependency for any of these primitives (focus trap, Toast, Combobox etc. are in-house; only the existing `@radix-ui/react-slot`). Avoids licence-register work.
- `tsc` strict build is the frontend gate; there is no frontend test runner.

## Technical Decisions

### Semantic colour tokens (new `ThemeColors` keys, HSL triplets without `hsl()`)

| Theme | success | warning | info | gm | live | danger |
|---|---|---|---|---|---|---|
| dnd (default) | `130 40% 55%` (#5EBA6E) | `32 85% 58%` (#EF9A39) | `205 55% 65%` (#75AED7) | `285 45% 70%` (#C490D5) | `4 80% 68%` (#EF756C) | `0 75% 72%` (#ED8282) |
| arcane | `150 45% 55%` (#59C08C) | `38 85% 60%` (#F0B042) | `195 60% 62%` (#64BBD8) | `320 55% 72%` (#DF90C5) | `350 80% 70%` (#F0758A) | `0 75% 72%` (#ED8282) |
| highseas | `145 40% 55%` (#5EBA85) | `30 85% 60%` (#F09942) | `190 55% 62%` (#69C2D3) | `280 45% 72%` (#C297D8) | `4 80% 68%` (#EF756C) | `0 75% 72%` (#ED8282) |
| forest | `100 45% 55%` (#7BC059) | `38 85% 58%` (#EFAC39) | `200 50% 65%` (#79B5D2) | `290 40% 72%` (#CB9BD4) | `8 80% 68%` (#EF7E6C) | `0 75% 72%` (#ED8282) |
| cyberpunk | `120 90% 55%` (#25F425) | `50 100% 55%` (#FFD91A) | `200 100% 65%` (#4DC3FF) | `270 100% 75%` (#BF80FF) | `340 100% 68%` (#FF5C92) | `0 100% 72%` (#FF7070) |
| light | `142 70% 26%` (#147136) | `28 90% 32%` (#9B4D08) | `205 80% 34%` (#11629C) | `275 55% 40%` (#6F2E9E) | `0 72% 42%` (#B81E1E) | `0 72% 42%` (#B81E1E) |

Reference dnd inherited values (for contrast only; theme files remain source of truth): background #120F0D, card #1D1916, foreground #EBE5D6, primary #D3A122, muted-foreground #A99D7E. Foil gradient (Achievements/Milestones only): #B98526 → #F3D488 → #C18B2A.

Token meanings: **success** = approved, captions keeping up, finished Job, alive (never decoration). **warning** = "look before you trust this" (Continuity Flags, needs-attention items, backlog, "Not from this NPC's memories", missing status, model-missing notice), not "error". **info** = Private visibility and the View-as-Player banner ("someone else's eyes"). **gm** = players cannot see this (GM-only visibility, Secret fields, GM-only pins/nodes); each theme's gm hue sits clear of its `primary`. **live** = only the recording indicator/REC state, never errors. **danger** = readable destructive text and icons (failed Jobs, error lines, delete confirmations).

### Opacity / wash steps

- Wash (fill) = token @ **14%**; border = token @ **40%** (continuity-flag border @ **45%**).
- SecretField: gm @ **6%** wash, **dashed** gm border @ **50%**.
- Rejected proposal opacity **0.55**. Inherited primary steps used by components: primary @ 5% (review shell bg), 6% (canon note), 14% (active recap sentence), 30% / 40% borders.
- Tailwind exposes each token as `hsl(var(--x) / <alpha-value>)` (`text-success`, `bg-gm/14`, `border-warning/40`, `bg-gm/6`), and the opacity scale is extended with **6, 14, 45, 55** so no arbitrary `/[0.14]` values are needed.
- Custom themes (`lorekeeper-custom-themes` in localStorage) missing any new key: fall back per key to the dnd value if the custom `background` lightness ≤ 50%, else the light value. The fallback runs before `ThemeContext.applyTheme`'s existing `colors` → `--<key>` loop; no CSS variable may be left unset.

### Type roles (families always `var(--font-heading)` / `var(--font-body)`, never literal fonts)

| Role | Family | Size | Weight | Line height | Tracking / notes |
|---|---|---|---|---|---|
| page-title | heading | 24px | 700 | 1.3 | 0.04em (existing PageHeader) |
| entity-title | heading | 30px | 700 | 1.2 | 0.04em; drops to 24px (entity-title-mobile) below `md` |
| section-label | heading | 12px | 600 | 1.4 | 0.1em, uppercase via CSS |
| body | body | 16.8px | 400 | 1.65 | existing 1.05rem set in `index.css` |
| body-sm | body | 14px | 400 | 1.55 | |
| meta | body | 12px | 400 | 1.4 | |
| quote | body | 14px | 400 | 1.55 | italic |
| mono | `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` | 12px | 400 | 1.4 | `font-variant-numeric: tabular-nums` |
| stat-display | heading | 24px | 700 | 1.2 | |
| caption-live | body | 20px | 400 | 1.5 | |
| caption-table | body | 36px | 500 | 1.3 | |
| recap-table | body | 32px | 400 | 1.45 | |

Utilities required by 8.1: `text-entity-title`, `text-quote`, `font-mono-tabular`, `text-caption-live`, `text-caption-table`, `text-recap-table`. Cyberpunk's monospace body is kept in captions (don't override a GM's world font). Table sizes are estimates, verified later by E4.

### Shape, radius, elevation, spacing

- Radius always from theme `--radius` (`sm` = −4px, `md` = −2px, `lg` = `--radius`, `xl` = +4px); never hardcoded. Pills (`rounded-full`) only for badges and chips. Dashed outline = provisional or not public.
- Spacing tokens: gutter-mobile 16px, page-max 64rem (`max-w-5xl`), reading-max 48rem, slideover-max 32rem (`md:max-w-lg`), slideover-wide 48rem (`md:max-w-3xl`), tap-target 44px, tap-target-table 56px.
- Z-order: SlideOver 50, PreviewBanner 60 (above nav, no shadow), Toast 70. Dropdowns/popovers `shadow-xl`; SlideOver `shadow-2xl` over `bg-black/40`. No glassmorphism beyond the nav's `backdrop-blur-sm`.

### Ownership and conventions

- Epic owns: `types/theme.ts`, `themes/*.ts`, `contexts/ThemeContext.tsx` (token fallback only), `tailwind.config.ts`, `index.css`, `components/ui/*`, `components/SlideOver.tsx`, the `components/NavBar.tsx` shell, `components/shell/*`, `lib/routes.ts`, `pages/NotFoundPage.tsx`, `lib/shortcuts.ts`, `scripts/check-ui-tokens.mjs`. Frontend paths are relative to `src/frontend/src/`.
- Story 8.2 makes class-only edits in files other epics own; it must not change layout.
- New primitives are cva-styled like `components/ui/button.tsx`, use theme tokens only, show a visible `ring` focus, and pass `tsc` strict. Lucide icons only; no emoji as UI icons.
- Pages: named exports behind the `lazy` adapter; react-query keys `[domain, campaignId]`; `md:`-first responsive.
- All role/visibility UI is cosmetic. Data hiding is always server-side (one authorization enforcement point); components must not be treated as the control.
- API exposed for other epics: SlideOver `size`/`push`/`pop` and `lib/layers.ts` layer stack; `useToast()` + `setTitleBadge(n)`; `usePreview()`, `useWriteGuard()`, Button `write` prop; `useCurrentCampaign`, `useEffectiveRole()`; `lib/routes.ts` registry `{ path, title, navGroup?, roles }` + `isRouteRegistered()`, `<NotFound />`, `usePageTitle()`; `useShortcut(key, { scope, description }, handler)`; `lib/format.ts` `formatEta`, `entryTitle`.

## UX & Interaction Patterns

- Brand rule: new screens must look like they were always there. Restyling existing primitives (Button, Card, Badge, Input, Textarea, PageHeader, nav dropdown) is out of bounds.
- Only one SlideOver at a time (replace or push, never stack); `Esc` closes only the top layer and never exits preview. Below `md` SlideOvers are full-screen with a sticky header.
- Shortcuts never fire in inputs, textareas, selects, contenteditable or during IME composition; `?` opens the shortcut list.
- Voice: plain, calm, honest. ETAs are ranges or "about" ("about 1–2 min left"); entries named by italic title, never raw IDs; sentence-case buttons; AI-made text labelled with its origin.
- State patterns: skeletons shaped like content (no full-page spinner); inline request errors in `danger` with Retry, keeping form input; offline notice "You're offline — changes are paused"; one not-found page "This page doesn't exist or isn't shared with you." for both missing and forbidden.
- Toast: popover surface, bottom-right `md`+ / bottom-centre phones, max 3, one action, 6 s info / 10 s undo / failures persist, pause on hover or focus, polite announcements.
- Nav keeps its shape (wordmark, one grouped dropdown, avatar) plus CampaignSwitcher and a reserved JobTrayButton slot; net link count unchanged. Players see only Portal, World, My Journal, Chronicler, Recaps (each only when registered).
- Route changes set `document.title` ("World · Lorekeeper"), announce politely, and move focus to the page `h1`.

## Cross-Story Dependencies

- 8.1 is the root: 8.2, 8.3, 8.4 and 8.5 depend on it. 8.6 needs 8.1, 8.4 and 8.5. 8.7 needs 8.5 (fallback toast) and 8.6 (RoleBadge, PreviewContext). 8.8 needs 8.7. 8.9 needs 8.3 (layer stack, SlideOver) and 8.8 (page registry).
- External: soft dependency on E0-Access.2 `useCampaignRole` (`GET /api/campaigns/{id}/me`); until it lands, `useEffectiveRole` stubs `gm` for `is_owner` Campaigns and `player` otherwise. 8.2's CI step is a one-line addition to E0-QA's frontend workflow.
- Consumers: E0-Jobs.10 (Toast, title badge, JobTrayButton slot); E1 Review Checklist (wide SlideOver, push header, shortcuts); E0-WorldCore EntityPanel and `/world` registration; E7 (Portal routes, `/dashboard` → `/portal`, preview data path); E4 (`/live`, 56px targets); E3, E10 shortcuts. Registering their routes activates nav entries and redirects without editing this epic's code.
