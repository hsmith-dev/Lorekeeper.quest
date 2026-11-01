---
type: review
lens: reconcile-prd
target: ARCHITECTURE-SPINE.md (draft, 2026-10-31)
sources: prd.md (FR-1..FR-55, NFR-1..NFR-11, EV-1..EV-6), addendum.md
created: 2026-10-31
---

# Reconcile review: Architecture Spine vs PRD

## Verdict

**Revise before epics.** The spine is strong on the transport and substrate requirements: Jobs, model sidecars, structured output, the single Canon write path, file serving and the Live WS. Most FRs have a clear home. The gaps cluster in one area, which is how Visibility *propagates*. The PRD's quiet requirements are mostly unhomed: derived-content invalidation, the "members but not Share Links" tier, merge redirects, delete effects, chat archival on demotion and inference channels. Each has an enforcement point in AD-13, but no rule that says what that point must do. That is exactly where E0-Access, E1, E5, E6, E7, E8 and E9 will each make up their own answer. There are also two internal contradictions: proposal fingerprint vs supersede, and Foundation-migration ownership vs the boundary map. One FR (FR-29) has a model-work need with no Job or context-window strategy.

Counts: 3 critical, 10 high, 15 medium, 9 low.

What landed well (no action): AD-2/AD-4 BYOK-at-run-time and no keys in payload (FR-1); AD-5 GM-only `result_ref` (FR-2); AD-8 (FR-3); AD-9/AD-18 (FR-4/FR-5 mapping, legacy links, idempotent migration); AD-11 conflict_key (FR-21 "same conflict"); AD-12 `kind=player` hidden from anon (FR-42, journal rows only); AD-13 uniform 404, party schemas omit fields, AI context through ctx, `party_tsv`/`party_embedding` (FR-9b); AD-13 stream re-check (FR-44 open streams close); AD-14 tiles never contain pins (FR-54); AD-15 (FR-26 backlog and reconnect); Graph convention returns pre-filtered nodes and edges, so layout, counts and search are client-side over Party data (FR-25).

---

## Critical

### C1. The Visibility lattice cannot express "Members but not Share Links", so derived content from shared Player Journals leaks to anon (FR-42, FR-40, FR-8 "derived content", NFR-5)

AD-12 handles the FR-42 rule ("Shared entries are visible to Members but never to read-only Share Links") with `journal_entries.kind=player` that anon "never sees". But derived records compute their visibility through `access.effective_visibility()` and `most_restrictive()` over `{party, gm, private}`. A shared Player entry is `party`, so everything derived from it is `party` and reaches anon Share Links. That includes Mentions shown on an Entity panel, proposals promoted from it (FR-42 → FR-8 "visibility follows evidence"), a recap built from "Party content", a Player-edition Chronicle file, stats counts and `stored_files.visibility`. The ordering is also undefined. `private` is author-relative, so `most_restrictive(private(A), gm)` and `most_restrictive(private(A), private(B))` have no stated answer. Neither does the default visibility of a proposal whose quote lies in a Private Player entry (AD-11 `source_field` has no player value).
**Fix (AD-12/AD-13):** Define the effective-visibility lattice explicitly as `anon_party < member_party < private(author) < gm`, with `private(A) ⊓ private(B) = gm`. Make `effective_visibility(record)` return `(level, author_id|None)` and fold in `kind=player → at least member_party`. Make `stored_files.visibility` and every derived row store or compute that tuple, and make `CampaignContext(role=anon)` reject `member_party`. In AD-11, state that a proposal evidenced only by a Private Player entry defaults to `gm`, and one evidenced by a shared Player entry defaults to `member_party`.

### C2. Visibility changes have no single trigger and no registry of derived content (FR-41, FR-32, FR-9 cache note, FR-48, FR-54, NFR-5)

AD-13 lists `on_visibility_change(db, ref)` and AD-17 lists a `visibility_changed` hook. Nothing states:
- **The trigger.** Every Visibility write must go through one setter, but entries go through `journal_service`, entities through `apply_change`, maps through `map_service`, and FR-41 bulk changes are owned by E7.
- **The registry.** Nothing enumerates which derived records depend on which sources. AD-14 covers only `stored_files.stale`. These are unhomed:
  - `recaps` text (a Party recap still holds text from an entry that is now GM-only; FR-32 asks only about audio);
  - NPC and Chronicler chat history that is redisplayed or replayed;
  - `user_achievements` and Milestones;
  - Rolling Recaps;
  - the Redis `cache:journals:{user_id}` (addendum C: keyed by user, not role);
  - any react-query or Redis cache of role-filtered lists.
