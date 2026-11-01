---
title: 'E0-Access.11: Campaign events route and useCampaignEvents'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '64eb9886df50b4d9cc6b942368e726036b1071f5'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Each keyed invalidation costs one short DB session and query per connected non-GM viewer.
    evidence: |-
      campaign_event_stream opens AsyncSession(bind) per keyed event when the viewer is not a writable GM. Keyed events are not throttled. A bulk import with M keyed events and N Players means N*M queries, run one after another per stream. Unmeasured: a burst benchmark with real publishers (E0-WorldCore.3, E0-Journal) would settle whether batching or a short per-stream memo is needed.
    location: >-
      src/backend/app/access/events.py campaign_event_stream
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** Nothing tells an open browser that Campaign data changed. Visibility and Role changes only show after a reload, so a Player can keep seeing a record that was just hidden. E0-Jobs.6 shipped the channel `campaign:{id}:events`, `publish_campaign_event` and `sse_response`, but no route consumes the channel and nothing publishes `visibility` or `role` on it.

**Approach:** Add `GET /api/campaigns/{campaign_id}/events`. It streams the channel through `sse_response`, and every event goes through an Audience filter in `app/access/events.py` first. A resync handshake comes first: an `event: subscribed` frame is sent once the subscription is live, and the client refetches when it gets it. `set_visibility` commits and grant changes publish unkeyed `visibility` / `role` invalidations. nginx gets a streaming location. The frontend gets `hooks/useCampaignEvents.ts`, which is mounted once in the app shell.

## Boundaries & Constraints

**Always:**
- Event payloads are `{domain, id}` and nothing else. The filter rebuilds the payload from those two fields, so any extra key a publisher adds is dropped.
- **Who receives what.** Every rule fails closed.
  - A writable GM ctx gets every well-formed invalidation.
  - The broadcast domains `visibility` and `role` reach every viewer, always with `id: null`.
  - A keyed event of a registered domain reaches a non-GM only if `scoped_select(model, filter_ctx)` finds that id now, i.e. it is visible after the change (AD-5).
  - An unkeyed event of a registered domain reaches a non-GM unless the domain's model is always-GM for them: `always_gm` with no owner field, or a `false()` predicate.
  - A Player gets nothing of an unknown domain, a malformed message or an id that is not a UUID. Not even the domain name.
- The real ctx (`require_campaign("player", preview=False)`) is what `sse_response` watches. Under `X-Lorekeeper-Preview: member`, a GM's events are filtered as the member view. The header only narrows.
- **Resync contract** (E0-Jobs.7 and E0-Jobs.9 follow it). The listener yields `("subscribed", {})` right after SUBSCRIBE succeeds, and the route sends it as the first frame. Every event published after that frame is delivered, subject to the filter. A client must treat any data read before `subscribed` as possibly stale: on every `subscribed` it refetches the Campaign's queries. There are no event ids and no replay. Every gap (overflow, access_changed, a network drop, a Valkey restart) is closed by reconnect, then `subscribed`, then refetch.
- If a visibility check can't run (a DB error), the stream ends rather than dropping that one event. The client then reconnects and resyncs.
- `visibility` is published once per Campaign after a `set_visibility` commit, through `register_visibility_listener`. `role` is published once per Campaign after a grant change commits, from `grants._dispatch`. Both go through `publish_campaign_event(cid, domain, None)`. Its 30 s per-(Campaign, domain) window with a trailing send is stricter than the story's "at most 1 per second", and the leading edge goes out at once.
- The route is limited by slowapi `30/minute` with `user_or_ip`. The request session is closed before streaming.
- nginx: an anchored regex location in the generic `api` zone, with `proxy_buffering off`, `proxy_read_timeout 1h` and `gzip off`. The proxy lines are written out in full, because `proxy_common.conf` already sets `proxy_read_timeout` and a duplicate is an nginx error. `X-Accel-Buffering` is not in `proxy_ignore_headers`.
- **Frontend.** Use fetch with a ReadableStream and a bearer header, plus the preview header while preview is active. Never use EventSource or `?token=`. On each `invalidate`, call `invalidateQueries([domain, campaignId])`. A `role` event also invalidates `["campaignRole", campaignId]`. `visibility`, `role` and `subscribed` refetch everything Campaign-scoped. Reconnect with backoff (1 s doubling to 30 s, with jitter, reset on `subscribed`). On `access_changed`, reconnect once at once. Stop on 401/404, and on a 404 invalidate `campaignRole` too. Preview on/off reopens the stream.

