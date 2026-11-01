---
title: 'E0-UX.9 Shortcut registry, help overlay and touch-target audit'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '56a28028dbe46f881bb3e9f3bc72253051acf028'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      The CI touch-target audit reads class strings statically; no CI check measures rendered boxes.
    evidence: |-
      check-touch-targets.mjs unions classes across conditional branches, maxes conflicting sizes instead of twMerge order, counts w-full/flex-1 as wide and min-h on inline elements, and cannot see neighbour overlap. Rendered sizes at 375 px were verified only by the throwaway Playwright run (55/55). A committed browser audit needs a browser runner in CI.
    location: >-
      src/frontend/scripts/check-touch-targets.mjs
    severity: low
  - summary: >-
      An always-mounted SlideOver (open toggled from false to true) cannot take initial focus on the frame it opens, because the panel is still visibility:hidden.
    evidence: |-
      Found in the Playwright run: focusInitial() ran while the panel's visibility transition started from hidden, so focus stayed on the page and a later Close click left focus on body. ShortcutHelp now mounts its SlideOver only while open. NpcDetailPanel/QuestDetailPanel mount conditionally and are unaffected, but any future always-mounted SlideOver hits this; the fix belongs in SlideOver (retry focus once visible).
    location: >-
      src/frontend/src/components/SlideOver.tsx (open effect, focusInitial)
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Feature epics (E1, E3, E4, E10) need one way to register keyboard shortcuts that never fire while the user is typing, never take browser or screen-reader keys, and can be discovered with `?`. Today there is no registry and no help list. Several shell and `components/ui` controls are also under 44 px at 375 px.

**Approach:** Add `lib/shortcuts.ts`, a module registry with a single document listener, a validated key grammar and the `useShortcut(key, { scope, description }, handler)` hook. Add `components/shell/ShortcutHelp.tsx`, a SlideOver opened with `?` (or from the profile menu) that lists the registered shortcuts grouped by scope. Add `scripts/check-touch-targets.mjs`, a static audit wired into CI, and fix the undersized targets it reports.

## Boundaries & Constraints

