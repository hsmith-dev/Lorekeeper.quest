---
review: adversarial
target: ARCHITECTURE-SPINE.md (draft, 2026-10-31)
context: prd.md (final, 2026-10-31), brownfield-context.md
lens: "Build two units that each obey every AD to the letter yet are incompatible; find privacy paths that leak while every AD is obeyed; break the memory/admission model."
date: 2026-10-31
verdict: NOT READY TO BIND PARALLEL EPICS. Revise (5 critical, 14 high), then re-review.
---

# Adversarial review: Architecture Spine

## Verdict

The spine is strong on mechanics: one job table, one access module, one Canon write path, pinned model contracts. It is weak wherever the rule says *what* gets computed and not *how*. Those gaps fall into three groups.

1. **Ownership contradictions in the spine itself.** AD-19, the boundary map and the "ownership rules" give the same tables three different owners. Parallel epics following any one of these sources to the letter end up with duplicate `CREATE TABLE`s or two Alembic heads on day one.
2. **Undefined derived visibility.** AD-12 says derived visibility is "computed by `effective_visibility()`" but never gives the formula, the inputs or the lattice. The three-value enum `{party, gm, private}` cannot express two audiences the PRD needs: "Members but not anonymous" (shared Player Journals) and "private to whom" (derived from a Private record). Every epic that derives something (Mentions, history, recaps, exports, stats, chat history, tiles, audio) can therefore pick a different formula and still be compliant. Several of those compliant formulas leak.
3. **The admission model governs only RQ Jobs.** The heaviest contended resource is Ollama with `NUM_PARALLEL=1`, and the spine sends NPC replies, the Chronicler and quick lookup to it *outside* any queue. The Live-Session gate is global across Campaigns and has no definition of "active".

None of this needs a new paradigm. It needs about 20 tightened rules, listed below as **proposed AD text**. Severity reflects (a) the chance that two compliant epics collide, or that a compliant build leaks, multiplied by (b) the blast radius. A privacy leak that EV-4 would not catch ranks above one it would.

Ranking: **Critical** = a compliant build leaks GM-only content, or parallel epics cannot both merge. **High** = likely incompatibility or a leak under a common sequence. **Medium** = plausible divergence or a narrow leak. **Low** = hygiene or a theoretical channel.

---

## CRITICAL

### C1. Three owners of the Foundation tables (`jobs`, `stored_files`, `entities`*)

**Construction.**
- **E0-Access** obeys AD-19: "The Foundation migration ... creates every shared enum and table: `visibility`, `campaign_role`, `jobs`, `stored_files`, `data_backfills`, `entities` and their satellite tables ...". The boundary map gives E0-Access the Foundation migration.
- **E0-Jobs** obeys the boundary map: it "Owns (tables): `jobs`, `data_backfills`". It writes its own revision with `jobs`.
- **E0-WorldCore** obeys the boundary map: it owns `entities`, `entity_aliases`, `entity_mentions`, `relationship_types`, `entity_relationships`, `quest_steps` and `entity_changes`. It writes its own revision. The PRD ships FR-4 and FR-5 with F1 in Phase 1, while the Foundation migration ships in Phase 0.
- **E10** obeys the cross-table rule that "`stored_files` and `files.py` are created by whichever of E5, E8 or E10 lands first". The same row also says "`file_service.py` (owned by E0-Jobs if it lands first)", which names a fourth candidate that the cross-table rule excludes.

**Result.** `jobs`, `stored_files` and `entities` each get created in two revisions, or each epic waits for the other. AD-19's "rebase `down_revision` onto head" only produces a linear chain of conflicting DDL. It does not resolve them. Columns that AD-12 puts on `entities` (`field_visibility`, `linked_user_id`, `visibility`) and AD-18 adds (`legacy_npc_id`, `legacy_quest_id`, `merged_into_id`) have no single author.

**Proposed rule (replaces the AD-19 first bullet and the cross-table ownership bullets):**
> **AD-19a Foundation ownership.** The Foundation migration is split into three named revisions in a fixed order, each with exactly one owning epic:
> `F1-core` (E0-Access): the `visibility` and `campaign_role` enums, the role, visibility and party columns on *existing* tables, and `role_version`.
> `F2-jobs-files` (E0-Jobs): `jobs`, `data_backfills`, `stored_files`, `stored_file_sources` (see C4), and `app/services/file_service.py` plus `api/routes/files.py`.
> `F3-world` (E0-WorldCore): `entities` with **every** column named in AD-9, AD-12 and AD-18, and all satellite tables.
> No feature epic creates any of these. E5, E8 and E10 consume `file_service`. The boundary-map row for each table names exactly one epic, and a CI test parses the boundary map and fails if a table appears in two "Owns" cells.

### C2. Mention visibility: "stored" and "derived" at once, with the formula left open (Shorthand-quote and merge-identity leaks)

**Construction (internal contradiction).** AD-12 bullet 1 says to put a `visibility` column "on every FR-8 covered table", and FR-8 lists *Mentions*, *Entity history*, *Quest steps* and *Relationships*. The same bullet says "Derived records (Mentions and similar) get their effective visibility from `access.effective_visibility()` at read time; it is not stored."
- E0-WorldCore obeys bullet 1 and adds `entity_mentions.visibility`.
- E9 obeys AD-13 by using `scoped_select(EntityMention, ctx)` for "most-mentioned", and the registry points at that column.
- E7 obeys bullet 2 and calls `effective_visibility(mention)` = `most_restrictive(entry.visibility, entity.visibility)`.

The two now disagree on every Mention whose stored column was set at a different time from its inputs.

**Leak 1: Shorthand-sourced quote.** Take a GM entry with Party visibility. The Shorthand reads "Aldric = the traitor, met cult at bell tower" and the Narrative does not name Aldric. Extraction proposes `add_mention` with `source_field=shorthand` and that quote. The GM approves (AD-10). Under the most natural compliant formula, the effective visibility of the Mention is `most_restrictive(party entry, party entity)` = **party**. A Player opening Aldric's panel sees the Mention's *quote*, which is Shorthand. AD-11 stores `source_field` on the *proposal*, but nothing requires the Mention to carry it, and `effective_visibility` has no rule for it.

**Leak 2: merge identity.** "The Masked Man" (GM-only) is merged into "Aldric" (Party). AD-10 says merge is a composition of `apply_change`, and AD-9 says Mentions are re-pointed by FK. Every Mention of the Masked Man in a Party entry is now a Mention of Aldric, and `most_restrictive(party, party)` = party. The Player sees "Aldric" mentioned with the quote "the masked man slipped away", which reveals the secret identity. FR-17 only covers fields and aliases. Because visibility is "not stored", the absorbed Entity's GM-only status cannot be carried anywhere.

