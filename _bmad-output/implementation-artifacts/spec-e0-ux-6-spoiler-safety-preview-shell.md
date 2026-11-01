---
title: 'E0-UX.6 Spoiler-safety components and the Preview shell'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '35cf71b22900cb06f3a79dbb6350a8bb2680ee6f'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/DESIGN.md'
warnings: [oversized]
deferred:
  - summary: >-
      Backend CORS allow_headers omits X-Lorekeeper-Preview, so cross-origin deploys would fail preflight once preview is reachable.
    evidence: |-
      src/backend/app/main.py:73 allow_headers=["Authorization", "Content-Type"]. Same-origin (nginx/Vite proxy) is unaffected; preview has no entry point in E0-UX.6. Backend is out of this story's scope; belongs with E0-Access.3 / E7.7.
    location: >-
      src/backend/app/main.py:73
    severity: medium
  - summary: >-
      Direct fetch() calls (useChat.ts streaming, AdminPage.tsx model install, future lib/sse.ts) do not send the preview header.
    evidence: |-
      Only the axios interceptor in services/api.ts adds it. E7.7 AC names lib/sse.ts and the interceptor; chat streaming in preview would be GM-scoped until wired.
    location: >-
      src/frontend/src/hooks/useChat.ts:65
    severity: medium
  - summary: >-
      No automated check that NavBar/SlideOver/ChatPage read the --lk-preview-offset variable PreviewBanner sets, or that App mounts the banner.
    evidence: |-
      renderToStaticMarkup does not run effects and the repo has no DOM/browser test runner; covered only by the scratchpad Playwright harness. Add a browser check when E0-UX.7/E7.7 make preview reachable.
    location: >-
      src/frontend/src/components/shell/PreviewBanner.tsx
    severity: medium
---

<intent-contract>

## Intent

**Problem:** GMs have no consistent way to see what is hidden from Players, and there is no "Preview as Player" mode, so later epics (World, Portal, Review Checklist, E7.7) have no shared spoiler-safety vocabulary or preview shell to build on.

**Approach:** Add five presentational primitives in `components/ui` (VisibilityBadge, SecretField, FieldVisibilityHint, RoleBadge, Button `write` prop), a tab-scoped preview store (`lib/preview.ts`) with `usePreview()`/`useWriteGuard()` in `contexts/PreviewContext.tsx`, a `PreviewBanner` mounted above the nav, and the `X-Lorekeeper-Preview: member` request header on axios requests while preview is active. Nothing in this story calls `enter()`, so the mode is unreachable in the UI until E0-UX.7 and E7.7.

## Boundaries & Constraints

**Always:** Theme and semantic tokens only (`bg-gm/14`, `border-gm/50`, `bg-gm/6`, `bg-info/14`, `bg-info`); lucide icons with `aria-hidden`; visible `ring` focus; sentence-case copy, verbatim from the AC; `tsc` strict clean. Any Esc-dismissable widget registers with `pushLayer` (`lib/layers.ts`). Comments state that hiding is cosmetic and data hiding is server-side (AD-13). Preview state lives in `sessionStorage` (per tab), all storage access in try/catch.

**Never:** Esc exits preview (the banner registers no layer). Client-side hiding treated as the access control. New npm dependencies. Changes to the backend, `useChat.ts` streaming `fetch`, or `lib/sse.ts` (E0-Jobs.9/E7.7). Hardcoded colours. Wiring an "enter preview" entry point (E0-UX.7 / E7.7). Edits to pages beyond the one-class offsets below.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Badge GM read-only | `value="gm"` | Pill: Lock + "GM only", `bg-gm/14 text-gm` | -- |
| Badge editable → Party | `editable`, value `gm`, pick Party | Inline "Players will see this. Make visible?" with "Make visible"/"Cancel"; `onChange("party")` only on confirm | Cancel/Esc: no call, focus back to badge |
| Badge editable → GM only | value `party`, pick GM only | `onChange("gm")` at once | -- |
| Badge Private option | `allowPrivate` false | Menu offers only Party, GM only (Private still shown if it is the current value) | -- |
| Badge for Player | `audience="player"` | Renders nothing | -- |
| Badge own journal | `audience="player" ownJournal` | "Shared" (Eye) if `shared` or value `party`, else "Private" (UserRound, info wash) | -- |
| SecretField GM | label "GM notes" | Dashed `border-gm/50`, `bg-gm/6`, visible label "GM notes · GM only" + Lock; accessible name starts "GM only" | -- |
| SecretField hidden | preview active or `audience="player"` | Renders nothing | -- |
| Hint | GM focuses wrapped field / blurs | "Visible to players" + Eye shown / hidden; wired by `aria-describedby` | Player/preview: children only |
| RoleBadge | `gm`/`co_gm`/`player` | Muted pill "GM"/"Co-GM"/"Player" | -- |
| Preview store | `enter("c1")`, reload tab | `active` true, campaignId `c1` after reload; `exit()` clears | Storage throws: in-memory only, no crash |
| Write guard | preview active | `useWriteGuard()` = `{disabled:true,title:"Preview is read-only"}`; `<Button write>` disabled with that title | Inactive: `{disabled:false}`, Button unchanged |
| Header | preview active | axios requests carry `X-Lorekeeper-Preview: member`; none when inactive | -- |