**Always:**
- No shortcut fires when focus is in an `input`, `textarea`, `select` or contenteditable, or during IME composition (`isComposing` / keyCode 229). `Esc` is never registrable, because the layer stack (`lib/layers.ts`) owns it.
- A shortcut fires only while its component is mounted and `enabled !== false`. The help list shows exactly the shortcuts currently registered and enabled, grouped by scope: "Global" first, then `page` (labelled with the current route's registry title via `findRoute`), then other scopes in the order they were first registered.
- The key grammar refuses browser and screen-reader keys. `parseShortcut` throws for: Escape, Tab, arrows, Home/End/PageUp/PageDown, F1–F12, Backspace/Delete, plain Enter, any `Alt+`, and any `Mod/Ctrl/Meta+` combination except `Mod+Enter`. A plain or `Shift+` key never fires while Ctrl, Meta or Alt is held. `Space` fires only when focus is not on an interactive element. Focus inside a `menu`, `menubar`, `listbox`, `tree`, `treegrid` or `grid` (typeahead) blocks all shortcuts.
- WCAG 2.1.4: the help overlay has a "Single-key shortcuts" switch, stored per device in `localStorage` `lk_shortcuts` = `"off"`. When it is off, no single-key shortcut fires, `?` included. The profile menu's "Keyboard shortcuts" item still opens the help.
- A `write: true` shortcut does not run its handler while preview is on (`isPreviewActive()`). It shows the toast "Preview is read-only" instead, and the help marks it "Not available in preview".
- While the help is open, no other shortcut fires. While any layer opened after a shortcut was registered is open, that shortcut does not fire, unless it was registered with `overLayers: true`.
- The help is one SlideOver. When another SlideOver is already open, the help is pushed into it as a level (`← Back to …`), so nothing is closed and `Esc` returns to the previous level. Otherwise the help opens its own SlideOver. Either way `Esc` closes only the help and focus returns to the element that had it.
- Touch targets: every interactive control in `components/ui/*`, `components/shell/*`, `components/SlideOver.tsx` and `components/NavBar.tsx` is ≥ 44 px in both dimensions at 375 px, or has a ≥ 44 px hit area. The hit area comes from the new `tap-target` utility (a centred `::before` of at least 44×44 that applies below `md` and on coarse pointers) on a positioned element. Nothing is hover-only below `md`. Every allowlist entry in the audit has a non-empty `reason`, and a stale entry fails the check.
- Semantic tokens only (`lint:tokens` passes). No new npm dependency. Desktop (`md+`) looks unchanged.

**Never:**
- Do not define any shortcut other than `?` (feature epics register their own).
- Do not add a test runner. Checks are node scripts that use the existing esbuild + node:test harness.
- Do not restyle Button, Card, Badge, Input, Textarea or PageHeader at `md+`.
- Do not edit `sprint-status.yaml`, `epics.md` or `desktop-verification-queue.md`, and do not commit `epic-*-context.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open help | `?` on page body | Help opens; the "Global" group lists `?` "Show keyboard shortcuts" | — |
| Typing | `?` in input/textarea/select/contenteditable | nothing fires; the character is typed | — |
| IME | `isComposing` or keyCode 229 | nothing fires | — |
| Modifier held | `Ctrl+?`, `Meta+j`, `Alt+j` for plain `j` | nothing fires | — |
| Caps Lock | `J` without Shift for `j` | fires `j`; `Shift+A` needs Shift | — |
| Reserved key | `useShortcut("Escape" \| "Mod+L" \| "Alt+x" \| "ArrowDown" \| "Enter")` | `parseShortcut` throws naming the key | programmer error |
| Space on button | `Space` with a button focused | does not fire; the button activates | — |
| Scope unmounted / disabled | component unmounted or `enabled:false` | does not fire; not listed | — |
| Duplicate key | two enabled `j` | the most recently registered one fires | — |
| Layer above | page `j`, then a SlideOver opens | `j` doesn't fire; `?` (overLayers) still opens help | — |
| Preview write | `write:true` while previewing | handler not run; toast "Preview is read-only" | — |
| Off switch | `lk_shortcuts=off` | no single-key shortcut fires; `Mod+Enter` still does | — |
| Close help | `Esc` or Close in help | help closes, focus returns to the opener; the page underneath stays as it was | — |
| Help over SlideOver | `?` with an Entity SlideOver open | help pushed into it; Esc goes back to the Entity level with focus restored | — |
| Repeat | held `?` (`event.repeat`) | ignored unless `allowRepeat` | — |

</intent-contract>

## Code Map

- `src/frontend/src/lib/layers.ts` -- `pushLayer`, `layerCount()`; one Esc listener. The shortcut dispatcher reads `layerCount()` and never handles Esc.
- `src/frontend/src/components/SlideOver.tsx` -- registers itself with `activateSlideOver` (registry) and `pushLayer`; `push`/`pop` stack; Esc handler pops when `depth>0`; focus save/restore on push/pop; close button `p-1.5` (30 px) and back button (text height) are undersized.
- `src/frontend/src/lib/slideOverRegistry.ts` -- `Registration {name, returnTarget, supersede, contains}`, `activeSlideOver()`. Add optional `push` so the help can push into the active SlideOver.
- `src/frontend/src/lib/preview.ts` -- `isPreviewActive()` (no React); `PREVIEW_READ_ONLY_TITLE` lives in `contexts/PreviewContext.tsx`.
- `src/frontend/src/components/ui/toast.tsx` -- `toast({ text })`.
- `src/frontend/src/lib/routes.ts` -- `findRoute(pathname)` gives the page scope label.
- `src/frontend/src/App.tsx` -- shell mount point (inside the BrowserRouter, next to `Toaster`).
- `src/frontend/src/components/NavBar.tsx` -- nav panel links `block px-4 py-2` (~36 px); the profile dropdown buttons `py-2` (~36 px); the logo Link has no width guarantee. `scripts/check-campaign-switcher.mjs:490-508` asserts `min-h-11`, `gap-2 sm:gap-3`, menu `aria-label` order and the `hidden sm:inline` span, all of which must be kept.
- `src/frontend/src/components/ThemeSelector.tsx` -- compact `<select>` (~24 px) inside the profile dropdown. Class-only fix.
- `src/frontend/src/components/ui/button.tsx` -- cva sizes `h-10`/`h-9`/`h-10 w-10`: add `relative tap-target` to the base (no visual change).
- `src/frontend/src/components/ui/input.tsx` -- `h-10` → `h-11 md:h-10` (only 2 usages).
- `src/frontend/src/components/ui/combobox.tsx` -- option `py-2` (~36 px) → add `min-h-11 md:min-h-0`.
- `src/frontend/src/components/ui/visibility-badge.tsx` -- pill trigger (~22 px), menu items `min-h-9`, and confirm buttons `h-7`.
- `src/frontend/src/components/ui/tabs.tsx`, `segmented-control.tsx` -- `min-h-11` ok; add `min-w-11`.
- `src/frontend/src/components/shell/CampaignSwitcher.tsx` -- trigger `min-h-11`; add `min-w-11`. `ITEM` `min-h-11 w-full` ok.
- `src/frontend/src/components/shell/PreviewBanner.tsx` -- Exit uses ad-hoc `before:-inset-*`; switch it to `tap-target`.
- `src/frontend/src/components/ui/model-missing-notice.tsx` -- an inline sentence link; allowlist it (WCAG 2.5.8 inline exception).
- `src/frontend/src/index.css` -- epic-owned; add the `tap-target` utility.
- `src/frontend/scripts/check-routes.mjs` -- the harness to copy (esbuild bundle to `node_modules/.cache`, FakeStorage, externals, `define`).
- `.github/workflows/frontend-ci.yml` -- append the steps.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/lib/shortcuts.ts` -- NEW. Exports:
  - `parseShortcut(key)` → `{ key, shift, mod, single, label[] }`. Throws on reserved keys. `Space` maps to `" "`; `Mod` displays as ⌘ on Apple platforms and Ctrl elsewhere.
  - `isTypingTarget(el)` and `isInteractiveTarget(el)`.
  - `matchesShortcut(parsed, event)`.
  - `registerShortcut({ key, scope, description, write?, overLayers?, allowRepeat?, handler })` → remover. It captures `layerCount()` at registration.
  - `dispatchShortcut(event, activeElement)` → boolean. It applies every guard in the Always rules, runs the newest match, and calls `preventDefault` when the shortcut fires.
  - `listShortcuts()` → enabled entries. `groupShortcuts(entries, pageTitle)` → `[{ scope, label, items }]`.
  - `subscribeShortcuts`, `getShortcutsVersion` (for `useSyncExternalStore`).
  - `singleKeyShortcutsEnabled()`, `setSingleKeyShortcutsEnabled(b)`, `suspendShortcuts()` → resume.
  - `useShortcut(key, { scope, description, enabled?, write?, overLayers?, allowRepeat? }, handler)`. It parses the key during render (so it throws early), keeps the handler in a ref and registers in `useEffect`.
  - A lazy document keydown listener while any shortcut is registered.
- `src/frontend/src/lib/slideOverRegistry.ts` + `src/frontend/src/components/SlideOver.tsx` -- add `push?: (o) => void` to `Registration` and set it from SlideOver. Fix the close button (`relative tap-target`) and the back button (`relative tap-target`).
- `src/frontend/src/components/shell/ShortcutHelp.tsx` -- NEW.
  - Exports `openShortcutHelp()`, `ShortcutList({ groups, previewing, enabled, onToggle })` (pure markup) and `ShortcutHelp`.
  - `ShortcutHelp` registers `?` (Global, "Show keyboard shortcuts", `overLayers`). It suspends other shortcuts while open. It pushes into the active SlideOver or else opens its own SlideOver titled "Keyboard shortcuts".
  - The list: per group a `<section aria-labelledby>` with an `h3` and a `<dl>` of `<kbd>` keys and descriptions. It shows the switch (`role="switch"`, `aria-checked`, min 44 px) and "Not available in preview" on write items while previewing.
- `src/frontend/src/App.tsx` -- mount `<ShortcutHelp />` inside the router, logged-in or not.
- `src/frontend/src/components/NavBar.tsx` -- touch fixes. Add a profile-menu item "Keyboard shortcuts" that focuses the avatar button, closes the dropdown and calls `openShortcutHelp()`.
- `src/frontend/src/index.css` -- `.tap-target::before` utility (`@media (max-width: 767.98px), (pointer: coarse)`).
- `src/frontend/src/components/ui/{button,input,combobox,visibility-badge,tabs,segmented-control}.tsx`, `components/shell/{CampaignSwitcher,PreviewBanner}.tsx`, `components/ThemeSelector.tsx` -- class-only touch-target fixes, as listed in the Code Map.
- `src/frontend/scripts/check-touch-targets.mjs` -- NEW, static audit.
  - Scope: the files listed in Always. Interactive elements are `button`, `a`, `Link`, `input`, `select`, `textarea`, `summary`, button.tsx's `Comp`, and any tag with an interactive `role`. `<Button>`/`<Input>` usages are skipped, because those primitives are audited where they are defined.
  - It resolves class strings from literals, same-file `const` strings and cva bases, and counts only classes with no breakpoint prefix (or with `max-md:`). Elements hidden at 375 px (`hidden`, `sr-only`) are skipped.
  - Pass: `tap-target` with a positioned class, or a height of at least 44 px (`h-`/`min-h-`/`size-` ≥ 11, or arbitrary px ≥ 44) and a width of at least 44 px (`w-`/`min-w-`/`size-` ≥ 11, `w-full`, `flex-1`).
  - Hover-only: fails on `hover:`/`group-hover:`/`peer-hover:` reveal classes (`opacity-100`, `visible`, `block`, `flex`, `inline-flex`) when the base hides the element (`opacity-0`, `invisible`, `hidden`).
  - It has an allowlist `[{ file, match, reason }]`, a `--self-test` against inline fixtures, and it prints the checklist.
- `src/frontend/scripts/check-shortcuts.mjs` -- NEW (harness from check-routes). Covers every matrix row through `dispatchShortcut` with fake events and elements, plus real `pushLayer`, the preview store and the toast state. It also covers `parseShortcut` refusals, the grouping and order, the register/remove lifecycle through `registerShortcut` (Node has no DOM, so `useShortcut`'s effect is exercised by the Playwright run), an SSR check that `useShortcut` throws on a reserved key during render, and an SSR of `ShortcutList`.
- `.github/workflows/frontend-ci.yml` -- add steps `node scripts/check-shortcuts.mjs`, `node scripts/check-touch-targets.mjs` and `node scripts/check-touch-targets.mjs --self-test`.

**Acceptance Criteria:**
- Given the built app with a mocked API in headless Chromium, when the user presses `?` on a page, then the help SlideOver opens with the Global group. When they press Esc, it closes and focus is back on the previously focused element.
- Given focus in the journal textarea or any input, when `?` is typed, then the character appears and the help does not open.
- Given a 375 px viewport (touch), when the nav, its open menus, the profile dropdown, the CampaignSwitcher, a SlideOver and the help render, then every visible interactive element measures ≥ 44×44, by its own box or its `tap-target` `::before`, and nothing scrolls horizontally.
- Given CI, when frontend-ci runs, then the build, `lint:tokens`, all existing checks and the two new checks pass. The PR description holds the touch-target checklist.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 51 findings — high 0, medium 4, low 34, false 13, maybe-false 0
- findings:
  - Blind Hunter
    - `[low]` `[patch]` ThemeSelector was only half fixed, and the file wasn't audited. Fixed: ThemeSelector.tsx is now in `auditedFiles()`, the non-compact select and the ↓/↑ buttons are fixed, and the icon buttons have aria-labels. Footer, ChatWidget and pages stay outside the story's named scope (`components/ui`, `components/shell`).
    - `[low]` `[reject]` On touch tablets of 768 px or wider, the `md:` resets shrink menu items below 44 px. The AC measures at 375 px, and tablet sizing (56 px) belongs to E4. Fixing it means changing every reset to a pointer media variant.
    - `[low]` `[reject]` The enlarged hit areas can overlap. They only grow controls that are smaller than 44 px. The h-7 Confirm/Cancel pair overlaps only when the row wraps (8 px). The back button grows over the non-interactive h2.
    - `[false]` `[reject]` Adding `relative`/`::before` to Button breaks absolute children or `overflow-hidden`/`before:` consumers. A grep of every `<Button` usage finds none with absolute children, overflow-hidden or before: utilities.
    - `[low]` `[reject]` Mod+Enter is blocked in textareas. The AC says no registered shortcut fires in an input or textarea, and the matrix test makes that explicit. E1 can reopen this if its checklist needs it.
    - `[low]` `[reject]` The help lists shortcuts that are silenced right now (under a layer, duplicates, or with the switch off). The switch shows its own state, and the AC asks for the registered list.
    - `[low]` `[reject]` The off switch doesn't sync across tabs. Toggling it in one tab while another is open is rare, and the fix adds a storage listener and another branch.
    - `[low]` `[patch]` Turning the switch off doesn't tell the user how to get back. Fixed: the hint now says "You can still open this list from the profile menu."
    - `[low]` `[reject]` useShortcut throws during render in production. This is deliberate (Design Notes and spec): a reserved key is a programmer error and should fail loudly in development. Parsing is cheap.
    - `[low]` `[reject]` The push bridge in the registry is loosely typed. No caller drifts today, and the registry is meant to have no React imports.
    - `[medium]` `[patch]` The help's open state is tracked only on the standalone path, so the profile menu can push a second help level. Fixed: a module-level count of mounted help content, and `show()` returns early while it is above zero.
    - `[low]` `[reject]` check-shortcuts misses some cases (enabled:false, Spacebar, F13…). enabled:false lives in the hook effect (covered by Playwright). The others are minor variants of tested rules.
    - `[low]` `[defer]` The static touch audit ignores padding and some size classes. It is conservative by design (padding fails), and rendered sizes are covered by the Playwright run. Grouped into the deferred "no rendered-size CI check" entry.
    - `[low]` `[reject]` Space can take over page scrolling. Space is in the spec's grammar for E4's "with nothing else focused" play/pause. It is refused on interactive targets.
    - `[false]` `[reject]` The spec isn't in the diff. It was left out of the review diff on purpose and is committed with the code.
  - Verification Gap
    - `[medium]` `[patch]` Pushing into an open SlideOver is untested. Fixed: `pushHelpIntoActiveSlideOver()` is extracted, and check-shortcuts activates a fake registration with a recording `push`.
    - `[medium]` `[patch]` The document listener attach/detach is never exercised. Fixed: a fake-document test counts keydown add/remove. Hook-effect wiring and the `?` options are covered by the Playwright run (no DOM runner).
    - `[low]` `[patch]` The ThemeSelector fix is outside the audit. Same entry as the Blind Hunter ThemeSelector row.
    - `[medium]` `[patch]` The profile menu can push a second help level. Same entry as the Blind Hunter open-state row.
  - Edge Case Hunter
    - `[low]` `[reject]` A shortcut that re-registers under a layer captures the higher depth. This is documented in Design Notes. It only happens when a page key changes its description or enabled flag while a layer is open.
    - `[low]` `[reject]` Numeric layer depth can attach a shortcut to an unrelated newer layer. This needs a nested layer to close beneath another, which the one-SlideOver rule prevents.
    - `[low]` `[reject]` A focused checkbox or radio blocks every shortcut. The AC and spec say "input", taken literally. It errs on the safe side.
    - `[low]` `[reject]` `?` with a non-SlideOver layer on top pushes the help under it. The only such layers are the nav and switcher menus, which close on focus loss and outside pointer.
    - `[low]` `[reject]` The switch doesn't sync across tabs. Same as the Blind Hunter row.
    - `[low]` `[reject]` A custom scope named like the page title or "Global" produces duplicate headings. This is a programmer naming choice, and no such scope exists.
    - `[low]` `[reject]` The help lists shortcuts that are blocked right now. Same as the Blind Hunter row.
    - `[low]` `[patch]` `parseShortcut(" ")` gives a blank key cap. Fixed: a literal space maps to Space.
    - `[low]` `[defer]` The audit unions classes from conditional branches. This is a static-audit limit, grouped into the deferred rendered-size entry.
    - `[low]` `[defer]` A conditional `hidden` skips a control. Same deferred entry.
    - `[low]` `[defer]` Conflicting sizes are maxed instead of twMerge order. Same deferred entry.
    - `[low]` `[defer]` min-h on an inline element is counted. Same deferred entry (no audited element does this today).
    - `[low]` `[defer]` w-full/flex-1 is treated as wide. Same deferred entry.
    - `[low]` `[reject]` tap-target is clipped by overflow-hidden. No audited tap-target element or ancestor clips it (the Playwright run measured the pseudo-element).
    - `[false]` `[reject]` tap-target collides with before: utilities. PreviewBanner's `before:` classes were removed in this change, and none remain on tap-target elements.
    - `[low]` `[reject]` Neighbouring tap-targets overlap. Same as the Blind Hunter overlap row.
    - `[false]` `[reject]` Expression roles aren't audited. No audited file sets `role={expr}` on an interactive element.
    - `[false]` `[reject]` JSX inside comments or strings creates phantom elements. The audit passes on the real files, and none are reported.
    - `[false]` `[reject]` `max-lg:` sizes are reported as failing. No audited file uses them.
    - `[low]` `[reject]` Matching the allowlist by substring could hide a new link. Any change to that file shows up in the checklist output and in review.
    - `[false]` `[reject]` Subdirectories of ui/ and shell/ aren't walked. Neither has any subdirectories.
    - `[low]` `[reject]` Input's `md:h-10` overrides a consumer's h-*. Only the combobox uses Input, and it passes no height.
    - `[false]` `[reject]` Button's `relative` moves absolute children. Same refutation as the Blind Hunter Button row.
  - Intent Alignment
    - `[low]` `[defer]` CI reads class strings, not rendered boxes. Deferred: there is no browser runner in CI, so a committed Playwright audit is the follow-up.
    - `[false]` `[reject]` The audit scope is wider or narrower than the AC. It covers `components/ui/*` and `components/shell/*` as the AC says, plus the epic-owned shell files.
    - `[false]` `[reject]` The checklist isn't in the PR. The PR description carries the script's checklist.
    - `[false]` `[reject]` "Current page" is not filtered by route. Registration follows mounting, so what is registered is what the current page has mounted.
    - `[false]` `[reject]` Esc with pushLayer. SlideOver calls pushLayer, and Esc closes only the help level (Playwright verified, both modes).
    - `[low]` `[reject]` No real write path exercises the preview guard. This story defines no write keys; the guard is unit-tested.
    - `[low]` `[reject]` Blocking typeahead widgets goes beyond the intent. It is a stricter "never while typing" and is in the spec.
    - `[low]` `[reject]` Extras beyond the intent (the 2.1.4 switch, suspension, repeat). These implement "don't override screen-reader keys" and come from the spec.
    - `[false]` `[reject]` Build and Playwright results aren't in the diff. They are recorded under Verification below.

## Design Notes

- **Layer depth rule.** `registerShortcut` records `layerCount()` when it registers. The dispatcher skips the entry when `layerCount()` is now higher, so page keys go quiet under a SlideOver or an open menu. A shortcut registered inside an open SlideOver (enabled by `open`) registers after that SlideOver's layout-effect `pushLayer`, so it sees its own layer and still fires.
- **Why push instead of replace.** The registry already enforces "one SlideOver at a time". If the help replaced an open review panel, it would close the user's work. Pushing gives the "← Back to …" header that EXPERIENCE.md already uses, and Esc then pops back.
- **Key grammar example:** `"?"`, `"j"`, `"Shift+A"`, `"/"`, `"+"`, `"Space"` and `"Mod+Enter"` are allowed; `"Mod+L"`, `"Alt+j"`, `"Escape"` and `"ArrowUp"` throw.

## Verification

**Commands:**
- `cd src/frontend && npm run build` -- expected: success
- `cd src/frontend && npm run lint:tokens && node scripts/check-ui-tokens.mjs --self-test && node scripts/check-semantic-fallback.mjs && node scripts/check-ui-primitives.mjs && node scripts/check-focus-trap.mjs && node scripts/check-spoiler-safety.mjs && node scripts/check-campaign-switcher.mjs && node scripts/check-routes.mjs && node scripts/check-shortcuts.mjs && node scripts/check-touch-targets.mjs && node scripts/check-touch-targets.mjs --self-test` -- expected: all pass

**Manual checks (if no CLI):**
- A throwaway Playwright run in the scratchpad: headless Chromium against `vite preview` with routed API mocks. It checks the shortcuts, help open/close with focus return (standalone and pushed into a SlideOver), no firing while typing, the off switch, the profile-menu entry, and the touch-target sizes plus no horizontal scroll at 375 px.

## Auto Run Result

Status: done

**Summary:**
- **`lib/shortcuts.ts`** is the shortcut registry, with one lazy document listener and `useShortcut(key, { scope, description, enabled?, write?, overLayers?, allowRepeat? }, handler)`.
  - The key grammar refuses Esc, Tab, arrows, Home/End/PageUp/PageDown, F1–F12, Backspace/Delete, plain Enter, any Alt combination, and any Mod combination except Mod+Enter.
  - Nothing fires while focus is in an input, textarea, select, contenteditable, a textbox role or a typeahead widget, or during IME composition.
  - A plain key never fires with Ctrl, Meta or Alt held. Space never fires on an interactive element.
  - Shortcuts go quiet under a layer opened after them, unless they are registered with `overLayers`.
  - `write` shortcuts show "Preview is read-only" during preview.
  - The single-key off switch (WCAG 2.1.4) is stored in `localStorage` as `lk_shortcuts`.
- **`components/shell/ShortcutHelp.tsx`** opens on `?`, or from the profile menu's "Keyboard shortcuts" item.
  - It shows a "Keyboard shortcuts" SlideOver (layer via `pushLayer`) with groups Global, then the page title, then other scopes. Keys are shown as `kbd` items in a `dl`.
  - It suspends other shortcuts while open.
  - If another SlideOver is open, it is pushed into it as a "← Back to …" level, so Esc goes back to that level and focus returns to where it was.
- **The `tap-target` utility** gives a centred hit area of at least 44×44 below md and on coarse pointers, with no visual change.
  - Undersized controls in ui/, shell/, SlideOver, NavBar and ThemeSelector were fixed.
  - **`scripts/check-touch-targets.mjs`** is the static audit. It checks the 44 px minimum and hover-only reveals, needs a reason for every allowlist entry, rejects stale entries, has a self-test, and prints the PR checklist. It runs in CI.

**Files changed:**
- `src/frontend/src/lib/shortcuts.ts`: registry, grammar, guards and hook (new)
- `src/frontend/src/components/shell/ShortcutHelp.tsx`: help overlay and `?` (new)
- `src/frontend/scripts/check-shortcuts.mjs`: 32 tests for the I/O matrix, registry, listener, push path and SSR (new)
- `src/frontend/scripts/check-touch-targets.mjs`: touch-target and hover-only audit (new)
- `src/frontend/src/lib/slideOverRegistry.ts` and `components/SlideOver.tsx`: `push` on the registration; close and back buttons get `tap-target`
- `src/frontend/src/index.css`: `tap-target` utility
- `src/frontend/src/App.tsx`: mounts `<ShortcutHelp />`
- `src/frontend/src/components/NavBar.tsx`: 44 px nav and profile items; "Keyboard shortcuts" menu item
- `src/frontend/src/components/ui/{button,input,combobox,visibility-badge,tabs,segmented-control}.tsx`, `components/shell/{CampaignSwitcher,PreviewBanner}.tsx`, `components/ThemeSelector.tsx`: class-only touch-target fixes (plus aria-labels on ThemeSelector's icon buttons)
- `.github/workflows/frontend-ci.yml`: three new steps

**Review:**
- 51 findings. Patches were applied for 7 rows, grouped into 6 entries:
  - medium: duplicate help push, push-path test, listener test
  - low: ThemeSelector audit and fixes, hint text, literal space key
- Deferred:
  - the static audit has no rendered-size CI check
  - SlideOver can't take initial focus when it is always mounted
- Rejected: every remaining row; the reasons are in the triage log.

**Follow-up review recommended:** true. Three medium entries were patched. Unverified risk: the help's duplicate-push guard and focus behaviour are checked only by the throwaway Playwright run, because there is no DOM runner in CI.

**Verification:**
- `npm run build` ok.
- `lint:tokens` 114/114. The token self-test, semantic-fallback, ui-primitives, focus-trap, spoiler-safety, campaign-switcher and routes checks all pass.
- check-shortcuts 32/32. check-touch-targets: 32 elements OK, and its self-test passes.
- Throwaway Playwright run, headless Chromium against `vite preview` with a mocked API: 55/55. It covered:
  - `?` opens the help with Global and `?`; Esc and Close close it; focus returns to the opener.
  - Ctrl/Meta/Alt+? do nothing; `?` over an open nav menu opens the help, and Esc closes only the help.
  - No firing in a textarea (the character is typed), an input, a select or a contenteditable, or during IME composition.
  - The help is pushed into an open NPC SlideOver: one dialog, a back button, Esc returns to the NPC level with focus on Close, and a second Esc closes it.
  - The off switch stores `lk_shortcuts=off` and `?` is ignored; the profile item still opens the help and focus returns to Profile.
  - At 375 px on a touch device, the nav, nav menu, switcher, profile dropdown, help and pushed-help header all measure at least 44×44 (own box or `::before`), with no horizontal scroll.

**Residual risks:**
- Content inside feature panels (NpcDetailPanel, QuestDetailPanel, pages) is outside this story's audit scope and still has controls under 44 px at 375 px.
- At 768 px and wider, the `md:` resets bring menu items back to their desktop height, even on touch tablets.

**Needs desktop verification:** none beyond the normal UI pass. Optional: `cd src/frontend && npm run dev`. Press `?` on a page and inside an open NPC panel. Type `?` in the journal, toggle the switch, and try VoiceOver on the help list.
