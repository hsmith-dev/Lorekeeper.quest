---
title: 'E0-QA.13: EV-4 probes for every existing route'
type: 'feature'
created: '2026-11-20'
status: 'done'
baseline_revision: '2a355566b3cb3b06d8dba7afa5308c093149dc3d'
review_loop_iteration: 1
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      Feedback about a Campaign the submitter has since lost access to (a removed Member) is still accepted, but its campaign_id pointer is now dropped, so the admin inbox loses that research context.
    evidence: |-
      The old route comment wanted such feedback to stay submittable; it still is, only without the pointer. Keeping the pointer for former Members requires knowing they were ever a Member (no membership history table exists), and keeping it for anyone reopens the existence oracle. Owner decision.
    location: >-
      src/backend/app/api/routes/feedback.py submit_feedback
    severity: low
---

<intent-contract>

## Intent

**Problem:** `tests/ev4/pending_baseline.txt` still listed 55 routes with no EV-4 probe or exemption: the admin portal, auth, billing, feedback, health, settings and ingest. Nothing proved that they leak nothing across users or Campaigns.

**Approach:** Give every listed route a probe in `tests/ev4/probes/<area>.py` that uses only the harness families, or an exemption with a reason. Empty the baseline and add a test that keeps it empty. Fix any leak in product code through `app/access/`. The story's other ACs (AI routes, Player writes, Shorthand-only search) were already probed by the E0-Access stories, so they are mapped below rather than duplicated.

## Boundaries & Constraints

**Always:**
- Probes run as `anon_share`, `player` and `cross_gm_player`.
- Hidden ≡ missing, compared on status, body and headers.
- Canaries go in every other-user or other-Campaign field.
- Every admin-only route returns the uniform admin denial, the same as `GET /api/admin/users`.
- Changes to `exemptions.yaml` and shared helpers stay additive. The only removals are this story's own exemptions, once a probe replaced them.

**Never:**
- No baseline lines.
- No chat or captured-context probes. Those belong to E0-QA.14.
- No edits to sibling stories' probe files (`entities.py`, `world*.py`) or to sse/model clients.
- No raw selects on registered tables outside `app/access/` (CI-8).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Non-admin on any `/api/admin/*` | real target user / promo vs missing id | byte-identical to the `GET /api/admin/users` denial; no user, promo, config or message change; no model-server call | 401/403 |
| Feedback submit, unreachable Campaign | another owner's Campaign, a Campaign the actor was removed from, a missing id | 201, `campaign_id: null`, same body and headers; nothing stored as pointer; same queries for every id | IntegrityError race → retried without pointer |
| Feedback submit, reachable Campaign | Owner or any Member | 201, pointer kept | none |
| Per-user reads (me, settings, model status, evaluations, billing status) | another user's canary settings, evaluations, avatar, promo redemption | the caller's own data only; unchanged when the other user changes | anon: 401/403 |
| Per-user writes (avatar, tutorial, settings PUT, evaluate, redeem-promo) | another user's rows | only the caller's row changes | anon: 401/403 |
| Delete another user's evaluation | their id vs missing | the same 404, row kept | none |
| Redeem a code another user used up | exhausted code vs nonexistent code | the same 400 | none |
| Test Connection, no URL/key in body | other user's canary URL/key saved | provider gets the caller's own saved URL/key (or none) | none |
| Ingest image / voice / discord | caller upload; GM uploads canary text in between | answer depends only on the caller's bytes (ml / stt fakes); byte-identical before and after | anon: 401/403 |

</intent-contract>

## Code Map

- `src/backend/tests/ev4/registry.py`: `@ev4_probe`, `DEFAULT_ACTORS`, `check_coverage`.
- `src/backend/tests/ev4/families.py`: the family helpers. `assert_counts_and_ranking_unchanged` raises ValueError on a status ≥ 400.
- `src/backend/tests/ev4/probes/_support.py`: `assert_same_answer`, `outsider`, `row_count`, `MISSING`.
- `src/backend/app/main.py`: the admin router is mounted with `dependencies=[Depends(require_admin)]`. Auth, billing and settings are not account-gated.
- `src/backend/app/api/routes/feedback.py`: submit (the leak), plus the admin-only inbox and context.
- `src/backend/app/access/context.py`: `role_map(db, user)` runs two queries whatever the Campaign, while `ctx_for` runs one or two depending on whether the Campaign exists.
- `src/backend/app/clients/fakes.py`: `FakeMLClient.ocr` (UTF-8 decode) and `FakeSTTClient.transcribe` (sha256 of the bytes). Both are active under ENVIRONMENT=test.

## Tasks & Acceptance