- **Loosening.** AD-14 fixes a derived file's visibility "at creation". A GM who publishes a GM-only Map to Party leaves its tiles `gm` (404 to Players) until they are regenerated.

**Fix:** In AD-13, add `access.set_visibility(db, ctx, ref, vis | field_map)` as the only Visibility mutator. It is called by `journal_service`, `apply_change` and the map and file services, and it fires `visibility_changed` in the same transaction (or an outbox). Add a `DERIVED_REGISTRY` in `access.py`, next to `VISIBILITY_REGISTRY`, in which each epic registers `(derived_model, source_refs_resolver, on_restrict: hide|stale|recompute, on_loosen: recompute|inherit)`. Require `source_refs` on `recaps`, `chat_messages` (sources), Chronicle files and tiles. Rule that tiles and other "pure projection" files take visibility from their parent at read time and are not snapshotted. Rule that every server-side cache key includes `(user_id, campaign_id, role_version, campaign.visibility_epoch)`, where `visibility_epoch` is bumped by `set_visibility`, or else is invalidated by `role_changed`/`visibility_changed` handlers.

### C3. Merge leaks hidden identity and hidden edges (FR-17, FR-15, FR-8 "reference removed", EV-4)

AD-9 says "every resolver follows `merged_into_id`", and AD-10 says merge is a composition of `apply_change`. FR-17's visibility rule ("each merged field and alias keeps the more restrictive Visibility", plus the GM warning) is not stated anywhere. There are two concrete leaks:
1. A Player fetching the old id of a GM-only Entity used to get 404. After it is merged into a Party Entity, the resolver redirects, which reveals "the masked stranger *is* the innkeeper".
2. Relationships, Mentions and aliases that belonged to the GM-only Entity are re-pointed at a Party survivor. They were previously stripped as "references to a hidden record" and now become visible.

**Fix (AD-10):** Add a merge rule with three parts:
- Re-pointed Relationships, Mentions, aliases and field values get `visibility = most_restrictive(own, source_entity.visibility)` in the same `apply_change` batch.
- `merged_into_id` resolution goes through `access`. It redirects only if the requester could see the *removed* Entity, and otherwise returns 404.
- The merge endpoint returns a `visibility_downgrades[]` preview that the UI shows as the FR-17 warning.

Also require chain resolution to the terminal survivor with cycle prevention (`merged_into_id` must point at an unmerged row).

---

## High

### H1. Delete effects are undefined for Journal Entries and Entities (FR-6, FR-11, FR-36, FR-53)

AD-10 "binds" FR-6 (source deleted), but there is no rule. Nothing says whether deletes are hard or soft. Nothing says what happens to `entity_changes.source_journal_id` (a SET NULL FK loses "source deleted"), or where "Canon fields whose only source was that entry are flagged for GM review" lives: no table or state exists for it. Nothing covers what happens to:
- `entity_relationships` and `quest_steps` source entries;
- `npc_knowledge` grant rows on that `journal_id`;
- `map_pin_entries`;
- pending `proposal_batches` and `continuity_flags` of the entry;
- stored chat `sources` (FR-6 says "citations stop resolving", but chat messages keep quote snapshots);
- recaps and Chronicles built from the entry.

FR-11 Entity delete has the same problem: Mentions, Relationships, Pins, `chat_sessions.npc_entity_id`, and AD-10 "marks stale if … deleted", which implies the row must still exist.
**Fix:** Add a "Delete semantics" rule to AD-10 or AD-17:
- `journal_entries` and `entities` are soft-deleted (`deleted_at`). Resolvers and `scoped_select` treat a soft-deleted row as nonexistent (404), so hidden, deleted and nonexistent responses stay identical.
- `delete_entry` runs, in one transaction: delete Mentions and `npc_knowledge` rows; mark pending proposals `superseded` and open flags `dismissed:source_deleted`; append `entity_changes(op='source_deleted')` for each Canon value whose sources are all deleted; and create a GM review item (a `change_proposals` op `review_source_deleted` in a system batch, so it renders in the existing checklist).
- Chat `sources` are stored as refs only and resolved at read time through `access`.
- `entry_deleted` reaches the C2 derived registry.

