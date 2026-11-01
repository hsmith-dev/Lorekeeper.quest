---
title: 'E0-Access.10: Grant changes bump access_epoch and close open streams'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: 'a55c32d30ed3742c4ce99bc562a6dc79d7efcd53'
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
