---
title: 'E0-Access.13: Analytics and export cover every Member, scoped by Role'
type: 'bugfix'
created: '2026-11-20'
status: 'done'
baseline_revision: '0d71955bfb4845679b134717f820267a0d79656d'
review_loop_iteration: 1
followup_review_recommended: false
context: []
warnings: ['oversized']
deferred:
  - summary: >-
      PDF export (WeasyPrint, CPU-bound) is now open to every Member with no entry cap, render timeout or cache (per-user rate limits added in the coordinator follow-up).
    evidence: |-
      The story defines no cap, and a silent cap would truncate the export. Measure render time for a large Campaign; E8 Chronicle replaces this export and should own paging or streaming.
    location: >-
      src/backend/app/api/routes/campaigns.py export_campaign
    severity: medium (unverified)
  - summary: >-
      Account gate (PR #61) still requires a paid account for export and analytics, so an unpaid Player cannot use the Player views.
    evidence: |-
      app/api/deps.py account_gate; campaigns.py header comment lists export and analytics as gated. Owner decision whether these are PARTY_READ.
    location: >-
      src/backend/app/api/routes/campaigns.py
    severity: low
---

<intent-contract>

## Intent

**Problem:** `GET /api/campaigns/{id}/analytics` and `/export` filter on `JournalEntry.user_id == ctx.user_id`, so a GM's totals and export silently drop every other Member's entries; both routes are also `gm`-only, so a Player gets nothing.

**Approach:** Drop the author filter and open both routes to `require_campaign("player")`. Every read goes through `scoped_select` (entries, tag links), and the export renders entries and the Campaign through `project`/`project_all`, so a GM sees every Member's entries (with Shorthand) and a Player gets only what their Audience covers (Party entries plus their own Private ones, Party projection: no Shorthand).

## Boundaries & Constraints

**Always:** all reads via `scoped_select`; export content only from `project`/`project_all` output (the single place GM fields are stripped); hidden ≡ missing (uniform 404) for non-members, anon and Share Link viewers; the preview header only narrows (a GM previewing as Player gets the Player view); PDF stays WeasyPrint off the event loop.

**Never:** no new analytics fields or schema changes; no raw selects or CI-8 baseline lines; no change to the account gate PR #61 assigns these routes; no NPC/Quest/Entity content in the export; no frontend changes (the UI already calls both routes for any Member).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| GM, many authors | Owner + Co-GM + Player entries (any visibility) | analytics totals and export include all of them; export shows Shorthand | none |
| Player | Party + GM-only entries, another Player's Private entry, own Private entry | counts/weeks/top tags use Party + own Private only; export has no Shorthand, no GM-only or others' Private narratives | none |
| GM-only change | GM adds a GM-only entry with a unique tag | Player analytics JSON and export bytes/text unchanged | none |
| Shorthand-derived tag | tag link with `source_field="shorthand"` on a Party entry | not counted for a Player | none |
| GM previewing as Player | `X-Lorekeeper-Preview` header | Player view (200), not 404 | none |
| anon / Share Link / non-member | any | the one 404, byte-identical to a missing Campaign | `not_found()` |

</intent-contract>

## Code Map

- `src/backend/app/api/routes/campaigns.py` -- `export_campaign` (~L137) and `get_campaign_analytics` (~L177): `Depends(_gm)` + `.where(JournalEntry.user_id == ctx.user_id)`; `top_tags` already uses `scoped_select(JournalTag, ctx)` joined to `Tag` (JournalTag `field_rule` hides GM-field links for non-GMs). PR #61 adds `can_write`/`PARTY_READ` here — rebase onto it.
- `src/backend/app/services/export_service.py` -- `build_campaign_markdown/pdf(campaign, entries)` read ORM attrs (`entry.shorthand`); switch to projected data (pydantic models from `project`/`project_all`), print Shorthand only when the projection has it.
- `src/backend/app/templates/export/campaign.html.j2` -- PDF template; guard the shorthand block.
- `src/backend/app/access/projection.py` -- `project(obj, ctx)`, `project_all(db, rows, ctx)` (loads tag links); `PROJECTIONS[JournalEntry]` = GM/Party (`JournalPartyResponse` has no `shorthand`), `Campaign` → GM/Party/anon.
- `src/backend/app/access/registry.py` -- `JournalEntry: stored(kind_field="kind", gm_fields=("shorthand",))`; `scoped_select` (L545).
- `src/backend/tests/ev4/probes/campaigns.py` -- `probe_export_campaign`/`probe_campaign_analytics` (currently `allowed=is_gm_of_a`).
- `src/backend/tests/ev4/probes/_support.py` -- `add_entry(visibility, kind, author, canary)`, `add_tag(journal_id, source_field, name)`.
- `src/backend/tests/ev4/families.py` -- `assert_no_canary` (accepts str/bytes), `assert_counts_and_ranking_unchanged` (compares JSON or text body + headers).
- `src/backend/tests/access/test_campaign_permissions.py` -- `test_export_and_analytics_need_gm` (L205), `test_analytics_counts_the_callers_own_entries` (L220), `test_analytics_top_tags_and_own_entries` (L360) encode the old behaviour.
- `src/backend/tests/access/test_grants.py` (~L504) and `tests/ev4/probes/grants.py` (~L133) -- use analytics as the "gm-only" route after a demotion; switch to a remaining gm-only route (`POST /{id}/tag-categories`).
- `src/backend/tests/test_export_pdf.py` -- WeasyPrint export tests (pypdf readback).

## Tasks & Acceptance

**Execution:**
- `src/backend/app/api/routes/campaigns.py` -- both routes `Depends(_player)`; drop the author filter; export: `export_ctx = ctx` for a GM, else `audience_ctx(ctx.campaign_id, MEMBER_VIEW, by=ctx)`; entries via `scoped_select(JournalEntry, export_ctx)` with the tags + custom_category eager loader; `project(campaign, export_ctx)` + `project_all(db, entries, export_ctx)`; update docstrings/header comment -- the fix.
- `src/backend/app/services/export_service.py`, `app/templates/export/campaign.html.j2` -- build from projected models; Shorthand line only if present -- Player export carries no Shorthand.
- `src/backend/tests/access/test_campaign_permissions.py` -- replace the three old tests: Owner + Co-GM + Player authors all counted/exported for a GM; Player counts/weeks/top tags/export Party-only; preview → Player view -- AC 1–2.
- `src/backend/tests/ev4/probes/campaigns.py` -- export (markdown and pdf) and analytics allowed for every authenticated Member of A. For non-GMs: `assert_counts_and_ranking_unchanged` on analytics and the markdown export across two mutations, first planting another Player's Private entry plus a shorthand-derived tag, then a GM-only entry with a canary tag; also `assert_no_canary` on the markdown bytes and on the PDF extracted text (extract once per response). For GMs: the planted Private entry's narrative and its own `XSH` Shorthand token appear in the export, and analytics `total_entries` counts it -- EV-4.
- `src/backend/tests/access/test_grants.py`, `tests/ev4/probes/grants.py` -- demotion checks use a still-gm route -- keep them meaningful.
- `src/backend/tests/test_export_pdf.py` -- Player PDF has narratives but no Shorthand -- PDF path.

**Acceptance Criteria:**
- Given entries from the Owner and two Members, when a GM calls analytics or export (markdown|pdf), then totals and export include all three authors' entries.
- Given a Player, when they call the same routes, then counts, weekly totals and tag rankings use only Party entries plus their own Private ones, and the export holds only Party-visibility narratives (not even their own Private ones) with no Shorthand.
- Given EV-4, when a GM-only entry with a unique tag is added, then the Player's analytics, tag ranking and export are unchanged and carry no canary; anon and Share Link actors get the missing-Campaign 404.

## Spec Change Log

### 2026-11-20 — Review loop 1 (bad_spec)
- **Trigger:** the intent auditor found that the story's export AC says "only Party Narratives", while analytics says "Party entries plus the Player's own Private entries". The spec's Design Notes had merged the two, so a Player's export included their own Private entries. A blind-hunter finding and CI also showed every export failing with `MissingGreenlet`, because `JournalEntry.tags` was lazy-loaded.
- **Amended:**
  - The Design Notes now give the Player's export its own ctx, `audience_ctx(..., MEMBER_VIEW, by=ctx)`, and require the tags/custom_category eager loader.
  - The campaigns.py task, the Player AC, and the EV-4 probe task now cover a positive GM check and a count check on the private-entry mutation.
- **Known-bad state avoided:**
  - A Player's export carrying their own Private entries, against the story's literal AC.
  - A 500 on every non-empty export.
- The reverted first-pass implementation is commit `b051e05abbef245f7562615436e5573315d78dac` (`git show` it). Reuse its KEEP parts verbatim.
- **KEEP:**
  - Both routes on `_player` with the author filter removed. Analytics unchanged from the first pass: `scoped_select` on `ctx`, `top_tags` via `scoped_select(JournalTag, ctx)`.
  - `export_service.py` and the template built from projected models, printing Shorthand only via `getattr(entry, "shorthand", None)`, so GM markdown output stays byte-identical.
  - The `authors` fixture design in `test_campaign_permissions.py`, the preview and non-member 404 tests, the demotion checks moved to `POST /tag-categories`, and the PDF Player test.
  - The PR #61 header comment (account gate, `can_write`), merged with the E0-Access.13 note.
  - The test name `test_drafts_are_gm_only_and_gms_keep_gm_context`, which comes from main.

## Review Triage Log

### 2026-11-20 — Review pass
- verdicts: 18 findings — high 3, medium 1, low 8, false 6, maybe-false 0
- findings:
  - `[high]` `[bad_spec]` (blind) The export does not eager-load `JournalEntry.tags`, so it raises MissingGreenlet → amended Design Notes and the campaigns task to require the eager loader. CI confirmed it: every export test failed with MissingGreenlet.
  - `[low]` `[reject]` (blind) Exported entries have no author or visibility labels. This is a feature request the story does not ask for, a GM export is the GM's own material, and the fix adds rendering branches.
  - `[false]` `[reject]` (blind) A Player's export drops their own Shorthand. The story says the export carries "no Shorthand", and Shorthand is a GM field in the registry.
  - `[low]` `[bad_spec]` (blind) The analytics probe makes no positive check for a GM → added to the EV-4 probe task.
  - `[medium]` `[bad_spec]` (blind) The probe never snapshots counts across the other Player's Private entry → the probe task now runs `assert_counts_and_ranking_unchanged` over the private-entry mutation too.
  - `[low]` `[bad_spec]` (blind) The GM check in the export probe is weak ("Notes:" anywhere) → the probe task now requires the planted entry's own XSH token.
  - `[medium]` `[defer]` (blind) PDF export is open to every Member with no rate limit or cap. Whether it is actually costly is unverified, and throttling is not this story's scope (see `deferred`).
  - `[low]` `[reject]` (blind) The PDF text comparison is fragile. For the same content WeasyPrint lays out the same text deterministically, and the dates come from entry data. "Extract once" is folded into the probe task.
  - `[low]` `[reject]` (blind) Unit-test gaps: preview `entries_per_week`, a player_2 PDF, an empty export. These paths share code with the tested ones, and an empty export renders the header (an empty loop).
  - `[low]` `[reject]` (blind) Docs, changelog and privacy copy are not updated. There is no CHANGELOG in the repo, and GM visibility of Private entries is the existing Audience rule (AD), not new.
  - `[high]` `[bad_spec]` (intent) A Player's export included their own Private entries, against "only Party Narratives" → Design Notes now use `audience_ctx(MEMBER_VIEW)` for a non-GM export.
  - `[false]` `[reject]` (intent) "Per-Session totals" and "contributions" are missing. The technical notes say "analytics and export scope only" and E9 replaces analytics. The AC lists what the scoping covers, and `entries_per_week` is the existing per-period total.
  - `[false]` `[reject]` (intent) "No NPC or Quest notes" is untested. `assert_no_canary` scans for every seeded canary, including the NPC and Quest notes canaries in the EV-4 seed.
  - `[false]` `[reject]` (intent) The PDF is checked on extracted text, not bytes. Raw PDF bytes are compressed, so a byte scan can never find a canary. Extracted text is the stronger check.
  - `[false]` `[reject]` (intent) The demotion checks moved to tag-categories. This is required, because analytics is no longer GM-only.
  - `[false]` `[reject]` (verification-gap) No gaps reported, so there is nothing to act on (recorded as its single report).
  - `[high]` `[bad_spec]` (edge) The tags lazy load returns a 500, grouped with the first blind finding → same amendment.
  - `[high]` `[bad_spec]` (edge) The `custom_category` lazy load, grouped with the first blind finding → the eager loader chains `.selectinload(Tag.custom_category)`.

### 2026-11-20 — Review pass 2 (after loop 1)
- verdicts: 21 findings — high 0, medium 0, low 15, false 6, maybe-false 0
- findings:
  - `[low]` `[reject]` (blind) The GM export has no author or visibility labels. Carried from pass 1: a feature request outside the story.
  - `[false]` `[reject]` (blind) A Player's analytics and export cover different row sets. This follows the story's AC wording on purpose (Design Notes, loop 1).
  - `[low]` `[patch]` (blind) Nothing stops an ORM row reaching `export_service` → `_shorthand` now raises TypeError for anything that is not a projected pydantic model.
  - `[low]` `[reject]` (blind) The demotion test no longer checks analytics narrowing. Role resolution per request is covered by the grants tests; it would only add assertions.
  - `[low]` `[reject]` (blind) Analytics gaps: tags on own Private entries, player_2's top tags, avg length. These come from the same scoped query as fields that are asserted.
  - `[low]` `[reject]` (blind) The non-GM PDF baseline is taken after the first mutation. The markdown export is compared across that mutation, and both formats come from the same projected row set.
  - `[false]` `[reject]` (blind) The GM PDF probe has no presence check. `test_export_pdf.py::test_pdf_for_a_player_has_party_narratives_and_no_shorthand` asserts the GM PDF holds the Notes lines and the Private and GM-only narratives.
  - `[low]` `[reject]` (blind) The export eager-loads tags it never renders. `project()` requires the load, and a tag-less variant adds projection surface.
  - `[low]` `[patch]` (blind) The analytics docstring omits preview → added "A GM previewing as a Player gets the member view".
  - `[false]` `[reject]` (blind) Analytics should use an explicit ctx like export. The difference is deliberate (AC wording); analytics on `ctx` is the Audience scope the story names.
  - `[low]` `[defer]` (edge) No row cap or render timeout. Carried; already deferred.
  - `[low]` `[reject]` (edge) An empty Shorthand renders "*Notes: *". This is pre-existing GM output, kept byte-identical on purpose.
  - `[low]` `[reject]` (edge) PDF line wrapping in the unit-test phrase asserts. CI is the arbiter: a wrapped phrase fails loudly, and the "not in" checks target single tokens.
  - `[low]` `[patch]` (edge) A canary wrapped across lines would go undetected → the probe also scans the extracted text with line breaks removed (CANARY_RE has a fixed-length uuid, so no false merges).
  - `[low]` `[reject]` (edge) PDF snapshot after the first mutation. Duplicate of the blind finding above, same reason.
  - `[low]` `[reject]` (edge) The deleted analytics-after-demotion check. Duplicate of the blind finding above, same reason.
  - `[false]` `[reject]` (edge) The Approach claim contradicts the AC. The intent-contract is read-only, and the Design Notes record the resolution.
  - `[false]` `[reject]` (edge) Unscoped tag-link reads. `project()` filters tag links through `audience_of` and the Party schema, and the export renders no tags.
  - `[low]` `[patch]` (edge) The `anonymous` actor was not probed on export or analytics → both probes now add "anonymous".
  - `[false]` `[reject]` (verification-gap) No gaps reported.
  - `[low]` `[reject]` (intent) Divergences already triaged in pass 1: preview 200, GM sees Private entries, "per-Session totals", the PDF checked as text. These are carried, and the auditor raised nothing new.

## Design Notes

Analytics and export use different row sets for a non-GM, exactly as the story's AC words them. **Analytics** run on `ctx` (Party entries plus the Player's own Private ones). **Export** for a non-GM runs on `audience_ctx(ctx.campaign_id, MEMBER_VIEW, by=ctx)`, which gives "only Party Narratives". That ctx reads as a generic Member with no user, so it excludes the Player's own Private entries, and through the Party projection it yields no Shorthand. A GM's export runs on `ctx` itself. Use this same reduced ctx for `scoped_select`, `project` and `project_all` in the export, so E8 can reuse the pattern. The export query must eager-load `selectinload(JournalEntry.tags).selectinload(Tag.custom_category)` (the same loader as `journals._ENTRY_TAGS`). `project()` reads `obj.tags` and `_project_tag` reads `custom_category`, and a lazy load on the AsyncSession raises `MissingGreenlet`.

