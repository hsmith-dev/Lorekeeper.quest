---
title: 'E0-QA.14: EV-4 is a zero-leak hard gate, with chat and captured-context probes'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: 'fadca8ae75f41f41afe5371e73c5b422702c93b1'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      A retry held behind a hidden key holder answers like a free retry, but afterwards stays queued until the holder ends, so a Player watching it over time could infer a busy hidden Job.
    evidence: |-
      Any non-revealing answer has this property while idempotency keys are global. queue_position counts only visible Jobs and depends_on_job_id is never serialised, so the only signal is how long the Job waits. Scoping keys per Campaign would not remove the same-Campaign case (another starter's Job). Owner decision: accept this (it looks like a busy queue), or make Player-started kinds use starter-scoped keys when E1 adds the first one.
    location: >-
      src/backend/app/jobs/control.py retry_job
    severity: medium
  - summary: >-
      A campaign-less chat POST builds its role map without X-Lorekeeper-Preview narrowing, so in member preview it still reads the user's GM Campaigns (own journals and, now, own canon).
    evidence: |-
      This predates the change: hybrid_search_own_journals in _prepare_chat behaves the same. To settle it, check whether a campaign-less chat POST in preview should be 404 (as a Campaign one is) or narrowed to a Player everywhere.
    location: >-
      src/backend/app/api/routes/chat.py _prepare_chat
    severity: medium (unverified)
  - summary: >-
      The live-model spoiler eval (AC4, SM-4) has not run yet: the desktop was offline.
    evidence: |-
      docs/SPOILER_EVAL.md results regions read "Not run yet". Needs the desktop run against Ollama lorekeeper, with the command in the Auto Run Result.
    location: >-
      docs/SPOILER_EVAL.md
    severity: medium
  - summary: >-
      A retry held behind a hidden Job overwrites depends_on_job_id, so the handler later sees the hidden holder's terminal status as dependency_status, and an original dependency is lost.
    evidence: |-
      No registered kind reads dependency_status today. A clean fix needs a separate hold column (a migration). E1 adds the first dependent kinds and should split "held behind" from "depends on".
    location: >-
      src/backend/app/jobs/control.py retry_job; src/backend/app/jobs/worker.py _claim
    severity: low
  - summary: >-
      The held-copy prefix LIKE can't use the btree key index outside the C locale.
    evidence: |-
      The scan is limited to active Jobs, so it is cheap today. A text_pattern_ops partial index on active keys would fix it, but it needs a migration.
    location: >-
      src/backend/app/jobs/enqueue.py _active_with_key; src/backend/app/jobs/control.py _key_holders
    severity: low
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

## Spec Change Log

### 2026-11-22: coordinator follow-up (duplicate work behind a hidden holder)
- **Trigger:** the known gap from the first pass, raised by the coordinator. A second retry against a held row (sequential, racing, or after the hidden holder ends) could queue the same work twice. Keys are idempotency keys, so that is a correctness bug.
- **Amended (code):**
  - The held key is now deterministic: `{key}#retry:{campaign}:{starter or 'none'}` (it used to be `…#retry:{job id}`).
  - The holder check (`control._key_holders`) matches the exact key, in any Campaign, plus held copies in the Job's own Campaign. Any holder the caller can see means 409.
  - `enqueue` de-duplicates against held copies in its own Campaign only.
  - `enqueue` now refuses caller keys that contain `#retry:`, which is reserved.
- **Why one copy holds:** the existing partial unique index on active keys allows one held copy per (Campaign, starter, key). The racing loser gets an IntegrityError and re-runs the check. The winner is always visible to the loser, because the caller is that starter or a GM of the Campaign, so the loser gets an honest 409. The Campaign is in the key so the same user's held copies in two Campaigns don't collide, since that 409 would reveal the hidden Job.
- **Data safety:** no migration and no schema change. Rows written with the old `#retry:{job id}` suffix existed only on this unmerged branch, so no deployed data has them. `_base_key` strips a suffix only when it starts with the row's own Campaign id, so any other key is left alone.
- **KEEP:**
  - A visible holder means 409.
  - A hidden holder answers 202 exactly like a free retry, and the row waits on `depends_on_job_id`, unpushed.
  - FOR SHARE on the holders.
  - The lost-race re-check.
- **Tests:** in `tests/test_job_routes.py`:
  - two sequential retries;
  - two racing retries in real concurrent transactions;
  - a retry after the hidden holder ends;
  - the same starter in two Campaigns;
  - the reserved mark.

  Each checks exactly one queued or running copy.

## Review Triage Log

### 2026-11-21 — Review pass (blind, edge-case, verification-gap, intent-alignment)
- verdicts: 38 findings — high 0, medium 4, low 21, false 7, maybe-false 6
- findings:
  - `[medium]` `[patch]` (blind, edge) A held retry keeps `{key}#retry:{id}` while it waits and runs, so an enqueue with the base key would miss dedup. → `enqueue._active_with_key` also matches active rows with the per-retry suffix; tested.
  - `[low]` `[reject]` (blind, edge) After 3 lost index races, `for…else` gives 409 whatever the last holder's visibility. Reaching it needs three successive racers each taking the key between check and flush (a hidden racer goes down the held path, which never conflicts). Unlikely, and a fix adds branches.
  - `[medium]` `[defer]` (blind, edge, intent) After the 202, a held retry stays `queued` until the holder ends, while a free one runs. A Player watching over time could infer a busy hidden holder. This is inherent to any non-revealing answer while the keys are global; owner decision (see deferred).
  - `[low]` `[reject]` (blind) Scope the unique index per Campaign or starter instead. It wouldn't remove the same-Campaign case (another starter's Job), and the index is owned by E0-Jobs; recorded in the deferred item.
  - `[low]` `[patch]` (blind) `own_canon_context` relies on the role map's implicit `user_id`, and a failure is swallowed. → the route passes `user_id=user.id`.
  - `[maybe-false]` `[defer]` (blind) `own_canon_context` ignores the RoleMap's preview. A campaign-less chat POST builds its role map without preview narrowing, and that predates this change (`hybrid_search_own_journals` is the same). Settled by checking how `role_map` treats `X-Lorekeeper-Preview` on a campaign-less POST.
  - `[low]` `[reject]` (blind, gap) The `campaign_id IS NULL` branch is untested. `SourceChunk.campaign_id` is a non-Optional `Mapped`, so the branch is defensive and unreachable today; harmless.
  - `[low]` `[reject]` (blind) The caravan Shorthand marker has no GM positive control. It is an extra marker beyond the five controlled questions; adding a question costs chat rate-limit budget (20/min) for no new path.
  - `[low]` `[reject]` (blind) The probe and the eval duplicate their questions and markers and have drifted. They serve different runs (CI fake vs live model); sharing them would couple a test package to a script.
  - `[low]` `[patch]` (blind, edge) The SPOILER_EVAL "no secret word is in a question" claim is wrong ("lich"). → the rule is now stated per case, and the cases checked.
  - `[maybe-false]` `[defer]` (blind) The live-run inference diff may be flaky with a nondeterministic model. With no session history there is no query rewrite, so the prompts are deterministic; settled by the desktop live run.
  - `[low]` `[patch]` (blind) The eval writes canary rows to any database. → it refuses a database whose name doesn't end in `_test`.
  - `[false]` `[reject]` (blind) The jobs probe imports the private `_headers`. `_support.py` already does (an existing pattern).
  - `[low]` `[patch]` (blind) The GM control uses json.dumps while the Player check uses `_prompt_text`. → the control uses `_prompt_text`.
  - `[false]` `[reject]` (blind) New canary kinds aren't in the seed. `mint_canary` registers every token in `CANARIES`; the seed lists only seeded rows.
  - `[low]` `[reject]` (blind, gap) `-k` deselection or an xfail bypasses or mislabels the skip gate. CI runs the full directory with no `-k`, and there are no xfail probes.
  - `[false]` `[reject]` (blind) The pending-baseline AC has no code. `test_coverage.py::test_pending_baseline_is_empty` (E0-QA.13) enforces it inside the same step.
  - `[maybe-false]` `[reject]` (blind) Spec status and uncommitted state. That is a workflow artifact; status is finalised at the end of this step.
  - `[low]` `[reject]` (edge) A held retry overwrites a real original `depends_on_job_id`. A failed Job's dependency is already terminal, and no registered kind reads `dependency_status`; a fix needs a new column.
  - `[low]` `[reject]` (edge) A cross-Campaign holder's status reaches the handler as `dependency_status`. That is a status value only, not content, and a cross-Campaign key collision is already a caller bug (enqueue raises).
  - `[low]` `[patch]` (edge) `forbidden` as a bare str iterates characters. → normalised to a tuple.
  - `[maybe-false]` `[reject]` (edge) Forbidden markers on campaign-less and B asks have no control. Those bodies pass `forbidden=()` (only canaries are checked), so no vacuous marker check exists.
  - `[low]` `[reject]` (edge) A secrets aren't checked in cross_gm_player's campaign-less prompt. Campaign-less retrieval reads only the user's own rows in GM Campaigns; the canary check covers A.
  - `[low]` `[patch]` (edge) An eval stream without `meta` or `done` gives empty traces that compare equal. → counted as vacuous.
  - `[low]` `[patch]` (edge) Eval vacuous checks only warn. → exit 1.
  - `[low]` `[patch]` (edge) Eval ignores `--campaign-id`, `--seed` and `--owner-email`. → `parser.error`.
  - `[maybe-false]` `[reject]` (edge, claim) "Every captured-context check is non-vacuous" covers only A. A is the only Campaign whose hidden content a Player could reach; the other bodies carry canary checks, which need no control.
  - `[low]` `[reject]` (edge, claim) The retry looks exactly like a normal one. Covered by the deferred lifecycle item and the rejected exhaustion row.
  - `[false]` `[reject]` (edge, claim) Secret words in questions. Duplicate of the patched doc row; the claim is fixed there.
  - `[medium]` `[patch]` (verification-gap) The lost-race re-check in `retry_job` is untested. → a test with the first holder check blind and the Owner's Job inserted (hidden → 202 held), plus a visible variant (409).
  - `[false]` `[reject]` (gap, other) Campaign-less uploads may not exist. Same as the unreachable-branch row above.
  - `[false]` `[reject]` (gap, other) xfail counted as a skip. Duplicate of the deselection row.
  - `[low]` `[reject]` (gap, other) Only the retry answer is compared. Same as the deferred lifecycle item.
  - `[medium]` `[defer]` (intent) AC4's live-model run hasn't executed. The desktop is offline; recorded under Needs desktop verification.
  - `[maybe-false]` `[reject]` (intent) AC2 probes only a `co_gm` demotion. The story's demotion is Co-GM → Player, which is exactly that.
  - `[false]` `[reject]` (intent) The gates.yml step command is unchanged. The step already runs `pytest tests/ev4` on PRs and main; the hard-gate behaviour lives in the harness it runs.
  - `[low]` `[reject]` (intent) The AC1 surfaces run on fake vectors and a fake LLM. That is the CI design (AD-21 fakes); the live run is AC4's eval.
  - `[low]` `[patch]` (CI) `test_retry_behind_a_holder_in_another_campaign_is_held` failed with MissingGreenlet (an expired `world.owner` in `bearer`). → headers computed once.