Add the same per-table effect list for `delete_entity`.

### H2. The proposal fingerprint uniqueness contradicts supersede-on-edit (FR-6, FR-13, FR-18)

AD-11 has `UNIQUE(journal_id, fingerprint)` "whether the existing row is pending or already decided". AD-17 marks pending proposals `superseded` on edit and queues new extraction. Any fact still present after the edit then produces the same fingerprint, the insert is a no-op, and the still-valid proposal vanishes from the checklist.
**Fix (AD-11):** Make the uniqueness `UNIQUE(journal_id, fingerprint) WHERE state <> 'superseded'`, or have re-extraction revive a matching `superseded` row to `pending`. State that `rejected` and `approved` still suppress (FR-15, FR-18).

### H3. There is no write-authorization predicate, no Owner tier and no defined Character Sheet ownership (FR-7, FR-42, FR-44, FR-6 last bullet)

AD-13 forbids routes from comparing roles, but `access.py` exposes only read tools (`scoped_select`, `project`) and `require_campaign(min_role="player"|"gm")`. Several write rules have no API:
- FR-7 "a Player writes only own Player Journal entries and own PC's Character Sheet; any other write returns not-found";
- "Campaign management stays Owner-only" (a Co-GM is a GM);
- which Visibility values a Player may set (Private or shared, never `gm`, never anon-visible);
- how a "Character Sheet" relates to `entities.linked_user_id`, that is, whether it is the existing `character_sheets` table or PC Entity fields. If it is the Entity, AD-10 says only GM contexts may call `apply_change`, which contradicts FR-7.

E0-Access, E7 and E0-WorldCore will each answer these differently.
**Fix (AD-13):** Add `access.authorize_write(db, ctx, obj_or_model, action) -> None | raises NotFound`, backed by a `WRITE_POLICY` table: (model, action) → {owner, gm, author, linked_pc_player}. Add `require_campaign(min_role="owner")`. Rule that a Player may set only `private | member_party` on their own `kind=player` entries. In AD-12, state that a Character Sheet is the existing `character_sheets` row with `entity_id` FK to the PC, writable by `entities.linked_user_id`, and that PC Entity Canon fields stay GM-only writes through `apply_change`.

### H4. Chat archival on demotion has no rule, and its column lands two phases late (FR-9 last bullet, FR-44)

FR-9 is Phase 0 and never cut. The spine puts `chat_sessions.archived_at` in E6 (Phase 2) and states no handler: "on `role_changed` co_gm→player (or removal), archive that Member's chat and NPC sessions in that Campaign, and history loaders exclude archived sessions". The Chronicler history loader (E0-Access refactor) and the NPC loader (E6) both need the exclusion.
**Fix:** Move `chat_sessions.archived_at` (and `campaign_id` if it is absent) into the Foundation migration under E0-Access. Add a `role_changed` handler in `access_hooks.py` owned by E0-Access, and a rule that every chat history loader filters `archived_at IS NULL` through one function, `chat_service.load_history(ctx, session_id)`.

### H5. Table ownership contradictions between AD-19 and the boundary map (AD-19, FR-4/5 phasing, FR-9)

- AD-19 says the Foundation migration creates `jobs`, `data_backfills`, `stored_files`, `entities` and all satellite tables.
- The boundary map gives `jobs`/`data_backfills` to E0-Jobs, the entity tables to E0-WorldCore (which ships with F1 in Phase 1, per PRD §4), and `stored_files` plus `files.py` to "whichever of E5/E8/E10 lands first". E10 separately says `file_service.py` is "owned by E0-Jobs if it lands first".
- `chat_sessions.archived_at` is assigned to E6 (see H4).

Two epics will both author the same DDL, or each wait for the other.
**Fix:** Pick one owner per table and state it once. The Foundation migration (E0-Access) creates enums, role and visibility columns, party columns, `chat_sessions.archived_at` and `stored_files` plus `file_service`/`files.py` (needed by FR-8 "every stored file served through an access-checked route" in Phase 0). E0-Jobs creates `jobs`/`data_backfills` in its own revision. E0-WorldCore creates the entity tables in its revision. Then delete the "whichever lands first" clauses.

