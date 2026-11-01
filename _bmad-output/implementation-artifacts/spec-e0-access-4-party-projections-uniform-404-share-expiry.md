---
title: 'E0-Access.4: Party projections and a uniform 404 on existing read and write responses, including Share Links with expiry'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '712e74e485801e5767f931c709b732acb96f2f03'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/planning-artifacts/epics.md'
warnings: ['oversized']
deferred:
  - summary: >-
      Cross-Campaign lists (GET /api/journals/ and GET /api/tags/ without campaign_id) ignore the preview header, so a previewing GM sees GM data there.
    evidence: |-
      role_map never narrows (carried from E0-Access.3's deferral of scoped_select_multi preview). Decide with E7.7 whether previews include cross-Campaign lists, or have the frontend always send campaign_id while previewing.
    location: >-
      src/backend/app/api/routes/journals.py:list_journals, src/backend/app/api/routes/tags.py:list_tags
    severity: medium
  - summary: >-
      "Similar timing" for hidden vs missing is not measured; require_campaign_for runs a membership query only when the row exists, so a row in another Campaign can take one query longer than a random id.
    evidence: |-
      Status, body and headers are proven identical by EV-4; latency is not. Whether the extra indexed query is distinguishable over the network is unverified. Settle with a timing probe or by always running the membership query.
    location: >-
      src/backend/app/access/context.py:require_campaign_for
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** E0-Access.3 built the registry (`scoped_select`, `audience_of`) but no route uses it: Members and Share Link viewers still get GM fields (`shorthand`, `notes`), GM-only rows, tags found only in Shorthand and counts over hidden rows, and a hidden record answers differently from a missing one (403s, custom 404 texts, revoked/expired share tokens).

**Approach:** Add `app/access/projection.py` (`project`, `project_all`, a `PROJECTIONS` map of `<X>GMResponse`/`<X>PartyResponse` per model, import-time check that Party schemas carry no GM field) and `share_ctx`; move the touched routes onto `require_campaign*`/`scoped_select`/`scoped_get` + `project`, with every denial the one `not_found()`; add a `Vary: Authorization, X-Lorekeeper-Preview` middleware; prove it with EV-4 probes.

## Boundaries & Constraints

**Always:**
- GM ctx → `<X>GMResponse`; Player / member-preview → `<X>PartyResponse`; anon → the Party schema (Campaign: `PublicCampaignResponse`). Party schemas omit GM fields (`JournalPartyResponse` no `shorthand`; NPC/Quest Party no `notes`); `field_visibility` never in a Party schema; a field hidden by `field_visibility` renders as the schema default (None when none). E0a `Public*` names become aliases of the Party schemas, so share output keys are unchanged.
- `project(obj, ctx)` raises `not_found()` when the row's Audience does not cover ctx (stored / always_gm / membership); derived rows are trusted from the scoped query that loaded them.
- Reference removal (non-GM): an entry's tag whose `journal_tags` link is hidden (`source_field=shorthand`) is dropped; a tag's `custom_category` whose TagCategory is hidden becomes `null`. The rest is served.
- Hidden ≡ missing for reads and writes: a lookup of a hidden row uses the same scoped query as a missing one and raises the same `404 {"detail":"Not found"}` (no 403, no custom 404 text) on the touched routes. A create whose new row the caller could not see is refused with `not_found()` before writing.
- Counts (`total`, tag `entry_count`, template `character_count`) count only rows visible to the ctx.
- Share: `share_ctx(db, token)` → anon ctx (read-only, Public); unknown, revoked, expired (`expires_at <= now()`) and wrong-kind tokens all → `not_found()`. `/api/share/{token}/npcs|quests` return `[]` (always_gm, Decision B1-D4); `test_share.py` keeps its field allowlists (asserted on the Party schema output of a fully filled row).
- Every `/api/*` response carries `Vary` including `Authorization` and `X-Lorekeeper-Preview` (merged with existing Vary values, e.g. CORS `Origin`).
- Preview narrowing reaches the touched campaign-scoped routes (they use `require_campaign*` or `ctx_for_request`).

**Never:** `can_write` / Player write rules (E0-Access.6); moving the other `accessible_campaign_ids` / `get_campaign_with_access` callers or inline owner checks (E0-Access.5); `party_tsv` search (E0-Access.7); collaborate-link roles (E0-Access.12); models or migrations; AI routes (`generate`, `extract`, `suggest`, `recap`, ...) beyond the shared lookup helper; preview of cross-Campaign lists.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM reads entry | `GET /api/journals/{id}` as Owner/Co-GM | GM schema incl. `shorthand`, all tags | — |
| Player reads party entry | same, Player | no `shorthand` key; shorthand-sourced tags removed; hidden category → null | — |
| Player reads hidden | gm / other's private entry, other Campaign, random UUID | byte-identical `404 {"detail":"Not found"}` | `not_found()` |
| Player lists | `GET /api/journals/?campaign_id=` and without | only visible rows, `total` over visible rows; `tag_id` filter matches visible links only | — |
| NPC / Quest as Player | list / get / PUT / DELETE / POST | `[]` / 404 / 404 / 404 / 404 (nothing written) | `not_found()` |
| GM PUT NPC/Quest | valid body | `NpcGMResponse` / `QuestGMResponse` | — |
| GM in preview | `X-Lorekeeper-Preview: member` | Party schemas; writes 404 | — |
| Sheets as Player | gm-visibility sheet | hidden from list, 404 by id/PATCH/DELETE; template `character_count` excludes it | — |
| Tags list as Player | tag only via shorthand | absent; counts over visible links only | — |
| Campaign | `GET /api/campaigns/`, new `GET /api/campaigns/{id}` | projected rows; non-member → 404 | `not_found()` |
| Share token | unknown / revoked / expired / collaborate on content route | same 404 | `not_found()` |
| Share journals | gm-visibility or kind=player entry | absent from list and total; 404 by id | — |

</intent-contract>

## Code Map

- `src/backend/app/access/registry.py` -- `registration`, `audience_of`, `visible_clause`, `scoped_select`, `scoped_get` (no `options=`; add a keyword), `gm_fields`, `Stored.field_visibility`. Read-only otherwise.
- `src/backend/app/access/context.py` -- `CampaignContext`, `_narrow_for_preview`, `require_campaign(_for)`, `RoleMap`, `scoped_select_multi` (raises on models without `campaign_id`: extend to Derived models such as `JournalTag`), private `player_ctx`/`gm_ctx` closures (lift into a public `role_ctx(roles, campaign_id)`), `PREVIEW_HEADER`.
- `src/backend/app/access/audience.py` -- `visible_to`, `stored_audience`, `ALWAYS_GM_FIELDS`, `PUBLIC`.
- `src/backend/app/access/__init__.py` -- exports (add `project`, `project_all`, `PROJECTIONS`, `share_ctx`, `resolve_share_token`, `ctx_for_request`, `role_ctx`, `VaryMiddleware`).
- `src/backend/app/access/policy.py` -- `not_found()`, `ANON`.
- `src/backend/app/schemas/{journal,npc,quest,tag,character_sheet,campaign,share}.py` -- current `*Response` schemas; `share.py` `Public*` allow-lists to become Party aliases.
- `src/backend/app/api/routes/journals.py` -- list/get/attach/detach/delete use `accessible_campaign_ids` and custom 404/403; `generate` returns `JournalResponse`. Other AI routes untouched.
- `src/backend/app/api/routes/{npcs,quests}.py` -- `_get_accessible_*` helpers (db.get + campaign check) used by every item route incl. generate.
- `src/backend/app/api/routes/character_sheets.py` -- template counts include all sheets (leak).
- `src/backend/app/api/routes/tags.py` -- counts over every link.
- `src/backend/app/api/routes/campaigns.py` -- `list_campaigns`; no `GET /{campaign_id}` exists yet (story names it: add it). Leave the rest to E0-Access.5.
- `src/backend/app/api/routes/share.py` -- `_resolve_token` (no expiry), raw selects, custom 404 texts.
- `src/backend/app/main.py` -- middleware registration (one line).
- `src/backend/app/services/journal_service.py:create_journal_entry` -- returns the entry with tags eagerly loaded; tags inserted with `source_field` NULL.
- `src/backend/tests/test_share.py` -- exact-key tests; NPC/Quest share tests expect 1 row today.
- `src/backend/tests/ev4/{fixtures,families,registry}.py`, `pending_baseline.txt`, `probes/members.py` -- actors, families, probe template; delete a probed route's pending line.
- `src/frontend/src/types/index.ts`, `pages/EntryDetailPage.tsx`, `pages/TimelinePage.tsx` -- `shorthand: string` rendered unguarded; make optional and guard.

## Tasks & Acceptance

**Execution:**
- `src/backend/app/schemas/*.py` -- add `<X>GMResponse`/`<X>PartyResponse` for Journal, Tag (+ category ref), NPC, Quest, CharacterSheet, Template, Campaign; keep old names as GM aliases; `share.py` Public* = Party aliases (same keys).
- `src/backend/app/access/projection.py` -- `PROJECTIONS`, `project`, `project_all` (loads `journal_tags` links for entries), import-time Party-field check.
- `src/backend/app/access/share.py` -- `resolve_share_token`, `share_ctx`.
- `src/backend/app/access/context.py`, `registry.py` -- `ctx_for_request`, `role_ctx`, Derived support in `scoped_select_multi`, `scoped_get(..., options=)`, `VaryMiddleware`.
- Routes: `journals.py`, `npcs.py`, `quests.py`, `tags.py`, `character_sheets.py`, `campaigns.py` (`GET /`, new `GET /{campaign_id}`), `share.py` -- scoped lookups + `project`, `response_model=None` where GM/Party differ (FastAPI must not coerce one schema into the other), `not_found()` for every denial on these routes.
- `src/backend/app/main.py` -- add `VaryMiddleware`.
- `src/backend/tests/access/test_projection.py` -- unit: schema choice per role, GM fields absent, field_visibility default, reference removal, not_found on hidden, import check, share_ctx expiry/revoked/kind, Vary header, preview.
- `src/backend/tests/ev4/probes/{journals,npcs,quests,tags,character_sheets,campaigns,share}.py` + `pending_baseline.txt` -- probes for every changed route (no canary, hidden ≡ missing, counts unchanged, hidden field = unset); remove their pending lines.
- `src/backend/tests/test_share.py` -- NPC/Quest share lists `[]`; allowlists asserted on the Party projection.
- Frontend -- `shorthand?` optional and guarded.

**Acceptance Criteria:**
- Given CI, when backend-tests, gates (lint-imports, check_scoped_queries, CI-11) and frontend-ci run, then all pass and no existing test regresses except the NPC/Quest share expectations the story changes.
- Given the EV-4 probes as `anon_share`, `player`, `cross_gm_player` (and `co_gm` where it matters), then zero leaks are recorded.
- Given any `/api/` response, then its `Vary` header lists `Authorization` and `X-Lorekeeper-Preview`.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 38 findings — high 0, medium 3, low 20, false 14, maybe-false 1 (verification-gap gaps pre-verified; intent-alignment divergences counted as 10 findings)
- findings:
  - `[medium]` `[patch]` (blind) delete_template cascades to sheets the caller cannot see while character_count hides them — delete now refuses with not_found() when the template has any sheet hidden from ctx; test added.
  - `[low]` `[reject]` (blind) attach_tag no-ops when a hidden shorthand link already exists — rare (Player manually tagging a Shorthand-only tag); 201 is identical to a fresh attach so nothing leaks; fix needs a new upgrade branch.
  - `[low]` `[reject]` (blind) /journals/generate skips check_create — a new entry is party + kind gm (Public) for every caller, so the refusal is unreachable today.
  - `[false]` `[reject]` (blind) Player loses own Shorthand in the generate response — intended: AD-13 / story say JournalPartyResponse has no shorthand (always-GM field).
  - `[medium]` `[defer]` (blind) Cross-Campaign lists ignore preview — pre-existing E0-Access.3 deferral; deferred again (frontmatter).
  - `[low]` `[patch]` (blind) /npcs|quests/{id}/entries use a raw select(JournalEntry) — switched to scoped_select(JournalEntry, ctx).
  - `[false]` `[reject]` (blind) Other frontend shorthand consumers unguarded — ChatPage reads chat sources (not a touched route); NPC/Quest panels are GM-only (always_gm); the other `shorthand: string` types are not journal responses.
  - `[low]` `[patch]` (blind) Share error copy omits expiry — SharedCampaignPage/JoinCampaignPage now say "invalid, expired or revoked".
  - `[false]` `[reject]` (blind) No Cache-Control / 500s lack Vary — a 500 body is the same generic text for every caller, so a shared cache cannot cross-serve content; Vary is what the intent asks for.
  - `[low]` `[reject]` (blind) check_create column-default fragility — every registered stored model has a Python-side default today; a future server-only default is hypothetical.
  - `[false]` `[reject]` (blind) delete_journal 403→404 — the intent requires the one 404, never 403; tests/test_journals.py passes in CI.
  - `[low]` `[reject]` (blind) Spec verification command is machine-specific — fix edits this build's spec.
  - `[low]` `[reject]` (blind) role_ctx revalidates the map per row — negligible (a handful of Campaigns).
  - `[low]` `[patch]` (blind) Triple blank lines in journals.py; ctx_for_request docstring too narrow — both corrected.
  - `[low]` `[reject]` (edge) field_visibility hiding a required field → 500 — no registered model uses field_visibility; E0-WorldCore wires entities with party_unset defaults.
  - `[low]` `[reject]` (edge) Invalid value in field_visibility JSON → 500 — same; values are written only by set_visibility (E0-Access.9).
  - `[low]` `[reject]` (edge) Unloaded tags/custom_category raise MissingGreenlet not a clear error — a programming error that fails loudly in tests either way.
  - `[low]` `[reject]` (edge) attach_tag with an existing hidden link — same as the blind row.
  - `[medium]` `[patch]` (edge) delete_template cascade — same root cause as the blind row; same patch.
  - `[low]` `[patch]` (edge) VaryMiddleware KeyError when start message has no headers — `message.setdefault("headers", [])`.
  - `[false]` `[reject]` (edge, claim) 500s carry no Vary — same as the blind row.
  - `[low]` `[reject]` (edge, claim) check_party_schemas misses a nested GM sub-ref not in PROJECTIONS — the field-name walk at every depth still rejects any GM field in it; no such schema exists.
  - `[low]` `[patch]` (verification-gap) cross-Campaign tag_id filter untested — probe added.
  - `[low]` `[patch]` (verification-gap) delete_journal allowed paths untested — author/Owner 204, Co-GM 404 tests added.
  - `[low]` `[patch]` (verification-gap) character-sheet success paths untested — Player create/list/get/patch/delete tests added.
  - `[low]` `[patch]` (verification-gap) generate success projection untested — Player/GM 201 key tests added.
  - `[low]` `[patch]` (verification-gap) tag attach/detach success paths untested — category, GM shorthand detach and Player manual detach tests added.
  - `[false]` `[reject]` (verification-gap, other) Player's own shorthand missing from the generate response — intended, as above.
  - `[maybe-false]` `[defer]` (intent) "Similar timing" unmeasured — would be medium if the extra membership query is distinguishable; settle with a timing probe; deferred (frontmatter).
  - `[false]` `[reject]` (intent) llm_provider.capture() unused — no touched route builds an LLM context from hidden rows; hidden NPC/Quest generate now 404s before the LLM dependency; AI context is E0-Access.6/.7.
  - `[false]` `[reject]` (intent) Share NPC/Quest allowlist moved to the schema output — the story mandates `[]` and "field allowlist tests kept".
  - `[low]` `[reject]` (intent) field_visibility default from the schema, not party_view — no model has field_visibility yet; E0-WorldCore plugs its party_unset defaults into the schema when entities register.
  - `[false]` `[reject]` (intent) Overlap with E0-Access.5 in journals/tags — needed for this story's no-leak/counts ACs; Access.5 starts after merge.
  - `[false]` `[reject]` (intent) NPC/Quest Player writes now 404 — follows from always_gm (B1-D4) + hidden ≡ missing for writes.
  - `[false]` `[reject]` (intent) Campaign anon schema is PublicCampaignResponse — the story's "E0a Public schemas become the anon Party projections".
  - `[false]` `[reject]` (intent) Vary on every /api/ response — a superset of "responses that differ under preview"; harmless.
  - `[false]` `[reject]` (intent) Per-link tag removal vs "only source" — journal_tags' PK is (journal_id, tag_id): one link per pair, so they coincide.
  - `[false]` `[reject]` (intent) Member preview and GM PUT schemas covered only in test_projection.py, not EV-4 probes — descriptive; both are tested and pass, EV-4 actors have no preview actor.

## Design Notes

Projection order in `project(obj, ctx)`: registration → row visibility (`not_found()`) → schema by role → `schema.model_validate(obj)` → non-GM pruning (tags by visible link, hidden category → None, `field_visibility` hidden fields → default) → `extra` fields merged. `project_all(db, rows, ctx)` takes one ctx or a `RoleMap` (per-row `role_ctx`) and preloads `journal_tags` rows for entries, so `project` stays sync; `project` on a non-GM entry with tags and no links raises (programming error, fails loudly).

```python
entry = await scoped_get(db, JournalEntry, ctx, journal_id, options=[selectinload(...)])
return (await project_all(db, [entry], ctx))[0]
```

Routes with two output schemas use `response_model=None` (+ `responses=` for docs): FastAPI would otherwise validate a Party object into the GM model.

## Verification

**Commands:**
- `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/e0a4_test.sh -q tests/access tests/ev4 tests/test_share.py tests/test_journals.py` -- expected: pass, `leaks=0`.
- `python scripts/check_scoped_queries.py` and `lint-imports` (src/backend) -- expected: clean.
- `cd src/frontend && npx tsc --noEmit && npm run build` -- expected: pass.
- `gh pr checks <n> --repo hsmith-dev/Lorekeeper.quest --watch` -- expected: all green.

## Auto Run Result

Status: done

**Summary:** `app/access/projection.py` adds `project` / `project_all` / `check_create` and the `PROJECTIONS` map (`<X>GMResponse` / `<X>PartyResponse` for Journal, Journal lite, Tag, Tag-with-count, NPC, Quest, CharacterSheet, Template, Campaign; anon Campaign = `PublicCampaignResponse`), with an import-time check that no Party schema carries a GM field at any depth. Non-GM projections drop tags whose `journal_tags` link is hidden (Shorthand), null hidden tag categories and render `field_visibility`-hidden fields as defaults; a hidden row is `not_found()`. `app/access/share.py` adds `resolve_share_token` / `share_ctx` (unknown, revoked, expired and wrong-kind tokens are the same 404). `context.py` adds `ctx_for_request`, `role_ctx`, Derived support in `scoped_select_multi` and `VaryMiddleware` (`Vary: Authorization, X-Lorekeeper-Preview` merged on every `/api/` response). Routes in journals (list, get, generate, tag attach/detach, delete), npcs, quests, tags, character_sheets, campaigns (`GET /`, new `GET /{campaign_id}`) and share load through `scoped_select` / `scoped_get` and return `project` output; every denial there is the one 404 (no 403, no custom texts). Counts (`total`, `entry_count`, `character_count`) count visible rows only. `Public*` share schemas are now aliases of the Party schemas (output keys unchanged); share NPC/Quest lists are `[]` (B1-D4). Frontend `shorthand` is optional and guarded; share pages say "invalid, expired or revoked".

**Rebased onto E0-Access.7 (#49) and E0-Jobs.1 (#48):** `scoped_select_multi` treats `DerivedFromSources` as derived; Access.7's `JournalLitePartyResponse` / `JournalListPartyResponse` are now aliases of the Party projection schemas, so the projection is the single place Shorthand is removed (it also prunes Shorthand-only tags, which Access.7's direct validation did not). The journal list keeps Access.7's party_tsv / narrative_tsv search branches and projects each row by the caller's Role in its own Campaign. NPC/Quest `/entries` keep Access.7's GM-vs-narrative-only match and project with the `lite` variant; since NPCs/Quests are always_gm, Players get the one 404 there — Access.7's `test_entity_entries_routes`, the cross-Campaign assertion in `test_journal_search_route` (P's own GM Campaign row keeps its Shorthand) and the `retrieval.py` entries probes were updated to match.

**Files changed:**
- `src/backend/app/access/{projection,share}.py` -- new: projections, create check, share ctx.
- `src/backend/app/access/{context,registry,__init__}.py` -- ctx_for_request, role_ctx, derived multi-select, Vary middleware, scoped_get options, exports.
- `src/backend/app/schemas/{journal,tag,npc,quest,character_sheet,campaign,share}.py` -- GM/Party pairs, old names as aliases.
- `src/backend/app/api/routes/{journals,npcs,quests,tags,character_sheets,campaigns,share}.py` -- scoped lookups + project, uniform 404.
- `src/backend/app/main.py` -- VaryMiddleware.
- `src/backend/tests/access/test_projection.py`, `tests/ev4/probes/{_support,journals,npcs,quests,tags,character_sheets,campaigns,share}.py`, `tests/ev4/pending_baseline.txt` (37 probed lines removed) -- tests and probes.
- `src/backend/tests/{test_share,test_party_retrieval}.py`, `tests/ev4/{test_fixtures,probes/retrieval}.py` -- expectations for always_gm NPCs/Quests and per-row projection.
- `src/frontend/src/{types/index.ts,pages/EntryDetailPage.tsx,pages/TimelinePage.tsx,pages/SharedCampaignPage.tsx,pages/JoinCampaignPage.tsx}` -- optional shorthand, copy.

**Review:** 38 findings (high 0, medium 3, low 20, false 14, maybe-false 1). Patched: delete_template refuses when hidden sheets would cascade (medium, grouped blind+edge), scoped NPC/Quest entries, Vary headers-key guard, share copy, journals.py hygiene and ctx_for_request docstring, and five verification gaps (cross-Campaign tag_id probe, delete allowed paths, sheet success paths, generate projection, tag attach/detach success). Deferred: cross-Campaign lists ignore preview (medium), hidden-vs-missing timing unmeasured (medium, unverified). Rejected findings and reasons are in the triage log.

**Follow-up review recommended:** false -- one medium entry patched, no high.

**Verification:** CI on the first push (PR #50) was all green. After the patches and the rebase onto `712e74e`, locally (scratch pgvector, weasyprint stubbed because the Mac has no pango): full backend suite 1113 passed, 22 skipped, the 6 PDF tests deselected (stub only) and `test_nlp.py` ignored (spaCy model not installed); EV-4 `probes=45 pending=82 leaks=0`; `check_scoped_queries.py` clean; `lint-imports` 5 kept; `npx tsc --noEmit` clean. CI re-runs on the rebased push.

**Needs desktop verification:** nothing specific (no Ollama, GPU, compose or nginx surface). Optional: run the brief's backend command for `tests/access tests/ev4 tests/test_share.py tests/test_party_retrieval.py`.

**Residual risks:** the rebase merge of journals list / NPC-Quest entries with E0-Access.7 was not re-reviewed by the review layers (covered by both stories' tests and probes). Mixed cross-Campaign lists now return GM rows with Shorthand next to Party rows without it (frontend treats `shorthand` as optional). Preview does not narrow cross-Campaign lists; Player write rules wait for E0-Access.6.