**Leak 3: NPC Knowledge presence.** AD-11 computes default NPC Knowledge from confirmed Mentions. Through Leak 1, a Shorthand-only Mention puts the entry into the NPC's knowledge. A Player's NPC Conversation then answers fluently about the bell-tower night, which reveals the NPC was secretly present. That is EV-3-shaped, but EV-4's canary check only covers *content* in context. The Narrative here is Party, so no canary fires.

**Proposed rule (new AD-12a):**
> **AD-12a Visibility classes.** Every table in `VISIBILITY_REGISTRY` declares one class:
> `stored`: has its own `visibility` column (journal_entries, entities, entity_aliases, entity_relationships, quest_steps, canon_notes, maps, map_pins, recaps, live_*, chat_sessions, stored_files).
> `derived`: has no column. It declares `derive_from=[...]` in the registry, and its effective visibility is computed by one function.
> `always_gm`: change_proposals, proposal_batches, continuity_flags, npc_knowledge, entity_changes rows whose `field` ∈ GM_FIELDS.
> **Mention formula (binding):** `eff(mention) = most_restrictive(entry.visibility, entity.visibility, field_vis(source_field), mention.visibility_floor)`, where `field_vis(shorthand|gm_notes) = gm`, `field_vis(narrative) = party`, and `visibility_floor` is a nullable stored column set **only** by merge to `most_restrictive(absorbed_entity.visibility)`. Merge sets the same floor on moved relationships and aliases. `entity_mentions` stores `source_field`.
> **Parity:** `access` exposes `visible_clause(Model, ctx) -> ColumnElement` and `effective_visibility(obj)`, both generated from the same registry definition. A property test asserts they agree on a randomized fixture. No service builds a visibility predicate in SQL by hand (this closes the E9 aggregation path).
> **NPC Knowledge default for a non-GM ctx** = entries with a confirmed Mention whose `eff(mention)` is visible to that ctx.

### C3. The visibility lattice cannot express PRD audiences: shared Player Journals reach anonymous links, and "private to whom" is undefined

**Construction.**
- AD-12: `visibility ∈ {party, gm, private}`, and `journal_entries.kind ∈ {gm, player}` with "anonymous Share Links never see `player`".
- FR-42: a Player "shares" their entry with Members, but never with read-only Share Links.
- E7 obeys AD-12 and implements "share" as `visibility = party` on a `kind=player` row. Access filters `kind=player` for anon on *journal_entries*.
- E9, E3 and E8 derive content (Mention counts, Relationships approved from a promoted Player entry, a Player-edition chapter) using `most_restrictive(...)`. The result is the value `party`. The `kind=player` fact is lost in the derivation, because `most_restrictive` returns an enum value, not an audience. **Anonymous Share Links see derived content from shared Player Journals.**

**"Private to whom".** A Chronicle that a Player builds "as that Player" (AD-13) includes their own Private entries. AD-14 sets file visibility = `most_restrictive(sources)` = `private`. AD-12 defines `private` as "author and GMs", and the registry's "author column" for `stored_files` is `created_by`. That works by luck. For a Mention in Player A's Private entry, the author column of the Mention is undefined: is it the approver (GM), the entity's creator, or the entry's author? E7 picks `entry.user_id`, while E6 (NPC Knowledge) uses `actor_user_id`. Player B then gets A's private content in B's NPC Conversation.

**Proposed rule (amends AD-12 and AD-13):**
> **AD-12b Audience lattice.** `access` computes visibility as an **audience**, never as a bare enum: `Audience = Public | Members | Owner(user_id) | GM`, ordered Public > Members > Owner(u) > GM (narrower to the right; `Owner(a) ⊓ Owner(b) = GM` for a≠b). Stored enum mapping: `party` on a `kind=gm` row → Public; `party` on a `kind=player` row → Members; `private` → Owner(row.author_user_id per registry); `gm` → GM. `most_restrictive` operates on Audiences. Derived records, files (`stored_files.audience_owner_id`) and caches store or compute an Audience. `visible_to(ctx, audience)` is the only check. EV-4 adds an "anon vs shared-Player-Journal-derived" probe and a "Player B vs Player A private-derived" probe.

### C4. No single visibility-mutation path, and untyped `source_refs`: derived content outlives a downgrade

**Construction.**
- AD-10 sends writes to `entities`, aliases, relationships and quest steps through `apply_change`. AD-17 sends journal writes through `journal_service`. Maps and pins (E10), recaps (E5), canon notes (E2) and chat sessions (E6) are written by their owning services.
- E7 owns "bulk visibility controls". It obeys AD-13 because it does not *compare* visibility values; it just writes them. For entities it calls `apply_change`. For maps it calls `map_service`. For recaps it updates `recaps.visibility` directly in its own route, since no AD forbids that.
- `access.on_visibility_change(db, ref)` "marks derived content stale", and the `visibility_changed` hook exists. Neither is *required* on any write path. `map_service.update_map` and E7's recap update never call it.
- Separately, AD-14 gives `stored_files.source_refs` as "JSONB" with no shape. E5 writes `{"journal_ids":[...]}`, E8 writes `[{"type":"entry","id":...}]` and E10 writes `{"map_id":...}`. Even when `on_visibility_change(ref=journal X)` *is* called, it cannot find E8's files without knowing E8's shape.

**Result.** A GM flips entry X to GM-only. The Chronicle Player edition, the recap audio (FR-32 says "changing the Visibility of any source entry invalidates the cache") and the recap text all stay served. EV-4 does not catch this unless a probe performs a *mutation sequence*, and none is required.

**Same class, chat history.** Chronicler and NPC chat messages are stored with their `sources` (titles and quotes), and in-session history is replayed into the next prompt. After the downgrade, `GET /chat/sessions/{id}` returns the old assistant text and the stored source titles and quotes, and the next turn replays them into the Player's prompt. FR-9's archive rule covers only Co-GM→Player demotion, not content downgrade. The same applies to FR-36 "grant/hide applies from the next reply": the previous turns still carry the hidden fact.

