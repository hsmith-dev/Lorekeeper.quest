---
title: 'E0-Access.9: set_visibility, the only Visibility writer'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '0e71df48f047b03fa4f8ad48d76ec76a218ea8c0'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      A reader that computed a Player result before a downgrade commits can write it to the cache after the post-commit SCAN/UNLINK.
    evidence: |-
      invalidate_campaign_cache deletes cache:{campaign_id}:* after commit. Nothing stops a slower concurrent reader from setting a key afterwards. No such cache exists today; E0-Access.10 owns the key scheme (audience + access_epoch) and should add a per-Campaign visibility generation, or bump the epoch on a Visibility change.
    location: >-
      src/backend/app/access/visibility.py invalidate_campaign_cache
    severity: medium (unverified)
  - summary: >-
      The after-commit listener and cache dispatch has no timeout, so a hung listener or Valkey blocks db.commit().
    evidence: |-
      _after_commit runs await_only(dispatch(...)). No listener is registered yet, and Valkey calls fail fast on a down server. A hang needs a stuck listener (E0-Journal) or a half-open Valkey socket. Add asyncio.wait_for when the first real listener lands.
    location: >-
      src/backend/app/access/visibility.py _after_commit
    severity: low
  - summary: >-
      The CI-8 merge allowance covers all of world_service.apply_change, not only op="merge" under a merge system ctx.
    evidence: |-
      The check is lexical (function scope plus column). The story names the function. Checking the op or ctx statically would need E0-WorldCore's code to exist. Revisit when E0-WorldCore.3/.9 land.
    location: >-
      scripts/check_scoped_queries.py VISIBILITY_WRITE_ALLOWED
    severity: low
---

<intent-contract>

## Intent

**Problem:** Nothing owns Visibility changes. A GM can't deliberately publish or hide a record, nothing invalidates content derived from a record when it is hidden, and nothing stops any module from writing a `visibility` column directly.

**Approach:** Add `app/access/visibility.py`. It holds `set_visibility` (the one writer, with a registry `writer` slot for Canon tables), the extension points `register_stale_marker` and `register_visibility_listener`, the shared `mark_dependents_stale` helper, and after-commit cache invalidation. Add the bulk route `POST /api/campaigns/{campaign_id}/visibility` returning `{updated: n}`, and a CI-8 rule in `scripts/check_scoped_queries.py` that fails on any Visibility write outside `app/access/`, except the one sanctioned merge `visibility_floor` write.

## Boundaries & Constraints

