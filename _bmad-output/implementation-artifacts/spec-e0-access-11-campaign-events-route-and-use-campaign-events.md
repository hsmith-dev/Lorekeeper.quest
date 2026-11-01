---
title: 'E0-Access.11: Campaign events route and useCampaignEvents'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '64eb9886df50b4d9cc6b942368e726036b1071f5'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred: []
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

## Design Notes

**What a key reveals.** The id of a hidden record never reaches a Player. A keyed event for a *visible* record can still fire when only a GM-only field of it changed (`gm_notes`). The Player then refetches, gets identical Party data, and learns only that something about a record they can see changed. This is accepted, and it is the residual AD-5 allows, because publishers emit row-level keys. Unkeyed events reveal that something in a domain the Player can read changed, at most once per 30 s.

## Verification

**Commands:**
- `docker run ... lorekeeper-backend-test python -m pytest -q` (desktop) -- expected: everything passes.
- `cd src/frontend && npx tsc --noEmit && npm run build && node scripts/check-campaign-events.mjs` -- expected: success.