### H6. FR-29's full-transcript hand-off has no Job and no context-window strategy (FR-29, FR-1, AD-7)

A 2-hour transcript (about 15–20k words) must become a draft "with no silent truncation" through "the existing summarize-to-shorthand flow". The baseline Ollama `num_ctx` is 4096 (AD-7), and the existing flow is a single in-request call. AD-2 doesn't bind FR-29, and no job kind exists for it.
**Fix:** Add job kind `live.handoff` on `onsave`, released when the session ends under the admission rule. It runs a map-reduce over the `live_segments` windows that fit `num_ctx`, through `complete_structured` or `summarize` with a checkpoint per window (AD-3 "one entry's worth" becomes one window), and writes a draft entry that is never saved until the GM approves it. State the window/overlap parameters as provisional under SPIKE-6.

### H7. FR-1 priority is not enforced for in-request interactive LLM work (FR-1 priority, FR-35, FR-28, NFR-6)

AD-3 orders RQ queues, but NPC replies and the Chronicler free-text lookup run in the web process and share the single Ollama slot (`OLLAMA_NUM_PARALLEL=1`) with a running `onsave` extraction that can hold it for minutes. That breaks "interactive first" and the ≤20 s first-token target. The AD-7 admission rule only covers Live Sessions.
**Fix (AD-3/AD-8):** Add an LLM gate in `llm_provider` for the local provider: a Redis-backed priority semaphore `llm:local` where interactive callers jump the queue, and Jobs acquire it per call, not per Job. Require Job handlers to split model work into bounded calls (≤ about 60 s each, provisional under SPIKE-6) so an interactive request waits at most one call. BYOK-configured calls bypass the gate.

### H8. Inference channels are not closed by the enforcement design (FR-8 "identical to not found", FR-25, FR-49, EV-4 inference channels)

- **CI scan.** `check_scoped_queries.py` scans only `select(<model>)`. It misses `db.get(Model, id)` (the bare-id fetch FR-8 calls out), `text()` SQL (hybrid search), `session.query` and ORM relationship lazy loads (for example `entity.mentions` or `entity.relationships` loading hidden rows into `project`).
- **Ids in filters and bodies.** No rule covers ids in query filters or bodies (`GET /api/proposals?journal_id=<hidden>`, `npc_entity_id`, `location_entity_id`). A hidden id that yields an empty 200 while a nonexistent one yields 404 is an oracle.
- **Filter before LIMIT.** No rule says the Visibility predicate is applied before LIMIT and ranking in retrieval, so a top-k candidate pool could still be shaped by hidden rows.
- **Counts.** No rule covers pagination totals, tag counts or list `total` fields.

**Fix (AD-13):**
1. Extend the CI check to `db.get`, `text(` on registered tables, and `relationship()` without `lazy="raise"` on registered models (relationships must be loaded through `scoped_select`).
2. Add `access.resolve_ref(db, ctx, Model, id)` for every id that arrives in a path, query or body, with identical 404 for hidden and missing.
3. State that every retrieval applies the ctx predicate inside the SQL before ranking or LIMIT.
4. State that any count or total is computed by the same scoped query.

### H9. NFR-1 offline install is not specified for the sidecar model weights (NFR-1, NFR-3, FR-30)

AD-7 has stt "loaded on first use" and NLI/OCR loaded lazily, but no rule says where the weights come from. faster-whisper, sentence-transformers and HF cross-encoders download from the Hub on first load by default, which is a new outbound call and an offline failure. Diarization weights are account-gated (R-4).
**Fix (AD-6):** Rule that sidecar weights are either baked into the image at build time or installed into a named `models_data` volume through the existing admin model-install flow (an offline bundle import). Sidecars run with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. `/v1/status` reports missing weights, and the UI hides the dependent feature (FR-30 "option hidden").

### H10. Queued Jobs can still be silently lost (FR-1 "no Job silently lost", AD-2 "prevents jobs lost on a Redis flush")

