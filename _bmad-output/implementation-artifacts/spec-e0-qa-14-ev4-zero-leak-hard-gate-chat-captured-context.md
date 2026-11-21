---
title: 'E0-QA.14: EV-4 is a zero-leak hard gate, with chat and captured-context probes'
type: 'feature'
created: '2026-11-21'
status: 'in-progress'
baseline_revision: 'fadca8ae75f41f41afe5371e73c5b422702c93b1'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** EV-4 already fails on leaks, unprobed routes and pending lines, but a captured-context check can still *skip* (and a skipped probe passes the gate). The chat probes ask only one question, so they never show that Shorthand, a GM-only entry, a source document or the glossary stays out of a Player's prompt. Nothing probes a demoted Co-GM's chats. A Player's Job retry that collides with a hidden Job's idempotency key gets a 409, and that reveals the hidden Job exists. `docs/SPOILER_EVAL.md` and `scripts/eval_spoiler.py` don't exist.

**Approach:**
- Make every EV-4 skip a failure.
- Move the chat POST probes into `tests/ev4/probes/chat.py`. Give them a question for each hidden source, a GM positive control and forbidden-marker checks on the captured context, and add a demotion probe.
- Fix the leaks they find in product code.
- Make a retry against a hidden key holder look exactly like a normal retry.
- Add the live-model spoiler eval script and its doc.

## Boundaries & Constraints

**Always:**
- Leaks are fixed in product code: reads go through `app/access/` (role map, `scoped_select`).
- Edits to `families.py`, `_support.py` and `exemptions.yaml` are additive. New kwargs get defaults, so existing callers are unchanged.
- Hidden ≡ missing is compared on status, body and headers.
- Every captured-context check is non-vacuous: a GM run of the same question must capture the hidden content.

**Never:**
- No baseline lines (CI-8 or EV-4) and no exemptions to pass the gate.
- No edits to sibling files: entities/world probes, `lib/sse.ts`, compose files, journal writers.
- No changes to `sprint-status.yaml`, `epics.md` or `desktop-verification-queue.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Player asks a question answered only by Shorthand, a GM entry, a source doc or the glossary | POST `/api/chat/` and `/stream`, campaign A | No canary in the body, SSE `meta`/`delta`/`done` or trace. The captured prompt has no glossary block, canon block, `Notes` line or plain Shorthand / secret text | — |
| GM positive control | gm_owner, same questions | Captured prompt holds the glossary block, Notes, canon block and the GM-entry canary | probe misuse → ValueError |
| GM-only change between two Player asks | Shorthand edit, new GM entry and Private entry | Identical trace: candidates incl. gated-out, sources, canon sources, citations, the fake reply digest | leak |
| Demoted Co-GM | live sessions in A, then PATCH role → player | List omits them; GET and POST with `session_id` ≡ missing; a new A message's prompt holds no archived turn | 404 |
| Demoted Co-GM, campaign-less chat | a source doc they uploaded in A while Co-GM | No A canon in the prompt, `canon_sources` or trace | — |
| Retry, key held by a hidden active Job | Player's own failed Job; the Owner's queued Job has the same key | 202 `{"job_id": own}`, same as with no holder. The row is `queued`, held behind the holder; the holder is untouched | — |
| Retry, key held by a visible active Job | the actor's own active Job holds the key | 409 KEY_IN_USE (unchanged) | 409 |
| Capture hook missing or probe skipped | — | EV-4 run fails | exit 1 |

</intent-contract>

## Code Map

- `src/backend/tests/ev4/families.py:217` `assert_captured_context_clean`: skips when `capture` is missing. Gets `forbidden=` and `min_calls=`.
- `src/backend/tests/ev4/conftest.py`: `pytest_sessionfinish` failure reasons. Add the skipped-probe reason.
- `src/backend/tests/ev4/probes/retrieval.py:200-245`: `_chat_probe`, `probe_chat`, `probe_chat_stream`. These move to `chat.py`; the index helpers stay.
- `src/backend/tests/ev4/probes/chat.py`: sessions probes. It gains the POST probes and the demotion probe.
- `src/backend/app/api/routes/chat.py:350-358`: the campaign-less canon `retrieve_canon_context(db, q, user.id, None)` reads every chunk the user uploaded, in any Campaign. This is the leak.
- `src/backend/app/services/source_service.py:41`: `retrieve_canon_context`. It is listed in the CI-8 baseline, and the filter change keeps that line valid.
- `src/backend/app/services/retrieval_service.py:132`: `hybrid_search_own_journals(roles=)` is the pattern for the campaign-less canon fix.
- `src/backend/app/jobs/control.py:92` `retry_job`: the global holder check gives 409.
- `src/backend/app/jobs/outbox.py:173` and `worker.py:162`: a `depends_on_job_id` hold, released when the dependency ends.
- `src/backend/app/services/chat_service.py:93` `build_chat_messages`: the glossary, canon and `Notes` markers.
- `src/backend/scripts/eval_common.py`: `build_parser`, `write_regions`, `format_table`, `ResultTable`.
- `seeds/ev4_canary.json`: the Shorthand, TERM, SOURCECHUNK and CHAT canaries.

## Tasks & Acceptance

**Execution:**
- `tests/ev4/families.py`:
  - A missing `capture` fails instead of skipping.
  - Add `forbidden: Iterable[str] = ()`: each substring found in the captured prompt is a leak.
  - Add `min_calls: int = 0`: fewer captured calls raises ValueError (probe misuse).
- `tests/ev4/test_families.py`: self-tests for the no-skip, `forbidden` and `min_calls` behaviour.
- `tests/ev4/conftest.py`: any skipped `test_probes.py` case fails the run, with a reason that names it.
- `tests/ev4/test_coverage.py`: the uncovered-route message names `tests/ev4/probes/`.
- `tests/ev4/probes/chat.py`:
  - The POST probes, with five questions: inn, Shorthand, GM entry, source doc and glossary.
  - A GM positive control and forbidden markers.
  - The trace now includes the reply.
  - A demotion probe on both POST routes (actor `co_gm`).
- `tests/ev4/probes/retrieval.py`: drop the moved probes.
- `app/services/retrieval_service.py` and `app/api/routes/chat.py`: campaign-less canon reads only chunks with no Campaign, or in Campaigns the role map makes the user GM of.
- `app/services/source_service.py`: add an optional `campaign_ids` filter for the campaign-less case.
- `app/jobs/control.py`:
  - A holder visible to the ctx (`scoped_select(Job, ctx)`) still gives 409.
  - A hidden holder: the row gets a per-retry key (`{key}#retry:{id}`), `depends_on_job_id = holder` (locked FOR SHARE), is `queued` and not pushed.
  - A lost race on the index re-runs the check.