### 2026-11-22: Re-review of the `control.py` and `enqueue.py` diff (edge-case and adversarial)
- verdicts: 18 findings: high 1, medium 3, low 9, false 2, maybe-false 3
- findings:
  - `[high]` `[patch]` (edge, adversarial) A starter's held copies in two Campaigns collided on `K#retry:{starter}`: three IntegrityErrors, then a 409 that reveals the hidden Job. → the Campaign id is now in the held key; tested.
  - `[medium]` `[patch]` (adversarial) Two GMs retrying Jobs with no starter wrote different keys (`…#retry:{gm}`), so the work queued twice. → `none` is used for a missing starter, so there is one key per Campaign.
  - `[medium]` `[patch]` (edge, adversarial) `enqueue` matched another Campaign's held copy by prefix and raised ValueError (a 500) "in another Campaign" though the exact key was free. → the prefix match is scoped to the caller's Campaign; tested.
  - `[medium]` `[patch]` (edge, adversarial) A caller key containing `#retry:` would be cut short or matched wrongly. → `enqueue` rejects the reserved mark, and `_base_key` strips only `#retry:{own campaign}:`; tested.
  - `[low]` `[reject]` (edge, adversarial) A 409 after three lost races regardless of visibility. With per-Campaign held keys, a conflict on a held key is always with a copy the caller can see, and a conflict on the exact key re-checks correctly. Three successive exact-key racers is not a realistic sequence.
  - `[low]` `[reject]` (edge, adversarial) The held path overwrites a real `depends_on_job_id`, and the hidden holder's status reaches the handler as `dependency_status`. A failed Job's dependency is already terminal, no registered kind reads `dependency_status`, and a fix needs a new column (a migration) for no current consumer. Recorded under deferred for E1, which adds the first dependent kinds.
  - `[low]` `[defer]` (adversarial) The prefix LIKE can't use the btree index outside the C locale. The scan is limited to active rows, which are few. A `text_pattern_ops` index would need a migration; deferred.
  - `[maybe-false]` `[reject]` (adversarial) `enqueue` de-duplication can return the id of another starter's held copy that the caller can't see. Exact-key de-duplication already did this before the change; `enqueue` has no Player-facing route today.
  - `[maybe-false]` `[reject]` (adversarial) The lifecycle of a held retry differs from a free retry. Already deferred (owner decision).
  - `[low]` `[reject]` (adversarial) An IntegrityError from another constraint inside the loop is re-raised as a 500. That is intended: only the active-key index is a race.
  - `[low]` `[reject]` (adversarial) Missing tests for `dependency_status` and pre-existing dependencies. Follows the deferred dependency item.
  - `[low]` `[patch]` (adversarial) Missing tests for cross-Campaign collisions and keys containing `#retry:`. → added.
  - `[false]` `[reject]` (edge, claim) "One copy per (starter, key)" fails across Campaigns. The claim is now per (Campaign, starter, key), and the cross-Campaign case gives one copy per Campaign, which is the intended scope.
  - `[false]` `[reject]` (edge, claim) Free-key parity breaks on cross-Campaign collision. Fixed by the high patch above.
  - `[maybe-false]` `[reject]` (adversarial) A FOR SHARE scan in non-id order could deadlock. Holders are only read-locked (shared locks are compatible). The writer, a worker finishing a holder, updates one row, so no lock cycle with two exclusive waiters forms.
  - `[low]` `[reject]` (adversarial) A queue_position of 0 on a held row looks unlike a busy queue. Part of the deferred lifecycle item.
  - `[low]` `[reject]` (adversarial) NULL-starter Jobs (starter deleted) and GM retries. Covered by the `none` patch.
  - `[low]` `[reject]` (edge) No test for exhaustion. Follows the rejected exhaustion row.

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