AD-4's boot recovery handles only stale `running` rows. A `queued` row whose RQ message was lost (Redis restart without AOF, or a flush) is never picked up, and neither is a row left behind when the process dies between commit and RQ push. AD-17 hooks run *after* commit, which opens a window where the entry is saved and the extraction Job is never created.
**Fix (AD-2/AD-4):** Add a reconciler, run at worker boot and every N minutes, that re-pushes `queued` rows older than X seconds that are absent from RQ, deduplicated by `job_id`. Rule that hook handlers which enqueue Jobs insert the `jobs` row in the triggering transaction (an outbox), with the RQ push after commit. Set Redis `appendonly yes` in the profiles.

---

## Medium

### M1. Job identity, ctx freshness and failure-text exposure (FR-1, FR-2, Glossary "Job owner", FR-44)

- **Owner.** The owner of hook-created Jobs is undefined. A Co-GM's edit uses the Co-GM's BYOK and quota, and the Owner's is never used. Nothing says this.
- **Boot backfills.** `data_backfills` Jobs run at boot have no user, but `handle(job, ctx)` requires a `CampaignContext`.
- **Stale ctx.** The ctx is captured at enqueue. A Player removed, or a Co-GM demoted, before the Job runs still gets a GM- or Player-scoped export.
- **Failure text.** FR-2 says failure reasons are GM-only "whoever triggered the Job", but AD-5 sends `error_message` to the Job's non-GM owner.
- **Stage text.** `stage` is free text and could carry entry titles.

**Fix (AD-2/AD-5):** Add `jobs.owner_user_id` (= the actor of the triggering request) and use it for the LLMConfig. Define `CampaignContext.system(campaign_id)` (GM-equivalent, no LLM) for boot backfills, and forbid LLM calls from it. Re-resolve ctx from `owner_user_id` at run start: if the role dropped below what the kind requires, cancel with `error_code=access_changed`. Make `stage` a closed enum. Non-GM owners get `error_code` plus a generic message, and GMs get `error_message`.

### M2. The Live Session admission rule is global, unsignalled and can stall forever (AD-7, FR-1, NFR-6, NFR-11)

"While a Live Session is active in any Campaign, workers consume only `interactive`."
- One Campaign's session therefore pauses every other Campaign's on-save Jobs for up to 4 h (NFR-6 is ≤ 3 min).
- No mechanism is defined for how workers learn that a session is active.
- An abandoned session (tab closed without End) blocks on-save Jobs indefinitely.

**Fix (AD-7/AD-15):** Define the signal as a Redis key `live:active:{id}` with a TTL refreshed by the drainer heartbeat (for example 120 s). It auto-expires, and the session is auto-ended after N minutes without audio. State that the global pause is a baseline-profile-only rule (the full profile keeps `onsave` running) and that the UI shows "queued until Live Session ends" on the affected Jobs. Record the NFR-11/NFR-6 tension for the owner as a Q4 corollary.

### M3. Raw audio retention timing and deletion have no home (FR-29, FR-30, NFR-5, FR-52 backups)

FR-30 lets the GM request labels "before the Live Session ends", but AD-15 discards chunk audio after transcription unless keep or diarize was already set. Labels requested at minute 60 would lose minutes 0–60. No Job or hook performs "delete once transcribed", "delete when the diarize Job finishes" or "delete at session end". `stored_files` has no byte-deletion or GC rule at all (map replace, recap re-narration, Chronicle regeneration).
**Fix (AD-14/AD-15):** Choose one rule. Either the keep/diarize choice is fixed at session start (the UI asks then), or all chunk audio is held as `stored_files(kind=live_audio, gm)` until `live_session_ended` plus diarize completion, then deleted. Add `file_service.delete(file_id)` (row plus bytes, in the worker) and a `files.gc` backfill Job for orphaned or superseded files. State that kept raw audio is excluded from backups unless the GM opts in.

### M4. The Live drainer has no single owner across web workers (FR-26, AD-15)

With gunicorn `-w 2`, a reconnect can land on the other worker, which starts a second drainer and produces duplicate or out-of-order segments (`live_segments` has no stated uniqueness). Nothing says whether draining continues while no socket is connected, which FR-26 requires for "resume with no loss".
**Fix (AD-15):** The drainer holds a Redis lock `live:{id}:drainer` (TTL plus heartbeat) and is decoupled from the socket. It runs while the session is active, whichever worker holds the lock. Add `UNIQUE(live_session_id, seq)` on `live_segments`. Captions are fanned out to sockets through pub/sub `live:{id}`.

