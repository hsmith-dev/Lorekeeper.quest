---
title: 'E0-Access.3: Access registry, Audiences, scoped_select and audience_ctx'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '61abdbaea6e82be7c59c94e35d739c6d27c10d0d'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Preview responses carry no `Vary: X-Lorekeeper-Preview` (or no-store), so a browser, service-worker or proxy cache could serve a GM body to a preview request of the same URL or the other way round.
    evidence: |-
      Nothing in app/ sets Vary; the same GET now varies on a request header. PreviewContext resets react-query, but the PWA service worker or an HTTP cache is not covered. Needs a response-header decision once real read routes adopt require_campaign (E0-Access.4/.5).
    location: >-
      src/backend/app/access/context.py:_narrow_for_preview
    severity: medium
  - summary: >-
      Routes still on the deprecated get_campaign_with_access / accessible_campaign_ids ignore the preview header, so a previewing GM sees GM data and can write there.
    evidence: |-
      Only require_campaign / require_campaign_for narrow; E0-Access.5 moves every caller onto them. The GM is the real user, so nothing leaks to a Player, but preview is incomplete until then.
    location: >-
      src/backend/app/api/deps.py
    severity: medium
  - summary: >-
      read_only on a reduced ctx is not enforced on writes beyond the preview 404.
    evidence: |-
      can_write (E0-Access.6) is the write gate; until then a service handed an audience_ctx ctx is not refused. No production code builds one yet.
    location: >-
      src/backend/app/access/context.py:CampaignContext
    severity: medium
  - summary: >-
      scoped_select_multi has no preview flag; cross-Campaign lists in a previewing request are not narrowed.
    evidence: |-
      Preview is per Campaign (RC-7 names require_campaign); a cross-Campaign list has no single ctx. Decide with E7.7 whether previews include cross-Campaign lists.
    location: >-
      src/backend/app/access/context.py:scoped_select_multi
    severity: low
  - summary: >-
      The import-time completeness check recognises Campaign-scoped tables only by a campaign_id column or the hard-coded tags/journal_tags list; a future FK-only child table could land unregistered.
    evidence: |-
      _REACHED_TABLES is hard-coded. derived_sources (E0-Jobs) should be registered or added to the list when it lands.
    location: >-
      src/backend/app/access/registry.py:_check_complete
    severity: low
  - summary: >-
      The CI-11 property test exercises scoped_select only, not scoped_select_multi.
    evidence: |-
      scoped_select_multi is covered by EV-4 scenario tests (now including a multi-Player-Campaign derived case); a property extension would make it airtight.
    location: >-
      src/backend/tests/access/test_registry_property.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** E0-Access.2 resolves a per-Campaign Role but nothing turns a Role into "which rows may this ctx see". Every later story (Access.4 `project`, .6 `can_write`, .7 retrieval, .9 `set_visibility`, E3/E6/E7/E8, E0-Jobs) needs one registry that declares each model's Audience and one predicate source, plus the reduced-ctx constructor `audience_ctx` and the GM preview header.