**Proposed rules:**
> **AD-12c One visibility setter.** `access.set_visibility(db, ctx, ref, value, *, field=None)` is the only code that writes any `visibility`, `field_visibility` or `visibility_floor` column. It delegates the row write to the owning service's registered setter (`apply_change` for Canon tables, `journal_service.update_entry` for entries). In the same transaction it calls `on_visibility_change` and enqueues the `visibility_changed` hook. `check_scoped_queries.py` is extended to fail on any `UPDATE`/assignment to a registered visibility column outside `access.py`.
> **AD-14a Typed provenance.** Derived records do not store `source_refs` JSONB. They store rows in `derived_sources(derived_type, derived_id, ref_type, ref_id, ref_field NULL)`, where `ref_type` is the closed `SourceKind` enum (see H9), with an index on `(ref_type, ref_id)`. `on_visibility_change` and `entry_deleted` resolve dependents only through this table. Every derived table (stored_files, recaps, chronicle runs, chat_messages, live recaps, stats snapshots if any) registers in `DERIVED_REGISTRY`.
> **AD-13a Stored AI output is re-projected on read and on replay.** Persisted assistant messages store `source_refs` only (no titles or quotes). On read, titles and quotes are resolved through `access.project`. For a non-GM ctx, a message whose refs include a ref no longer visible is replaced by a fixed redaction string, and it is **excluded from prompt replay**. NPC Conversation replay is filtered the same way against the *current* NPC Knowledge.
> **EV-4 downgrade suite (binding):** for every DERIVED_REGISTRY type, create it while its source is Party, downgrade the source, then assert 404 or redaction on every read route and the absence of the content from every captured LLM context.

### C5. Ollama is the contended resource, and nothing schedules it (in-request streams, `num_ctx` reload thrash, per-user models)

**Construction (all compliant).**
- AD-3: "NPC replies, quick lookup and the Chronicler stream inside the request. They are not Jobs." AD-7: Ollama `NUM_PARALLEL=1`, `MAX_LOADED_MODELS=1`.
- E1's extraction prompt (Entity list + 500-word entry + schema) exceeds 4096 tokens. E1 obeys AD-8, since `complete_structured` takes `messages, schema, config, task, timeout` and nothing forbids options, so it passes `options.num_ctx=8192` to avoid Ollama's silent front-truncation. E6 keeps the 4096 default. In Ollama, a request with a different `num_ctx` **reloads the model** (tens of seconds on CPU) and raises the KV-cache footprint. Alternating requests thrash: each NPC first token pays a reload, and NFR-6's 20 s target is gone.
- AD-8: "In the baseline every task resolves to the *user's* configured model". The Owner configured `llama3.1:8b`, a Co-GM `qwen2.5:7b`, and a Player has none (default). AD-2 resolves LLMConfig per Job owner. With `MAX_LOADED_MODELS=1`, every switch is a full 7B swap. The memory stays bounded, but the latency is unbounded.
- RQ priority orders *Jobs only*. With 1 worker, a Rolling Recap (interactive Job) waits behind a running `onsave` extraction (no preemption, up to "≤3 min"). The 60 s cadence and ≤45 s update (NFR-6) fail during the very Live Session that the AD-7 admission rule is meant to protect, because the admission rule stops *new* onsave Jobs and not the running one.
- During a Live Session, the GM's free-text quick lookup (Chronicler, in-request) and the Rolling Recap Job both queue in Ollama. A Player on their phone using the Chronicler in another Campaign does too. Nothing orders them.

**Proposed rules:**
> **AD-7a LLM admission.** All local-LLM calls, Job or request, acquire a slot from `core/llm_gate.py` (a Redis-backed priority semaphore, capacity = `OLLAMA_NUM_PARALLEL`) with a class: `live_recap` > `gm_interactive` (quick lookup, GM NPC/Chronicler) > `player_interactive` > `job_onsave` > `job_backfill`. Request-path callers wait at most `LLM_GATE_WAIT_S` (default 10) and then return 503 `{code:"llm_busy", retry_after}`. Jobs wait indefinitely. While a Live Session holds admission (AD-7b), `job_*` classes cannot acquire. A running Job's handler acquires per LLM call, not per Job, so a recap can slip in between extraction calls. To keep that possible, handlers must split work into calls of ≤ `LLM_CALL_BUDGET_S`.
> **AD-8a Fixed local model and context.** For the local provider, `model_for()` returns the deployment's `LOCAL_LLM_MODEL` for every user and task. Per-user model choice applies only to BYOK hosted providers. `num_ctx` is a deployment constant (`OLLAMA_CONTEXT_LENGTH` / Modelfile), and `llm_provider` strips `num_ctx`, `num_gpu` and `keep_alive` from per-call options. Every prompt builder calls `prompt_budget.fit(task, parts)` against that constant with an explicit truncation policy per task. A request that would exceed it raises; it never relies on server-side truncation.

---

## HIGH

### H1. Job idempotency silently drops edits, and enqueue/commit ordering loses Jobs

**Construction.** E1 obeys AD-4 with `idempotency_key = "extraction.run:{journal_id}"`. The GM saves, extraction starts (`running`) on the old text, and the GM edits a typo. The `entry_updated` handler enqueues again, but the partial unique index returns the **existing running Job**. That Job writes proposals for the old text. AD-17 superseded the pending proposals *before* this batch landed, so the stale batch is the only pending one. At approval, AD-10's stale check compares Canon `old_value`, not entry text, so it passes. Proposals quoting deleted text get approved.

Other cases:
- `enqueue(db, ...)` pushes to RQ inside the caller's transaction. The worker can dequeue `job_id` before commit and find no row, and AD-4 has no rule for "row missing".
- A row committed with the RQ push lost (Redis noeviction OOM, flush, crash between commit and push) stays `queued` forever. AD-4 only recovers `running` rows, and only at boot.

**Proposed rule (amends AD-4):**
> Idempotency keys for content-derived Jobs include the content version (`extraction.run:{journal_id}:{entry_hash}`). `proposal_batches` and `continuity_flags` store `entry_hash`. A batch whose `entry_hash` ≠ the current one is inserted as `superseded`, and approval marks a proposal `stale` if its batch's `entry_hash` ≠ current. `enqueue` inserts the row and registers an `after_commit` push (an outbox). A reaper runs every 30 s in each worker main loop. It re-pushes `queued` rows older than 60 s that are absent from RQ, and handles stale `running` rows (see H2). The boot-only rule is dropped.

### H2. RQ mechanics contradict AD-4: default timeout, work-horse death, double execution in the full profile, double retry

**Construction.**
- RQ's default `job_timeout` is 180 s. An E8 Chronicle export (≤3 min target) or a CPU extraction call hits it, and RQ kills the horse (`JobTimeoutException`). The PG row stays `running`.
- An OOM-kill of the forked work horse (worker limit 512 m, WeasyPrint or pyvips) kills only the horse. The parent worker does not reboot, so AD-4's "when a worker boots" recovery never runs, and the row is `running` forever.
- In the full profile, worker 2 restarts while worker 1 is in a synchronous WeasyPrint render. A blocked event loop means no heartbeat for more than 60 s, so worker 2's boot rule requeues a **live** Job and it runs twice (two Chronicle files, two proposal batches; the fingerprint saves proposals but not files).
- If any epic uses RQ's `Retry(max=2)` (idiomatic RQ) alongside AD-4's `max_attempts`, Jobs retry up to 9 times.