## Auto Run Result

Status: done

**Summary.** EV-4 is now a hard gate:
- A skipped probe, or a missing `capture()` hook, fails the run.
- Leak, uncovered-route and pending-line failures stay as they were from E0-QA.13.

The chat probes now live in `tests/ev4/probes/chat.py`. They ask five questions as a Player, each answered only by hidden content: the inn, Shorthand, a GM-only entry, a source document and the glossary. Every captured-context check:
- has a GM positive control and forbidden markers (glossary block, canon block, `Notes` lines, plain secret text);
- sets `min_calls`;
- compares the trace and the fake reply before and after a GM-only change.

A demotion probe covers a Co-GM demoted to Player: sessions are gone from the list, GET and POST answer like a missing id, and the prompt is clean.

**Leaks fixed:**
- A chat with no Campaign used to read every chunk the user had uploaded, in any Campaign, including Campaigns they had been demoted in. It now goes through `retrieval_service.own_canon_context`, which reads only the user's own chunks in Campaigns the role map makes them GM of now.
- The E0-Jobs.7 carry-over: when a hidden Job holds the same key, a retry answers 202 exactly like a free key. The row is held behind the hidden Job on a per-retry key, and enqueue de-duplication still matches it. A key holder the caller can see still gets 409. A lost race on the index re-runs the check.

