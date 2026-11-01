---
title: 'E0-Access.10: Grant changes bump access_epoch and close open streams'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'a55c32d30ed3742c4ce99bc562a6dc79d7efcd53'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Admin user deletion cascades away grants (memberships, owned Campaigns and their grants) without queuing the access: publish.
    evidence: |-
      admin.py delete_user calls db.delete(user); the CASCADE removes campaign_members, owned campaigns and their share tokens with no campaign_grants_removed / remove_member call. Open streams still close on the next grant_watch poll (at most GRANT_POLL_S = 15 s late), so this is late, not missed. The route is still in tests/ev4/pending_baseline.txt.
    location: >-
      src/backend/app/api/routes/admin.py delete_user
    severity: medium
---

<intent-contract>

## Intent

**Problem:** A grant change (role change, member removal, Share Link revocation or expiry) changes nothing that is already running. `access_epoch` is never bumped, an open Chronicler stream keeps sending GM-built text to someone who was just demoted or removed, and nothing makes a cache key depend on who is asking. The dead `cache:journals:{user_id}` helper is still there.

**Approach:** Add `app/access/grants.py`. It holds the only grant mutators (`change_member_role`, `remove_member`, `revoke_share_token`, `campaign_grants_removed`, plus the lazy expiry bump inside `resolve_share_token`). Each one bumps `access_epoch` where the grant survives and queues `publish_grant_change(campaign_id, grant_id)`, which publishes on `access:{campaign_id}:{grant_id}` after the root commit. It also holds `grant_watch(*ctxs)`, which returns as soon as an `access:` message arrives or a poll (an immediate one, then every 15 s) finds a grant missing or changed. Add `app/access/cache.py`, which builds keys as `cache:{campaign_id}:{generation}:{audience}:{access_epoch}:{domain}:…`. Invalidation increments a per-Campaign generation before deleting keys, so a write that races an invalidation is never served. `POST /api/chat/stream` races each chunk against `grant_watch`. When the watch fires, the stream aborts upstream and ends with `error {"detail":"Not found"}`.

## Boundaries & Constraints

**Always:**
- Only `app/access/` publishes on `access:` channels, and only `app/access/` builds `cache:` keys. Test-enforced by an AST scan of `app/`.
- Publishes happen after the root transaction commits. A rollback (root, or the savepoint the change was made in) discards them. A Valkey failure is logged and never raised. With no Valkey client, the publish is a no-op and the watch relies on the poll.
- The epoch is bumped when the grant row survives: a role change (only if the role actually changes), a revocation, and the expiry bump. A removal deletes the row, and the watch treats a missing grant as changed.
- Expiry is bumped lazily, at most once. When `resolve_share_token` meets an expired, non-revoked token with `updated_at <= expires_at`, one conditional UPDATE bumps it and sets `updated_at = now()`. Then it commits, publishes, and returns the same `not_found()`.
- The watch identifies a grant by `ctx.grant_id`. A Share Link ctx now carries `grant_id = token id`. A user ctx is re-resolved with `_resolve`, and it has changed if it is missing or if its role, grant_id or access_epoch differ. A token ctx has changed if the token is missing, revoked, expired or at another epoch. If a poll can't run (DB error), the watch fires, failing closed.
- Every denial stays the one `404 {"detail":"Not found"}`. A removed Member with a still-valid JWT gets 404 on every Campaign route, because each request re-resolves its ctx.
- `set_visibility`'s post-commit invalidation (`invalidate_campaign_cache`) increments `cachegen:{campaign_id}` first, then deletes `cache:{campaign_id}:*`.