The account gate from PR #61 (export/analytics need a paid account) is left as is; whether an unpaid Player should read these is an owner question (deferred).

## Verification

**Commands:**
- `pytest tests/access/test_campaign_permissions.py tests/access/test_grants.py tests/test_export_pdf.py tests/ev4 -q` (desktop container or CI) -- expected: all pass, 0 EV-4 leaks
- `python scripts/check_scoped_queries.py` -- expected: clean, no baseline additions

## Auto Run Result

Status: done

- **What changed:**
  - `GET /api/campaigns/{id}/analytics` and `/export` now take `require_campaign("player")`, and the per-author filter is gone.
  - Analytics use `scoped_select` on the caller's ctx. A GM sees every Member's entries. A Player sees Party entries plus their own Private ones.
  - Export for a GM uses `ctx` (every author, with Shorthand). Export for a non-GM uses `audience_ctx(MEMBER_VIEW)` and gives Party narratives only, with no Shorthand.
  - The export is built only from `project` and `project_all`, with tags and custom categories eager-loaded.
- **Files:**
  - `app/api/routes/campaigns.py`: the route fixes above.
  - `app/services/export_service.py`: built from projected models, and refuses ORM rows.
  - `app/templates/export/campaign.html.j2`: the Notes line is guarded.
  - `tests/access/test_campaign_permissions.py`: an authors fixture plus GM, Player, preview and non-member tests.
  - `tests/test_export_pdf.py`: a Player PDF test.
  - `tests/ev4/probes/campaigns.py`: every Member is probed, plus anon and anonymous. Counts are checked unchanged across a private-entry mutation and a GM-only mutation. Canaries are checked in markdown and in PDF text.
  - `tests/access/test_grants.py` and `tests/ev4/probes/grants.py`: the demotion checks now use a route that is still GM-only.
