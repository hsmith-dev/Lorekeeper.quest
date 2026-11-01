---
title: 'E0-UX.2 Fix destructive-text contrast, migrate hardcoded colours, and gate them in CI'
type: 'bugfix'
created: '2026-10-31'
status: 'done'
baseline_revision: 'fc1806a9a15f2da98765b946e20d733d46fb2114'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** Error text uses `text-destructive`, whose dark-theme lightness (30-35%) gives about 1.7:1 on dnd `card`; 54 hardcoded `green/amber/red-*` classes ignore the theme; and nothing in CI stops either coming back.

**Approach:** Class-only migration: readable destructive text/icons move to `text-danger`; hardcoded colours move to the E0-UX.1 semantic tokens by meaning (washes `/14`, borders `/40`); the no-flag mode of `scripts/check-ui-tokens.mjs` becomes the CI-15 grep gate; `npm run lint:tokens` runs both modes in the frontend CI job.

## Boundaries & Constraints

**Always:** Map by meaning, not hue: success/approved/installed/saved -> `success`; "look before you trust"/duplicate/queued/ungrounded/model missing -> `warning`; error or failed/dead text and icons -> `danger`; the active voice-recording state -> `live` (DESIGN: live = recording only). `destructive` survives only as a fill (`bg-destructive`, `bg-destructive/NN`, `border-destructive/NN`) or `text-destructive-foreground` on a solid destructive fill. Drop `dark:` colour variants (tokens are theme-aware). Status that used colour alone gains a word or lucide icon. Keep `components/ui/button.tsx` (`write` prop) and `badge.tsx` variants and the E0-UX.6 components working unchanged. Scanner is dependency-free Node, scans `src/**/*.{ts,tsx}`, allowlist array exists but is empty, and every allowlist entry must carry a reason.

