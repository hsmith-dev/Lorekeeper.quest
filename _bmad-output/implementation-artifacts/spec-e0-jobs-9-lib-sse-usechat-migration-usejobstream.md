---
title: 'E0-Jobs.9: lib/sse.ts, useChat migration and useJobStream'
type: 'feature'
created: '2026-11-20'
status: 'done'
baseline_revision: '9b73f0bcdec1f75aec6b389349b9e1fdf893bba1'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-access-11-campaign-events-route-and-use-campaign-events.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Each tab holds one long-lived stream per subscriber; with the Job tray (E0-Jobs.10) mounting useJobStream app-wide, every tab will hold two, which exhausts the HTTP/1.1 six-connections-per-origin limit after a few tabs on the plain port-80 nginx listener.
    evidence: |-
      nginx.conf listens on 80 (HTTP/1.1) and 443 with http2. The Campaign events and Job streams are separate fetches. This story no longer mounts JobStreamSubscriber, so the risk lands when E0-Jobs.10 mounts the tray: multiplex Job events onto the Campaign events stream, share one stream across tabs (BroadcastChannel / leader tab), or require h2.
    location: >-
      src/frontend/src/hooks/useJobStream.ts JobStreamSubscriber; nginx/nginx.conf listen 80
    severity: medium
  - summary: >-
      The React effects of useJobStream and useCampaignEvents (reopen on Campaign or preview change, abort on unmount) are not exercised by any check.
    evidence: |-
      The node check harness has no effect-running renderer (only renderToStaticMarkup). Dropping `previewing` from the deps or the cleanup leaves every check green. The throwaway Playwright run covered the mount and unmount paths once; a committed render harness is needed to keep it covered.
    location: >-
      src/frontend/src/hooks/useJobStream.ts useJobStream; src/frontend/src/hooks/useCampaignEvents.ts useCampaignEvents
    severity: medium
  - summary: >-
      The AdminPage model-install progress stream still reads its SSE body with its own fetch and parser, outside lib/sse.ts.
    evidence: |-
      This story names only chat, Campaign events and Jobs. The check-sse source guard exempts pages/AdminPage.tsx explicitly. Moving it to a one-shot openSse is small, but it changes an admin flow that this story did not test.
    location: >-
      src/frontend/src/pages/AdminPage.tsx install()
    severity: low
---

<intent-contract>

## Intent

**Problem:** The frontend has three hand-rolled stream readers: the `useChat` POST parser, E0-Access.11's `openFetchStream` in `useCampaignEvents`, and nothing yet for Job events. AR-24 says every SSE stream goes through one tested client with the bearer header and backoff.

**Approach:** Extract `src/frontend/src/lib/sse.ts`, a fetch + ReadableStream client. It parses frames, adds the bearer and preview headers, runs a 45 s idle watchdog, and reconnects with jittered backoff (1 s doubling to 30 s), reset by `subscribed`. After `access_changed` it reconnects once, at once, and stops on abort, 401 or 404. A one-shot mode (no reconnect) serves the chat POST. `useCampaignEvents` and `useChat` move onto it. Add `types/jobs.ts`, `services/api/jobs.ts` and `hooks/useJobStream.ts` (`useJobStream`, `useJobs`, `useJob`) for `GET /api/jobs/stream`, `/api/jobs/` and `/api/jobs/{id}`.

## Boundaries & Constraints

**Always:**
- Auth goes only in the `Authorization: Bearer` header. No `EventSource` and no `?token=` anywhere in `src/frontend/src`. With no `lk_token`, the client never connects and returns `no_token`.
- `ping` frames re-arm the watchdog but never reach `onEvent`.
- Reconnecting streams follow the resync contract: every `subscribed` (the first and each one after a reconnect) is delivered to the caller, who refetches.
- Chat turns never reconnect: a POST is never replayed.
- Chat keeps `meta`/`delta`/`done`/`error` handling and the blocking fallback exactly as before. The one exception is a revoked stream.
- Abort cancels the fetch and the reader, so the server sees the disconnect and frees the LLM slot.
- Job queries use the keys `['jobs', campaignId]` (the default list) and `['jobs', campaignId, jobId]` (detail). `job` events merge into both caches.

