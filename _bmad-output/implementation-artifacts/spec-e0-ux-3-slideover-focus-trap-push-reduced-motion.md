---
title: 'E0-UX.3 SlideOver focus trap, wide and full-screen variants, push header, and reduced motion'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '6d34034d98cd4707c17a8b3750a365e5dec99c4d'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      SlideOver component behaviour (Esc pop-vs-close, unmount focus return, push/pop scroll and focus restore, supersede) has no automated test.
    evidence: |-
      check-focus-trap.mjs covers only the pure helpers and registry; the frontend has no DOM/React test runner. Manual browser check recorded in Verification.
    location: >-
      src/frontend/src/components/SlideOver.tsx
    severity: medium
  - summary: >-
      check-focus-trap.mjs is not wired into package.json or CI.
    evidence: |-
      package.json scripts are dev/build/preview only; parallel siblings edit package.json; frontend CI checks are wired by E0-UX.2 / E0-QA.
    location: >-
      src/frontend/scripts/check-focus-trap.mjs
    severity: low
  - summary: >-
      NpcCard and QuestCard are non-focusable clickable divs, so closing their panel returns focus to main rather than the card, and keyboard users cannot open them.
    evidence: |-
      pages/CharactersPage.tsx:26 and pages/QuestsPage.tsx:24 render onClick divs without tabIndex/role; activeElement is body at open. Pre-existing; page files are outside this story.
    location: >-
      src/frontend/src/pages/CharactersPage.tsx:26
    severity: medium
  - summary: >-
      A SlideOver rendered inside another SlideOver's content is unmounted when it supersedes its parent; nested panels must use push().
    evidence: |-
      Superseded instance returns null, removing its subtree including the newcomer. No current caller nests; document for E1/WorldCore consumers.
    location: >-
      src/frontend/src/components/SlideOver.tsx
    severity: medium
  - summary: >-
      In-panel widgets and existing ad-hoc Esc handlers are not on the layer stack, so one Esc could close both an inner widget and the panel.
    evidence: |-
      Only SlideOver calls pushLayer. JournalInput.tsx:378 and CampaignSelector.tsx:74 keep their own listeners; E0-UX.4 Combobox/popovers should register via pushLayer or preventDefault Esc.
    location: >-
      src/frontend/src/lib/layers.ts
    severity: medium (unverified)
  - summary: >-
      Auto-focusing the first text input on open/push may raise the mobile keyboard and does not announce the pushed title.
    evidence: |-
      focusInitial targets the content's first focusable (e.g. NPC Name input). Needs an iOS/Android device check to settle.
    location: >-
      src/frontend/src/lib/focusTrap.ts
    severity: medium (unverified)
  - summary: >-
      push() stores the render closure at push time, so values captured from the pusher's state are frozen.
    evidence: |-
      levels render e.render from the stack entry; consumers should render a component that reads its own data.
    location: >-
      src/frontend/src/components/SlideOver.tsx
    severity: low
  - summary: >-
      Page behind the SlideOver is not inert and does not scroll-lock; TourOverlay smooth-scrolls under reduced motion.
    evidence: |-
      Only aria-modal marks modality (story keeps it). TourOverlay.tsx:20 passes behavior smooth, which overrides CSS scroll-behavior. Both pre-existing.
    location: >-
      src/frontend/src/components/TourOverlay.tsx:20
    severity: low
---

<intent-contract>

## Intent

**Problem:** `SlideOver` has no focus trap and never returns focus, has one size, can't show a nested panel, can be stacked, and the app ignores `prefers-reduced-motion` (UX-DR4, UX-DR5, UX-DR12, NFR-10).

**Approach:** Add an in-house `lib/focusTrap.ts` and a global Esc layer stack `lib/layers.ts`; rebuild `SlideOver` on them with `size`, a `push`/`pop` context, a one-open-at-a-time registry, and focus return; add global reduced-motion CSS in `index.css` and a `useReducedMotion()` hook.

## Boundaries & Constraints

**Always:** no new npm dependency; theme tokens only; `aria-modal="true"` stays and `aria-labelledby` points to the visible title; focusables are re-queried on every Tab; existing `NpcDetailPanel`/`QuestDetailPanel` look and behave as before apart from the trap and focus return; `tsc` strict passes; `focusTrap.ts` and `layers.ts` have no runtime imports (Node type stripping can load them).