**Proposed rule (amends AD-2 and AD-4):**
> The RQ wrapper (owned by E0-Jobs) enqueues with `job_timeout = registry[kind].timeout_s` (required; no default), `retry=None` and `failure_ttl` short. RQ `on_failure`/`on_stopped` callbacks transition the PG row. Heartbeats come from a **thread** started by the wrapper, not from the handler's event loop. A stale-`running` row is requeued only if `jobs.worker_id` is absent from RQ's `Worker.all()` registry. Synchronous CPU work in a handler (WeasyPrint, pyvips) runs in `asyncio.to_thread`. The SQLAlchemy engine is disposed and recreated in the work horse after fork.

### H3. The admission rule is global across Campaigns, "active" is undefined, and the obvious RQ implementation deadlocks itself

**Construction.**
- AD-7: "while a Live Session is active in **any** Campaign, workers consume only `interactive`." GM-B starts a Live Session in Campaign B and pauses it, or leaves the tab open; `proxy_read_timeout 4h`. Campaign A's on-save extraction sits queued for hours. NFR-6 (≤3 min) fails for A, and NFR-11's "never delayed by more than one Job" spirit is broken by a rule the PRD never asked for.
- "Paused" and "active" are undefined (FR-26 has pause).
- E4 owns `live_sessions` (Phase 2). E0-Jobs (Phase 0) must implement the gate, so it either cannot or must read a table that doesn't exist yet.
- RQ workers have a fixed queue list. RQ's built-in lever is `rq suspend`, which suspends the **whole** worker. An E4 developer who obeys AD-7 with `suspend` also stops the `interactive` queue, which includes E4's own Rolling Recap.
- AD-7 holds back "narration Jobs" by name, but nothing assigns `recap.narrate` a queue. E5 picks `interactive` because the GM is waiting, so narration (TTS 512 m) runs during a Live Session alongside STT and the 7B, which breaks the 7.2 GB case.

**Proposed rule (replaces the AD-7 admission paragraph):**
> **AD-7b Resource leases.** E0-Jobs owns `jobs/admission.py` with `hold(reason, campaign_id, ttl_s)` / `renew` / `release`, stored as Redis keys with a TTL. E4 holds `live` with `ttl=90 s`, renewed by the drainer on each received frame or ack. Pause stops renewal, so the lease expires, so other work resumes. The worker is a `LorekeeperWorker` subclass that, before each dequeue, computes its queue list from current leases. `rq suspend` is forbidden. **Each `kind` declares `queue` and `resources ⊆ {llm, nli, ocr, tts, stt, cpu_heavy}` in `jobs/registry.py`; `enqueue` has no `queue` parameter.** On baseline, an active `live` lease blocks any Job whose resources intersect `{llm, tts, nli, cpu_heavy}`, except kinds flagged `live_safe` (only `live.recap`). The lease applies **per host**, as now, but a Live Session with no frames for 15 min is auto-paused by E4. Narration is `onsave`.

### H4. Live drainer duplication across gunicorn workers, and the Rolling Recap race

**Construction.** AD-15 puts "a per-session drainer in the web process". Baseline has `-w 2`. The WS lands on gunicorn worker 1. The phone drops Wi-Fi, reconnects and lands on worker 2, which starts its own drainer because AD-15 says the socket owner drains. Worker 1's drainer is still popping from `live:{id}:pending`, so two drainers each post to `stt`, doubling CPU at the moment lag matters. Each enqueues "at most every 60 s" (per process), so two `live.recap` Jobs run. Each is "previous recap + new text in", so the second overwrites the first's output and drops content. FR-27 ("fact stated in minute 5 is still in the final Rolling Recap") fails. Recap results "arrive on the socket through pub/sub" on an unnamed channel, so E4 may subscribe to `jobs:{campaign_id}` and put recap text in the job event. That contradicts AD-5 ("results fetched from the owning domain route, never from the job row").

Redis is `maxmemory 96mb, noeviction`. A 10-minute PCM16 16 kHz backlog is about 19 MB per session, so four backlogged sessions plus RQ fill Redis. After that **every** `enqueue` fails, including journal-save extraction.

**Proposed rule (amends AD-15):**
> The drainer for session S runs only in the process holding Redis lock `live:{id}:drainer` (SET NX, 15 s TTL, renewed). Other processes forward acks and captions via pub/sub channel `live:{id}:out`. `live.recap` uses `idempotency_key = live.recap:{id}` and a stored watermark `through_seq`. The handler reads the latest recap row `FOR UPDATE` and processes segments `> through_seq`. Pending audio is stored in `live_chunks` on disk (`files_data`), and Redis holds only chunk ids. Backlog memory in Redis is ≤ 1 MB per session.

### H5. Absence of a field is itself the secret

**Construction.** AD-13: "Party response schemas omit GM fields entirely; they are never blanked." E0-WorldCore obeys. Mira's `status` is GM-only (she's secretly dead), so `EntityPartyResponse` for Mira has no `status` key, while every other Character has one. The graph convention requires `status` on every node, so E3 either omits the node (breaking FR-24), sends `null`, or sends the real value. Each epic picks one. If `field_visibility` itself is in any party response, or a frontend type guard is derived from it, the leak is explicit. EV-4 checks canaries and "hidden vs nonexistent *records*", not hidden vs unset *fields*.

**Proposed rule (amends AD-13):**
> For a non-GM ctx, a hidden field is rendered exactly as that field is rendered when unset: a registry-declared `unset` value per field (`status → "unknown"`, `description → absent`, list fields → `[]`). The registry declares the default for every Entity Type. An entity with a genuinely unset field must produce byte-identical JSON. `field_visibility` never appears in a Party schema. EV-4 adds a "hidden field vs unset field" equality probe.

### H6. Name and text oracles through 409s, global `entry_hash`, and global tags