- `tests/test_job_routes.py`: tests for the hidden holder (202, held, released when the holder ends) and the visible holder (409).
- `tests/ev4/probes/jobs.py`: a retry probe where a hidden holder answers like no holder.
- `scripts/eval_spoiler.py`: a live-model spoiler eval.
  - Seed the canary Campaign and add a Player.
  - Ask every case on both endpoints under `capture()`.
  - Count probes, canary leaks, context-marker leaks and inference-channel diffs (trace before and after a GM-only change), plus secret-answer words in the reply.
  - Write `docs/SPOILER_EVAL.md` regions. Exit 1 on any leak.
- `tests/test_eval_spoiler.py`: runs the eval with the fake provider (0 leaks), plus a planted-leak self-test.
- `docs/SPOILER_EVAL.md`: RETRIEVAL_EVAL format, with the reproduce command.
- `.github/workflows/gates.yml`: rewrite the CI-12 comment to describe the hard gate.

**Acceptance Criteria:**
- Given the EV-4 run in CI, when any probe leaks, skips, a route is uncovered or `pending_baseline.txt` has a line, then the step fails. The uncovered-route message names the route and `tests/ev4/probes/`.
- Given the chat probes as `player`, when they run, then `leaks=0` and every captured-context check saw at least one call.
- Given the live run on the desktop, when `eval_spoiler.py` runs against Ollama `lorekeeper`, then `docs/SPOILER_EVAL.md` records the probe count, leaks (target 0), the inference-channel checks and the command.

## Design Notes

**Retry and hidden holders.** A hidden holder can only be a Job of another starter: the holder is in the same Campaign but not the Player's own, or it is in another Campaign. Answering 202 while the row waits behind the holder looks the same as a normal retry sitting in a busy queue:
- `queue_position` counts only visible Jobs;
- `depends_on_job_id` is never serialised.

The per-retry key keeps the partial unique index satisfied. The work runs again after the holder ends. Kinds are idempotent on content-derived keys, so the repeat costs time but not correctness.

**Campaign-less canon.** The fix mirrors `hybrid_search_own_journals`: the user's own uploads, restricted to Campaigns where they are GM now.

## Verification

**Commands:**
- `pytest tests/ev4 tests/test_job_routes.py tests/test_eval_spoiler.py -q` (CI). Expected: pass, EV-4 leaks=0, pending=0.
- `python ../../scripts/check_scoped_queries.py`. Expected: clean.

**Environment limits (this machine):** never start Postgres, Valkey or Redis on this Mac and never install anything outside the worktree. The pytest suites need those servers, so they run in GitHub CI, which is the gate. Locally, run only static checks:
- `python -m py_compile` on every changed file;
- `python ../../scripts/check_scoped_queries.py` from `src/backend`;
- the pure-Python self-tests that need no database (`tests/ev4/test_coverage.py`, `tests/ev4/test_families.py`), if their imports work.

Write the tests so they pass on CI's Postgres + Valkey with `ENVIRONMENT=test` and `JOBS_EAGER=1`, using the fixtures in `tests/conftest.py`: `client`, `db`, `fake_llm`.
