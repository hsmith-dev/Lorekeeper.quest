---
title: 'E0-Access.3: Access registry, Audiences, scoped_select and audience_ctx'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: '61abdbaea6e82be7c59c94e35d739c6d27c10d0d'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred: []
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