**Never:**
- Don't build a second SSE framework (`core/sse.py`/`sse_response` is E0-Jobs.6). Don't add `core/pubsub.py` channels. Don't touch `app/jobs/` (E0-Jobs.5), the `after_commit` hook dispatcher (E0-Journal.1), stt (E0-Platform.5) or write rules/`can_write` (E0-Access.6).
- Don't add the members PATCH route, chat archiving on demotion, or the Sharing UI (E0-Access.12). Don't add a campaign events route (E0-Access.11).
- No migration (the columns exist since F1-core).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Demote mid-stream | Co-GM streaming chat; Owner `change_member_role(→player)` commits | epoch+1; publish; stream yields no more deltas, ends `error {"detail":"Not found"}`, upstream generator closed, turn not persisted | — |
| Remove mid-stream | Player streaming; `remove_member` | same as above (grant missing) | — |
| No Valkey | same, `get_valkey` uninitialised | poll detects it within the poll interval | — |
| Removed JWT | removed member calls Campaign routes | 404 identical to a missing Campaign | — |
| Revoke | `DELETE /share/{id}` | revoked, epoch+1, publish; share URLs 404 like unknown | — |
| Expired token | first resolve after expiry | epoch+1 once, publish once; 404; later resolves don't bump | — |
| No-op role change | same role | no bump, no publish | — |
| Rollback | grant change then rollback | no publish | — |
| Racing cache write | value computed before an invalidation, written after | never served (old generation) | — |
| Worker | Job started before demotion/removal | `permission_changed` | — |

</intent-contract>

## Code Map