### M5. Extraction and continuity ordering, and flags on proposals (FR-22, FR-19, FR-6)

FR-22 needs the continuity check to see the entry's *proposals*, but both Jobs are fired independently from `entry_saved`. `continuity_flags` has no `proposal_id`. Nothing says what happens to open flags on the old text when an entry is edited, so they would duplicate the new check's flags.
**Fix (AD-11/AD-17):** `continuity.check` either runs after `extraction.run` (chained on `job_finished`, or with a separate `continuity.check_proposals` kind) or extraction calls a continuity service function for each proposal. Add a nullable `continuity_flags.proposal_id`. On `entry_updated`, open flags of that entry become `superseded`, and dismissed or overridden flags are kept, as the conflict_key requires.

### M6. Stats and Achievements have no visibility model (FR-49, FR-50, FR-10, EV-4 counts)

`activity_events` and `user_achievements` (E9) have no visibility or source refs, yet FR-49 and FR-50 require every Player-visible stat and Milestone count to come from Player-visible content. Visibility can also change after an event is logged. "Contributions per Member", "100 Entities" and "first Quest completed" (on a GM-only Quest) are count oracles.
**Fix:** In AD-12 or E9, state that Player-facing stats are computed at query time through `scoped_select`, never from pre-aggregated events. `activity_events` carry `source_ref` and are filtered with `effective_visibility` at read time. Achievements are evaluated per user over that user's ctx view, so a Player is never awarded from content they cannot see, and they register in the C2 derived registry.

### M7. "View as Player" has no ctx mechanism (FR-41)

"Renders through the same filtered read path a Player uses" requires a GM to obtain a downgraded ctx. Nothing defines how (header, query or route), whether it impersonates a specific Player ("my character" and their Private entries) or a generic one, or that it must be read-only.
**Fix (AD-13):** Add `require_campaign` support for `X-View-As: player[:user_id]` for GMs only. It produces `CampaignContext(role=player, user_id=<target or None>, preview=True)`, all writes return 404, and EV-4 probes it.

### M8. The Chronicle Player-edition ctx is wrong for both callers (FR-45, FR-48)

AD-13 says "a Player-edition export runs as that Player", but that ctx includes the Player's own Private entries (scoped_select includes the author), which contradicts "Party content only". A GM exporting the Player edition has no defined ctx. The file's visibility (anon-downloadable or not) is also undefined when shared Player Journals are included (see C1).
**Fix (AD-13/AD-14):** Build the Player edition with `CampaignContext.party(campaign_id, include_shared_player_journals: bool)` whatever the caller. Its file gets `member_party` if it includes shared Player Journals and `anon_party` otherwise. The GM edition uses the GM ctx and the opt-in flags.

### M9. Entity history visibility is not derived (FR-16, FR-8 "Entity history", FR-21)

`entity_changes` has no visibility rule. Its rows can expose GM-only field values (`old_value`/`new_value`), links to GM-only source entries and `canon_note_id`. A Canon Note with no accepted change has no history row, but FR-21 requires it to appear in the Entity's history.
**Fix (AD-10/AD-12):** Register `entity_changes` as a derived record whose effective visibility is `most_restrictive(field visibility now, source entry, canon note)`. Party projection drops the source link when the source is hidden. The history read unions `canon_note_entities`, or `apply_change` writes `op='canon_note'`.

### M10. Cross-Campaign referential integrity is not enforced (FR-4)

"Mentions, Relationships and NPC Knowledge never cross Campaigns". Today every FK goes to `entities.id` alone, so a bad Relationship, Pin, merge or grant can join two Campaigns.
**Fix (AD-9):** Use composite FKs `(campaign_id, entity_id) → entities(campaign_id, id)` on satellite tables, or have `apply_change` and `resolve_ref` assert the same campaign, with a DB CHECK trigger as the backstop. Merging across Campaigns is rejected.

### M11. FR-15 redirect to the surviving Entity is not stated (FR-15, FR-17)

