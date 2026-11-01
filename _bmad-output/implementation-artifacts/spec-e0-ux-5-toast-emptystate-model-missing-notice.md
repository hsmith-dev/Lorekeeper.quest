---
title: 'E0-UX.5 Toast, EmptyState, ModelMissingNotice and shared state patterns'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '6d34034d98cd4707c17a8b3750a365e5dec99c4d'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
warnings: ['oversized']
deferred:
  - summary: >-
      scripts/check-ui-primitives.mjs is not run by any npm script or CI workflow.
    evidence: |-
      package.json has only dev/build/preview; .github/workflows has backend-tests, license-check and pages, none of which run check-ui-*.mjs. The same gap was deferred for check-ui-tokens.mjs in E0-UX.1; E0-UX.2 adds lint:tokens and the frontend CI job, which is the place to wire all three scripts.
    location: >-
      src/frontend/scripts/check-ui-primitives.mjs
    severity: medium
  - summary: >-
      Toaster DOM event wiring (pointer hover / focus pause) and responsive placement are not exercised by any check.
    evidence: |-
      The check script renders Toaster markup server-side and drives the store, but there is no DOM environment, so the ToastCard pointer/focus handlers and the md/phone placement were never run. Settling it needs a browser check (remote desktop unreachable this run) or a DOM test runner, which the story forbids adding.
    location: >-
      src/frontend/src/components/ui/toast.tsx
    severity: medium
---

<intent-contract>

## Intent

**Problem:** New expansion surfaces have no shared way to say "work finished", "nothing here yet", "the model is missing", "loading", "that failed" or "you're offline", so each page would invent its own (often with emoji or hardcoded colours).

**Approach:** Ship in-house primitives under `components/ui/` (toast with `<Toaster />` + `useToast()` + `setTitleBadge`, empty-state, model-missing-notice, skeleton, inline-error, offline-notice) plus `lib/format.ts` (`formatEta`, `entryTitle`), mount `<Toaster />` once in `App.tsx`, all styled with theme and E0-UX.1 semantic tokens only.

## Boundaries & Constraints

**Always:** Theme tokens and semantic tokens only (`text-danger`, `bg-warning/14`, `border-warning/40`, `bg-popover`); lucide icons, never emoji; visible `ring` focus; buttons ≥ 44px tall below `md`; sentence-case copy; `tsc` strict clean. Pulse only under `motion-safe:`. Toast z-index 70 via `z-[70]`. ModelMissingNotice admin link points to the existing install flow at `/admin?tab=system` (Admin → System → Model Library).

**Never:** No new npm dependency. Do not edit `tailwind.config.ts`, `index.css`, `SlideOver.tsx`, `lib/focusTrap.ts`, `components/ui/{button,combobox,segmented-control,tabs}.tsx` (sibling stories E0-UX.3/4). Do not migrate `ModelReadyBanner` or existing pages to the new primitives. No hardcoded `green|amber|red-*`, hex or `rgb(` colours. No frontend test runner. Don't edit `sprint-status.yaml` / `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Info toast | `toast({text, kind:"info"})` | shows; gone after 6 s | none |
| Undo toast | `kind:"undo"`, `action:{label:"Undo", onClick}` | 10 s; clicking action runs `onClick` then dismisses | none |
| Failure toast | `kind:"failure"` | persists until dismiss button | none |
| Hover / focus | pointer over or focus inside toast | timer pauses; resumes with remaining time on leave/blur | none |
| 4th toast | 3 shown (1 failure, 2 info) | oldest non-failure evicted | all 3 failures → oldest evicted |
| Announce | any toast | its text placed in the single `role="status"` polite region | repeat text re-announced |
| Title badge | `setTitleBadge(2)` then `setTitleBadge(0)` | `"(2) World · Lorekeeper"` then `"World · Lorekeeper"` | negative/NaN treated as 0 |
| ModelMissing admin | `{model:"speech model", feature:"Live captions", sizeLabel:"~1.5 GB"}`, admin | "The speech model isn't installed. An admin can add it in Admin › Models (~1.5 GB)." with link | none |
| ModelMissing non-admin | same, not admin | "The speech model isn't installed. Ask your admin." no link | profile loading → treated as non-admin |
| ModelMissing unreachable | `reachable={false}` | "The speech model isn't reachable." + admin link / "Ask your admin" | none |
| formatEta | 90 / 45 / 600 / 5400 / 0 / NaN | "about 1–2 min left" / "about 1 min left" / "about 10 min left" / "about 1–2 hours left" / "almost done" / "estimating time left" | never a bare number |
| entryTitle | `"The Ambush"` / `""` / `null` | `<em>The Ambush</em>` / `<em>Untitled entry</em>` | none |

</intent-contract>

## Code Map