**Never:**
- Don't add a new channel or a publish outside `app/core/pubsub.py`. Don't change `world_service` / `app/hooks/world.py` (E0-WorldCore.3) or the job stream (E0-Jobs.7). Don't add `lib/sse.ts` (E0-Jobs.9). The reader stays inside `useCampaignEvents.ts`, behind one `openStream` function that E0-Jobs.9 replaces.
- Don't forward an event to a Player on the strength of its domain alone, and don't use a GM-wide check for a preview ctx.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Connect | Member, bearer | 200 `text/event-stream`, `X-Accel-Buffering: no`, first frame `subscribed {}` | — |
| Hidden id | `{entities, <gm entity>}` | Player and preview: nothing. GM: delivered | — |
| Visible id | `{entities, <party entity>}` | Player gets `{domain:"entities", id}` | — |
| Always-GM domain | `{npcs, null}` / `{npcs, id}` | Player: nothing | — |
| Unknown domain / junk | `{secret_thing, id}`, non-JSON, extra keys | Player: nothing. GM: `{domain,id}` only (junk dropped) | logged |
| Broadcast | `{visibility, <id>}` | Everyone gets `{domain:"visibility", id:null}` | — |
| Not a member / anon / bad id | — | the same 404 as a missing Campaign (anon 401/404, as elsewhere) | — |
| Grant changes | Player demoted or removed mid-stream | `access_changed`, stream ends; reconnect gets 200 or 404 | — |
| Visibility commit | GM `set_visibility` and commit | one `{visibility, null}` on the channel; none on rollback | publish failure logged |
| No Valkey | — | stream ends with no `subscribed` frame; the client backs off | logged |

</intent-contract>

## Code Map

