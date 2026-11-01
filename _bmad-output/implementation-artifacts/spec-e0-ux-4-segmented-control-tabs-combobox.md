---
title: 'E0-UX.4 SegmentedControl, Tabs and Combobox primitives'
type: 'feature'
created: '2026-10-31'
baseline_revision: '6d34034d98cd4707c17a8b3750a365e5dec99c4d'
status: 'done'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      The keyboard, ARIA and async behaviour of SegmentedControl, Tabs and Combobox has no committed executable test.
    evidence: |-
      The frontend has no test runner (no test script, vitest, testing-library or playwright in package.json), and this story forbids new npm dependencies. The behaviour was exercised with a throwaway Playwright harness outside the repo (51/51 checks passed), but nothing in CI would catch a regression such as a flipped arrow direction, a dropped stale-response guard or a dropped onCreate gate.
    location: >-
      src/frontend/src/components/ui/{segmented-control,tabs,combobox}.tsx
    severity: medium
---

<intent-contract>

## Intent

**Problem:** New surfaces (Visibility switch, World and Keepsakes tabs, relationship-target and Location pickers) need segmented controls, tabs and comboboxes, but `components/ui` has none, so each screen would hand-roll its own keyboard and ARIA behaviour.

**Approach:** Add three in-house, cva-styled primitives (`segmented-control.tsx`, `tabs.tsx`, `combobox.tsx`) to `src/frontend/src/components/ui/` that implement the WAI-ARIA radio-group, tabs (manual activation, optional route mode) and list-autocomplete combobox patterns, using theme tokens only.

## Boundaries & Constraints

**Always:** cva variants exported next to each component, like `button.tsx`; theme tokens only (`muted`, `foreground`, `muted-foreground`, `border`, `input`, `popover`, `ring`, `danger`, `background`); visible focus `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background`; active segment / tab `bg-muted text-foreground font-medium`, inactive `text-muted-foreground hover:text-foreground hover:bg-muted/60`; SegmentedControl items ≥ 44px tall (`min-h-11`); lucide icons only; `tsc` strict; ids from `React.useId()`; debounce via the existing `hooks/useDebounce.ts` at 150 ms.

**Never:** no new npm dependency (only the existing `@radix-ui/react-slot`, `class-variance-authority`, `lucide-react`, `react-router-dom`); no edits to `button.tsx`, `input.tsx` or other existing primitives (restyling them is out of bounds); no edits to `index.css`, `SlideOver.tsx`, `focusTrap.ts` or E0-UX.5 files (sibling stories own them this wave); no `components/ui/index.ts` barrel (none exists, so consumers import by path); no adoption in existing pages (consumers arrive in later stories).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Segmented arrows | focus on selected item, ArrowRight / ArrowDown | next enabled item focused and selected (wraps); ArrowLeft/Up reverse; Home/End first/last enabled | disabled items skipped |
| Segmented no selection | `value` matches no option | first enabled item has `tabIndex=0`, rest `-1` | — |
| Tabs manual | ArrowRight on a tab | focus moves to next tab, active tab unchanged; Enter/Space activates focused tab | disabled tabs skipped |
| Tabs routeMode | tab `to="/world/web"` activated while on `/world` | `navigate("/world/web")` (push); Back returns to `/world`; active tab = longest `to` equal to or a `/`-prefix of the pathname | no match → first tab active |
| Combobox typing | user types "gob" | after 150 ms `loadOptions("gob")` runs, list opens, results shown | stale responses discarded; rejected promise shows "Couldn't load options" in `text-danger` |
| Combobox keys | closed, ArrowDown | list opens, first item active via `aria-activedescendant`; arrows move it (wrap); Enter selects; Esc closes | Enter with no active item does nothing |
| Combobox empty | result `[]` | "No matches" shown in a polite status | — |
| Combobox create | `onCreate` passed and non-empty query with no exact label match | trailing "Create “query”…" option; Enter/click calls `onCreate(query)` | never shown without `onCreate` |
| Combobox blur | user types then tabs away without selecting | list closes, input text reverts to selected option's label (or empty) | — |

</intent-contract>

## Code Map