- `src/frontend/src/App.tsx` -- mount `<Toaster />` once next to `<ChatWidget />` (inside providers so it can use tokens).
- `src/frontend/src/components/ui/button.tsx` -- read-only; reuse `Button`/`buttonVariants` (variants `outline`, `ghost`; size `sm`).
- `src/frontend/src/lib/utils.ts` -- `cn()` (tailwind-merge already knows the type roles).
- `src/frontend/tailwind.config.ts` -- read-only: semantic colours with `<alpha-value>`, opacity steps 6/14/45/55; z-index scale tops out at 50, so use `z-[70]`.
- `src/frontend/src/utils/apiError.ts` -- `apiErrorMessage(err, fallback)` for InlineError.
- `src/frontend/src/components/ModelReadyBanner.tsx` -- reference pattern: `useQuery(["me"], getMe)` for `is_admin`, link `/admin?tab=system`; leave unchanged.
- `src/frontend/src/pages/AdminPage.tsx:846-853` -- `?tab=system` deep-link opens the System tab containing the Model Library (line ~740).
- `src/frontend/src/services/api.ts:55` -- `getMe`.
- `src/frontend/src/hooks/useOfflineQueue.ts:53` -- existing `online` listener pattern.
- `src/frontend/scripts/check-semantic-fallback.mjs` -- precedent for a committed Node assert script (type stripping).

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/components/ui/toast.tsx` -- module store (`useSyncExternalStore`), `toast()`, `dismissToast()`, `setTitleBadge(n)`, `useToast()` returning `{ toast, dismiss, setTitleBadge }`, `<Toaster />` (fixed bottom-centre on phones, bottom-right `md`+, popover surface, max 3, eviction, per-kind timers with pause on hover/focus, one action + dismiss, one visually-hidden `role="status"` region) -- AC1, FR-2 substrate.
- `src/frontend/src/components/ui/empty-state.tsx` -- `EmptyState({ icon, children, action? })`: dashed `rounded-xl` border, `px-4 py-16`, 40px icon in `text-muted-foreground`, one sentence, optional single action element -- AC2.
- `src/frontend/src/components/ui/model-missing-notice.tsx` -- `ModelMissingNotice({ model, feature, sizeLabel?, reachable? })`: `border-warning/40 bg-warning/14`, `TriangleAlert` in `text-warning`, copy per matrix, admin via `["me"]` query -- AC3.
- `src/frontend/src/components/ui/skeleton.tsx` -- `Skeleton` (aria-hidden, `bg-muted`, `motion-safe:animate-pulse`, shape from className) -- AC4.
- `src/frontend/src/components/ui/inline-error.tsx` -- `InlineError({ error, onRetry?, fallback? })`: `role="alert"` `text-danger` line with icon and `apiErrorMessage` text (string errors shown as-is) and an outline "Retry" button; owns no form state -- AC4.
- `src/frontend/src/components/ui/offline-notice.tsx` -- `useOnlineStatus()` + `OfflineNotice` rendering "You're offline — changes are paused" with `WifiOff` on the warning wash only while offline -- AC4.
- `src/frontend/src/lib/format.ts` -- `formatEta(seconds)`, `entryTitle(title)` (uses `createElement`, file stays `.ts`) -- AC5.
- `src/frontend/src/App.tsx` -- import and mount `<Toaster />`.
- `src/frontend/scripts/check-ui-primitives.mjs` -- covers every I/O matrix row with `node:assert` (no test runner, no new dependency): bundles the new files to a temp dir with the already-installed `esbuild` (Vite's own dependency; `@/` alias → `src/`, externals `react`, `react-dom`, `@tanstack/react-query`, `react-router-dom`, `lucide-react`), then (a) drives the toast store API with `node:test` `mock.timers` (6 s / 10 s / persist, pause+resume remainder, eviction incl. all-failure case, announcement text and re-announce key, `setTitleBadge` on a stub `globalThis.document`), (b) renders `ModelMissingNotice` with `react-dom/server` `renderToStaticMarkup` inside `QueryClientProvider` (pre-seeded `["me"]` with `is_admin` true/false/absent) and `MemoryRouter`, asserting copy, link `href="/admin?tab=system"` and no link for non-admins, (c) asserts `formatEta` / `entryTitle` rows. For (a) the toast module must export its store operations (`toast`, `dismissToast`, `pauseToast`, `resumeToast`, `getToastState`, `setTitleBadge`) so the component's hover/focus handlers and the script use the same code path.

**Acceptance Criteria:**
- Given `<Toaster />` in `App.tsx`, when any module calls `toast(...)` or `useToast().toast(...)`, then the toast renders without any provider wrapper.
- Given a phone-width viewport, when a toast shows, then it is bottom-centre with 16px gutters and no horizontal scroll; at `md`+ it is bottom-right.
- Given the new files, when grepped for `(text|bg|border)-(green|amber|red)-\d`, hex or `rgb(`, then there are no matches.
- Given `EmptyState` / `ModelMissingNotice`, when rendered, then they contain no emoji and use lucide icons marked `aria-hidden`.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 38 findings — high 0, medium 6, low 22, false 10, maybe-false 0
- findings:
  - `[false]` `[reject]` blind: primitives have no callers — the story ships a substrate; adoption belongs to consumer stories (E0-Jobs.10, E4 etc.), and the spec bars migrating pages.
  - `[medium]` `[defer]` blind: check script not wired into npm/CI — matches E0-UX.1's deferral; E0-UX.2 owns lint wiring. Recorded in `deferred`.
  - `[medium]` `[patch]` blind: Toaster markup, action button, InlineError, EmptyState untested — added runToastAction, a Toaster render test, InlineError and EmptyState render tests (25/25 pass).
  - `[low]` `[reject]` blind: esbuild not a declared dependency — pinned through Vite in package-lock; `npm ci` is deterministic, and declaring it would be new dependency/licence work for a check script.
  - `[false]` `[reject]` blind: keyboard users can't reach timed toasts (WCAG 2.2.1) — the AC sets the 6 s/10 s durations and pause-on-focus explicitly.
  - `[false]` `[reject]` blind: failure toasts should be assertive — the AC requires one polite `role="status"` region.
  - `[low]` `[reject]` blind: action label not announced — the AC announces the text; adding the label changes the copy.
  - `[low]` `[reject]` blind: timers keep running in a hidden tab — adds a visibility listener and state for a rare case; the AC asks only for hover/focus pause.
  - `[low]` `[reject]` blind: toast overlaps ChatWidget button / no safe-area inset — toasts are short-lived and dismissible; an offset couples primitives to ChatWidget.
  - `[low]` `[patch]` blind: empty "Notifications" landmark always rendered — section now renders only with ≥ 1 toast; status region stays mounted.
  - `[low]` `[reject]` blind: `undo` allowed without action — a discriminated union adds API complexity; no caller yet.
  - `[low]` `[patch]` blind: action throwing leaves toast stuck — grouped with edge finding; `runToastAction` uses try/finally.
  - `[low]` `[reject]` blind: stale announcement replays on Toaster remount — Toaster mounts once in App.tsx; HMR-only.
  - `[low]` `[reject]` blind: setTitleBadge strips real "(1) " titles / needs re-applying — no titles start that way; re-apply contract documented for E0-UX.8.
  - `[low]` `[reject]` blind: formatEta has no days unit, < 15 s reads "almost done", boundaries untested — honest copy without a bare number; days branch is extra scope.
  - `[false]` `[reject]` blind: admin sees "An admin can add it" / label vs target mismatch — copy is AC-verbatim; the target is the mandated Admin → System → Model Library flow.
  - `[low]` `[reject]` blind: duplicated `["me"]` query, no role on notice — same key shares the cache; a shared hook is pre-existing debt outside this story.
  - `[false]` `[reject]` blind: offline copy "changes are paused" is untrue / navigator.onLine limits — copy is AC-verbatim; the offline queue already pauses journal writes.
  - `[low]` `[reject]` blind: InlineError has no pending prop / network errors lose cue — new public surface; not in AC.
  - `[low]` `[reject]` blind: EmptyState renders stray `0` — `action` is an element by contract; no caller passes numbers.
  - `[medium]` `[patch]` edge: InlineError crashes on FastAPI 422 array `detail` — non-string message now falls back to `fallback`/default text; tested.
  - `[low]` `[patch]` edge: `onClick={onRetry}` leaks MouseEvent into refetch — now `() => onRetry()`.
  - `[low]` `[reject]` edge: Error instances show generic fallback — apiErrorMessage behaviour is the shared contract; raw `Error.message` is often technical.
  - `[medium]` `[patch]` edge: touch tap fires mouseenter without mouseleave, pausing forever — switched to pointer events ignoring `pointerType === "touch"`.
  - `[low]` `[patch]` edge: action throwing keeps toast open — `runToastAction` try/finally; tested.
  - `[low]` `[reject]` edge: focus drops to body when a toast unmounts — focus-return logic adds state; rare.
  - `[low]` `[reject]` edge: eviction can remove a hovered toast — needs a 4th toast during hover; extra branch.
  - `[false]` `[reject]` edge: empty text toast — caller error; no caller passes empty text.
  - `[low]` `[patch]` edge: rAF suspended in hidden tabs delays announcements — now a 50 ms setTimeout with cleanup.
  - `[low]` `[reject]` edge: title prefix collision — same as the blind setTitleBadge row.
  - `[low]` `[reject]` edge: huge seconds yield "about 2778 hours left" — same as the blind formatEta row.
  - `[false]` `[reject]` edge: captive portal not detected as offline — AC specifies the offline notice, not connectivity probing; pre-existing platform limit.
  - `[false]` `[reject]` edge: AdminPage ignores tab change while mounted — the notice lives on feature pages, so following the link always mounts AdminPage fresh.
  - `[low]` `[reject]` edge: SIGINT leaves temp bundle dirs — rare; dirs live in node_modules/.cache.
  - `[medium]` `[patch]` verification-gap: Toaster/ToastCard wiring never run — same fix as the blind untested row; DOM hover/focus wiring deferred (no DOM runner allowed). Recorded in `deferred`.
  - `[medium]` `[defer]` verification-gap: script not in automated verification — same as the blind CI row.
  - `[false]` `[reject]` intent: all-failure eviction and optional `kind` exceed the AC — the eviction rule is needed to keep "at most 3", and both are recorded in the intent-contract matrix; a default `kind` is a superset.
  - `[false]` `[reject]` intent: formatEta "almost done"/"estimating", non-admin dropping size, extra feature line, tests not at the rendered surface — all are intent-contract matrix choices; rendered-surface gap is covered by the deferred browser check.

## Auto Run Result

Status: done

**Summary:** In-house Toast (module store + `<Toaster />` mounted once in App.tsx, `useToast()`, `toast()`, `setTitleBadge`, `runToastAction`), EmptyState, ModelMissingNotice (links admins to `/admin?tab=system`, the Model Library install flow), Skeleton, InlineError, OfflineNotice + `useOnlineStatus`, and `lib/format.ts` (`formatEta`, `entryTitle`). Semantic tokens only, lucide icons, no new dependency.

**Files changed:**
- `src/frontend/src/components/ui/toast.tsx` -- store, timers, eviction, pause/resume, live region, title badge, Toaster.
- `src/frontend/src/components/ui/empty-state.tsx` -- dashed empty-list panel.
- `src/frontend/src/components/ui/model-missing-notice.tsx` -- warning-wash notice with admin link.
- `src/frontend/src/components/ui/skeleton.tsx` -- content-shaped placeholder, motion-safe pulse.
- `src/frontend/src/components/ui/inline-error.tsx` -- `text-danger` error line with Retry.
- `src/frontend/src/components/ui/offline-notice.tsx` -- offline notice and hook.
- `src/frontend/src/lib/format.ts` -- `formatEta`, `entryTitle`.
- `src/frontend/src/App.tsx` -- mounts `<Toaster />`.
- `src/frontend/scripts/check-ui-primitives.mjs` -- 25 node:test checks covering every matrix row.

**Review:** 38 findings; patched 8 entries (3 medium, 5 low); deferred 2 entries (medium: CI wiring, DOM/browser check of Toaster); rejected the rest with reasons above.

**Follow-up review:** recommended. 3 medium entries were patched on a first pass. Unverified risk: the Toaster's pointer/focus pause handlers and its phone/`md` placement have never run in a real browser.

**Verification:** `node scripts/check-ui-primitives.mjs` 25/25 pass; `npx tsc --noEmit` clean; `npm run build` succeeds; `node scripts/check-ui-tokens.mjs --contrast` all 108 pairs pass; colour grep over new files finds nothing.

**Residual risks:** `rounded-xl` is Tailwind's 0.75rem, not `--radius` + 4px (needs `tailwind.config.ts`, out of scope). E0-UX.8 must call `setTitleBadge` again after setting route titles. Sprint-status sync skipped per the orchestrator brief.

## Design Notes

- `feature` appears as a short bold lead line ("Live captions is unavailable") above the AC sentence, so the notice names the feature it affects (EXPERIENCE.md) without altering the mandated sentence.
- Announcements: visible stack is a labelled `<section aria-label="Notifications">` (not live) so action/dismiss button labels aren't read; a separate `sr-only` `role="status" aria-live="polite"` node receives the newest text, cleared then set on the next frame so identical text re-announces.
- `setTitleBadge` strips any existing `^\(\d+\) ` prefix before applying, so it composes with route title changes made later by E0-UX.8 (which should call it again after setting a title).
- Timers: store `remaining` per toast; pause records elapsed; resume restarts with remainder.

## Verification

**Commands:**
- `cd src/frontend && node scripts/check-ui-primitives.mjs` -- expected: every check passes, exit 0 (and exit non-zero if any assertion fails).
- `cd src/frontend && npx tsc --noEmit` -- expected: no errors.
- `cd src/frontend && npm run build` -- expected: success.
- `cd src/frontend && node scripts/check-ui-tokens.mjs --contrast` -- expected: exit 0 (unchanged).
- `grep -nE "(text|bg|border|ring|fill|stroke)-(green|amber|red)-[0-9]|#[0-9a-fA-F]{3,8}\b|rgb\(" <new files>` -- expected: no matches.