- **Review:**
  - Pass 1 led to one bad_spec loop: the Player export scope, and the MissingGreenlet from the tags lazy load.
  - Pass 2 applied 4 low patches. One item is deferred (PDF throttling), plus an owner question on the account gate.
  - All rejected items and their reasons are in the triage log.
- **Follow-up review recommended:** false. Pass 2 patched only low findings.
- **Verification:**
  - GitHub CI is green on a9ac454: full backend 2358 passed / 4 skipped; gates EV-4 probes=96, leaks=0; CI-8 clean with no baseline lines; frontend and licences green.
  - Desktop was unreachable, so CI was the gate.
- **Residual risks:** PDF render cost now applies to every Member (deferred). Unpaid Players still hit the PR #61 account gate on these routes (owner question).
- **Needs desktop verification:** none beyond CI. Optional: `pytest tests/test_export_pdf.py tests/ev4 -q` in `lorekeeper-backend-test` against real WeasyPrint fonts.

### Coordinator follow-up: rate limits
- Added per-user slowapi limits keyed by `user_or_ip` (E0-Platform.8): PDF export 5/minute, Markdown export 10/minute (separate buckets via `_export_key`), analytics 30/minute.
- A denied caller fails in `require_campaign` before the limiter runs. So a hidden Campaign answers 404, never 429, even past the limit.
- New test: `test_export_and_analytics_are_rate_limited_per_user`. It covers PDF, Markdown and analytics, and checks the 429 for the same user, that other users are unaffected, that the two formats have separate buckets, and the 404 (not 429) for a non-member.
- PDF entry cap: deferred. The story defines none, and a silent cap would truncate the export.