**Execution:**
- `tests/ev4/probes/admin.py`: one probe per admin route. Each compares a real target with a missing one and with the uniform denial, checks that nothing changed, and spies on the model server. A sweep probe covers every registered `/api/admin*` route, and set equality makes drift fail.
- `tests/ev4/probes/feedback.py`: the submit probe compares hidden vs missing for an outsider and for a removed Member, and positively checks a Member's pointer. The inbox and context return the admin denial, with another user's id ≡ missing.
- `tests/ev4/probes/auth.py`: `me`, `avatar` and `tutorial-complete`.
- `tests/ev4/probes/billing.py`: `status` and `redeem-promo`.
- `tests/ev4/probes/settings.py`: all 7 settings routes.
- `tests/ev4/probes/ingest.py`: 3 routes, with the GM's canary upload as a positive control.
- `tests/ev4/exemptions.yaml`: register, login, forgot-password, reset-password, checkout, portal, webhook and health, each with a reason.
- `tests/ev4/pending_baseline.txt`: emptied. `test_coverage.py::test_pending_baseline_is_empty` keeps it that way.
- `app/api/routes/feedback.py`: keep the pointer only when the Campaign is in `role_map`. On an FK race, fall back to no pointer.
- `tests/test_feedback.py`: Owner and Member keep the pointer; missing → 201 with null; an outsider and a removed Member answer like missing.

**Acceptance Criteria (story) and where each is proven:**
- **AC1, pending baseline empty; every route probed or exempted.** Covered by this PR and the coverage gate. EV-4 now reports pending=0.
  - The three read families run where they can. The id-less per-user reads (`/api/auth/me`, `/api/billing/status`, `/api/settings/`, `/api/settings/model-status`, `/api/settings/evaluations`) have no id to hide, so they apply `assert_no_canary` and `assert_counts_and_ranking_unchanged`.
  - The admin-only reads (`/api/admin/*` GETs, `/api/feedback/`, `/api/feedback/{id}/context`) only ever answer with a denial. The counts family cannot run on an error response, so they apply `assert_no_canary` and hidden ≡ missing (real id vs missing id) plus equality with the uniform denial.
- **AC2, the GM authoring and AI routes return the missing-Campaign 404 for `player`.** Already covered and not duplicated:
  - `probes/ai_routes.py`: autocomplete, generate-draft, summarize-session, recap, npcs/extract, quests/suggest. Each refusal makes no LLM call.
  - `probes/authoring.py`: shorthand, session-plans (including generate), sources.
  - `probes/journals.py`: `probe_generate_journal`.
  - `probes/npcs.py` and `probes/quests.py`: `.../generate`.
  - `probes/write_rules.py`: generate-draft, campaigns generate-concept.
- **AC3, Player writes: forbidden ≡ missing, allowed writes give Party projections with no canary.** Already covered:
  - `probes/npcs.py::probe_update_npc` and `probes/quests.py` PUT.
  - `probes/journals.py::probe_attach_tag` and `probe_detach_tag` (own `kind=player` entry allowed, 201 with no canary).
  - `probes/character_sheets.py` PATCH, POST and DELETE, and `probes/write_rules.py`.
- **AC4, a word only in a GM entry's Shorthand doesn't move Player search or matching.** Already covered:
  - `probes/retrieval.py::probe_journal_search`: `gm_only_change` puts the word into a seeded entry's Shorthand, plus GM-only and Private entries.
  - `probe_npc_entries` and `probe_quest_entries`.
  - `probes/tags.py::probe_list_tags`: a Shorthand-source link to a visible tag does not move its count.

## Review Triage Log