AD-10 marks a proposal stale when its target was merged, but doesn't redirect it. Proposals with secondary targets (`add_relationship` target) aren't mentioned.
**Fix (AD-10):** On approval, resolve every Entity ref in the payload to the terminal survivor. If any ref changed, set `state=stale` with the rewritten target and require re-confirmation. If a ref was deleted with no survivor, keep it stale with no approve.

### M12. FR-31 recap text generation has no transport (FR-31, AD-3)

Only `recap.narrate` is a Job. Generating "Previously on…" over up to 5 Sessions on a CPU 7B is minutes of work, and the spine says nothing about whether it streams in-request (as the Chronicler does) or runs as a Job.
**Fix (AD-3):** Pick one. Either recap text streams over SSE in-request (an `ai_gen` limit, through the H7 gate), or it is a `recap.draft` Job whose result is a draft (never persisted Canon) fetched from `recaps` routes. List it in AD-2 binds.

### M13. Auto-tags may derive from Shorthand (FR-8 Tag Categories, FR-9(b), FR-6 "tags reflect new text")

If NER auto-tagging runs on Shorthand+Narrative (the `nlp_service` labels map to TagType), tag names and tag filters become a Shorthand oracle for Players (EV-4: "a canary only in Shorthand does not change a Player's search results"). The spine is silent. This needs checking against brownfield.
**Fix (AD-12/AD-17):** Entry tags carry `source ∈ {narrative, shorthand, manual}`. Party projections and tag counts use only `narrative` and `manual`. `update_entry` recomputes the tags.

### M14. FR-18 backfill: "one Job" vs a cursor that re-enqueues itself (FR-18, AD-3)

It is unclear whether the cursor Job reuses one `jobs` row (one visible Job with per-entry progress, as FR-18 requires) or inserts a row per step (N Jobs in the UI, retry semantics per step).
**Fix (AD-3):** Use the same `jobs` row. Re-enqueue pushes the same `job_id` with `payload.cursor` advanced, progress = entries done / total, attempts reset per step, and cancel stops the chain.

### M15. FR-41 bulk visibility and `apply_change` interplay (FR-41, FR-16)

It is undefined whether Entity Visibility changes are Canon changes recorded in `entity_changes` (and revertible) or a separate path. E7 owns the bulk UI, and E0-WorldCore owns `apply_change`.
**Fix:** As part of C2, `access.set_visibility` on Entities and fields delegates to `apply_change(op='set_visibility')`, so history and revert are uniform. Bulk is a loop in one transaction with one `visibility_changed` event per ref.

---

## Low

- **L1 (FR-24).** "Approved Relationship appears without manual refresh" for viewers other than the approver needs a push channel. Add a `canon:{campaign_id}` pub/sub event, sent through the existing jobs SSE stream as `event: canon`, that invalidates `[graph|entities, campaignId]`.
- **L2 (FR-23, FR-25).** `relationship_types` names can be spoilers ("secretly serves"). Either give them visibility or state that they are Party metadata.
- **L3 (FR-26).** Pause, resume and end have no WS client message types or session states. Add `{type:"control",action}` and `live_sessions.status`.
- **L4 (FR-44).** Stream re-checks must treat a deleted `campaign_members` row, or an expired or revoked share token, as a role change. Optionally publish `role_changed` on `access:{user_id}` for immediate close instead of up to 15 s.
- **L5 (EV-4, NFR-5).** The "before each release, a live-model run of the AI routes" isn't in AD-21. Add `scripts/ev4_live.py` and a release checklist step.
- **L6 (FR-13, FR-42).** State in AD-17 that the extraction and continuity hook handlers skip `kind=player`, and that GM-triggered extraction on a Player entry is `POST /api/proposals/extract?journal_id=` with GM ctx.
- **L7 (FR-1).** Map "exhausted AI configuration" (hosted quota) explicitly to `LLMConfigError`, so it is terminal with no retry.
- **L8 (Conventions).** `GET /api/campaigns/{id}/graph` and `/me` break the "campaign_id is a query param on collection routes" convention. Either state the exception or rename the routes.
- **L9 (FR-47, FR-52, AD-7).** The 512 MB worker runs WeasyPrint and pyvips. State that Chronicles embed downscaled Map derivatives, never originals, and that SPIKE-5 measures Chronicle export with Maps.