**Construction.**
- Brownfield: `journal_entries.entry_hash` is **globally unique** and returns 409 on duplicates, with a Redis `dedup:{hash}` 24 h key. The spine's Errors convention keeps "409 duplicate". A Player saving a Player Journal entry (E7) whose text hashes to an existing GM-only entry gets 409, which confirms a guessed GM text. Because the index is global, this works **across Campaigns and tenants**.
- If E0-WorldCore enforces `UNIQUE(campaign_id, normalized_name)` on `entities` or on aliases, then a Player renaming their own PC Character Sheet (allowed by FR-7) to a hidden NPC's name gets 409, revealing the name exists.
- Brownfield tags are **global**, `UNIQUE(name, tag_type)`, extracted by NER on every save (Shorthand included, today). `GET /api/tags/` returns counts. The spine never mentions tags. FR-4 says existing tags "keep working unchanged", and FR-49 uses tags for "most-mentioned" before F1. A Shorthand-only name becomes a tag visible with counts to Players and to other Campaigns.

**Proposed rule (new AD-13b):**
> Uniqueness and duplicate checks on any route reachable by a non-GM ctx are evaluated only over rows `visible_to(ctx)` *and authored by ctx.user*. Otherwise they are deferred to GM review. `entry_hash` uniqueness becomes `(campaign_id, user_id, entry_hash)`, and the Redis dedup key includes both. Tag extraction runs on the Narrative only. Tag reads for a non-GM ctx are counted through `visible_clause(JournalTag, ctx)`. The global `GET /api/tags/` counts are scoped by `role_map` (see M5). Entity name uniqueness, if any, is GM-scoped and never enforced against Player writes.

### H7. Proposals: a registry entry that makes them visible; override offers swallowed by the fingerprint; FR-22 marks with no owner

**Construction.**
- AD-11 says proposals are "always GM-only, whatever their columns say", but proposals have `chosen_visibility`, and AD-13's registry maps "each model to its ... visibility columns". E1 registers `ChangeProposal.visibility_col = chosen_visibility`, and the GET routes are protected by `require_campaign("gm")`. That is fine until the Player Portal (E7) or stats (E9) touches proposals through `scoped_select`. For example, "pending reviews" counts on the home page would include party-chosen proposals.
- E2 (FR-21) offers "Mira: deceased → alive" as a Change Proposal for journal J. Earlier, extraction on J proposed `set_status alive` and the GM **rejected** it as a false positive. The fingerprint `sha256(op|target|field|new_value)` is identical, and `UNIQUE(journal_id, fingerprint)` makes "a re-run insert nothing", so the override offer silently never appears.
- FR-22 "contradicting proposals are marked" needs either a column on E1's `change_proposals` or a `proposal_id` FK on E2's `continuity_flags`. Each epic owns only its own table, so both epics compliantly do neither, or both do it.
- `entry_saved` fires E1 and E2 handlers independently. On the full profile, continuity runs before extraction finishes, so there is nothing to mark.