### 2026-11-20 — Review pass (bmad-code-review: blind, edge, verification-gap, acceptance)
- verdicts: 27 findings — high 1, medium 4, low 12, false 4, rejected/defer 6
- findings:
  - `[high]` `[patch]` (acceptance, edge) The feedback fix still leaked through timing: `ctx_for` ran one query for a missing Campaign and two for a hidden one. → now `role_map(db, user)`, the same two queries for any id.
  - `[false]` `[reject]` (acceptance) `ctx_for` leaks through exceptions. Its only raise is NotFound, and pydantic has already typed the UUID. Moot after the `role_map` change, which raises nothing for an unknown id.
  - `[low]` `[patch]` (edge) The Campaign could be deleted between the check and the commit, causing an FK 500. → on IntegrityError, roll back and store the feedback without the pointer.
  - `[medium]` `[patch]` (acceptance, blind) `probe_test_connection` proved nothing, because the fake provider ignores the URL and key. → it now spies on the `LLMConfig` handed to the provider, and asserts it is the caller's own saved URL and key (or none), never the other user's canaries.
  - `[medium]` `[patch]` (blind, edge) No side-effect check on `POST /api/admin/models/install`. → `model_server_spy` refuses and records any `ollama_service.install_model_events` or `ollama_status` call during every admin probe.
  - `[medium]` `[patch]` (blind) The admin sweep only checked `swept >= N`. → it now asserts set equality with `ADMIN_ROUTES` plus `SWEEP_ONLY` (`jobs/stats`), so a new, renamed or removed admin route fails loudly.
  - `[low]` `[patch]` (acceptance, blind) The sweep used sample ids, not the real targets. → `_fill` substitutes the target user and promo ids.
  - `[low]` `[patch]` (blind) `_assert_untouched` hard-coded the user flags and skipped the display name and email. → it now snapshots the target user's row (suspended, reason, admin, access, source, display name, email) and compares.
  - `[medium]` `[patch]` (acceptance) The signed-in branch of the feedback submit probe compared no headers. → `_same_submit` now compares headers (bar content-length) as well as status and the stable body.
  - `[low]` `[patch]` (blind) The unauthenticated feedback branch skipped `check_denial`. → added.
  - `[low]` `[patch]` (blind) The removed-Member case was never probed. → `_former_member_campaign` adds the actor to a Campaign and removes them; that Campaign must answer like missing. Also in `tests/test_feedback.py`.
  - `[low]` `[patch]` (blind) No ordinary regression test for the feedback change. → `tests/test_feedback.py`, 3 tests.
  - `[low]` `[patch]` (blind, acceptance) `tutorial-complete` and `redeem-promo` were exempted though they are per-user. → both are now probed, and the exemptions are removed. redeem-promo also checks that a code another user used up ≡ a nonexistent code.
  - `[low]` `[patch]` (blind) The webhook exemption didn't say what happens when it is unconfigured. → the reason now states it: 503 before verifying when Stripe or the webhook secret is unset, otherwise 400 on a bad signature.
  - `[low]` `[patch]` (blind) The exemption block comment called health an account route. → reworded.
  - `[low]` `[patch]` (blind) The pending baseline header and the `test_coverage.py` docstring still described a shrinking baseline. → both now say it is empty and must stay empty.
  - `[low]` `[patch]` (blind) Ingest had no positive control, and voice ignored the input. → the GM's canary upload must come back through `expect`, and voice asserts the exact fake transcript hash of the bytes sent.
  - `[low]` `[patch]` (blind) The avatar probe never checked the caller's own row. → it now asserts the stored `avatar_data` equals the response.
  - `[low]` `[reject]` (blind) Move `check_denial` and `use_fake_llm` into `_support.py`. Cross-module probe imports are the existing pattern (`retrieval.use_fake_llm` is already imported by `ai_routes` and `journals`), and `_support.py` is shared with running sibling stories, so the edit stays out of it.
  - `[low]` `[reject]` (blind) Separate `NOBODY` uuids per module. They are harmless, being Campaign ids no actor holds.
  - `[low]` `[reject]` (blind) The `fake_evaluation` and `spy_connection_test` module patches don't use monkeypatch. try/finally restores them, and probes are plain async functions with no pytest fixture access. This matches `retrieval.fake_embeddings`.
  - `[low]` `[reject]` (blind) Import order in `feedback.py`. The repo has no isort gate; the import now sits with the other `app.*` imports.
  - `[false]` `[reject]` (acceptance) Hidden ≡ missing isn't applied to the id-less per-user reads. There is no id; recorded in the AC1 mapping above.
  - `[false]` `[reject]` (acceptance) Counts aren't applied to the admin-only reads. The family needs a 2xx response; recorded above.
  - `[false]` `[reject]` (acceptance) Billing checkout and portal are exempted beyond the coordinator's list. AC1 names `billing` as an example exemption; both hand the caller's own account to Stripe.
  - `[low]` `[defer]` (acceptance, blind) Feedback from a former Member loses its pointer. Owner decision (see `deferred`).
  - `[false]` `[reject]` (verification-gap) No gaps reported.

## Design Notes

The admin routes are probed, not exempted, as the coordinator preferred. Each per-route probe uses real targets with canaries. The sweep catches any admin route added later that skipped the router-level gate. `jobs/stats` stays exempted (E0-Jobs.7) but is still swept.

Feedback submit keeps the feedback and drops an unreachable pointer, rather than answering 404, because feedback must stay submittable. A hidden id and a missing id both store and return `campaign_id: null`. The check reads the caller's whole Role map, so its cost doesn't depend on the id.

## Verification

**Commands:**
- `pytest tests/ev4 tests/test_feedback.py -q` (desktop container or CI). Expected: all pass, EV-4 pending=0, leaks=0.
- `python scripts/check_scoped_queries.py`. Expected: clean, with no baseline additions.

## Auto Run Result

Status: done

- **What changed:**
  - The admin, feedback, auth, billing, settings and ingest routes are probed.
  - The anonymous credential routes, the Stripe hand-offs, the webhook and health are exempted.
  - The pending baseline is empty and guarded.
  - One leak is fixed: the existence oracle in feedback submit, by status/500 and by timing.
- **Review:** one pass. 1 high and 4 medium findings patched, plus 12 low. 6 rejected with reasons, and one owner question deferred.
- **Follow-up review recommended:** false.
- **Verification:**
  - First push: CI green. EV-4 probes=139, exemptions=12, pending=0, leaks=0. Backend 2569 passed.
  - After the review fixes and the merge of main (E0-Platform.6, which added `GET /api/admin/sidecars`, now swept), CI is green on 5cc2f07. EV-4 probes=141, exemptions=11, pending=0, leaks=0. EV-4 suite 628 passed. Backend 2593 passed, 4 skipped.
  - The desktop was unreachable, so CI was the gate.
- **Needs desktop verification:** none.
