---
title: 'E0-Access.9: set_visibility, the only Visibility writer'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '0e71df48f047b03fa4f8ad48d76ec76a218ea8c0'
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