**Proposed rule (amends AD-11):**
> The registry supports `always_gm=True` (proposals, batches, flags, npc_knowledge), and `scoped_select` returns nothing for non-GM ctx on those models. `fingerprint` includes `origin ∈ {extraction, override, promotion}`. Override offers are not proposals: the Canon Note form calls `apply_change(... canon_note_id=...)` directly on GM confirmation. `continuity_flags` carries nullable `proposal_id` (E2 owns it), and E1's renderer reads flags by `proposal_id`. `continuity.check` is enqueued by E1's handler with `depends_on = extraction job` (RQ `depends_on` plus the PG row's `depends_on_job_id`), so that flags against proposals see the batch.

### H8. Deleting an entry vs AD-10's GM-only Canon path; history FKs

**Construction.** FR-6: deleting an entry removes its Mentions and NPC Knowledge links, and FR-42 lets a Player delete their own Player Journal entry, which may have *confirmed* Mentions after GM promotion. AD-10 says confirmed Mentions are written only via `apply_change`, and "Only GM contexts may call it". E0-Journal therefore can either (a) call `apply_change` with the Player ctx, which raises; (b) use `ON DELETE CASCADE` on `entity_mentions.journal_id`, which bypasses `apply_change`, writes no `entity_changes` row and fires no `canon_changed`; or (c) block the delete, which violates FR-42. Each epic picks one. Separately, `entity_changes.source_journal_id` has no stated FK action. E0-WorldCore picks `CASCADE` (history destroyed) and E1 expects `SET NULL` + "source deleted" (FR-6).

**Proposed rule (amends AD-10):**
> `apply_change` accepts a **system ctx** `ctx.as_system(reason)` constructible only inside `journal_service.delete_entry` and `world_service.merge`. `delete_entry` removes Mentions via `apply_change(op=remove_mention, reason=source_deleted)`. All FKs from Canon and history tables to `journal_entries` are `ON DELETE SET NULL`, with `source_deleted_at` set by the delete path. A migration test asserts the FK actions.

### H9. Citation and source shapes diverge (the convention says "JournalSource-like ... extended")

**Construction.**
- E2 cites `{canon_ref_type: "entry", ...}` (AD-11 `conflict_key` uses `canon_ref_type`), while the Citations convention says `kind: journal`.
- E4's Rolling Recap must cite the transcript (EV-6 "supported by the transcript"), and there is no `kind` for it, so E4 adds `transcript` while E5 adds `live_segment`.
- `entity_field` needs a field name, and the shape `{kind,id,title,quote}` has none. E6 puts `"entity:field"` into `id`, while E3 adds `field`.
- E5 stores recap citations with titles and quotes at generation time (the entry title is GM-visible text). After the entry is retitled or hidden, the stored title leaks (see C4).
- `app/schemas/chat.py` is "extended" by E4, E5 and E6, and it is not listed as a shared append point.

**Proposed rule (replaces the Citations row):**
> One `SourceRef {kind: SourceKind, id: UUID, field: str|None, span: [start,end]|None}` in `app/schemas/sources.py` (owned by E0-Access, append-only enum). `SourceKind = journal | player_journal | canon_note | entity_field | live_segment | recap`. Responses carry `ResolvedSource {ref, title, quote}` built only by `access.resolve_sources(refs, ctx)`, which drops refs not visible to ctx and never stores titles or quotes. Continuity `canon_ref_type` uses `SourceKind`.

### H10. Synthetic audiences ("view as Player", GM-built Player edition) have no constructor

**Construction.** FR-45: a GM can export the Player edition. AD-13: "Jobs carry the ctx of whoever started them. A Player-edition export runs as that Player." When a GM starts it, the Job ctx is **GM**, so every `scoped_select` returns everything. E8 must downgrade, and AD-13 forbids comparing visibility outside `access`. E8 either filters `visibility == party` in `chronicle_service` (a forbidden but tempting path), or uses the GM ctx (a GM-only leak into a Party-visibility file). E7's "view as Player" preview (FR-41) has the same need and builds a second, different downgrade. Also, a Player-built Player edition includes *that Player's* Private entries, so editions differ by builder, and the file's audience is Owner(builder) (via C3) rather than Members.

**Proposed rule (amends AD-13):**
> `access.audience_ctx(campaign_id, audience)` with `audience ∈ {anon, member, as_user(user_id)}` is the only way to build a reduced ctx, and only from a GM ctx or the user themself. The Chronicle Player edition always builds with `audience_ctx(member)` (Party + shared Player Journals when opted in), whoever starts it. "View as Player" uses `as_user(player_id)`. Job rows store `ctx_kind`, `ctx_user_id` and `ctx_audience`, and handlers rebuild the ctx at run time from current membership. If the starter's role dropped since enqueue (`role_version` changed downward), the Job fails with `error_code=permission_changed`.

### H11. Event streams beyond Jobs: each epic invents a channel

**Construction.** FR-24 says "An approved Relationship appears without a manual refresh". Approval is a synchronous GM route, not a Job, so `useJobStream` never fires. E3 therefore adds `GET /api/graph/stream` on `canon:{campaign_id}`, E1 adds a pending-reviews SSE on `proposals:{campaign_id}`, and E4 publishes recaps on whatever it likes. AD-5's per-requester filter is specific to `jobs:*`. E3's channel pushes `{entity_id, op}` for **every** Canon change, including GM-only Entities, to Players. That reveals the existence of hidden Entities and GM activity timing.

**Proposed rule (new AD-5a):**
> `core/pubsub.py` is the only publisher. Its channel registry has exactly three channel kinds: `jobs:{campaign_id}` (AD-5), `campaign:{campaign_id}:events` and `live:{live_session_id}:out`. Campaign events carry only invalidation keys `{domain, id}`. They are delivered through one SSE route `GET /api/campaigns/{id}/events`, which forwards an event to a ctx only if `visible_to(ctx, ref)` holds *after* the change. Downgrades and deletes are sent to non-GMs as an unkeyed `{domain}` invalidation, batched to at most one per 30 s per domain, so the timing carries no information. The frontend `lib/sse.ts` exposes one `useCampaignEvents`.

### H12. Stale stream authority: a 15 s window, anon tokens, and expiry

**Construction.** AD-13 says streams re-check `role_version` every ≤15 s. A Co-GM is demoted mid-stream, and the NPC stream already holds a GM-built prompt (GM knowledge, voice notes), so up to 15 s more of GM-grounded tokens are generated. `role_version` lives on `campaign_members`, so for an anon Share Link ctx there is nothing to re-check: revoking the token or reaching `expires_at` (AD-12) never closes anon SSE. A removed Member has no row, and an implementation that does `SELECT role_version` and gets `None` may treat "unchanged" as `None == None`.

**Proposed rule (amends AD-13):**
> Every grant (member row, share token, owner) has an `access_epoch`. `role_changed`, member removal, token revocation and expiry publish `access:{campaign_id}:{grant_id}`, and stream generators close on receipt. The ≤15 s poll remains as a fallback. A missing grant counts as changed. LLM streaming generators check the epoch between chunks and abort the upstream request.

### H13. Hooks fire inside transactions and with an unspecified ctx (E9 awards achievements with the GM's ctx)

**Construction.** AD-10 says `apply_change` "writes ... and then fires `canon_changed`" *in the same transaction*. AD-17 says hooks fire "after commit". Merge and revert are compositions of `apply_change`, so `canon_changed` fires N times mid-transaction, and E3 or E9 handlers act on changes that then roll back. Hook handlers receive no specified ctx. E9's `stats_hooks` on `canon_changed` computes "100 Entities in the world" using the **actor's (GM) ctx** and awards it to every Member. A Player with 60 visible Entities gets the 100-Entities Milestone, which leaks the count (FR-50 forbids this). E9 also "owns" `entities.attributes.completed_at`, which is a Canon table column written outside `apply_change` (AD-10), inside E0-WorldCore's typed-attribute registry. The quest completion rate needs to know which statuses count as completed or closed, and the registry lists values without categories. E9 hard-codes `{"completed","failed"}` while the registry says `done`/`abandoned`.

**Proposed rule (amends AD-17 and AD-9):**
> Hooks are collected in `session.info` and dispatched by an SQLAlchemy `after_commit` listener, and discarded on rollback. Every event carries `{campaign_id, refs, actor_ctx}`. A handler that computes anything **per user** builds `access.ctx_for(user_id, campaign_id)` for each recipient. `entity_types.py` declares a `category ∈ {open, closed_success, closed_failure, closed_other}` for each status. `apply_change` itself stamps `attributes.completed_at` when a Quest enters `closed_success`. E9 only reads it.

### H14. Memory: limits sum above the bound; the ml container is undersized for OCR; worker 512 m for WeasyPrint

**Construction.** Baseline limits: ollama 5 g + postgres 0.5 + redis 0.125 + web 0.5 + worker 0.5 + ml 1 + stt 1 + tts 0.5 + nginx 0.064 = **9.2 GB of limits against a 7.5 GB bound**. Compliance therefore rests entirely on admission (H3) and on lazy loading, yet several paths bypass admission:
- `/api/ingest/voice` (in-request, `stt`);
- OCR on source upload (in-request, `ml`). Brownfield OCR is EasyOCR, which is torch-based. Inside a 1 g `ml` that already holds MiniLM and spaCy, plus lazy NLI, it OOMs. The AD-6 LRU budget unloads models, not in-flight requests.
- WeasyPrint rendering 100 entries with embedded fonts and Map images inside a 512 m worker. That case is not in SPIKE-5's list; R-10 only lists Map tiling.

**Proposed rule (amends AD-7):**
> The binding check is "sum of limits of the containers that can be simultaneously *hot* under the admission state ≤ 7.5 GB". It is computed in CI from `profiles/baseline.env` and the registry's `resources` per kind. `ml` serves at most one lazy model at a time and returns 503 (`ModelServiceUnavailable`, retried) when admission would exceed `ML_RESIDENT_BUDGET_MB`. OCR moves to an ONNX engine, or to a Job with `resources={ocr}`. In-request `stt` for single recordings becomes the Job `stt.transcribe` (`resources={stt}`, `live_safe=false`). SPIKE-5 adds "Chronicle export of 100 entries with 3 Maps" to its matrix.

---

## MEDIUM

### M1. Two owners of one file: append-point drift
`api/routes/entities.py` is owned by E0-WorldCore, and E3 also owns "relationship-type CRUD in entities.py". Similar overlaps: `journals.py` (E0-Journal and E7), `campaigns.py` (E7 role management and E0-Access `SharingPage` roles), `export_service` (E0-Access "export scope" and E8 "extends"), `chat.py`/`chat_service` (E0-Access refactor and E6 NPC mode), `AnalyticsPage.tsx` (E0-Access analytics scope and E9), `jobs/errors.py`, `schemas/chat.py` and `VISIBILITY_REGISTRY`. None of these are on the shared-append-points list.
**Fix:** each overlapping file is split along the overlap (`routes/relationship_types.py`, `routes/player_journals.py`, `routes/members.py`), or added to the shared-append-points list with an explicit "register, don't restructure" contract. CI fails if an epic PR modifies a file owned by another epic outside the append points (CODEOWNERS-style map generated from the boundary table).

### M2. `chat_sessions.archived_at` is owned by a Phase-2 epic but needed in Phase 0
FR-9 (the last bullet, in the same release as FR-7, Phase 0) requires archiving chat sessions on Co-GM→Player demotion. The boundary map gives `chat_sessions.archived_at` to **E6** (Phase 2). E0-Access cannot add it without duplicating E6's column. If it waits, FR-9 ships without the archive, and a demoted Co-GM's existing Chronicler sessions replay GM-retrieved history into Player prompts.
**Fix:** move `chat_sessions.archived_at` and `npc_entity_id` into `F1-core` (C1), owned by E0-Access. E0-Access registers the `role_changed` archive handler for all chat sessions. E6 adds only `npc_knowledge`.

### M3. Relationship types and aliases leak through lists and matching
`relationship_types` has no visibility (AD-19 lists it, but AD-12 doesn't cover it). FR-24's "filter by Relationship type" dropdown lists "secretly loyal to" and "betrayed" to Players. Aliases have a `visibility` column but no default: E1 sets it from `chosen_visibility`, while merge sets most-restrictive. A Party alias "the Traitor" on Party Aldric is created when the GM picks "same as Aldric" on a Shorthand-sourced surface form. Also, `normalize_name()` matching for Player search, Player chat "entry-for-Entity matching" (FR-9b) and transcript tap targets runs over all aliases.
**Fix:** for a non-GM ctx, relationship types are listed only if used by at least one visible edge. The alias default is `eff` of its evidence (`source_field` per C2). `world_service.match_names(ctx, text)` is the only matcher, and it uses only aliases visible to ctx.

### M4. A Pin label names a hidden Location
FR-8: a Party record pointing at a GM-only record is served "with that reference removed". A Party Pin labelled "Thieves' Guild hideout" linked to a GM-only Location keeps its label, so the Map shows the secret. This is compliant with AD-13's `project()`.
**Fix:** `map_pins` is `stored` with `visibility_default = location.visibility` at creation. When the linked Location is less visible than the Pin, `set_visibility` warns the GM (as for merge). A Pin whose linked Location is hidden from ctx is hidden unless `pin.visibility_override=true` was set explicitly by a GM.

### M5. Cross-Campaign reads have no shared helper
FR-8 says to apply the requester's role in each record's Campaign. `scoped_select(Model, ctx)` takes a single-Campaign ctx. E7's "my campaigns" feed loops over ctxs, while the existing global search and tags (see H6) use `role_map` with an `IN (...)` visibility filter that re-implements the `kind=player`/anon and Private-author rules.
**Fix:** `access.scoped_select_multi(Model, role_map)` is the only cross-Campaign query builder, generated from the same registry definitions as `visible_clause`.

### M6. The ANN index (deferred) turns result counts into an oracle
AD-13 sends non-GM retrieval to `party_embedding`. When the deferred HNSW index is added, pgvector applies `WHERE visibility/kind/campaign` *after* the index scan (`ef_search` 40). A Player's top-k shrinks when GM-only entries crowd the query's neighbourhood, which reveals GM-only density near a probe phrase. That is exactly EV-4's "ranking" class, and it appears only at scale.
**Fix:** add to Deferred → "when an ANN index is added": `hnsw.iterative_scan = relaxed_order` (pgvector ≥0.8) is mandatory for every filtered query, or use partial indexes per audience. EV-4 adds a "GM-only near-duplicates do not change the Player's k" probe.

### M7. Audio cache key: column conflation, cross-Campaign scope, visibility
AD-16 says "cached by `sha256(text|preset)` in `stored_files`", and `stored_files` already has `sha256` (the byte hash per AD-14). E5 puts the cache key in `sha256`, while E8 and E10 put byte hashes there. The lookup is not Campaign-scoped, so identical text in Campaign B hits Campaign A's file. Whether that yields a 404 or a copy, it also tells GM-B (perhaps a Player in A) whether that exact text was narrated elsewhere: a cache hit returns `done` immediately instead of queued. The key omits audience, so a GM-only and a Party recap with the same text share one file and one visibility. After invalidation, regenerating under the same key collides with the stale row.
**Fix:** `stored_files.cache_key` is a separate column, `UNIQUE(campaign_id, kind, cache_key) WHERE NOT stale`, with `cache_key = sha256(campaign_id|kind|preset|text|audience_fingerprint)`. Narration always goes through the Job lifecycle, so timing is the same whether or not the cache hits.

### M8. `party_embedding` backfill vs AD-17's sole write path
AD-18 runs the `party_embedding` backfill as a `backfill` Job. AD-17 makes `save_entry`/`update_entry`/`delete_entry` the only journal write paths. The backfill author either calls `update_entry`, which fires `entry_updated`, so every historical entry re-runs extraction and continuity and floods the Review Checklist and the queue, or writes columns directly, which violates AD-17. `journal.reembed` (AD-17) has the same problem.
**Fix:** `journal_service.reindex_entry(db, id)` is the only index-only write path. It recomputes tsv, embedding and party columns, fires **no** hooks, and is used by `journal.reembed` and every index backfill.

### M9. `create_entity` proposals carry one visibility for many fields
AD-11 gives each proposal one `default_visibility`/`chosen_visibility`. A `create_entity` payload holds name (from the Narrative), description (from Shorthand) and status (from GM notes). "Approve all" never changes visibility, so all fields go to Party, including the Shorthand-derived description.
**Fix:** per-op payload models for `create_entity` and `update_field` carry `field_visibility: {field: visibility}` derived from per-field `source_field`. `chosen_visibility` sets the record-level value only. Proposals from Private Player Journal entries default to `gm` (never `private`, since a Canon record can't be private to a Player).

### M10. Enum mechanism divergence
Only `visibility` and `campaign_role` are named PG enums. Job `status`, proposal `op` and `state`, Entity `type` and `kind`, Mention status and `activity_events.kind` are not specified. E1 makes `proposal_state` a PG enum, E2 adds a value through `autocommit_block` in its own revision (AD-19 allows this), and E0-Jobs uses `text` + CHECK. The result is mixed migration semantics, and an enum value added in a branch cannot be dropped on rollback.
**Fix:** only `visibility` and `campaign_role` are PG enums. Every other closed set is `text` with a CHECK generated from a Python `StrEnum` in `app/domain/enums.py` (append-only, owned by the table owner). A CI test asserts that the CHECK and the StrEnum match.

### M11. Job `result_ref` is withheld from the Player who owns the Job
AD-5 sends `result_ref` "to GMs only". FR-45 says a Player can export the Player edition, so the Player's own `chronicle.export` Job completes with no pointer to the file. E8 invents `GET /api/chronicle/exports?mine=1` or puts the file id in `stage`. E7 would do something else for Player-triggered work.
**Fix:** the registry declares `result_audience(kind)`. `result_ref` is sent to a ctx if `visible_to(ctx, result_record)`. Proposals and flags are `always_gm` and stay GM-only automatically.

### M12. Live Session "active" vs paused is a per-epic state machine
`live_sessions.status` has no defined values. E4 uses `{recording, paused, ended}`, while the admission check (whoever writes it) looks for `active`.
**Fix:** this is folded into AD-7b leases (H3), so admission never reads `live_sessions`. Define `live_sessions.state ∈ {recording, paused, ended}` in AD-15.

### M13. Browser and PWA caching of access-checked bytes
AD-14 serves through `X-Accel-Redirect`. nginx's default static handling adds `ETag`/`Last-Modified` and may add caching headers. To meet "<1 s per view", E10 sets `Cache-Control: public, max-age=…` on tiles. A Player's browser or the PWA service worker keeps tiles, audio and Chronicle files after a downgrade or demotion (FR-44, FR-41).
**Fix:** `/api/files/*` and tiles send `Cache-Control: private, no-cache` plus an `ETag` that includes `access_epoch` and file version. Revalidation goes through FastAPI. The service worker never caches `/api/`.

### M14. Player NPC enable flag has no home
FR-39 enables Player NPC Conversations per NPC. E6 owns only `npc_knowledge` and two `chat_sessions` columns. E6 either writes `entities.attributes.player_chat_enabled` directly (violating AD-10) or via `apply_change`, which pollutes Canon history with a setting.
**Fix:** `npc_settings(entity_id PK, player_chat_enabled, ...)`, owned by E6 and `always_gm` for writes.

---

## LOW

- **L1. Ollama prompt-prefix timing.** With `NUM_PARALLEL=1`, llama.cpp reuses the KV cache of the previous prompt's common prefix. A Player's request that shares a long prefix with the GM's last prompt gets a faster first token. **Fix:** prompt builders put the ctx-specific system block (role and audience marker) first, so non-GM and GM prompts never share a cached prefix.
- **L2. Queue position and ETA as an activity signal.** A Player's queued export shows `eta_seconds` inflated by the GM's Jobs, and it stalls during a Live Session lease. This reveals GM activity. **Fix:** for non-GM ctx, `eta_seconds` is computed only from the Player's own Job and `stage` is a fixed vocabulary.
- **L3. Anonymous Share Links spend the Owner's hosted quota.** If anon chat exists (FR-9b covers it), `get_user_llm_config` for anon resolves to the Owner's BYOK or hosted config, and `user_or_ip` keys on the IP. **Fix:** anon AI routes use only the local provider and get a dedicated per-token rate limit.
- **L4. Role vocabulary mismatch at the UI edge.** `campaign_role {co_gm, player}`, `CampaignContext.role {gm, player, anon}` and `require_campaign(min_role="player"|"gm")` coexist, while `GET /campaigns/{id}/me` has no response shape. **Fix:** `/me` returns `{role: gm|player|anon, is_owner, member_role: co_gm|player|null}`, defined in `schemas/access.py`.
- **L5. Merged-into-hidden disappearance.** A Party Entity absorbed into a GM-only survivor starts returning 404 to Players, which signals a merge. **Fix:** merge warns the GM, and the absorbed Party Entity's id keeps resolving to a Party tombstone (`name` only) when the survivor is hidden from ctx.
- **L6. Backfill cursor duplication.** A cursor Job that re-enqueues its successor and then fails (and is retried) forks two cursors. **Fix:** the cursor lives in `data_backfills.cursor`, and the idempotency key is `backfill:{name}:{campaign_id}`, so the re-enqueue happens in the same transaction as the cursor advance.
- **L7. E0a hotfix filters by hand.** `share.py` (Phase 0a) predates `access.py` and will compare fields itself. **Fix:** state that E0-Access replaces the E0a filtering with `project()` and deletes E0a's party schemas, so they don't fork from `<X>PartyResponse`.
- **L8. The EV-4 route enumeration does not cover WS message types or pub/sub payloads.** **Fix:** EV-4 also enumerates the `core/pubsub.py` channel registry and the WS server message types, and needs a probe per message type.

---

## Coverage of the requested attack list

| Requested vector | Finding |
| --- | --- |
| Clashing shared-data shapes | C2, H9, M7, M9 |
| Two owners of one entity/table/file | C1, M1, M2, M14, H13 (`completed_at`) |
| Conflicting state-mutation paths | C4 (visibility), H8 (delete vs apply_change), M8 (reindex), H7 (override) |
| Conflicting migration ordering | C1, M2, M10 |
| Divergent enum values | H13 (quest status categories), M10, M12, L4 |
| Differing citation/source shapes | H9, C4 (stored citations) |
| Two SSE/pub-sub conventions | H11, H4 |
| Differing derived-visibility computation | C2, C3, H13 (stats ctx) |
| Inference via counts and ranking | H13, M6, H6 (tags), H11 (event timing) |
| Embeddings | M6, C2 (NPC Knowledge) |
| Job events | M11, L2, H11 |
| 404 vs 200 shape | H5 (field absence), L5, H6 (409) |
| Relationship endpoints | M3 |
| Map tiles | M4, M13 |
| Audio cache keys | M7 |
| Chat history replay | C4 (AD-13a), M2 |
| NPC knowledge | C2 (Leak 3), C4 (replay after hide), M14 |
| Canon notes in retrieval | H9 (SourceKind), C3/C4 (re-projection); Canon Notes are `stored` and stay GM by default. No new hole beyond these. |
| Rolling Recap | H4 (race and channel), C5 (cadence under contention) |
| Interactive Jobs vs streamed requests on Ollama | C5 |
| Worker priority with RQ | H2, H3 |
| Live Session pause across Campaigns | H3, M12 |
