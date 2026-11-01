---
status: draft
stepsCompleted: [1, 2]
stepsPending: [3, 4]
workflow: bmad-create-epics-and-stories
mode: autonomous (owner pre-approved; step menus decided by agent, see Decisions)
created: 2026-10-31
updated: 2026-10-31
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-Lorekeeper.quest-2026-10-31/prd.md
  - _bmad-output/planning-artifacts/prds/prd-Lorekeeper.quest-2026-10-31/addendum.md
  - _bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/EXPERIENCE.md
  - _bmad-output/planning-artifacts/brownfield-context.md
  - _bmad-output/planning-artifacts/spikes/cpu-benchmarks.md
  - _bmad-output/planning-artifacts/scope-input.md
companions:
  - _bmad-output/planning-artifacts/epics-parallel-plan.md
epicCount: 19
estimatedStories: 104
---

# Lorekeeper.quest - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Lorekeeper.quest, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

Steps 1 (requirements inventory) and 2 (epic list) are complete. Stories (step 3) are written by parallel agents per `epics-parallel-plan.md`. Terms follow PRD §3 exactly. Epic ids follow the ARCHITECTURE-SPINE boundary map (`E0a`, `E0-*`, `E1`–`E10`) plus one added epic (`E0-UX`); story ids are `<epic>.<n>` (for example `E1.3`, `E0-Access.2`).

### Decisions (autonomous run)

The owner pre-approved this run and was not available for step menus. Each decision below replaces a "[C] continue" or a user question.