**Approach:** Extend `app/access/audience.py` into the full Audience lattice (`Public ⊃ Members ⊃ Owner(u) ⊃ GM`, `covers`, `most_restrictive`, `stored_audience`, `mention_audience`); add `app/access/registry.py` (registration classes `stored` / `derived` / `always_gm` plus the story's `membership` scope, every current table registered, `DERIVED_REGISTRY`, `visible_clause`, `audience_of`, `scoped_select`, `scoped_get`); add `audience_ctx` and the `X-Lorekeeper-Preview: member` narrowing in `require_campaign`; make `scoped_select_multi` apply the per-Role predicate.

## Boundaries & Constraints

**Always:** one predicate source: `visible_clause` (SQL) and `audience_of` (Python) both derive from the same registration and a hypothesis property test (≥ 200 examples per registered model) proves they agree. AD-12 mapping exactly: `party`+`kind=gm` (or no kind) → Public, `party`+`kind=player` → Members, `private` → Owner(owner_field), `gm` → GM; `Owner(a) ⊓ Owner(b) = GM`. ctx audiences: GM → GM, Player → Owner(self) (reads Public, Members, Owner(self)), member preview → Members (owns nothing), anon → Public. Reduced ctxs are `read_only=True` and built only by `audience_ctx` (CI-8 flags `read_only=` outside `app/access/`). Every denial is the one `not_found()`. Preview may only narrow: a Player request with the header is byte-identical to one without; `/me` always reports the real Role.

**Never:** `project`/Party schemas, share-route changes (E0-Access.4); migrating route callers (E0-Access.5); `can_write` (.6); retrieval (.7); `set_visibility` (.9); the scoped-query ratchet (E0-Access.5); a `derived_sources` table (E0-Jobs); touching the stt sidecar, `sprint-status.yaml`, `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stored row, GM ctx | any visibility | visible | — |
| Stored row, Player p | `party` / `private` by p / `private` by q / `gm` | visible / visible / hidden / hidden | hidden by id → `not_found()`, same as random id |
| Stored row, anon | `party` kind gm / `party` kind player / other | visible / hidden / hidden | — |
| Member preview | `party` any kind visible; `private` (even the GM's own) hidden | — | — |
| Derived chunk | parent document `gm` | chunk hidden to Player | — |
| journal_tag | entry `party`, `source_field=shorthand` | GM only; `narrative`/`manual`/NULL → entry's Audience | — |
| tag | reached by any visible journal_tag in ctx's Campaign | visible; reached only via shorthand or other Campaign → hidden | — |
| npcs, quests | any row | GM only | — |
| campaigns / members / share tokens / templates | row of ctx's Campaign | Public / Members / GM / Public | management stays Owner-only (route rule) |
| `scoped_select_multi` | Owner of B, Player in A | all of B; A filtered as Player | empty map → nothing |
| `audience_ctx` | GM ctx → anon / member / as_user(any); Player → anon / member / as_user(self) | reduced read-only ctx | Player → as_user(other), anon → member, other campaign → `not_found()` |
| Preview header | GM + `member` | Player read path; unsafe method → 404; `gm` min_role → 404 | other values ignored; Player/anon ignored |
| Unregistered model | `scoped_select(Feedback, ctx)` | — | `UnregisteredModel`; a campaign-scoped table left unregistered fails at import |
| Derived type | `DERIVED_REGISTRY.append({...})`, non-file ok | `audience_of(obj)` = most restrictive of its `derived_sources` | unknown ref_kind → ValueError; no sources → GM |

</intent-contract>

## Code Map

- `src/backend/app/access/audience.py` -- minimal `Audience`/`AudienceLevel`/`ctx_audience` from E0-Access.2; names stay, extend in place.
- `src/backend/app/access/context.py` -- frozen `CampaignContext.__post_init__` (system-ctx rules; add `read_only` and audience/role consistency), `require_campaign` (add preview narrowing, `preview=` opt-out for `/me`), `role_map` (return a dict carrying `user_id`), `scoped_select_multi` (per-Role predicate).
- `src/backend/app/access/__init__.py` -- export the new contract names.
- `src/backend/app/db/models/*` -- owner fields: `user_id` (journal, plans, shorthand, sources, chat), `created_by_user_id` (sheets, tag categories); `tags` has no `campaign_id` (global, unique name+type) and `journal_tags` reaches entries by `journal_id`; `campaigns` scope column is `id`; `chat_sessions.campaign_id` nullable; `feedback.campaign_id` is operator feedback, not campaign content.
- `src/backend/app/services/journal_service.py:84` -- tags today come from the Narrative (`source_field` NULL), so NULL takes the entry's Audience.
- `src/backend/app/api/routes/members.py` -- `/me` must opt out of preview narrowing (carry-over b).
- `src/backend/tests/access/test_context.py` -- `_ctx` helper hand-builds an anon ctx (needs `read_only=True`), toy-app pattern for route tests.
- `src/backend/tests/ev4/fixtures.py` + `seeds/ev4_canary.json` -- actors and canaries; the seeded sheet holds canaries but defaults to `party`, so the seed gains `visibility: gm` for it.
- `scripts/check_scoped_queries.py` + `scripts/test_check_scoped_queries.py` -- CI-8 keyword rule (add `read_only=`).
- `src/backend/requirements-dev.txt`, `licenses/register.yaml` -- `hypothesis` (MPL-2.0), `attrs` (MIT).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/access/audience.py` -- lattice: `covers`, `most_restrictive`, `AnyOf` (any-of reach for tags), `visible_to`, `stored_audience`, `field_audience`, `mention_audience`, `ALWAYS_GM_FIELDS`.
- `src/backend/app/access/registry.py` -- `stored`/`derived`/`always_gm`/`membership` specs, `parent`/`reached_through` links, `REGISTRY` with every current table, import-time completeness check, `UnregisteredModel`, `visible_clause`, `audience_of`, `scoped_select`, `scoped_get`, `DERIVED_REGISTRY` (+ `DerivedType`, `register_derived`).
- `src/backend/app/access/context.py` -- `read_only`, `audience_ctx`, `as_user`, `ANON_VIEW`/`MEMBER_VIEW`, preview in `require_campaign`, `RoleMap`, per-Role `scoped_select_multi` (imports registry lazily to avoid a cycle).
- `src/backend/app/access/__init__.py`, `src/backend/app/api/routes/members.py` -- exports; `/me` uses `require_campaign("player", preview=False)`.
- `scripts/check_scoped_queries.py`, `scripts/test_check_scoped_queries.py` -- flag `read_only=` (non-False) outside `app/access/`.
- `src/backend/tests/access/test_audience.py` -- lattice, mapping, Mention formula, derived types (pure).
- `src/backend/tests/access/test_registry_property.py` -- CI-11 hypothesis property per registered model.
- `src/backend/tests/access/test_scoped_select.py` -- EV-4 actors: GM-only canaries absent for player/anon/preview, present for GM/Co-GM; counts, hidden-vs-missing, ordering; `scoped_select_multi` cross-Campaign; `audience_ctx` matrix; preview header (narrow-only both directions, writes 404, `/me` real role, CORS preflight).
- `src/backend/tests/access/test_context.py`, `src/backend/tests/ev4/fixtures.py`, `seeds/ev4_canary.json` -- anon helper `read_only`; seed sheet `visibility`.
- `src/backend/requirements-dev.txt`, `licenses/register.yaml` -- hypothesis + attrs.

**Acceptance Criteria:**
- Given CI, when backend-tests and gates run, then the property test, the scoped-select suite and `python scripts/check_scoped_queries.py` pass with no regression of the existing suite.
- Given a GM request with `X-Lorekeeper-Preview: member` to `/api/campaigns/{id}/me`, then the body still says the real Role.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 42 findings — high 0, medium 6, low 21, false 15, maybe-false 0 (intent-alignment divergences counted as 8 findings)
- findings:
  - `[medium]` `[patch]` (blind) `dataclasses.replace(reduced, read_only=False)` passes CI-8 — the rule now flags every `read_only=` outside app/access/ (False included); planted test added; gates.yml comment fixed.
  - `[low]` `[reject]` (blind) `**{"read_only": True}`, positional or `object.__setattr__` bypass CI-8 — needs deliberate obfuscation; same stance as E0-Access.2's as_system rule.
  - `[medium]` `[defer]` (blind) read_only not enforced on writes — can_write is E0-Access.6; deferred.
  - `[medium]` `[defer]` (blind) No `Vary: X-Lorekeeper-Preview` — deferred until real read routes adopt require_campaign.
  - `[low]` `[reject]` (blind) `scoped_select_multi(user_id=)` can override `roles.user_id` — the explicit argument wins by design; no caller passes both.
  - `[low]` `[patch]` (blind) scoped_select_multi GM branch skipped the derived parent EXISTS — derived models now get per-Campaign branches for GM Campaigns too; covered by the new multi-Campaign test.
  - `[low]` `[defer]` (blind) Property test does not cover scoped_select_multi — deferred (EV-4 scenario tests cover it).
  - `[low]` `[defer]` (blind) Completeness check misses FK-only child tables — deferred.
  - `[low]` `[reject]` (blind) `as_user(u)` does not check membership — audience_ctx is sync by contract; an Owner(non-member) ctx sees only party rows.
  - `[low]` `[reject]` (blind) Property test not derandomized and runs in two jobs — Hypothesis prints the falsifying example; total CI cost is small.
  - `[low]` `[reject]` (blind) Oracle thin for Tag and ctx pool — JournalTag's Python side is checked independently in its own run; six planted SQL bugs were all caught.
  - `[low]` `[patch]` (blind) most_restrictive does not type-check the first element — every element checked; str and AnyOf rejected; test added.
  - `[false]` `[reject]` (blind) audience_ctx raises HTTP 404 for non-request callers — same contract as ctx_for (E0-Access.2 AC: "raises not_found()").
  - `[false]` `[reject]` (blind) Spec stale — the review runs before finalization; updated now.
  - `[low]` `[reject]` (blind) No test of the (min_role, preview) dependency cache key — the `/me` preview test fails if the keys collide.
  - `[low]` `[reject]` (edge) Tag audience_of ignores the Campaign — documented contract: callers pass the ctx Campaign's reaching rows; scoped_select is the enforcement point.
  - `[low]` `[reject]` (edge) Oracle pre-filters Tag reach by Campaign — same contract as above.
  - `[low]` `[reject]` (edge) Orphan parent gives GM in Python but hidden in SQL — FKs cascade, so orphans cannot exist.
  - `[low]` `[patch]` (edge) DERIVED_REGISTRY dict missing keys or str derive_from — one normalizer raises TypeError/ValueError; tests added.
  - `[low]` `[patch]` (edge) register_derived with a str derive_from — same fix.
  - `[low]` `[reject]` (edge) A source with no ref_kind skips the derive_from check — the check is an aid; the source still contributes its Audience.
  - `[low]` `[reject]` (edge) Mapping source with neither key gives a confusing error — it still fails loudly.
  - `[low]` `[reject]` (edge) parents as a set or generator — documented as list/tuple; fails loudly.
  - `[low]` `[reject]` (edge) Transient row with visibility unset — audience_of reads stored rows.
  - `[low]` `[patch]` (edge) most_restrictive first element — same fix as the blind row.
  - `[false]` `[reject]` (edge) covers() with AnyOf — visible_to is the AnyOf entry point; covers takes lattice points.
  - `[low]` `[reject]` (edge) CI-8 bypass via `**`/setattr — same as the blind row.
  - `[low]` `[reject]` (edge) read_only= false positives on unrelated calls — none exist in app/; the message names the fix.
  - `[medium]` `[defer]` (edge) Preview ignored on deprecated-helper routes — E0-Access.5; deferred.
  - `[low]` `[defer]` (edge) scoped_select_multi ignores preview — deferred to the E7.7 decision.
  - `[false]` `[reject]` (edge) scoped_get on a composite PK raises TypeError — a programming error failing loudly; JournalTag is never fetched by id.
  - `[false]` `[reject]` (edge) require_campaign_for in preview returns a ctx for a gm row — the route's scoped_get with the narrowed ctx then 404s, as for a real Player.
  - `[false]` `[reject]` (edge, claim) audience_of and visible_clause disagree across Campaigns — scoped_select applies the Campaign scope; audience_of's contract takes in-Campaign parents.
  - `[medium]` `[patch]` (verification-gap) Per-Campaign derived branch of scoped_select_multi untested with two Player Campaigns — test added (Player in A and C, GM of B, a cross-filed chunk).
  - `[false]` `[reject]` (intent) Leak tests at function level; no route uses scoped_select yet — the story builds the library; E0-Access.4/.5 move routes.
  - `[false]` `[reject]` (intent) GM-only fields (shorthand, notes) not stripped — field projection is E0-Access.4 `project`; the registry declares gm_fields for it.
  - `[false]` `[reject]` (intent) anon actor built via audience_ctx, not share_ctx — share_ctx is E0-Access.4.
  - `[false]` `[reject]` (intent) Preview only reaches /me in production — RC-7 is require_campaign; routes adopt it in E0-Access.5.
  - `[false]` `[reject]` (intent) A fourth `membership` class — the story itself lists campaigns, members and tokens as "membership-scoped".
  - `[false]` `[reject]` (intent) scoped_select raises at call time, completeness at import — both are implemented; the import check covers "an unregistered model raises at import time".
  - `[false]` `[reject]` (intent) audience_ctx needs `by=` and lets a Player narrow to anon/member — the AC needs the caller; narrowing is safe and matches "by a user for themself".
  - `[false]` `[reject]` (intent) Player audience Owner(self) vs "Members plus Owner(self)" — the same readable set in the lattice.

## Design Notes

`membership` is a fourth registration form for the three tables the story calls "membership-scoped" (plus `character_sheet_templates`, a layout every sheet viewer needs): a constant Audience per table, management rules stay in routes. `tags` is reached through entries, so its Audience is an *any-of* (`AnyOf`) over its visible `journal_tags` in the ctx's Campaign rather than a single lattice point (a join would let Player c see a tag reached only by Players a and b's private entries). `audience_of` on derived rows takes `parents=` (objects or Audiences) when the relationship is not loaded. Preview narrowing treats every non-GET/HEAD/OPTIONS method as a write.

- **Order:** `covers(row_aud, ctx_aud)` ("row_aud ⊒ ctx_aud") — Public covers all; Members covers Members, Owner(*), GM; Owner(u) covers Owner(u), GM; GM covers GM. `most_restrictive` is the meet (incomparable Owner(a), Owner(b) → GM). `visible_to(aud_or_anyof, ctx)` = `covers(aud, ctx.audience)`; for `AnyOf`, any member covers (empty → hidden, even to GM).
- **SQL per class** (`ctx` audience → predicate): GM → `true()`; Owner(p) → `vis = party OR (vis = private AND owner = p)`; Members → `vis = party`; Public → `vis = party AND (kind = gm)` (kind clause only when `kind_field` is set). `stored(column=None, owner_field=...)` means every row is Owner(owner) (chat_sessions). `derived` = AND over `parent(...)` links of `EXISTS(parent scoped to ctx.campaign_id AND visible_clause(parent))`, AND the field rule (`journal_tags.source_field = shorthand` → GM-only, i.e. `false()` for non-GM); `reached_through(...)` = EXISTS of any visible child (tags). `always_gm` → GM `true()`, others `false()`. `membership(audience)` → constant per `covers`.
- **scoped_select:** `select(M).where(M.<scope col> == ctx.campaign_id, visible_clause(M, ctx))`; scope col is `campaign_id`, or `id` for `campaigns`; models with no campaign column (tags, journal_tags) are scoped through their parent EXISTS inside `visible_clause`. `scoped_get(db, M, ctx, id)` returns the row or calls `not_found()`.
- **Import-time completeness:** at the bottom of `registry.py`, every mapped table with a `campaign_id` column plus `tags`/`journal_tags` must be registered or listed in `UNSCOPED` with a reason (`feedback`: operator feedback, read by `user_id`); else `RuntimeError` on import. Registrations keep `gm_fields` (journal_entries `shorthand`, npcs/quests `notes`) for E0-Access.4's `project`.
- **ctx rules (`__post_init__`, keep the E0-Access.2 system rules):** gm → audience GM; anon → user_id None, audience Public, `read_only`; player → audience Owner(user_id), or user_id None + Members + `read_only`. `audience_ctx(campaign_id, target, *, by: CampaignContext)` (sync, no db): `by.campaign_id` must match; result allowed only if `covers(result.audience, by.audience)` (so GM → anything; Player → anon, member, as_user(self); anon → anon); otherwise `not_found()`. Results: anon → role anon/Public/no user; member → role player/Members/no user; as_user(u) → role player/Owner(u)/user u; all `read_only=True`, `is_owner=False`, `grant_id=None`, epoch copied from `by`.
- **Preview:** in `require_campaign`'s dependency (take `request: Request`), after `meets`-independent resolution: if `preview` is on, header `X-Lorekeeper-Preview` == `"member"` exactly and the resolved ctx is GM, narrow with `audience_ctx`; then a non-safe method → `not_found()`; then apply `meets(ctx, min_role)` to the narrowed ctx. `RoleMap(dict)` carries `.user_id`; `scoped_select_multi(model, roles, user_id=None)` ORs `campaign IN gm_ids` with `campaign IN player_ids AND visible_clause(model, player ctx)`.
- **Property test (CI-11):** async `@given` (pytest-asyncio 0.24 supports it) with `settings(max_examples=200, deadline=None, suppress_health_check=[function_scoped_fixture, too_slow])`, one test per registration (parametrize over `REGISTRY`). Users/Campaigns A and B are created once per test (flushed, not committed); each example inserts 1–4 random rows (random visibility/kind/owner/campaign/source_field; tags with 0–3 reaching journal_tags) inside `db.begin_nested()` and rolls the savepoint back. For a pool of A-ctxs (owner GM, co-GM, player p, player q, `audience_ctx` member, anon, as_user(p)) assert `row ∈ scoped_select(M, ctx)` iff the row is in A and `visible_to(audience_of(row, parents=...), ctx)`.
- **EV-4 suite:** use the `ev4` fixture actors; ctxs via `ctx_for` (gm_owner, co_gm, player, cross_gm_player) and `audience_ctx` (anon_share, preview). Insert extra canary rows per stored model at `gm`, `private` by GM, `private` by player, `party`; scan every returned row's column values except `gm_fields` with `find_canaries` and assert `actor.may_see`-consistent results.

```python
stmt = scoped_select(JournalEntry, ctx).order_by(JournalEntry.created_at)
row = await scoped_get(db, SessionPlan, ctx, plan_id)   # not_found() if hidden or missing
```

## Verification

**Commands:**
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: backend-tests, gates, frontend-ci, licence checks green.
- `python -m pytest -q scripts/test_check_scoped_queries.py && python scripts/check_scoped_queries.py` -- expected: pass locally.

## Auto Run Result

Status: done

**Summary:** Full Audience lattice (`covers`, `most_restrictive`, `AnyOf`, `visible_to`, `stored_audience`, `field_audience`, `mention_audience`) in `app/access/audience.py`. New `app/access/registry.py` registers every current table (stored / derived / always_gm / membership; `feedback` UNSCOPED) with `visible_clause`, `audience_of`, `scoped_select`, `scoped_get`, `DERIVED_REGISTRY`/`register_derived` and an import-time completeness check. `audience_ctx` is the only reduced-ctx constructor (narrow-only, `read_only=True`). `X-Lorekeeper-Preview: member` narrows a GM in `require_campaign`/`require_campaign_for` (writes 404; `/me` opts out with `preview=False`). `RoleMap` plus per-Role `scoped_select_multi`. CI-8 flags `read_only=` outside app/access/; the CI-11 hypothesis property test (200 examples per model) is wired into gates.yml.

**Files changed:**
- `src/backend/app/access/{audience,registry,context,__init__}.py` -- lattice, registry, reduced ctxs, preview, exports.
- `src/backend/app/api/routes/members.py` -- `/me` reports the real Role in preview.
- `scripts/check_scoped_queries.py`, `scripts/test_check_scoped_queries.py`, `.github/workflows/gates.yml` -- CI-8 `read_only=` rule, CI-11 step.
- `src/backend/tests/access/{test_audience,test_registry_property,test_scoped_select,test_context}.py` -- new and adjusted tests.
- `src/backend/tests/ev4/{fixtures,test_fixtures}.py`, `seeds/ev4_canary.json` -- the seeded canary sheet is `visibility: gm`.
- `src/backend/requirements-dev.txt`, `licenses/register.yaml` -- hypothesis 6.112.1 (MPL-2.0), attrs 24.2.0 (MIT).

**Review:** 42 findings. Patched: CI-8 `read_only=False` (medium), multi-Campaign derived test (medium), scoped_select_multi derived GM branch (low), most_restrictive validation (low), DERIVED_REGISTRY entry validation (low). 6 deferred (frontmatter). Every rejection and its reason is in the triage log.

**Follow-up review recommended:** true -- two medium entries patched on a first pass. Named risk: the widened CI-8 `read_only=` rule may flag a legitimate future `read_only=` keyword outside app/access/ (E0-Access.4's share_ctx lives inside app/access/, so it is unaffected).

**Verification:** PR #44 CI was green on the first push (backend tests, gates static + database including CI-11, frontend, licence checks). Locally (scratch pgvector) the full backend suite passed 826 (3 errors in tests/test_nlp.py: spaCy model not installed locally). After the patches, tests/access (123) and scripts/test_check_scoped_queries.py (28) pass and `check_scoped_queries.py` is clean; CI re-runs on the patch push.

**Needs desktop verification:** nothing specific (no Ollama, GPU or compose surface). Optional: the builder-brief backend command limited to `tests/access tests/ev4 tests/test_members_me.py`.

**Residual risks:** preview narrows only routes on `require_campaign` (just `/me`, which opts out) until E0-Access.5; no `Vary` header yet; reduced-ctx write refusal waits for `can_write` (E0-Access.6).
