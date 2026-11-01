---
title: 'E0-UX.1 Semantic colour tokens and type roles in all six themes'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/DESIGN.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: []
deferred:
  - summary: >-
      The contrast check is not run automatically and its failing path has no committed fixture.
    evidence: |-
      No package.json script or workflow calls scripts/check-ui-tokens.mjs; the exit-1 path was only exercised with a scratch fixture (light gm 275 55% 70% -> exit 1). E0-UX.2 adds lint:tokens and the CI gate; add a committed failing fixture then.
    location: >-
      src/frontend/scripts/check-ui-tokens.mjs
    severity: medium
---

<intent-contract>

## Intent

**Problem:** New screens have no theme-stable colours for "safe", "careful", "hidden", "someone else's eyes", "live" and "error"; they misuse `primary`/`destructive`, whose meaning shifts per theme, and there are no shared type-role utilities.

**Approach:** Add six HSL tokens (`success`, `warning`, `info`, `gm`, `live`, `danger`) to `ThemeColors` and all six built-in themes with DESIGN.md frontmatter values, expose them in Tailwind with alpha support and the DESIGN.md opacity steps, fall back for custom themes in `ThemeContext`, add the type-role utilities, and add a dependency-free WCAG contrast script.

## Boundaries & Constraints

**Always:** Values are HSL triplets without `hsl()`, copied exactly from DESIGN.md frontmatter comments. Type roles take their family from `var(--font-heading)` / `var(--font-body)` (mono role uses the mono stack). No new npm dependency. `index.css` `:root` defaults gain the dnd values so no variable is unset before JS runs.

**Never:** Migrate existing hardcoded colour classes or `text-destructive` uses (E0-UX.2). Add the no-flag CI grep mode or the `lint:tokens` package.json script (E0-UX.2). Change `ThemeSelector` `REQUIRED_COLOR_KEYS` (new keys stay optional for imports). Edit `sprint-status.yaml` or `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Built-in theme | any of six themes | all six `--<token>` vars set to that theme's values | none |
| Dark custom theme missing keys | custom `background` lightness ≤ 50% | missing tokens take dnd values; present ones kept | none |
| Light custom theme missing keys | custom `background` lightness > 50% | missing tokens take light values | none |
| Unparseable custom `background` | e.g. `"oops"` | treated as dark (dnd fallback); no var left unset | no throw |
| Contrast pass | built-in themes | script prints table, exits 0 | none |
| Contrast fail | a token < 4.5:1 vs card, background or 14% wash over card | prints theme, token, surface and ratio; exits 1 | non-zero exit |

</intent-contract>

## Code Map

- `src/frontend/src/types/theme.ts` -- `ThemeColors` interface; add six required keys.
- `src/frontend/src/themes/{dnd,arcane,highseas,forest,cyberpunk,light}.ts` -- `colors` objects; append the six tokens in the existing aligned style.
- `src/frontend/src/contexts/ThemeContext.tsx:19` `applyTheme` -- loops `theme.colors` into `--<key>`; fallback goes before this loop. Custom themes come from `localStorage` `lorekeeper-custom-themes` and `ThemeSelector.validateTheme` (only checks the 19 legacy keys).
- `src/frontend/tailwind.config.ts` -- existing colours use `hsl(var(--x))` (no alpha); new ones must use `hsl(var(--x) / <alpha-value>)`. Add `opacity` extension `6, 14, 45, 55`.
- `src/frontend/src/index.css` -- `:root` defaults (dnd) and base typography; add token defaults and `@layer utilities` type roles.
- `src/frontend/scripts/` -- does not exist yet; `check-ui-tokens.mjs` lives here (E0-UX.2's `lint:tokens` runs `node scripts/check-ui-tokens.mjs` from `src/frontend`).
- DESIGN.md frontmatter `colors:` (HSL in comments) and `typography:` roles (entity-title 30px/1.2/700 heading, mobile 24px; quote 14px/1.55 body italic; mono 12px/1.4; caption-live 20px/1.5; caption-table 36px/1.3/500; recap-table 32px/1.45).

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/types/theme.ts` -- add `success`, `warning`, `info`, `gm`, `live`, `danger` (string) -- typed tokens for every theme.
- `src/frontend/src/themes/*.ts` (six files) -- set the six tokens to DESIGN.md values -- AC1.
- `src/frontend/src/themes/semantic.ts` -- export `SEMANTIC_TOKEN_KEYS` and `withSemanticFallback(colors, darkFallback, lightFallback)` (lightness parse of `background`; only `import type`, no runtime imports, so Node can run it directly with type stripping) -- keeps the rule unit-sized and testable without a test runner.
- `src/frontend/src/contexts/ThemeContext.tsx` -- in `applyTheme`, before the loop, call `withSemanticFallback(theme.colors, dndTheme.colors, lightTheme.colors)` -- AC3.
- `src/frontend/tailwind.config.ts` -- add six colours with `<alpha-value>` and the opacity steps -- AC2.
- `src/frontend/src/index.css` -- `:root` dnd defaults for the six vars; utilities `text-entity-title` (24px, 30px at `md`), `text-quote`, `font-mono-tabular`, `text-caption-live`, `text-caption-table`, `text-recap-table` -- AC5.
- `src/frontend/scripts/check-ui-tokens.mjs` -- `--contrast` mode: regex-parse `themes/*.ts` HSL triplets, HSL→sRGB, WCAG luminance, check each token vs card, background, and `0.14·token + 0.86·card`; non-zero on failure naming theme/token/surface/ratio. Optional `--themes-dir <dir>` (default `src/themes` next to the script) so a failing fixture can be checked. Without flags: print that the grep check arrives in E0-UX.2 and exit 0 -- AC4.