- **D-1 Owner overrides win over the PRD** (`scope-input.md` "Owner decisions — round 2", already in the spine). (a) Reference Box = **16 GB, one profile**, CPU-only supported, GPU optional; container limits sum ≤ 14.5 GB (AD-7). NFR-2 is restated below on that basis. (b) Existing Members migrate to **Player**, not Co-GM (FR-7, AD-18). (c) The entity schema FR-4/FR-5 (plus FR-11/16/17, as the spine assigns them to E0-WorldCore) ships in **Phase 0**. (d) Commercial-edition TTS = **browser speech** (`TTS_PROVIDER=none`, AD-16); Kokoro + espeak-ng ships only as the optional `tts` container in the AGPL build.
- **D-2 Epics follow the spine boundary map**, so each epic maps to the modules and tables it owns, and CI's "one owner per table" check stays true. Titles are stated as user value. Foundation epics are still standalone outcomes (for example "Share Links stop leaking", "Jobs run in the background with visible progress").
- **D-3 Added `E0-UX` (Shell and design-system foundations).** The spine has no owner for theme tokens, `components/ui` primitives, `SlideOver`, the NavBar shell or global a11y CSS, and the UX spine lists defects in them. `E0-UX` owns those files and no tables.
- **D-4 FR-44 is split.** Invite, change Role and remove Member ship in `E0-Access` (it owns `members.py` and roles in `SharingPage.tsx`). Linking a Player to a PC and the "my character" consequences ship in `E7`.
- **D-5 Rate-limit key `user_or_ip` (AD-20) and the nginx `ai_gen` keying** are owned by `E0-Platform` (it owns compose and proxy config). Each feature epic adds its own `locations.conf` lines (shared append point).
- **D-6 UX open questions defaulted:** (1) global current Campaign = yes (CampaignSwitcher in `E0-UX`, role data from `E0-Access`); (2) nav renames accepted with redirects; (3) six built-in themes, no seventh; (4) preview as a generic Player; (5) Table view sizes stay as estimates and are verified in an E4 story; (6) the Achievement set is defined by E9 in `domain/achievements.py`; (7) browser notifications are opt-in in Settings; (8) Narrator display names are set after the SPIKE-3 listening test (E5).
- **D-7 GitHub Pages workflows** (`pages.yml`, `static.yml`, `jekyll-gh-pages.yml` all deploy the same site; `static.yml` publishes the whole repo). Owner decision still pending; included as a conditional E0-QA story recommending keeping only `pages.yml`.
- **D-8 PRD in flight.** Another agent is updating the PRD with the overrides. FR numbers are stable, so this inventory cites FR ids; where wording differs, D-1 applies. NFR-6 and §7 targets remain provisional until the x86 spike re-run.
- **D-9 Other inputs.** The brief, research and review files are excluded as inputs; their content is already folded into the PRD, addendum and spine.
- **D-10 Phases.** PRD §9 phases are kept, amended by D-1(c). Because the World Model core lands in Phase 0, E3 and E10 (and E7's wiki) no longer need to wait for E1; the build DAG in the parallel plan allows them to start once Phase 0 exits.

## Requirements Inventory

### Functional Requirements

**Foundations (PRD §4)**

- FR-1: Long AI and file work runs as background Jobs outside the request; the starting request returns a Job ID in < 1 s; Jobs survive web restarts and resume or fail visibly after a full restart; heavy-model Jobs run one at a time per model; priority interactive > on-save > backfill, and a backfill never delays another Campaign's on-save Jobs by more than one Job; Jobs resolve the owner's LLM config at run time, never queue raw keys, meter hosted usage; config failures fail without retry; other failures retry at most twice then show `failed` with a readable reason; the triggering Journal Entry stays saved.
- FR-2: Users see their Jobs' status (queued, running with progress and ETA, done, failed) and can retry failed ones; updates reach the UI within 5 s without reload; Job results are visible only to GMs.
- FR-3: AI features request schema-conforming structured output from the local LLM and reject invalid output (≤ 2 repair attempts, then "AI output unusable", nothing written); works with the bundled model, BYOK falls back to prompted JSON with the same validation; ≥ 95% valid on first or second attempt on EV-1.
- FR-4: Every Entity belongs to exactly one Campaign; same name in two Campaigns = two Entities; Mentions, Relationships and NPC Knowledge never cross Campaigns; global tags keep working, new features read Entities and Mentions. **(Phase 0, D-1c)**
- FR-5: On upgrade, NPC and Quest records become Entities with no data loss (role npc/pc/monster → Character, faction → Faction, Quest → Quest; notes → Secret); migrated Entities start GM-only and are bulk-published via FR-41; old links resolve; narrative name matches become suggested Mentions; migration is idempotent and never crash-loops boot. **(Phase 0, D-1c)**
- FR-6: Author or GM can edit a Journal Entry's Shorthand, Narrative, Session and Visibility; search, retrieval, tags and dedup reflect edits; editing a GM entry supersedes pending unedited proposals and re-queues extraction and continuity (not for Player Journal entries); approved Canon never changes automatically; delete removes Mentions and NPC Knowledge links, flags single-source Canon fields for review ("source deleted") and stops citations resolving; Players edit/delete only their own Player Journal entries.
- FR-7: Every Member has a Role assigned by the Owner; Owner is always GM; collaborate Share Links store a Role (default Player) and optional expiry; existing collaborate links grant Player; **existing Members migrate to Player (D-1b)**; a Player writes only their own Player Journal entries and own PC's Character Sheet, other writes return "not found"; write responses pass the Visibility filter; campaign management stays Owner-only; Players need no paid account for Party routes (BYOK/quota rules still apply to hosted AI).
- FR-8: Every record and Entity text field has a Visibility; one enforcement point applies the requester's Role to every read, write response, file download and AI context; covered records and defaults as PRD FR-8 (GM-only, always-GM, Private, Party lists); visibility follows evidence for proposals; Party records pointing at GM-only records are served with the reference removed; cross-Campaign and bare-ID fetches apply per-record Role and hidden = "not found"; GM authoring/AI routes are unavailable to Players ("not found"); AI context for a Player uses only content they may see; every stored file is served through an access-checked route with unguessable URLs.
- FR-9: P0 leak fix. **(a) ships now, alone:** read-only Share Link responses contain no Shorthand, NPC/Quest notes or Secrets (later no GM-only records), with a field-by-field test and release notes. **(b) same release as FR-7:** for Players and Share Links, chat sources, retrieval candidates, canon sources and returned system prompt carry no Shorthand or GM-only ids/snippets/titles; no glossary injection; keyword search, chat retrieval and entry-for-Entity matching rank on Party content only; blocking and streaming chat both covered; demotion Co-GM → Player archives that Member's NPC Conversations and chat sessions.
- FR-10: Campaign analytics and export cover every Member's entries; GMs get everything, Players get what FR-8 allows.

**F1 Living World Model (PRD §5.1)**

- FR-11: GM views, creates, edits and deletes Entities of every type; Players view Party Entities; each type has a list page and a detail panel (name, aliases, status, description, GM notes for GMs, Mentions, Relationships); status vocabularies per type (Character alive/deceased/missing/unknown; Location/Faction/Item active/destroyed or disbanded/unknown; Quests keep statuses and add steps).
- FR-12: Journal Entries link to mentioned Entities with the supporting quote; Entity panel lists confirmed Mentions newest-first (replacing name-substring lookup); entry view lists its Entities.
- FR-13: Saving or editing a GM-authored entry queues an extraction Job producing Change Proposals (new Entity, field/status change, Relationship new/changed, Quest Progress, Mention), each with source entry, quote, default Visibility and old/new values; no-op proposals hidden; meets NFR-6.
- FR-14: Proposals reference existing Entities by name or alias instead of duplicating; uncertain match offers up to 3 candidates plus "new Entity"; choosing one adds the surface form as alias; duplicate-Entity rate ≤ 10% on EV-1.
- FR-15: GM reviews all proposals from one entry in one Review Checklist grouped New / Changed / Quest progress; states pending/edited/approved/rejected; "Approve all" approves pending and edited only; opens from post-save flow and a pending-reviews indicator; approval re-checks old values (stale, merged or deleted targets re-confirm, redirect to survivor); rejected proposals are never re-raised for that entry; Players never see proposals.
- FR-16: Every approved change records source entry, approver and time and can be reverted; history lists each change with source link; reverts are themselves recorded.
- FR-17: GM merges two same-type Entities; survivor keeps aliases, Mentions, Relationships, history; links to removed Entity resolve to survivor; merged fields keep the more restrictive Visibility; warning when merging Party with GM-only.
- FR-18: GM re-runs extraction for one entry or the whole Campaign (backfill); never duplicates pending or re-raises decided proposals; backfill is one low-priority Job with per-entry progress.

**F2 Canon guard (PRD §5.2)**

- FR-19: Saving or editing a GM entry queues a continuity check; every Continuity Flag cites at least one conflicting entry, Entity field or Canon Note and quotes both sides; only claims sharing an Entity are compared; meets EV-2 targets.
- FR-20: GM sees flags beside the entry and in its Review Checklist; pending/failed checks never block saving; dismissal records a reason (false alarm, flashback/in-fiction framing, other); UI states the check is best-effort.
- FR-21: GM overrides a flag with a Canon Note (reason required) that becomes Canon; override offers the matching Entity change as a proposal; the same conflict (same Entity, Canon reference, attribute) is not raised again; Chronicler can cite Canon Notes subject to Visibility; Canon Notes appear in the concerned Entities' history.
- FR-22: Proposals contradicting Canon are marked in the checklist with the conflicting Canon cited; the GM can still approve and is offered a Canon Note.

**F3 Relationship web (PRD §5.3)**

- FR-23: GM creates, edits and ends typed, directed Relationships (per-Campaign editable type list, direction, note, Visibility, source entry); approved proposals can create them; ended Relationships stay in history.
- FR-24: Members pan, zoom, search and filter the graph (Entity Type, Relationship type, Faction) and open node panels; node style reflects type and status; 300 nodes / 600 edges at ≥ 30 fps on the reference laptop; approved Relationships appear without refresh; keyboard-accessible list view shows the same nodes and edges.
- FR-25: Players see only Party Entities and Relationships; layout, counts and search reveal nothing about hidden nodes; graph response holds no GM-only nodes or edges (EV-4).

**F4 Live Session (PRD §5.4)**

- FR-26: GM starts, pauses and ends a Live Session; captions appear chunk by chunk; on the Reference Box average processing per chunk ≤ chunk duration over 2 h and lag meets NFR-6, with lag shown; backlog indicator, audio queued up to 10 min then oldest skipped with notice; reconnect or refresh resumes with no loss of transcribed text.
- FR-27: Rolling Recap updates about every 60 s incrementally, keeping earlier content (a minute-5 fact survives a 2 h session); labelled as from the transcript, not the journal.
- FR-28: GM taps a recognised name or types one to see the Entity card and latest Mentions in < 2 s; matching transcript words are tappable; a free-text question gets a cited Chronicler answer or "not from your journal".
- FR-29: Ending a Live Session turns the full transcript (no truncation) into a draft Journal Entry through the existing review-then-save flow; never saved without GM approval; triggers F1/F2 Jobs once saved; raw audio deleted after transcription unless kept or diarization requested.
- FR-30: Optional offline speaker labels as a Job on a finished transcript; off by default; requesting before end keeps audio until done; hidden when the diarization model is absent.

**F5 Narrated recaps (PRD §5.5)**

- FR-31: GM generates a "Previously on…" recap of the last N Sessions (default 1, max 5) in the genre voice, edits before saving; opens with "Previously on…"; draws only on selected entries and cites them; never persisted without explicit save; Party-only by default, GM-only if GM content included; meets EV-6.
- FR-32: GM narrates a saved recap with a chosen Narrator as a Job, then plays, replays or downloads; 300 words meets NFR-6; cached audio replays; editing text or changing a source's Visibility invalidates the cache.
- FR-33: Each genre has a default Narrator (fantasy, sci-fi, horror, video game, other); GM can choose another; if TTS is unavailable, text shows with browser read-aloud and an "unavailable" notice. **Commercial edition always uses browser speech (D-1d).**
- FR-34: Players play Party Narrated Recaps from the Portal; GM-only recap text and audio are absent from every Player response and audio route (EV-4).

**F6 Talk to an NPC (PRD §5.6)**

- FR-35: GM starts an NPC Conversation from an NPC's panel; replies stream in character using name, description, status and voice notes; first token within NFR-6; deceased/missing NPC opens with a status notice citing its source, conversation can continue.
- FR-36: NPC replies draw only on NPC Knowledge; GM views the knowledge list and grants or hides entries or fields (including Secrets), applying from the next reply; suggested Mentions, unapproved proposals and other NPCs' conversations never enter knowledge; meets EV-3.
- FR-37: Outside its knowledge the NPC says in character it doesn't know; each reply lists entries drawn on; unsupported replies carry "not from this NPC's memories".
- FR-38: NPC Conversations are Private chat history and never change the World Model or journal; GM can copy a passage into a new Journal Entry draft that goes through normal review.
- FR-39: GM enables NPC Conversations for Players per NPC (off by default); Player persona uses only Party fields and Party knowledge (no voice notes, GM-only grants, Secrets); per-Player history; EV-3 and EV-4 show no GM-only content.

**F7 Player Portal (PRD §5.7)**

- FR-40: A Player opening the Campaign sees the Portal (recent Narratives, their PC, Party Entities by type, web, Maps, Narrated Recaps, search); usable at 375 px with no horizontal scroll; read-only Share Link shows the same Party content without Player Journals or "my character".
- FR-41: GM sets Visibility of any record or Entity field, in bulk from list views, and previews the portal as a Player through the same filtered read path; changes apply on next read; derived content (audio, Chronicle files, tiles, caches) is invalidated or hidden until regenerated.
- FR-42: Players write, edit and delete their own Player Journal entries; GMs can read them; author can share with all Members (never with read-only Share Links); Private by default; extraction runs only when a GM triggers it, and proposals go to the GM's checklist.
- FR-43: Players ask the Chronicler; answers draw only on visible content plus their own Private entries; GM-only facts get "not from your journal" with no hint.
- FR-44: Owner invites Members with a Role, changes Roles, removes Members and links a Player to a PC; Role change or removal takes effect on the next request and closes open streams; a linked Player sees their PC's Party Mentions and own Player Journal on "my character". **(Split, D-4.)**

**F8 Chronicle export (PRD §5.8)**

- FR-45: GM exports either edition, Player exports the Player edition, as PDF and EPUB with cover (name, genre, date range), TOC (page numbers in PDF, navigation in EPUB), chapters by Session date, Entity appendix by type when F1 data exists; GM can include shared Player Journal entries; EPUB passes EPUBCheck with no errors.
- FR-46: Exported text renders accented, non-Latin and typographic characters ("Ælfrida", "Ōkami", "—", curly quotes) with no "?" substitution.
- FR-47: Export runs as a Job and the file downloads through an access-checked route; 100 entries within NFR-6.
- FR-48: Player edition includes Party content only, built through the FR-8 read path and covered by EV-4; GM edition includes Shorthand and Secrets on opt-in.

**F9 Milestones and stats (PRD §5.9)**

- FR-49: Members see Sessions played, entries per Session, contributions per Member, most-mentioned Entities (from Mentions; from tags before F1) and Quest completion rate (completed / closed or active, defined in a tooltip); every stat a Player sees is computed from visible content only.
- FR-50: Each defined Achievement is awarded once per user per Campaign; Milestones ("10th Session", "first Quest completed", "100 Entities") shown; recompute is idempotent; Player counts are from visible content only; no loss messages, countdowns or nags.
- FR-51: Each user turns Streaks and Achievements on or off for themselves; off by default; one missed Session is covered by automatic grace.

**F10 Map pins (PRD §5.10)**

- FR-52: GM uploads, renames, replaces and deletes Maps (PNG, JPEG, WebP; ≤ 50 MB, ≤ 16,000 px longest side; others rejected clearly); large Maps prepared as a Job; a prepared 16,000 px Map pans/zooms with each view < 1 s; files persist, are backed up and served only through access-checked routes.
- FR-53: GM places, moves, edits and deletes Pins with a label linking a Location Entity and/or Journal Entries; positions are image-relative and survive zoom and same-aspect replacement; clicking a Pin opens the Location panel or linked entries; a Location's panel lists its Pins.
- FR-54: Players see only Party Maps and Party Pins; a GM-only Pin on a Party Map is absent from the response and tiles reveal no GM-only Pin (EV-4).
- FR-55: When F1 approves a new Location and a Map exists, the checklist offers to place it; accepting opens placement mode, declining creates no Pin.

### NonFunctional Requirements

- NFR-1: Local and offline. Every feature runs on the group's host with no internet once installed; no required cloud service; BYOK optional. DS-1..DS-5 pass with the internet disconnected; access over LAN or self-run remote access through the HTTPS front end (mic needs HTTPS); no new outbound calls except opt-in BYOK and model install; every model installable offline; one `docker compose up` brings up all services.
- NFR-2: Reference Box baseline and graceful degradation. **Amended by D-1a: the Reference Box is 16 GB, CPU-only, GPU optional, one profile.** No feature fails for lack of a GPU; heavy work runs as Jobs with progress; captions arrive in chunks; speaker labels optional. Sum of container limits ≤ 14.5 GB (AD-7 table); peak RSS stays inside it for idle, one heavy Job, and a Live Session with STT plus Rolling Recap. SPIKE-5 re-measures on x86.
- NFR-3: Model isolation. STT, TTS, NLI, diarization, embeddings, NER and OCR run in sidecars or lazily loaded queued work, never inside web workers; existing in-process STT and OCR move out; existing voice upload uses the new STT service; during a Live Session STT is the only newly resident model; the bundled 7B is reused and no further resident LLM is added (one loaded model, AD-7).
- NFR-4: Licence compatibility. Every new dependency (libraries, packages, images, weights, voices, fonts) is distributable under AGPL and the commercial licence; a licence register lists all; CI on every PR and `main`, no path filter, fails the commercial build on GPL, AGPL, statically linked LGPL, NC, Hippocratic or unknown; allowlist for dynamically linked LGPL system libs; register-vs-artifact check for weights, voices and system packages; backend CI runs on `main`.
- NFR-5: Privacy and spoiler safety. Players never see GM-only content (hard gate); EV-4 runs in CI with 0 leaks before release; Live audio processed locally and deleted after transcription by default; no new telemetry; data leaves the host only via user exports and opt-in BYOK.
- NFR-6: Latency targets (provisional until the x86 spike re-run; reset needs owner sign-off in `.memlog.md`): proposals ≤ 3 min CPU / ≤ 30 s GPU (≈ 500-word entry); continuity ≤ 3 min / ≤ 30 s; caption lag ≤ 30 s with sustained processing ≤ chunk duration / ≤ 5 s; Rolling Recap ≈ 60 s cadence, each update ≤ 45 s; quick lookup ≤ 2 s; NPC first token ≤ 20 s / ≤ 3 s; narration of 300 words ≤ 2 min / ≤ 30 s; Chronicle 100 entries ≤ 3 min; portal page load (warm) ≤ 2 s.
- NFR-7: Grounding and honest limits. Every AI output stating campaign facts cites sources or carries "not from your journal" / "not from this NPC's memories"; AI never changes Canon without GM approval; best-effort and slow features say so (continuity disclaimer, Job ETAs).
- NFR-8: Brownfield consistency. AI routes keep BYOK resolution, per-Campaign access check and hosted metering; every new AI or streaming endpoint gets slowapi and nginx limits, keyed per user not per IP; migrations forward-only, safe at boot, tested by running the chain against a copy of an existing database.
- NFR-9: Failure isolation. A failing AI step never blocks or loses a Journal Entry save; every failure shows in Job status.
- NFR-10: Theming and accessibility. New UI uses the six themes' tokens, works at 375 px, meets WCAG 2.2 AA; Review Checklist fully keyboard-operable; Narrated Recap always shows its text.
- NFR-11: Shared-server fairness (scope limit). One group per host; on multi-Campaign servers only FR-1 priority and the one-Job backfill bound are guaranteed; per-Campaign quotas are a non-goal.

### Additional Requirements

From ARCHITECTURE-SPINE (AD-n), addendum, brownfield recon and spikes. No starter template applies (brownfield; extend existing `src/backend` and `src/frontend`).

**Architecture decisions that create work (each cited by stories)**

- AR-1 (AD-1): Layered modular monolith with import rules enforced by `import-linter` contracts; `nlp_service`, `embedding_service`, `transcription_service`, `vision_service` become async client wrappers; `main.py` lifespan stops loading models; web/worker images never install torch, spaCy, sentence-transformers, whisper, easyocr, onnxruntime or TTS packages.
- AR-2 (AD-2): One job system: `jobs` row is authoritative, created only via `app/jobs/enqueue.py: enqueue(db, ctx, kind, payload, *, idempotency_key)`; outbox push in `after_commit`; reaper every 30 s re-pushes queued rows > 60 s; RQ message carries only `job_id`; `jobs/registry.py` declares queue, `timeout_s`, `resources`, `live_safe`, `result_audience`; `LorekeeperWorker` rebuilds ctx (fails `permission_changed` on `access_epoch` loss), resolves LLM config via `llm_config_service.resolve_llm_config`, heartbeats every 10 s.
- AR-3 (AD-3): Exactly three queues `interactive` > `onsave` > `backfill`, 2 worker processes; a Job does at most one entry's model work; backfills are cursor Jobs re-enqueuing themselves; Live admission lease (`live`, TTL 90 s) skips kinds using `{llm, nli, tts, cpu_heavy}` unless `live_safe`; `rq suspend` forbidden; NPC replies, Chronicler, quick lookup, recap drafts stream in-request.
- AR-4 (AD-4): Status `{queued, running, done, failed, cancelled}`, `max_attempts=3` owned by the PG row, RQ `retry=None`; terminal errors `LLMConfigError`, `StructuredOutputError`, `permission_changed`; retries at 10 s then 60 s; stale-heartbeat requeue; idempotency key unique among active rows with content version; closed `error_code` StrEnum.
- AR-5 (AD-5): Shared job routes `GET /api/jobs/{id}`, `GET /api/jobs/?campaign_id=&status=`, `POST /api/jobs/{id}/retry`, SSE `GET /api/jobs/stream?campaign_id=`; `core/pubsub.py` sole publisher with exactly three channels (`jobs:{campaign_id}`, `campaign:{campaign_id}:events` via `GET /api/campaigns/{id}/events`, `live:{id}:out`); `result_ref` only if visible; downgrade/delete invalidations unkeyed and throttled; `core/sse.py: sse_response` with ping and access-close.
- AR-6 (AD-6): Model sidecars `ml` (embed, ner, nli, ocr), `stt` (transcribe), `tts` (Kokoro-FastAPI) reachable only on the compose network via `app/clients/*`; health and `/v1/status`; weights baked at build, `HF_HUB_OFFLINE=1`; CI starts each sidecar with `--network none`; embedding contract `domain/embedding.py` (`EMBEDDING_DIM=384`) is the only definition; `ml` lazy NLI/OCR under `ML_RESIDENT_BUDGET_MB`, 503 on budget.
- AR-7 (AD-7): One profile, container limits table, sum ≤ 14.5 GB; changing a limit requires lowering another and re-running EV-5; `docker-compose.gpu.yml` override; diarize profile outside the sum.
- AR-8 (AD-8): `core/llm_gate.py: llm_slot(cls)` Redis priority semaphore for every local LLM call (classes `live_recap` > `gm_interactive` > `player_interactive` > `job_onsave` > `job_backfill`; 503 `llm_busy` after 60 s); `model_for` returns `LOCAL_LLM_MODEL`; strip per-call `num_ctx`/`num_gpu`/`keep_alive`; `prompt_budget.fit`; `detect_backend`; `complete_structured(messages, schema, config, *, task, timeout)` with backend-specific modes, pydantic validation, ≤ 2 repairs; flat schemas in `schemas/llm/<feature>.py`; typed `LLMError` family mapped by one route helper.
- AR-9 (AD-9): One `entities` table (`type`, `kind`), status validated by `domain/entity_types.py` with categories; `attributes` JSONB; composite FKs `(campaign_id, entity_id)`; `merged_into_id`; `world_service.match_names` / `normalize_name` sole matchers; only `visibility` and `campaign_role` are PG enums, other closed sets are CHECKs generated from StrEnums.
- AR-10 (AD-10): Single Canon write path `world_service.apply_change(db, ctx, CanonChange) -> EntityChange` writing append-only `entity_changes` and queuing `canon_changed`; GM ctx or `ctx.as_system(reason)` (only journal delete and merge); approval re-reads and marks stale; merge sets `visibility_floor`; journal FKs `ON DELETE SET NULL` with `source_deleted_at`, delete raises `confirm_field` items.
- AR-11 (AD-11): `proposal_batches` (origin extraction/override/promotion/source_deleted), `change_proposals` ops, payloads, states, fingerprint uniqueness; `continuity_flags` with `conflict_key`; `continuity.check` depends on the extraction Job; `canon_notes` + `canon_note_entities` registered as retrieval source; `npc_knowledge` stores only grant/hide overrides; `npc_settings`; all `always_gm`.
- AR-12 (AD-12): Visibility PG enum `{party, gm, private}`; `field_visibility` JSONB; Audiences `Public ⊃ Members ⊃ Owner(u) ⊃ GM`; registry classes `stored` / `derived` / `always_gm`; binding Mention audience formula; `visible_clause` and `audience_of` generated from one registry with a property test; new columns on `journal_entries` (`kind`, `visibility`, `party_tsv`, `party_embedding`), `campaign_members` (`role`, `access_epoch`), `campaign_share_tokens` (`role`, `expires_at`, `access_epoch`), `entities.linked_user_id`, `character_sheets.pc_entity_id`.
- AR-13 (AD-13): `app/access/` is the only role interpreter: `CampaignContext`, `require_campaign(min_role)`, `can_write`, `role_map`/`scoped_select_multi` (replace `accessible_campaign_ids`), `scoped_select`, `project`, `resolve_sources`, `audience_ctx`, `set_visibility` (sole visibility writer, marks derived dependents stale, queues `visibility_changed`); Party schemas omit GM fields, hidden renders as unset; uniform `404 {"detail":"Not found"}`; non-GM AI context uses `party_*` columns, no glossary, no trace system prompt; `retrieval_service.register_source`; stored chat refs redacted on read/replay; grant changes bump `access_epoch` and close streams; capture hook for EV-4; cache keys include audience and epoch, `cache:journals:{user_id}` removed.
- AR-14 (AD-14): `stored_files` + `derived_sources` + `DERIVED_REGISTRY`; `file_service` sole reader/writer (`put`, `open`, `delete`, `gc` via `files.gc` Job); bytes on `files_data` volume; served only by `GET /api/files/{id}` and the tile route with `X-Accel-Redirect`, private cache, epoch ETag; stale files 404 to non-GMs; tiles never contain pins; backups doc updated.
- AR-15 (AD-15): Live WS `wss://…/api/live/{id}/ws`, first message auth, GM only; `live_sessions` state; PCM16 16 kHz chunks (15 s default, 10–30 configurable) with `{seq, start_ms}`; `live_chunks` unique `(live_session_id, seq)`; single drainer via Redis lock; `initial_prompt` from Entity names, aliases and glossary; server messages `caption`, `backlog`, `recap`, `notice`; reconnect replay; `live.recap` Job `interactive`/`live_safe` ≤ every 60 s; 10-min backlog cap; `live.draft` map-reduce; audio deletion rules; nginx `/api/live/` Upgrade block, `proxy_read_timeout 4h`; `/api/ingest/voice` calls `stt`.
- AR-16 (AD-16): `LOREKEEPER_EDITION ∈ {agpl, commercial}`; commercial forces `TTS_PROVIDER=none` and strict licence mode; `TTSProvider` protocol in `tts_service.py` (`kokoro_http`, `none`); sentence-level synthesis concatenated in worker, no ffmpeg; presets in `domain/narrators.py` keyed `(provider, genre)`; ≤ 500 MB; cache key `sha256(provider|preset|text|audience)`; a new engine must pass the proper-noun STT round-trip test.
- AR-17 (AD-17): Journal writers `create_journal_entry`, `update_journal_entry`, `delete_journal_entry`, `reindex_entry` only; recompute `narrative_tsv`, `party_tsv`, `embedding`, `party_embedding` (fallback `journal.reembed` Job), tags with `source_field`, server-side `entry_hash` unique on `(campaign_id, user_id, entry_hash)`; offline-queue entries land `visibility=gm`; hooks via `after_commit` with events `entry_saved`, `entry_updated`, `entry_deleted`, `visibility_changed`, `canon_changed`, `role_changed`, `job_finished`, `live_session_ended`; payload `{campaign_id, refs, actor_ctx}`; handlers in `app/hooks/<feature>.py`, failures logged `hook_failed`.
- AR-18 (AD-18): Alembic contains schema plus set-based SQL; legacy copy `npcs`/`quests` → `entities` idempotent with status map (`dead → deceased`), `legacy_npc_id`/`legacy_quest_id`, `visibility=gm`, `notes → gm_notes`; `npcs`/`quests` frozen, legacy routes become adapters; `GET /api/entities/legacy/{npc|quest}/{id}`; per-row work via `data_backfills` as backfill Jobs; members → `player`, archive their chat sessions, entries stay `kind=gm` / `visibility=party`; collaborate links grant `player`; read-only links = anonymous Public.
- AR-19 (AD-19): Foundation revisions in fixed order F1-core (E0-Access) → F2-jobs-files (E0-Jobs) → F3-world (E0-WorldCore), continuing after head `a3e7c1f9d258`; feature epics add only their own tables; ids from `alembic revision`, rebase `down_revision` before merge; models registered in `db/models/__init__.py` (`AppConfig` in `__all__`), `env.py` imports the package.
- AR-20 (AD-20): slowapi `@limiter.limit` keyed `user_or_ip` on every new AI/streaming route; nginx `ai_gen` keyed on a hash of the bearer; anchored regex locations for AI routes with ids; job/event/file/tile routes in the generic zone with `proxy_buffering off` where streaming; `/_files/` internal.
- AR-21 (AD-21): Test DB via `alembic upgrade head` on `TEST_DATABASE_URL` (default `lorekeeper_test` on `docker-compose.dev.yml` pgvector pg16), Redis from the same file; `create_all` removed; fake LLM provider, client fakes, `JOBS_EAGER=1`; EV-4 harness `tests/ev4/` enumerating `app.routes` and nginx locations with per-feature probes or reasoned exemptions and the required probe families; evals as `scripts/eval_<name>.py` + `docs/<NAME>_EVAL.md` on committed `seeds/demo_campaign.json` via `scripts/seed_demo.py`.
- AR-22 (AD-22): `licenses/register.yaml` updated in the same PR as any dependency, image, apt package, model, voice or font; scans: `pip-licenses` (web, worker, ml, stt), `license-checker-rseidelsohn` (frontend), image apt scan, register-vs-artifacts for weights; allowlist dynamic LGPL system libs (libvips apt, Pango, HarfBuzz, GLib), no `pyvips[binary]`; strict mode in commercial; `tts` image permitted only for AGPL.
- AR-23 (Conventions): naming (`<feature>.<verb>` job kinds, `<domain>_service.py`, `routes/<domain>.py`); UUID v4, `timestamptz` UTC ISO-8601 Z, Session order `session_date ?? created_at`; error shape and 404-never-403; `<X>GMResponse` / `<X>PartyResponse` via `access.project`; `SourceRef` / `ResolvedSource` / `grounded`; grounding instructions in the final user turn each turn; new settings in `core/config.py`; JSON-line logging without tokens, keys, Shorthand or audio; admin System tab shows sidecar status and job counts.
- AR-24 (Frontend conventions): `services/api/<domain>.ts`, `types/<domain>.ts`, `hooks/use<Domain>.ts` keyed `[domain, campaignId, …]`; SSE only via `lib/sse.ts` (extracted from `useChat`; bearer header, backoff, no EventSource or `?token=`), `useChat` migrated; `useJobStream`, `useCampaignEvents`, `useCampaignRole` (`GET /api/campaigns/{id}/me`); named-export lazy pages, one `NAV_GROUPS` line each; `components/review/ReviewChecklist.tsx` + `itemRenderers.ts` keyed `proposal:<op>` / `flag`; `components/entities/EntityDetailPanel.tsx` + `panelSections.ts` (E2, E3, E6, E10 register sections, never edit the panel); graph and map conventions.
- AR-25 (Deployment): images multi-arch `linux/amd64,linux/arm64` via buildx; `scripts/deploy-oci.sh` updated (OCI Ampere A1 arm64 host runs the same profile); web boot runs `pg_dump` then `alembic upgrade head`; worker starts after web healthy; rollback = restore dump + previous tag; `COMPOSE_PROFILES=tts` only in AGPL.
- AR-26 (Addendum C, P0 leak detail): share-specific response schemas; Player chat schemas with no `shorthand` field; `narrative_tsv`/embedding include Shorthand so Player retrieval needs `party_tsv`/`party_embedding` in Phase 0; `/npcs/{id}/entries` and `/quests/{id}/entries` ILIKE on shorthand; routes using `accessible_campaign_ids` (journal list/get/tag attach-detach/delete, `tags.py` counts) replaced by role map; GM-only authoring/AI route list; records lacking Visibility (Session Plans, Character Sheets, `ShorthandTerm`, Tag Categories, `ChatSession`); `PUT /npcs`/`PUT /quests` write responses filtered.
- AR-27 (Brownfield test gaps): route tests skip lifespan; no fake LLM; frontend has no test runner (`tsc` strict stays the gate; EV-4 runs against the API); conftest hardcodes `TEST_DB_URL`; 10 backend tests total.

**CI gates (all on every PR and `main`, no path filter)**

- CI-1: Backend CI triggers on `main` (today `master` only).
- CI-2: `import-linter` layer contracts (AD-1).
- CI-3: Fail if web/worker requirements list a model package (AD-1, AD-16 TTS packages).
- CI-4: Licence scans and strict commercial mode (AD-22, NFR-4).
- CI-5: Sidecar images start with `--network none` and pass health (AD-6).
- CI-6: Single Alembic head; `upgrade head` on empty DB and on a seeded `a3e7c1f9d258` snapshot; FK action test (AD-19, NFR-8).
- CI-7: Boundary-map parser fails when a table has two owners (AD-19).
- CI-8: `scripts/check_scoped_queries.py` ratchet against `scoped_queries_baseline.txt` (AD-13).
- CI-9: Flat LLM schema test (no `$ref`/`anyOf`, `extra="forbid"`) (AD-8).
- CI-10: StrEnum ↔ CHECK sync test (AD-9).
- CI-11: Registry property test `visible_clause` ≡ `audience_of` (AD-12).
- CI-12: EV-4 spoiler-leak suite, 0 leaks, hard gate (NFR-5); uncovered route fails.
- CI-13: Multi-arch buildx image build (AD-25).
- CI-14: AD-7 memory-limit sum check over `.env.example` (≤ 14.5 GB).
- CI-15: Frontend `tsc` strict build; grep check blocking new hardcoded `green-*`/`amber-*`/`red-*` and `text-destructive` in new UI (UX-DR3).

**Spikes and licence investigation (PRD §8; status from `spikes/cpu-benchmarks.md`)**

- SPIKE-1 NLI (R-1): measured on M-series; xsmall 50 pairs 0.71 s, base 2.58 s; both produced one confident false contradiction. Decision: xsmall default, base only if EV-2 on ≥ 50 real pairs gains. **Remaining:** x86 re-run. Owner epic E0-QA (benchmarks) feeding E2.
- SPIKE-2 STT (R-2, R-10): measured on M-series; faster-whisper base passes (worst chunk RTF 0.31 int8), small fails live. Decision: base, 15 s chunks, `compute_type` config. **Remaining:** x86 re-run int8 vs float32, LLM-busy case, `initial_prompt` name accuracy. E0-QA + E4.
- SPIKE-3 TTS (R-3): Kokoro RTF 0.25–0.38, sentence-level peak 2.1 GB, paragraph 3.9 GB (forbidden). **Remaining:** kokoro-onnx RSS on Linux, Narrator listening tests. E5.
- SPIKE-4 Diarization (R-4): not run. Time to diarize 1 h on CPU and offline pre-downloaded install. Decides whether FR-30 ships and which engine. E4.
- SPIKE-5 Memory (R-5): not run. Per-service RSS for idle, one heavy Job, Live Session; verify the AD-7 limits on x86; tile a 16,000 px map. E0-Platform.
- SPIKE-6 LLM throughput (R-6): not run (Ollama unavailable). Prompt and generation tokens/s per prompt shape with Entity lists of 50 and 300; decides extraction shortlist vs full list. E0-LLM, feeding E1.
- LIC-1 (R-7): technical part answered: `pip install kokoro` bundles GPL-3.0 espeak-ng via `espeakng-loader`; without it, fantasy proper nouns are silently dropped. Owner decision applied (D-1d). **Remaining:** record findings in the licence register and keep the non-GPL pronunciation path (Entity-name lexicon as Kokoro phoneme overrides) as a deferred spike; legal review is an owner action. E5 + E0-QA.

**Evaluation harnesses (PRD §7)**

- EV-1 Extraction (E1): ≥ 15 entries / ≥ 60 labelled changes; P/R/F1 per type, duplicate rate, schema-valid rate, Visibility-default correctness; operating points with/without NER pre-pass and Entity list; `docs/EXTRACTION_EVAL.md`. SM-1: F1 ≥ 0.75, status precision ≥ 0.80.
- EV-2 Continuity (E2): ≥ 10 contradictions, ≥ 10 controls, flashback/rumour and retcon traps; detection, false alarms, citation correctness; NLI threshold sweep with/without LLM verification; `docs/CONTINUITY_EVAL.md`. SM-2.
- EV-3 NPC knowledge (E6): 3 NPCs × ≥ 8 known + ≥ 8 unknown probes incl. a GM-hidden fact; answer rate and leak rate; `docs/NPC_KNOWLEDGE_EVAL.md`. SM-3: leak ≤ 5%, 0 on hidden, answer ≥ 75%.
- EV-4 Spoiler leakage (E0-QA harness; every epic adds probes): canary seed; every route as Player, anon Share Link, and GM-in-one/Player-in-another; responses, captured AI context, inference channels; route list from router + nginx; 0 leaks hard CI gate; live-model run before release; `docs/SPOILER_EVAL.md`. SM-4.
- EV-5 Performance (E0-QA; rows contributed by each epic): wall-clock and peak memory for every NFR-6 row and NFR-2 case; `docs/BENCHMARKS.md`. SM-5.
- EV-6 Recap faithfulness (E5 for Narrated, E4 for Rolling): 5 Narrated + 2 Rolling recaps; share of supported sentences; `docs/RECAP_EVAL.md`. SM-8 ≥ 90%.
- Demo seed: `seeds/demo_campaign.json` (9 entries: Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker, plus added status-change, contradiction and trap entries), owned by E0-QA; each eval epic appends its labelled entries.
- Demo scenarios DS-1..DS-5 (phase exits): DS-1 E1, DS-2 E2, DS-3 E7 (+E3, E10), DS-4 E4 + E6, DS-5 E5 + E8 + E9. All run offline (NFR-1).

### UX Design Requirements

From DESIGN.md (visual tokens and components) and EXPERIENCE.md (behaviour). Includes the existing defects found in the UX review.

**Existing defects and design-system foundations**

- UX-DR1: Add six semantic tokens `success`, `warning`, `info`, `gm`, `live`, `danger` as HSL keys in `types/theme.ts` `ThemeColors` and in all six `themes/*.ts` files with the DESIGN.md values (each ≥ 4.5:1 on that theme's card, background and its own 14% wash); expose as `hsl(var(--x))` in `tailwind.config.ts`; custom themes missing them fall back to dnd values (dark) or light values (background lightness > 50%).
- UX-DR2: **Defect: destructive-token contrast.** Dark-theme `destructive` (lightness 30–35%) fails AA as text. Readable error text and icons use `text-danger`; `destructive` stays for fills only; replace existing `text-destructive` text usage on dark themes.
- UX-DR3: **Defect: ~50 hardcoded `green-*`, `amber-*`, `red-*` Tailwind classes.** Migrate them to semantic tokens (DESIGN marks migration optional; this plan includes it as one story) and add the CI-15 grep check so new UI never introduces them or hex colours.
- UX-DR4: **Defect: `SlideOver` lacks a focus trap.** Add focus trap and return-focus-to-opener; add the wide variant (`slideover-wide` 48rem) and full-screen below `md`; support an in-panel "← Back to …" push header; enforce one SlideOver at a time (no modal-over-modal).
- UX-DR5: Global `prefers-reduced-motion` handling (none exists today): SlideOver and sheets don't slide, skeletons don't pulse, REC dot and Job ring static, no foil shimmer, captions jump-scroll, graph never animates layout or zoom.
- UX-DR6: New primitives `SegmentedControl`, `Tabs`, `Combobox` in `components/ui`, cva-styled like `button.tsx`, WAI-ARIA tabs/radio/combobox keyboard patterns; route-mapped Tabs update the URL; Combobox trailing "Create…" only where creation is allowed.
- UX-DR7: `Toast` system: popover surface, bottom-right `md+` / bottom-centre phones, up to 3 stacked, auto-dismiss 6 s (Undo 10 s, failures persist), polite announcements, one action.
- UX-DR8: `EmptyState` (dashed `rounded.xl`, 40px lucide icon, one line, one action) replacing emoji headlines in new pages; `ModelMissingNotice` (inline warning wash, lucide TriangleAlert, admin link with size, "Ask your admin" otherwise); lucide instead of emoji as UI icons in new UI.
- UX-DR9: Typography roles: `entity-title` (30px, 24px mobile), italic `quote`, `mono` with tabular figures for timestamps/ETAs/counts, `caption-live` 20px, `caption-table` 36px, `recap-table` 32px; families always from `--font-heading` / `--font-body`.
- UX-DR10: Shell: `CampaignSwitcher` with `RoleBadge` and global current-Campaign state remembered per device (fallback with toast when access is lost); nav restructure (World absorbs Characters and Quests; Record Session → Live Session; Analytics → Stats; new Keepsakes) with redirects `/characters`, `/quests`, `/record`; Player nav set (Portal, World, My Journal, Chronicler, Recaps) and `/dashboard` → `/portal` for Players; route-change title announcements; one unified not-found page identical for missing and forbidden.
- UX-DR11: Spoiler-safety components: `VisibilityBadge` (pill with icon and word; GM menu button; moving to Party confirms inline, to GM-only doesn't; hidden from Players except Private/Shared on own journal), `SecretField` (dashed gm border, "GM only" announced before label), Field visibility hint on focus, `PreviewBanner` (info band above nav z 60, every screen, Esc never exits, writes disabled with "Preview is read-only").
- UX-DR12: Touch targets ≥ 44px (56px in Live Session and Table view); no hover-only affordances below `md`; `Esc` closes the top layer; shortcuts never fire in inputs; `?` shows the shortcut list.
- UX-DR13: Global state patterns: skeletons shaped like content (never full-page spinner); offline read-only notice on new surfaces; inline request errors in `danger` with Retry and kept input; voice and tone rules (ETAs as ranges or "about", entries named by italic title, never raw IDs, sentence-case buttons, AI-made text labelled with its origin).

**Jobs and World Model**

- UX-DR14: `JobTrayButton` (Hourglass, count of running Jobs + pending reviews, spinning segment) and Job tray popover (running, queued, last 24 h, pending checklists; actions View, Retry, Download, Cancel-queued); `JobRow` (stage, 4px determinate bar or "Queued · 1 ahead", mono ETA, danger reason on failure); Job completion toast, "(1)" title prefix, opt-in browser notification only when tab hidden; long-Job state patterns (queued, running, done, failed, "AI output unusable").
- UX-DR15: Post-save card under a saved entry: "Saved." then per-stage rows ("Reading for world changes", "Checking continuity") with bar and ETA, becoming "7 changes to review · 1 continuity flag" with Review; never blocks the next entry.
- UX-DR16: `ReviewChecklist` (`EntityDiffReviewPanel`) behaviour 1–12 in EXPERIENCE.md: wide SlideOver, Continuity section first, groups with counts, needs-attention first, staging until "Apply to world", sticky tally footer with "Approve remaining (n)", group approve, partial apply, filter row, collapse > 8 items, keyboard triage `j/k/a/r/e/u/Shift+A`, `Ctrl/⌘+Enter` apply, progress line, re-check at Apply with Stale and "Now applies to … (merged)" chips, Undo toast 10 s, local draft on close, FR-55 follow-up prompt, marked-proposal Canon Note offer; a11y listitem labels and `aria-live` announcements; focus stays on item.
- UX-DR17: `ProposalItem` four states (pending, edited, approved, rejected) and attention chips ("Possible duplicate", "Stale", "Contradicts canon", "From your Shorthand"); diff old struck / new bold; `MatchPicker` radio list (≤ 3 candidates + New entity, re-targets to alias add).
- UX-DR18: Reviews queue `/reviews` (one row per entry with pending counts, oldest first, backfill results one checklist per entry, "All caught up" empty state) and the Dashboard "N to review" pill.
- UX-DR19: World hub `/world` with type chips, search, card grid, GM bulk-selection mode with "Make 24 entities visible to players?" confirm, and the post-upgrade callout ("142 entities came over… Review and publish").
- UX-DR20: `EntityPage` (`/world/:type/:id`, `md:grid-cols-[1fr_280px]`) and `EntityPanel` (SlideOver) with sections registered in `panelSections.ts`: Overview (GM notes as SecretField), Relationships, Mentions, On maps, History, NPC Knowledge and "Talk to"; overflow (Edit, Merge…, Set visibility, Re-run extraction, Delete, Preview as Player); inline per-section editing; Player view without gaps; deleted/merged-while-open states.
- UX-DR21: `StatusBadge` (colour + icon + word; GM click to change, records "Manual edit"; "since *entry*" citation), `HistoryList` (mono dates, diff, source, approver, inline revert confirm, "source deleted" with Review, Canon Note blocks), `MentionList` (newest first, suggested Mentions dashed with Confirm/Remove, click opens entry at the highlighted quote, paginate in 20s), Merge dialog (survivor pick, preview, Visibility warning), `EntityCard`.
- UX-DR22: Entry detail additions: Mentions strip, ContinuityFlags above Narrative, Edit button (FR-6), VisibilityBadge.

**Feature surfaces**

- UX-DR23: `ContinuityFlag` card (two quote columns stacking below `sm`, best-effort footer, Dismiss menu with reasons and 10 s Undo, "Checking continuity…" chip, failed-check Retry) and `CanonNoteForm` (required reason, "Also propose: …" checked by default, resolved Canon Note block, proposal marked "From Canon Note").
- UX-DR24: Relationship web: `GraphCanvas` (shape = type: circle/rounded square/hexagon/diamond; dashed gm stroke for GM-only; deceased dimmed; labels at zoom ≥ 1 or focus), `GraphToolbar` (search `/`, filter chips, list toggle, zoom, Fit, "Showing 48 of 214 · Clear filters"), `GraphListView` (peer, sortable, expandable edges; default below 640 px, > 1,000 nodes or no WebGL), `NodeLegend`; layout computed before display and persisted per Campaign per device; neighbour highlight; keyboard navigation and announcements; Add/End relationship forms; no hidden-node hints for Players.
- UX-DR25: Maps: map list with upload card and "Preparing map…" Job state, `MapViewer` (pan, zoom, Fit, pins constant screen size), `MapPin`/`map-pin-gm` teardrops, `PlacementBar`, `PinEditor` (label required, Location Combobox with "Create Location…", linked entries, Visibility default from Location or GM-only), `PinList` (complete keyboard equivalent), move by drag or arrows (Shift ×10), replace-image aspect warning and "Review pin positions" mode, "On maps" and "Place on a map" from a Location, `p` placement shortcut.
- UX-DR26: Live Session page: pre-checks (speech model, HTTPS, mic permission) with distinct states and "Record only" link; Start panel; `LiveStatusBar` (REC dot + word, mono elapsed, `LagMeter`, Pause, End, Table toggle) pinned in top 56px; `CaptionChunk` with dotted-underlined Entity names; `CaptionPending`; jump-to-live; `BacklogBanner` and in-line skipped ranges; `RollingRecapCard` with "From the transcript, not your journal", age and coverage; `QuickLookup` (rail on tablet/desktop, bottom sheet on phone, skeleton then card ≤ 2 s; "Searching NPC records" fallback); reconnect toast; End confirm with "Keep raw audio" and "Label speakers afterwards"; Table view (`t`); screen wake lock or "Keep this screen on"; phone bottom tabs; captions `aria-live` log, backlog notices assertive once.
- UX-DR27: `RecapPlayer`: Narrator chip, 44px play/pause, scrubber, speed 0.75–1.5×, download, Table play (full-screen, `recap-table`, Space toggles), sentence highlight that stays in view unless user scrolled, text always visible, no autoplay, "Narrator unavailable — using your browser's voice" fallback; Keepsakes page with Previously on / Chronicle tabs; GM-only recap badge "Only GMs can play this recap."
- UX-DR28: NPC Conversation: `/chat?npc=:id` mode, sidebar grouped by NPC; `NpcChatHeader` (avatar, name in heading face, StatusBadge, KnowledgeScope chip "Knows 14 entries · 2 hidden", Private badge); deceased/missing notice banner; "Veyra is thinking… 12 s — slower on CPU" row after 5 s; "Drawn from 3 entries" disclosure or `NotFromMemoriesLabel`; "Copy to a journal draft"; `KnowledgeEditor` three-state rows (Knows · Granted · Hidden, Secrets grant-only explicitly, "Applies from the next reply"); Player NPC toggle "Players can talk to {name}".
- UX-DR29: Player Portal: mobile-first 375 px single column, `md` two columns; home (latest recap, My character, Recent story, World by type, Ask the Chronicler); My character (PC Party Mentions, own Player Journal; "Your GM hasn't linked your character yet."); `PlayerJournalComposer` (title, textarea, Private / Share with party SegmentedControl, no AI step, no extraction); no GM jargon; Player surfaces never show absences; role-change notice to Owner about archiving.
- UX-DR30: Sharing › Members: invite with Role, change Role (with the archive notice), remove, link Player to PC, link expiry; Role badges.
- UX-DR31: `ChronicleExportPanel`: edition SegmentedControl (Player default, GM with gm badge), PDF/EPUB checkboxes, include toggles (appendix, maps, shared Player Journals, GM-only Shorthand/Secrets off), summary line with page estimate, cover preview, Job progress, downloads, past exports with "Out of date — visibility changed since" and Re-export; Chronicle typography (bundled OFL serif, Cinzel chapters).
- UX-DR32: Stats page (renamed Analytics, reusing StatTile/WeeklyBarChart/TagRankList): `MilestoneCard` (foil top rule, shown once on Dashboard/Portal, permanent on Stats), `AchievementBadge` (foil ring only when earned, opt-in only), Settings › Notifications & milestones toggles; celebration-only copy, no streak guilt.

### FR Coverage Map

Every FR and NFR maps to at least one epic. Primary owner first; "+" marks contributing epics.

| Req | Epic(s) | Note |
|---|---|---|
| FR-1 | E0-Jobs | Job system, queues, retries, priority |
| FR-2 | E0-Jobs + E0-UX | Job API/SSE; tray UI built in E0-Jobs on E0-UX primitives |
| FR-3 | E0-LLM | `complete_structured`, validation and repair |
| FR-4 | E0-WorldCore | Campaign-scoped `entities` with composite FKs (Phase 0) |
| FR-5 | E0-WorldCore | Legacy NPC/Quest copy, redirects, suggested Mentions backfill (Phase 0) |
| FR-6 | E0-Journal + E1 | Edit/delete write path and hooks; E1 supersede-and-requeue handler |
| FR-7 | E0-Access | Roles, members → Player, link Roles, write rules |
| FR-8 | E0-Access + every feature epic | Enforcement point; each epic registers its tables and probes |
| FR-9 | E0a (a), E0-Access (b) | Hotfix ships alone; (b) ships with FR-7 |
| FR-10 | E0-Access | Analytics and export scope |
| FR-11 | E0-WorldCore | Entity CRUD, list pages, detail panel (Phase 0) |
| FR-12 | E1 + E0-WorldCore | Mentions table in F3-world; extraction-created Mentions and entry Mentions strip in E1 |
| FR-13 | E1 | Extraction Job |
| FR-14 | E1 + E0-WorldCore | `match_names` in WorldCore; MatchPicker and shortlist in E1 |
| FR-15 | E1 | Review Checklist |
| FR-16 | E0-WorldCore | `entity_changes`, history, revert |
| FR-17 | E0-WorldCore | Merge |
| FR-18 | E1 | Re-run and cursor backfill |
| FR-19 | E2 | Continuity check Job |
| FR-20 | E2 | Flag display and dismissal |
| FR-21 | E2 | Canon Notes, override, retrieval source |
| FR-22 | E2 | Marked proposals |
| FR-23 | E3 | Relationship CRUD and types (rows written via `apply_change`) |
| FR-24 | E3 | Graph UI and list view |
| FR-25 | E3 | Player graph filtering + EV-4 probe |
| FR-26 | E4 | Live transport, captions, backlog, reconnect |
| FR-27 | E4 | Rolling Recap |
| FR-28 | E4 | Quick lookup |
| FR-29 | E4 | End-of-session draft hand-off |
| FR-30 | E4 | Diarization (cut-first) |
| FR-31 | E5 | Recap text |
| FR-32 | E5 | Narration Job and cache |
| FR-33 | E5 | Narrators, provider interface, browser fallback |
| FR-34 | E5 + E7 | Player audio route; Portal placement |
| FR-35 | E6 | NPC Conversation |
| FR-36 | E6 | NPC Knowledge |
| FR-37 | E6 | In-character refusal and citations |
| FR-38 | E6 | Not Canon; copy to draft |
| FR-39 | E6 | Player NPC Conversations (cut order #3) |
| FR-40 | E7 | Portal home and wiki |
| FR-41 | E7 + E0-Access | `set_visibility` in E0-Access; bulk controls and preview UI in E7 |
| FR-42 | E7 | Player Journals |
| FR-43 | E7 + E0-Access | Player-scoped retrieval built in E0-Access; Player chat surface in E7 |
| FR-44 | E0-Access + E7 | Invite/role/remove (E0-Access); PC link and "my character" (E7) |
| FR-45 | E8 | Chronicle PDF/EPUB |
| FR-46 | E8 | Unicode |
| FR-47 | E8 | Export Job and download |
| FR-48 | E8 | Editions follow Visibility |
| FR-49 | E9 | Stats |
| FR-50 | E9 | Achievements and Milestones |
| FR-51 | E9 | Opt-in streaks |
| FR-52 | E10 | Map upload and tiling |
| FR-53 | E10 | Pins |
| FR-54 | E10 | Map/Pin Visibility |
| FR-55 | E10 (+E1 renderer slot) | Checklist follow-up offer |
| NFR-1 | E0-Platform + E0-QA | Offline sidecars and baked weights; offline DS runs |
| NFR-2 | E0-Platform | 16 GB profile, limits, SPIKE-5 |
| NFR-3 | E0-Platform | Models out of web workers |
| NFR-4 | E0-QA | Licence register and CI gate (+ every epic registers deps) |
| NFR-5 | E0-Access + E0-QA | Enforcement + EV-4 hard gate (+ every epic adds probes) |
| NFR-6 | E0-QA (EV-5) + E1, E2, E4, E5, E6, E7, E8 | Each feature epic measures its row |
| NFR-7 | E0-Access (SourceRef/grounded) + E1, E2, E4, E5, E6 | Citations and labels |
| NFR-8 | E0-QA + E0-Platform + E0-LLM | Migration-chain tests; rate limits; BYOK/metering patterns |
| NFR-9 | E0-Journal + E0-Jobs | Hooks never block saves; failures in Job status |
| NFR-10 | E0-UX + every UI epic | Tokens, a11y floor, keyboard checklist (E1) |
| NFR-11 | E0-Jobs | Queue priority, cursor backfills |

**Other requirement coverage**

| Item | Epic |
|---|---|
| AR-1, AR-6, AR-7, AR-20, AR-25, SPIKE-5 | E0-Platform |
| AR-2–AR-5, AR-14 | E0-Jobs |
| AR-8, SPIKE-6 | E0-LLM |
| AR-12, AR-13, AR-18 (members), AR-19 F1-core, AR-26 | E0-Access |
| AR-17 | E0-Journal |
| AR-9, AR-10, AR-18 (legacy copy), AR-19 F3-world | E0-WorldCore |
| AR-11 | E1 (proposals), E2 (flags, Canon Notes), E6 (NPC Knowledge) |
| AR-15, SPIKE-4 | E4 |
| AR-16, SPIKE-3, LIC-1 | E5 |
| AR-21, AR-22, AR-27, CI-1–CI-15 (harness), SPIKE-1/2 x86 re-run, EV-4, EV-5, demo seed, D-7 | E0-QA |
| AR-23, AR-24 | All epics (conventions) |
| EV-1 / EV-2 / EV-3 / EV-6 | E1 / E2 / E6 / E5 + E4 |
| UX-DR1–UX-DR13 | E0-UX |
| UX-DR14 | E0-Jobs (on E0-UX primitives) |
| UX-DR15–UX-DR18, UX-DR22 (Mentions strip) | E1 |
| UX-DR19–UX-DR21 | E0-WorldCore |
| UX-DR22 (Edit, VisibilityBadge) | E0-Journal |
| UX-DR23 | E2 |
| UX-DR24 | E3 |
| UX-DR25 | E10 |
| UX-DR26 | E4 |
| UX-DR27 | E5 |
| UX-DR28 | E6 |
| UX-DR29 | E7 |
| UX-DR30 | E0-Access (roles/invite) + E7 (PC link) |
| UX-DR31 | E8 |
| UX-DR32 | E9 |

## Epic List

19 epics, about 104 stories. Phase 0 = foundations and privacy (now including the World Model core, D-1c). Phase 1 = World Model extraction and independent quick wins. Phase 2 = dependents. "Owns" restates the spine boundary map; shared append points (spine) may be touched by any epic, a line at a time.

### Epic E0a: Share Links stop leaking GM content (P0 hotfix)

Owners who share a read-only link can trust it: anonymous viewers no longer see Shorthand, NPC or Quest notes, or Secrets. Ships first and on its own, before any other work.

- **Requirements:** FR-9(a); AR-26 (share part); EV-4 seed test for share routes (field-by-field).
- **Phase:** 0 (first, independent release).
- **Owns:** `api/routes/share.py`, share response schemas; frontend `SharedCampaignPage.tsx`. Tables: none.
- **Depends on:** none.
- **Stories (est.):** 2 (share-specific schemas + field-by-field test; release notes and frontend adjustments).

### Epic E0-QA: Trustworthy tests, CI gates and evaluation harness

The owner and capstone reviewers can trust every merge: tests build the schema from migrations against the dev Postgres, CI runs on `main` and every PR, the licence gate protects the commercial build, the EV-4 spoiler suite exists as a hard gate, and benchmarks and the demo seed are reproducible.

- **Requirements:** NFR-4, NFR-5 (EV-4 harness), NFR-6 (EV-5 harness), NFR-8 (migration-chain tests), AR-21, AR-22, AR-27, CI-1 to CI-15 (harness and workflows), SPIKE-1/SPIKE-2 x86 re-run, EV-4, EV-5, demo seed, LIC-1 register entries, D-7 Pages workflow cleanup (conditional).
- **Phase:** 0 (substrate first; EV-4 grows with every epic).
- **Owns:** `tests/conftest.py`, `tests/ev4/` harness, CI workflows, import-linter config, `licenses/`, `seeds/`, `scripts/seed_demo.py`, `docs/BENCHMARKS.md`, `docs/SPOILER_EVAL.md`. Tables: none.
- **Depends on:** none to start; EV-4 probe families for access need E0-Access contracts (stub-first).
- **Stories (est.):** 7 (test substrate via Alembic + fakes; CI on main + migration-chain gates; import-linter + model-package + boundary-map + enum gates; licence register and scans; EV-4 harness and route enumeration; demo seed and EV-5 benchmark suite incl. x86 spike re-run; Pages workflow consolidation).

### Epic E0-Platform: Runs offline on one 16 GB box with models outside the web tier

A self-hoster brings the whole stack up with one command, offline, inside 16 GB, and the web tier no longer loads ML models per worker.

- **Requirements:** NFR-1, NFR-2 (16 GB, D-1a), NFR-3, NFR-8 (rate-limit keying, D-5), AR-1, AR-6, AR-7, AR-20, AR-25, SPIKE-5.
- **Phase:** 0.
- **Owns:** `app/clients/*`, `src/services/ml`, `src/services/stt`, compose files, `.env.example` limits, `docker-compose.gpu.yml`, buildx, `scripts/deploy-oci.sh`, async refactor of `nlp_service`/`embedding_service`/`transcription_service`/`vision_service`, `domain/embedding.py`, `core/limiter.py` (`user_or_ip`), nginx `ai_gen` keying. Tables: none.
- **Depends on:** none (E0-QA CI gates soft).
- **Stories (est.):** 6 (`ml` sidecar + client; `stt` sidecar + `/api/ingest/voice` switch; async wrapper refactor and lifespan cleanup; single-profile compose, limits and GPU override; per-user rate-limit keying and nginx; SPIKE-5 memory verification, multi-arch build and OCI deploy).

### Epic E0-Access: Roles and one Visibility enforcement point

The Owner can invite Players with confidence: Members have Roles, every read, write response, search and AI context is filtered by one enforcement point, and chat and search no longer leak Shorthand.

- **Requirements:** FR-7, FR-8, FR-9(b), FR-10, FR-41 (`set_visibility` backend), FR-43 (Player-scoped retrieval), FR-44 (invite/role/remove part, D-4), NFR-5, NFR-7 (`SourceRef`, `grounded`), AR-12, AR-13, AR-18 (members), AR-19 F1-core, AR-26, UX-DR30 (roles part).
- **Phase:** 0 (FR-9(b) in the same release as FR-7).
- **Owns:** `app/access/*`, `api/deps.py`, `schemas/sources.py`, `api/routes/members.py`, `api/routes/events.py`, retrieval and chat ctx refactor (`retrieval_service`, `source_service`, `chat.py`, `chat_service`), `campaigns.py` analytics/export scope, Player route lockout, `scripts/check_scoped_queries.py`; frontend `hooks/useCampaignRole.ts`, `hooks/useCampaignEvents.ts`, roles in `SharingPage.tsx`. Tables: F1-core revision (enums; role/visibility/kind/party/`access_epoch` columns; `chat_sessions.archived_at`, `npc_entity_id`; `journal_tags.source_field`; `character_sheets.pc_entity_id`; `entry_hash` uniqueness).
- **Depends on:** E0a; E0-QA substrate; E0-Platform `ml` client for `party_embedding` (soft: may queue `journal.reembed`).
- **Stories (est.):** 8 (F1-core migration + members → Player; access package core and registry; Party schemas and uniform 404 across existing routes; role map replacing `accessible_campaign_ids` + scoped-query ratchet; Player lockout of GM authoring/AI routes and write rules; Party-only retrieval/chat/search with `party_tsv`/`party_embedding` (FR-9b); grant changes, `access_epoch`, stream close and events route; members/roles API and Sharing UI + analytics/export scope).

### Epic E0-Jobs: Background Jobs with visible progress

GMs and Players never wait on a blocked request: long work runs as Jobs that survive restarts, report stage, progress and ETA within 5 s, and can be retried; files are stored and served safely.

- **Requirements:** FR-1, FR-2, NFR-9, NFR-11, AR-2, AR-3, AR-4, AR-5, AR-14, AR-19 F2-jobs-files, UX-DR14.
- **Phase:** 0.
- **Owns:** `app/jobs/*` (core, admission), `api/routes/jobs.py`, `api/routes/files.py`, `core/sse.py`, `core/pubsub.py`, `services/file_service.py`, worker compose service; frontend `lib/sse.ts`, `hooks/useJobStream.ts`, Job tray UI. Tables: `jobs`, `data_backfills`, `stored_files`, `derived_sources`.
- **Depends on:** E0-Access (ctx, F1-core precedes F2), E0-UX (Toast, tray primitives; soft).
- **Stories (est.):** 6 (F2 migration + enqueue/outbox/registry; worker wrapper, retries, heartbeats, reaper; queues, priority, cursor backfills, Live admission lease; job routes, pubsub channels and SSE; file service, file route, `X-Accel-Redirect`, backups doc; `lib/sse.ts` + `useChat` migration + Job tray and completion notices).

### Epic E0-LLM: Reliable, prioritised local-LLM access with structured output

AI features get schema-valid answers from the local model without starving each other: one priority gate, one local model, prompt budgets, typed errors, and a deterministic fake for CI.

- **Requirements:** FR-3, NFR-8 (BYOK, metering), AR-8, SPIKE-6.
- **Phase:** 0.
- **Owns:** `llm_provider.py` (gate use, `model_for`, `detect_backend`, `complete_structured`, fake provider, EV-4 capture hook), `core/llm_gate.py`, `core/errors.py`, `services/llm_config_service.py`, `services/prompt_budget.py`, `schemas/llm/__init__.py`. Tables: none.
- **Depends on:** none hard (E0-Access ctx for the capture hook, soft).
- **Stories (est.):** 5 (LLM gate and fixed local model; `llm_config_service` and typed errors; `complete_structured` with repair and flat-schema test; `prompt_budget` and `detect_backend`; fake provider + capture hook + SPIKE-6 throughput benchmark).

### Epic E0-Journal: Edit and delete Journal Entries safely

A GM or author can correct a Journal Entry after saving. Search, tags and retrieval follow the edit, and every feature reacts through hooks rather than editing the journal code.

- **Requirements:** FR-6, NFR-9, AR-17, UX-DR22 (Edit button, VisibilityBadge on entry detail).
- **Phase:** 0.
- **Owns:** `journal_service` writers (`create`, `update`, `delete`, `reindex`), `api/routes/journals.py` (PUT, delete), `app/hooks/__init__.py` dispatcher; frontend entry edit UI in `EntryDetailPage.tsx`. Tables: none (columns come from F1-core).
- **Depends on:** E0-Access (columns, `can_write`), E0-Platform (`ml` embeddings), E0-Jobs (`journal.reembed`).
- **Stories (est.):** 4 (journal writers + index-column recompute; `after_commit` hook dispatcher and events; edit/delete routes with Player rules and delete contract; entry edit UI).

### Epic E0-UX: A consistent, accessible app shell for the expansion

Every user gets an app that looks like it was always this way and is usable by keyboard and screen reader: semantic colour tokens fix the contrast defects, the SlideOver traps focus, reduced motion is respected, new primitives exist, and the shell knows the current Campaign and Role.

- **Requirements:** NFR-10, UX-DR1 to UX-DR13 (incl. defects UX-DR2 destructive contrast, UX-DR3 ~50 hardcoded colours, UX-DR4 SlideOver focus trap), CI-15.
- **Phase:** 0.
- **Owns (added, D-3):** `types/theme.ts`, `themes/*.ts`, `tailwind.config.ts`, `index.css` (reduced motion), `components/ui/*` (new SegmentedControl, Tabs, Combobox, Toast, EmptyState, ModelMissingNotice, VisibilityBadge, SecretField, RoleBadge), `components/SlideOver.tsx`, `components/NavBar.tsx` shell (CampaignSwitcher, nav groups restructure, redirects), not-found page, shortcut help overlay. Tables: none.
- **Depends on:** E0-Access `useCampaignRole` for CampaignSwitcher roles (soft; stub until available).
- **Stories (est.):** 6 (semantic tokens in all themes + danger/destructive fix; hardcoded colour migration + CI grep check; SlideOver focus trap, wide variant, push header + reduced-motion CSS; primitives SegmentedControl/Tabs/Combobox + Toast + EmptyState/ModelMissingNotice; spoiler-safety components VisibilityBadge/SecretField/RoleBadge/PreviewBanner shell; CampaignSwitcher, global current Campaign, nav restructure and redirects, unified not-found, route announcements).

### Epic E0-WorldCore: The world as Campaign-scoped Entities with history

A GM's existing NPCs and Quests become a real World Model of Characters, Locations, Factions, Items and Quests, each with a wiki page, aliases, status, history with revert, and merge. It is published to Players deliberately.

- **Requirements:** FR-4, FR-5, FR-11, FR-16, FR-17, FR-12 (tables, suggested Mentions), FR-14 (`match_names`), AR-9, AR-10, AR-18 (legacy copy, adapters), AR-19 F3-world, UX-DR19, UX-DR20, UX-DR21.
- **Phase:** 0 (D-1c).
- **Owns:** `world_service.py`, `domain/entity_types.py`, `domain/enums.py`, `api/routes/entities.py`, legacy `npcs.py`/`quests.py` adapters; frontend `components/entities/*` (EntityDetailPanel, `panelSections.ts`), entity list pages, World hub `/world`. Tables (F3-world): `entities`, `entity_aliases`, `entity_mentions`, `relationship_types`, `entity_relationships`, `quest_steps`, `entity_changes` (+ legacy copy).
- **Depends on:** E0-Access, E0-Jobs (F2 precedes F3; `backfill.mentions`), E0-Journal (delete contract), E0-UX (panel primitives).
- **Stories (est.):** 8 (F3-world migration + legacy copy; entity type registry and enums; `apply_change` + history + revert; Entity API with GM/Party projection; legacy adapters + redirects; suggested-Mention backfill + Mention confirm/remove; merge; World hub, Entity page/panel, bulk publish callout).

### Epic E1: The journal updates the world (extraction and Review Checklist)

After saving her notes, the GM gets a short grouped Review Checklist of proposed world changes and applies the ones she approves. Nothing becomes Canon without her.

- **Requirements:** FR-12, FR-13, FR-14, FR-15, FR-18, FR-6 (supersede and re-queue handler), FR-55 (renderer slot), NFR-6 (extraction row), NFR-7, NFR-10 (keyboard checklist), AR-11 (proposals), EV-1, DS-1, UX-DR15 to UX-DR18, UX-DR22 (Mentions strip).
- **Phase:** 1.
- **Owns:** `extraction_service.py`, `jobs/extraction.py`, `hooks/extraction.py`, `api/routes/proposals.py`, `schemas/proposals.py`, `schemas/llm/extraction.py`; frontend `components/review/*` (ReviewChecklist, `itemRenderers.ts`), `hooks/useProposals.ts`, post-save hook-in in `JournalInput.tsx`, Reviews queue. Tables: `proposal_batches`, `change_proposals`.
- **Depends on:** E0-WorldCore, E0-LLM, E0-Jobs, E0-Journal, E0-UX.
- **Stories (est.):** 7 (proposal tables and schemas; extraction Job with Entity shortlist and matching; Visibility-follows-evidence defaults; Review Checklist core UI and staging; apply with stale/merge re-check and Undo; post-save card, Reviews queue, re-run and backfill; EV-1 eval and DS-1).

### Epic E2: Canon guard catches continuity mistakes

The GM is warned, with both quotes, when an entry contradicts Canon, and can dismiss the flag or record a Canon Note that later checks and the Chronicler respect.

- **Requirements:** FR-19, FR-20, FR-21, FR-22, NFR-6 (continuity row), NFR-7, AR-11 (flags, Canon Notes), EV-2, DS-2, UX-DR23, SPIKE-1 decision (xsmall vs base).
- **Phase:** 2.
- **Owns:** `continuity_service.py`, `jobs/continuity.py`, `hooks/continuity.py`, `api/routes/continuity.py`, `schemas/llm/continuity.py`, Canon Note retrieval source; frontend `flag` renderer, entity panel section, entry-detail flag. Tables: `continuity_flags`, `canon_notes`, `canon_note_entities`.
- **Depends on:** E1 (proposals, checklist, extraction Job ordering), E0-Platform (`ml /v1/nli`), E0-LLM.
- **Stories (est.):** 5 (tables and Canon Note retrieval source; continuity Job: candidate pairs, NLI, LLM verify, conflict_key; flag display, dismiss, best-effort copy; override with Canon Note and offered proposal; marked proposals + EV-2 + DS-2).

### Epic E3: See the relationship web

GMs and Players explore who is allied with, opposed to or carrying what, through an interactive graph or an equivalent list, with Players seeing only Party content.

- **Requirements:** FR-23, FR-24, FR-25, NFR-10, UX-DR24.
- **Phase:** 2 (can start after Phase 0, D-10).
- **Owns:** `api/routes/graph.py`, `api/routes/relationship_types.py`; frontend `pages/RelationshipWebPage.tsx`, `components/graph/*`, relationships panel section. Tables: none (`entity_relationships`, `relationship_types` owned by E0-WorldCore; writes via `apply_change`).
- **Depends on:** E0-WorldCore, E0-Access; E1 soft (approved Relationships appear live).
- **Stories (est.):** 4 (relationship types and Relationship CRUD via `apply_change`; graph endpoint with access filtering + EV-4 probe; graph canvas, toolbar, legend and persisted layout; list view, keyboard navigation and performance check).

### Epic E4: Live Session at the table

During play the GM gets chunked captions, a Rolling Recap and two-second Entity lookup on a tablet, and turns the session into a draft entry at the end.

- **Requirements:** FR-26, FR-27, FR-28, FR-29, FR-30, NFR-6 (caption, recap, lookup rows), NFR-2 (Live case), AR-15, AR-3 (Live admission use), SPIKE-4, EV-6 (Rolling), SM-7, DS-4 (first half), UX-DR26.
- **Phase:** 2 (can move earlier, PRD §9).
- **Owns:** `api/ws/live.py`, `live_session_service.py`, `jobs/live.py`, `jobs/diarize.py`, diarize profile; frontend `pages/LiveSessionPage.tsx`, `lib/liveSocket.ts`, AudioWorklet. Tables: `live_sessions`, `live_chunks`, `live_segments`.
- **Depends on:** E0-Jobs (admission lease), E0-Platform (`stt`), E0-LLM (`live_recap` gate), E0-Journal (draft hand-off); E0-WorldCore soft (lookup; legacy NPC fallback otherwise).
- **Stories (est.):** 7 (live tables + WS auth and chunk ingest; drainer, STT, captions, backlog; reconnect and resume; Rolling Recap Job; quick lookup and Chronicler question; end-of-session draft and audio deletion; diarization spike + optional Job, Table view verification).

### Epic E5: "Previously on…" narrated recaps

The GM opens a Session with a genre-voiced recap she has reviewed, narrated locally (AGPL build) or read by the browser (commercial build), and Players can replay Party recaps.

- **Requirements:** FR-31, FR-32, FR-33, FR-34, NFR-4 (TTS edition rule), NFR-6 (narration row), NFR-10 (text with audio), AR-16, SPIKE-3, LIC-1, EV-6 (Narrated), DS-5 (recap part), UX-DR27.
- **Phase:** 1.
- **Owns:** `tts_service.py`, `clients/tts.py` usage, `api/routes/recaps.py`, `jobs/recap.py`, `domain/narrators.py`, tts compose service (AGPL profile); frontend recap player, Keepsakes › Previously on tab. Tables: `recaps`.
- **Depends on:** E0-Jobs (Jobs, files, derived sources), E0-LLM, E0-Access (derived audience).
- **Stories (est.):** 5 (recap text draft-then-save with citations; `TTSProvider` interface, editions and `none` browser fallback; Kokoro sidecar, presets and sentence synthesis; narration Job, cache and invalidation, audio route; RecapPlayer, Table play, EV-6).

### Epic E6: Talk to an NPC

The GM preps by interviewing an NPC who answers in character from what it plausibly knows and says "I don't know" otherwise; the GM can enable this for Players per NPC.

- **Requirements:** FR-35, FR-36, FR-37, FR-38, FR-39, NFR-6 (first token), NFR-7, AR-11 (NPC Knowledge), EV-3, DS-4 (second half), UX-DR28.
- **Phase:** 2.
- **Owns:** `npc_chat_service.py`, `api/routes/npc_chat.py` (SSE), `entry_ids` filter on `hybrid_search_journal` (reviewed by E0-Access); frontend `hooks/useNpcChat.ts`, NPC mode in `ChatPage.tsx`, "Talk to" panel section, KnowledgeEditor. Tables: `npc_knowledge`, `npc_settings`.
- **Depends on:** E0-WorldCore (confirmed Mentions), E0-Access (retrieval ctx), E0-LLM; E1 soft (more confirmed Mentions).
- **Stories (est.):** 5 (knowledge tables and computed knowledge set; NPC chat streaming with persona and re-injected grounding; refusal label, citations, copy-to-draft; KnowledgeEditor grant/hide; Player NPC Conversations + EV-3).

### Epic E7: Player Portal

Players catch up between Sessions on their phones: a spoiler-safe wiki, their character's story, their own private journal and a Chronicler limited to what they may see. GMs publish deliberately and preview exactly what Players see.

- **Requirements:** FR-40, FR-41 (bulk controls and preview UI), FR-42, FR-43 (Player chat surface), FR-44 (PC link, "my character", D-4), FR-34 (Portal placement), NFR-5, NFR-6 (portal load), NFR-10, EV-4 probes, DS-3, UX-DR29, UX-DR30 (PC link).
- **Phase:** 2.
- **Owns:** `api/routes/portal.py`, `api/routes/player_journals.py`; frontend `pages/PortalPage.tsx`, "my character", GM preview (`audience_ctx`), bulk visibility controls (`set_visibility`). Tables: none.
- **Depends on:** E0-Access, E0-WorldCore, E0-UX (PreviewBanner shell); E1 soft (PRD lists F1). Optional sections appear when E3, E5, E10 exist.
- **Stories (est.):** 6 (Portal home and Party wiki at 375 px; my character and PC link; Player Journals; Player Chronicler surface; GM bulk visibility and derived invalidation UI; Preview as Player + DS-3).

### Epic E8: Campaign Chronicle export

At the end of an arc, the group gets the Campaign as a well-typeset PDF and a valid EPUB, in a GM edition or a spoiler-safe Player edition.

- **Requirements:** FR-45, FR-46, FR-47, FR-48, FR-10 (export scope used), NFR-4 (WeasyPrint, OFL font), NFR-6 (export row), DS-5 (book part), UX-DR31.
- **Phase:** 1.
- **Owns:** `chronicle_service.py` (extends `export_service`), `jobs/chronicle.py`, `api/routes/chronicle.py`, templates, OFL font; frontend export UI (Keepsakes › Chronicle tab). Tables: none (outputs are `stored_files` + `derived_sources`).
- **Depends on:** E0-Jobs (Jobs, files), E0-Access (`audience_ctx(member)`); E0-WorldCore soft (appendix).
- **Stories (est.):** 4 (Jinja book model + WeasyPrint PDF with Unicode font; EPUB3 writer + EPUBCheck; export Job, editions, download, staleness; export panel UI).

### Epic E9: Milestones and stats

Members see the Campaign's story in numbers and celebrate Milestones and opt-in Achievements, never nagged and never shown counts that hint at hidden content.

- **Requirements:** FR-49, FR-50, FR-51, FR-10, DS-5 (milestone part), UX-DR32.
- **Phase:** 1.
- **Owns:** `achievement_service.py`, `domain/achievements.py`, `hooks/stats.py`, `api/routes/stats.py`; frontend `AnalyticsPage.tsx` → Stats. Tables: `activity_events`, `user_achievements`, `user_settings.streaks_enabled`.
- **Depends on:** E0-Access (per-recipient ctx), E0-Journal (hooks); E0-WorldCore soft (Mentions; tags before).
- **Stories (est.):** 4 (activity events + stats API scoped per audience; Achievements and Milestones rules, idempotent awards; streaks with grace + opt-in settings; Stats page, MilestoneCard, AchievementBadge).

### Epic E10: Maps and pins

The GM uploads Maps and pins Locations and entries to them; Players explore Party Maps without any trace of GM-only Pins.

- **Requirements:** FR-52, FR-53, FR-54, FR-55, NFR-2 (tiling memory, SPIKE-5 input), NFR-10, AR-14 (tiles), UX-DR25.
- **Phase:** 2 (can start after Phase 0, D-10).
- **Owns:** `map_service.py`, `jobs/maps.py`, `api/routes/maps.py`; frontend `pages/MapsPage.tsx`, `components/map/*`, `lib/mapCoords.ts`, pins panel section, FR-55 renderer. Tables: `maps`, `map_pins`, `map_pin_entries`.
- **Depends on:** E0-Jobs (files, `maps.tile`), E0-WorldCore (Location); E1 for FR-55 only.
- **Stories (est.):** 5 (map tables, upload validation, storage; pyvips tiling Job and tile route; pins CRUD with normalized coordinates and Visibility rules + EV-4 probe; MapViewer, placement, PinEditor, PinList, keyboard; Location integration and FR-55 offer).

<!-- Stories per epic are written in step 3 by parallel batch agents (see epics-parallel-plan.md) and merged under these headings using the template's "## Epic {{N}}" / "### Story {{N}}.{{M}}" format, with N = the epic id. -->