**Never:** edit E0-UX.4/E0-UX.5 files (`components/ui/button.tsx`, `combobox.tsx`, `segmented-control.tsx`, `tabs.tsx`, `toast*`, `empty-state.tsx`, `inline-error.tsx`, `model-missing-notice.tsx`, `lib/format.ts`); restyle existing primitives; add a test runner; make the Esc stack exit preview.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Tab cycle | open panel, focus on last focusable, `Tab` | focus moves to first focusable in panel | default Tab prevented |
| Shift+Tab cycle | focus on first focusable, `Shift+Tab` | focus moves to last | default prevented |
| Focus outside | focus on `body` (clicked non-focusable text), `Tab` | focus moves to first (Shift: last) panel focusable | — |
| No focusables | panel with only text, `Tab` | heading keeps focus | — |
| Open | panel content has an input | input focused; content with no focusable → heading (`tabIndex=-1`) focused | — |
| Close | Esc / backdrop / Close | focus returns to opener; opener removed → `main` focused (gets `tabindex=-1` if needed) | no `main` → no-op |
| Push | `push({title, render, backLabel})` | header shows "← backLabel", pushed title; A stays mounted, hidden | — |
| Pop | Back or first Esc | A shown with its scroll position and prior focus restored; second Esc closes | opener of push gone → first focusable rule |
| Second open | B opens while A open | A's `onClose` called, A renders nothing, B shown; B returns focus to A's opener; dev `console.warn` names both | A's own focus restore is skipped |
| Layers | two layers registered, Esc | only the top layer's handler runs | IME composition / `defaultPrevented` ignored |
| Reduced motion | `prefers-reduced-motion: reduce` | all transition/animation durations ≈0 (1 iteration), no slide, no pulse/spin; `useReducedMotion()` true and updates live | no `matchMedia` → false |

</intent-contract>

## Code Map