**Acceptance Criteria:**
- Given `text-success`, `bg-gm/14`, `border-warning/40` or `bg-gm/6` in a source file, when Tailwind builds, then the CSS uses `hsl(var(--x) / <alpha>)` with alpha 1, 0.14, 0.4, 0.06.
- Given a page using the six type-role classes, when built, then the CSS rules exist with the DESIGN.md sizes and families from `var(--font-*)` only.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 31 findings — high 0, medium 6, low 19, false 6, maybe-false 0
- findings:
  - `[low]` `[patch]` edge: theme without parseable `card` silently skipped (check-ui-tokens.mjs:101) — filter removed; now fails with `<id>: surface "card" is missing`, checked with a fixture.
  - `[low]` `[reject]` edge: malformed numbers like `1.2.3` give NaN ratios that pass — theme files are hand-written triplets; fix adds a guard for an unlikely input.
  - `[low]` `[reject]` edge: S/L over 100% computes wrong ratios — unlikely in hand-written themes; guard adds complexity.
  - `[low]` `[reject]` edge: a later duplicate key in the file overwrites the token — no theme file has non-colour HSL strings today; scoping the parser is extra complexity.
  - `[low]` `[reject]` edge: `--themes-dir` without `--contrast` exits 0 — no-flag mode is a documented stub until E0-UX.2.
  - `[low]` `[reject]` edge: non-HSL custom token value kept, yielding invalid CSS — same behaviour as the 19 legacy keys; the AC covers missing keys only; validation is a new guard.
  - `[false]` `[reject]` edge: fallback chosen by background lightness can miss contrast on custom surfaces — the AC prescribes exactly the background-lightness rule.
  - `[false]` `[reject]` edge: font-mono-tabular uses a literal font stack — the AC's var(--font-*) rule covers heading/body roles; DESIGN.md mono role is a literal stack.
  - `[medium]` `[patch]` blind: tailwind-merge drops `text-entity-title` etc. when merged with a colour class — confirmed (`twMerge("text-entity-title text-primary")` -> `text-primary`); `cn` now uses extendTailwindMerge with the five roles in the font-size group.
  - `[low]` `[patch]` blind: contrast checker skips themes without `card` — grouped with edge finding 1; same fix.
  - `[low]` `[reject]` blind: parser not scoped to `colors` object — grouped with edge duplicate-key finding; unlikely today.
  - `[low]` `[reject]` blind: fallback keeps invalid custom values — grouped with edge non-HSL finding.
  - `[low]` `[reject]` blind: `as ThemeColors` return cast hides missing legacy keys — the only caller passes a full Theme; negligible.
  - `[false]` `[reject]` blind: custom themes get no contrast guarantee — fallback rule is the one the AC specifies.
  - `[low]` `[reject]` blind: nothing runs the contrast check in CI — the intent assigns CI gating to E0-UX.2.
  - `[medium]` `[patch]` blind: fallback logic and failure path have no committed checks — grouped with verification-gap 1; added scripts/check-semantic-fallback.mjs (failing-path part deferred, see verification-gap 2).
  - `[false]` `[reject]` blind: popover/muted/6% surfaces not checked — the AC defines the three surfaces.
  - `[low]` `[patch]` blind: entity-title letter-spacing on mobile not in DESIGN.md — mobile rule now `letter-spacing: normal` (overrides h1-h6 base), 0.04em at md+.
  - `[false]` `[reject]` blind: light `live` equals `danger` — values are mandated verbatim by DESIGN.md.
  - `[low]` `[patch]` blind: `--radius` alignment whitespace change — restored.
  - `[low]` `[patch]` blind: duplicate theme imports in ThemeContext — now uses the `../themes` barrel.
  - `[medium]` `[patch]` verification-gap: withSemanticFallback untested — added scripts/check-semantic-fallback.mjs (node:assert, Node >= 22.18), passes.
  - `[medium]` `[defer]` verification-gap: contrast check not automated, failing path uncommitted — wiring belongs to E0-UX.2; recorded in `deferred`.
  - `[low]` `[patch]` verification-gap other: card-missing theme skipped — grouped with edge finding 1.
  - `[medium]` `[patch]` intent: fallback runtime behaviour unverified — grouped with verification-gap 1.
  - `[medium]` `[defer]` intent: failing path never triggered by committed code — grouped with verification-gap 2.
  - `[low]` `[reject]` intent: index.css :root copy of dnd values not checked by the script — values match today; checking CSS adds a second parser.
  - `[false]` `[reject]` intent: Tailwind classes unexercised — the auditor and implementer compiled them and confirmed `hsl(var(--x) / 0.NN)` output.
  - `[low]` `[reject]` intent: type-role rendering unverified — CSS rules inspected in build output; no UI consumer yet.
  - `[low]` `[reject]` intent: no-flag stub exits 0 — documented placeholder until E0-UX.2.
  - `[low]` `[patch]` intent: `--radius` whitespace — grouped with blind whitespace finding.