</intent-contract>

## Code Map

- `src/frontend/src/lib/layers.ts` -- `pushLayer(onEscape)` returns remover; Esc runs top only, skips `defaultPrevented`.
- `src/frontend/src/components/ui/button.tsx` -- cva Button; add `write?: boolean` consuming `useWriteGuard()`.
- `src/frontend/src/components/ui/segmented-control.tsx` -- roving-focus + arrow-key pattern to mirror in the badge menu.
- `src/frontend/src/components/ui/badge.tsx` -- existing pill shape (`rounded-full border px-2.5 py-0.5 text-xs font-semibold`).
- `src/frontend/src/services/api.ts:11` -- axios request interceptor (auth header); add preview header here.
- `src/frontend/src/App.tsx` -- mount `<PreviewBanner/>` before `<NavBar/>`, inside `QueryClientProvider`.
- `src/frontend/src/components/NavBar.tsx:211` -- `sticky top-0 z-50`; offset by `--lk-preview-offset`.
- `src/frontend/src/components/SlideOver.tsx:216` -- panel `fixed inset-y-0 z-50`; offset top by `--lk-preview-offset` so the banner (z 60) never hides its header.
- `src/frontend/tailwind.config.ts` -- alpha-aware `gm`/`info`; opacity steps 6/14/45/55; no z 60 step → `z-[60]`.
- `src/frontend/scripts/check-ui-primitives.mjs` -- esbuild + node:test + `renderToStaticMarkup` pattern to copy.
- `.github/workflows/frontend-ci.yml` -- add a step for the new check script.
- `src/frontend/src/types/index.ts:43` -- Campaign ids are `string`.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/lib/preview.ts` -- NEW: storage key `lk-preview`, `PREVIEW_HEADER`, `getPreviewCampaignId`, `setPreviewCampaignId`, `subscribePreview`, `previewHeaders()` -- non-React store shared by hook and interceptor.
- `src/frontend/src/contexts/PreviewContext.tsx` -- NEW: `usePreview()` (`useSyncExternalStore`; `enter`/`exit` also clear the react-query cache when a client is in context), `useWriteGuard()`, `PREVIEW_READ_ONLY_TITLE`.
- `src/frontend/src/components/shell/PreviewBanner.tsx` -- NEW: `h-10 sticky top-0 z-[60] bg-info`, text `text-card`, AC copy, inverted outline "Exit preview" button (44px hit area below `md`); sets `--lk-preview-offset: 40px` on `<html>` while active.
- `src/frontend/src/components/ui/visibility-badge.tsx` -- NEW: badge + menu (`aria-haspopup="menu"`, `menuitemradio`, arrows/Home/End, Enter/Space, Tab/outside click close, `pushLayer`) + inline Party confirmation.
- `src/frontend/src/components/ui/secret-field.tsx`, `field-visibility-hint.tsx`, `role-badge.tsx` -- NEW per matrix.
- `src/frontend/src/components/ui/button.tsx` -- add `write` prop.
- `src/frontend/src/services/api.ts` -- merge `previewHeaders()` in the request interceptor.
- `src/frontend/src/App.tsx`, `NavBar.tsx`, `SlideOver.tsx` -- mount banner; one-class top offsets.
- `src/frontend/scripts/check-spoiler-safety.mjs` + `.github/workflows/frontend-ci.yml` -- NEW check covering the matrix via SSR markup and store calls; CI step.

**Acceptance Criteria:**
- Given preview is active, when any route renders, then the banner is the topmost band (z 60) above the sticky nav, and pressing Esc (also with a SlideOver open, which closes) leaves preview on.
- Given preview is active, when the tab reloads or navigates, then the banner is still shown; a new tab starts without preview.
- Given the check script and Playwright harness, when they run, then every matrix row passes.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 38 findings — high 0, medium 12, low 23, false 3, maybe-false 0
- findings:
  - Blind Hunter
    - `[medium]` `[defer]` CORS allow_headers rejects X-Lorekeeper-Preview cross-origin — real at src/backend/app/main.py:73; backend out of scope and preview unreachable; deferred.
    - `[medium]` `[patch]` blocked write Button never shows its title (disabled:pointer-events-none) — added `disabled:pointer-events-auto cursor-not-allowed` when blocked.
    - `[medium]` `[patch]` `<Button write asChild>` not guarded — aria-disabled, tabIndex -1, preventDefault on click capture and bubble when blocked.
    - `[medium]` `[patch]` preview state survives logout — setPreviewCampaignId(null) in NavBar logout, useAuth logout and the api.ts 401 handler.
    - `[false]` `[reject]` stored campaignId unused / header lacks campaign — RC-7 fixes the header value as `member`; tying preview to a campaign route is E0-UX.7/E7.7.
    - `[low]` `[patch]` ChatPage fixed mobile sidebar `top-14` sits under the nav in preview — offset by --lk-preview-offset (grouped with edge-case ChatPage height).
    - `[low]` `[reject]` Exit preview clickable over modals; TutorialWelcomePrompt (z-110) covers banner — design z-order puts the banner above SlideOver on purpose; the onboarding prompt is a deliberate full-screen modal; rare.
    - `[low]` `[patch]` 40px offset duplicated vs h-10 — offset is now 2.5rem, matching h-10 (grouped with edge-case rem finding).
    - `[medium]` `[patch]` keyboard/confirm matrix rows untested in CI — extracted pure `visibilityChoice` and tested it in check-spoiler-safety.mjs (group: tests).
    - `[low]` `[patch]` confirmation never dismisses; stale after outside value change — closes on outside pointerdown / focus leaving; resets on value change (group: confirm state).
    - `[low]` `[patch]` editable without onChange shows a dead menu — renders the read-only pill (group: no-onChange).
    - `[low]` `[reject]` writes not blocked client-side unless opted in — by design: server 404s writes under the header (RC-7); client guard is cosmetic (AD-13); blanket blocking would break POST reads such as chat.
    - `[low]` `[reject]` cache reset only happens via the hook — only the hook enters/exits preview; the direct store calls added on logout also navigate to /login with auth cleared.
    - `[medium]` `[defer]` streaming calls are an unticketed gap — recorded in deferred; api.ts comment now names direct fetch calls.
  - Intent Alignment
    - `[false]` `[reject]` lib/preview.ts and the header belong to E7 per the boundary map — the dispatcher explicitly asked for request-header plumbing in this story, kept inert.
    - `[low]` `[reject]` resetQueries instead of E7.7's clear() — resetQueries also refetches active observers so no stale GM data stays rendered; E7.7 may revisit.
    - `[low]` `[patch]` banner foreground uses text-card where DESIGN.md says background — switched to background tokens.
    - `[low]` `[reject]` second banner sentence is sr-only below sm — needed to fit 375px without horizontal scroll; full copy still announced.
    - `[false]` `[reject]` PreviewContext has no Provider — AC requires only the usePreview export; a module store lets the interceptor share state.
    - `[medium]` `[patch]` tests exercise static markup, not interaction — group: tests.
  - Verification Gap
    - `[medium]` `[patch]` Party-confirm gate and hint toggle untested — group: tests; `visibilityChoice` tests added; hint toggle covered by the Playwright run only.
    - `[medium]` `[defer]` preview offset contract (banner var vs NavBar/SlideOver) unchecked — needs a DOM/browser runner the repo lacks; deferred.
  - Edge Case Hunter
    - `[low]` `[reject]` unknown value crashes the LOOKS lookup — prop is a typed union; no API wiring yet.
    - `[low]` `[patch]` value changes while menu/confirm open — group: confirm state.
    - `[low]` `[patch]` hidden confirm layer swallows Esc after tabbing away — group: confirm state.
    - `[low]` `[patch]` editable without onChange — group: no-onChange.
    - `[medium]` `[patch]` asChild write not guarded — same fix as the Blind Hunter row.
    - `[medium]` `[patch]` blocked tooltip never shows — same fix as the Blind Hunter row.
    - `[low]` `[patch]` px offset vs rem height under font scaling — offset 2.5rem.
    - `[low]` `[patch]` ChatPage height calc overflows by 40px in preview — subtracted the offset.
    - `[low]` `[reject]` Exit unreachable by keyboard inside an open SlideOver trap — Esc closes the panel first, then the banner is reachable.
    - `[low]` `[reject]` non-react-query state survives enter() — the data path is E7.7's.
    - `[low]` `[reject]` enter("") acts as exit — typed string API; no caller passes empty ids.
    - `[low]` `[patch]` AdminPage fetch missing from the not-covered comment — comment now names direct fetch calls.
    - `[low]` `[reject]` hint child might not forward aria-describedby — documented contract: a single field element.
    - `[low]` `[reject]` hint stays visible if the focused field unmounts — rare; would need extra tracking.
    - `[low]` `[reject]` duplicated tab copies sessionStorage — browser behaviour; recorded as a residual risk.
    - `[medium]` `[patch]` check claims every matrix row — group: tests; interaction rows also covered by the scratchpad Playwright run.

## Design Notes

`shared` is only meaningful on a Player's own journal (a private entry shared with the party); GM views ignore it. Badge `audience` defaults to `"gm"` but is forced to `"player"` while preview is active, so GM previews see the Player rendering. Header is sent on every axios request while active: the contract says it can only narrow and is ignored outside GM campaign routes, so blanket sending is safe; until E0-Access honours it the server serves GM data, which is why nothing enters preview yet.

## Verification

**Commands:**
- `cd src/frontend && npx tsc --noEmit` -- expected: no errors
- `cd src/frontend && npm run build` -- expected: success
- `cd src/frontend && node scripts/check-ui-tokens.mjs --contrast && node scripts/check-semantic-fallback.mjs && node scripts/check-ui-primitives.mjs && node scripts/check-focus-trap.mjs && node scripts/check-spoiler-safety.mjs` -- expected: all pass

**Manual checks (if no CLI):**
- Throwaway Playwright harness (scratchpad) on headless Chromium: badge menu keyboard flow, confirm/cancel focus, Esc layering with preview, hint focus/blur, banner persistence across reload.

## Auto Run Result

Status: done

**Summary:** Spoiler-safety primitives (VisibilityBadge with GM menu + inline Party confirmation, SecretField, FieldVisibilityHint, RoleBadge), the Button `write` prop with `useWriteGuard()`, a per-tab preview store (`lib/preview.ts`, sessionStorage `lk-preview`), `usePreview()` in `contexts/PreviewContext.tsx`, the PreviewBanner above the nav (z 60, `--lk-preview-offset: 2.5rem`), and the `X-Lorekeeper-Preview: member` header on axios requests while active. Inert: nothing calls `enter()` until E0-UX.7/E7.7, and the backend does not yet honour the header (E0-Access.3).

**Files:**
- `src/frontend/src/lib/preview.ts` — preview store + header helper (new)
- `src/frontend/src/contexts/PreviewContext.tsx` — usePreview, useWriteGuard (new)
- `src/frontend/src/components/shell/PreviewBanner.tsx` — banner (new)
- `src/frontend/src/components/ui/{visibility-badge,secret-field,field-visibility-hint,role-badge}.tsx` — primitives (new)
- `src/frontend/src/components/ui/button.tsx` — `write` prop
- `src/frontend/src/services/api.ts` — preview header; clears preview on 401
- `src/frontend/src/App.tsx` — mounts banner
- `src/frontend/src/components/NavBar.tsx`, `SlideOver.tsx`, `pages/ChatPage.tsx` — offset by banner; NavBar logout clears preview
- `src/frontend/src/hooks/useAuth.ts` — logout clears preview
- `src/frontend/scripts/check-spoiler-safety.mjs`, `.github/workflows/frontend-ci.yml` — new check + CI step

**Review:** 38 findings; 20 rows patched (8 root causes), 3 deferred, 15 rejected (reasons in the triage log). Note: the Tasks line naming `text-card` for the banner was superseded by the DESIGN.md `background` token during review.

**Follow-up review recommended:** true — patched medium entries: 4 (write-button tooltip, asChild guard, logout clearing preview, confirm-gate tests). Unverified risk: the `asChild` blocked-click guard (capture-phase preventDefault) has no automated test.

**Verification:** `npx tsc --noEmit` clean; `npm run build` ok; check-ui-tokens --contrast 108/108; check-semantic-fallback pass; check-ui-primitives 25/25; check-focus-trap ok; check-spoiler-safety 24/24; scratchpad Playwright harness 17/17 on headless Chromium.

**Residual risks:** CORS header allowance and streaming-fetch header (deferred); duplicated tabs inherit preview via sessionStorage; disabled write buttons are not keyboard-focusable, so the read-only reason is hover-only.