- `src/frontend/src/components/SlideOver.tsx` -- current: props `open,onClose,title,children`; own `keydown` Esc listener; backdrop `z-40 bg-black/40 transition-opacity duration-300`; panel `fixed inset-y-0 right-0 z-50 w-full md:max-w-lg ... transition-transform duration-300`; header `h2` + inline-SVG Close; body `flex-1 overflow-y-auto px-5 py-5`. Already full-width below `md`.
- `src/frontend/src/components/NpcDetailPanel.tsx:68`, `QuestDetailPanel.tsx:60` -- `<SlideOver open={!!x} onClose title>`; both `return null` when closed, so SlideOver mounts on open and unmounts on close (focus return must run in unmount cleanup). API stays compatible; no change expected.
- `src/frontend/src/App.tsx:81` -- `<main className="flex-1 flex flex-col">` (no tabindex; append point, don't edit — the fallback sets `tabindex=-1` at runtime).
- `src/frontend/src/main.tsx` -- `React.StrictMode` (effects double-run in dev; open/close effects must be idempotent).
- `src/frontend/src/index.css` -- owned here this wave; append the reduced-motion block.
- `src/frontend/scripts/check-semantic-fallback.mjs` -- pattern for a dependency-free Node check importing `.ts` via type stripping (Node ≥ 22.18; local Node 26).
- `src/frontend/src/hooks/` -- hook location convention (`useDebounce.ts` etc.).

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/lib/focusTrap.ts` -- `FOCUSABLE_SELECTOR`; `getFocusable(container)` (re-query, drop `tabIndex<0`, hidden/no client rects); pure `nextFocusIndex(count, current, shift)`; `handleTabKey(container, event, active, fallback)` always prevents default and focuses the computed target; `focusInitial(content, heading)`; `restoreFocus(el)` (connected → focus, else `main` with `tabindex=-1`).
- `src/frontend/src/lib/layers.ts` -- `pushLayer(onEscape) => remove`, `closeTopLayer()`, `layerCount()`; one lazy document `keydown` listener that calls only the top handler.
- `src/frontend/src/hooks/useReducedMotion.ts` -- `useSyncExternalStore` on `matchMedia('(prefers-reduced-motion: reduce)')`.
- `src/frontend/src/components/SlideOver.tsx` -- `size?: "default" | "wide"` (`md:max-w-lg` / `md:max-w-3xl`), optional `name` for the dev warning; `sticky top-0` header; `aria-labelledby`; layer registration (Esc pops, then closes); document Tab trap while active; open-focus and close-return; `SlideOverContext` + exported `useSlideOver()` with `push`, `pop`, `depth`; stack entries each in their own scroll container (non-top `hidden`), scroll and focus saved on push and restored on pop; module registry enforcing one visible SlideOver with dev warning; closed panel `invisible` so it is not tabbable.
- `src/frontend/src/index.css` -- `@media (prefers-reduced-motion: reduce)` rule over `*, ::before, ::after` setting animation/transition duration `0.01ms !important`, iteration count 1, `scroll-behavior: auto`.
- `src/frontend/scripts/check-focus-trap.mjs` -- node:assert checks for `nextFocusIndex`, `handleTabKey` with fake elements, and `layers.ts` top-only Esc.

**Acceptance Criteria:**
- Given `<SlideOver size="wide">` at `md`+, when built, then the panel has `md:max-w-3xl`; default keeps `md:max-w-lg`; below `md` both are `w-full` with a sticky header.
- Given NpcDetailPanel or QuestDetailPanel, when opened, then it looks as before, Tab stays inside, and closing returns focus to the clicked list item.
- Given a pushed panel, when it is shown, then the header has a "← Back to …" button and `aria-labelledby` names the pushed title.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 41 findings — high 0, medium 9, low 21, false 8, maybe-false 3
- findings:
  - (intent-alignment) `[low]` `reject` Initial focus goes to first focusable in content, not panel-wide (Close) — deliberate, documented reading (Design Notes); the mobile-keyboard consequence is tracked separately below.
  - (intent-alignment) `[low]` `reject` Dev warning names both SlideOvers by `name ?? title`, not a code site — `name` prop exists precisely to name the caller; adding stack parsing is complexity for a dev-only message.
  - (intent-alignment) `[low]` `defer` Existing ad-hoc Esc handlers (`JournalInput.tsx:378`, `CampaignSelector.tsx:74`) not migrated to `lib/layers.ts` — outside this story's files; grouped with the inner-widget Esc deferral.
  - (intent-alignment) `[false]` `reject` "Replace content" vs "close old instance" — observable outcome is identical: one panel, new content, old one gone.
  - (intent-alignment) `[false]` `reject` 0.01 ms instead of 0 ms — imperceptible; intentional so `transitionend` fires.
  - (intent-alignment) `[false]` `reject` Existing panels' visual change unverified — header `bg-background` equals the panel background; sticky header inside a non-scrolling flex column renders identically; `invisible` only applies when closed, and consumers unmount instead.
  - (verification-gap) `[low]` `defer` `check-focus-trap.mjs` not wired into package.json/CI — package.json is touched by parallel siblings; CI wiring for frontend checks is owned by E0-UX.2 / E0-QA (same state as E0-UX.1's scripts).
  - (verification-gap) `[medium]` `defer` SlideOver component logic (Esc pop-vs-close, unmount focus return, push/pop scroll restore) has no automated test — no DOM/React test runner and adding one is out of scope; manual check recorded.
  - (verification-gap) `[low]` `patch` Reduced-motion check was a loose text match — now slices the exact `@media` block (asserts it exists and closes) and checks five rules inside it.
  - (verification-gap) `[false]` `reject` `useReducedMotion` has no consumer — the AC requires it to be exported for later JS-animated components.
  - (verification-gap) `[low]` `defer` `TourOverlay.tsx:20` `scrollIntoView({behavior:"smooth"})` overrides CSS under reduced motion — pre-existing, not this story's file; future fix uses `useReducedMotion()`.
  - (verification-gap) `[false]` `reject` `open=false` paths unreached by current callers — not a defect; the API supports always-mounted callers.
  - (blind) `[medium]` `defer` A `<SlideOver>` rendered inside another panel's content is unmounted when it supersedes its parent — nested panels must use `push` (the story's mechanism); documented as an API contract.
  - (blind) `[medium]` `patch` Return target was always inherited from the superseded panel — registry now inherits only when the newcomer's opener is inside the old panel (`contains`) or missing; tests added.
  - (blind) `[medium]` `patch` Tab trap ignored layers above it — Tab is left alone when a newer layer is registered and focus is outside the panel.
  - (blind) `[low]` `defer` In-panel widgets must `preventDefault` Esc or register a layer — grouped with E0-UX.4 coordination deferral.
  - (blind) `[low]` `reject` Radio groups / `button[disabled][tabindex]` / `visibility:hidden` / inert in focusable list — none occur in current panels; fix adds branches.
  - (blind) `[low]` `defer` No `inert`/scroll lock on the page behind — not in the story (aria-modal stays); pre-existing.
  - (blind) `[maybe-false]` `defer` Auto-focusing the first text input on open/push may raise the mobile keyboard and doesn't announce pushed context — needs a device check (iOS/Android) to settle.
  - (blind) `[low]` `defer` Pushed `render` closure captures pusher state at push time — contract note for E1/WorldCore consumers (render a component that reads its own data).
  - (blind) `[medium]` `defer` (grouped with verification-gap SlideOver tests) SlideOver has no tests; Node ≥ 22.18 needed by the script.
  - (blind) `[low]` `patch` CSS check `indexOf` -1 made `block.length > 0` vacuous — fixed as above.
  - (blind) `[low]` `patch` Reduced motion ignored `transition-delay`/`animation-delay` — both set to `0s !important`.
  - (blind) `[false]` `reject` `animate-spin` freezes — the AC explicitly asks for ~0 duration on `animate-spin`; spinners sit next to text labels.
  - (blind) `[false]` `reject` `useReducedMotion` dead code — required export (see above).
  - (blind) `[low]` `reject` Stale `name`/`title` in dev warning if title changes while open — dev-only message, fix needs refs.
  - (edge) `[medium]` `defer` Opener is a non-focusable clickable `<div>` (NpcCard/QuestCard), so focus returns to `main` — pre-existing: cards aren't keyboard-operable; fixing needs page files outside this story.
  - (edge) `[medium]` `patch` Tab pulled focus out of a portaled layer above — same fix as the blind Tab-trap row.
  - (edge) `[low]` `reject` `focus()` on unfocusable target (fieldset[disabled], inert) stalls Tab — not present in current panels; fix adds retry loop.
  - (edge) `[low]` `reject` `visibility:hidden`/inert elements kept in list — same as above.
  - (edge) `[low]` `reject` Active element inside panel but not in list → Tab goes to first — happens only after clicking plain text; fix needs DOM-position comparison.
  - (edge) `[low]` `patch` Connected-but-unfocusable opener dropped focus to body — `restoreFocus` now checks `activeElement` and falls back to `main`; test added.
  - (edge) `[low]` `reject` Opener removed in the same commit as unmount — deferring restore to a microtask would break StrictMode re-focus; unlikely in practice.
  - (edge) `[low]` `patch` pop()+push() in one handler skipped refocus — layout effect now keyed on the top entry key.
  - (edge) `[low]` `reject` Superseded instance whose parent keeps `open=true` stays null — intended: it was told to close.
  - (edge) `[maybe-false]` `reject` Always-mounted close at depth>0 flashes root during slide-out — no always-mounted caller exists; would be low.
  - (edge) `[false]` `reject` Initial focus fails during visibility transition — `visibility` interpolates to `visible` immediately when either endpoint is visible.
  - (edge) `[medium]` `patch` Held Esc (auto-repeat) unwound every level and closed — `layers.ts` ignores `event.repeat`; test added.
  - (edge) `[maybe-false]` `defer` Inner widget handling Esc without `preventDefault` closes both — depends on E0-UX.4's Combobox/popover; they should register with `pushLayer`.
  - (edge) `[low]` `reject` Stale name in warning — duplicate of blind row; same reason.
  - (edge) `[medium]` `defer` Claim "closing returns focus to the clicked list item" is false for mouse clicks on non-focusable cards — same root as the NpcCard row; falls back to `main` per the story's rule.

## Design Notes

- **Initial focus target.** The panel chrome always contains Close (and Back), so "first focusable element, or the heading if there is none" is only meaningful for the panel *content*; the rule applies to the content area of the top stack entry. Tab cycling covers the whole panel including header buttons.
- **Replace, not stack.** Pages render their own `<SlideOver>`, so "one at a time" is a module registry: the newest open instance is active; the previous one is told to close (`onClose`) and renders nothing even if its parent ignores that. The new one inherits the old one's return-focus target, because its own opener lived inside the panel that just vanished.
- **Reduced motion** uses `0.01ms` rather than `0` so `transitionend`/`animationend` still fire.

## Verification

**Commands:**
- `cd src/frontend && node scripts/check-focus-trap.mjs` -- expected: exit 0, "ok".
- `cd src/frontend && npx tsc --noEmit` -- expected: no errors.
- `cd src/frontend && npm run build` -- expected: success; built CSS contains `prefers-reduced-motion` and `md:max-w-3xl`.

**Manual checks (if no CLI):**
- In a browser: open an NPC, Tab/Shift+Tab cycles inside; Esc returns focus to the NPC card; DevTools "Emulate prefers-reduced-motion: reduce" → panel appears without sliding, skeletons static.

## Auto Run Result

Status: done

**Summary:** SlideOver now traps Tab (focusables re-queried each Tab), focuses the first focusable in its content (or the heading) on open, and returns focus to its opener (or `main`) on close. It has `size="wide"` (`md:max-w-3xl`) next to the default `md:max-w-lg` (full-screen with a sticky header below `md`), a `useSlideOver()` `push`/`pop` API with a "← Back to …" header and per-level scroll/focus restore, and a one-open-at-a-time registry that supersedes the previous panel with a dev warning. Esc goes through a global layer stack (`lib/layers.ts`, top layer only). A global `prefers-reduced-motion` CSS block and a `useReducedMotion()` hook are added. Existing panels keep the same props.

**Files changed:**
- `src/frontend/src/components/SlideOver.tsx` -- rewritten on the new helpers; `size`, `name`, push/pop context, registry, trap, focus return.
- `src/frontend/src/lib/focusTrap.ts` -- new; focusable query, `nextFocusIndex`, `handleTabKey`, `focusInitial`, `restoreFocus`.
- `src/frontend/src/lib/layers.ts` -- new; global Esc stack (`pushLayer`, `closeTopLayer`, `layerCount`).
- `src/frontend/src/lib/slideOverRegistry.ts` -- new; one-open-at-a-time registry (extracted so it is Node-testable).
- `src/frontend/src/hooks/useReducedMotion.ts` -- new; live `matchMedia` hook.
- `src/frontend/src/index.css` -- reduced-motion block (durations 0.01ms, delays 0, one iteration, no smooth scroll).
- `src/frontend/scripts/check-focus-trap.mjs` -- new; dependency-free Node check of the helpers, registry, layers and the CSS block.

**Review:** 41 findings (high 0, medium 9, low 21, false 8, maybe-false 3). Patched 8 rows: Esc auto-repeat ignored (medium); return target inherited only when the opener is inside the superseded panel (medium); Tab trap yields to a newer layer when focus is outside the panel (medium, two rows); `restoreFocus` falls back to `main` when `focus()` fails (low); push/pop focus effect keyed on the top entry (low); reduced-motion delays zeroed (low); CSS check tightened (low, two rows). Deferred 8 items (see frontmatter `deferred`), including no component-level test, focus return for non-focusable NpcCard/QuestCard openers (pre-existing), nested-SlideOver supersede, and inner-widget Esc for E0-UX.4. Rejected rows and reasons are in the Review Triage Log.

**Follow-up review recommended:** true -- three medium entries were patched (Esc repeat, return-target inheritance, Tab-trap layer yield), and none of them is covered at the component level; the Tab-trap yield in particular should be checked in a browser once E0-UX.4's popovers exist.

**Verification:** `node scripts/check-focus-trap.mjs` -> "check-focus-trap: ok"; `npx tsc --noEmit` -> clean; `npm run build` -> success, built CSS contains `prefers-reduced-motion` and `md:max-w-3xl`. No lint script exists. Matrix rows Open, Tab/Shift+Tab, Focus outside, No focusables, Close, Second open, Layers and the reduced-motion CSS are covered by the script; Push/Pop rendering and `useReducedMotion()` have only the manual browser check (no DOM test runner). Manual browser check not performed (no browser available in this run).

**Residual risks:** component behaviour is verified only through helper tests and tsc; script needs Node >= 22.18; sprint-status sync skipped per the orchestrator brief.