## Design Notes

Lightness parse: take the third whitespace-separated part of `background`, strip `%`, `parseFloat`; `NaN` → dark. Mobile-first `text-entity-title`: 24px base, 30px inside `@media (min-width: 768px)` (Tailwind `md`). `font-mono-tabular` uses the DESIGN.md mono stack (a code face, not a heading/body role) plus `font-variant-numeric: tabular-nums`.

## Verification

**Commands:**
- `cd src/frontend && node scripts/check-ui-tokens.mjs --contrast` -- expected: exit 0, all 6×6×3 pairs ≥ 4.5.
- Scratch fixture: copy `src/themes/*.ts`, lower one token (e.g. light `gm` to `275 55% 70%`), run `node scripts/check-ui-tokens.mjs --contrast --themes-dir <fixture>` -- expected: exit 1 naming `light`, `gm`, surface and ratio.
- Scratch `node` script importing `src/themes/semantic.ts` (Node type stripping) -- expected: dark custom (`background` `220 10% 8%`) missing keys gets dnd values; light custom (`40 30% 96%`) gets light values; `"oops"` background gets dnd values; present custom keys are kept; result has all six keys.
- `cd src/frontend && npx tsc --noEmit` -- expected: no errors.
- `cd src/frontend && npm run build` -- expected: success; grep built CSS for the AC1 sample classes when used in a scratch check.

## Auto Run Result

Status: done

**Summary:** Six semantic tokens (`success`, `warning`, `info`, `gm`, `live`, `danger`) added to `ThemeColors` and all six themes with DESIGN.md values; alpha-aware Tailwind colours plus opacity steps 6/14/45/55; custom-theme fallback (dnd if background L <= 50%, else light) before `applyTheme`'s loop; six type-role utilities; dependency-free WCAG contrast script.

**Files changed:**
- `src/frontend/src/types/theme.ts` -- six new required keys.
- `src/frontend/src/themes/{dnd,arcane,highseas,forest,cyberpunk,light}.ts` -- token values.
- `src/frontend/src/themes/semantic.ts` -- `SEMANTIC_TOKEN_KEYS`, `withSemanticFallback`.
- `src/frontend/src/contexts/ThemeContext.tsx` -- fallback before CSS-variable loop.
- `src/frontend/tailwind.config.ts` -- colours with `<alpha-value>`, opacity steps.
- `src/frontend/src/index.css` -- `:root` token defaults, type-role utilities.
- `src/frontend/src/lib/utils.ts` -- `cn` registers type roles as font sizes in tailwind-merge.
- `src/frontend/scripts/check-ui-tokens.mjs` -- `--contrast` mode (no-flag mode is a stub for E0-UX.2).
- `src/frontend/scripts/check-semantic-fallback.mjs` -- fallback assertions.

**Review:** 31 findings; patched 9 rows (6 entries: 2 medium, 4 low); deferred 1 entry (2 rows, medium); rejected 20 rows with reasons in the triage log.

**Follow-up review:** recommended (2 medium entries patched on a first pass). Unverified risk: the `cn` change (extendTailwindMerge) affects every component's class merging and was checked only with scratch calls, not in the rendered UI.

**Verification:** `node scripts/check-ui-tokens.mjs --contrast` exit 0, 108/108 pairs (min highseas live on wash 4.84:1); scratch fixture (light gm 275 55% 70%) exit 1 naming light/gm/surface/ratio; `node scripts/check-semantic-fallback.mjs` pass; `npx tsc --noEmit` clean; `npm run build` succeeds.

**Residual risks:** custom themes may carry invalid token strings (not validated); contrast and fallback checks are not yet in CI (E0-UX.2); `check-semantic-fallback.mjs` needs Node >= 22.18 (CI pins Node 20). Sprint-status sync skipped per the orchestrator brief.