- `src/backend/app/core/pubsub.py` -- `_listen` and `listen_*`. Add `announce=` and `SUBSCRIBED_EVENT`.
- `src/backend/app/core/sse.py` -- `sse_response(gen, ctx=, bind=)`. Reuse as is; document the resync contract in the docstring.
- `src/backend/app/access/registry.py` -- `scoped_select`, `registration`, `AlwaysGM`, `visible_clause`. Read-only here.
- `src/backend/app/access/context.py` -- `_narrow_for_preview`, `require_campaign(preview=False)`.
- `src/backend/app/access/visibility.py` -- `register_visibility_listener`.
- `src/backend/app/access/grants.py` -- `_dispatch`: add the `role` publish.
- `src/backend/app/api/routes/visibility.py`, `app/main.py` -- the router-under-`/api/campaigns` pattern, with the `gate` dependency.
- `src/backend/tests/test_sse.py` -- the in-process uvicorn and fakeredis harness to copy.
- `src/backend/tests/ev4/probes/grants.py`, `_support.py`, `fixtures.py` -- probe patterns, actors and `previewing`.
- `nginx/locations.conf` -- the shared append point. The template at the bottom shows a streaming location.
- `src/frontend/src/hooks/useChat.ts` -- the existing fetch and ReadableStream reader. `src/lib/preview.ts` -- `previewHeaders`, `subscribePreview`.
- `src/frontend/src/App.tsx` -- mount one subscriber inside `CurrentCampaignProvider`.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/core/pubsub.py` -- add `SUBSCRIBED_EVENT = "subscribed"`, plus `announce: bool = False` on `_listen` and the three `listen_*` functions. With it on, yield `(SUBSCRIBED_EVENT, {})` once after SUBSCRIBE succeeds.
- `src/backend/app/access/events.py` (new) -- `register_event_domain`, built-ins (`journal`, `entities`, `relationships`, `character_sheets`, `session_plans`, `sources`, `shorthand`, `npcs`, `quests`, plus broadcast `visibility` and `role`), `stream_ctx(request, ctx)`, `deliverable(session, ctx, data)`, `campaign_event_stream(filter_ctx, *, bind)`, and the visibility listener that publishes `visibility`. Export the public names from `app/access/__init__.py`.
- `src/backend/app/access/grants.py` -- `_dispatch` publishes `role` once per Campaign.
- `src/backend/app/api/routes/events.py` (new) and `app/main.py` -- the route, mounted under `/api/campaigns` with `gate`.
- `nginx/locations.conf` -- the events location.
- `src/backend/tests/access/test_campaign_events.py` (new) -- the filter matrix, both publishers (commit and rollback), and the route end-to-end on uvicorn and fakeredis or real Valkey (headers, `subscribed` first, filtering, preview, 404s, the limiter), plus nginx resolution.
- `src/backend/tests/test_pubsub.py` -- `announce`.
- `src/backend/tests/ev4/probes/events.py` (new) -- the EV-4 probe: no hidden id or GM-only domain reaches a Player, preview or cross-GM Player; a visible id does (positive control); hidden Campaign = missing.
- `src/frontend/src/hooks/useCampaignEvents.ts` (new), `src/App.tsx` -- the hook and the shell mount.
- `src/frontend/scripts/check-campaign-events.mjs` (new), `.github/workflows/frontend-ci.yml` -- pure-logic checks: the frame parser, keys per event, the reconnect policy, and a fake-transport run.

**Acceptance Criteria:**
- Given the route registered, when EV-4 runs, then the events probe records no leaks and the route resolves to an nginx location with `proxy_buffering off` and `proxy_read_timeout 1h`.
- Given the full backend suite and frontend build and checks, when CI runs, then they pass with no regressions.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 31 findings — high 0, medium 4, low 15, false 5, maybe-false 7
- findings:
  - `[low]` `[reject]` Blind: a keyed event for a deleted visible row is dropped for Players — by contract (AD-5 and the story): publishers send deletes unkeyed. Now documented in the events.py docstring.
  - `[medium]` `[patch]` Blind: a half-open connection hangs forever — added a 45 s idle watchdog (`createFetchStream(idleMs)`, 3 missed pings) and a check that runs it.
  - `[low]` `[reject]` Blind: a 401 stops the stream and it does not restart on re-login — the intent says to stop on 401; login is a full page navigation, which remounts the shell.
  - `[low]` `[reject]` Blind: 402/403 reconnect forever at 30 s — the intent says "stop only on 401/404"; the cost is one request per 30 s.
  - `[maybe-false]` `[reject]` Blind: no Valkey → 200 with an empty body — sse_response's contract (E0-Jobs.6); the client backs off. A 503 would change the shared helper.
  - `[low]` `[patch]` Blind: the resync set misses npc-entries/quest-entries — added both to CROSS_CAMPAIGN_KEYS. shared* keys belong to anonymous share pages, which run no stream (rejected part).
  - `[maybe-false]` `[reject]` Blind: the first `subscribed` double-fetches — the deliberate resync contract (correctness over a few requests); documented.
  - `[low]` `[reject]` Blind: `["role", cid]` matches no query — required by the AC (`[domain, campaignId]` for every event); harmless.
  - `[maybe-false]` `[defer]` Blind: one DB session per keyed event per viewer — unmeasured; deferred with what would settle it.
  - `[medium]` `[patch]` Blind + VerificationGap: the stream-level fail-closed path was untested — added test_a_failed_check_ends_the_stream.
  - `[low]` `[reject]` Blind: EventDomain.where is unused/untested — an extension point mirroring register_visibility_kind; deleting it is out of scope churn.
  - `[false]` `[reject]` Blind: one failed grant publish suppresses `role` — publish_grant_change catches every error (grants.py), so the loop never aborts.
  - `[low]` `[reject]` Blind: the nginx location copies proxy_common.conf with no drift guard — documented in the location comment; a guard would need a config diff tool.
  - `[low]` `[patch]` Blind + Edge: the response body was not cancelled on non-ok / exit — now `resp.body.cancel()` and `reader.cancel()`; a check covers the non-ok case.
  - `[low]` `[patch]` Blind + Edge + VerificationGap: EVENTS_PATH ignored VITE_API_URL — it now uses the same base as services/api.ts.
  - `[maybe-false]` `[reject]` Intent: R2a (id-less events as presence leaks) vs R2b — the intent says "decide what Players get"; decided R2b (Design Notes), and EV-4 proves it.
  - `[maybe-false]` `[reject]` Intent: no real producer for entities/journal yet — E0-WorldCore.3 / E0-Journal own them (siblings); the filter is tested on injected wire messages in the B2 format.
  - `[maybe-false]` `[reject]` Intent: nginx is checked as text, not run — also run on the desktop: `nginx -t` passed, and a stub SSE upstream behind the location streamed frames incrementally. Real app behind nginx is listed for desktop verification.
  - `[maybe-false]` `[reject]` Intent: the React hook is never rendered — the loop, the transport and the cache effects are executed against a real QueryClient; the mount is guarded by a source check.
  - `[false]` `[reject]` Intent: the 30 s throttle vs 1/s — 30 s satisfies "at most 1 per second" and is the B2 contract; the leading edge is immediate.
  - `[false]` `[reject]` Intent: "reconnect ONCE" resets after `subscribed` — once per access change; a later grant change is a new event.
  - `[false]` `[reject]` Intent: pubsub.py was edited outside the story — the requester asked for the resync story so E0-Jobs.7/.9 follow it; `announce` is additive and default-off.
  - `[medium]` `[patch]` Edge: `visibility` was published before the cache generation moved — _publish_visibility now bumps the cache first (test_visibility_is_published_after_the_cache_generation_moves).
  - `[low]` `[reject]` Edge: deleted row — same as the first Blind row.
  - `[low]` `[patch]` Edge: npc-entries/quest-entries — same fix as above.
  - `[low]` `[reject]` Edge: 401 permanent stop — same as above.
  - `[low]` `[reject]` Edge: 402/403 — same as above.
  - `[false]` `[reject]` Edge: re-added after a 404 does not reopen — re-adding happens via an invite/join flow that navigates, which remounts; rare otherwise.
  - `[low]` `[patch]` Edge: _never_visible only caught always_gm — now also any `false()` predicate (test with a GM-only membership domain).
  - `[medium]` `[patch]` VerificationGap: `subscribed` after confirmation was not observable — stub-pubsub tests for the delayed confirmation, the timeout and the error branch.
  - `[low]` `[patch]` VerificationGap: 404-first loop and campaignRoleKey reuse — a 404-first check added; the hook now reuses campaignRoleKey from useCampaignRole.

## Design Notes

**What a key reveals.** The id of a hidden record never reaches a Player. A keyed event for a *visible* record can still fire when only a GM-only field of it changed (`gm_notes`). The Player then refetches, gets identical Party data, and learns only that something about a record they can see changed. This is accepted, and it is the residual AD-5 allows, because publishers emit row-level keys. Unkeyed events reveal that something in a domain the Player can read changed, at most once per 30 s.

## Verification

**Commands:**
- `docker run ... lorekeeper-backend-test python -m pytest -q` (desktop) -- expected: everything passes.
- `cd src/frontend && npx tsc --noEmit && npm run build && node scripts/check-campaign-events.mjs` -- expected: success.

## Auto Run Result

Status: done (PR #67, draft). Run by one builder: the implementation was done in the main thread (the platform's subagents run asynchronously), and the review layers ran as 4 parallel subagents.

**Summary.**
- `GET /api/campaigns/{id}/events` streams `campaign:{id}:events` through `sse_response`. Every event is filtered per viewer by `app/access/events.py`; the filter rules are in the intent contract.
- Resync contract: `listen_*(announce=True)` yields `subscribed` once SUBSCRIBE is confirmed, and clients refetch on every `subscribed`.
- After commit, `set_visibility` publishes `visibility` (cache first) and grant changes publish `role`.
- nginx gets a streaming location.
- `useCampaignEvents` is mounted once in the shell.

**Files.**
- `app/access/events.py` (new) -- the filter, the domains, the stream and the visibility publisher.
- `app/api/routes/events.py` (new), `app/main.py` -- the route.
- `app/access/grants.py` -- the `role` publish.
- `app/access/__init__.py` -- exports.
- `app/core/pubsub.py` -- `announce`, `SUBSCRIBED_EVENT`, `_confirmed`.
- `app/core/sse.py` -- docstring.
- `nginx/locations.conf` -- the events location; the template regexes are now quoted.
- `tests/access/test_campaign_events.py`, `tests/test_pubsub.py`, `tests/ev4/probes/events.py`, `tests/ev4/test_nginx.py` -- tests.
- `src/frontend/src/hooks/useCampaignEvents.ts`, `src/App.tsx`, `scripts/check-campaign-events.mjs`, `.github/workflows/frontend-ci.yml` -- the frontend.

**Review.**
- 31 findings.
- Patched: medium 4, low 6 (each fix is listed in the triage log).
- Deferred: 1, the per-event DB check cost.
- Rejected: 20, each with a reason in the triage log (31 = 10 patched + 1 deferred + 20 rejected).
- Follow-up review: true, because 2 or more medium entries were patched. The risk to check is the new idle watchdog in `openFetchStream`, which aborts a quiet stream after 45 s.

**Verification.**
- Desktop (`lorekeeper-backend-test`, own pg16 and Valkey containers, now removed): full suite 2022 passed, 7 failed.
  - The nginx-test failure was caused by this change (an assertion about `{36}`) and is fixed.
  - The 6 others are timing tests (reaper/admission threads, real-Valkey bursts, a hooks handler). They passed in GitHub CI on the same commit. On the desktop they pass alone and fail under the parallel load of other builders.
  - The targeted rerun after the fixes: 489 passed, 1 timing flake (`burst[real]`).
- GitHub CI on the first commit: 2028 passed, 1 failed (test_nginx, fixed). EV-4: probes=86, leaks=0.
- Frontend: `tsc --noEmit`, `npm run build` and every check script pass (`check-campaign-events`: 22 checks).
- nginx: `nginx -t` passes; a stub SSE upstream behind the new location streamed frames incrementally (1.5 s apart, unbuffered).

**Needs desktop verification.**
- With the real stack up (`docker compose -f docker-compose.prod.yml up`), run `curl -skN https://<host>/api/campaigns/<id>/events -H "Authorization: Bearer <jwt>"`. Expect `event: subscribed` at once, then `event: ping` every 15 s. Toggle an entry's Visibility as GM and expect `event: invalidate {"domain":"visibility","id":null}` without delay.
- In a browser, as a Player, with the campaign open: GM hides a visible entry and the Player's list refetches within about 1 s (the first in each 30 s window) or at the window's end.

**Residual risks.**
- Unkeyed events show Players that something changed in a domain they can read (at most 1 per 30 s per domain), and keyed events for a visible record fire even when only a GM-only field changed.
- The 30 s trailing window can keep a newly hidden record on a Player's screen for up to 30 s after a second change in the same window.