**Always:**
- Only a writable GM user ctx may change Visibility. That rules out Player, anon, read-only (`audience_ctx`, preview) and system ctxs. Every one of those denials is `not_found()`. In preview the route is already 404 because of `require_campaign`.
- A ref is valid only if its kind maps to a registered `stored` model with a Visibility column and its row is in `ctx.campaign_id`. For `journal`/`player_journal` the entry's `kind` must also match. Anything else is `not_found()`, the same as a missing row.
- `always_gm` models, `ALWAYS_GM_FIELDS` and model `gm_fields` raise 422 `{"detail":"This is always GM-only","code":"always_gm"}`.
- Order of work. The write runs first (through the model's `writer` when one is registered). Next comes `mark_dependents_stale(db, [ref])`, which calls every stale marker `(db, ref)` in registration order inside the caller's transaction. After the root transaction commits, each listener is called once per Campaign with `(campaign_id, refs, actor_ctx)`, and then `cache:{campaign_id}:*` is deleted from Valkey. On rollback, listeners and cache work are discarded.
- The bulk route takes 1–500 items and is all-or-nothing: any 404 or 422 rolls back every item. Duplicate items count once.
- CI-8 ratchet: never add a baseline line. Keep the new section separate from `OWNER_INFRA`, and freeze the allowlist in a test.

**Never:**
- Don't change Player write rules or `can_write` (that is E0-Access.6). Don't touch `app/jobs/` (E0-Jobs.4), stt (E0-Platform.5), `epics.md` or `sprint-status.yaml`.
- Don't publish on `access:` channels or bump `access_epoch` (that is E0-Access.10).
- Don't flag constructor kwargs (`Model(visibility=...)`). A create sets an initial value, which `check_create` gates; it is not a change.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM single | GM ctx, party entry → gm | entry gm; projected GM body returned; markers ran | — |
| Bulk | GM, 3 items, value gm | `200 {"updated":3}`; all committed | — |
| Missing / other Campaign / wrong journal kind | any one item | 404 Not found; nothing written | rollback |
| always_gm | `npc`/`quest` item, or `field="shorthand"`/`gm_notes` | 422 always_gm; nothing written | rollback |
| field on a model without field visibility | `field="title"` on session_plan | 422 `no_field_visibility` | rollback |
| Player / anon / preview | any | uniform 404 | — |
| Body over 500 items / empty / unknown kind | — | 422 (pydantic) | — |
| Downgrade | Player read party entry; GM flips to gm | next Player read, list, count, search and chat context exclude it | — |

</intent-contract>

## Code Map

- `src/backend/app/access/registry.py` -- `Stored` dataclass (l.94) and `stored()`: add `writer`. `REGISTRY`, `registration`, `scoped_select`, `scope_column`.
- `src/backend/app/access/audience.py:168` -- `ALWAYS_GM_FIELDS`.
- `src/backend/app/access/projection.py` -- `project_all(db, [obj], ctx)` builds the returned record. A JournalEntry needs `tags`+`custom_category` loaded (see `journals.py:47 _ENTRY_TAGS`).
- `src/backend/app/access/sources.py` -- the built-in journal kind filters (`JournalEntry.kind == gm/player`) to mirror.
- `src/backend/app/schemas/sources.py` -- `SourceRef`. This file is append-only: add `RecordRef {kind:str, id, field?}`.
- `src/backend/app/jobs/outbox.py:185-245` -- the after_commit / soft-rollback / transaction-end listener pattern (await_only inside the greenlet) to copy. Read-only.
- `src/backend/app/core/valkey_client.py` -- `get_valkey()` raises RuntimeError when uninitialised, which it is in tests. Treat that as "nothing cached".
- `src/backend/app/access/__init__.py` -- export the new API.
- `src/backend/app/main.py:136` -- mount the new router at `/api/campaigns`; register the `VisibilityError` handler next to the LLMError handler (l.65).
- `scripts/check_scoped_queries.py` + `scripts/test_check_scoped_queries.py` -- CI-8. Mirror the `ALLOWED_SYSTEM_SITES` scoping (top-level function only).
- `src/backend/tests/ev4/probes/_support.py`, `families.py`, `probes/retrieval.py` (`fake_embeddings`, `index_seeded`, `_index`, `use_fake_llm`) -- EV-4 helpers; `llm_provider.capture()` exists.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/sources.py` -- add `RecordRef`.
- `src/backend/app/schemas/visibility.py` -- `VisibilityItem`, `BulkVisibilityRequest` (items 1–500, `value: Visibility`), `BulkVisibilityResponse {updated:int}`.
- `src/backend/app/access/registry.py` -- `Stored.writer` plus `stored(writer=)`.
- `src/backend/app/access/visibility.py` -- the kind map (`register_visibility_kind`), `VisibilityError`, `set_visibility`, `set_visibility_many`, `register_stale_marker`, `register_visibility_listener`, `mark_dependents_stale`, and the session listeners for post-commit listeners and cache invalidation.
- `src/backend/app/access/__init__.py` -- exports.
- `src/backend/app/api/routes/visibility.py` -- the bulk route (`require_campaign("gm")`), which commits.
- `src/backend/app/main.py` -- router and handler.
- `scripts/check_scoped_queries.py` -- the Visibility-write rule and `VISIBILITY_WRITE_ALLOWED = {("app/services/world_service.py","apply_change"): {"visibility_floor"}}`.
- `scripts/test_check_scoped_queries.py` -- planted-violation, allowlist and frozen-allowlist tests.
- `src/backend/tests/access/test_set_visibility.py` -- unit and API tests for the matrix, call order, writer slot, field paths and rollback.
- `src/backend/tests/ev4/probes/visibility.py` -- an EV-4 probe for the route (anon_share, player, cross_gm_player, co_gm), plus the downgrade suite: after the downgrade, the Player's detail, list, search and chat capture are checked.

**Acceptance Criteria:**
- Given a registered stale marker and listener, when a GM bulk-downgrades, then the recorded order is write, marker, commit, listener, cache-invalidate. With none registered, the change still commits.
- Given a model whose registry entry names a `writer`, when `set_visibility` targets it, then the writer is called and the column is not written directly.
- Given a planted `x.visibility = ...`, `setattr(x, "field_visibility", ...)`, `.values(visibility=...)` or raw `UPDATE ... SET visibility =` outside `app/access/`, then `check_scoped_queries.py` fails. A `visibility_floor` write in `world_service.apply_change` passes, and the same write anywhere else fails.

## Design Notes

- Listeners run after commit, which follows the spine's hook rule ("dispatched by an after_commit listener, discarded on rollback"). Their signature has no `db`, so they can't join the transaction, and running them post-commit means a rolled-back change emits nothing. Stale markers get `db` and run inside the transaction.
- `{updated: n}` is the number of distinct items written, unchanged values included. The UI doesn't claim specific counts.
- Field writes: `field=None` sets the stored column. `field="visibility_floor"` sets that column when the model has one. On a model with `field_visibility`, any other column sets `field_visibility[field]`; a new dict is assigned so JSONB change tracking sees it. Writers receive `field` as `"visibility"`, `"visibility_floor"` or `"field_visibility.<key>"`.
- Cache keys: E0-Access.10 must start every Campaign cache key with `cache:{campaign_id}:`. This story deletes that prefix after commit (SCAN+UNLINK), and a Valkey error is logged, never raised.

## Verification

**Commands:**
- `python scripts/check_scoped_queries.py` -- expected: ok
- `python -m pytest -q scripts/test_check_scoped_queries.py` -- expected: all pass
- `pytest -q` on the desktop (own Postgres+Valkey) -- expected: no regressions; EV-4 leaks=0

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 40 findings — high 0, medium 4, low 24, false 7, maybe-false 5
- findings:
  - Blind hunter:
    - `[low]` `patch` The `writer` slot conflicts with the CI allowance for apply_change — added a comment by VISIBILITY_WRITE_ALLOWED: a writer writes `visibility`/`field_visibility` through its generic field update (variable-name setattr), and the allowlist stays as the story fixes it.
    - `[low]` `patch` Stale markers run twice if a writer also marks staleness — the `Stored.writer` contract now says a writer must not call mark_dependents_stale.
    - `[false]` `reject` visibility_floor is not protected against a looser visibility — the floor is applied at read time (`mention_audience` uses most_restrictive), so a looser row value cannot widen floored content.
    - `[low]` `reject` Values are not checked per kind/field — `private` on a GM entry is defined behaviour (Owner(author), AD-12). A rule would add branches the story never asked for.
    - `[low]` `reject` Unchanged values still mark stale and invalidate — spec choice; it is harmless (extra invalidation only).
    - `[low]` `reject` 500 items cost about 1000 queries, with no rate limit — a GM-only op, bounded at 500; acceptable for v1.
    - `[maybe-false]` `defer` A concurrent reader can re-cache after invalidation — no cache exists yet; deferred to E0-Access.10 (medium, unverified).
    - `[low]` `patch` The listener contract is undocumented (no session use; first ctx per Campaign) — documented in the register_visibility_listener docstring.
    - `[low]` `reject` A sync-session commit skips dispatch — the app has no sync sessions; the warning is logged.
    - `[false]` `reject` The Campaign check assumes `campaign_id` — every registerable stored model uses `campaign_id`, and scoped_select already scopes by scope_column.
    - `[medium]` `patch` The CI-8 visitor misses Query.update, `**values`, execute-with-dicts, nested subscripts and loop/with targets — all are now flagged, with planted tests. `execute` is narrowed to `update(...)` statements so read bind dicts pass (with a test).
    - `[low]` `patch` insert().values is flagged but constructors pass — documented as deliberate in the module docstring.
    - `[low]` `reject` The SET regex can be cut short by `from` inside a string literal — rare; a full SQL parser is out of proportion.
    - `[false]` `reject` The allowlist is never checked against real code — apply_change doesn't exist yet by design (E0-WorldCore). A stale-entry check would fail today.
    - `[low]` `patch` Dedupe on the raw ref double-counts `field=None` vs `field="visibility"` — `dedupe_targets` keys on (kind, id, path), with a test. The import-order and OpenAPI-enum parts: `[false]`, because the schema is imported only via the route, which imports app.access first.
    - `[false]` `reject` Test gaps: the downgrade suite is gated on `authenticated` — the authenticated non-GM actors (player, cross_gm_player) are both Players of A. A malformed Mapping is an internal-API programming error, not a request path.
  - Verification gap:
    - `[medium]` `patch` A generic PUT `setattr(row, field, value)` loop would write visibility if an Update schema gained the field — added test_no_create_or_update_schema_declares_a_visibility_column.
  - Edge-case hunter:
    - `[medium]` `patch` ORM bulk update via execute/bulk_update_mappings is missed — flagged (grouped with the blind-hunter CI-8 row).
    - `[medium]` `patch` Legacy Query.update dict is missed — flagged (same group).
    - `[low]` `patch` `.values(**{})` / `dict()` are missed — flagged (same group).
    - `[low]` `reject` A subquery FROM inside SET ends the capture — rare, and paren tracking is out of proportion.
    - `[low]` `reject` SQL held in a variable — needs dataflow; unlikely in this codebase (raw SQL is rare and literal).
    - `[low]` `patch` A nested field_visibility subscript is missed — flagged (same group).
    - `[low]` `patch` for/with/comprehension targets are missed — flagged (same group).
    - `[low]` `reject` A non-UTF-8 file crashes the checker — the existing checks in the same script read files the same way.
    - `[maybe-false]` `reject` A writer that deletes the row gives a 500 on reload — no writer exists; E0-WorldCore's update_field never deletes.
    - `[low]` `patch` A duplicate row via a different field spelling is counted twice — fixed by dedupe_targets.
    - `[low]` `reject` A structural column used as a field_visibility key — no model has field_visibility yet; E0-WorldCore defines its keys.
    - `[low]` `reject` Re-registering a kind with a different where is silently ignored — kinds are registered once at import.
    - `[low]` `reject` A bad Mapping ref gives a pydantic error — the internal API; the route validates first.
    - `[maybe-false]` `defer` A listener or Valkey hang blocks commit — deferred (low).
    - `[maybe-false]` `defer` A reader re-caches after invalidation — same as the blind-hunter row; deferred to E0-Access.10.
    - `[low]` `reject` Two actors in one transaction — one request has one actor; documented as "first change's ctx".
    - `[low]` `reject` CancelledError in dispatch — cancellation mid-commit is an operator abort.
    - `[medium]` `patch` Claim: the CI-8 rule does not catch every form — the same group as the CI-8 visitor patch.
  - Intent alignment:
    - `[false]` `reject` The staleness path is not exercised with a real marker — by design: E0-Jobs.8 registers the derived_sources marker. The seam and its order are tested with fakes.
    - `[false]` `reject` The cache key scheme doesn't exist — E0-Access.10 owns it. The `cache:{campaign_id}:` prefix contract is documented and invalidation is tested against a fake Valkey.
    - `[low]` `patch` A lexical CI rule misses dynamic setattr — covered by the schema guard test (verification-gap row).
    - `[low]` `patch` The writer slot vs the frozen allowlist — same as the blind-hunter row (comment added).
    - `[maybe-false]` `defer` The merge allowance doesn't check op or ctx — deferred (low).

## Auto Run Result

Status: done

**Summary:**
- `app/access/visibility.py` is the one Visibility writer:
  - `set_visibility` / `set_visibility_many`: GM-only; uniform 404; 422 `always_gm`; a registry `writer` slot; field and floor paths.
  - The `register_stale_marker`, `register_visibility_listener` and `mark_dependents_stale` seams. Markers run in the transaction. Listeners, then `cache:{campaign_id}:*` invalidation, run after commit, and are discarded on rollback, savepoint-aware.
- The bulk route `POST /api/campaigns/{campaign_id}/visibility` returns `{updated: n}`: 1–500 items, all-or-nothing.
- CI-8 rule in `scripts/check_scoped_queries.py`: no Visibility write outside `app/access/` except `world_service.apply_change` writing `visibility_floor`. It has a frozen allowlist, no baseline, and is separate from OWNER_INFRA.
- EV-4: a route probe plus the downgrade suite. After a party→gm flip, the Player's next detail, list and count, search and chat prompt (`llm_provider.capture()`) all exclude the entry.

**Files:**
- `src/backend/app/access/visibility.py` — new: the writer, the seams and the after-commit dispatch.
- `src/backend/app/access/registry.py` — `Stored.writer` and `stored(writer=)`.
- `src/backend/app/access/__init__.py` — exports.
- `src/backend/app/schemas/sources.py` — `RecordRef` (append-only).
- `src/backend/app/schemas/visibility.py` — new: the bulk request and response.
- `src/backend/app/api/routes/visibility.py` — new: the bulk route.
- `src/backend/app/main.py` — router and the VisibilityError handler.
- `scripts/check_scoped_queries.py`, `scripts/test_check_scoped_queries.py` — the CI-8 Visibility-write rule and its tests.
- `src/backend/tests/access/test_set_visibility.py` — new: unit and API tests.
- `src/backend/tests/ev4/probes/visibility.py` — new: the EV-4 probe and downgrade suite.

**Review:**
- 40 findings: 15 patched, 3 deferred (in frontmatter), 22 rejected, each with a reason in the triage log.
- Patched by verdict: medium 4, low 11, high 0.
- followup_review_recommended: false. No high was patched. The medium patches are all one CI-8 group plus the schema guard, and both are covered by tests that ran.

**Verification:**
- The desktop backend suite (own Postgres and Valkey): 1516 passed, 4 skipped (main: 1488 passed, 4 skipped); EV-4 probes=81, pending=46, leaks=0.
- `python scripts/check_scoped_queries.py`: ok. `pytest scripts/test_check_scoped_queries.py`: 107 passed. `lint-imports`: 5 kept, 0 broken.
- The GitHub CI on draft PR #56 is the gate.

**Residual risks:**
- No stale marker or listener is registered yet (E0-Jobs.8 and E0-Journal.1 add them).
- No cache keys exist yet (E0-Access.10 must use the `cache:{campaign_id}:` prefix).
- The CI-8 rule is lexical, so dynamic SQL in variables is not caught.

**Needs desktop verification:** none. Everything ran against real Postgres and Valkey containers on the desktop.

**Sprint sync:** skipped per the builder brief; the orchestrator updates sprint-status.yaml and epics.md.