**Never:**
- No Job tray UI (E0-Jobs.10).
- No backend changes.
- No new npm dependency.
- No migration of `AdminPage` model install. It is an admin-only POST progress stream outside this story's list; it is deferred.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Network loss | fetch rejects or the body errors | reconnect after 1 s, 2 s, 4 s … 30 s, each with jitter (×0.5–1) | attempt counter reset by `subscribed` |
| Silent stream | no chunk for 45 s | ended as an error → backoff reconnect | — |
| access_changed | frame then stream end | one reconnect, no delay; a second one without `subscribed` in between backs off | stop only on 401/404 |
| 401 / 404 | response status | stop; `onStop(reason)`; campaign events invalidate the role and Campaign queries, the Job stream invalidates `['jobs', cid]` | — |
| other status (503, 429) | response status | backoff reconnect (one-shot: return status) | body cancelled |
| Chat revoked | `error {"detail":"Not found"}` mid-stream | partial assistant reply and the user turn are removed; error shown; no blocking fallback; campaignRole invalidated | — |
| Chat other error / non-ok | `error {detail}` or 503 | as before: drop the partial reply, fall back to the blocking POST | — |
| Chat unmount mid-stream | component unmounts | fetch aborted (server releases the slot); no fallback | — |
| Job event, cached | `job` for a listed Job | fields patched in list + detail; on a status change the list (and detail) are refetched | malformed data ignored |
| Job event, unknown | id not in list | list refetched | — |

</intent-contract>

## Code Map

- `src/frontend/src/hooks/useCampaignEvents.ts` -- E0-Access.11. Holds the parser (`parseSseFrame`, `createFrameSplitter`), the policy (`backoffMs`, `nextStep`, `ReconnectState`), `createFetchStream`/`openFetchStream` with the 45 s watchdog, `streamHeaders`, and the `runCampaignEvents` loop. The transport, parser, policy and loop move to `lib/sse.ts`. The hook keeps `applyFrame`/the invalidation key logic and calls `openSse`. It re-exports the moved names that the existing check imports.
- `src/frontend/src/hooks/useChat.ts:24-137` -- its own `parseSseFrame` and stream loop, to be replaced by `openSse(..., { method: "POST", body, reconnect: false })`.
- `src/frontend/src/services/api.ts:12-23` -- the axios interceptor comment that names lib/sse.ts. Preview headers come from `lib/preview.ts` `previewHeaders()`.
- `src/frontend/src/services/api/members.ts` -- the pattern for a domain API module that uses the shared axios instance.
- `src/backend/app/api/routes/jobs.py`, `app/schemas/jobs.py` -- read-only contract: `JobResponse` fields, `JobListResponse{jobs}`, and stream frames `subscribed`/`job`/`ping`/`access_changed`. Retry returns 202 `{job_id}`; cancel returns a JobResponse.
- `src/backend/app/api/routes/chat.py:486-598` -- read-only. A revoked chat stream ends with `error {"detail":"Not found"}`. The slot is released in the generator's finally on disconnect.
- `src/frontend/scripts/check-campaign-events.mjs` -- the esbuild + node:test harness to copy for `check-sse.mjs`.
- `.github/workflows/frontend-ci.yml` -- add the new check step.

## Tasks & Acceptance