**Never:** Change layout, spacing, sizes or copy beyond the icon/word additions. Restyle Button/Badge/Card primitives. Migrate other palettes (`blue-*` etc.) that CI-15 does not name. Add npm dependencies. Edit `sprint-status.yaml` or `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Clean tree | migrated `src` | `check-ui-tokens.mjs` prints file count, exits 0 | none |
| Hardcoded class | `text-red-500`, `hover:bg-green-500/10`, `border-t-amber-400` | exit 1, `file:line:col` + offending class | non-zero exit |
| Destructive text | `text-destructive`, `hover:text-destructive/80` | exit 1 | non-zero exit |
| Destructive fg | `text-destructive-foreground` | passes | none |
| Colour literal | `style={{ color: "#fff" }}`, `background: "rgba(0,0,0,.5)"`, `bg-[#123456]`, `fill="#abc"` | exit 1 | non-zero exit |
| Token in style | `hsl(var(--danger))` in a style value | passes | none |
| Self-test | `--self-test` | scan of committed bad fixture must fail on every seeded line, contrast on a bad theme fixture must exit 1, clean fixture must pass; exits 0 when all hold | exit 1 naming the expectation that broke |

</intent-contract>

## Code Map

- `src/frontend/scripts/check-ui-tokens.mjs` -- `--contrast` mode done (E0-UX.1, `parseThemeFile`, `contrast`, `composite`); no-flag branch at file end is a stub to replace. Extend `--contrast` with `danger` vs `destructive/15` wash over `card` (error lines sit on `bg-destructive/10`; measured min 5.31:1 light).
- `src/frontend/package.json` -- scripts has only dev/build/preview; add `lint:tokens` exactly as the AC states.
- `.github/workflows/frontend-ci.yml` -- steps after `npm run build`; replace the lone `--contrast` step with `npm run lint:tokens`, add `--self-test` step.
- `src/frontend/src/components/TourOverlay.tsx:57,62` -- `rgba(0,0,0,0.65)` in inline `boxShadow`/`background`; move to `ring-[9999px] ring-black/65` and `bg-black/65` classes (same pixels).
- Hardcoded classes (54) in `components/JournalInput.tsx` (237,537,551,633,661), `components/ModelReadyBanner.tsx:30-32` ("⚠" text -> lucide `TriangleAlert`), `pages/AdminPage.tsx` (598,703), `CharactersPage.tsx:18-19`, `ChatPage.tsx` (53,128,380), `QuestsPage.tsx:10-11`, `RecordSessionPage.tsx` (212,290-292), `SettingsPage.tsx` (422,517).
- `text-destructive` text uses (63 + one `/80`) in 29 files, listed by `grep -rnE "text-destructive(?!-foreground)"`; badge/button `text-destructive-foreground` on fills stay.
- Faction tag `bg-destructive/15 text-destructive-foreground` in `components/JournalCard.tsx:10`, `pages/EntryDetailPage.tsx:18`, `pages/TimelinePage.tsx:14` -- not on a fill (light theme 1.16:1); text becomes `text-danger`.

## Tasks & Acceptance

**Execution:**
- `src/frontend/scripts/check-ui-tokens.mjs` -- implement grep mode (rules: hardcoded class incl. variant prefixes and sides, `text-destructive` not followed by `-foreground`, hex/`rgb(`/`rgba(`/numeric `hsl(` in Tailwind arbitrary values, style colour properties and SVG colour attributes); `--src-dir` override; `ALLOWLIST` (empty) of `{file, rule, reason}`; `--self-test`; danger-on-destructive-wash contrast row -- CI-15.
- `src/frontend/scripts/fixtures/ui-tokens/{bad,clean}/*.tsx`, `.../bad-theme/*.ts` -- committed fixtures for `--self-test` (outside `src`, so tsc/Vite ignore them) -- closes E0-UX.1 deferred item.
- 29 files with `text-destructive` -- `text-danger` (keep `hover:`/`/80` modifiers) -- AC1.
- 8 files with hardcoded classes + `TourOverlay.tsx` -- token classes per mapping; ModelReadyBanner and ChatPage "⚠" -> `TriangleAlert` (aria-hidden, `h-4 w-4`/`h-3 w-3` inline) -- AC2.
- JournalCard/EntryDetailPage/TimelinePage faction tag -- `text-danger` -- AC1 second clause.
- `src/frontend/package.json`, `.github/workflows/frontend-ci.yml` -- `lint:tokens` script and steps -- AC4.

**Acceptance Criteria:**
- Given the migrated tree, when `npm run lint:tokens` runs, then both modes exit 0 with an empty allowlist.
- Given a scratch `text-red-500` added to any `src` tsx file, when `npm run lint:tokens` runs, then it exits non-zero naming the file and line.
- Given dnd, when an error line renders on `card`, then `danger` measures >= 4.5:1 (6.76:1), and >= 4.5:1 on a `destructive/15` wash in every theme.
- Given Dashboard, Chat, Characters, Quests, Settings and Admin with a mocked API, when screenshotted before and after in dnd and light at 1280px and 375px, then only colours differ (no layout shift).

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 34 findings — high 0, medium 4, low 20, false 10, maybe-false 0
- findings:
  - `[low]` `[reject]` intent: AI-status dot uses `bg-danger`, story says red fills -> `destructive` — recorded Design Notes decision: an 8px indicator beside its word is an icon; dark `destructive` on `card` is 1.7:1, below the 3:1 non-text minimum.
  - `[false]` `[reject]` intent: recording button mapped to `live` not by hue — the caller asked for mapping by meaning; DESIGN reserves `live` for recording.
  - `[false]` `[reject]` intent: faction tag change is outside the 73 uses and affects role colours — AC1 second clause forbids `text-destructive-foreground` off a fill; light measured 1.16:1 before, now readable (screenshots). RoleBadge (E0-UX.6) is untouched.
  - `[false]` `[reject]` intent: opacity steps 6/14/45/55 vs `/40` — `/40` is a Tailwind default step and the story's own AC value.
  - `[false]` `[reject]` intent: TourOverlay is outside the named files — story's CI-15 rule covers `rgb(` in style colour properties and requires an empty allowlist.
  - `[false]` `[reject]` intent: no rendered evidence of "only colours moved" — Playwright before/after ran over 10 views x dnd/light x 1280/375 (40 shots): no size change, no element rect moved >0.5px.
  - `[low]` `[patch]` intent: scratch `text-red-500` failing the job not evidenced — grouped with verification-gap 2; self-test now spawns the CLI and asserts exit 1, and a scratch `src/zz-scratch.tsx` made `npm run lint:tokens` exit 1.
  - `[false]` `[reject]` edge: blue/other palettes not gated — story's CI-15 regex names green/amber/red only; intent excludes the rest.
  - `[low]` `[reject]` edge: ternary colour literals in style/SVG props escape — none in tree; matching expressions adds parser complexity.
  - `[low]` `[reject]` edge: style key and value on separate lines escape — same; unlikely, would need whole-file matching.
  - `[low]` `[reject]` edge: `rgb(var(--x))` flagged — tokens are HSL; no `rgb(var())` in tree; fails loudly rather than silently.
  - `[low]` `[patch]` edge: `fill="url(#fade)"` flagged as hex — lookbehind added for `url(`; clean fixture line proves it.
  - `[low]` `[reject]` edge: symlink loops in `src` — none exist; guard adds complexity.
  - `[low]` `[reject]` edge: missing fixtures dir gives a stack trace — still a non-zero exit; cosmetic.
  - `[low]` `[reject]` edge: stale allowlist entries not reported — allowlist is empty; adds a feature.
  - `[medium]` `[patch]` edge: danger checked on /15 destructive wash only, tree uses /20 hover — alpha raised to 0.20 (light 4.97:1, passes).
  - `[false]` `[reject]` edge: TriangleAlert may break the "no layout shift" claim — rect diff shows parent `<p>` boxes identical; only the banner heading text sits ~2px right, inherent to the AC's required icon.
  - `[low]` `[reject]` edge: header claims token refs pass but `rgb(var())` fails — grouped with the rgb(var()) row.
  - `[medium]` `[patch]` verification-gap: self-test cannot tell the destructive-wash rule from the card rule — added `wash-only-danger.ts` (fails only destructive/20 at 4.34:1, passes at /15) with an exact-one-failure assertion.
  - `[medium]` `[patch]` verification-gap: CLI dispatch/exit codes never exercised — self-test spawnSyncs the script (bad src -> 1, clean -> 0, bad themes -> 1).
  - `[low]` `[reject]` verification-gap other: per-line scan misses multi-line styles and colour constants — grouped with the edge multi-line row.
  - `[false]` `[reject]` blind: blue quest status not migrated — grouped with edge blue row.
  - `[low]` `[reject]` blind: `ring-black/65`/`bg-black/65` is still a fixed colour — black scrim matches the epic's documented `bg-black/40` SlideOver convention; story gates literals only.
  - `[medium]` `[patch]` blind: destructive-wash checked at one opacity — grouped with edge /20 row.
  - `[low]` `[reject]` blind: error states keep `/10`/`/30` next to success `/14`/`/40` — AC keeps destructive fills as they are; the wash rule applies to migrated hardcoded classes.
  - `[low]` `[reject]` blind: `bg-danger` status dot against AC — grouped with intent dot row.
  - `[low]` `[reject]` blind: allowlist matches whole file+rule — allowlist is empty; finer keys add surface.
  - `[low]` `[patch]` blind: self-test asserts less than fixture comment claims — grouped with verification-gap 1; comment and assertions now match.
  - `[low]` `[reject]` blind: named colours, custom-property keys, `[color:#fff]`, interpolated classes, CSS files escape — beyond CI-15's defined rules; none in tree.
  - `[low]` `[reject]` blind: CI ordering / contrast run twice — steps are in the same job after build, matching "next to"; duplication costs <1s.
  - `[low]` `[patch]` blind: summary says "hardcoded colour(s)" for destructive-text — now "token violation(s)".
  - `[low]` `[reject]` blind: faction/monster tags now use the error colour — monster was already `text-destructive` red; faction already sat on a destructive wash; AC1 dictates `text-danger`.
  - `[false]` `[reject]` harness flag: Settings theme select background darker — diff PNG shows only glyph antialiasing; compiled CSS diff touches no rule used by that select.
  - `[false]` `[reject]` harness flag: light warning hue amber -> tan and merged greens — values are E0-UX.1's DESIGN.md tokens, intended.

## Design Notes

Mapping examples: `text-green-600 bg-green-500/10 border-green-500/20` -> `text-success bg-success/14 border-success/40`; `text-amber-600 dark:text-amber-400` -> `text-warning`; recording `border-red-500 text-red-500 bg-red-500/10` -> `border-live text-live bg-live/14`; status dot `bg-green-500`/`bg-red-500` -> `bg-success`/`bg-danger` (an 8px indicator next to its word is treated as an icon, so it uses the readable token, not the dark `destructive` fill). Error branches already using `bg-destructive/10 border-destructive/30` keep the destructive fill and only swap text.

## Verification

**Commands:**
- `cd src/frontend && npm run lint:tokens && node scripts/check-ui-tokens.mjs --self-test` -- expected: exit 0.
- `cd src/frontend && npx tsc --noEmit && npm run build` and every `scripts/check-*.mjs` -- expected: pass.
- `grep -rnE "(green|amber|red)-[0-9]|text-destructive([^-]|$)" src/frontend/src` -- expected: no output.
- Playwright (scratchpad harness, not committed) screenshots before/after -- expected: diffs only in migrated colours.

## Auto Run Result

Status: done

**Summary:** Readable destructive text moved to `text-danger` (64 uses in 25 files, plus 3 faction tags that put `text-destructive-foreground` on a wash, 1.16:1 in light). 54 hardcoded green/amber/red classes mapped by meaning to `success`/`warning`/`danger`/`live` (washes /14, borders /40, red badge washes to `destructive/14`), `dark:` variants dropped. "⚠" glyphs replaced by lucide `TriangleAlert`. TourOverlay scrim moved from inline `rgba()` to `ring-black/65`/`bg-black/65`. `check-ui-tokens.mjs` no-flag mode is now the CI-15 gate (5 rules, empty allowlist that requires reasons, `--src-dir`); `--contrast` also checks `danger` on a destructive/20 wash; `--self-test` runs committed fixtures and spawns the CLI. `lint:tokens` added; CI runs it plus the self-test.

**Files changed:**
- `src/frontend/scripts/check-ui-tokens.mjs` -- grep gate, destructive-wash contrast row, self-test.
- `src/frontend/scripts/fixtures/ui-tokens/{bad,clean,bad-theme}/*` -- gate fixtures (outside `src`).
- `src/frontend/package.json` -- `lint:tokens`.
- `.github/workflows/frontend-ci.yml` -- `npm run lint:tokens` (replaces the lone contrast step) and `--self-test`.
- 29 files under `src/frontend/src/{components,pages}` -- class-only colour migration (+ TriangleAlert in ModelReadyBanner and ChatPage; TourOverlay classes).

**Review:** 34 findings (0 high, 4 medium, 20 low, 10 false). Patched 5 entries (2 medium: destructive-wash alpha + wash-only fixture, CLI exit path; 3 low: `url(#id)` false positive, summary wording, scratch-commit evidence). Deferred none. Rejected rows with reasons are in the triage log.

**Follow-up review:** recommended (two medium entries patched on a first pass). Unverified risk: the self-test's spawnSync assertions and the wash-only fixture ran only on local Node 26; CI uses Node 22.

**Verification:** `npm run lint:tokens` exit 0 (112 files, 114 contrast pairs; lowest light danger on destructive/20 4.97:1; dnd danger on card 6.76:1). `--self-test` OK. A scratch `src/zz-scratch.tsx` with `text-red-500` made `lint:tokens` exit 1. `npx tsc --noEmit` clean; `npm run build` ok; check-semantic-fallback, check-ui-primitives (25/25), check-focus-trap and check-spoiler-safety (24/24) pass; workflow YAML parses; the grep for `(green|amber|red)-N` and bare `text-destructive` in `src` returns nothing. Playwright headless Chromium with a mocked API, before/after builds: Dashboard, Chat, Characters, Quests, Settings, Admin (users/promo/feedback/platform/system) x dnd, light x 1280, 375 = 40 shots. No page size changed and no element rect moved > 0.5px; pixel diffs are only in status/error colours and the two icon swaps.

**Residual risks:** only dnd and light were screenshotted (arcane, highseas, forest and cyberpunk rely on the contrast script). States not captured: recording button, offline-queue/duplicate notices, RecordSessionPage, TourOverlay. Quests `active` still uses `blue-*` (outside CI-15). Sprint-status sync skipped per the orchestrator brief.