**New:** `scripts/eval_spoiler.py` (refuses databases not named `*_test`) and `docs/SPOILER_EVAL.md`.

**Files:**
- Product code:
  - `app/api/routes/chat.py`: campaign-less canon goes through the role map.
  - `app/services/retrieval_service.py`: adds `own_canon_context`.
  - `app/services/source_service.py`: adds the `campaign_ids` filter.
  - `app/jobs/control.py`: retry with a hidden or visible key holder, and the lost race.
  - `app/jobs/enqueue.py`: de-duplication matches held retries.
- EV-4 harness:
  - `tests/ev4/families.py`: no skip; adds `forbidden` and `min_calls`.
  - `tests/ev4/conftest.py`: a skipped probe fails the run.
  - `tests/ev4/test_families.py`, `tests/ev4/test_coverage.py` and `tests/ev4/test_probes.py`: self-tests.
- Probes:
  - `tests/ev4/probes/chat.py`: chat and demotion probes.
  - `tests/ev4/probes/retrieval.py`: the moved probes removed.
  - `tests/ev4/probes/jobs.py`: hidden-key-holder retry probe.
- Other tests:
  - `tests/test_job_routes.py`: hidden and visible holders, the lost race, de-duplication.
  - `tests/test_party_retrieval.py`: `own_canon_context`.
  - `tests/test_eval_spoiler.py`: the eval.