**Execution:**
- `src/frontend/src/lib/sse.ts` -- new: frame parser and splitter, `sseHeaders()`, `backoffMs`, `nextStep`, `connectSse` (one connection with the watchdog), and `openSse(url, {method, body, onEvent, signal, reconnect, idleMs, onStop, …})`. `openSse` drives the loop and returns the end reason.
- `src/frontend/src/hooks/useCampaignEvents.ts` -- drop the transport and loop. `runCampaignEvents` becomes a thin wrapper over `openSse` that keeps its options and return values.
- `src/frontend/src/hooks/useChat.ts` -- stream through `openSse`. Handle a revoked stream. Abort on unmount.
- `src/frontend/src/types/jobs.ts`, `src/frontend/src/services/api/jobs.ts` -- Job types; `listJobs`, `getJob`, `retryJob`, `cancelJob`, `JOB_STREAM_PATH`.
- `src/frontend/src/hooks/useJobStream.ts` -- `applyJobFrame` (pure), `runJobStream`, `useJobStream(campaignId)`, `useJobs(campaignId)`, `useJob(jobId, campaignId = current)`.
- `src/frontend/src/services/api.ts` -- re-export the jobs API; update the comment.
- `src/frontend/scripts/check-sse.mjs` + CI step -- parser, policy, loop over a fake fetch (reconnect, jitter bounds, access_changed once, 401/404 stop, abort, watchdog, one-shot POST, ping filtering), job cache merging, and source guards across `src/` (no EventSource or `?token=`; fetch-based readers only in `lib/sse.ts`, except the deferred AdminPage).
- `src/frontend/scripts/check-campaign-events.mjs` -- keep passing. Move the transport tests to the new names where needed.

**Acceptance Criteria:**
- Given `npm run build`, `check-sse.mjs` and every existing check script, when they run, then all pass.
- Given a throwaway Playwright run against a mocked API, when the campaign and Job streams drop, send `access_changed`, return 404, or a chat stream is revoked mid-way, then the browser shows the behaviour in the matrix: refetch after each `subscribed` and a bearer header on every request.

## Design Notes

`openSse` stays transport-generic: it knows `subscribed`, `access_changed` and `ping` because every server stream emits them. Callers get `{event, data}` and decide what to refetch. An exception thrown by `onEvent` cancels the reader and propagates. `useChat` relies on this to end a turn on `error`.

The chat stream has no pings, and the first token may take longer than 45 s on CPU, so chat passes `idleMs: null`. Streaming chat now also sends the preview header, as the blocking fallback already does. The server only narrows with it.

## Verification

**Commands:**
- `cd src/frontend && npm run build && npm run lint:tokens && for f in scripts/check-*.mjs; do node $f || exit 1; done` -- expected: all pass
- throwaway Playwright (scratchpad, not committed) against a mocked `/api` -- expected: the matrix rows are observed

## Spec Change Log

## Review Triage Log