- `src/backend/app/access/context.py:_resolve` (l.198) -- the ctx rebuild the poll reuses; `CampaignContext` doc for `grant_id`.
- `src/backend/app/access/share.py` -- `resolve_share_token` (expiry filter at l.34) and `ctx_for_share` (`grant_id=None`, which becomes the token id).
- `src/backend/app/access/visibility.py:369 invalidate_campaign_cache` and `_after_commit`/`_drop_rolled_back` (l.400–440) -- the after-commit pattern to mirror. Add the generation increment.
- `src/backend/app/api/routes/campaigns.py:257 revoke_share_token`, `:289 remove_campaign_member`, `:322 leave_campaign`, and `delete_campaign` -- switch to the grants helpers.
- `src/backend/app/api/routes/chat.py:chat_stream` (l.~440) -- the stream loop; `_prepare_chat` returns `prep.ctx`/`prep.scope` (a RoleMap when there is no Campaign).
- `src/backend/app/services/cache_service.py` -- no callers. Delete it (it holds `cache:journals:{user_id}`).
- `src/backend/app/core/valkey_client.py` -- `get_valkey` raises RuntimeError when uninitialised; `set_valkey` for tests.
- `src/backend/app/jobs/worker.py:_current_ctx` (l.250) -- read-only: an epoch mismatch or a missing grant gives `permission_changed`.
- `tests/jobs/test_worker.py` `_campaign`, `_member`, `_job`, `_assert_permission_changed` -- reuse by import.
- `tests/ev4/probes/_support.py`, `families.py` (`assert_hidden_equals_missing`), `retrieval.py` (`use_fake_llm`) -- EV-4 helpers. A probe must call a family helper.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/grants.py` -- new. Holds the channel name, `publish_grant_change`, the after-commit queue, the mutators, `grant_watch`, and `GRANT_POLL_S = 15`.
- `src/backend/app/access/cache.py` -- new. Holds `cache_key`, `cache_generation`, `cached_json`, `invalidate_campaign_cache`, and `CACHE_TTL_S`.
- `src/backend/app/access/visibility.py` -- `invalidate_campaign_cache` delegates to `cache.invalidate_campaign_cache`.
- `src/backend/app/access/share.py` -- the lazy expiry bump, and `grant_id = share.id`.
- `src/backend/app/access/context.py` -- the docstring for `grant_id`.
- `src/backend/app/access/__init__.py` -- exports.
- `src/backend/app/api/routes/campaigns.py` -- the revoke, remove, leave and delete routes use the grants helpers.
- `src/backend/app/api/routes/chat.py` -- `chat_stream` races chunks against `grant_watch`.
- `src/backend/app/services/cache_service.py` -- delete.
- `src/backend/tests/access/test_grants.py` -- new: the matrix (unit and route), cache keys and the race, the worker, the AST guards.
- `src/backend/tests/ev4/probes/grants.py` -- new EV-4 probes: chat stream demote or remove mid-stream, member removal and share revocation via routes.

**Acceptance Criteria:**
- Given a Player or Co-GM streaming `POST /api/chat/stream`, when their grant changes mid-stream, then no delta after the change reaches them, the stream ends with `event: error` / `{"detail":"Not found"}`, and their next request answers per their new grant (404 like missing when removed).
- Given two ctxs of one Campaign with different audiences or epochs, then their cache keys differ, and every key starts with `cache:{campaign_id}:`.
- Given the AST scan, when any module under `app/` outside `app/access/` holds a `"cache:"` or `"access:"` string literal, then the test fails.

## Design Notes

- Generation: `cachegen:{cid}` deliberately sits outside the `cache:{cid}:*` delete pattern. A reader reads the generation before computing. If the generation is missing (first use, or evicted), it is seeded with `SET NX time_ns()`, so a reset can never reuse an old value. Invalidation is INCR, then delete. A reader that read the generation before the INCR writes under a dead generation. A reader that read it after the INCR computes after the commit. `cached_json` also skips the write when the generation moved during compute.
- The chat stream races `anext(stream)` against the watch task with `asyncio.wait(FIRST_COMPLETED)`. On a fire, it cancels the pending chunk and calls `aclose()` on the provider stream, which closes the upstream HTTP request, and persists nothing. With no Campaign, the watch covers the user's Co-GM grants in the role map.
- `grant_watch(*ctxs, bind=None)` polls in its own `AsyncSession(bind=bind or AsyncSessionLocal's engine)`. The route passes `db.bind`, so the poll never shares the request session.

## Verification

**Commands:**
- `python scripts/check_scoped_queries.py` -- expected: ok
- `lint-imports` (src/backend) -- expected: contracts kept
- `pytest -q` on the desktop (own Postgres and Valkey) and in GitHub CI -- expected: no regressions; EV-4 leaks=0

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 30 findings — high 0, medium 6, low 19, false 5, maybe-false 0
- findings:
  - Blind hunter:
    - `[medium]` `patch` A campaignless stream's watched ctxs come from ctx_for after prep, so a Co-GM demoted or removed in between is watched at the new state or skipped. Fixed: `_watched_grants` returns `lost` when a GM Campaign of the role map now gives NotFound or a non-GM role, and the stream ends with error Not found and no LLM call (tested).
    - `[false]` `reject` A campaignless stream doesn't watch Player Campaigns — `hybrid_search_own_journals` reads only the GM Campaigns of the role map (retrieval_service.py:148), so no Player Campaign rows reach a campaignless reply.
    - `[low]` `reject` No route calls change_member_role, the join route creates members, and no guard covers role/revoked/access_epoch writes — the PATCH route is E0-Access.12's AC (it depends on this story). Creating a grant is not a change of an existing one. A write guard adds a checker rule the story doesn't ask for.
    - `[low]` `reject` The expiry once-only marker relies on updated_at — no route edits a token. A revoke after expiry already bumps. A token created already expired was never live. A dedicated column needs a migration for a rare case.
    - `[medium]` `patch` resolve_share_token wrote an UPDATE on every miss, committed the caller's session, and could turn the 404 into a 500. Fixed: a read-only SELECT first, then the UPDATE and commit in its own session, with errors logged and the 404 kept (tested).
    - `[low]` `patch` The after-commit publish has no timeout. Fixed: asyncio.wait_for with PUBLISH_TIMEOUT_S = 2, logged (tested).
    - `[low]` `patch` cache_key used repr(audience) and unescaped ':' joins. Fixed: an explicit audience_token, and '%' and ':' are percent-escaped (collision test).
    - `[low]` `reject` cached_json swallows serialization errors and returns JSON types on a hit — it has no callers yet. Its contract is JSON-native values, and a failed write only loses caching.
    - `[low]` `patch` A failing watch closed the stream with nothing logged. Fixed: it logs `grant_watch_failed` with exc_info and still fails closed (tested).
    - `[low]` `reject` One pubsub connection and one poll per stream — fine for the self-hosted single-box target (a handful of streams). A shared subscriber is an optimisation for E0-Jobs.6's sse_response.
    - `[low]` `reject` The poll compares expiry with the app clock and the resolver uses the DB clock — app and DB share a host, so skew is negligible, and the fix touches every poll.
    - `[medium]` `patch` meta and early deltas went out before the first poll result, so a change during _prepare_chat (seconds, with the query-rewrite LLM call) leaked. Fixed: `grant_changed` runs before meta. On a change only `error` is sent, with no LLM call (tested). Grouped with the edge-case row 1.
    - `[low]` `patch` Missing failure-path tests — added as part of the patches above (pre-stream change, lost grant, failing watch, hung publish, corrupt value, no-commit on a miss).
  - Verification gap:
    - `[low]` `patch` The members DELETE route was never asserted to publish. Added `published == [(c.id, m.id)]`.
    - `[low]` `patch` Nothing checked the watch is cancelled on a normal end. The unchanged-stream test now records the watch's start and cancellation.
    - `[low]` `patch` No Owner stream with the Campaign deleted mid-stream. Added test_campaign_delete_mid_stream_closes_the_stream.
    - `[medium]` `defer` Admin user deletion removes grants without a publish — streams still close on the poll (at most 15 s late). The route is still in EV-4 pending. Deferred in the frontmatter.
  - Edge-case hunter:
    - `[medium]` `patch` The first deltas were built on the old grant before the first poll — the same root cause as the blind-hunter meta row, fixed by the pre-stream `grant_changed`.
    - `[low]` `reject` A removed Member who rejoins before an old Job runs passes the epoch check — they hold the same rights again, so the Job runs with their current ctx and nothing leaks. The fix is in app/jobs (E0-Jobs).
    - `[low]` `reject` The updated_at marker — same as the blind-hunter row.
    - `[medium]` `patch` The miss path committed the caller's session — fixed with the blind-hunter share row (own session).
    - `[low]` `patch` Junk tokens triggered a write UPDATE — fixed with the same patch (SELECT first).
    - `[low]` `patch` Cache-key ':' collision — fixed with the blind-hunter cache_key row.
    - `[low]` `patch` A corrupt cached value raised — it now logs `cache_read_failed` and recomputes (tested).
    - `[low]` `patch` _cancel's suppress(BaseException) swallowed an outer cancellation — it now re-raises when the current task is cancelling, and cleanup runs first.
  - Intent alignment:
    - `[false]` `reject` There is no role-change route, and demotion is tested through the mutator — epics.md puts the PATCH route in E0-Access.12, which depends on this story. The mutator is the contract it calls.
    - `[low]` `reject` The EV-4 stream probe closes through the poll rather than the publish — the publish-to-close path is covered by tests/access/test_grants.py against fakeredis and a real Valkey (VALKEY_TEST_URL, set in CI).
    - `[false]` `reject` No cached HTTP response is exercised — no route caches anything on main (cache_service had no callers). The key scheme and race are tested where they live.
    - `[false]` `reject` Jobs and WebSocket streams aren't wired — neither exists on main. `grant_watch` is the interface E0-Jobs.6's sse_response consumes.
    - `[false]` `reject` A demotion doesn't archive chat sessions — that is E0-Access.12's AC (archive on PATCH). E0-Access.8 only hides archived sessions.

## Auto Run Result

Status: done

**Summary:**
- `app/access/grants.py`:
  - The only grant mutators: `change_member_role`, `remove_member`, `revoke_share_token`, `campaign_grants_removed`, plus the lazy expiry bump `bump_expired_share_token`.
  - Each bumps `access_epoch` when the row survives, and queues `publish_grant_change` on `access:{campaign_id}:{grant_id}`. The publish runs after the root commit and is dropped on rollback, savepoints included.
  - `grant_watch(*ctxs, bind=)` and `grant_changed`: an immediate poll, then a 15 s poll plus the pubsub message. A missing grant counts as changed, and a failed poll fails closed.
- `app/access/cache.py`:
  - Keys are `cache:{campaign_id}:{generation}:{audience}:{access_epoch}:{domain}:…`, escaped.
  - Invalidation seeds and increments `cachegen:{campaign_id}`, then deletes, so a racing write is never served. `set_visibility` uses it.
  - The dead `cache_service` (`cache:journals:{user_id}`) is removed.
- `POST /api/chat/stream`:
  - It checks the grant before `meta`, then races every chunk against the watch.
  - When the watch fires, nothing more is sent, the upstream generator is closed, nothing is persisted, and the stream ends with `error {"detail":"Not found"}`.
  - A campaignless chat watches its Co-GM grants.
- Routes: revoke, remove, leave and delete-campaign go through the mutators.
- A Share Link ctx carries `grant_id` = the token id.

**Files:**
- `src/backend/app/access/grants.py` — new. Mutators, the publish, the after-commit queue, and the watch.
- `src/backend/app/access/cache.py` — new. The key scheme and the race-safe invalidation.
- `src/backend/app/access/share.py` — the lazy expiry bump; `grant_id` on the Share Link ctx.
- `src/backend/app/access/visibility.py` — invalidation delegates to cache.py.
- `src/backend/app/access/context.py`, `__init__.py` — the `grant_id` docs and the exports.
- `src/backend/app/api/routes/campaigns.py` — revoke, remove, leave and delete use the mutators.
- `src/backend/app/api/routes/chat.py` — the stream watches its grant.
- `src/backend/app/services/cache_service.py` — deleted.
- `src/backend/tests/access/test_grants.py` — new. The matrix, the stream, the cache, the worker `permission_changed`, and the AST guards.
- `src/backend/tests/ev4/probes/grants.py` — new EV-4 probes: demote and remove mid-stream, removed JWT, revoked link.
- `src/backend/tests/access/test_set_visibility.py`, `src/backend/tests/test_llm_provider_gate.py` — fakes adjusted.

**Review:**
- 30 findings: 16 patched (in 13 entries), 1 deferred, 13 rejected, each with its reason in the triage log.
- Patched by entry verdict: medium 3, low 10, high 0.
- followup_review_recommended: true. Three medium entries were patched in the stream lifecycle. The named unverified risk: the cancellation path is tested only through httpx's ASGITransport, so a real client disconnect under uvicorn and nginx is untested (whether `_cancel` re-raising, the slot release and the upstream close behave the same there).

**Verification:**
- Desktop, own Postgres and Valkey:
  - backend suite: 1619 passed, 4 skipped (main: 1556 passed, 4 skipped);
  - EV-4: probes=84, pending=46, leaks=0;
  - `check_scoped_queries.py`: ok;
  - `lint-imports`: 5 kept, 0 broken.
- GitHub CI on draft PR #60 is the gate.

**Residual risks:**
- No route caches anything yet (`cached_json` has no callers).
- The members PATCH route and archive-on-demotion are E0-Access.12.
- Admin user deletion relies on the poll (deferred).

**Needs desktop verification:**
- A real client disconnect mid-stream behind nginx. Open `POST /api/chat/stream` with curl, kill curl mid-stream, and check that the `llm_gate` slot is released and no `grant_watch` pubsub connection stays open (`valkey-cli CLIENT LIST | grep sub=`).

**Sprint sync:** skipped per the builder brief.