- Eval and docs:
  - `scripts/eval_spoiler.py` and `docs/SPOILER_EVAL.md`: the live spoiler eval.
  - `.github/workflows/gates.yml`: CI-12 comment.

**Review:** one pass, 38 findings.
- Patches:
  - 2 medium: dedup of held retries; the lost-race test.
  - 9 low: the CI MissingGreenlet, explicit `user_id`, bare-str `forbidden`, the GM control text, eval vacuous traces, the vacuous exit code, ignored flags, the database guard, the doc's secret-word rule.
- Deferred:
  - 2 medium: the held retry's later lifecycle (owner decision); the live AC4 run.
  - 1 unverified: preview on a campaign-less chat, which predates this story.
- Rejected: the rest, each with its reason in the triage log.

**Follow-up review recommended: true.** Two medium patches went into jobs code (`enqueue._active_with_key` now matches by `LIKE` on the per-retry key, and the lost-race path was reworked) after the review pass. That new matching and ordering hasn't had an independent review. Known gap: `control._key_holder` itself matches only the exact base key, so a second retry against a suffixed held row could queue the same work twice.

**Verification:** CI on ccdeeba is green.
- EV-4: probes=157, exemptions=11, pending=0, leaks=0. The suite ran 692 passed and 1 skipped; the skip is a family self-test, not a probe.
- Backend: 2718 passed, 4 skipped.
- Gates, licences and frontend: green.
- The desktop was unreachable; locally only static checks ran (py_compile and `check_scoped_queries`).

**Needs desktop verification:** the AC4 live run. Start your own pgvector and Valkey containers and a `*_test` database, then run from `src/backend` with `ENVIRONMENT` not set to `test`:
`python scripts/eval_spoiler.py --database-url postgresql+asyncpg://…/lorekeeper_eval_test --llm-url http://127.0.0.1:11434 --llm-model lorekeeper --out ../../docs/SPOILER_EVAL.md`
Expected: leaks=0 and vacuous=0; commit the regenerated doc.