### 2026-11-20 — Review pass
- verdicts: 27 findings — high 0, medium 7, low 12, false 8, maybe-false 0
- findings:
  - `[medium]` `[patch]` Blind: an onEvent throw in reconnect mode ends the Campaign events / Job stream for good with an unhandled rejection (the old transport reconnected) — openSse now catches it in reconnect mode, logs it, ends the connection as an error and backs off; check-sse test added.
  - `[low]` `[reject]` Blind: 4xx other than 401/404 retries every 30 s forever — the intent says stop only on 401/404; capped at one try per 30 s; the server answers malformed or hidden ids with the uniform 404.
  - `[false]` `[reject]` Blind: a stopped stream never restarts after re-login — before login the current Campaign is null, so the effect opens when it resolves; an axios 401 does a full reload (`window.location.href = "/login"`), which remounts the subscribers.
  - `[false]` `[reject]` Blind: chat ignores `access_changed` and accepts a reply cut off without `done` — chat.py never emits `access_changed` (a revoke is `error {"detail":"Not found"}`); not requiring `done` is the old behaviour, unchanged.
  - `[false]` `[reject]` Blind: revoke detected by the "Not found" string — chat.py emits that detail only on revoke (NOT_FOUND_DETAIL); the other `error` details come from llm_provider HTTPExceptions with other text (confirmed by the verification-gap layer).
  - `[low]` `[reject]` Blind: on revoke the user's text is lost — the existing blocking-failure path drops the turn the same way; restoring a draft adds new surface for a rare event.
  - `[medium]` `[patch]` Blind: the useChat migration has no behavioural checks — grouped with the Gap finding below; fix there.
  - `[low]` `[reject]` Blind: useJob may cache a Job under the wrong Campaign; the placeholder `?.jobs.find` may throw — `campaignId` is an explicit parameter (E0-Jobs.10 passes it); the list cache only ever holds a JobListResponse from useJobs' own queryFn, and stream merges guard with Array.isArray.
  - `[low]` `[reject]` Blind: Jobs client lacks a status-filter hook and retry/cancel mutations — tray actions are E0-Jobs.10; this story ships the API functions.
  - `[low]` `[reject]` Blind: services/api.ts and services/api/jobs.ts import each other — `api` is used only inside function bodies; the build and every check pass; moving the axios instance is a refactor beyond this story.
  - `[medium]` `[patch]` Blind: two long-lived streams per tab exhaust HTTP/1.1 connections — the JobStreamSubscriber mount was removed from App.tsx (the story mounts per component); the connection budget is deferred to E0-Jobs.10.
  - `[low]` `[reject]` Blind: bursts of status changes cancel each other's list refetches — cancel-and-restart converges on the latest list once the burst ends; `cancelRefetch: false` would keep a fetch that started before the last change.
  - `[medium]` `[patch]` Edge: an onEvent throw in reconnect mode kills the stream — same root cause as the first Blind row; patched there.
  - `[false]` `[reject]` Edge: the Job stream is not reopened after a 401 or no_token and re-login — same refutation as the Blind restart row.
  - `[low]` `[reject]` Edge: a fast double submit aborts the first turn — a stale `isLoading` closure that predates this change; ChatPage's composer is disabled while `isLoading`.
  - `[false]` `[reject]` Edge: a final frame without a trailing blank line is dropped — every server stream (core/sse.py, chat.py) ends each frame with `\n\n`; the old parsers did the same.
  - `[low]` `[reject]` Edge: an in-flight list refetch can overwrite a newer progress patch — it heals on the next event (progress arrives at most once a second), and a status change always refetches.
  - `[low]` `[reject]` Edge: useJob for a Job in another Campaign — same as the Blind useJob row.
  - `[low]` `[reject]` Edge: progress outside 0..1 and negative ETAs are not clamped — the server computes them; presentation belongs to the tray (E0-Jobs.10).
  - `[false]` `[reject]` Edge: the chat URL now carries the VITE_API_URL prefix — the blocking fallback (axios baseURL) already uses that base, so streaming and blocking now agree.
  - `[medium]` `[patch]` Gap: the useChat revoked / aborted / fallback handling is checked only by source regexes — `streamChatTurn` was extracted (same behaviour), and check-sse covers ok / revoked / error detail / 503 / no token / abort / no meta or no text.
  - `[medium]` `[defer]` Gap: the useJobStream / useCampaignEvents React effects (reopen, abort) are not exercised — needs an effect-running render harness; deferred.
  - `[false]` `[reject]` Intent: aborting on unmount means a turn the user left mid-reply is not saved — the spec matrix row "Chat unmount mid-stream" asks for the abort, and the intent asks that disconnect free the slot; recorded as a behaviour change in the result.
  - `[low]` `[defer]` Intent: the AdminPage model-install SSE stays outside lib/sse.ts — the spec excludes it; deferred.
  - `[low]` `[reject]` Intent: `useJob(jobId, campaignId?)` instead of `useJob(jobId)` — still callable as `useJob(jobId)` (it defaults to the current Campaign); the key needs the Campaign.
  - `[medium]` `[patch]` Intent: the app-wide JobStreamSubscriber mount goes beyond "when a component mounts" — grouped with the Blind connections row; mount removed.
  - `[false]` `[reject]` Intent: no hand check against the real `/api/chat/stream` is in the diff — the throwaway Playwright run covered revoke, ok, 503 fallback and unmount against a mock; a live check is listed under desktop verification.

## Auto Run Result

Status: done

**Summary:** `lib/sse.ts` is now the frontend's one stream client.
- Transport: fetch + ReadableStream, with the bearer and preview headers.
- Watchdog: 45 s idle. Pings re-arm it and never reach `onEvent`.
- Reconnects: backoff of 1 s doubling to 30 s with ×0.5–1 jitter, reset by `subscribed`. After `access_changed` it reconnects once, at once. It stops on abort, 401 or 404.
- One-shot mode serves the chat POST.