- `src/frontend/src/components/ui/button.tsx` -- style reference: `cva` base + variants, `forwardRef`, `cn`, export `{ Component, componentVariants }`. Read-only.
- `src/frontend/src/components/ui/input.tsx` -- reuse `Input` for the Combobox text field (same look as all forms). Read-only.
- `src/frontend/src/lib/utils.ts` -- `cn()` (tailwind-merge aware of type-role classes).
- `src/frontend/src/hooks/useDebounce.ts` -- `useDebounce<T>(value, delay)`; reuse, do not modify.
- `src/frontend/src/components/NavBar.tsx:250` and `src/frontend/src/pages/AdminPage.tsx:887` -- the existing active/inactive tab classes to match.
- `src/frontend/tailwind.config.ts` -- `popover`, `muted`, `danger` etc. already exposed; no change needed.
- `react-router-dom` v6 -- `useLocation`, `useNavigate` for Tabs `routeMode`.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/components/ui/segmented-control.tsx` -- create generic `SegmentedControl<T extends string>` (`options: {value,label,icon?,disabled?}[]`, `value`, `onValueChange`, `aria-label`/`aria-labelledby`, `size: default|table`, `className`) rendering `role="radiogroup"` with `role="radio"` buttons, `aria-checked`, roving tabindex, arrow/Home/End move-and-select; export `segmentedControlVariants`, `segmentedItemVariants` -- AC 1.
- `src/frontend/src/components/ui/tabs.tsx` -- create `Tabs` (`tabs: {value,label,to?,disabled?,content?}[]`, controlled `value`/`onValueChange` or `defaultValue`, `routeMode`, `aria-label`, `children` as active-panel fallback content, `className`, `panelClassName`) rendering `role="tablist"` / `role="tab"` (`aria-selected`, `aria-controls`, roving tabindex) and one `role="tabpanel"` per tab (`aria-labelledby`, inactive ones `hidden` and empty); manual activation; Home/End; route mode navigates with push; export `tabsListVariants`, `tabVariants` -- AC 2.
- `src/frontend/src/components/ui/combobox.tsx` -- create generic `Combobox<T extends ComboboxOption>` (`loadOptions(query) => Promise<T[]>`, `value: T | null`, `onChange(option: T)`, optional `onCreate(query)`, `createLabel?(query)`, `placeholder`, `id`, `aria-label`/`aria-labelledby`, `disabled`, `className`) with `role="combobox"` input (`aria-expanded`, `aria-controls`, `aria-autocomplete="list"`, `aria-activedescendant`) and `role="listbox"` popover of `role="option"` items; behaviour per matrix; export `comboboxOptionVariants` -- AC 3.

**Acceptance Criteria:**
- Given any of the three primitives rendered in any of the six themes, when inspected, then every colour class is a theme token, keyboard focus shows a `ring`, and `npx tsc --noEmit` and `npm run build` pass.
- Given `SegmentedControl` with options "Private · Share with party", when rendered, then it is `role="radiogroup"` with `role="radio"` items, only the selected item is in the tab order, the active one is `bg-muted text-foreground font-medium`, and each item is ≥ 44px tall.
- Given `Tabs` with `routeMode`, when a tab is activated, then the URL updates by push so Back returns to the previous tab; without `routeMode` arrows move focus only and Enter/Space activates; `tablist`/`tab`/`tabpanel` are wired with `aria-controls` and `aria-labelledby`.
- Given `Combobox`, when the user types, then options load debounced 150 ms through `useDebounce`, the list is a `listbox`, and the "Create…" option appears only when `onCreate` is passed.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 39 findings — high 0, medium 9, low 18, false 12, maybe-false 0
- findings:
  - `[medium]` `[patch]` (blind) Combobox shows and lets you select old-query options while a new query debounces/loads — handleChange now bumps requestIdRef, clears options and sets status loading; harness "cb old results cleared while typing" passes.
  - `[medium]` `[patch]` (blind) Create row computed against old results, can create duplicates — same root cause; showCreate now requires status === "ready".
  - `[low]` `[reject]` (blind) Selection cannot be cleared — no consumer exists yet; clearing needs new public API (`T | null`) that the first optional-field consumer should define.
  - `[low]` `[reject]` (blind) loadOptions gets no AbortSignal — stale responses are already dropped and loads are debounced; adding a signal is new API surface with no demonstrated harm.
  - `[medium]` `[patch]` (blind) role="status" region inside a display:none wrapper, so announcements can be missed — the popover container is never display:none now; the status region stays mounted (sr-only when empty/closed); harness "cb status region mounted when closed" passes.
  - `[low]` `[reject]` (blind) No aria-describedby/aria-invalid/name passthrough — no consumer yet; adding props is new surface the first form consumer can add.
  - `[false]` `[reject]` (blind) Tabs crashes outside a Router — App.tsx:77 wraps the whole app in BrowserRouter and the app uses no portals; there is no test runner or Storybook that renders outside it.
  - `[low]` `[reject]` (blind) Relative `to` / router basename break route matching — the app sets no basename (App.tsx:77), and the intended World/Keepsakes tabs use absolute paths; resolvePath support is an added branch with no caller.
  - `[low]` `[patch]` (blind) No-match fallback can pick a disabled tab, and a tab without `to` in routeMode fires onValueChange without activating — fallback now picks the first enabled tab; activate() returns early for routeMode tabs without `to`.
  - `[low]` `[patch]` (blind) SegmentedControl hides a selected value that is disabled — selectedIndex no longer filters disabled options; the tab stop falls back to the first enabled option; harness "seg disabled selected stays checked" passes.
  - `[low]` `[reject]` (blind) Arrow keys ignore RTL — the app has no RTL locale or dir attribute anywhere in src; adding it means extra branches with no reachable case.
  - `[medium]` `[defer]` (blind) No tests ship with the primitives — grouped with the verification-gap finding; deferred (no test runner, and the no-new-dependency rule).
  - `[false]` `[reject]` (intent) Back-button behaviour isn't exercised — the scratch harness checks "route click -> /world/web" and "route Back -> /world" in Chromium and both pass.
  - `[false]` `[reject]` (intent) An empty result isn't announced as a listbox — when options exist the listbox is rendered and exposed; the empty state is a polite status per the spec's Design Notes, and a listbox may contain only options.
  - `[false]` `[reject]` (intent) The Create row has gates beyond onCreate — the AC says it appears "only when" onCreate is passed, which holds; hiding it for an empty query or an exact match narrows it further but doesn't break that condition.
  - `[false]` `[reject]` (intent) Filtering is done only by loadOptions — the AC defines filtering through the async `loadOptions(query)`; the component calls it per settled query.
  - `[low]` `[reject]` (intent) SegmentedControl is nowrap, a 375 px risk — the planned option sets ("Private · Share with party", "Mention · Granted · Hidden") fit at 375 px; wrapping is a layout decision for a consumer with long labels.
  - `[false]` `[reject]` (intent) Keyboard patterns aren't demonstrated at runtime — 51 browser checks covering every keyboard row passed in the scratch harness (the committed-test gap is deferred separately).
  - `[false]` `[reject]` (intent) Reading C (adopting the primitives in feature surfaces) isn't addressed — the consumer stories list E0-UX.4 as their dependency, and this story's ACs cover only the primitives.
  - `[medium]` `[defer]` (verification-gap) No executable verification of the three primitives — filed disposition defer, accepted: needs a frontend test runner, which this story forbids.
  - `[medium]` `[patch]` (verification-gap) An in-flight response for an older query is applied while typing — same root cause as the first finding; fixed by bumping requestIdRef in handleChange.
  - `[low]` `[patch]` (verification-gap) SegmentedControl shows nothing selected when value is disabled — same as the blind finding; patched.
  - `[low]` `[patch]` (edge) Fallback picks disabled tabs[0] — first enabled tab now.
  - `[low]` `[patch]` (edge) A routeMode tab without `to` fires onValueChange — early return added.
  - `[low]` `[reject]` (edge) Relative `to`, or `to` with a query or hash — same as the blind basename/relative finding; no caller.
  - `[false]` `[reject]` (edge) Plain Tabs outside a Router throws — App.tsx:77 BrowserRouter wraps everything.
  - `[low]` `[patch]` (edge) routeMode fallback activation skips onValueChange — now compared against the matchRouteTab result.
  - `[low]` `[reject]` (edge) SegmentedControl RTL arrows — no RTL in the app.
  - `[low]` `[reject]` (edge) Tabs RTL arrows — no RTL in the app.
  - `[false]` `[reject]` (edge) Duplicate option values collide on React keys — option values are a caller contract (they identify the selection); duplicates are invalid input, not a reachable state.
  - `[medium]` `[patch]` (edge) Old-query results are selectable while typing — same root cause as the first finding; patched.
  - `[false]` `[reject]` (edge) A synchronous throw from loadOptions crashes the tree — the prop is typed `(query) => Promise<T[]>`, and an async function rejects rather than throwing; a sync throw breaks the caller contract and fails loudly.
  - `[false]` `[reject]` (edge) An untrimmed query is sent to loadOptions — passing the raw text is deliberate (the caller decides on trimming); the Create row's trimming is a display choice, so nothing goes wrong.
  - `[medium]` `[patch]` (edge) Options aren't cleared on close, so stale items show on reopen — close() now clears options and resets status.
  - `[low]` `[patch]` (edge) Mousedown on popover padding blurs the input — onMouseDown preventDefault on the popover container.
  - `[false]` `[reject]` (edge) The popover stays open when disabled flips true — a disabled input fires blur when it loses focus, and the existing blur handler closes the list; with no consumer, nothing toggles disabled mid-edit.
  - `[low]` `[patch]` (edge) Enter with the list open and no active option submits a surrounding form — Enter is now prevented whenever the list is open.
  - `[medium]` `[patch]` (edge, claim) "Stale responses discarded" only partly held — same root cause as the first finding; patched.
  - `[low]` `[patch]` (edge, claim) "No match → first tab" could pick a disabled tab — same as the fallback finding; patched.

## Design Notes

Route-mode matching picks the tab whose `to` is longest among those equal to the pathname or a prefix followed by `/`, so `/world/web` selects Web, not the `/world` tab, while `/world/abc` stays on the `/world` tab. Route mode keeps manual activation (arrows only move focus) so arrowing across tabs doesn't push a history entry per keypress.

Every tab owns a `tabpanel` element (inactive ones `hidden`, rendering nothing) so each `aria-controls` id resolves. In route mode, callers pass `<Outlet />` as `children`; it renders inside the active panel.

"No matches" sits outside the `<ul role="listbox">` in a `role="status"` element, because a listbox may only contain options; the empty listbox still exists so `aria-controls` resolves.

## Verification

**Commands:**
- `cd src/frontend && npx tsc --noEmit` -- expected: exit 0
- `cd src/frontend && npm run build` -- expected: exit 0
- `cd src/frontend && node scripts/check-ui-tokens.mjs --contrast` -- expected: exit 0 (unchanged)
- `grep -nE '#[0-9a-fA-F]{3,6}|rgb\(|-(green|amber|red)-[0-9]' src/frontend/src/components/ui/{segmented-control,tabs,combobox}.tsx` -- expected: no output

## Auto Run Result

Status: done

**Summary:** Added three in-house, cva-styled, token-only primitives to `src/frontend/src/components/ui/`. They use no new dependencies, add no barrel and have no consumers yet.

**Files changed:**
- `src/frontend/src/components/ui/segmented-control.tsx`: new WAI-ARIA radio group. Roving tabindex, arrows move and select, Home/End jump, items at least 44px tall, optional 56px `table` size.
- `src/frontend/src/components/ui/tabs.tsx`: new WAI-ARIA tabs with manual activation. Every tab has a panel. `routeMode` matches on the longest path prefix and pushes navigation, so Back returns to the previous tab.
- `src/frontend/src/components/ui/combobox.tsx`: new list-autocomplete combobox on top of `Input`. `loadOptions` runs debounced 150 ms through `useDebounce`, stale results are dropped, `aria-activedescendant` tracks the active option, the Create row appears only with `onCreate`, and the polite status reads "No matches", "Loading…" or "Couldn't load options".
- This spec file.

**Review:** 39 findings (medium 9, low 18, false 12), all logged above.
- 13 patch rows covering 6 root causes:
  - Combobox stale results (medium)
  - Status live region inside a hidden wrapper (medium)
  - Popover mousedown blur
  - Enter in a form submits it
  - Disabled selected segment shows as unselected
  - Tabs fallback and routeMode guards
- 2 deferred rows, one root cause: no committed frontend test.
- 24 rejected: 12 false, plus 12 low-value or no-consumer items such as clearing the selection, AbortSignal, aria-describedby passthrough, RTL, relative `to` and nowrap layout. Each one's reason is in the log.

**Follow-up review:** recommended (`true`). Two medium root causes were patched in the first pass. The unverified risk is the Combobox live-region and async-state behaviour: it is exercised only in headless Chromium and has not been tried with a real screen reader (VoiceOver/NVDA).

**Verification:**
- `npx tsc --noEmit` exit 0.
- `npm run build` exit 0.
- `node scripts/check-ui-tokens.mjs --contrast`: all 108 pairs pass.
- Hex/rgb/green-amber-red grep: clean.
- A throwaway Playwright harness outside the repo (headless Chromium, real component files through vite) ran 51 of 51 checks. They cover every I/O matrix row: segmented arrows/wrap/Home/End/disabled skip/no-selection tab stop; tabs manual activation, aria wiring, routeMode push and Back, `/world/abc` and no-match fallback; combobox debounce (one load per settled query), filtering, activedescendant, Enter/Esc, No matches, error, stale-response drop, blur revert, click select, and the Create row with and without `onCreate`.

**Residual risks:**
- No committed tests (deferred).
- Screen-reader announcement timing is untested on real assistive technology.
- Consumers must pass absolute `to` paths in `routeMode`.
- Sprint-status sync was skipped by orchestrator rule (`sprint-status.yaml` is not edited).