The three streams that use it:
- `useCampaignEvents`: E0-Access.11's `openFetchStream` is gone; the hook wraps `openSse`.
- `useChat`: it streams through `streamChatTurn`, which wraps `openSse` with no reconnect and no watchdog.
  - Revoked mid-stream (`error {"detail":"Not found"}`): the partial reply and the user turn are dropped, a notice is shown, `campaignRole` is invalidated, and there is no blocking fallback.
  - Unmount: the fetch is aborted, so the server frees the LLM slot.
  - Every other failure still falls back to the blocking POST.
- `useJobStream`, `useJobs` and `useJob`: they back the `['jobs', cid]` and `['jobs', cid, jobId]` caches from `GET /api/jobs/stream`, `/api/jobs/` and `/api/jobs/{id}`. A `job` event patches the cached rows; a status change refetches.

**Files:**
- `src/frontend/src/lib/sse.ts` (new): parser, headers, policy, `connectSse`, `openSse`.
- `src/frontend/src/hooks/useCampaignEvents.ts`: transport and loop removed; wraps `openSse`; re-exports the moved names.
- `src/frontend/src/hooks/useChat.ts`: `streamChatTurn`, revoke handling, abort on unmount.
- `src/frontend/src/hooks/useJobStream.ts` (new): cache merging, stream loop, query hooks, `JobStreamSubscriber`. The subscriber is not mounted yet; E0-Jobs.10 mounts it.
- `src/frontend/src/services/api/jobs.ts`, `src/frontend/src/types/jobs.ts` (new): the Jobs API and its types.
- `src/frontend/src/services/api.ts`: re-exports the Jobs API; comment updated.
- `src/frontend/scripts/check-sse.mjs` (new, 36 tests), plus a step in `.github/workflows/frontend-ci.yml`.
- `src/frontend/scripts/check-campaign-events.mjs`: transport tests moved to check-sse; a 401 test added.

**Review:** 27 findings.
- 3 patch groups, all medium:
  - a throwing `onEvent` no longer kills a reconnecting stream;
  - the app-wide Job-stream mount was removed (HTTP/1.1 connection budget);
  - the chat outcomes are now checked in CI through `streamChatTurn`.
- 3 deferred: connection budget for E0-Jobs.10, the React-effect test harness, and the AdminPage install stream.
- 21 rejected; the reasons are in the triage log.

**Follow-up review:** recommended. Three medium entries were patched. The named unverified risk is that `useChat.send`'s state handling still has no CI check: deleting its revoked or aborted early return would leave CI green. Only the throwaway Playwright run exercised it.

**Verification:**
- `npm run build`: passes.
- `npm run lint:tokens` and both `--self-test` runs: pass.
- All 11 `scripts/check-*.mjs`: pass.
- A throwaway Playwright run (headless Chromium, real hooks bundled with esbuild, a mock API on 127.0.0.1, not committed) passed 9 of 9 checks:
  - Campaign events: a plain end backed off 0.89 s; `access_changed` reconnected after 0.10 s; a second `access_changed` with no `subscribed` backed off 0.95 s; 404 stopped it, with no further connection.
  - Refetch on every `subscribed`.
  - Job stream: reconnected after network loss (1.5 s), reconnected at once after `access_changed`, and stopped on 401.
  - Job events merged into the cache.
  - Chat revoked mid-stream: no fallback, no replay.
  - Chat ok, unchanged.
  - Chat 503: blocking fallback.
  - Chat unmount mid-stream: the server saw the close.

**Behaviour changes:**
- Streaming chat now sends the preview header, as the blocking fallback already did. In preview, a chat POST is 404.
- Leaving the chat page mid-reply now aborts the turn, so it is not saved.
- Campaign events now also refetch the role and Campaign queries on 401.

**Residual risks:**
- check-sse uses real 20–60 ms timers.
- The AdminPage install stream remains outside `lib/sse.ts`.

**Needs desktop verification:** a live check of `/api/chat/stream` by hand. Run `docker compose -f docker-compose.dev.yml up`, sign in, send a chat turn, and confirm the deltas stream. Then change that Member's Role mid-reply: the "access changed" notice should appear and no second request should be sent.
