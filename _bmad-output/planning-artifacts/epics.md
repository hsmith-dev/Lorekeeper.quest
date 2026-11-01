---
status: final
stepsCompleted: [1, 2, 3, 4]
workflow: bmad-create-epics-and-stories
mode: autonomous (owner pre-approved; step menus decided by agent, see Decisions)
created: 2026-10-31
updated: 2026-10-31
validation: _bmad-output/planning-artifacts/epics-validation-report.md
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-Lorekeeper.quest-2026-10-31/prd.md
  - _bmad-output/planning-artifacts/prds/prd-Lorekeeper.quest-2026-10-31/addendum.md
  - _bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-Lorekeeper.quest-2026-10-31/EXPERIENCE.md
  - _bmad-output/planning-artifacts/brownfield-context.md
  - _bmad-output/planning-artifacts/spikes/cpu-benchmarks.md
  - _bmad-output/planning-artifacts/scope-input.md
  - _bmad-output/planning-artifacts/epic-stories/B1.md … B6.md (step 3 batch outputs, kept for provenance)
companions:
  - _bmad-output/planning-artifacts/epics-parallel-plan.md
  - _bmad-output/planning-artifacts/build-waves.md
  - _bmad-output/planning-artifacts/epics-validation-report.md
epicCount: 19
estimatedStories: 104
storyCount: 155  # 154 batch stories + 1 optional (E0-Access.14, pending owner decision OD-1)
---

# Lorekeeper.quest - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Lorekeeper.quest, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

All four steps are complete. Stories (step 3) were written by six parallel batch agents per `epics-parallel-plan.md` (`epic-stories/B1.md` to `B6.md`, kept unchanged for provenance) and merged here under their epics, with every cross-batch contract reconciled (see "Cross-batch contract reconciliation" at the end). Step 4 validation is in `epics-validation-report.md`, and the parallel build order is in `build-waves.md`. Terms follow PRD §3 exactly. Epic ids follow the ARCHITECTURE-SPINE boundary map (`E0a`, `E0-*`, `E1`–`E10`) plus one added epic (`E0-UX`); story ids are `<epic>.<n>` (for example `E1.3`, `E0-Access.2`).

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
- **D-11 Merge (step 3).** Stories keep the batch format: the template's user story and Given/When/Then ACs, followed by `Covers`, `Technical notes`, `Dependencies` and `Size`. Epic headings use `## Epic <id>` and story headings `### Story <id>.<n>`, with N = the epic id (as planned above). Each batch's Decisions remain authoritative where this document doesn't override them (B1-D*, B2 1–16, B3-D*, B4-D*, B5 1–16, B6-*).
- **D-12 Dependencies are story ids.** Every Dependencies line names real story ids. Text after "Soft:" is a soft dependency (the story works without it) and isn't an ordering edge. Story-level dependencies are the authority for build order; they amend the epic DAG with A-1 to A-3 (see reconciliation).
- **D-13 Owner gaps are closed in the owning story.** Where a dependent assumed a capability that the owner batch lacked, the merge added an AC to the owning story (tagged `Reconciliation RC-n`) instead of a new story. The only new story is the optional E0-Access.14 (OD-1).
- **D-14 Step 4 closes without a menu.** All validation checks pass (`epics-validation-report.md`), so the autonomous run chose [C] and set `status: final`. OD-1 stays open for the owner and doesn't block implementation, because option A is the default and option B is a drop-in story.
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
- SPIKE-6 LLM throughput (R-6): not run (Ollama unavailable). Prompt and generation tokens/s per prompt shape with Entity lists of 50 and 300; decides extraction shortlist vs full list. Measured once in E0-Platform.10 on the x86 desktop; E0-LLM.6 consumes the results, feeding E1.
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
| AR-8 | E0-LLM |
| SPIKE-6 | E0-Platform (measured once in E0-Platform.10) + E0-LLM (E0-LLM.6 consumes the results) |
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

19 epics, 155 stories (154 from the batches plus one optional story pending owner decision OD-1; the estimate was about 104). Phase 0 = foundations and privacy (now including the World Model core, D-1c). Phase 1 = World Model extraction and independent quick wins. Phase 2 = dependents. "Owns" restates the spine boundary map; shared append points (spine) may be touched by any epic, a line at a time.

### Epic E0a: Share Links stop leaking GM content (P0 hotfix)

Owners who share a read-only link can trust it: anonymous viewers no longer see Shorthand, NPC or Quest notes, or Secrets. Ships first and on its own, before any other work.

- **Requirements:** FR-9(a); AR-26 (share part); EV-4 seed test for share routes (field-by-field).
- **Phase:** 0 (first, independent release).
- **Owns:** `api/routes/share.py`, share response schemas; frontend `SharedCampaignPage.tsx`. Tables: none.
- **Depends on:** none.
- **Stories (est.):** 2 (share-specific schemas + field-by-field test; release notes and frontend adjustments).
- **Stories (final):** 2 (`E0a.1` to `E0a.2`).

### Epic E0-QA: Trustworthy tests, CI gates and evaluation harness

The owner and capstone reviewers can trust every merge: tests build the schema from migrations against the dev Postgres, CI runs on `main` and every PR, the licence gate protects the commercial build, the EV-4 spoiler suite exists as a hard gate, and benchmarks and the demo seed are reproducible.

- **Requirements:** NFR-4, NFR-5 (EV-4 harness), NFR-6 (EV-5 harness), NFR-8 (migration-chain tests), AR-21, AR-22, AR-27, CI-1 to CI-15 (harness and workflows), SPIKE-1/SPIKE-2 x86 re-run, EV-4, EV-5, demo seed, LIC-1 register entries, D-7 Pages workflow cleanup (conditional).
- **Phase:** 0 (substrate first; EV-4 grows with every epic).
- **Owns:** `tests/conftest.py`, `tests/ev4/` harness, CI workflows, import-linter config, `licenses/`, `seeds/`, `scripts/seed_demo.py`, `docs/BENCHMARKS.md`, `docs/SPOILER_EVAL.md`. Tables: none.
- **Depends on:** none to start; EV-4 probe families for access need E0-Access contracts (stub-first).
- **Stories (est.):** 7 (test substrate via Alembic + fakes; CI on main + migration-chain gates; import-linter + model-package + boundary-map + enum gates; licence register and scans; EV-4 harness and route enumeration; demo seed and EV-5 benchmark suite incl. x86 spike re-run; Pages workflow consolidation).
- **Stories (final):** 15 (`E0-QA.1` to `E0-QA.15`).

### Epic E0-Platform: Runs offline on one 16 GB box with models outside the web tier

A self-hoster brings the whole stack up with one command, offline, inside 16 GB, and the web tier no longer loads ML models per worker.

- **Requirements:** NFR-1, NFR-2 (16 GB, D-1a), NFR-3, NFR-8 (rate-limit keying, D-5), AR-1, AR-6, AR-7, AR-20, AR-25, SPIKE-5.
- **Phase:** 0.
- **Owns:** `app/clients/*`, `src/services/ml`, `src/services/stt`, compose files, `.env.example` limits, `docker-compose.gpu.yml`, buildx, `scripts/deploy-oci.sh`, async refactor of `nlp_service`/`embedding_service`/`transcription_service`/`vision_service`, `domain/embedding.py`, `core/limiter.py` (`user_or_ip`), nginx `ai_gen` keying. Tables: none.
- **Depends on:** none (E0-QA CI gates soft).
- **Stories (est.):** 6 (`ml` sidecar + client; `stt` sidecar + `/api/ingest/voice` switch; async wrapper refactor and lifespan cleanup; single-profile compose, limits and GPU override; per-user rate-limit keying and nginx; SPIKE-5 memory verification, multi-arch build and OCI deploy).
- **Stories (final):** 10 (`E0-Platform.1` to `E0-Platform.10`).

### Epic E0-Access: Roles and one Visibility enforcement point

The Owner can invite Players with confidence: Members have Roles, every read, write response, search and AI context is filtered by one enforcement point, and chat and search no longer leak Shorthand.

- **Requirements:** FR-7, FR-8, FR-9(b), FR-10, FR-41 (`set_visibility` backend), FR-43 (Player-scoped retrieval), FR-44 (invite/role/remove part, D-4), NFR-5, NFR-7 (`SourceRef`, `grounded`), AR-12, AR-13, AR-18 (members), AR-19 F1-core, AR-26, UX-DR30 (roles part).
- **Phase:** 0 (FR-9(b) in the same release as FR-7).
- **Owns:** `app/access/*`, `api/deps.py`, `schemas/sources.py`, `api/routes/members.py`, `api/routes/events.py`, retrieval and chat ctx refactor (`retrieval_service`, `source_service`, `chat.py`, `chat_service`), `campaigns.py` analytics/export scope, Player route lockout, `scripts/check_scoped_queries.py`; frontend `hooks/useCampaignRole.ts`, `hooks/useCampaignEvents.ts`, roles in `SharingPage.tsx`. Tables: F1-core revision (enums; role/visibility/kind/party/`access_epoch` columns; `chat_sessions.archived_at`, `npc_entity_id`; `journal_tags.source_field`; `character_sheets.pc_entity_id`; `entry_hash` uniqueness).
- **Depends on:** E0a; E0-QA substrate; E0-Platform `ml` client for `party_embedding` (soft: may queue `journal.reembed`).
- **Stories (est.):** 8 (F1-core migration + members → Player; access package core and registry; Party schemas and uniform 404 across existing routes; role map replacing `accessible_campaign_ids` + scoped-query ratchet; Player lockout of GM authoring/AI routes and write rules; Party-only retrieval/chat/search with `party_tsv`/`party_embedding` (FR-9b); grant changes, `access_epoch`, stream close and events route; members/roles API and Sharing UI + analytics/export scope).
- **Stories (final):** 14 (`E0-Access.1` to `E0-Access.14`; `E0-Access.14` is optional, pending OD-1).

### Epic E0-Jobs: Background Jobs with visible progress

GMs and Players never wait on a blocked request: long work runs as Jobs that survive restarts, report stage, progress and ETA within 5 s, and can be retried; files are stored and served safely.

- **Requirements:** FR-1, FR-2, NFR-9, NFR-11, AR-2, AR-3, AR-4, AR-5, AR-14, AR-19 F2-jobs-files, UX-DR14.
- **Phase:** 0.
- **Owns:** `app/jobs/*` (core, admission), `api/routes/jobs.py`, `api/routes/files.py`, `core/sse.py`, `core/pubsub.py`, `services/file_service.py`, worker compose service; frontend `lib/sse.ts`, `hooks/useJobStream.ts`, Job tray UI. Tables: `jobs`, `data_backfills`, `stored_files`, `derived_sources`.
- **Depends on:** E0-Access (ctx, F1-core precedes F2), E0-UX (Toast, tray primitives; soft).
- **Stories (est.):** 6 (F2 migration + enqueue/outbox/registry; worker wrapper, retries, heartbeats, reaper; queues, priority, cursor backfills, Live admission lease; job routes, pubsub channels and SSE; file service, file route, `X-Accel-Redirect`, backups doc; `lib/sse.ts` + `useChat` migration + Job tray and completion notices).
- **Stories (final):** 10 (`E0-Jobs.1` to `E0-Jobs.10`).

### Epic E0-LLM: Reliable, prioritised local-LLM access with structured output

AI features get schema-valid answers from the local model without starving each other: one priority gate, one local model, prompt budgets, typed errors, and a deterministic fake for CI.

- **Requirements:** FR-3, NFR-8 (BYOK, metering), AR-8, SPIKE-6.
- **Phase:** 0.
- **Owns:** `llm_provider.py` (gate use, `model_for`, `detect_backend`, `complete_structured`, fake provider, EV-4 capture hook), `core/llm_gate.py`, `core/errors.py`, `services/llm_config_service.py`, `services/prompt_budget.py`, `schemas/llm/__init__.py`. Tables: none.
- **Depends on:** none hard (E0-Access ctx for the capture hook, soft).
- **Stories (est.):** 5 (LLM gate and fixed local model; `llm_config_service` and typed errors; `complete_structured` with repair and flat-schema test; `prompt_budget` and `detect_backend`; fake provider + capture hook; acting on the SPIKE-6 results that E0-Platform.10 measures).
- **Stories (final):** 6 (`E0-LLM.1` to `E0-LLM.6`).

### Epic E0-Journal: Edit and delete Journal Entries safely

A GM or author can correct a Journal Entry after saving. Search, tags and retrieval follow the edit, and every feature reacts through hooks rather than editing the journal code.

- **Requirements:** FR-6, NFR-9, AR-17, UX-DR22 (Edit button, VisibilityBadge on entry detail).
- **Phase:** 0.
- **Owns:** `journal_service` writers (`create`, `update`, `delete`, `reindex`), `api/routes/journals.py` (PUT, delete), `app/hooks/__init__.py` dispatcher; frontend entry edit UI in `EntryDetailPage.tsx`. Tables: none (columns come from F1-core).
- **Depends on:** E0-Access (columns, `can_write`), E0-Platform (`ml` embeddings), E0-Jobs (`journal.reembed`).
- **Stories (est.):** 4 (journal writers + index-column recompute; `after_commit` hook dispatcher and events; edit/delete routes with Player rules and delete contract; entry edit UI).
- **Stories (final):** 4 (`E0-Journal.1` to `E0-Journal.4`).

### Epic E0-UX: A consistent, accessible app shell for the expansion

Every user gets an app that looks like it was always this way and is usable by keyboard and screen reader: semantic colour tokens fix the contrast defects, the SlideOver traps focus, reduced motion is respected, new primitives exist, and the shell knows the current Campaign and Role.

- **Requirements:** NFR-10, UX-DR1 to UX-DR13 (incl. defects UX-DR2 destructive contrast, UX-DR3 ~50 hardcoded colours, UX-DR4 SlideOver focus trap), CI-15.
- **Phase:** 0.
- **Owns (added, D-3):** `types/theme.ts`, `themes/*.ts`, `tailwind.config.ts`, `index.css` (reduced motion), `components/ui/*` (new SegmentedControl, Tabs, Combobox, Toast, EmptyState, ModelMissingNotice, VisibilityBadge, SecretField, RoleBadge), `components/SlideOver.tsx`, `components/NavBar.tsx` shell (CampaignSwitcher, nav groups restructure, redirects), not-found page, shortcut help overlay. Tables: none.
- **Depends on:** E0-Access `useCampaignRole` for CampaignSwitcher roles (soft; stub until available).
- **Stories (est.):** 6 (semantic tokens in all themes + danger/destructive fix; hardcoded colour migration + CI grep check; SlideOver focus trap, wide variant, push header + reduced-motion CSS; primitives SegmentedControl/Tabs/Combobox + Toast + EmptyState/ModelMissingNotice; spoiler-safety components VisibilityBadge/SecretField/RoleBadge/PreviewBanner shell; CampaignSwitcher, global current Campaign, nav restructure and redirects, unified not-found, route announcements).
- **Stories (final):** 9 (`E0-UX.1` to `E0-UX.9`).

### Epic E0-WorldCore: The world as Campaign-scoped Entities with history

A GM's existing NPCs and Quests become a real World Model of Characters, Locations, Factions, Items and Quests, each with a wiki page, aliases, status, history with revert, and merge. It is published to Players deliberately.

- **Requirements:** FR-4, FR-5, FR-11, FR-16, FR-17, FR-12 (tables, suggested Mentions), FR-14 (`match_names`), AR-9, AR-10, AR-18 (legacy copy, adapters), AR-19 F3-world, UX-DR19, UX-DR20, UX-DR21.
- **Phase:** 0 (D-1c).
- **Owns:** `world_service.py`, `domain/entity_types.py`, `domain/enums.py`, `api/routes/entities.py`, legacy `npcs.py`/`quests.py` adapters; frontend `components/entities/*` (EntityDetailPanel, `panelSections.ts`), entity list pages, World hub `/world`. Tables (F3-world): `entities`, `entity_aliases`, `entity_mentions`, `relationship_types`, `entity_relationships`, `quest_steps`, `entity_changes` (+ legacy copy).
- **Depends on:** E0-Access, E0-Jobs (F2 precedes F3; `backfill.mentions`), E0-Journal (delete contract), E0-UX (panel primitives).
- **Stories (est.):** 8 (F3-world migration + legacy copy; entity type registry and enums; `apply_change` + history + revert; Entity API with GM/Party projection; legacy adapters + redirects; suggested-Mention backfill + Mention confirm/remove; merge; World hub, Entity page/panel, bulk publish callout).
- **Stories (final):** 11 (`E0-WorldCore.1` to `E0-WorldCore.11`).

### Epic E1: The journal updates the world (extraction and Review Checklist)

After saving her notes, the GM gets a short grouped Review Checklist of proposed world changes and applies the ones she approves. Nothing becomes Canon without her.

- **Requirements:** FR-12, FR-13, FR-14, FR-15, FR-18, FR-6 (supersede and re-queue handler), FR-55 (renderer slot), NFR-6 (extraction row), NFR-7, NFR-10 (keyboard checklist), AR-11 (proposals), EV-1, DS-1, UX-DR15 to UX-DR18, UX-DR22 (Mentions strip).
- **Phase:** 1.
- **Owns:** `extraction_service.py`, `jobs/extraction.py`, `hooks/extraction.py`, `api/routes/proposals.py`, `schemas/proposals.py`, `schemas/llm/extraction.py`; frontend `components/review/*` (ReviewChecklist, `itemRenderers.ts`), `hooks/useProposals.ts`, post-save hook-in in `JournalInput.tsx`, Reviews queue. Tables: `proposal_batches`, `change_proposals`.
- **Depends on:** E0-WorldCore, E0-LLM, E0-Jobs, E0-Journal, E0-UX.
- **Stories (est.):** 7 (proposal tables and schemas; extraction Job with Entity shortlist and matching; Visibility-follows-evidence defaults; Review Checklist core UI and staging; apply with stale/merge re-check and Undo; post-save card, Reviews queue, re-run and backfill; EV-1 eval and DS-1).
- **Stories (final):** 10 (`E1.1` to `E1.10`).

### Epic E2: Canon guard catches continuity mistakes

The GM is warned, with both quotes, when an entry contradicts Canon, and can dismiss the flag or record a Canon Note that later checks and the Chronicler respect.

- **Requirements:** FR-19, FR-20, FR-21, FR-22, NFR-6 (continuity row), NFR-7, AR-11 (flags, Canon Notes), EV-2, DS-2, UX-DR23, SPIKE-1 decision (xsmall vs base).
- **Phase:** 2.
- **Owns:** `continuity_service.py`, `jobs/continuity.py`, `hooks/continuity.py`, `api/routes/continuity.py`, `schemas/llm/continuity.py`, Canon Note retrieval source; frontend `flag` renderer, entity panel section, entry-detail flag. Tables: `continuity_flags`, `canon_notes`, `canon_note_entities`.
- **Depends on:** E1 (proposals, checklist, extraction Job ordering), E0-Platform (`ml /v1/nli`), E0-LLM.
- **Stories (est.):** 5 (tables and Canon Note retrieval source; continuity Job: candidate pairs, NLI, LLM verify, conflict_key; flag display, dismiss, best-effort copy; override with Canon Note and offered proposal; marked proposals + EV-2 + DS-2).
- **Stories (final):** 7 (`E2.1` to `E2.7`).

### Epic E3: See the relationship web

GMs and Players explore who is allied with, opposed to or carrying what, through an interactive graph or an equivalent list, with Players seeing only Party content.

- **Requirements:** FR-23, FR-24, FR-25, NFR-10, UX-DR24.
- **Phase:** 2 (can start after Phase 0, D-10).
- **Owns:** `api/routes/graph.py`, `api/routes/relationship_types.py`; frontend `pages/RelationshipWebPage.tsx`, `components/graph/*`, relationships panel section. Tables: none (`entity_relationships`, `relationship_types` owned by E0-WorldCore; writes via `apply_change`).
- **Depends on:** E0-WorldCore, E0-Access; E1 soft (approved Relationships appear live).
- **Stories (est.):** 4 (relationship types and Relationship CRUD via `apply_change`; graph endpoint with access filtering + EV-4 probe; graph canvas, toolbar, legend and persisted layout; list view, keyboard navigation and performance check).
- **Stories (final):** 6 (`E3.1` to `E3.6`).

### Epic E4: Live Session at the table

During play the GM gets chunked captions, a Rolling Recap and two-second Entity lookup on a tablet, and turns the session into a draft entry at the end.

- **Requirements:** FR-26, FR-27, FR-28, FR-29, FR-30, NFR-6 (caption, recap, lookup rows), NFR-2 (Live case), AR-15, AR-3 (Live admission use), SPIKE-4, EV-6 (Rolling), SM-7, DS-4 (first half), UX-DR26.
- **Phase:** 2 (can move earlier, PRD §9).
- **Owns:** `api/ws/live.py`, `live_session_service.py`, `jobs/live.py`, `jobs/diarize.py`, diarize profile; frontend `pages/LiveSessionPage.tsx`, `lib/liveSocket.ts`, AudioWorklet. Tables: `live_sessions`, `live_chunks`, `live_segments`.
- **Depends on:** E0-Jobs (admission lease), E0-Platform (`stt`), E0-LLM (`live_recap` gate), E0-Journal (draft hand-off); E0-WorldCore soft (lookup; legacy NPC fallback otherwise).
- **Stories (est.):** 7 (live tables + WS auth and chunk ingest; drainer, STT, captions, backlog; reconnect and resume; Rolling Recap Job; quick lookup and Chronicler question; end-of-session draft and audio deletion; diarization spike + optional Job, Table view verification).
- **Stories (final):** 11 (`E4.1` to `E4.11`).

### Epic E5: "Previously on…" narrated recaps

The GM opens a Session with a genre-voiced recap she has reviewed, narrated locally (AGPL build) or read by the browser (commercial build), and Players can replay Party recaps.

- **Requirements:** FR-31, FR-32, FR-33, FR-34, NFR-4 (TTS edition rule), NFR-6 (narration row), NFR-10 (text with audio), AR-16, SPIKE-3, LIC-1, EV-6 (Narrated), DS-5 (recap part), UX-DR27.
- **Phase:** 1.
- **Owns:** `tts_service.py`, `clients/tts.py` usage, `api/routes/recaps.py`, `jobs/recap.py`, `domain/narrators.py`, tts compose service (AGPL profile); frontend recap player, Keepsakes › Previously on tab. Tables: `recaps`.
- **Depends on:** E0-Jobs (Jobs, files, derived sources), E0-LLM, E0-Access (derived audience).
- **Stories (est.):** 5 (recap text draft-then-save with citations; `TTSProvider` interface, editions and `none` browser fallback; Kokoro sidecar, presets and sentence synthesis; narration Job, cache and invalidation, audio route; RecapPlayer, Table play, EV-6).
- **Stories (final):** 7 (`E5.1` to `E5.7`).

### Epic E6: Talk to an NPC

The GM preps by interviewing an NPC who answers in character from what it plausibly knows and says "I don't know" otherwise; the GM can enable this for Players per NPC.

- **Requirements:** FR-35, FR-36, FR-37, FR-38, FR-39, NFR-6 (first token), NFR-7, AR-11 (NPC Knowledge), EV-3, DS-4 (second half), UX-DR28.
- **Phase:** 2.
- **Owns:** `npc_chat_service.py`, `api/routes/npc_chat.py` (SSE), `entry_ids` filter on `hybrid_search_journal` (reviewed by E0-Access); frontend `hooks/useNpcChat.ts`, NPC mode in `ChatPage.tsx`, "Talk to" panel section, KnowledgeEditor. Tables: `npc_knowledge`, `npc_settings`.
- **Depends on:** E0-WorldCore (confirmed Mentions), E0-Access (retrieval ctx), E0-LLM; E1 soft (more confirmed Mentions).
- **Stories (est.):** 5 (knowledge tables and computed knowledge set; NPC chat streaming with persona and re-injected grounding; refusal label, citations, copy-to-draft; KnowledgeEditor grant/hide; Player NPC Conversations + EV-3).
- **Stories (final):** 7 (`E6.1` to `E6.7`).

### Epic E7: Player Portal

Players catch up between Sessions on their phones: a spoiler-safe wiki, their character's story, their own private journal and a Chronicler limited to what they may see. GMs publish deliberately and preview exactly what Players see.

- **Requirements:** FR-40, FR-41 (bulk controls and preview UI), FR-42, FR-43 (Player chat surface), FR-44 (PC link, "my character", D-4), FR-34 (Portal placement), NFR-5, NFR-6 (portal load), NFR-10, EV-4 probes, DS-3, UX-DR29, UX-DR30 (PC link).
- **Phase:** 2.
- **Owns:** `api/routes/portal.py`, `api/routes/player_journals.py`; frontend `pages/PortalPage.tsx`, "my character", GM preview (`audience_ctx`), bulk visibility controls (`set_visibility`). Tables: none.
- **Depends on:** E0-Access, E0-WorldCore, E0-UX (PreviewBanner shell); E1 soft (PRD lists F1). Optional sections appear when E3, E5, E10 exist.
- **Stories (est.):** 6 (Portal home and Party wiki at 375 px; my character and PC link; Player Journals; Player Chronicler surface; GM bulk visibility and derived invalidation UI; Preview as Player + DS-3).
- **Stories (final):** 9 (`E7.1` to `E7.9`).

### Epic E8: Campaign Chronicle export

At the end of an arc, the group gets the Campaign as a well-typeset PDF and a valid EPUB, in a GM edition or a spoiler-safe Player edition.

- **Requirements:** FR-45, FR-46, FR-47, FR-48, FR-10 (export scope used), NFR-4 (WeasyPrint, OFL font), NFR-6 (export row), DS-5 (book part), UX-DR31.
- **Phase:** 1.
- **Owns:** `chronicle_service.py` (extends `export_service`), `jobs/chronicle.py`, `api/routes/chronicle.py`, templates, OFL font; frontend export UI (Keepsakes › Chronicle tab). Tables: none (outputs are `stored_files` + `derived_sources`).
- **Depends on:** E0-Jobs (Jobs, files), E0-Access (`audience_ctx(member)`); E0-WorldCore soft (appendix).
- **Stories (est.):** 4 (Jinja book model + WeasyPrint PDF with Unicode font; EPUB3 writer + EPUBCheck; export Job, editions, download, staleness; export panel UI).
- **Stories (final):** 5 (`E8.1` to `E8.5`).

### Epic E9: Milestones and stats

Members see the Campaign's story in numbers and celebrate Milestones and opt-in Achievements, never nagged and never shown counts that hint at hidden content.

- **Requirements:** FR-49, FR-50, FR-51, FR-10, DS-5 (milestone part), UX-DR32.
- **Phase:** 1.
- **Owns:** `achievement_service.py`, `domain/achievements.py`, `hooks/stats.py`, `api/routes/stats.py`; frontend `AnalyticsPage.tsx` → Stats. Tables: `activity_events`, `user_achievements`, `user_settings.streaks_enabled`.
- **Depends on:** E0-Access (per-recipient ctx), E0-Journal (hooks); E0-WorldCore soft (Mentions; tags before).
- **Stories (est.):** 4 (activity events + stats API scoped per audience; Achievements and Milestones rules, idempotent awards; streaks with grace + opt-in settings; Stats page, MilestoneCard, AchievementBadge).
- **Stories (final):** 5 (`E9.1` to `E9.5`).

### Epic E10: Maps and pins

The GM uploads Maps and pins Locations and entries to them; Players explore Party Maps without any trace of GM-only Pins.

- **Requirements:** FR-52, FR-53, FR-54, FR-55, NFR-2 (tiling memory, SPIKE-5 input), NFR-10, AR-14 (tiles), UX-DR25.
- **Phase:** 2 (can start after Phase 0, D-10).
- **Owns:** `map_service.py`, `jobs/maps.py`, `api/routes/maps.py`; frontend `pages/MapsPage.tsx`, `components/map/*`, `lib/mapCoords.ts`, pins panel section, FR-55 renderer. Tables: `maps`, `map_pins`, `map_pin_entries`.
- **Depends on:** E0-Jobs (files, `maps.tile`), E0-WorldCore (Location); E1 for FR-55 only.
- **Stories (est.):** 5 (map tables, upload validation, storage; pyvips tiling Job and tile route; pins CRUD with normalized coordinates and Visibility rules + EV-4 probe; MapViewer, placement, PinEditor, PinList, keyboard; Location integration and FR-55 offer).
- **Stories (final):** 7 (`E10.1` to `E10.7`).


## Epic E0a: Share Links stop leaking GM content (P0 hotfix)

Owners who share a read-only link can trust it: anonymous viewers no longer see Shorthand, NPC or Quest notes, or Secrets. Most of this shipped in PR #1. The open story finishes FR-9(a): release notes and a strict field allowlist. Link expiry and Role-aware filtering depend on F1-core, so they ship in E0-Access (E0-Access.4 and E0-Access.12), not here. See Decision B1-D3.

**Covers:** FR-9(a), AR-26 (share part), the EV-4 share seed test.

### Story E0a.1: Share Links serve only player-visible fields

**Status:** Done (PR #1, commit `b35f9f4`)

As an Owner who has shared a read-only link,
I want the link's responses to leave out my Shorthand and my NPC and Quest notes,
So that anyone holding the link sees only the player-facing chronicle.

**Acceptance Criteria:**

**Given** a Campaign with a Journal Entry whose Shorthand holds a canary string, and an NPC and a Quest whose `notes` hold it
**When** an anonymous client calls `GET /api/share/{token}/journals`, `/journals/{id}`, `/npcs` and `/quests` with a `read_only` token
**Then** no response contains a `shorthand` or `notes` key, and none contains the canary
**And** a `collaborate` token gets 404 on every content endpoint and can only read the campaign metadata.

**Covers:** FR-9(a), AR-26 (share part).

**Technical notes:** `app/schemas/share.py` (`PublicJournalResponse`, `PublicJournalListResponse`, `PublicNpcResponse`, `PublicQuestResponse`, which are allowlists); `app/api/routes/share.py`; `tests/test_share.py` (3 tests); `tests/conftest.py` (`promo_code` fixture made idempotent). AD-13.

**Dependencies:** none. **Size:** S.

### Story E0a.2: Exact-field share test, frontend Public types and release notes

**Status:** Open

As an Owner upgrading Lorekeeper,
I want release notes that say what my existing read-only links no longer show, and a test that fails if any new field reaches a share response,
So that I understand the change and the leak cannot quietly come back.

**Acceptance Criteria:**

**Given** the share routes from E0a.1
**When** the test suite runs
**Then** `tests/test_share.py` asserts the **exact key set** of each share response (`PublicCampaignResponse`, `PublicJournalResponse` including nested `tags`, `PublicNpcResponse` and `PublicQuestResponse`) against a list written in the test
**And** adding any column to `JournalEntry`, `NpcEntry`, `Quest` or `Tag` leaves those key sets unchanged (the test builds the rows with every column filled).

**Given** `pages/SharedCampaignPage.tsx`, which today types share data as the owner types `JournalListResponse`, `NpcEntry` and `Quest`
**When** the frontend builds
**Then** it uses new `PublicJournal`, `PublicJournalList`, `PublicNpc` and `PublicQuest` types in `types/index.ts` that match the backend schemas exactly
**And** `tsc` strict fails if the share page reads `shorthand` or `notes`.

**Given** the next release
**When** an Owner reads the release notes (`docs/RELEASE_NOTES.md`, new, with a link from `README.md`)
**Then** an entry says that read-only Share Links no longer show Shorthand or NPC/Quest notes, that collaborate links were never readable, and that links already issued keep working.

**Covers:** FR-9(a) (field-by-field test and release notes), AR-26.

**Technical notes:** E0a owns `api/routes/share.py`, the share schemas and `SharedCampaignPage.tsx`. `JournalCard` takes the owner `JournalEntry` type, so give it a narrowed prop type or a `preview` variant. Don't widen the Public types to fit it. AD-13.

**Dependencies:** E0a.1. **Size:** S.

## Epic E0-QA: Trustworthy tests, CI gates and evaluation harness

The owner and capstone reviewers can trust every merge. Tests build the schema from migrations against the dev Postgres. CI runs on `main` and on every PR. The licence gate covers the shipped images, not just the CPU wheels. EV-4 is a hard zero-leak gate. Benchmarks and the demo seed can be reproduced.

**Covers:** NFR-4, NFR-5 (EV-4 harness), NFR-6 (EV-5 harness), NFR-8 (migration-chain tests), NFR-1 (offline eval runs), AR-21, AR-22, AR-27, CI-1 to CI-15 (harness and workflows), SPIKE-1/SPIKE-2 x86 re-run, EV-4, EV-5, demo seed, LIC-1 register entries, D-7.

### Story E0-QA.1: Backend CI runs on `main`

**Status:** Done (PR #2, commit `df41744`)

As the owner,
I want backend tests to run on pushes to `main` and on every PR,
So that a broken `main` is caught when it breaks, not at the next PR.

**Acceptance Criteria:**

**Given** `.github/workflows/backend-tests.yml`
**When** a commit is pushed to `main`
**Then** the backend test job runs (the trigger used to be `master`, which does not exist).

**Covers:** CI-1.

**Technical notes:** One-line trigger fix. The path filter is still in place, and E0-QA.6 removes it (AD-21 "no path filter").

**Dependencies:** none. **Size:** S.

### Story E0-QA.2: Dependency licence gate for Python and npm packages

**Status:** Done (PR #2, commit `df41744`)

As the owner selling a commercial licence,
I want CI to fail when a Python or npm dependency has a copyleft, non-commercial, ethical-use or unknown licence,
So that nothing incompatible enters the commercial build unnoticed.

**Acceptance Criteria:**

**Given** `src/backend/requirements.txt` and `src/frontend/package-lock.json`
**When** the `Dependency licences` workflow runs
**Then** `scripts/check-licenses.py` reads PEP 639 `License-Expression`, then the classifiers (`--python-env`), plus `license-checker-rseidelsohn` JSON (`--npm`), and fails on any licence outside `.github/license-policy.toml` `[allow]`
**And** the 3 recorded exceptions (fpdf2, python-bidi, caniuse-lite) pass with `OWNER TO CONFIRM` reasons. Current dependencies give 0 violations.

**Covers:** NFR-4 (library scan part), CI-4 (partial), AR-22 (pip and npm scans).

**Technical notes:** `.github/workflows/license-check.yml`, `.github/license-policy.toml`, `scripts/check-licenses.py`. Remaining gaps are tracked as open stories: path filters (E0-QA.6), the register and strict edition mode (E0-QA.7), shipped images and the CUDA wheels (E0-QA.8), and owner confirmation (E0-QA.9).

**Dependencies:** none. **Size:** M.

### Story E0-QA.3: One GitHub Pages deployer

**Status:** Done (PR #4, commit `5a66be6`)

As the owner,
I want only `pages.yml` to deploy the Pages site,
So that duplicate workflows stop overwriting the landing page and the whole repo is never published.

**Acceptance Criteria:**

**Given** `.github/workflows/`
**When** a commit lands on `main`
**Then** only `pages.yml` deploys to Pages. `static.yml` and `jekyll-gh-pages.yml` are removed.

**Covers:** D-7.

**Technical notes:** Shipped. No further work.

**Dependencies:** none. **Size:** S.

### Story E0-QA.4: The test database URL can be overridden from the environment

**Status:** Open

As a developer running tests on the remote CachyOS desktop over Tailscale, in CI, or in a parallel worktree,
I want the test database URL to come from the environment,
So that the suite runs against whichever pgvector Postgres I point it at, without editing `conftest.py`.

**Acceptance Criteria:**

**Given** `tests/conftest.py`, which today hardcodes `TEST_DB_URL` to `localhost:5432/lorekeeper_test`
**When** `TEST_DATABASE_URL` is set
**Then** every fixture (`setup_test_db`, `db`, `client`) connects to that URL
**And** if it is unset, the default stays `postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test`, so existing local runs and CI keep working.

**Given** a URL whose database name does not end in `_test`
**When** the session fixture starts
**Then** it aborts with a clear message before it drops anything, so a typo can never wipe a dev or prod database.

**Given** two worktrees running at once
**When** each sets `TEST_DATABASE_URL=…/lorekeeper_test_<lane>`
**Then** neither touches the other's schema. The README "Running tests" section documents the variable, the `_test` guard, the per-lane naming (parallel plan §4.3) and the Tailscale example.

**Given** `.github/workflows/backend-tests.yml`
**When** it runs
**Then** it sets `TEST_DATABASE_URL` explicitly, and the comment that says the values must match a hardcoded URL is removed.

**Covers:** AR-21 (`TEST_DATABASE_URL`), AR-27 (hardcoded `TEST_DB_URL` gap), NFR-8.

**Technical notes:** Keep the module constant `TEST_DB_URL` (other test modules may import it), read as `os.environ.get("TEST_DATABASE_URL", <default>)`. The env name follows the AD-21 contract. AD-21.

**Dependencies:** none. **Size:** S.

### Story E0-QA.5: Tests build the schema from Alembic migrations

**Status:** Open

As the owner,
I want the test schema built by `alembic upgrade head` instead of `Base.metadata.create_all`,
So that every test also exercises the migration chain that production boots with.

**Acceptance Criteria:**

**Given** an empty test database at `TEST_DATABASE_URL`
**When** the session fixture runs
**Then** it creates the `vector` extension, runs `alembic upgrade head` programmatically (`alembic.command.upgrade` with `sqlalchemy.url` set to the test URL), and runs the suite
**And** `create_all` and `drop_all` are gone from `tests/conftest.py`. Teardown uses `alembic downgrade base` or `DROP SCHEMA public CASCADE` followed by `CREATE SCHEMA public`.

**Given** the models package
**When** `migrations/env.py` loads
**Then** it imports `app.db.models` (the whole package), and `app/db/models/__init__.py` registers every model, with `AppConfig` inside `__all__`
**And** a test `tests/test_migrations_match_models.py` runs Alembic's autogenerate comparison (`compare_metadata`) against the migrated DB and fails on any difference, apart from a short commented ignore list (for example the generated `narrative_tsv` index).

**Given** the test environment
**When** pytest starts
**Then** `conftest.py` sets `ENVIRONMENT=test` and `JOBS_EAGER=1` before importing `app.main`, so the fake LLM provider (E0-LLM), the client fakes (E0-Platform) and inline Jobs (E0-Jobs) activate when they land, with no further conftest change
**And** the 13 existing tests pass on the remote desktop's cached Docker image and in CI.

**Covers:** AR-21 (`alembic upgrade head`, `create_all` removed, fakes switch), AR-27, NFR-8, AR-19 (model registration).

**Technical notes:** `tests/conftest.py`, `migrations/env.py` (currently imports only a few models, `env.py:40`), `app/db/models/__init__.py`. `env.py` loads the repo `.env`, so the fixture must override `sqlalchemy.url` explicitly. Redis for tests comes from `docker-compose.dev.yml`. Leave `REDIS_URL` alone if it is set. AD-19, AD-21.

**Dependencies:** E0-QA.4. **Size:** M.

### Story E0-QA.6: Migration-chain gates, and CI with no path filters

**Status:** Open

As the owner,
I want CI to prove that the migration chain has one head and upgrades both an empty database and a copy of today's schema, on every PR and every push to `main`,
So that a self-hoster's boot-time `alembic upgrade head` never fails on their real data.

**Acceptance Criteria:**

**Given** the migrations directory
**When** CI runs
**Then** a job fails if `alembic heads` returns more than one head (CI-6)
**And** `alembic upgrade head` succeeds on an empty database.

**Given** a committed snapshot fixture `tests/fixtures/snapshot_a3e7c1f9d258.sql` (schema at revision `a3e7c1f9d258` plus a small seeded dataset: 1 Owner, 2 Members, 1 read-only and 1 collaborate token, journal entries with Shorthand, NPCs, Quests, chat sessions)
**When** CI restores it and runs `alembic upgrade head`
**Then** the upgrade succeeds, row counts of pre-existing tables are unchanged, and the job runs the post-upgrade assertions that each later revision registers in `tests/migrations/test_upgrade_snapshot.py` (E0-Access.1 adds the member-role assertions)
**And** a test enumerates every FK from `information_schema.referential_constraints` against an expected `ON DELETE` table in the same file, so revisions that add FKs must state their action (CI-6 FK action test).

**Given** `.github/workflows/backend-tests.yml` and `license-check.yml`
**When** any PR opens or anything is pushed to `main`
**Then** both workflows run with no `paths:` filter (AD-21, NFR-4).

**Covers:** NFR-8 (migrations tested against an existing database), NFR-4 ("no path filter"), CI-6, AD-21 CI scope.

**Technical notes:** Create the snapshot by checking out `a3e7c1f9d258`, upgrading an empty DB, seeding with a script committed as `scripts/make_snapshot.py`, and running `pg_dump`. The snapshot is the brownfield baseline for every Phase 0 revision (F1-core, F2, F3). AD-19, AD-21.

**Dependencies:** E0-QA.5. **Size:** M.

### Story E0-QA.7: Licence register and strict commercial mode

**Status:** Open

As the owner,
I want one licence register that lists every dependency, image, apt package, model, voice and font with its licence and edition status, checked by CI,
So that I can show the commercial build is clean and the AGPL-only parts are known.

**Acceptance Criteria:**

**Given** a new `licenses/register.yaml`
**When** it is first committed
**Then** it has one entry per current Python package, npm package (shipped and build-time), base image (`python:3.11-slim`, `pgvector/pgvector:pg16`, `redis`, `nginx`, `ollama/ollama`), bundled model (Lorekeeper-Mistral-7B GGUF, MiniLM-L6-v2, spaCy `en_core_web_trf`, Whisper, EasyOCR weights) and font, each with `name`, `kind ∈ {python, npm, image, apt, model, voice, font}`, `version`, `license` (SPDX), `source_url`, `editions ⊆ {agpl, commercial}` and `notes`
**And** it records the LIC-1 findings: espeak-ng (GPL-3.0+, via `espeakng-loader`) is `editions: [agpl]`, `tts` container only, and the deferred non-GPL pronunciation path is noted. The rejected list from PRD addendum F is recorded with reasons.

**Given** `scripts/check-licenses.py`
**When** it runs with `--register licenses/register.yaml`
**Then** it fails when an installed Python or npm package has no register entry, or the entry's licence differs from the scanned one
**And** when `LOREKEEPER_EDITION=commercial` (strict mode), it fails on any entry or scan result with GPL, AGPL, LGPL outside the dynamic system-library allowlist (libvips from apt, Pango, HarfBuzz, GLib), non-commercial, Hippocratic or unknown licences, and on any entry whose `editions` excludes `commercial` but which is present in a commercial artifact
**And** in `agpl` mode, GPL-family entries pass only when their `editions` is `[agpl]` and the artifact is the `tts` image.

**Given** a model, voice or font file listed in the register
**When** the register-vs-artifacts check runs
**Then** each `kind ∈ {model, voice, font}` entry has an `artifact` path or download source and a `sha256`, and the check fails if a baked artifact has no entry.

**Covers:** NFR-4 (register, strict mode, register-vs-artifact), AR-22, CI-4, LIC-1 (register entries), AD-16 (`LOREKEEPER_EDITION`).

**Technical notes:** Keep `.github/license-policy.toml` as the scanner's allowlist, aliases and exceptions file. `register.yaml` is the inventory. `pyvips[binary]` is denied. Add `pyyaml` as a dev-only dependency of the checker. Run in both editions as two matrix legs in `license-check.yml`. AD-22.

**Dependencies:** E0-QA.2. **Size:** M.

### Story E0-QA.8: The licence check scans the Docker images we actually ship

**Status:** Open

As the owner,
I want the licence gate to scan the built backend, worker and sidecar images, including apt packages and the CUDA wheels,
So that the ~15 NVIDIA-proprietary wheels the backend image pulls in with CUDA torch, which the CPU-only CI install never sees, are caught and handled.

**Acceptance Criteria:**

**Given** `src/backend/Dockerfile.prod`, which runs `pip install -r requirements.txt` from the default index (CUDA torch on x86-64)
**When** a new `image-licenses` job in `license-check.yml` builds the image and runs `python scripts/check-licenses.py --python-env --register licenses/register.yaml` **inside** it
**Then** every `nvidia-*` wheel (cuBLAS, cuDNN, NCCL, cusparselt and others), `triton` and the CUDA `torch` build are reported with their real licence strings
**And** the job lists them as violations in commercial mode.

**Given** the same image
**When** the apt scan runs (`dpkg-query -W -f='${Package} ${Version}\n'` plus `/usr/share/doc/*/copyright`)
**Then** each apt package resolves to a register entry or the dynamic-LGPL system-library allowlist, and an unknown package fails.

**Given** the CUDA wheels are a known issue that E0-Platform's AD-1 refactor removes (web and worker images never install torch, and `ml` gets a CPU-wheel default with a GPU override image)
**When** this story lands
**Then** the CUDA wheels are listed under a `[[pending]]` table in `license-policy.toml`, each with `tracking: "E0-Platform AD-1 / ml CPU image"`. Pending entries print a warning and do not fail the job. Any **new** unregistered package still fails
**And** `docs/LICENSING.md` (new) explains the gap, the interim rule (the commercial build must use the CPU wheel index `--extra-index-url https://download.pytorch.org/whl/cpu` until AD-1 lands) and the owner decision still needed about GPU-image redistribution under the NVIDIA EULA.

**Given** an image matrix
**When** E0-Platform adds the `ml` and `stt` images and E5 adds `tts`
**Then** each is one matrix line in `image-licenses` with no code change. The `tts` image runs only in the `agpl` leg.

**Covers:** NFR-4 (image-level and system-package scan, "fails the commercial build"), AR-22 (image apt scan, scans of web, worker, ml and stt images), CI-4.

**Technical notes:** Build with `docker buildx build --load` and run the checker with `docker run --rm -v $PWD/scripts:/chk:ro -v $PWD/licenses:/lic:ro -v $PWD/.github:/pol:ro`. The checker must not be installed into the image. Cache layers with `type=gha`. The remote desktop's cached image is a useful local reproduction (`docker run … pip list | grep nvidia`). AD-1, AD-22.

**Dependencies:** E0-QA.7. **Size:** M.

### Story E0-QA.9: Owner confirms or replaces the three licence exceptions

**Status:** Open (owner action plus a small code change)

As the owner,
I want to record my decision on the fpdf2 (LGPL-3.0), python-bidi (LGPL, via easyocr) and caniuse-lite (CC-BY-4.0) exceptions,
So that the commercial build doesn't rely on exceptions nobody has approved.

**Acceptance Criteria:**

**Given** the 3 `[[exception]]` entries in `.github/license-policy.toml` marked `OWNER TO CONFIRM`
**When** the owner decides
**Then** each entry gains `confirmed_by` and `confirmed_on` fields (or is removed), and its reason text drops `OWNER TO CONFIRM`.

**Given** `LOREKEEPER_EDITION=commercial`
**When** the checker meets an exception with no `confirmed_by`
**Then** it fails, naming the package. In `agpl` mode it only warns.

**Given** the owner rejects an exception
**When** the decision is recorded
**Then** a replacement is recorded with an owning story: fpdf2 is replaced by WeasyPrint (BSD) in E8's PDF story, and python-bidi leaves the web image when E0-Platform moves EasyOCR into the `ml` sidecar, after which it is scanned in that image instead
**And** the decision is written to `docs/LICENSING.md` and `licenses/register.yaml` (`notes`).

**Covers:** NFR-4, AR-22.

**Technical notes:** The default recommendation for the owner, in the PR description: confirm caniuse-lite (build-time data, attribution only). Confirm fpdf2 and python-bidi only as interim measures until E8 and E0-Platform remove them. AD-22.

**Dependencies:** E0-QA.7. **Size:** S.

### Story E0-QA.10: Structural CI gates: layers, model packages, table owners, enum sync, memory sum

**Status:** Open

As a developer working in a parallel worktree,
I want CI to enforce the architecture's structural rules on every PR,
So that layering, table ownership and the memory budget cannot drift while six lanes merge.

**Acceptance Criteria:**

**Given** an `.importlinter` config at `src/backend/`
**When** `lint-imports` runs in CI
**Then** the AD-1 layer contracts are enforced (`api` → `services` → `db`, `domain` imports nothing from the app, `clients` only `core`). Today's violations are listed in `ignore_imports` with a `# ratchet` comment, and a test fails if that list grows (CI-2).

**Given** `requirements.txt` for the web and worker images
**When** CI runs `scripts/check_model_packages.py`
**Then** it fails if any of `torch`, `spacy`, `sentence-transformers`, `openai-whisper`, `faster-whisper`, `easyocr`, `onnxruntime`, `kokoro` or `TTS` appears, except packages in a ratchet baseline `scripts/model_packages_baseline.txt` that can only shrink. Today's baseline holds `torch`, `spacy`, `sentence-transformers`, `openai-whisper` and `easyocr`, which E0-Platform removes (CI-3).

**Given** the boundary map table in `ARCHITECTURE-SPINE.md` ("Capability → Architecture Map")
**When** `scripts/check_table_owners.py` parses its "Owns (tables)" column, including F1-core, F2-jobs-files and F3-world expanded from AD-19
**Then** it fails if a table has two owners, or if a `create_table` in a migration names a table with no owner (CI-7).

**Given** StrEnums in `app/domain/enums.py`, once E0-WorldCore creates it, and any model column with a CHECK generated from one
**When** `tests/test_enum_check_sync.py` runs
**Then** for each registered `(StrEnum, table, column)` pair it compares the enum members with the CHECK constraint values read from `pg_constraint` and fails on mismatch. With no pairs registered it passes (CI-10).

**Given** `.env.example`
**When** `scripts/check_memory_budget.py` sums every `*_MEM_LIMIT`
**Then** it fails if the sum exceeds 14.5 GB. It passes vacuously until E0-Platform adds the limits (CI-14).

**Given** gates owned by other epics (CI-5 sidecar `--network none`, E0-Platform; CI-8 scoped queries, E0-Access.5; CI-9 flat LLM schemas, E0-LLM; CI-11 registry property test, E0-Access.3; CI-13 buildx, E0-Platform; CI-15 colour grep, E0-UX)
**When** those epics land their scripts
**Then** each one is a single named step in `.github/workflows/gates.yml` (new, no path filter), so the workflow file is the one place to see every gate.

**Covers:** CI-2, CI-3, CI-7, CI-10, CI-14 (and the CI-5, CI-8, CI-9, CI-11, CI-13, CI-15 slots), AR-1 (enforcement), AR-9 (StrEnum CHECK test), AR-19.

**Technical notes:** Register `import-linter` in `licenses/register.yaml` (BSD-2). The table-owner parser reads Markdown, so keep it tolerant of backticks and `+`. AD-1, AD-7, AD-9, AD-19.

**Dependencies:** E0-QA.6, E0-QA.7. **Size:** M.

### Story E0-QA.11: EV-4 harness scaffolding: route enumeration, actors and probe families

**Status:** Open

As the owner,
I want a spoiler-leak harness that lists every API route and nginx location and tests each one as several kinds of requester,
So that every feature epic can add a probe file, and an uncovered route is visible rather than silently skipped.

**Acceptance Criteria:**

**Given** `tests/ev4/` (new)
**When** `pytest tests/ev4` runs
**Then** `tests/ev4/routes.py` enumerates every `APIRoute` and `APIWebSocketRoute` in `app.routes` (method plus path template) and every `location` in `nginx/locations.conf` and `nginx.conf`, and resolves each API path to its nginx location using nginx's real matching order (exact `=`, then longest `^~` prefix, then regex in file order, then longest prefix)
**And** `tests/ev4/test_coverage.py` fails for any route that has neither a probe registered with `@ev4_probe(method, path)` in `tests/ev4/probes/*.py` nor an entry in `tests/ev4/exemptions.yaml` with a `reason`.

**Given** existing routes have no probes yet
**When** the harness lands
**Then** they are listed in `tests/ev4/pending_baseline.txt`, which the coverage test accepts and which can only shrink (a test fails if a line is added). E0-QA.13 empties it.

**Given** `tests/ev4/fixtures.py`
**When** a probe asks for actors
**Then** it gets a seeded **canary Campaign** (`seeds/ev4_canary.json`: each GM-only field and record type holds a unique token such as `CANARY-SHORTHAND-<uuid>`, `CANARY-NPCNOTE-<uuid>`) and actors `gm_owner`, `anon_share` (read-only token), `cross_gm_player` (GM in Campaign A, Player in Campaign B) and `player`
**And** `player` and `cross_gm_player` call `make_member(role=…)`. Until `campaign_members.role` exists (E0-Access.1), that raises `pytest.skip("roles not yet available")`.

**Given** `tests/ev4/families.py`
**When** a probe uses a family helper
**Then** these helpers exist:
- `assert_no_canary(response)`: scans body and headers;
- `assert_hidden_equals_missing(actor, hidden_url, missing_url)`: same status, body and relevant headers;
- `assert_hidden_field_equals_unset(actor, url, field)`;
- `assert_counts_and_ranking_unchanged(actor, url, mutate_gm_only)`: adding GM-only content changes no count, total, order or page boundary for a non-GM;
- `assert_captured_context_clean(actor, call)`: uses the E0-LLM capture hook if present, otherwise skips with a reason;
- `assert_audience_ladder(url)`: Public vs Members vs Owner(other);
- `downgrade_suite(type_name)`: driven by `DERIVED_REGISTRY` when it exists, empty otherwise.

**Given** CI
**When** `pytest tests/ev4` runs as its own step in `gates.yml`
**Then** it reports the probe count, exemption count, pending count and leak count. The leak count is the number of canary hits plus family assertion failures. At this stage a leak fails the build, but a pending route does not.

**Covers:** EV-4 (harness), NFR-5 (harness), AR-21 (EV-4 enumeration and families), CI-12 (scaffold).

**Technical notes:** The harness is E0-QA's. `tests/ev4/probes/` is a shared append point, and each feature adds `<feature>.py`. The nginx parser only needs `location` lines and their modifiers. Fail loudly on syntax it cannot parse. AD-13, AD-20 ("EV-4 resolves each route against the real nginx matching order"), AD-21.

**Dependencies:** E0-QA.5, E0-QA.10 (the `gates.yml` step). **Size:** L.

### Story E0-QA.12: Demo seed and the shared eval-script scaffold

**Status:** Open

As a capstone reviewer or eval author,
I want the 9-entry demo Campaign committed as a seed, plus a standard eval-script skeleton and report format,
So that EV-1, EV-2, EV-3, EV-5 and EV-6 run the same way on the same data, offline.

**Acceptance Criteria:**

**Given** `seeds/demo_campaign.json` (new)
**When** it is committed
**Then** it holds the 9 demo entries behind `docs/RETRIEVAL_EVAL.md` (Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker) with Shorthand, Narrative, session dates, NPCs and Quests, plus 3 entries added for later evals: a status change (Mira dies), a contradiction and a flashback trap
**And** each entry has a stable `seed_id` so that eval epics can append labelled entries without renumbering.

**Given** `scripts/seed_demo.py --database-url … [--owner-email …]`
**When** it runs twice
**Then** the second run makes no changes (idempotent on `seed_id`), and it prints the Campaign id
**And** it works with networking disabled (`docker compose run --network none`), with no model download (NFR-1).

**Given** `scripts/eval_common.py` (new) and `docs/EVAL_TEMPLATE.md`
**When** an epic writes `scripts/eval_<name>.py`
**Then** it reuses `load_campaign(seed)`, `sweep(operating_points)`, `write_report(doc_path, table, chosen_point, failures)` and the shared CLI (`--campaign-id`, `--out`), and the doc follows the RETRIEVAL_EVAL sections (method, results table, chosen operating point, "measured failure → fix", reproduce command)
**And** `scripts/eval_retrieval.py` is moved onto `eval_common` and reproduces the published hybrid@0.65 = 14/16 hit@3, 5/5 gate-holds within ±1 hit.

**Covers:** demo seed, AR-21 (eval format), NFR-1 (offline eval runs), EV-1/2/3/6 substrate.

**Technical notes:** E0-QA owns `seeds/` and `scripts/seed_demo.py`. Eval epics append entries but never restructure the file. The seed writes through the same ORM models (not raw SQL) so that index columns are computed. AD-21.

**Dependencies:** E0-QA.5. **Size:** M.

### Story E0-QA.13: EV-4 probes for every existing route

**Status:** Open

As the owner,
I want every route that existed before the expansion probed as Player, anonymous Share Link and cross-Campaign GM,
So that the access work in E0-Access is proven, not assumed, on the code that was actually leaking.

**Acceptance Criteria:**

**Given** `tests/ev4/pending_baseline.txt` from E0-QA.11
**When** this story completes
**Then** it is empty. Every pre-existing route has a probe in `tests/ev4/probes/` (`journals.py`, `share.py`, `npcs.py`, `quests.py`, `tags.py`, `campaigns.py`, `members.py`, `character_sheets.py`, `sources.py`, `session_plans.py`, `shorthand.py`, `ingest.py`, `settings.py`) or a reasoned exemption (for example `auth`, `billing`, `admin` behind `require_admin`, `feedback`)
**And** each read probe applies `assert_no_canary`, `assert_hidden_equals_missing` and `assert_counts_and_ranking_unchanged` for `player`, `anon_share` and `cross_gm_player`.

**Given** the GM authoring and AI routes (AR-26 list)
**When** probed as `player`
**Then** each returns `404 {"detail":"Not found"}` with a body identical to a missing Campaign's.

**Given** write routes (`PUT /api/npcs/{id}`, `PUT /api/quests/{id}`, journal tag attach and detach, sheet writes)
**When** probed as `player`
**Then** the forbidden write is a 404 identical to "missing", and allowed writes return Party projections with no canary.

**Given** search and matching (`GET /api/journals?search=`, `/api/npcs/{id}/entries`, `/api/quests/{id}/entries`, `/api/tags` counts)
**When** a word appears only in a GM entry's Shorthand
**Then** the `player` result set, totals and order are identical to a run without that word.

**Covers:** EV-4 (existing routes), NFR-5, FR-8, FR-9(b) (search and matching evidence), AR-26.

**Technical notes:** Uses only the harness families. Probes for chat routes and captured LLM context are in E0-QA.14. AD-13, AD-21.

**Dependencies:** E0-QA.11, E0-Access.4, E0-Access.5, E0-Access.6, E0-Access.7, E0-Access.13. **Size:** L.

### Story E0-QA.14: EV-4 is a zero-leak hard gate, with chat and captured-context probes

**Status:** Open

As the owner,
I want CI to block any merge with a single EV-4 leak, an unprobed route, or a Player prompt that contains GM content,
So that "Players never see GM-only content" is a release gate, not a hope.

**Acceptance Criteria:**

**Given** `POST /api/chat/` and `POST /api/chat/stream`
**When** probed as `player` with questions whose only answer is in Shorthand, a GM-only entry, a source document or the glossary
**Then** `tests/ev4/probes/chat.py` shows no canary in sources, retrieval candidates (including gated-out ones), canon sources, the SSE `meta`, `delta` and `done` events, or the returned trace
**And** the captured LLM context (`assert_captured_context_clean`) holds no canary, no glossary block and no Shorthand. The probe runs against both the blocking and the streaming endpoint.

**Given** a demoted Member (Co-GM → Player) who has chat sessions
**When** they list, fetch or continue those sessions
**Then** archived sessions are absent, a fetch returns 404, and a new message's captured context contains no turn from an archived session.

**Given** `gates.yml`
**When** the EV-4 step runs on a PR or on `main`
**Then** it fails on any leak, on any route that is neither probed nor exempted, or on a non-empty `pending_baseline.txt` (CI-12 hard gate)
**And** a new route with no probe or exemption fails with a message naming the route and pointing to `tests/ev4/probes/`.

**Given** `docs/SPOILER_EVAL.md` (new, RETRIEVAL_EVAL format)
**When** the pre-release live-model run executes (`scripts/eval_spoiler.py` against the real `lorekeeper` model on the remote desktop's Ollama, not the fake provider)
**Then** the doc records the probe counts, the leak count (target 0), the inference-channel checks and the reproduce command. SM-4 is met at 0 leaks.

**Covers:** EV-4, NFR-5 (0 leaks before release), CI-12, FR-9(b) (chat evidence), FR-43 (evidence), SM-4.

**Technical notes:** The captured-context family needs the E0-LLM "Fake provider + capture hook" contract (parallel plan §3.5, expected story E0-LLM.5). Without it, `chat.py` probes still run the response-side checks, and the gate stays red until the hook exists (see Decision B1-D9). AD-13 (test capture), AD-21.

**Dependencies:** E0-QA.13, E0-Access.8, E0-Access.12, E0-LLM.5 (fake provider and capture hook). **Size:** M.

### Story E0-QA.15: EV-5 benchmark suite and the x86 spike re-run

**Status:** Open

As the owner,
I want one reproducible benchmark script and `docs/BENCHMARKS.md` with a row for every NFR-6 target and NFR-2 case, re-measured on x86,
So that latency targets come from the real Reference Box class rather than M-series numbers taken at n=1.

**Acceptance Criteria:**

**Given** `scripts/eval_benchmarks.py` (on `eval_common`) and `docs/BENCHMARKS.md`
**When** it runs
**Then** the doc has one row per NFR-6 target (proposals, continuity, caption lag, Rolling Recap update, quick lookup, NPC first token, 300-word narration, 100-entry Chronicle, warm portal load) and per NFR-2 case (idle, one heavy Job, Live Session with STT plus Rolling Recap), with columns: target CPU, target GPU, measured CPU, measured GPU, peak RSS, n, date, hardware, owning epic
**And** rows whose feature hasn't landed show `pending (E<n>)`. Each feature epic fills its own row (standing AC, EV-5).

**Given** the spike scripts in `spikes/cpu-benchmarks.md` (appendix)
**When** they are committed under `scripts/spikes/` and re-run on the remote x86 desktop, with the CPU case run as `CUDA_VISIBLE_DEVICES=""` inside `docker run --cpus=<n> --memory=16g` to approximate the 16 GB CPU-only Reference Box, and the GPU case on the RTX 5080
**Then** BENCHMARKS.md records SPIKE-1 (NLI xsmall vs base, 50 pairs) and SPIKE-2 (faster-whisper base int8 vs float32 RTF per 15 s chunk, the "LLM busy" case, and `initial_prompt` name accuracy on the 6 demo names), with n ≥ 5 and the median and spread reported
**And** the result states whether the M-series decisions (xsmall default, base STT, 15 s chunks) still hold.

**Given** NFR-6 targets are provisional
**When** the x86 numbers would change a target
**Then** the proposed reset is written to `.memlog.md` (new at repo root) as a pending entry, and it takes effect only once the owner records sign-off there.

**Covers:** EV-5, NFR-6 (harness and reset process), NFR-2 (measurement rows), SPIKE-1 and SPIKE-2 x86 re-run, SM-5.

**Technical notes:** The desktop runs Ollama 0.40.3 natively, about 156 tok/s on GPU. Record the Ollama version and model digest per row. SPIKE-5 (memory) belongs to E0-Platform and SPIKE-6 (LLM throughput) to E0-LLM. Both write their rows here through `eval_common`. AD-7, AD-21.

**Dependencies:** E0-QA.12. **Size:** M.

## Epic E0-Platform: Runs offline on one 16 GB box with models outside the web tier

A self-hoster brings the whole stack up with one command, offline, inside 16 GB, and the web tier no longer loads ML models per worker.

**Out of scope (dependency):** the in-app Hugging Face model-installer fix (Ollama rejects the HF repo reference) is in progress on branch `fix/hf-model-install`. Stories here depend on it where they need the `lorekeeper` model installed in a containerised Ollama. They do not re-specify it.

### Story E0-Platform.1: Dev compose ports bind to localhost by default

As a self-hoster developing on a shared network,
I want the dev compose files to publish Postgres, Redis, the backend and Vite only on `${BIND_IP:-127.0.0.1}`,
So that a fresh `docker compose up` never exposes an unauthenticated database to the LAN, while I can still opt in to reach the stack over Tailscale.

**Acceptance Criteria:**

**Given** `docker-compose.yml` and `docker-compose.dev.yml` with no `BIND_IP` set
**When** I run `docker compose -f docker-compose.dev.yml up -d` and `docker compose up -d`
**Then** `docker compose port` / `ss -ltn` shows 5432, 6379, 8000 and 5173 bound to `127.0.0.1` only
**And** a connection attempt to those ports from another host is refused.

**Given** `BIND_IP=<tailscale ip>` in `.env` on the remote x86 desktop
**When** the dev stack starts
**Then** Postgres and Redis are reachable from the dev laptop over Tailscale at that IP, and not on the desktop's LAN address.

**Given** `docker-compose.prod.yml`
**When** this story lands
**Then** its port publishing is unchanged (only nginx publishes 80/443), and `.env.example` documents `BIND_IP` with a warning against `0.0.0.0`.

- **Covers:** NFR-1 (self-run remote access), NFR-5 (no data exposure). AR-25.
- **Technical notes:** Change each `ports:` entry to `"${BIND_IP:-127.0.0.1}:5432:5432"` and so on. Add a short "Remote dev over Tailscale" note to `README.md`. `tests/conftest.py` reading `TEST_DATABASE_URL` is E0-QA's substrate work. This story only makes the Tailscale-reachable DB possible. Governed by AD-7 (compose files owned by E0-Platform).
- **Dependencies:** none.
- **Size:** S

### Story E0-Platform.2: CPU-only torch in the backend image (closes the NVIDIA wheel licence gap)

As the owner shipping a commercial edition,
I want the backend images to install the CPU-only torch build,
So that the image no longer contains about 15 NVIDIA-proprietary wheels that the CPU-only CI licence check never sees, and the image is several GB smaller.

**Acceptance Criteria:**

**Given** `src/backend/Dockerfile` and `src/backend/Dockerfile.prod` built for `linux/amd64`
**When** the image is built
**Then** torch is installed from the PyTorch CPU index (`--index-url https://download.pytorch.org/whl/cpu`, pinned `torch==<ver>+cpu`) before `requirements.txt`
**And** `docker run --rm <image> pip list | grep -i nvidia` prints nothing
**And** `python -c "import torch; assert not torch.cuda.is_available()"` succeeds.

**Given** the same Dockerfiles built for `linux/arm64`
**When** the image is built
**Then** it installs the standard CPU torch wheel and the build succeeds (the `build-essential` note in `Dockerfile.prod` is kept).

**Given** the built image
**When** `scripts/check-licenses.py` is run against the image's installed packages (`pip-licenses` inside the container)
**Then** it passes with `.github/license-policy.toml`, and `licenses/register.yaml` (or the current policy allowlist, if E0-QA's register has not landed) records torch (BSD-3-Clause) as the CPU build.

**Given** the existing test suite and `/api/health`
**When** run against the new image
**Then** journal save, retrieval and `test_nlp.py` behave as before, and the image size drop is recorded in the PR description.

- **Covers:** NFR-4, NFR-3 (interim). AR-22 (register entry), AR-1 (precursor).
- **Technical notes:** This is an interim fix. E0-Platform.6 removes torch from the web/worker image entirely. The same CPU-index pattern is reused for the `ml` sidecar image (E0-Platform.3). The licence-check workflow (`.github/workflows/license-check.yml`) belongs to E0-QA. If its scan has to run inside the image to catch this class of gap, raise that with E0-QA and do not edit the workflow here. Governed by AD-22, AD-1.
- **Dependencies:** none.
- **Size:** S

### Story E0-Platform.3: `ml` sidecar for embeddings and NER, with its client

As a self-hoster,
I want embeddings and spaCy NER to run once in an `ml` sidecar instead of once per web worker,
So that the four gunicorn workers stop holding four copies of MiniLM and `en_core_web_trf`.

**Acceptance Criteria:**

**Given** `src/services/ml/` (FastAPI app plus Dockerfile, Python 3.11, CPU torch from the CPU index)
**When** the image is built
**Then** `all-MiniLM-L6-v2` and `en_core_web_trf` are baked into the image at build time, and the container runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`
**And** `docker run --network none <ml image>` becomes healthy on `GET /healthz` (CI-5 smoke script `scripts/sidecar_smoke.sh ml`).

**Given** the running `ml` sidecar
**When** `POST /v1/embed {texts:[...]}` is called
**Then** it returns `{model, dim: 384, vectors}` with normalized vectors
**And** for the 9 demo-seed narratives, each vector's cosine similarity to the old in-process `embedding_service.embed` output is ≥ 0.9999, so no re-embed is needed.

**Given** a narrative mentioning "Borin Stonebeard", "Karak Dun" and "a ring of shadows"
**When** `POST /v1/ner {text}` is called
**Then** it returns `{ents:[{text,label,start,end}]}` covering spaCy entity labels plus the existing Matcher labels for items and quests, so `nlp_service`'s tag mapping produces the same tags as today (existing `test_nlp.py` cases move to `src/services/ml/tests/` and pass).

**Given** `GET /v1/status`
**When** called
**Then** it lists loaded models and current RSS.

**Given** `app/clients/ml.py`
**When** the backend calls `embed(texts)` or `ner(text)` and the sidecar is down or times out
**Then** the client raises `ModelServiceUnavailable` (in `app/clients/errors.py`), with timeouts from `settings.ml_url` and `settings.ml_timeout_s`
**And** a deterministic fake (`app/clients/fakes.py`, chosen when `ENVIRONMENT=test`) returns stable 384-d vectors and rule-based ents, so route tests run without the sidecar.

**Given** `app/domain/embedding.py`
**When** this story lands
**Then** it defines `EMBEDDING_MODEL` and `EMBEDDING_DIM = 384` as the only definition, and the existing copies (`embedding_service.py`, the `JournalEntry`/source chunk models and any migration-adjacent constants) import it.

- **Covers:** NFR-1, NFR-3. AR-6, AR-1. CI-5 (smoke script).
- **Technical notes:** Add the `ml` service to `docker-compose.yml` and `docker-compose.prod.yml` on the internal network only, with no `ports:` and no nginx route (AD-6). Set `ml_url` in `app/core/config.py`. Add licence register lines for sentence-transformers, torch CPU, spaCy, `en_core_web_trf` and the MiniLM weights. The sidecar does not depend on the backend package. The client fake lives in `app/clients/` because E0-Platform owns that directory. E0-QA's conftest switches it on. This story does not change callers yet (E0-Platform.6). Governed by AD-6, AD-1.
- **Dependencies:** E0-Platform.2 (CPU-index pattern).
- **Size:** M

### Story E0-Platform.4: `ml` lazy NLI and OCR under a resident-memory budget

As a self-hoster on 16 GB,
I want NLI and OCR models in `ml` to load only when first used and to unload under a memory budget,
So that continuity checks and image ingest work without permanently holding memory the Live Session needs.

**Acceptance Criteria:**

**Given** the `ml` image with `cross-encoder/nli-deberta-v3-xsmall` and the EasyOCR English weights baked in
**When** the container starts
**Then** only embeddings and NER are resident, and `GET /v1/status` shows NLI and OCR as `not_loaded`.

**Given** `POST /v1/nli {pairs:[{premise,hypothesis}]}` with 50 pairs
**When** called the first time
**Then** the model loads, the pairs are scored in batches of 32, and the response is `{scores:[{entailment,neutral,contradiction}]}` in input order.

**Given** `POST /v1/ocr` with a multipart PNG of typed text
**When** called
**Then** it returns `{text}` matching today's `vision_service` output for the same image.

**Given** `ML_RESIDENT_BUDGET_MB=2000` and NLI already resident
**When** an OCR request would push the lazily loaded set past the budget
**Then** `ml` evicts the least recently used lazy model if that is enough, and otherwise returns `503 {"detail":"ml budget exceeded","code":"ml_budget"}`
**And** `app/clients/ml.py` maps 503 to `ModelServiceUnavailable` (a retried error in AD-4).

**Given** the `ml` container started with `--network none`
**When** NLI and OCR are called
**Then** both work offline (weights were baked, no download attempted).

- **Covers:** NFR-1, NFR-2, NFR-3. AR-6. SPIKE-1 decision (xsmall default).
- **Technical notes:** `nli(pairs)` and `ocr(image_bytes)` are added to `app/clients/ml.py` and the fake. Licence register lines for the NLI weights and EasyOCR (code and weights). E2 consumes `nli`. The `-base` swap is E2's decision after EV-2, and changing it must keep the `ml` 2.5g limit. Governed by AD-6, AD-7.
- **Dependencies:** E0-Platform.3.
- **Size:** M

### Story E0-Platform.5: `stt` sidecar with faster-whisper, and voice upload switched to it

As a GM recording a session,
I want voice transcription to run in an `stt` sidecar on faster-whisper,
So that transcription is about 2–4× faster at the same accuracy, uses less memory, and no longer loads Whisper inside a web worker.

**Acceptance Criteria:**

**Given** `src/services/stt/` (FastAPI app plus Dockerfile) with faster-whisper 1.2.1 / ctranslate2 4.8.4 and the `base` model baked in
**When** the container starts with `--network none`
**Then** `GET /healthz` is healthy and `GET /v1/status` shows the model `not_loaded` (loaded on first use).

**Given** `POST /v1/transcribe` with a multipart audio file (webm, ogg, wav, mp3)
**When** called
**Then** it returns `{text, language, segments:[{start_ms,end_ms,text}], rtf}`.

**Given** `POST /v1/transcribe?format=pcm16` with raw PCM16 16 kHz mono bytes and an `initial_prompt`
**When** called
**Then** the bytes are converted to float32 inside the sidecar, the prompt is passed to faster-whisper, and the same response shape is returned.

**Given** `STT_COMPUTE_TYPE=int8` (default) or `float32`
**When** the model loads
**Then** that compute type is used, and the model unloads after 10 min idle (`STT_IDLE_UNLOAD_S=600`).

**Given** `/api/ingest/voice` (`api/routes/ingest.py:67-86`)
**When** a user uploads a recording
**Then** `transcription_service.transcribe` is an async wrapper over `app/clients/stt.py: transcribe(audio, *, initial_prompt=None, format=None)`, the route keeps its 25 MB cap, 422-on-empty and rate limits, and `RecordSessionPage` works unchanged
**And** if `stt` is unavailable the route returns `503 {"detail":"Speech model unavailable"}`.

**Given** `src/backend/requirements.txt`
**When** this story lands
**Then** `openai-whisper` is removed and the per-process Whisper `ThreadPoolExecutor` is deleted.

- **Covers:** NFR-1, NFR-3 ("existing voice upload uses the new STT service"). AR-6, AR-15 (`/api/ingest/voice` calls `stt`). SPIKE-2 decision (base, int8 default with float32 override).
- **Technical notes:** Add the `stt` service to the compose files on the internal network with `STT_MEM_LIMIT`. Add `stt_url` and `stt_compute_type` to `app/core/config.py`. Add a `stt` fake to `app/clients/fakes.py`. The CPU image uses PyPI ctranslate2 wheels and installs no NVIDIA runtime. GPU STT is a separate `gpu` build target used only by `docker-compose.gpu.yml` (E0-Platform.7), built locally and never published (see Decisions). Licence register lines for faster-whisper, ctranslate2 and the Systran `faster-whisper-base` weights (MIT). E4 uses the PCM16 path. Governed by AD-6, AD-1.
- **Dependencies:** E0-Platform.3 (client error types, fake pattern, smoke script).
- **Size:** M

### Story E0-Platform.6: Web and worker image without models: async client wrappers and lifespan cleanup

As a self-hoster,
I want `nlp_service`, `embedding_service` and `vision_service` to become async wrappers over the `ml` client, and the web image to carry no model packages,
So that the web tier stops loading models per worker (about 6.4 GB idle and 11.9 GB peak today) and the event loop is no longer blocked by CPU inference.

**Acceptance Criteria:**

**Given** `app/main.py` lifespan (`:31-41`)
**When** the app starts
**Then** it calls `init_redis()` only, with no `load_nlp_model()` or `load_embedding_model()`, and boot to healthy takes under 10 s without the sidecars up.

**Given** `embedding_service.embed`, `nlp_service.extract_tags` and `vision_service` OCR
**When** called
**Then** each is `async def` and delegates to `app/clients/ml.py`
**And** every caller is updated and awaits it in the same PR: `journal_service.py:84,120`, `api/routes/journals.py:313` (reindex), `api/routes/sources.py:92`, `api/routes/npcs.py:173`, `retrieval_service.py:97`, `source_service.py:56`, `eval_service.py:40-41`, `scripts/eval_retrieval.py:74`, and `/api/ingest/image`.

**Given** a journal save while `ml` is down
**When** `create_journal_entry` runs
**Then** the entry still saves (the existing "must not block" behaviour), tags and embedding are left empty, and a warning is logged. The `journal.reembed` fallback Job is E0-Journal's.

**Given** `src/backend/requirements.txt` and the built web/worker image
**When** `scripts/check_model_packages.py` runs
**Then** it fails if the requirements or `pip list` in the image include torch, spaCy, sentence-transformers, whisper, faster-whisper, easyocr, onnxruntime, kokoro or any TTS package
**And** it passes on this branch, and the `en_core_web_trf` download and the build-essential step are removed from `Dockerfile`/`Dockerfile.prod` (kept only if a remaining dependency needs it on arm64, with the reason commented).

**Given** `docs/RETRIEVAL_EVAL.md`'s reproduce command run against the stack with the `ml` sidecar
**When** the eval runs on the demo campaign
**Then** hybrid@0.65 still gives 14/16 hit@3 and 5/5 gate-holds.

- **Covers:** NFR-3, NFR-2. AR-1. CI-3 (check script).
- **Technical notes:** This supersedes the CPU-torch interim from E0-Platform.2 for web and worker, since torch leaves the image entirely. E0-QA wires `scripts/check_model_packages.py` into CI. The admin System tab gains sidecar `/v1/status` for `ml` and `stt` through `api/routes/admin.py` (a read-only status call; job counts are added by E0-Jobs). The `import-linter` contract that only `app/clients/*` and `llm_provider` talk to models is E0-QA's config. This story makes the code pass it. Governed by AD-1, AD-6.
- **Dependencies:** E0-Platform.3, E0-Platform.4, E0-Platform.5.
- **Size:** L

### Story E0-Platform.7: One 16 GB profile with container limits, GPU override and sum check

As a self-hoster,
I want one compose profile whose container limits add up to 14.5 GB or less, plus an optional GPU override,
So that `docker compose up` fits a 16 GB CPU-only box and a GPU only makes things faster.

**Acceptance Criteria:**

**Given** `.env.example`
**When** this story lands
**Then** it defines `OLLAMA_MEM_LIMIT=5.25g`, `ML_MEM_LIMIT=2.5g`, `TTS_MEM_LIMIT=2.5g`, `STT_MEM_LIMIT=1.25g`, `WEB_MEM_LIMIT=1g`, `WORKER_MEM_LIMIT=1g`, `POSTGRES_MEM_LIMIT=768m`, `REDIS_MEM_LIMIT=128m` and `NGINX_MEM_LIMIT=128m`, and `docker-compose.prod.yml` uses each as `deploy.resources.limits.memory`
**And** the `worker` and `tts` limits are reserved now, so the sum stays true when E0-Jobs adds the worker service and E5 adds `tts`.

**Given** `scripts/check_mem_limits.py`
**When** it parses `.env.example`
**Then** it fails if the sum of `*_MEM_LIMIT` exceeds 14.5 GB or if a compose service lacks a limit variable. It passes at 14.5 GB exactly (CI-14; E0-QA wires it into CI).

**Given** `docker-compose.prod.yml`
**When** the stack starts
**Then** Ollama runs with `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=4096` and `OLLAMA_KEEP_ALIVE=30m`, Postgres with `shared_buffers=192MB`, and Redis with `--maxmemory 96mb --maxmemory-policy noeviction`
**And** the backend runs as `web` (`gunicorn -w 4`) with the 1g limit, and its old 14g limit and the "confirmed live via cgroup memory.peak" comment are updated to the new budget.

**Given** a host with an NVIDIA GPU
**When** I run `docker compose -f docker-compose.prod.yml -f docker-compose.gpu.yml up -d`
**Then** `ollama` and `stt` get a GPU device reservation, `stt` builds its local `gpu` target, and no other service or limit changes.

**Given** a host that runs Ollama natively (the remote desktop's Ollama 0.40.3 serves `lorekeeper` at about 156 tok/s)
**When** `KOBOLD_URL=http://host.docker.internal:11434` is set and the `ollama` service is scaled to 0
**Then** `web` reaches the host Ollama through `extra_hosts: host.docker.internal:host-gateway`, and the docs say the 5.25g reserve still counts toward the host's budget.

**Given** the `diarize` profile
**When** it is defined (by E4)
**Then** `scripts/check_mem_limits.py` excludes it from the sum, as AD-7 states.

- **Covers:** NFR-2 (16 GB profile, D-1a), NFR-1 (one `docker compose up`). AR-7. CI-14 (check script).
- **Technical notes:** The README baseline changes from about 8 GB to 16 GB (`README.md:17`). Raising a limit later means lowering another in the same PR and re-running EV-5. The model install path for `lorekeeper` in the container is the admin installer, which depends on `fix/hf-model-install`. Governed by AD-7.
- **Dependencies:** E0-Platform.6. Soft: the `fix/hf-model-install` branch (outside this plan; needed only to install the model in the containerised Ollama).
- **Size:** M

### Story E0-Platform.8: Per-user rate-limit keying in slowapi and nginx

As a group playing at one table behind one router,
I want AI rate limits keyed per user rather than per IP,
So that four Players on the same Wi-Fi don't share one 10 r/m bucket.

**Acceptance Criteria:**

**Given** `app/core/limiter.py`
**When** this story lands
**Then** it exports `user_or_ip(request)`, which returns `user:<sub>` from a valid bearer JWT (decoded without a DB call, with signature checked) and otherwise the remote address
**And** the existing default key (`get_remote_address`) stays for unauthenticated routes such as auth and share.

**Given** the existing AI and streaming routes (`/api/chat/`, `/api/chat/stream`, journals generate/generate-draft/autocomplete/recap/summarize-session, session-plans generate, settings test/evaluate, ingest voice/image)
**When** two authenticated users from the same IP each send requests at the per-route limit
**Then** neither is throttled by the other's traffic, and a test proves it with two tokens against one `ASGITransport` client address.

**Given** `nginx/nginx.conf`
**When** this story lands
**Then** the `ai_gen` zone keys on `map $http_authorization $lk_rate_key` (a hash of the bearer, falling back to `$binary_remote_addr`), the `api` and `auth` zones are unchanged, and `nginx -t` passes.

**Given** `nginx/locations.conf`
**When** a future AI route has an id in its path
**Then** a commented template shows the anchored regex location form (`location ~ ^/api/x/[0-9a-f-]{36}/y$`), the generic-zone form with `proxy_buffering off` for job, event and file streaming routes, and `/_files/` as `internal`.

- **Covers:** NFR-8 (limits keyed per user, D-5). AR-20.
- **Technical notes:** Feature epics add their own `locations.conf` lines (shared append point). The EV-4 harness that resolves routes against the nginx matching order is E0-QA's. Never log the bearer or its hash. Governed by AD-20.
- **Dependencies:** none (works against today's routes).
- **Size:** S

### Story E0-Platform.9: Multi-arch images, upgrade-safe boot and OCI deploy

As the owner,
I want every image built for `linux/amd64` and `linux/arm64`, a boot that dumps the database before migrating, and an updated OCI deploy script,
So that the x86 desktop and the arm64 OCI host run the same images and a bad migration can be rolled back.

**Acceptance Criteria:**

**Given** `docker-bake.hcl` with targets `web` (also used for worker), `ml`, `stt` and `nginx`
**When** `docker buildx bake --set *.platform=linux/amd64,linux/arm64` runs
**Then** all four build for both platforms (the `stt` `gpu` target is excluded), and `.github/workflows/images.yml` runs the build on every PR and on `main` with no path filter (CI-13).

**Given** the `web` service command
**When** the container boots with a newer image
**Then** it runs `pg_dump` to the `backups` volume (named with the timestamp and the current Alembic revision) before `alembic upgrade head`
**And** if the dump fails, it does not migrate and exits non-zero with a readable log line.

**Given** `scripts/deploy-oci.sh`
**When** it runs against the OCI Ampere A1 host (arm64, 24 GB)
**Then** it pulls the multi-arch tags, uses the same single profile and `.env` limits, and runs the existing one-time model import step
**And** `docs/OCI_DEPLOYMENT.md` documents rollback: restore the pre-upgrade dump with `scripts/restore-db.sh`, then redeploy the previous tag.

**Given** `COMPOSE_PROFILES`
**When** `LOREKEEPER_EDITION=commercial`
**Then** the deploy script refuses to set `COMPOSE_PROFILES=tts` and logs why (AD-16).

- **Covers:** NFR-8 (migrations safe at boot), NFR-1. AR-25. CI-13.
- **Technical notes:** The `worker` service starting after `web` is healthy is E0-Jobs' compose change. This story only provides the `web` health dependency. `images.yml` is a new workflow because buildx is owned by E0-Platform in the boundary map. E0-QA owns the existing test and licence workflows. Governed by AD-7 and the spine's "Containers and deployment".
- **Dependencies:** E0-Platform.7.
- **Size:** M

### Story E0-Platform.10: SPIKE-5 and SPIKE-6 re-run on the remote x86 desktop, limits confirmed

As the owner deciding Phase 0 exit,
I want per-container memory and Ollama throughput measured on x86 with the Docker stack up,
So that the AD-7 limits and the provisional NFR-6 rows rest on measured numbers instead of M-series estimates.

**Acceptance Criteria:**

**Given** the remote CachyOS desktop (RTX 5080 16 GB, Docker plus the NVIDIA toolkit) running the single profile from E0-Platform.7, CPU-only (no GPU override, GPU hidden from containers)
**When** `scripts/spikes/spike5_memory.py` samples cgroup `memory.peak` and `memory.current` for every container
**Then** it records per-container peak RSS for three NFR-2 cases: idle; one heavy Job (an `ml` NLI batch of 50 pairs plus a 7B completion of an extraction-shaped prompt); and a Live-Session case (`stt` transcribing 15 s PCM16 chunks continuously for 10 min while a 7B Rolling-Recap-shaped prompt runs every 60 s)
**And** no container exceeds its limit, the sum of peaks fits 14.5 GB, and any limit that needs to change is changed in `.env.example` together with a matching reduction elsewhere.

**Given** the same box
**When** a pyvips `dzsave(layout="google")` tiling of a 16,000 px JPEG runs inside a 1g-limited container
**Then** peak RSS and wall time are recorded as the E10 input (the spike script runs from a scratch venv and ships nothing).

**Given** the containerised Ollama with `lorekeeper` installed (via the admin installer, needing `fix/hf-model-install`) on CPU, and the native GPU Ollama 0.40.3 for the GPU column
**When** `scripts/spikes/spike6_llm_throughput.py` runs each prompt shape (extraction with Entity lists of 50 and 300, continuity verify, Rolling Recap update, NPC first turn, 300-word recap draft) three times
**Then** it records prompt-processing tok/s, generation tok/s, time to first token and total time per shape, CPU and GPU
**And** it runs the previously skipped structured-extraction test once with Ollama `format` set to a flat JSON schema, recording whether the output validates.

**Given** the measurements
**When** the story completes
**Then** the results go to `_bmad-output/planning-artifacts/spikes/x86-desktop-benchmarks.md` (machine, versions, n, commands) and as rows in `docs/BENCHMARKS.md` in the EV-5 format
**And** the summary states, for each NFR-6 row touched (proposals, continuity, caption lag, recap cadence, NPC first token), whether the provisional target holds, and flags any reset for owner sign-off in `.memlog.md`. It does not change the targets itself.

- **Covers:** NFR-2, NFR-6 (inputs). SPIKE-5, SPIKE-6 (x86 run). EV-5 rows.
- **Technical notes:** The desktop has 16 GB VRAM, and its system RAM may exceed 16 GB. The 16 GB case is enforced through the container limits, not the host. Record the host RAM and note that the measured headroom is valid only under those limits. Postgres and Redis can be reached over Tailscale via `BIND_IP` (E0-Platform.1). Running the backend test suite there needs E0-QA's `TEST_DATABASE_URL` override. The SPIKE-6 script is a measurement harness only. E0-LLM still owns `prompt_budget`, the shortlist decision and any production benchmark wiring (see Decisions). SPIKE-1 and SPIKE-2 x86 re-runs belong to E0-QA and can share the session. Governed by AD-7.
- **Dependencies:** E0-Platform.4, E0-Platform.5, E0-Platform.7. Soft: E0-QA.15 (EV-5 format; if missing, use the RETRIEVAL_EVAL format), the `fix/hf-model-install` branch.
- **Size:** M

## Epic E0-Access: Roles and one Visibility enforcement point

The Owner can invite Players with confidence. Members have Roles, and one enforcement point, `app/access/`, filters every read, write response, search and AI context. Chat and search no longer leak Shorthand. FR-9(b) ships in the same release as FR-7, so the whole epic is released as one unit (parallel plan §4.1).

**Covers:** FR-7, FR-8, FR-9(b), FR-10, FR-41 (`set_visibility` backend), FR-43 (Player-scoped retrieval), FR-44 (invite, change Role and remove, D-4), NFR-5, NFR-7 (`SourceRef`, `grounded`), AR-12, AR-13, AR-18 (members), AR-19 F1-core, AR-26, UX-DR30 (roles part), CI-8, CI-11.

**Role vocabulary used below** (AD-12, AD-13):
- Stored `campaign_role ∈ {co_gm, player}` on `campaign_members`. The Owner has no member row.
- `CampaignContext.role ∈ {gm, player, anon}`. Owner → `gm` with `is_owner=True`. `co_gm` → `gm`. `player` → `player`. A read-only Share Link → `anon`.
- `require_campaign(min_role)` orders `player < gm < owner`. `anon` contexts are built only by the share routes and `audience_ctx`.

### Story E0-Access.1: F1-core migration, with existing Members migrated to Player

**Status:** Open

As an Owner upgrading Lorekeeper,
I want the database to gain Roles, Visibility and Party-only search columns, with every existing Member migrated to Player,
So that from the first boot after the upgrade nobody I invited can see GM content they couldn't see before Roles existed.

**Acceptance Criteria:**

**Given** head `a3e7c1f9d258`
**When** the F1-core revision (from `alembic revision`, `down_revision = a3e7c1f9d258` rebased onto head at merge) runs
**Then** it creates the PG enums `visibility {party, gm, private}` and `campaign_role {co_gm, player}`, and adds:
- `journal_entries`: `kind` (CHECK `gm|player`, default `gm`), `visibility` (default `party`), `party_tsv` TSVECTOR with a GIN index, `party_embedding` Vector(384) nullable;
- `campaign_members`: `role` (default `player`), `access_epoch` int default 0;
- `campaign_share_tokens`: `role` (`campaign_role`, nullable, used only by `collaborate`), `expires_at` timestamptz nullable, `access_epoch` int default 0;
- `chat_sessions`: `archived_at` timestamptz nullable, `npc_entity_id` UUID nullable (no FK yet; F3-world adds it);
- `journal_tags.source_field` (CHECK `shorthand|narrative|manual`, nullable);
- `character_sheets.pc_entity_id` UUID nullable (no FK yet; F3 adds it) and `character_sheets.visibility` (default `party`);
- a `visibility` column on `session_plans`, `source_documents` and `shorthand_terms` (default `gm`) and on `tag_categories` (default `party`).

**Given** existing rows
**When** the revision's set-based SQL runs
**Then** every `campaign_members.role = player`
**And** every `chat_sessions` row whose `user_id` is a member (not the Owner) of its `campaign_id` gets `archived_at = now()`
**And** existing `collaborate` tokens get `role = player`
**And** existing entries keep `kind = gm` and `visibility = party`, and `party_tsv = to_tsvector('english', coalesce(narrative, ''))`
**And** `entry_hash` uniqueness becomes unique on `(campaign_id, user_id, entry_hash)` (AR-17)
**And** a `downgrade()` exists for dev use only. Production is forward-only (NFR-8).

**Given** the CI snapshot from E0-QA.6
**When** `upgrade head` runs on it
**Then** `tests/migrations/test_upgrade_snapshot.py` asserts: both seeded Members are `player`, their chat sessions are archived and the Owner's are not, the collaborate token grants `player`, entry counts and Narratives are unchanged, and every `party_tsv` is non-null where `narrative` is non-null
**And** running `upgrade head` a second time (stamp back, re-apply the data step) changes nothing (idempotent `WHERE` clauses).

**Given** the models
**When** the revision lands
**Then** `app/db/models/*` declare the new columns with `Mapped[]` types, `domain/enums.py`-style StrEnums for `kind` and `source_field` live in `app/access/enums.py` (moved into `domain/enums.py` by E0-WorldCore), and E0-QA.5's model/migration diff test passes
**And** `tests/ev4/fixtures.make_member(role=…)` works (the E0-QA.11 skip is removed).

**Covers:** FR-7 (members → Player, links grant Player, link expiry column), FR-9(b) (archive on migration), AR-12 (new columns), AR-18 (members), AR-19 F1-core, NFR-8.

**Technical notes:** One revision is the F1-core contract that B2's F2 rebases onto. Don't add tables owned by other epics. `party_embedding` is backfilled by E0-Access.7, not here (Alembic holds schema plus set-based SQL only, AD-18). Owner rows stay absent from `campaign_members`. AD-12, AD-18, AD-19.

**Dependencies:** E0-QA.6, E0-QA.11; E0a.2 (E0a ships first). **Size:** L.

### Story E0-Access.2: `CampaignContext`, `require_campaign` and the Role map

**Status:** Open

As a Member of several Campaigns,
I want every request resolved to my Role in that specific Campaign,
So that being a GM in one Campaign never grants anything in another.

**Acceptance Criteria:**

**Given** a new `app/access/` package (`policy.py`, `context.py`)
**When** a route declares `ctx: CampaignContext = Depends(require_campaign("player"|"gm"|"owner"))`
**Then** it resolves `CampaignContext(campaign_id, user_id, role, is_owner, audience, grant_id, access_epoch)`. `grant_id` is the `campaign_members.id` (`None` for the Owner), and `access_epoch` is copied from the grant
**And** collection routes take `campaign_id` as a query parameter
**And** item routes use `require_campaign_for(Model, id_param, min_role)`, which loads the row, resolves its `campaign_id`, then checks the Role
**And** too low a Role, no membership and a missing Campaign or row all raise the same `404 {"detail":"Not found"}` through one `access.not_found()` helper.

**Given** `role_map(db, user) -> dict[campaign_id, role]` and `scoped_select_multi(Model, role_map)`
**When** a cross-Campaign list is built
**Then** each row is filtered by the Role in its own Campaign (the registry predicate arrives in E0-Access.3; until then only membership is applied)
**And** `api/deps.py: get_campaign_with_access` and `accessible_campaign_ids` become thin wrappers marked deprecated. E0-Access.5 removes their callers.

**Given** `GET /api/campaigns/{id}/me`
**When** any Member or the Owner calls it
**Then** it returns `{campaign_id, role: "gm"|"player", is_owner, display_role: "Owner"|"Co-GM"|"Player"}`, and non-members get 404
**And** frontend `hooks/useCampaignRole.ts` (react-query key `["campaignRole", campaignId]`) exposes `{role, isOwner, isGm, isLoading}`. Its gating is cosmetic only.

**Given** `ctx.as_system(reason)` on a `CampaignContext` (Reconciliation RC-6, for E0-Journal.3 and E0-WorldCore.9)
**When** it is called with `reason` in the closed StrEnum `SystemReason {entry_deleted, merge}`
**Then** it returns a ctx with `role="gm"`, `actor="system"`, the caller's `campaign_id` and `user_id`, and `system_reason` set. Any other reason raises `ValueError`
**And** no request dependency can produce a system ctx (`require_campaign` never returns one), and `scripts/check_scoped_queries.py` fails CI on any `as_system(` call outside `journal_service.delete_journal_entry` and `world_service.merge_entities`.

**Given** `access.ctx_for(db, user_id, campaign_id)` (RC-6, used by the Job worker, hook handlers and the backfill runner)
**When** it is called
**Then** it rebuilds the `CampaignContext` that `require_campaign` would build for that user now (current Role, `grant_id`, `access_epoch`), or raises `not_found()` if the user is no longer the Owner or a Member.

**Covers:** FR-7, FR-8 (per-record Role across Campaigns), AR-13 (`CampaignContext`, `require_campaign`, `role_map`, `scoped_select_multi`), AR-24 (`useCampaignRole`), AR-23 (404-never-403).

**Technical notes:** New `app/access/__init__.py` exports the contract names exactly as in parallel plan §3.1. `/me` lives in `api/routes/members.py` (new, E0-Access), mounted under `/api/campaigns`. Frontend: `services/api/members.ts`, `types/members.ts`. AD-13.

**Dependencies:** E0-Access.1. **Size:** M.

### Story E0-Access.3: Access registry, Audiences, `scoped_select` and `audience_ctx`

**Status:** Open

As the owner of the codebase,
I want one registry that declares how each model's Audience is computed, with SQL and Python predicates generated from it,
So that every epic gets Visibility right by registering its tables, not by writing filters.

**Acceptance Criteria:**

**Given** `app/access/registry.py` and `app/access/audience.py`
**When** a model is registered
**Then** it declares exactly one class:
- `stored(column="visibility", owner_field="user_id", kind_field=None, field_visibility=None)`;
- `derived(derive_from=[...])`;
- `always_gm()`.
**And** the Audiences `Public ⊃ Members ⊃ Owner(u) ⊃ GM` map from stored values exactly as AD-12 says: `party` on `kind=gm` → Public, `party` on `kind=player` → Members, `private` → Owner(author), `gm` → GM, with `Owner(a) ⊓ Owner(b) = GM`
**And** `ctx.audience` is GM for `gm`, Members plus Owner(self) for `player`, and Public for `anon`.

**Given** today's tables
**When** this story lands
**Then** each one is registered:
- `journal_entries`: stored, with `kind`;
- `character_sheets`, `session_plans`, `source_documents`, `source_chunks` (derived from document), `shorthand_terms`, `tag_categories`: stored;
- `journal_tags` and `tags` as reached through entries: derived from `journal_entries`, using `source_field` (a `shorthand` tag is GM);
- `chat_sessions`: stored-private with owner `user_id`;
- `npcs` and `quests`: `always_gm` until F3-world copies them into `entities` (Decision B1-D4);
- `campaigns`, `campaign_members`, `campaign_share_tokens`: membership-scoped, with management restricted to the Owner.
**And** `DERIVED_REGISTRY` exists (empty list of derived *file* types, for E0-Jobs and features to append)
**And** the Mention formula `aud(mention) = most_restrictive(entry, entity, field_aud(source_field), visibility_floor)` is implemented as `audience.mention_audience(...)` and unit-tested, ready for E0-WorldCore to register `entity_mentions`.

**Given** `visible_clause(Model, ctx)` (SQL) and `audience_of(obj)` (Python), both generated from the registry
**When** `tests/access/test_registry_property.py` runs (hypothesis, ≥ 200 examples per registered model)
**Then** for random rows and contexts, `row ∈ select(Model).where(visible_clause(Model, ctx))` iff `audience_of(row) ⊒ ctx.audience` (CI-11).

**Given** `scoped_select(Model, ctx)`
**When** a route lists or fetches rows
**Then** it returns `select(Model).where(Model.campaign_id == ctx.campaign_id, visible_clause(Model, ctx))`, and an unregistered model raises at import time.

**Given** `audience_ctx(campaign_id, anon | member | as_user(user_id))`
**When** called from a GM ctx, or by a user for themself
**Then** it returns a reduced `CampaignContext` (role `anon` or `player`, matching Audience, `read_only=True`)
**And** calling it from a Player ctx for another user raises `not_found()`. It is the only reduced-ctx constructor (E7 preview, E8 Player edition and E9 per-recipient stats use it).

**Given** a request whose resolved ctx is GM and which carries the header `X-Lorekeeper-Preview: member` (Reconciliation RC-7, for E7.7)
**When** `require_campaign` resolves the ctx
**Then** it returns `audience_ctx(campaign_id, member)` (read-only, Members Audience, owning nothing), so every read, search and AI context in that request takes the Player read path
**And** for a Player, anon or Share Link request the header is ignored: it can only narrow access and never widen it (a test sends it as a Player and as anon and gets byte-identical responses with and without it)
**And** a write route reached with the header returns `404 {"detail":"Not found"}`, and any other header value is ignored.

**Given** `DERIVED_REGISTRY` (RC-8, for E4.5 and E5)
**When** an epic appends an entry `{derived_type, derive_from: [ref_kind, ...]}`
**Then** non-file derived types are accepted as well as file types (for example E4's `live_recap`, derived from `live_segment`), and a unit test registers a non-file dummy type and checks that `audience_of` returns the most restrictive Audience of its `derived_sources` rows.

**Covers:** FR-8 (one enforcement point, covered records, defaults), AR-12 (Audiences, registry classes, Mention formula, one predicate source), AR-13 (`scoped_select`, `audience_ctx`), CI-11.

**Technical notes:** Field-level visibility (`field_visibility` JSONB) is a registry option that E0-WorldCore turns on for `entities`. `gm_notes` and `npc_settings.voice_notes` are declared `always_gm_fields`. Register `hypothesis` (MPL-2.0) as a dev dependency. AD-12, AD-13.

**Dependencies:** E0-Access.2. **Size:** M.

### Story E0-Access.4: Party projections and a uniform 404 on existing read and write responses, including Share Links with expiry

**Status:** Open

As a Player or a read-only Share Link viewer,
I want every journal, NPC, Quest, tag, Character Sheet and Campaign response to contain only fields and records I may see,
So that hidden content is absent, not blanked, and is indistinguishable from content that doesn't exist.

**Acceptance Criteria:**

**Given** `access.project(obj, ctx)`
**When** a route returns a registered model
**Then** a GM ctx gets `<X>GMResponse` and a Player or anon ctx gets `<X>PartyResponse` from `app/schemas/<domain>.py`
**And** Party schemas omit GM fields entirely: `JournalPartyResponse` has no `shorthand`, and Party NPC and Quest responses have no `notes`
**And** a hidden field renders exactly as when unset (registry defaults), and `field_visibility` never appears in a Party response.

**Given** a Player
**When** they `GET` a GM-only or another user's Private record by id, or a record in a Campaign where they are not a Member
**Then** the response is byte-identical to the one for a random UUID: `404 {"detail":"Not found"}`.

**Given** write routes reachable by a non-GM, and `PUT /api/npcs/{id}` and `PUT /api/quests/{id}` for GMs
**When** they return a body
**Then** the body goes through `project` for the caller's ctx (AR-26 write-response leak).

**Given** `api/routes/share.py`
**When** a read-only token is used
**Then** it resolves through `access.share_ctx(token)` to an `anon` ctx (Public Audience), and the routes use `scoped_select` and `project` (the E0a Public schemas become the `anon` Party projections)
**And** a token whose `expires_at` is in the past, or which is revoked, gets the same 404 as an unknown token
**And** `npcs` and `quests` return empty lists to `anon` and `player` until F3-world (Decision B1-D4), which `tests/test_share.py` reflects, with the field allowlist tests kept.

**Given** a Party record that references a GM-only record (an entry tagged with a tag whose only source is Shorthand)
**When** served to a Player
**Then** the reference is removed and the rest of the record is served.

**Covers:** FR-8 (responses, reference removal, bare-ID fetch = not found), FR-7 (write responses filtered), FR-9(a)/(b) (share responses once FR-8 exists), AR-13 (Party schemas, uniform 404), AR-26, AR-23.

**Technical notes:** Routes touched: `journals.py` (list, get), `npcs.py`, `quests.py`, `tags.py`, `character_sheets.py`, `campaigns.py` (`GET /`, `GET /{id}`), `share.py`. Add probes to `tests/ev4/probes/` for each changed route (standing AC). AD-13.

**Dependencies:** E0-Access.3. **Size:** L.

### Story E0-Access.5: Per-Campaign permission checks replace `accessible_campaign_ids` and inline owner checks

**Status:** Open

As a user who is GM in one Campaign and Player in another,
I want every list, get, tag and delete route to apply my Role in the record's own Campaign,
So that my GM access in Campaign A never applies to Campaign B's records.

**Acceptance Criteria:**

**Given** the call sites of `accessible_campaign_ids` (`journals.py:109,144,156,325`, `tags.py:27`, `sources.py`)
**When** this story lands
**Then** each uses `role_map` plus `scoped_select_multi` (cross-Campaign lists) or `require_campaign_for` (item routes)
**And** journal tag attach and detach and journal delete require `gm` in the entry's Campaign (Player Journal deletes arrive with E7 through `can_write`)
**And** `tags.py` counts only tags on entries visible to the ctx, so a tag whose only use is in GM content does not appear in a Player's list or counts.

**Given** inline owner checks (`Campaign.user_id == user.id` in `campaigns.py` export, analytics and PATCH, and in `journals.py:241` autocomplete)
**When** this story lands
**Then** each is replaced by `require_campaign("owner")` (management) or `require_campaign("gm")` (authoring)
**And** autocomplete therefore works for Co-GMs with Campaign context (previously members got none).

**Given** `scripts/check_scoped_queries.py` and the committed `scripts/scoped_queries_baseline.txt`
**When** CI runs it (a step in `gates.yml`)
**Then** it flags `select(<registered model>)`, `db.get(<registered model>)`, raw SQL naming a registered table, and `Campaign.user_id ==` outside `app/access/`
**And** it fails if a call site is not in the baseline. The baseline lists today's remaining sites after this story and can only shrink (a test fails if it grows) (CI-8)
**And** `accessible_campaign_ids` is deleted.

**Covers:** FR-8 (cross-Campaign Role per record), AR-13 (`role_map` replaces `accessible_campaign_ids`, CI ratchet), AR-26 (`accessible_campaign_ids` routes), CI-8.

**Technical notes:** The baseline file is the shrinking list that the epics after this one (E0-Journal, E0-WorldCore) burn down. Add EV-4 probes for the touched routes, with `cross_gm_player` as the main actor. AD-13.

**Dependencies:** E0-Access.3. **Size:** M.

### Story E0-Access.6: Players are locked out of GM authoring and AI routes, and write rules are enforced

**Status:** Open

As an Owner,
I want Players unable to call GM authoring, AI or management routes, and unable to write anything except what they own,
So that a Player cannot generate, edit or delete GM content even by calling the API directly.

**Acceptance Criteria:**

**Given** a Player ctx
**When** they call `POST /api/npcs/{id}/generate`, `/api/npcs/extract`, `/api/quests/{id}/generate`, `/api/quests/suggest`, `/api/journals/recap`, `/summarize-session`, `/autocomplete`, `/reindex`, `/generate-draft`, `/generate`, `/api/session-plans/generate`, source upload or delete, or any create, update or delete on journals, NPCs, Quests, session plans, shorthand terms, tag categories or sources
**Then** each returns `404 {"detail":"Not found"}` (they all declare `require_campaign("gm")`), with no LLM call made and no hosted usage recorded.

**Given** `access.can_write(ctx, obj)`
**When** a write route checks it
**Then** `gm` may write any row in the Campaign. `player` may write only `journal_entries` with `kind=player` and `user_id = ctx.user_id`, and `character_sheets` whose `pc_entity_id` resolves to an Entity with `linked_user_id = ctx.user_id`. Until F3-world adds `entities`, that sheet check is always false
**And** every refusal is `not_found()`
**And** uniqueness and duplicate checks on non-GM-reachable routes run only over rows visible to the ctx and authored by `ctx.user_id` (no 409 that reveals a hidden row).

**Given** campaign management (Share Links, Roles, members, PATCH and DELETE Campaign)
**When** a Co-GM calls it
**Then** it returns 404. Management is Owner-only (`require_campaign("owner")`).

**Given** a Player who has no paid or granted account
**When** they call Party read routes (`require_campaign("player")` routes that make no hosted-AI call) or redeem a collaborate link with Role `player`
**Then** `require_active_account` does not block them
**And** hosted-AI routes still apply the existing BYOK and quota rules.

**Covers:** FR-7 (Player write rules, other writes = not found, management Owner-only, no paid account for Party routes), FR-8 (GM authoring and AI routes unavailable to Players), AR-13 (`can_write`, uniqueness over visible rows), AR-26 (GM-only route list, records lacking Visibility).

**Technical notes:** Change `main.py`'s router-level `dependencies=gate` to a per-route `require_campaign_paid()` for AI routes, and leave Party reads ungated. Document the change in the route modules. `can_write` is the B2 and B4 contract (E0-Journal edit rules, E7 Player Journals). AD-13.

**Dependencies:** E0-Access.4. **Size:** M.

### Story E0-Access.7: Party-only search and retrieval using `party_tsv` and `party_embedding`

**Status:** Open

As a Player searching the journal or asking the Chronicler,
I want results ranked and matched on Party Narratives only,
So that a word that appears only in the GM's Shorthand can't change what I find or the order I find it in.

**Acceptance Criteria:**

**Given** `retrieval_service.hybrid_search_journal(db, query_text, *, ctx, limit=3, max_distance=0.65, entry_ids: set[UUID] | None = None)`
**When** `ctx.role != "gm"`
**Then** keyword search uses `party_tsv`, vector search uses `party_embedding`, and candidates are restricted by `visible_clause(JournalEntry, ctx)`, plus `kind=player` entries that are the user's own Private entries or are shared with Members (FR-43)
**And** a GM ctx keeps today's `narrative_tsv` and `embedding` behaviour, with the measured 0.65 gate unchanged
**And** `entry_ids`, when given, restricts candidates to those ids after visibility (the E6 NPC Knowledge contract).

**Given** `retrieval_service.register_source(kind, fn)`
**When** retrieval assembles context
**Then** sources are registered providers keyed by `SourceKind`. `journal` and `player_journal` are registered here
**And** `source_service.retrieve_canon_context` becomes the `source_documents` provider, and it returns nothing to non-GM ctx while documents are GM-only.

**Given** journal writes in the existing save and reindex paths (`journal_service.py:120`, `journals.py:299`)
**When** an entry is created, edited or reindexed
**Then** `retrieval_service.index_party_fields(db, entry)` sets `party_tsv = to_tsvector('english', narrative)` and `party_embedding = embed(narrative)` in the same transaction. Embedding failures leave `party_embedding` NULL and never block the save
**And** `scripts/backfill_party_embeddings.py` (idempotent, batches of 50, resumable via `WHERE party_embedding IS NULL`) fills existing rows. Until a row is filled, non-GM vector search skips it and never falls back to `embedding`.

**Given** `GET /api/journals?search=`, `/api/npcs/{id}/entries` and `/api/quests/{id}/entries` (today `shorthand ILIKE`)
**When** a non-GM calls them
**Then** matching uses `party_tsv` or `narrative ILIKE` only, and responses use `JournalLitePartyResponse` (no `shorthand`).

**Given** the keyword `narrative_only: bool = False` on `hybrid_search_journal` (Reconciliation RC-9, consumed by E6.1; built here because E0-Access owns `retrieval_service`)
**When** it is `True`
**Then** keyword and vector search use `party_tsv` and `party_embedding` for every ctx, GM included, so Shorthand never matches or ranks; rows with a NULL `party_embedding` are skipped
**And** the keyword can only narrow: a property test asserts that it never returns a candidate that the same call without it would hide.

**Covers:** FR-9(b) (keyword search, chat retrieval and entry-for-Entity matching rank on Party content only), FR-43 (Player-scoped retrieval incl. own Private entries), FR-8 (AI context only from visible content), AR-13 (`register_source`, `entry_ids`, `party_*` columns), AR-26 (lexical oracles).

**Technical notes:** `embed()` is `embedding_service.embed`. E0-Platform turns it into the async `ml` client wrapper, and this code calls whichever is current (soft dependency). E0-Journal later moves `index_party_fields` into `reindex_entry` and adds the `journal.reembed` Job fallback (B2 contract). This story only adds the one-line calls. EV-4: `assert_counts_and_ranking_unchanged` on each search route. AD-13, AD-17, AD-18.

**Dependencies:** E0-Access.1, E0-Access.3. **Size:** L.

### Story E0-Access.8: Player-safe Chronicler chat with `SourceRef` citations

**Status:** Open

As a Player asking the Chronicler a question,
I want answers, citations and the retrieval trace built only from what I may see, with no glossary and no Shorthand,
So that a GM-only fact gets "not from your journal" and no hint that it exists.

**Acceptance Criteria:**

**Given** `app/schemas/sources.py` (new, append-only)
**When** it lands
**Then** it defines `SourceKind = journal | player_journal | canon_note | entity_field | live_segment | recap`, `SourceRef {kind, id, field?, span?}`, `ResolvedSource {ref, title, quote}` and the response flag `grounded: bool`
**And** only `access.resolve_sources(refs, ctx)` builds `ResolvedSource`, dropping refs the ctx can't see.

**Given** `api/routes/chat.py` `_prepare_chat`, `POST /api/chat/` and `POST /api/chat/stream`, and `chat_service.build_chat_messages`
**When** a Player ctx calls either endpoint
**Then** retrieval uses E0-Access.7's ctx path, and every retrieval candidate in the response (including gated-out ones) is visible to the ctx
**And** responses use `ChatPartyResponse`, `JournalSourceParty` and `RetrievalCandidateParty` schemas with **no `shorthand` field**
**And** canon sources are empty for non-GM ctx (source documents are GM-only)
**And** no Shorthand glossary block is added to the prompt
**And** the SSE `meta` event and the blocking response carry no `system_prompt` or trace prompt
**And** the "no relevant entries" grounding note still goes in the final user turn (`chat_service.py:139-158` convention).

**Given** a GM ctx
**When** chatting
**Then** behaviour is unchanged (full sources, glossary, trace), now built through `ctx`.

**Given** chat session storage
**When** an assistant message is saved
**Then** `chat_sessions.messages[*]` stores `{role, content, refs: SourceRef[], grounded}` and no snippets or titles
**And** on read (`GET /api/chat/sessions/{id}`) and before replaying history into a prompt, `access.project` redacts any message whose refs are no longer all visible to the ctx and leaves it out of the replay
**And** sessions with `archived_at` set are absent from a Player's list, return 404 to a Player fetch or POST, and are never replayed (a GM ctx of the same user may read them read-only).

**Given** `access.register_resolver(kind: SourceKind, fn)` (Reconciliation RC-10)
**When** `resolve_sources(refs, ctx)` meets a ref
**Then** it calls the resolver registered for `ref.kind` to build title and quote. `journal` and `player_journal` are built in here; later epics append one line each (`entity_field` in E0-WorldCore.5, `canon_note` in E2.1, `live_segment` in E4.2)
**And** visibility is still checked in `access` before any resolver runs, so a resolver can never return a ref the ctx can't see
**And** a ref whose kind has no registered resolver is dropped (fail closed) and logged once as `resolver_missing`.

**Covers:** FR-9(b) (chat sources, candidates, canon sources, system prompt, glossary; blocking and streaming), FR-43, NFR-7 (`SourceRef`, `ResolvedSource`, `grounded`), AR-13 (stored AI output, no trace for non-GM), AR-23 (citations convention), AR-26.

**Technical notes:** Owned files: `chat.py`, `chat_service.py`, `schemas/sources.py`, `schemas/chat.py` additions. Legacy messages without `refs` are treated as `refs=[]` (visible only to their author's GM ctx). Tests stub `llm_provider.stream_messages` and `complete_messages` until E0-LLM's fake provider lands. AD-13, AD-8 (grounding in the final user turn).

**Dependencies:** E0-Access.4, E0-Access.7. **Size:** L.

### Story E0-Access.9: `set_visibility`, the only Visibility writer

**Status:** Open

As a GM,
I want one backend operation that changes the Visibility of any record or field, applies on the next read and invalidates anything derived from it,
So that publishing to Players is deliberate and nothing stale leaks after I hide something.

**Acceptance Criteria:**

**Given** `access.set_visibility(db, ctx, ref: SourceRef | RecordRef, value: Visibility, *, field: str | None = None)`
**When** a GM ctx calls it
**Then** it validates the ref is in `ctx.campaign_id` and registered as `stored`, writes `visibility` (or `field_visibility[field]` for models with field visibility, or `visibility_floor`), and returns the projected record
**And** a Player or anon ctx gets `not_found()`
**And** `always_gm` models and `always_gm_fields` (`gm_notes`, `voice_notes`) raise 422 `{"detail":"This is always GM-only","code":"always_gm"}`.

**Given** a model whose registry entry names a `writer` (E0-WorldCore will register `world_service.apply_change` for Canon tables)
**When** `set_visibility` targets it
**Then** the write goes through that writer instead of a direct UPDATE.

**Given** the extension points `access.register_stale_marker(fn)` and `access.register_visibility_listener(fn)`
**When** a visibility change commits in the same transaction
**Then** each stale marker is called with `(db, ref)` (E0-Jobs registers the `derived_sources` marker) and each listener is called with `(campaign_id, refs, actor_ctx)` (E0-Journal registers the `visibility_changed` hook dispatch)
**And** with none registered, the change still commits and a test asserts the call order.

**Given** `POST /api/campaigns/{campaign_id}/visibility` (new, `api/routes/visibility.py`), body `{items: [{kind, id, field?}], value}`, up to 500 items
**When** a GM calls it
**Then** all items change in one transaction (all-or-nothing). The response is `{updated: n}`, or 404 if any item isn't found
**And** `cache` keys for affected reads are invalidated (E0-Access.10 key scheme).

**Given** `access.mark_dependents_stale(db, refs)` (Reconciliation RC-11, for E0-WorldCore.3)
**When** `set_visibility` commits a change, or `world_service.apply_change` changes Canon
**Then** both call this one public helper, which runs every registered stale marker for the refs inside the caller's transaction. It is the only staleness entry point that code outside `app/access/` may call.

**Given** `scripts/check_scoped_queries.py`
**When** it scans for writes to `visibility`, `field_visibility` or `visibility_floor`
**Then** it allows exactly one `visibility_floor` write outside `app/access/`: `world_service.apply_change(op="merge")` under a `merge` system ctx (AD-10, Decision B3-D7). The allowlist entry names that function, and any other write fails CI.

**Covers:** FR-41 (backend: set Visibility of any record or field, bulk, applies on next read, derived invalidation seam), FR-8, AR-13 (`set_visibility` sole writer, marks derived dependents stale, queues `visibility_changed`).

**Technical notes:** `scripts/check_scoped_queries.py` gains a rule that flags any assignment to a `visibility`, `field_visibility` or `visibility_floor` attribute outside `app/access/`. The bulk route is the contract E7's bulk controls call (Decision B1-D6). EV-4 probe: Player and anon get 404, and a Party → GM change hides the record on the very next Player read. AD-12, AD-13.

**Dependencies:** E0-Access.4. **Size:** M.

### Story E0-Access.10: Grant changes bump `access_epoch` and close open streams

**Status:** Open

As an Owner who changes a Member's Role, removes a Member or revokes a link,
I want the change to apply on that person's next request and any open stream of theirs to close,
So that a demoted Player can't keep reading GM content through a chat stream that was already open.

**Acceptance Criteria:**

**Given** a role change, member removal, token revocation or token expiry
**When** it commits
**Then** the grant's `access_epoch` is incremented (for expiry, lazily, when the token is next resolved), and `access.publish_grant_change(campaign_id, grant_id)` publishes to Redis channel `access:{campaign_id}:{grant_id}` after commit.

**Given** `access.grant_watch(ctx)`, an async helper
**When** a streaming route uses it
**Then** it resolves as soon as an `access:` message for that grant arrives, or a 15 s poll finds the grant missing or with a different `access_epoch`
**And** `POST /api/chat/stream` checks it between chunks, aborts the upstream LLM request, and ends with an SSE `error {"detail":"Not found"}` event.

**Given** cached reads
**When** any cache key is built
**Then** it includes the ctx audience and `access_epoch`
**And** `cache:journals:{user_id}` is removed (`redis_client` callers updated), so a demoted Member never sees a cached GM view.

**Given** a JWT that is still valid for a removed Member
**When** they call any Campaign route
**Then** they get 404 on that request (no session state is trusted).

**Covers:** FR-44 (Role change or removal takes effect on next request; open streams close), AR-13 (grant changes, caches), FR-7.

**Technical notes:** `access:` is an access-control channel published only by `app/access/`. It is separate from B2's three feature channels in `core/pubsub.py` (Decision B1-D7). B2's `core/sse.py: sse_response` and B5's WS use `grant_watch` to close. AD-5, AD-13.

**Dependencies:** E0-Access.2, E0-Access.8. **Size:** M.

### Story E0-Access.11: Campaign events route and `useCampaignEvents`

**Status:** Open

As a Member with the app open,
I want Campaign changes (visibility, Roles, later Canon) pushed to my browser as invalidations,
So that my screens refresh without a reload and never keep showing something I may no longer see.

**Acceptance Criteria:**

**Given** `GET /api/campaigns/{id}/events` (new, `api/routes/events.py`, `require_campaign("player")`)
**When** a Member connects with a bearer header
**Then** the response is `text/event-stream` with `X-Accel-Buffering: no`, a `ping` every 15 s, and one `invalidate` event per message on Redis channel `campaign:{campaign_id}:events` (payload `{domain, id}`; the channel name is B2's contract)
**And** messages are only `{domain, id}` keys. Downgrade and delete invalidations carry no id, so they reveal nothing to the recipient
**And** the stream closes when `grant_watch(ctx)` fires.

**Given** `set_visibility` (E0-Access.9) and grant changes (E0-Access.10)
**When** they commit
**Then** an unkeyed `{domain: "visibility"}` or `{domain: "role"}` invalidation is published to `campaign:{id}:events`, throttled to at most 1 per second per Campaign.

**Given** frontend `hooks/useCampaignEvents.ts`
**When** a page mounts it with a `campaignId`
**Then** it opens the stream with the bearer header (fetch plus ReadableStream, no EventSource, no `?token=`), reconnects with backoff, and calls `queryClient.invalidateQueries({queryKey: [domain, campaignId]})` for each event
**And** a `role` event also invalidates `["campaignRole", campaignId]`.

**Given** nginx
**When** the route is registered
**Then** `locations.conf` has a location for `/api/campaigns/<id>/events` in the generic `api` zone with `proxy_buffering off` and `proxy_read_timeout 1h`, and an EV-4 probe shows a Player receives no ids for hidden records.

**Covers:** AR-5 (campaign events route, unkeyed downgrade invalidations), AR-13, AR-20 (generic zone, buffering off), AR-24 (`useCampaignEvents`).

**Technical notes:** B2 owns `core/sse.py`, `core/pubsub.py` and `lib/sse.ts`, and they come later in the build DAG. This story writes SSE frames with a small local generator in `events.py`, and keeps the stream reader inside `useCampaignEvents.ts`. B2's stories swap in `sse_response` and `lib/sse.ts` with a one-line change each (Decision B1-D8). AD-5, AD-13, AD-20.

**Dependencies:** E0-Access.9, E0-Access.10. **Size:** M.

### Story E0-Access.12: Members API and Roles in Sharing › Members

**Status:** Open

As an Owner,
I want to invite people with a Role, change a Member's Role and remove Members from Sharing › Members,
So that I decide exactly who is a Co-GM and who is a Player.

**Acceptance Criteria:**

**Given** `api/routes/members.py` (all `require_campaign("owner")`)
**When** the Owner calls the members endpoints
**Then** these exist:
- `GET /api/campaigns/{id}/members`: `[{member_id, user_id, display_name, role, joined_at}]`, plus the Owner as a synthetic `{role: "owner"}` row;
- `PATCH /api/campaigns/{id}/members/{member_id}`, body `{role: "co_gm"|"player"}`;
- `DELETE /api/campaigns/{id}/members/{member_id}` (keeps today's `?delete_entries` behaviour).
**And** `POST /api/campaigns/{id}/share` accepts `{kind: "collaborate", role: "co_gm"|"player" = "player", expires_at?: datetime}` and `{kind: "read_only", expires_at?}`, and `GET` lists `role` and `expires_at`
**And** redeeming a collaborate link (`POST /api/share/{token}/join`) creates the member with the token's `role`, and an expired or revoked token gets 404
**And** the old member routes in `campaigns.py` move into `members.py` at the same paths, so existing frontend calls keep working.

**Given** the Owner
**When** anyone tries to demote or remove the Owner
**Then** there is no member row for the Owner, so it cannot happen. The synthetic Owner row has no PATCH or DELETE (404).

**Given** a Member demoted from `co_gm` to `player`
**When** the PATCH commits
**Then** all their `chat_sessions` in that Campaign (including NPC Conversations, `npc_entity_id IS NOT NULL`) get `archived_at = now()`, their `access_epoch` is bumped, and the grant-change publish fires (E0-Access.10)
**And** their existing entries stay `kind=gm` and `visibility=party`, and become editable only by GMs.

**Given** `pages/SharingPage.tsx` › Members
**When** the Owner views it
**Then** each Member shows a Role badge (`RoleBadge` from E0-UX if present, otherwise a text badge with the same label) and a Role select, plus Remove
**And** choosing Player for a Co-GM shows the inline notice "Their NPC Conversations and chat history in this Campaign will be archived." before confirming (EXPERIENCE.md role-change notice)
**And** creating a collaborate link offers Role (default Player) and an optional expiry date, and read-only links offer an optional expiry
**And** the UI uses theme tokens only, works at 375 px, is keyboard operable with visible focus, and shows EmptyState, loading and error states.

**Covers:** FR-44 (invite with Role, change Role, remove; D-4 part), FR-7 (link stores Role, default Player, optional expiry; Owner always GM; management Owner-only), FR-9(b) (demotion archives chat sessions and NPC Conversations), UX-DR30 (roles part: invite with Role, change Role with archive notice, remove, link expiry, Role badges).

**Technical notes:** Linking a Player to a PC is E7 (D-4). Frontend: `hooks/useSharing.ts` extended, `services/api/members.ts`. EV-4: `tests/ev4/probes/members.py` (Co-GM and Player get 404 on all management routes). AD-12, AD-13, AD-18.

**Dependencies:** E0-Access.6, E0-Access.10. **Size:** M.

### Story E0-Access.13: Analytics and export cover every Member, scoped by Role

**Status:** Open

As a GM,
I want Campaign analytics and export to include every Member's entries, and Players to get the same views limited to what they may see,
So that the numbers and the export reflect the whole group's Campaign without exposing GM content.

**Acceptance Criteria:**

**Given** a Campaign with entries from the Owner and two Members
**When** a GM calls `GET /api/campaigns/{id}/analytics` or `GET /api/campaigns/{id}/export?format=markdown|pdf`
**Then** totals and the export include all three authors' entries (previously owner-only via the inline `Campaign.user_id` check).

**Given** a Player
**When** they call the same routes (`require_campaign("player")`)
**Then** analytics are computed with `scoped_select(JournalEntry, ctx)`, so counts, per-Session totals, tag rankings and contributions use only Party entries plus the Player's own Private entries
**And** the export contains only Party Narratives (no Shorthand, no GM-only entries, no NPC or Quest notes), rendered through the Party projections.

**Given** EV-4
**When** `tests/ev4/probes/campaigns.py` adds a GM-only entry with a unique tag
**Then** the Player's analytics totals, tag ranking and export are unchanged (`assert_counts_and_ranking_unchanged`, `assert_no_canary` on the exported bytes).

**Covers:** FR-10, FR-8 (stats and export within Visibility), NFR-5.

**Technical notes:** `campaigns.py` analytics and export scope only. E8 replaces the export with Chronicle, and E9 replaces analytics with Stats. Both reuse this scoping via `audience_ctx`. AD-13.

**Dependencies:** E0-Access.4, E0-Access.5. **Size:** M.

### Story E0-Access.14: OPTIONAL (pending owner decision OD-1): Legacy NPCs and Quests stay visible to Players during the upgrade gap

**Status:** Optional. Pending owner decision OD-1. Drop this story in only if the owner picks option B. With option A (the default, Decision B1-D4) this story is not built.

As a Player in an existing Campaign,
I want the NPC and Quest lists I could already see to stay visible after the E0-Access release,
So that the upgrade doesn't empty my view of the world until the GM republishes it.

**Acceptance Criteria:**

**Given** the F1-core revision (folded into E0-Access.1's revision if that has not merged yet, otherwise a small E0-Access revision directly on F1-core and before F2-jobs-files)
**When** it runs
**Then** `npcs` and `quests` gain `visibility` (the PG enum) `NOT NULL DEFAULT 'party'`, and existing rows get `party`
**And** the registry entries for `npcs` and `quests` change from `always_gm` to `stored`, with `notes`, `secrets` and any GM note field declared `always_gm_fields`.

**Given** a Player or a Share Link visitor
**When** they read `/api/npcs`, `/api/quests` or the share routes
**Then** Party rows are returned through the existing Party schemas (E0-Access.4) with GM-only fields absent, and GM-only rows return the uniform 404
**And** a GM can hide a legacy row through `set_visibility` (E0-Access.9) before F3-world exists.

**Given** the F3-world copy (E0-WorldCore.2)
**When** it runs after this story
**Then** each Entity's `visibility` is copied from the legacy row instead of `gm`, so a row the GM had hidden stays hidden and a Party row stays Party
**And** the release notes say which option shipped.

**Given** the standing ACs
**When** the story ships
**Then** the EV-4 probes for `/api/npcs`, `/api/quests` and the share routes (E0-QA.13) run the canary family against Party and GM-only legacy rows.

**Covers:** FR-5 (assumption on legacy visibility), FR-8, FR-9(b) (Party projection for legacy rows), AR-18 (option B), NFR-5.

**Technical notes:** Option B of Decision B1-D4. It is temporary: E0-WorldCore freezes `npcs`/`quests` after the copy, so the column is read only by the copy and the legacy adapters. It needs no frontend change. B3 already ships the bulk-publish route (`POST /api/entities/visibility`, E0-WorldCore.5/.10), which covers option A's "republish" path, so option B is about the gap between the E0-Access and E0-WorldCore releases only.

**Dependencies:** E0-Access.1, E0-Access.3, E0-Access.4, E0-Access.9. **Size:** S.

## Epic E0-Jobs: Background Jobs with visible progress

GMs and Players never wait on a blocked request: long work runs as Jobs that survive restarts, report stage, progress and ETA within 5 s, and can be retried; files are stored and served safely.

### Story E0-Jobs.1: F2-jobs-files revision and models

As a developer building any Job-producing feature,
I want the `jobs`, `data_backfills`, `stored_files` and `derived_sources` tables created by one F2 revision on top of F1-core,
So that every later epic has one authoritative job record and file record to build on.

**Acceptance Criteria:**

**Given** the Alembic head is the F1-core revision (E0-Access)
**When** `alembic revision` creates F2-jobs-files and `alembic upgrade head` runs on an empty DB and on a seeded `a3e7c1f9d258` snapshot
**Then** it creates:
- `jobs(id uuid, campaign_id, kind, queue, status, priority, payload jsonb, idempotency_key, ctx_kind, ctx_user_id, ctx_audience, access_epoch, attempts, max_attempts default 3, progress real, stage text, eta_seconds int, error_code, error_message, result_ref jsonb, depends_on_job_id, worker_id, heartbeat_at, created_by, created_at, started_at, finished_at, next_run_at)`;
- a partial unique index on `idempotency_key` where `status IN ('queued','running')`, and indexes on `(campaign_id, status, created_at)` and `(status, queue, created_at)`;
- `data_backfills(name unique, status, cursor jsonb, job_id, updated_at)`;
- `stored_files(id, campaign_id, kind, storage_key, content_type, size, sha256, audience_owner_id, cache_key, stale, created_by, created_at)` with `cache_key` unique per `(campaign_id, kind)` where `stale = false`;
- `derived_sources(derived_type, derived_id, ref_kind, ref_id, ref_field)` indexed on `(ref_kind, ref_id)`
**And** the single-head check and FK-action test pass.

**Given** `app/jobs/errors.py` and `app/domain/enums.py` StrEnums for `JobStatus {queued, running, done, failed, cancelled}`, `JobQueue {interactive, onsave, backfill}` and `JobErrorCode`
**When** the migration is generated
**Then** the CHECK constraints come from those StrEnums, and the CI-10 sync test covers them.

**Given** `access/registry.py`
**When** the models register
**Then** `jobs` is `always_gm` with an owner read rule (`created_by = ctx.user_id` for non-GMs), `stored_files` is `derived` (audience from `derived_sources`), and `derived_sources` and `data_backfills` are `always_gm`
**And** the models are exported from `app/db/models/__init__.py`.

- **Covers:** FR-1 (durable record), AR-2, AR-14 (tables), AR-19 F2-jobs-files.
- **Technical notes:** AD-19 fixes F2 as one revision with four tables, so the files tables land here even though the file service comes in E0-Jobs.8 (see Decisions). `JobErrorCode` starts with `llm_config`, `ai_output_unusable` (the code of E0-LLM's `StructuredOutputError`; Reconciliation RC-4 renamed it from `structured_output`), `permission_changed`, `model_unavailable`, `llm_unavailable`, `llm_busy`, `timeout`, `interrupted`, `internal`, and is append-only. Governed by AD-2, AD-4, AD-14, AD-19.
- **Dependencies:** E0-Access.1 (F1-core revision), E0-Access.3 (access registry).
- **Size:** M

### Story E0-Jobs.2: `enqueue` with outbox push and the kind registry

As a feature developer,
I want one `enqueue(db, ctx, kind, payload, *, idempotency_key)` function that writes the row and pushes to RQ only after commit,
So that a Job is never lost to a rolled-back transaction or a Redis flush, and never runs twice for the same content.

**Acceptance Criteria:**

**Given** `app/jobs/registry.py` with a `JobKind(queue, timeout_s, resources ⊆ {llm,nli,ocr,stt,tts,cpu_heavy}, live_safe, result_audience)` entry per kind
**When** `enqueue` is called with an unregistered kind, a payload containing a key named like a secret (`api_key`, `token`, `password`), or no `idempotency_key`
**Then** it raises `ValueError` and writes nothing.

**Given** a request that calls `enqueue` and then commits
**When** the transaction commits
**Then** an `after_commit` listener pushes `job_id` (and only `job_id`) to the RQ queue named by the registry entry
**And** if the transaction rolls back, nothing is pushed and no row exists.

**Given** a `queued` or `running` Job with `idempotency_key = "extraction.run:{journal_id}:{entry_hash}"`
**When** `enqueue` is called again with the same key
**Then** it returns the existing `job_id` and creates no row. Once that Job is `done`, the same key creates a new row.

**Given** `JOBS_EAGER=1` (tests)
**When** `enqueue` commits
**Then** the handler runs in-process after commit through the same wrapper path, so tests see final row state with no worker.

**Given** a route that starts a Job
**When** it returns
**Then** the response is `202 {"job_id"}` in under 1 s (a test asserts the route does no model work).

**Given** `enqueue(..., depends_on_job_id=<job_id>)` (Reconciliation RC-1, for E2.3)
**When** the dependency is still `queued` or `running`
**Then** the dependent row is written `queued` with `depends_on_job_id` set and is not pushed to RQ
**And** when the dependency reaches any terminal status (`done`, `failed` or `cancelled`), an after-commit step pushes every dependent, so the dependent runs whatever the outcome. The handler reads the outcome from `job.dependency_status`
**And** when the dependency is already terminal at enqueue time, the dependent is pushed at once, and a dependency in another Campaign raises `ValueError`.

- **Covers:** FR-1 (Job ID in < 1 s, no raw keys queued), NFR-9. AR-2, AR-4 (idempotency).
- **Technical notes:** A built-in `system.noop` kind (queue `interactive`, no resources) exists for tests and the tray demo. `rq==2.12.0` goes into the register. `enqueue` has no `queue` argument. Governed by AD-2, AD-4.
- **Dependencies:** E0-Jobs.1, E0-Access.2 (`CampaignContext`).
- **Size:** M

### Story E0-Jobs.3: `LorekeeperWorker`: ctx rebuild, LLM config, retries and the worker service

As a GM,
I want background Jobs to run as me with my current permissions and my LLM configuration, and to retry sensibly,
So that a demoted user's queued Job can't act with old rights, and a missing API key fails clearly instead of looping.

**Acceptance Criteria:**

**Given** a `worker` compose service from the backend image running `rq worker` with `LorekeeperWorker`, 2 processes, `WORKER_MEM_LIMIT`, `depends_on: web: service_healthy`
**When** a queued Job is picked up
**Then** the wrapper opens a fresh DB engine after fork, one session per Job, sets `status=running`, `started_at`, `worker_id`, and calls `async def handle(job, ctx, db)` via `asyncio.run`.

**Given** the Job's stored `ctx_kind`, `ctx_user_id`, `ctx_audience` and `access_epoch`
**When** the starter's membership or role no longer grants the rights recorded
**Then** the Job fails with `error_code=permission_changed`, no retry, and the handler is never called.

**Given** a kind with `llm` in `resources`
**When** the Job starts
**Then** the wrapper calls `llm_config_service.resolve_llm_config(db, user)`. An `LLMConfigError` fails it with `llm_config` and the readable reason "No AI model is configured for your account", no retry. After a hosted completion, the handler calls `record_hosted_usage`.

**Given** a handler that raises `ModelServiceUnavailable`, `LLMUnavailable`, `llm_busy` or any other exception
**When** attempts < `max_attempts` (3)
**Then** the row returns to `queued` with `next_run_at` +10 s after the first failure and +60 s after the second, RQ runs with `retry=None`, and after the third failure the row is `failed` with `error_code` and a readable `error_message`
**And** `StructuredOutputError` fails immediately with `ai_output_unusable` ("AI output unusable").

**Given** a running Job
**When** the handler runs
**Then** a thread updates `heartbeat_at` every 10 s, sync CPU work runs through `asyncio.to_thread`, a handler can call `job.report(progress, stage, eta_seconds)` to write the row, and logs carry `job_id`, `kind` and `campaign_id` without tokens or Shorthand
**And** a Job exceeding the registry `timeout_s` fails with `timeout` (retried per the rules above).

**Given** the Journal Entry that triggered a Job
**When** the Job fails for any reason
**Then** the entry remains saved and unchanged (test with a failing `system.noop` variant).

**Given** E0-LLM's `errors.RETRYABLE`, `errors.TERMINAL` and `llm_gate.class_for_queue` (Reconciliation RC-4)
**When** the wrapper runs a Job
**Then** it classifies every `LLMError` by those exports and writes its `code` (`llm_config`, `ai_output_unusable`, `llm_busy`, `llm_unavailable`) as `error_code`, and a test asserts that every `LLMError.code` is a `JobErrorCode` member
**And** `JobKind` gains an optional `gate_class`. Before calling the handler, the wrapper sets the contextvar `llm_gate.current_class` to the kind's `gate_class` when declared (for example `live.recap → live_recap`), otherwise to `class_for_queue(queue)` (`interactive → gm_interactive`, `onsave → job_onsave`, `backfill → job_backfill`), and resets it afterwards.

- **Covers:** FR-1 (owner's LLM config at run time, metering, config failures not retried, ≤ 2 retries, entry stays saved), NFR-9. AR-2, AR-4.
- **Technical notes:** `llm_config_service` and the `LLMError` family belong to E0-LLM. If E0-LLM has not merged yet, the wrapper imports `deps.get_user_llm_config`'s resolution through a thin adapter that E0-LLM replaces (see Decisions). Files: `app/jobs/worker.py`, compose `worker` service in `docker-compose.yml` and `docker-compose.prod.yml`. Governed by AD-2, AD-4.
- **Dependencies:** E0-Jobs.2, E0-Access.2 (`ctx_for`), E0-LLM.1 (`resolve_llm_config`, `errors.RETRYABLE`/`TERMINAL`), E0-LLM.2 (`class_for_queue`, `current_class`). Soft: E0-Platform.7 (reserves `WORKER_MEM_LIMIT`; if it hasn't merged, this story adds the variable at 1g and keeps the sum).
- **Size:** L

### Story E0-Jobs.4: Reaper and restart recovery

As a GM whose server was restarted mid-Job,
I want queued Jobs to be re-pushed and interrupted Jobs to resume or fail visibly,
So that no Job is ever silently lost.

**Acceptance Criteria:**

**Given** a `queued` row older than 60 s that RQ does not hold (for example, after `redis-cli FLUSHALL`)
**When** the reaper (every 30 s in every worker, coordinated by a Redis lock so only one runs at a time) ticks
**Then** it re-pushes the `job_id`, and the Job runs once.

**Given** a `running` row whose `heartbeat_at` is more than 60 s old and whose `worker_id` is absent from RQ's worker registry
**When** the reaper ticks
**Then** the row is requeued if attempts remain, or marked `failed` with `error_code=interrupted` and "Interrupted by a restart" if not.

**Given** a `queued` row whose `next_run_at` is in the future
**When** the reaper ticks
**Then** it pushes the row only once `next_run_at` has passed.

**Given** a test that kills a worker process mid-Job, and a test that restarts web while a Job runs
**When** recovery completes
**Then** the first Job is requeued or failed visibly, the second finishes normally (web restarts don't affect the worker), and no duplicate `done` rows exist.

**Given** a `queued` dependent whose `depends_on_job_id` Job is terminal but which was never pushed (Reconciliation RC-1)
**When** the reaper ticks
**Then** it pushes the dependent once, so a crash between the dependency finishing and the push never strands it.

- **Covers:** FR-1 (survives restarts; resume or fail visibly). AR-2 (reaper), AR-4 (stale rows).
- **Technical notes:** In `app/jobs/worker.py` (reaper loop) and `app/jobs/enqueue.py` (re-push helper). The retry delays from E0-Jobs.3 rely on the reaper honouring `next_run_at`. Governed by AD-2, AD-4.
- **Dependencies:** E0-Jobs.3.
- **Size:** M

### Story E0-Jobs.5: Queue priority, per-model serialisation, cursor backfills and Live admission

As a GM in a shared server,
I want interactive work to go first, heavy models to run one Job at a time, and backfills to yield after every entry,
So that another Campaign's backfill never delays my on-save Job by more than one Job, and a Live Session isn't slowed by background work.

**Acceptance Criteria:**

**Given** the three queues `interactive`, `onsave` and `backfill`
**When** each worker process dequeues
**Then** it listens in that priority order, and a test with 5 backfill Jobs queued before 1 onsave Job shows the onsave Job starts after at most one backfill Job.

**Given** two queued Jobs whose kinds both declare `nli` (or `stt`, `tts`, `ocr`, `cpu_heavy`)
**When** both worker processes pick them up
**Then** a Redis resource lease (`jobs/admission.py`, key `res:<resource>`) lets one run, and the other goes back to `queued` with `next_run_at` +5 s and its `stage` set to "Waiting for the model"
**And** `llm` is not leased here, because E0-LLM's `llm_slot` serialises it.

**Given** a cursor backfill kind
**When** its handler processes one entry
**Then** it records per-entry progress (`progress = done/total`, `stage = "Entry 12 of 140"`) on the same row, updates `data_backfills.cursor`, and re-enqueues itself with the next cursor on the `backfill` queue keeping the same `job_id` lineage visible as one row in the tray
**And** a helper `run_cursor(job, ctx, db, *, select_next, process_one)` in `app/jobs/backfill.py` implements this for consumers.

**Given** `jobs/admission.py` `hold(name, ttl)`, `renew(name)` and `release(name)`
**When** E4 holds the `live` lease (TTL 90 s)
**Then** workers skip every kind whose `resources` intersect `{llm, nli, tts, cpu_heavy}` unless `live_safe`, putting it back with `next_run_at` +15 s, and resume when the lease lapses
**And** `rq suspend` is not used anywhere (a grep test).

**Given** `jobs/backfill.py: register_backfill(name, kind)` and a `data_backfills` row with `status = pending`, for example `suggested_mentions_v1` written by the F3-world revision (Reconciliation RC-2, for E0-WorldCore.7)
**When** a worker starts, and on every reaper tick until the row is `done`
**Then** the runner enqueues the registered kind once per Campaign that existed when the row was written, with the Campaign Owner's GM ctx (`access.ctx_for(owner_user_id, campaign_id)`), idempotency key `backfill:{name}:{campaign_id}`, on the `backfill` queue
**And** `data_backfills.cursor` records the Campaigns already enqueued and finished, so a restart never runs a Campaign twice, and the row becomes `done` once every Campaign's Job is terminal. A failed Campaign is listed in `cursor.failed` and shows in that Owner's tray
**And** a row whose name has no registered kind logs `backfill_unregistered` once and stays `pending`.

- **Covers:** FR-1 (one at a time per model, priority, one-Job bound), NFR-11. AR-3.
- **Technical notes:** Cursor backfills are the contract for B3 (FR-18, `backfill.mentions`). The Live admission contract is for B5 (E4). One row per backfill: the Job re-pushes its own `job_id` with a new cursor rather than creating new rows, which matches "one Job with per-entry progress". Governed by AD-3.
- **Dependencies:** E0-Jobs.4, E0-Access.2 (`ctx_for` for the backfill runner).
- **Size:** M

### Story E0-Jobs.6: `core/pubsub.py` and `core/sse.py`

As a feature developer,
I want one publisher with exactly three channels and one SSE response helper,
So that no feature invents its own channel or polling endpoint, and every stream pings, avoids buffering and closes when access is revoked.

**Acceptance Criteria:**

**Given** `app/core/pubsub.py`
**When** code publishes
**Then** only `publish_job(campaign_id, event)`, `publish_campaign_event(campaign_id, domain, id | None)` and `publish_live(live_session_id, msg)` exist, mapping to `jobs:{campaign_id}`, `campaign:{campaign_id}:events` and `live:{id}:out`, and a test fails if any other `PUBLISH` call exists outside this module.

**Given** a worker updating a Job's status, progress, stage or ETA
**When** the row changes
**Then** a `job` event `{job_id, kind, status, progress, stage, eta_seconds, error_code, error_message, result_ref}` is published on `jobs:{campaign_id}` after commit, throttled to at most one progress event per Job per second (status changes are never throttled).

**Given** `publish_campaign_event` for a downgrade or delete
**When** called with `id=None`
**Then** it publishes an unkeyed `{domain}` invalidation, at most one per domain per 30 s per Campaign.

**Given** `app/core/sse.py: sse_response(gen, *, ctx)`
**When** a route returns it
**Then** the response has `Content-Type: text/event-stream`, `X-Accel-Buffering: no` and `Cache-Control: no-cache`, sends `event: ping` every 15 s, and closes the stream within 2 s of an `access:{campaign_id}:{grant_id}` message for the ctx's grant.

- **Covers:** FR-2 (updates reach the UI without reload). AR-5.
- **Technical notes:** `GET /api/campaigns/{id}/events` and visibility-aware delivery of campaign events belong to E0-Access, which consumes this channel. The `access:` channel is published by E0-Access on grant changes. This module only subscribes to it. Governed by AD-5.
- **Dependencies:** E0-Jobs.3, E0-Access.10 (grant-change publish).
- **Size:** S

### Story E0-Jobs.7: Job routes and the SSE stream

As a GM or Player,
I want to fetch, list, retry and cancel my Jobs and receive live updates,
So that I can see what is running and recover failures without reloading.

**Acceptance Criteria:**

**Given** `app/api/routes/jobs.py`
**When** a GM calls `GET /api/jobs/{id}` for a Campaign Job
**Then** the response is `JobResponse {id, kind, status, progress, stage, eta_seconds, error_code, error_message, result_ref, attempts, created_at, started_at, finished_at}`
**And** a Player gets their own Jobs only, `result_ref` is included only if `visible_to(ctx, result_record)`, and any other Job returns `404 {"detail":"Not found"}`.

**Given** `GET /api/jobs/?campaign_id=&status=`
**When** called
**Then** it returns the ctx's visible Jobs newest-first (running, queued, and finished in the last 24 h by default), and each queued Job includes `queue_position` ("1 ahead") computed over its queue.

**Given** a `failed` Job
**When** its starter or a GM calls `POST /api/jobs/{id}/retry`
**Then** a new attempt is queued with `attempts` reset and `202 {"job_id"}` is returned. Retrying a non-failed Job returns 409.

**Given** a `queued` Job
**When** its starter or a GM calls `POST /api/jobs/{id}/cancel`
**Then** the status becomes `cancelled` and the worker skips it. Cancelling a `running` Job returns 409 ("Only queued Jobs can be cancelled").

**Given** `GET /api/jobs/stream?campaign_id=` with a bearer header
**When** a Job changes
**Then** the client receives the `job` event within 5 s, filtered by the same rules as `GET /api/jobs/{id}`, through `sse_response`.

**Given** the new routes
**When** EV-4 runs
**Then** `tests/ev4/probes/jobs.py` covers hidden-vs-nonexistent Job ids, `result_ref` suppression for Players, and SSE filtering
**And** `locations.conf` puts `/api/jobs/stream` in the generic `api` zone with `proxy_buffering off`, and the stream route has `@limiter.limit` keyed `user_or_ip`.

**Given** the admin System tab
**When** an admin opens it
**Then** it shows Job counts by status and queue next to the sidecar status from E0-Platform.6.

- **Covers:** FR-2 (status, retry, < 5 s, results GM-only). AR-5. Standing ACs (EV-4 probe, 404, nginx, limiter).
- **Technical notes:** The cancel route and `queue_position` add to the §3.2 contract (see Decisions). The event shape is unchanged. Response schemas go in `app/schemas/jobs.py`. Governed by AD-5, AD-13.
- **Dependencies:** E0-Jobs.6, E0-Access.2 (`require_campaign`), E0-Access.3 (`scoped_select`), E0-QA.11 (EV-4 harness), E0-Platform.8 (`user_or_ip`).
- **Size:** M

### Story E0-Jobs.8: File service, access-checked file route and backups

As a GM producing recap audio, Chronicles and Maps,
I want every stored file kept on one volume with provenance and served only through an access check,
So that Players can never fetch a GM-only or stale file by guessing a URL.

**Acceptance Criteria:**

**Given** `app/services/file_service.py`
**When** `put(db, ctx, campaign_id, kind, data, content_type, *, cache_key, sources: list[SourceRef])` runs
**Then** it writes bytes to `/data/files/{campaign_id}/{kind}/{uuid}` on the `files_data` volume, inserts `stored_files` with `sha256` and `size`, and writes one `derived_sources` row per source
**And** `open`, `delete` and a `files.gc` backfill Job (orphaned and superseded files, registered in `jobs/registry.py`) are the only other functions touching the volume.

**Given** `GET /api/files/{id}`
**When** the ctx may see the file's derived audience and the file is not stale
**Then** the response is empty-bodied with `X-Accel-Redirect: /_files/<storage_key>`, `Content-Type` from the row, `Cache-Control: private, no-cache` and an ETag that includes `access_epoch`
**And** a stale file returns 404 to non-GMs, and a hidden or missing file returns `404 {"detail":"Not found"}`.

**Given** nginx
**When** this story lands
**Then** `location /_files/ { internal; alias /data/files/; }` exists, `files_data` is mounted read-only in nginx and read-write in web and worker, and a direct request to `/_files/...` returns 404.

**Given** `docs/DATABASE_BACKUPS.md`
**When** this story lands
**Then** it covers backing up and restoring `files_data` with the database, and states that kept raw Live audio is excluded unless the GM opts in.

**Given** the file route
**When** EV-4 runs
**Then** `tests/ev4/probes/files.py` covers hidden vs nonexistent ids, stale files for Players, and the `/_files/` direct path.

**Given** `file_service.put_tree(db, ctx, kind, files: Iterable[tuple[str, bytes]], sources)` (Reconciliation RC-3, for E10.2 map tiles)
**When** it is called
**Then** it writes the whole tree under one directory `/data/files/{campaign_id}/{kind}/{uuid}/`, first to a temporary name and then renamed into place, so no reader sees a half-written tree, and it inserts one `stored_files` row (`storage_key` = the directory, `size` = total bytes, `sha256` = hash of the sorted manifest) with its `derived_sources` rows
**And** `accel_response(stored_file, subpath)` serves one file inside the tree as `X-Accel-Redirect: /_files/<storage_key>/<subpath>` after rejecting `..`, absolute paths and paths not in the manifest with the uniform 404
**And** `delete` and `files.gc` remove a tree recursively.

- **Covers:** FR-8 (files served through an access-checked route with unguessable URLs). AR-14. Standing ACs.
- **Technical notes:** The tile route pattern `GET /api/maps/{id}/tiles/{z}/{y}/{x}.jpg` belongs to E10 and reuses `file_service.open` plus the same header helper (`file_service.accel_response`). `DERIVED_REGISTRY` entries for each derived type are added by their owning epics. Governed by AD-14.
- **Dependencies:** E0-Jobs.5 (cursor backfill for `files.gc`), E0-Access.3 (access registry, `DERIVED_REGISTRY`, `audience_of`).
- **Size:** M

### Story E0-Jobs.9: `lib/sse.ts`, `useChat` migration and `useJobStream`

As a frontend developer,
I want one SSE client that sends the bearer header and reconnects with backoff,
So that Job updates, campaign events and chat streams all share one tested parser and no token ever goes into a URL.

**Acceptance Criteria:**

**Given** `lib/sse.ts` extracted from the `fetch` + `ReadableStream` parser in `hooks/useChat.ts:65-130`
**When** a caller opens a stream with `openSse(url, { method, body, onEvent, signal })`
**Then** it sends `Authorization: Bearer`, parses `event:`/`data:` frames including multi-line data, ignores `ping`, reconnects on network loss with exponential backoff (1 s up to 30 s, with jitter), and stops on abort or a 401/404.

**Given** `hooks/useChat.ts`
**When** migrated onto `lib/sse.ts`
**Then** chat streaming (`meta`, `delta`, `done`, `error`) and the blocking fallback behave as before, checked by hand against `/api/chat/stream`.

**Given** `hooks/useJobStream.ts` and `services/api/jobs.ts` + `types/jobs.ts`
**When** a component mounts `useJobStream(campaignId)`
**Then** it subscribes to `/api/jobs/stream?campaign_id=`, merges `job` events into the react-query cache keyed `['jobs', campaignId]` and `['jobs', campaignId, jobId]`, and exposes `useJob(jobId)`.

**Given** the repo
**When** a grep check runs
**Then** there is no `EventSource` and no `?token=` in `src/frontend/src`.

- **Covers:** FR-2 (no reload). AR-24 (SSE only via `lib/sse.ts`), AR-5.
- **Technical notes:** `useCampaignEvents` (E0-Access) builds on `lib/sse.ts`. `tsc` strict is the gate, since the frontend has no test runner. Governed by AD-5 and the frontend data convention.
- **Dependencies:** E0-Jobs.7.
- **Size:** M

### Story E0-Jobs.10: Job tray, Job rows, completion notices and the NavBar tray contract

As a GM,
I want an hourglass in the NavBar that counts running Jobs and pending reviews and opens a tray with progress, ETA and actions,
So that I can leave a page and still follow, retry or download my background work.

**Acceptance Criteria:**

**Given** `components/jobs/JobTrayButton.tsx` mounted in `NavBar.tsx` with one line
**When** Jobs are running
**Then** it shows a lucide Hourglass, a count of running Jobs plus the sum of registered tray-section counts, and a spinning segment (static under `prefers-reduced-motion`), with an accessible name such as "Background work: 2 running, 1 to review".

**Given** the Job tray popover
**When** opened
**Then** it lists, newest first, running Jobs, queued Jobs, and Jobs finished in the last 24 h, followed by the registered sections (for example E1's pending Review Checklists)
**And** each `JobRow` shows the stage text, a 4px determinate bar when progress is reported or "Queued · 1 ahead" from `queue_position`, a mono tabular ETA as a range ("about 1–2 min left"), and on failure the reason in `text-danger`
**And** row actions are View (when `result_ref` is present), Retry (failed), Download (when `result_ref` points at a file) and Cancel (queued only).

**Given** `components/jobs/traySections.ts`
**When** another epic calls `registerTraySection({ key, useCount(campaignId), Section })`
**Then** its count joins the badge and its section renders in the tray, without editing `JobTrayButton.tsx` (shared append point, one line per epic).

**Given** a Job finishes while the user is on another page
**When** its `done` or `failed` event arrives
**Then** a Toast appears ("Chronicle ready · Download", failures persist until dismissed), the document title gains a "(1)" prefix until the tray is opened, and a browser notification appears only if the tab is hidden and the user opted in under Settings › Notifications.

**Given** a Player
**When** the shell renders
**Then** the tray shows only their own Jobs and no GM Job badge, matching EXPERIENCE.md's Player shell.

**Given** the tray at 375 px, keyboard only
**When** I Tab to the button, press Enter, and move through rows
**Then** focus is visible, Esc closes the popover and returns focus to the button, and status changes are announced politely.

- **Covers:** FR-2 (status, retry, ETA). UX-DR14. NFR-10. Standing UI ACs.
- **Technical notes:** Uses E0-UX's Toast (`useToast`), EmptyState and semantic tokens. If E0-UX has not landed, use a minimal inline toast behind the same `useToast` signature and swap it later. The opt-in browser-notification toggle is one row in `SettingsPage.tsx`, stored per device in `localStorage` (D-6.7). NavBar is E0-UX's shell, and this story adds only the mount line. Governed by AD-5 and the frontend conventions.
- **Dependencies:** E0-Jobs.9, E0-Access.2 (`useCampaignRole`), E0-UX.1 (semantic tokens), E0-UX.5 (Toast, EmptyState).
- **Size:** M

## Epic E0-LLM: Reliable, prioritised local-LLM access with structured output

AI features get schema-valid answers from the local model without starving each other. There is one priority gate, one local model, prompt budgets, typed errors and a deterministic fake for CI. Phase 0, Wave 0, with no hard dependencies. Governed by AD-8 (plus AD-4 for error semantics and AD-13 for the capture hook).

**Covers:** FR-3, NFR-8 (BYOK resolution, hosted metering), AR-8, SPIKE-6.

### Story E0-LLM.1: Typed LLM errors and one LLM-config resolver

As a developer building an AI feature,
I want one function that resolves a user's LLM config and one typed error family that maps to HTTP the same way everywhere,
So that every route and Job keeps BYOK, gating and metering behaviour without copying `deps.py` logic.

**Acceptance Criteria:**

**Given** the existing resolution order in `api/deps.py:152-260` (personal UserSettings, then open-access mode with the `hosted_model_variant=="base"` swap, then a hosted subscriber with quota, then a 402)
**When** `services/llm_config_service.resolve_llm_config(db, user)` is called
**Then** it returns the same `LLMConfig` as today for each of those four cases, or raises `LLMConfigError(reason="llm-config")`
**And** `deps.get_user_llm_config` becomes a thin wrapper that maps `LLMConfigError` to `402` with header `X-Gate-Reason: llm-config`, and the existing tests in `tests/test_journals.py` and the chat tests still pass unchanged.

**Given** `app/core/errors.py`
**When** it is imported
**Then** it defines `LLMError` with subclasses `LLMConfigError`, `LLMBusy` (code `llm_busy`), `LLMUnavailable` (code `llm_unavailable`), `StructuredOutputError` (code `ai_output_unusable`, carrying `attempts` and the last validation errors) and `PromptBudgetError` (code `prompt_too_large`)
**And** one helper, `llm_error_response(exc)`, registered as a FastAPI exception handler in `app/main.py` (append point), maps them to `402`, `503`, `503`, `422` and `422` with body `{"detail": <readable text>, "code": <code>}`.

**Given** a route or Job that completes with the platform's hosted default config
**When** it finishes
**Then** `record_hosted_usage` is called exactly once per completion through a shared helper, `llm_config_service.meter(db, user, config, *texts)`, which does nothing when `is_hosted_default(config)` is false (BYOK)
**And** a unit test covers metered versus BYOK.

**Given** a Job handler that raises any `LLMError`
**When** the worker classifies it
**Then** `LLMConfigError` and `StructuredOutputError` are terminal, and `LLMBusy` and `LLMUnavailable` are retried (AD-4). The mapping is exported as `errors.RETRYABLE` and `errors.TERMINAL` for the E0-Jobs wrapper to import.

- **Covers:** NFR-8 (BYOK, metering), AR-8 (typed errors, route helper), FR-3 (error path).
- **Technical notes:** AD-8 (Errors), AD-2 (the worker resolves config through this function), AD-4. Extract code from `api/deps.py:152-260`, and keep the "why" comment style. `llm_provider.py:30 is_hosted_default` is unchanged. No new dependencies. The `error_code` values `llm_config`, `ai_output_unusable`, `llm_busy` and `llm_unavailable` are what the E0-Jobs `jobs/errors.py` enum must include (assumed contract).
- **Dependencies:** none.
- **Size:** S

### Story E0-LLM.2: One priority gate for the local LLM, and one fixed local model

As a GM running a Live Session while extraction backfills,
I want every local-LLM call to queue in priority order (live recap, then interactive, then Jobs) behind one Redis gate, always against the same loaded model,
So that the Rolling Recap and my questions are served first and Ollama never thrashes by reloading models.

**Acceptance Criteria:**

**Given** `app/core/llm_gate.py` and `async with llm_slot(cls)`, where `cls ∈ {live_recap, gm_interactive, player_interactive, job_onsave, job_backfill}` (a StrEnum)
**When** the number of holders is below `llm_gate_capacity` (from `OLLAMA_NUM_PARALLEL`, default 1)
**Then** the slot is granted at once
**And** otherwise the caller joins a Redis waiter set, ordered by class priority then arrival, and is granted the next free slot only when it is at the head (an atomic Lua acquire).

**Given** capacity 1, a held slot, and waiters arriving in the order `job_backfill`, `gm_interactive`, `live_recap`
**When** the holder releases
**Then** the grants go to `live_recap`, then `gm_interactive`, then `job_backfill` (a test against the real dev Redis)
**And** waiters in the same class are served first in, first out.

**Given** a request-path caller has waited `LLM_GATE_WAIT_S` (60 s)
**When** the wait expires
**Then** `LLMBusy` is raised, which the route helper turns into `503 {"code":"llm_busy"}`. An SSE route raises it before the stream starts, so the client gets a normal 503.
**And** a Job caller waits up to its remaining `timeout_s`, then raises `LLMBusy`, which is retried (AD-4).

**Given** a holder process that dies mid-call
**When** its holder entry (TTL 30 s, renewed every 10 s while held) lapses
**Then** the slot is recovered within 30 s with no manual action
**And** a streaming call holds the slot until the stream finishes or the client disconnects (released in the generator's `finally`).

**Given** a BYOK config (any config for which `llm_provider.uses_platform_llm(config)` is false)
**When** it calls the LLM
**Then** it bypasses the gate completely.

**Given** the existing `complete_messages` and `stream_messages`
**When** they are called
**Then** they acquire the gate with the class from the `gate_class` keyword, defaulting to the contextvar `llm_gate.current_class` (default `gm_interactive`)
**And** `llm_gate.class_for_queue(queue)` maps `onsave → job_onsave`, `backfill → job_backfill` and `interactive → gm_interactive`, for the E0-Jobs worker to set per Job. A kind can override this (for example `live.recap → live_recap`).

**Given** the local provider
**When** `llm_provider.model_for(task, config)` is called
**Then** it returns `settings.local_llm_model` for every task, except that `task="narrative"` still honours `hosted_model_variant` (with the reload cost accepted, AD-8)
**And** `num_ctx`, `num_gpu` and `keep_alive` are stripped from per-call options, which a unit test asserts.

- **Covers:** AR-8 (gate, `model_for`, option stripping), FR-1 priority support (LLM side), NFR-8.
- **Technical notes:** AD-8 (The gate; Local model and context), AD-3. Redis keys are `llm_gate:holders` (ZSET by expiry) and `llm_gate:waiters` (ZSET by `priority*1e13 + ts_ms`). Waiters poll every 100 ms. The gate deliberately uses keys, not pub/sub, because `core/pubsub.py` allows exactly three channels (AD-5). New settings in `app/core/config.py`: `local_llm_model`, `llm_gate_wait_s`, `llm_gate_capacity`. `llm_gate.snapshot()` (holders and waiters by class) feeds the admin System tab later. There is no preemption: a running generation is never cut off. Each call through `complete_structured` (E0-LLM.4) acquires separately, so a `live_recap` call can slip in between repair turns.
- **Dependencies:** E0-LLM.1. (Gate tests stub the provider and use the real dev Redis; the fake provider comes later in this epic.)
- **Size:** M

### Story E0-LLM.3: Backend detection and prompt budgets

As a self-hoster on a 4096-token context,
I want every prompt builder to fit its parts into the context with an explicit truncation or map-reduce policy, and the app to know whether it is talking to Ollama,
So that long transcripts and entity lists are never silently cut, and narrative generation stops paying for a failed KoboldCpp request on Ollama.

**Acceptance Criteria:**

**Given** an `api_url`
**When** `llm_provider.detect_backend(api_url)` is called
**Then** it returns `ollama` when `GET {api_url}/api/version` succeeds, and `openai_compat` otherwise (KoboldCpp or another OpenAI-compatible server), and caches the result per URL for the process lifetime
**And** `ai_service.generate_narrative` skips `_generate_kobold_native` when the backend is `ollama` (removes the wasted request noted at `ai_service.py:111`), with a test against a mocked `/api/version`.

**Given** `services/prompt_budget.py` with a `TASK_POLICIES` registry
**When** `prompt_budget.fit(task, parts)` is called with named parts (system, instructions, required, optional lists, history)
**Then** it returns the messages that fit `OLLAMA_CONTEXT_LENGTH` (4096) minus the task's reserved output tokens, applying the task's policy: `drop_oldest` (history), `truncate_tail` (optional context ranked by relevance) or `map_reduce`
**And** if the required parts alone don't fit, it raises `PromptBudgetError`. It never truncates required parts silently.

**Given** a `map_reduce` task and an input larger than one window
**When** `prompt_budget.map_reduce(chunks, map_fn, reduce_fn, task=...)` runs
**Then** every chunk is processed (a test asserts that the last chunk's sentinel text reaches a map call), and the reduce step recurses until its input fits.

**Given** token estimation
**When** no tokenizer is available
**Then** the estimate is `ceil(chars / 3.2)` plus 10% margin, which E0-LLM.6 calibrates from the SPIKE-6 measurements (E0-Platform.10) against Ollama's reported `prompt_eval_count` and records in `TASK_POLICIES` comments.

**Given** the tasks known at Phase 0
**When** the registry is read
**Then** it has entries for `chat`, `narrative`, `structured` (generic), `live_recap`, `live_draft` (map_reduce), `npc_chat` and `lookup_answer`. Feature epics add their own task lines (for example `extraction`, `continuity`, `recap`) as one-line additions.

- **Covers:** AR-8 (`prompt_budget.fit`, `detect_backend`), FR-29 support (no truncation), NFR-8.
- **Technical notes:** AD-8 (Local model and context; Backend detection). This fixes the brownfield 12000-char truncation risk (`chat_service.py:276`) for callers that adopt `fit`. Migrating `summarize_session_transcript` itself happens in E4.7. No new dependencies (no tokenizer package).
- **Dependencies:** E0-LLM.2.
- **Size:** M

### Story E0-LLM.4: `complete_structured` with schema enforcement and at most two repairs

As an AI feature (extraction, continuity, rolling recap),
I want to ask for output matching a pydantic schema and get a validated object, or a clear "AI output unusable" error after two repair attempts,
So that no feature writes half-parsed JSON and every backend behaves the same.

**Acceptance Criteria:**

**Given** `complete_structured(messages, schema: type[BaseModel], config, *, task, timeout) -> BaseModel` in `llm_provider.py`
**When** the backend is Ollama (`detect_backend`)
**Then** it calls native `/api/chat` with `format=<schema.model_json_schema()>`, `temperature=0`, `stream=false` and the model from `model_for`, and the schema is also restated in the final user turn.

**Given** an `openai`, `custom` or KoboldCpp backend
**When** it is called
**Then** it sends `response_format={"type":"json_schema","json_schema":{"name":task,"schema":...,"strict":true}}`, and on a 4xx response it retries once as prompted JSON.
**And** `anthropic` and `gemini` always use prompted JSON. All paths share the same validation.

**Given** output that fails `schema.model_validate_json`
**When** repair runs
**Then** it appends the raw output as an assistant turn and a user turn listing the validation errors (truncated to 1,000 characters), asking for corrected JSON only, at most twice
**And** after the second failed repair it raises `StructuredOutputError(attempts=3, errors=...)`, and the caller writes nothing (a test feeds invalid, invalid, invalid output through an `httpx.MockTransport` and asserts no DB write in a sample handler).

**Given** each attempt
**When** it completes
**Then** a JSON log line `{task, attempt, valid, backend, ms}` is emitted, and the counter `llm_provider.structured_stats[task]` (first-try valid, valid after repair, failed) is updated for eval scripts (EV-1 reads it for FR-3's ≥ 95% check).
**And** each attempt acquires `llm_slot` separately with the caller's gate class.

**Given** `app/schemas/llm/__init__.py`
**When** a feature defines a schema
**Then** it subclasses `FlatModel` (`extra="forbid"`)
**And** a CI test imports every module in `app/schemas/llm/` and fails on any `$ref`, `$defs`, `anyOf`, `oneOf` or `allOf`, or a missing `additionalProperties: false`. It also fails on `Optional` fields, because they generate `anyOf`. Optional values use enums or empty strings instead, which is also what OpenAI strict mode needs.

**Given** the remote test desktop (CachyOS, RTX 5080, native Ollama 0.40.3 serving `lorekeeper`, reached over Tailscale)
**When** `pytest -m ollama` runs with `OLLAMA_TEST_URL` set (from the cached backend Docker image, using host networking or `host.docker.internal`)
**Then** `tests/integration/test_llm_structured_ollama.py` runs 50 calls over 3 sample flat schemas (an entity list, a recap update, a yes/no verdict with a quote) and reports first-try and after-repair validity
**And** at least 95% validate on the first or second attempt. The measured rates and the Ollama version go in `docs/BENCHMARKS.md` as an FR-3 row. Without `OLLAMA_TEST_URL` the suite is skipped, so CI stays model-free.

- **Covers:** FR-3, AR-8 (structured output, flat schemas), NFR-8 (BYOK parity).
- **Technical notes:** AD-8 (Structured output; Validation and repair; Schemas). Flat-schema guidance comes from research row 1 (`research-decisions-summary.md`). The `ollama` pytest marker is registered in `pytest.ini`/`pyproject` (a one-line append). This story doesn't depend on the conftest change, but the remote desktop run uses E0-QA.4's env-overridable `TEST_DATABASE_URL` once it lands. Unit tests use `httpx.MockTransport`, so no new dependency is needed.
- **Dependencies:** E0-LLM.2, E0-LLM.3.
- **Size:** M

### Story E0-LLM.5: Deterministic fake LLM provider and the EV-4 context-capture hook

As a developer and CI,
I want a deterministic, schema-aware fake LLM under `ENVIRONMENT=test`, plus a hook that records exactly what context each call sent,
So that AI routes and Jobs are testable without Ollama, and EV-4 can prove no GM-only text reached a Player's prompt.

**Acceptance Criteria:**

**Given** `ENVIRONMENT=test`
**When** `complete_messages` or `stream_messages` is called with any config
**Then** the `fake` provider answers without network access, including `complete_structured` calls (E0-LLM.4) through its `format` path,, deterministically (the same messages give the same output, keyed on a hash of the messages)
**And** `stream_messages` yields the fake answer in several chunks, so streaming code paths are exercised.

**Given** a test that needs scripted output
**When** it uses the fixture `fake_llm.script([...])`
**Then** successive calls return the scripted strings in order, including invalid JSON, so repair paths can be tested
**And** calls that pass a `format`/schema with no script return a minimal valid instance generated from the pydantic model (enums take their first member, strings get `"fake"`, lists hold one element).

**Given** `llm_provider.capture()`, a contextvar-based context manager
**When** code inside it makes LLM calls
**Then** every call's full `messages`, `task`, gate class and resolved model are appended to the capture list, for both the fake and real providers
**And** capture is off by default and costs nothing when off. The EV-4 harness (E0-QA) uses it for the "captured LLM context" probe family.

**Given** the test suite
**When** it runs in CI with no Ollama service
**Then** no test opens a socket to `KOBOLD_URL`, which an autouse fixture asserts.

- **Covers:** AR-8 (fake provider), AR-21 support (fakes under `ENVIRONMENT=test`), NFR-5 support (capture hook for EV-4).
- **Technical notes:** AD-21 (Fakes), AD-13 (Test capture). The fake lives in `llm_provider.py` as `provider="fake"`, selected when `settings.environment == "test"`, unless a test opts into a real URL (the `ollama` marker from E0-LLM.4). This is the hook that E0-QA.14's captured-context probes need (B1 expects it as E0-LLM.5). Fixtures go in a new `tests/fixtures/fake_llm.py` that `tests/conftest.py` (owned by E0-QA) imports with a one-line addition. The capture hook stores no secrets: `api_key` is never recorded.
- **Dependencies:** E0-LLM.4 (the structured path is faked too). Soft: E0-QA.4, E0-QA.5 (the hook works with any ctx). Consumers (not dependencies): E0-QA.11, E0-QA.14, E1.2, E2.2.
- **Size:** S

### Story E0-LLM.6: Act on SPIKE-6: calibrate prompt budgets, decide the extraction prompt shape, and measure gate contention

As the owner deciding NFR-6 targets and the extraction prompt shape,
I want E0-LLM to turn the x86 SPIKE-6 throughput measurements (E0-Platform.10) into concrete settings and a recommendation, and to measure the one thing that harness can't, which is waiting behind the gate,
So that E1 knows whether it needs an Entity shortlist, and `prompt_budget` and the gate rest on measured numbers.

**Acceptance Criteria:**

**Given** the SPIKE-6 results from E0-Platform.10 (`_bmad-output/planning-artifacts/spikes/x86-desktop-benchmarks.md` and the `docs/BENCHMARKS.md` rows: prompt and generation tok/s, time to first token and total time per prompt shape, CPU and GPU, plus the structured-extraction validity check)
**When** this story consumes them
**Then** SPIKE-6 is not measured a second time. This story only reads those numbers.
**And** `prompt_budget`'s chars-per-token ratio (E0-LLM.3) is calibrated against Ollama's reported `prompt_eval_count` for the same prompts, and the result is recorded in a `TASK_POLICIES` comment that cites the benchmark row.

**Given** the extraction-shape rows (Entity lists of 50 and 300)
**When** the recommendation is written in `_bmad-output/planning-artifacts/spikes/llm-throughput-decisions.md`
**Then** it says whether E1 should send the full Entity list or a RapidFuzz plus embedding shortlist, and at what Entity count it should switch
**And** it proposes NFR-6 values for the proposal, Rolling Recap and NPC first-token rows, marked "needs owner sign-off in `.memlog.md`". It does not change the targets itself.

**Given** `scripts/bench_llm_gate.py`, which goes through the production `llm_slot` and `complete_structured` paths
**When** it runs on the remote desktop against the compose `ollama` container on CPU (AD-7 limits: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_CONTEXT_LENGTH=4096`) and against native Ollama 0.40.3 on the GPU
**Then** it records the gate overhead per call, and how long a `live_recap` call waits behind a running `job_backfill` generation of extraction size (the gate has no preemption), n ≥ 5. Results go in `docs/BENCHMARKS.md` as "LLM gate" rows.
**And** if the CPU wait would push a Rolling Recap update past 45 s, the decisions note proposes a cap on `job_backfill` output tokens while the `live` lease is held, which E4 and E1 then pick up.

- **Covers:** SPIKE-6 (acting on the result), NFR-6 input (EV-5 rows), AR-8 (budget calibration, gate behaviour).
- **Technical notes:** The B2 contract is that E0-Platform.10 runs the SPIKE-6 measurement harness and E0-LLM owns acting on it (see B2 Decisions §6). AD-7, AD-8, AD-21. The scripts go in `src/backend/scripts/`. No new dependencies.
- **Dependencies:** E0-LLM.4, E0-Platform.10 (SPIKE-6 x86 results; measured there only). Soft: E0-QA.15 (`docs/BENCHMARKS.md`, EV-5 format).
- **Size:** S

## Epic E0-Journal: Edit and delete Journal Entries safely

A GM or author can correct a Journal Entry after saving. Search, tags and retrieval follow the edit, and every feature reacts through hooks rather than editing the journal code.

### Story E0-Journal.1: Hook dispatcher on `after_commit`

As a feature developer,
I want to register a handler for journal and Canon events in `app/hooks/<feature>.py` and have it run only after the change commits,
So that extraction, continuity and stats react to saves without editing `journal_service`, and a failing handler never breaks a save.

**Acceptance Criteria:**

**Given** `app/hooks/__init__.py`
**When** this story lands
**Then** it defines the event StrEnum `entry_saved, entry_updated, entry_deleted, visibility_changed, canon_changed, role_changed, job_finished, live_session_ended`, `emit(db, event, *, campaign_id, refs, actor_ctx)` and a `HANDLERS` list (one line per feature: shared append point).

**Given** code that calls `emit` inside a transaction
**When** the transaction commits
**Then** an SQLAlchemy `after_commit` listener dispatches each collected event, in order, to every handler registered for it, with payload `{campaign_id, refs, actor_ctx}`
**And** when the transaction rolls back, the collected events are discarded and no handler runs.

**Given** a handler that raises
**When** it is dispatched
**Then** the exception is logged as `hook_failed` with event, handler and `campaign_id` (no Shorthand), other handlers still run, and the caller sees no error.

**Given** the worker
**When** a Job reaches `done` or `failed`
**Then** it emits `job_finished` with `refs={job_id, kind, status}`.

- **Covers:** NFR-9, AR-17 (hooks).
- **Technical notes:** `session.info["lk_hooks"]` collects the events. Handlers run in a fresh session, because the committed session must not be reused inside `after_commit`, and an enqueue inside a handler goes through the E0-Jobs outbox. A per-user handler builds `access.ctx_for(user_id, campaign_id)` itself. The `job_finished` emit is a one-line call from the E0-Jobs wrapper. Governed by AD-17.
- **Dependencies:** E0-Jobs.3 (wrapper emits `job_finished`).
- **Size:** S

### Story E0-Journal.2: Journal writers recompute every index column

As a GM,
I want every way an entry is created, edited or re-indexed to recompute search, Party search, embeddings, tags and the duplicate hash,
So that search, chat retrieval, tag counts and duplicate detection always match the text I see.

**Acceptance Criteria:**

**Given** `journal_service.create_journal_entry` (existing), `update_journal_entry(db, ctx, entry, changes)`, `delete_journal_entry(db, ctx, entry_id)` and `reindex_entry(db, entry)`
**When** a create or update changes Shorthand or Narrative
**Then** `narrative_tsv` (Shorthand + Narrative) and `party_tsv` (Narrative only) are recomputed in SQL, `embedding` and `party_embedding` are recomputed through `app/clients/ml.py`, and tags are replaced: rows with `source_field ∈ {narrative, shorthand}` are re-derived from `ml /v1/ner`, and manually attached tags are kept.

**Given** `ml` is unavailable during a create or update
**When** the write commits
**Then** the entry saves with the text change and the tsv columns updated, and a `journal.reembed` Job (`onsave` queue, `resources={cpu_heavy}`, `live_safe=false`, idempotency key `journal.reembed:{journal_id}:{entry_hash}`) is enqueued to fill the embeddings and tags.

**Given** a create or update
**When** the hash is computed
**Then** `entry_hash` is computed on the server from the normalized Shorthand, ignoring any client-sent hash, and is unique on `(campaign_id, user_id, entry_hash)`
**And** the Redis dedup key is scoped the same way, and an edit that collides with another of the user's entries in that Campaign returns 409.

**Given** an entry saved by the offline queue
**When** it is created
**Then** it lands with `visibility=gm`.

**Given** `POST /api/journals/reindex` (`api/routes/journals.py:299`)
**When** called
**Then** it uses `reindex_entry`, which updates index columns only and emits no hooks.

**Given** a create, update or delete
**When** it commits
**Then** it emits `entry_saved`, `entry_updated` or `entry_deleted` with `refs={journal_id, kind, previous_entry_hash, entry_hash, changed_fields}` (delete: `{journal_id, kind}`), and publishes `campaign:{id}:events` `{domain:"journal", id}` (delete: unkeyed).

**Given** a grep test
**When** CI runs
**Then** no module outside `journal_service` assigns `narrative`, `notes`, `narrative_tsv`, `embedding`, `party_*` or `entry_hash` on a `JournalEntry`.

- **Covers:** FR-6 (search, retrieval, tags and dedup reflect edits), NFR-9. AR-17.
- **Technical notes:** The columns (`kind`, `visibility`, `party_tsv`, `party_embedding`, `journal_tags.source_field`, the `entry_hash` uniqueness) come from E0-Access's F1-core revision. The `source_field` values `narrative`, `shorthand` and `manual` are assumed (see Decisions). `utils/hashNotes.ts` stays for client-side dedup UX only. `journal.reembed` is registered in `jobs/registry.py`. Governed by AD-17, AD-2.
- **Dependencies:** E0-Journal.1, E0-Jobs.2 (`enqueue`), E0-Platform.6 (async `ml` wrappers), E0-Access.1 (F1-core columns), E0-Access.7 (`index_party_fields`, folded into `reindex_entry` here).
- **Size:** L

### Story E0-Journal.3: Edit and delete routes with Player rules and the delete contract

As a GM or an entry's author,
I want to edit an entry's Shorthand, Narrative, Session and Visibility, and delete an entry with defined consequences,
So that I can correct mistakes, and Players can manage only their own Player Journal entries.

**Acceptance Criteria:**

**Given** `PUT /api/journals/{id}` with any of `{notes, narrative, session_date, visibility}`
**When** a GM edits a `kind=gm` entry, or a Player edits their own `kind=player` entry
**Then** `update_journal_entry` applies the change, the response passes through `access.project` (`JournalGMResponse` or `JournalPartyResponse`), and Visibility changes go through `access.set_visibility`, never a direct column write.

**Given** a Player editing or deleting a `kind=gm` entry, another Player's entry, or an entry they can't see
**When** the request is made
**Then** it returns `404 {"detail":"Not found"}`, the same as a nonexistent id (`can_write(ctx, obj)`).

**Given** a GM edits a `kind=gm` entry's Shorthand or Narrative
**When** the edit commits
**Then** `entry_updated` carries `kind=gm`, `changed_fields` and both hashes, so the E1 and E2 handlers can supersede pending unedited proposals and re-queue `extraction.run` and `continuity.check` under the new `entry_hash`
**And** a contract test registers a fake handler and asserts it receives exactly this payload. An edit of a `kind=player` entry carries `kind=player`, which those handlers ignore by contract.

**Given** an edit that changes only `session_date` or Visibility
**When** it commits
**Then** `changed_fields` excludes text, so no re-extraction trigger fires, and embeddings are not recomputed.

**Given** `DELETE /api/journals/{id}` (moved from the route into `delete_journal_entry`)
**When** a permitted user deletes
**Then** in the same transaction `delete_journal_entry` calls `world_service.detach_entry(db, ctx.as_system("entry_deleted"), journal_id)` (a no-op until E0-WorldCore implements it), deletes the row and its tag links, and emits `entry_deleted`
**And** a later `GET` of the entry, or a citation resolve that points at it, returns `404 {"detail":"Not found"}`.

**Given** the new `PUT` route
**When** EV-4 runs
**Then** `tests/ev4/probes/journals.py` covers a Player `PUT`/`DELETE` on a GM entry, on another Player's entry, and on a nonexistent id (all identical 404s), and a GM's write response for a Party viewer.

- **Covers:** FR-6 (author or GM edits; Players only their own; delete effects; no automatic Canon change), FR-7 (write responses pass the Visibility filter). AR-17, AR-10 (delete contract). Standing route ACs.
- **Technical notes:** This story creates `app/services/world_service.py` with only a documented no-op `detach_entry`. E0-WorldCore takes ownership of the file and replaces the body (see Decisions). Approved Canon never changes here, because edits only emit events and Canon changes go through E1's Review Checklist. `PUT` is not an AI route, so it stays in the generic nginx zone. Governed by AD-17, AD-13, AD-10.
- **Dependencies:** E0-Journal.2, E0-Access.2 (`require_campaign`, `as_system`), E0-Access.4 (`project`), E0-Access.6 (`can_write`), E0-Access.9 (`set_visibility`).
- **Size:** M

### Story E0-Journal.4: Entry edit and delete UI on the entry detail page

As a GM or an entry's author,
I want an Edit button and a Visibility badge on the entry detail page, and a delete that tells me what happens,
So that I can fix an entry in place without re-creating it.

**Acceptance Criteria:**

**Given** `pages/EntryDetailPage.tsx` for a user who may edit the entry (from `useCampaignRole` plus `kind`/author)
**When** the page renders
**Then** an "Edit" button and a `VisibilityBadge` appear in the header. Users who may not edit see neither control, and Players see the badge only on their own entries (Private / Shared).

**Given** I click Edit
**When** the inline editor opens
**Then** I can change Shorthand, Narrative and Session date, and Save or Cancel. Save calls `PUT /api/journals/{id}`, my input is kept on error with an inline `text-danger` message and Retry, and on success the page updates without a reload.

**Given** a GM saves a text change to a GM entry
**When** the save succeeds
**Then** a one-line notice says "Saved. World changes and continuity will be re-checked." (shown only when the E1/E2 hooks are registered, through a capability flag from `GET /api/campaigns/{id}/me` or a static feature flag).

**Given** I choose Delete
**When** the confirmation opens
**Then** it names the entry by its italic title and states that Mentions and NPC Knowledge links will be removed and that Canon facts sourced only from this entry will be flagged for review. Confirming calls `DELETE`, then navigates to the journal list with a Toast.

**Given** 375 px width and keyboard only
**When** I use Edit, Save, Cancel and Delete
**Then** every control is reachable with visible focus, Esc cancels the editor or the dialog, targets are ≥ 44 px, and only theme and semantic tokens are used.

- **Covers:** FR-6 (UI). UX-DR22 (Edit button, VisibilityBadge). NFR-10. Standing UI ACs.
- **Technical notes:** Uses E0-UX's `VisibilityBadge`, Toast and tokens. If they haven't landed, use a plain button behind the same props and swap later. The Mentions strip and ContinuityFlags on this page belong to E1 and E2. `services/api/journals.ts` gains `updateJournal` and the typed response. The existing "Read Aloud" (`EntryDetailPage.tsx:166`) is unchanged. Governed by AD-17 and the frontend conventions.
- **Dependencies:** E0-Journal.3, E0-Access.2 (`useCampaignRole`), E0-UX.5 (Toast), E0-UX.6 (VisibilityBadge).
- **Size:** M

## Epic E0-UX: A consistent, accessible app shell for the expansion

Every user gets an app that looks like it was always this way and works by keyboard and screen reader. Semantic colour tokens fix the contrast defects, SlideOver traps focus, reduced motion is respected, the new primitives exist, and the shell knows the current Campaign and Role.

**Covers:** NFR-10, UX-DR1 to UX-DR13, CI-15 (the grep check), FR-2 (Toast substrate for Job notices). **Owns (D-3):**

- `types/theme.ts`, `themes/*.ts`, `contexts/ThemeContext.tsx` (token fallback only), `tailwind.config.ts`, `index.css`;
- `components/ui/*` and `components/SlideOver.tsx`;
- the `components/NavBar.tsx` shell, `components/shell/*` and `lib/routes.ts`;
- `pages/NotFoundPage.tsx`, `lib/shortcuts.ts` and `scripts/check-ui-tokens.mjs`.

It owns no tables. **Depends on:** E0-Access.2 (`useCampaignRole`) as a soft dependency, stubbed until it lands. **Phase:** 0, Wave 0.

### Story E0-UX.1: Semantic colour tokens and type roles in all six themes

As a GM or Player using any theme,
I want "safe", "careful", "hidden", "someone else's eyes", "live" and "error" to have their own readable colours in every theme,
So that new screens can signal state clearly without relying on `primary` or `destructive`, whose meaning shifts from theme to theme.

**Acceptance Criteria:**

**Given** `types/theme.ts` `ThemeColors`
**When** the story is complete
**Then** it declares six new HSL keys: `success`, `warning`, `info`, `gm`, `live` and `danger`
**And** each of `themes/dnd.ts`, `arcane.ts`, `highseas.ts`, `forest.ts`, `cyberpunk.ts` and `light.ts` sets all six to the DESIGN.md frontmatter values (for example dnd `danger: "0 75% 72%"` and light `gm: "275 55% 40%"`).

**Given** `tailwind.config.ts`
**When** a developer writes `text-success`, `bg-gm/14`, `border-warning/40` or `bg-gm/6`
**Then** the classes resolve to `hsl(var(--x) / <alpha>)`
**And** the opacity scale is extended with `6`, `14`, `45` and `55`, the DESIGN.md wash and border steps, so no arbitrary `/[0.14]` values are needed.

**Given** a custom theme in `lorekeeper-custom-themes` that lacks one or more of the new keys
**When** `ThemeContext` applies it
**Then** each missing key falls back to the dnd value if the custom `background` lightness is ≤ 50%, or to the light value if it is > 50%
**And** no CSS variable is left unset.

**Given** the contrast script `scripts/check-ui-tokens.mjs --contrast`, which parses the HSL triplets from `themes/*.ts`
**When** it runs
**Then** every new token on every built-in theme measures ≥ 4.5:1 against that theme's `card`, its `background`, and its own 14% wash composited over `card`
**And** the script exits non-zero and names the theme, token and ratio when any pair fails.

**Given** the DESIGN.md type roles
**When** a page uses them
**Then** the Tailwind/`index.css` utilities `text-entity-title` (30px, 24px below `md`), `text-quote` (italic, 14px/1.55), `font-mono-tabular` (12px, `font-variant-numeric: tabular-nums`), `text-caption-live` (20px), `text-caption-table` (36px) and `text-recap-table` (32px) exist
**And** every heading or body role takes its family from `var(--font-heading)` or `var(--font-body)`, never a literal font name.

**Covers:** UX-DR1, UX-DR9, NFR-10.
**Technical notes:**
- Keys are HSL triplets without `hsl()`, matching the existing theme files.
- `ThemeContext.applyTheme` already loops `colors` into `--<key>` (`contexts/ThemeContext.tsx:21`). The fallback runs before that loop.
- The `--contrast` mode of the script uses the WCAG relative-luminance formula. Wash compositing is `0.14·token + 0.86·card` in sRGB.
- No new npm dependency.
**Dependencies:** none.
**Size:** M

### Story E0-UX.2: Fix destructive-text contrast, migrate hardcoded colours, and gate them in CI

As a user of a dark theme,
I want error text and status colours to stay readable and match my theme,
So that I'm not shown low-contrast red error lines or off-theme green and amber badges.

**Acceptance Criteria:**

**Given** the 73 `text-destructive` text uses across 29 files today (`grep -rn "text-destructive\b" src`, excluding `text-destructive-foreground`)
**When** the migration is done
**Then** every one that colours readable text or an icon is `text-danger`
**And** `destructive` survives only as a fill (`bg-destructive`, `bg-destructive/10`, `border-destructive`) or as `text-destructive-foreground` on a destructive fill, including in `components/ui/button.tsx` and `badge.tsx`
**And** an error line on dnd (`destructive` lightness 30%) measures ≥ 4.5:1 against `card`.

**Given** the 54 hardcoded `green-*`, `amber-*` and `red-*` classes in `components/JournalInput.tsx`, `components/ModelReadyBanner.tsx`, `pages/AdminPage.tsx`, `CharactersPage.tsx`, `ChatPage.tsx`, `QuestsPage.tsx`, `RecordSessionPage.tsx` and `SettingsPage.tsx`
**When** the migration is done
**Then** green maps to `success`, amber to `warning`, red text and icons to `danger`, and red fills to `destructive`
**And** washes use `/14` and borders `/40`
**And** each status that used colour alone gains an icon or word, so colour never carries meaning by itself (for example, `ModelReadyBanner` gets a lucide `TriangleAlert` instead of "⚠").

**Given** `scripts/check-ui-tokens.mjs` without flags (the CI-15 grep check)
**When** it runs over `src/**/*.{ts,tsx}`
**Then** it fails on any `(text|bg|border|ring|fill|stroke|from|to|via)-(green|amber|red)-\d+` class, any hex or `rgb(` colour literal in a `className` or `style` colour property, and any `text-destructive` not followed by `-foreground`
**And** it passes on the migrated tree with an empty allowlist
**And** `package.json` gains `"lint:tokens": "node scripts/check-ui-tokens.mjs && node scripts/check-ui-tokens.mjs --contrast"`.

**Given** the frontend CI job owned by E0-QA
**When** a PR runs
**Then** `npm run lint:tokens` runs next to `npm run build` on every PR and on `main`, with no path filter
**And** a deliberately added `text-red-500` in a scratch commit makes the job fail.

**Given** each migrated page, in all six themes
**When** it is checked by eye at 375 px and at desktop width
**Then** no layout changed and only colours moved.

**Covers:** UX-DR2 (defect), UX-DR3 (defect), CI-15, NFR-10.
**Technical notes:**
- This is a mechanical, class-only change in files other epics own (`EntryDetailPage.tsx`, `SharingPage.tsx`, `SharedCampaignPage.tsx` and others). It lands in Wave 0, before those epics edit the files, to keep rebases clean.
- Adding the script to the workflow is a one-line step in E0-QA's frontend job (the shared CI file; E0-QA.6 owns the workflow).
- The DESIGN.md note that migration is optional is overridden by epics.md UX-DR3.
**Dependencies:** E0-UX.1.
**Size:** M

### Story E0-UX.3: SlideOver focus trap, wide and full-screen variants, push header, and reduced motion

As a keyboard or screen-reader user,
I want detail panels to keep my focus inside them and give it back when they close, and animations to stop when I've asked for reduced motion,
So that I never get lost behind a modal and the app doesn't move when I've told my OS I need it still.

**Acceptance Criteria:**

**Given** an open `SlideOver`
**When** I press `Tab` or `Shift+Tab` repeatedly
**Then** focus cycles only through the panel's focusable elements
**And** on open, focus moves to the first focusable element, or to the panel heading if there is none
**And** on close (Esc, backdrop or the Close button), focus returns to the element that opened it. If that element is gone, focus goes to `main`.

**Given** `<SlideOver size="wide">`
**When** it renders at `md` and up
**Then** it is `md:max-w-3xl` (48rem, `slideover-wide`), and the default size stays `md:max-w-lg`
**And** below `md`, both sizes are full-screen with a sticky header.

**Given** a SlideOver showing panel A
**When** a child calls `push({ title, render, backLabel: "Back to checklist" })`
**Then** the same SlideOver shows the pushed content with a "← Back to checklist" button in the header
**And** Back, or `Esc` once, pops to A with A's scroll position restored, and a second `Esc` closes the SlideOver.

**Given** a SlideOver is already open
**When** code tries to open a second one
**Then** the first one's content is replaced (or pushed, when `push` is used), never stacked
**And** a dev-mode console warning names the caller.

**Given** the global layer stack in `lib/layers.ts`, which SlideOver, popovers and placement modes register with
**When** I press `Esc`
**Then** only the top layer closes.

**Given** `prefers-reduced-motion: reduce`
**When** any page renders
**Then** global CSS in `index.css` sets transition and animation durations to ~0 for `.transition-*`, `animate-pulse` and `animate-spin`
**And** SlideOver and bottom sheets appear without sliding, skeletons don't pulse, and the exported `useReducedMotion()` hook returns `true`, for components that animate in JS (graph camera, captions, foil)
**And** the backdrop fades within 0 ms.

**Given** the existing users of SlideOver (`NpcDetailPanel.tsx`, `QuestDetailPanel.tsx`)
**When** they open
**Then** they behave as before, with the trap and return focus added and no visual change.

**Covers:** UX-DR4 (defect), UX-DR5, UX-DR12 (Esc closes the top layer), NFR-10.
**Technical notes:**
- The focus trap is written in-house (about 60 lines in `lib/focusTrap.ts`) with no dependency. Focusable elements are queried at each Tab, so dynamic content works.
- `aria-modal="true"` stays. `aria-labelledby` points to the title.
- This story owns the `SlideOver` API (`size`, `push`, `pop`). E1's Review Checklist and E0-WorldCore's EntityPanel consume it.
**Dependencies:** E0-UX.1.
**Size:** M

### Story E0-UX.4: SegmentedControl, Tabs and Combobox primitives

As a developer building the new surfaces,
I want accessible segmented controls, tabs and comboboxes in `components/ui`,
So that the Visibility switch, the World and Keepsakes tabs, and the target and Location pickers all behave the same and pass WAI-ARIA keyboard patterns.

**Acceptance Criteria:**

**Given** `components/ui/segmented-control.tsx`
**When** it renders options such as "Private · Share with party"
**Then** it is a `role="radiogroup"` with `role="radio"` items
**And** arrow keys move and select, Home and End jump, and only the selected item is in the tab order
**And** the active segment is `bg-muted text-foreground font-medium`, matching the existing campaign tab buttons
**And** each item is ≥ 44px tall.

**Given** `components/ui/tabs.tsx` with `routeMode`
**When** the user activates a tab
**Then** the URL updates (for example `/world` → `/world/web`) and Back returns to the previous tab
**And** without `routeMode`, arrow keys move focus and Enter or Space activates (manual activation)
**And** the roles `tablist`, `tab` and `tabpanel` are wired with `aria-controls` and `aria-labelledby`.

**Given** `components/ui/combobox.tsx` with an async `loadOptions(query)`
**When** the user types
**Then** options filter as they type (debounced 150 ms through `hooks/useDebounce.ts`), ArrowDown opens the list, arrows move `aria-activedescendant`, Enter selects and Esc closes
**And** a trailing "Create…" option appears only when an `onCreate` prop is passed
**And** an empty result shows "No matches", and the list is announced as a `listbox`.

**Given** each primitive
**When** it is built
**Then** it is cva-styled like `components/ui/button.tsx`, uses theme tokens only, shows a visible `ring` focus, and passes `tsc` strict.

**Covers:** UX-DR6, NFR-10.
**Technical notes:**
- No Radix or other dependency beyond the existing `@radix-ui/react-slot`. Keeping it in-house avoids licence-register work.
- Exported from `components/ui/index.ts` if that barrel exists, otherwise imported by path.
**Dependencies:** E0-UX.1.
**Size:** M

### Story E0-UX.5: Toast, EmptyState, ModelMissingNotice and shared state patterns

As any user,
I want consistent notices for finished work, empty lists, missing models, loading and errors,
So that I always know what happened, what will appear, and what to do next.

**Acceptance Criteria:**

**Given** `<Toaster />` mounted once in `App.tsx`, and `useToast()` from `components/ui/toast.tsx`
**When** code calls `toast({ text, action?, kind: "info" | "undo" | "failure" })`
**Then** the toast shows on the popover surface, bottom-right at `md` and up and bottom-centre on phones, with at most one action
**And** at most 3 stack, and a fourth evicts the oldest non-failure toast
**And** info toasts auto-dismiss after 6 s, undo toasts after 10 s, and failure toasts persist until dismissed
**And** the timer pauses while the toast is hovered or holds focus (WCAG 2.2.1)
**And** the text is announced through one `role="status"` (polite) region.

**Given** `components/ui/empty-state.tsx`
**When** a list has no items
**Then** it renders a dashed `rounded-xl` box with 64px/16px padding, a 40px lucide icon in `muted-foreground`, one sentence and at most one primary action
**And** it uses no emoji.

**Given** `components/ui/model-missing-notice.tsx` with `{ model, feature, sizeLabel }`
**When** the viewer is an admin
**Then** it shows the warning wash with a lucide `TriangleAlert` and the copy "The speech model isn't installed. An admin can add it in Admin › Models (~1.5 GB)." with a link
**And** a non-admin sees "Ask your admin" instead of the link
**And** a `reachable=false` variant reads "isn't reachable".

**Given** the shared state helpers `components/ui/skeleton.tsx`, `components/ui/inline-error.tsx` and `components/ui/offline-notice.tsx`
**When** a new surface loads, fails or goes offline
**Then** skeletons take the content's shape (no full-page spinner)
**And** the inline error is a `text-danger` line with the `apiErrorMessage(err)` text and a Retry button, keeping any form input
**And** the offline notice reads "You're offline — changes are paused".

**Given** the voice-and-tone rules
**When** the primitives ship
**Then** `lib/format.ts` exports `formatEta(seconds)`, which returns a range or "about" (for example "about 1–2 min left") and never a bare number, and `entryTitle(title)`, which renders an italic `<em>`.

**Covers:** UX-DR7, UX-DR8, UX-DR13, FR-2 (the Toast and title-prefix substrate that E0-Jobs.10 uses for completion notices), NFR-10.
**Technical notes:**
- The Toast is built in-house, so the licence register doesn't change.
- `useToast` also exports `setTitleBadge(n)` for the "(1)" document-title prefix that the Job tray (E0-Jobs.10) drives.
- Toasts sit at z 70, above SlideOver (50) and PreviewBanner (60).
**Dependencies:** E0-UX.1.
**Size:** M

### Story E0-UX.6: Spoiler-safety components and the Preview shell

As a GM,
I want every hidden thing to look hidden, with the word and an icon, and a preview mode I can't forget I'm in,
So that what Players can see is always obvious to me.

**Acceptance Criteria:**

**Given** `components/ui/visibility-badge.tsx` with `value ∈ {party, gm, private}` and `shared?`
**When** it renders
**Then** `party` is a neutral outline pill with lucide `Eye` and "Party"; `gm` is a gm wash with `Lock` and "GM only"; `private` is an info wash with `UserRound` and "Private"
**And** in GM mode (`editable`) it is a menu button with a chevron offering Party, GM only and Private (where allowed)
**And** choosing Party shows the inline confirmation "Players will see this. Make visible?" before `onChange`, and choosing GM only calls `onChange` at once
**And** with `audience="player"` it renders nothing, except on the Player's own journal, where it shows "Private" or "Shared".

**Given** `components/ui/secret-field.tsx` wrapping a field
**When** it renders for a GM
**Then** it has a dashed gm border at 50%, a 6% gm wash, and the label row "{Label} · GM only" with a lock
**And** screen readers hear "GM only" before the field label
**And** in preview or for a Player it renders nothing (the server omits the data too; this is cosmetic).

**Given** the `FieldVisibilityHint` (`components/ui/field-visibility-hint.tsx`)
**When** a GM focuses a Party text field that uses it
**Then** the `meta` helper "Visible to players", with an `Eye` icon, appears under the field, and it disappears on blur.

**Given** `components/ui/role-badge.tsx`
**When** it is given `gm`, `co_gm` or `player`
**Then** it renders a muted pill reading "GM", "Co-GM" or "Player".

**Given** `contexts/PreviewContext.tsx`, which exports `usePreview()` returning `{ active, enter(campaignId), exit() }`, plus `components/shell/PreviewBanner.tsx`
**When** `active` is true
**Then** a 40px info band sits above the nav (z 60) on every route, reading "Viewing as Player · You're seeing exactly what players see." with an inverted outline "Exit preview" button
**And** `Esc` does not exit preview; only the button does
**And** `useWriteGuard()` returns `{ disabled: true, title: "Preview is read-only" }`, and `components/ui/button.tsx` honours a `write` prop by applying it
**And** the preview flag persists across navigation and a page reload for that tab (`sessionStorage`).

**Covers:** UX-DR11, NFR-10, and the "Preview mode" contract in plan §3.4 (shell part).
**Technical notes:**
- This story provides only the shell. The data path (server-side reduced ctx, cache isolation) is wired by E7.7.
- The components are presentational. Data hiding is always server-side (AD-13), and the AC comments say so to stop client-side hiding being treated as the control.
**Dependencies:** E0-UX.1, E0-UX.4 (menu uses the SegmentedControl/listbox patterns), E0-UX.5.
**Size:** M

### Story E0-UX.7: Global current Campaign and the CampaignSwitcher

As a member of several Campaigns,
I want to pick my current Campaign once, in the nav, and see my Role in it,
So that every page follows that choice and shows the right tools for my Role.

**Acceptance Criteria:**

**Given** `hooks/useCurrentCampaign.ts` and its `CurrentCampaignProvider`
**When** a user picks a Campaign
**Then** the choice is stored per device in `localStorage` under `lk-current-campaign:{userId}`
**And** every page that already has a campaign selector (`components/CampaignSelector.tsx`) defaults to it
**And** queries keyed `[domain, campaignId]` refetch for the new Campaign.

**Given** `components/shell/CampaignSwitcher.tsx` in the NavBar, between the grouped dropdown and the avatar
**When** it opens
**Then** it lists every Campaign the user belongs to, each with a RoleBadge
**And** the current Campaign's name and RoleBadge show on the trigger, truncated at 375 px without overflow
**And** for a GM, a "Preview as Player" item calls `usePreview().enter(campaignId)`.

**Given** the role source
**When** E0-Access's `useCampaignRole(campaignId)` (`GET /api/campaigns/{id}/me`, E0-Access.2) exists
**Then** the switcher uses it
**And** until then, a stub in `hooks/useEffectiveRole.ts` returns `gm` for `is_owner` Campaigns and `player` otherwise, the privacy-first default of D-1b
**And** `useEffectiveRole()` returns `player` while preview is active, whatever the real Role.

**Given** the stored current Campaign was deleted or access was lost
**When** the app loads or the Campaign list refetches
**Then** it falls back to the first remaining Campaign and shows the toast "You no longer have access to that campaign. Switched to *{name}*."
**And** with no Campaigns left, the switcher shows "No campaign" and a link to create one.

**Given** a 375 px viewport
**When** the nav renders with the switcher and the avatar
**Then** there is no horizontal scroll, and every control is ≥ 44px.

**Covers:** UX-DR10 (CampaignSwitcher and global state), D-6(1), NFR-10.
**Technical notes:**
- The roles shown are cosmetic. The server enforces them (AD-13).
- `JobTrayButton` has a reserved slot next to the switcher, filled by E0-Jobs.10.
**Dependencies:** E0-UX.5 (fallback toast), E0-UX.6 (RoleBadge, PreviewContext). Soft: E0-Access.2.
**Size:** M

### Story E0-UX.8: Nav restructure, route redirects, unified not-found and route announcements

As a returning GM or a Player,
I want the nav to show the new grouping for my Role, my old bookmarks to keep working, and a single honest not-found page,
So that the expansion adds no nav bloat, no dead links, and no way to tell "hidden" from "missing".

**Acceptance Criteria:**

**Given** `lib/routes.ts`, a registry where each page route declares `{ path, title, navGroup?, roles }`, and `App.tsx` builds its `<Route>`s from it
**When** a feature epic adds a page
**Then** it adds one registry line, the existing shared append point for `App.tsx` and `NAV_GROUPS`
**And** `isRouteRegistered("/world")` reports whether a target exists.

**Given** the GM `NAV_GROUPS`
**When** the nav renders for a GM
**Then** the groups are:
  - Chronicle: Journal, History, Timeline, **Live Session**, **Keepsakes** (only when registered), **Stats**;
  - Campaign: **World** (only when registered, and then replacing Characters and Quests), Character Sheets, Session Plans, Sources, Shorthand;
  - Collaborate: Sharing, Feedback;
  - Admin (admins only).

**Given** the Player nav set
**When** `useEffectiveRole()` is `player`
**Then** the dropdown shows only Portal, World, My Journal, Chronicler (`/chat`) and Recaps, each only when its route is registered
**And** none of Sources, Shorthand, Session Plans, Live Session or Admin appear.

**Given** the legacy redirect table in `lib/routes.ts`
**When** a user opens `/analytics`
**Then** they land on `/stats`, which renders the existing `AnalyticsPage` (E9 later restyles that page)
**And** `/record` lands on `/live?mode=record`, which renders today's `RecordSessionPage` until E4 registers `LiveSessionPage` for `/live` (E4 keeps the `mode=record` branch)
**And** `/characters` lands on `/world?type=character` and `/quests` on `/world?type=quest` once `/world` is registered. Until then, those two paths keep serving `CharactersPage` and `QuestsPage`
**And** query strings are preserved, and redirects use `replace` so Back doesn't loop.

**Given** any path with no registered route, or a page whose API returns 404
**When** it renders
**Then** `pages/NotFoundPage.tsx` shows "This page doesn't exist or isn't shared with you." with a link home (Dashboard for GMs, Portal for Players when registered)
**And** pages render it through `<NotFound />` on a 404, so a Player opening a GM URL sees exactly what a missing record shows (same copy, same title, no different timing hint).

**Given** any route change
**When** the new page mounts
**Then** `components/shell/RouteAnnouncer.tsx` sets `document.title` ("World · Lorekeeper") and announces the title in a polite live region
**And** pages can add a count through `usePageTitle("World", "214 entities")`, announced as "World, 214 entities"
**And** focus moves to the page's `h1` (`tabIndex=-1`).

**Covers:** UX-DR10 (nav, redirects, Player set, not-found, announcements), D-6(2), NFR-10.
**Technical notes:**
- Registering `/world` (E0-WorldCore.10), `/portal` (E7.1), `/keepsakes` (E5 or E8) and `/live` (E4) activates the nav entries and redirects without editing this story's code.
- `/dashboard` → `/portal` for Players is added by E7.1 through the same table.
- The old NPC and Quest *detail* links are resolved by E0-WorldCore's legacy adapters, not here.
**Dependencies:** E0-UX.7.
**Size:** M

### Story E0-UX.9: Shortcut registry, help overlay and touch-target audit

As a keyboard-heavy GM, or a Player on a phone,
I want shortcuts that never fire while I'm typing, a list I can call up with `?`, and controls big enough to tap,
So that power features are discoverable and nothing misfires at the table.

**Acceptance Criteria:**

**Given** `lib/shortcuts.ts` exporting `useShortcut(key, { scope, description }, handler)`
**When** a key is pressed while focus is in an `input`, `textarea`, `select` or `contenteditable`, or while IME composition is active
**Then** no registered shortcut fires (except `Esc`, which the layer stack handles)
**And** shortcuts registered under a scope fire only while that scope's surface is mounted.

**Given** any page
**When** I press `?` outside an input
**Then** `components/shell/ShortcutHelp.tsx` opens in a SlideOver listing the shortcuts registered for the current page, grouped by scope, with their descriptions
**And** `Esc` closes it and focus returns.

**Given** the new primitives and the shell (`components/ui/*` and `components/shell/*`)
**When** the touch-target audit is done at 375 px
**Then** every interactive control is ≥ 44px in both dimensions, or has a ≥ 44px hit area through padding
**And** no affordance is hover-only below `md`
**And** the result is recorded as a checklist in the PR description.

**Covers:** UX-DR12, NFR-10.
**Technical notes:**
- Feature epics register their own keys (`j/k/a/r/e/u` in E1, `/`, `L` and `+/-/0` in E3, `t` and `Space` in E4, `p` in E10) through `useShortcut`. This story defines none beyond `?`.
- The 56px Table-view target is enforced by E4.
**Dependencies:** E0-UX.3 (layer stack, SlideOver), E0-UX.8 (page registry for the page scope).
**Size:** S

## Epic E0-WorldCore: The world as Campaign-scoped Entities with history

A GM's existing NPCs and Quests become a real World Model of Characters, Locations, Factions, Items and Quests. Each Entity has a wiki page, aliases, a status, history with revert, and merge. Migrated rows start GM-only. Because existing Members became Players in F1-core (D-1b), **Players see no migrated Entity until the GM publishes it**. That is why this epic also ships the bulk-publish path. Phase 0 (D-1c).

**Covers:** FR-4, FR-5, FR-11, FR-12 (tables, suggested Mentions, Mention API), FR-14 (`match_names`), FR-16, FR-17, AR-9, AR-10, AR-18 (legacy copy and adapters), AR-19 F3-world, UX-DR19, UX-DR20, UX-DR21, CI-10 (enum sync for its enums), NFR-8 (migration safety), NFR-5 (EV-4 probes for its routes).

### Story E0-WorldCore.1: Entity Type registry and closed-set enums

As a GM,
I want every Entity Type to have one fixed set of statuses, fields and Party "unset" renderings,
So that statuses mean the same thing on every page, in every Job and in every Player view.

**Acceptance Criteria:**

**Given** `app/domain/entity_types.py`
**When** it is imported
**Then** it defines exactly the types `character`, `location`, `faction`, `item` and `quest`, and the Character kinds `pc`, `npc` and `creature`
**And** each type lists its statuses with a `category ∈ {open, closed_success, closed_failure, closed_other}`. Character: `alive` open, `missing` open, `unknown` open, `deceased` closed_other. Location: `active` open, `destroyed` closed_other, `unknown` open. Faction: `active` open, `disbanded` closed_other, `unknown` open. Item: `active` open, `destroyed` closed_other, `unknown` open. Quest: `active` open, `completed` closed_success, `failed` closed_failure, `abandoned` closed_other
**And** each type lists its typed `attributes` keys (for example Location `region`, Item `holder_entity_id`, Quest `completed_at`) and a default status (`unknown` for every type except Quest, which defaults to `active`).
**Owner amendment (2026-11-01):** the attribute keys also include Character `voice` ("Voice & mannerisms", feeds Talk-to-NPC personas and narration), `appearance`, `pronouns`, `goals` ("Goals & motivation"); Location `kind` (closed set `LocationKind`: settlement, dungeon, wilderness, building, region, plane, other); Faction `goals`; Item `rarity` (free text); Quest `reward` and `location_entity_id` ("Where", a Location). Each can be GM-only like any other field. Memberships (an NPC in a Faction, a PC in the party) are relationship edges (F3), not attributes.

**Given** a field that a Player may not see
**When** the registry is asked for its Party rendering
**Then** it returns that field's unset value: `status → "unknown"` (Quest → `"active"`), `description → null`, `aliases → []`, an attribute → absent. `access.project` uses this for "hidden renders as unset" (AD-13).

**Given** `app/domain/enums.py`
**When** it is imported
**Then** it defines the StrEnums `EntityType`, `CharacterKind`, `EntityChangeOp` (the ops in E0-WorldCore.3), `MentionOrigin ∈ {migration, extraction, manual}` and `MentionSourceField ∈ {narrative, shorthand, gm_notes}` (named apart from the tag enum, RC-12)
**And** a helper `check_sql(enum, column)` renders the `CHECK (column IN (...))` text that migrations use (AD-9: only `visibility` and `campaign_role` are PG enums).

**Given** CI-10 (owned by E0-QA)
**When** it runs
**Then** every StrEnum in `domain/enums.py` matches the CHECK constraint generated for it in the migrated schema, and a status that isn't valid for its type is rejected by `entity_types.validate_status(type, status)`.

**Given** the `journal_tags.source_field` StrEnum that F1-core put in `app/access/enums.py` (Reconciliation RC-12)
**When** this story moves it into `domain/enums.py`
**Then** it keeps its values under the distinct name `TagSourceField {shorthand, narrative, manual}`, so it can't be confused with `MentionSourceField`, and CI-10 checks both CHECK constraints.

- **Covers:** FR-11 (status vocabularies), AR-9, CI-10.
- **Technical notes:** AD-9. Pure domain module with no imports (layer rule, AD-1). `domain/` is owned by E0-WorldCore except `embedding.py` (E0-Platform), `narrators.py` (E5) and `achievements.py` (E9). Unit tests live in `tests/domain/test_entity_types.py`. This module is consumed by B4 (graph styling) and B6 (Quest completion rate, appendix) through the `domain/entity_types.py` contract.
- **Dependencies:** E0-QA.5 (test substrate), E0-QA.10 (CI-10 harness).
- **Size:** S

### Story E0-WorldCore.2: F3-world migration with the legacy NPC/Quest copy

As a GM upgrading Lorekeeper,
I want my existing NPCs and Quests copied into the new World Model with nothing lost and nothing exposed,
So that I keep my whole world and decide myself what my Players can see.

**Acceptance Criteria:**

**Given** a database at the F2-jobs-files head
**When** `alembic upgrade head` runs the F3-world revision
**Then** it creates `entities`, `entity_aliases`, `entity_mentions`, `relationship_types`, `entity_relationships`, `quest_steps` and `entity_changes` with these columns:
- `entities`: `id`, `campaign_id`, `type`, `kind` (Characters only, CHECK), `name`, `description`, `status`, `attributes` JSONB `{}`, `gm_notes`, `visibility` (PG enum, default `gm`), `field_visibility` JSONB `{}`, `linked_user_id` (nullable FK users), `merged_into_id` (nullable), `deleted_at`, `legacy_npc_id` (unique, nullable), `legacy_quest_id` (unique, nullable), `created_by_user_id`, `created_at`, `updated_at`, plus `UNIQUE (campaign_id, id)` as the composite-FK target;
- `entity_aliases`: `id`, `campaign_id`, `entity_id`, `alias`, `normalized_alias`, `visibility_floor` (nullable), with `UNIQUE (campaign_id, entity_id, normalized_alias)`;
- `entity_mentions`: `id`, `campaign_id`, `journal_id`, `entity_id`, `quote`, `source_field` (CHECK), `confirmed` bool, `origin` (CHECK `MentionOrigin`), `visibility_floor`, `span_start`, `span_end`, `created_at`;
- `relationship_types`: `id`, `campaign_id`, `key`, `label`, `inverse_label`, `hostile boolean NOT NULL DEFAULT false` (RC-13, used by E3 to style opposed edges), with `UNIQUE (campaign_id, key)`;
- `entity_relationships`: `id`, `campaign_id`, `source_entity_id`, `target_entity_id`, `relationship_type_id`, `note`, `visibility`, `visibility_floor`, `source_journal_id`, `source_deleted_at`, `started_at`, `ended_at`;
- `quest_steps`: `id`, `campaign_id`, `quest_entity_id`, `position`, `text`, `done`, `done_at`, `source_journal_id`, `source_deleted_at`;
- `entity_changes`: `id`, `campaign_id`, `entity_id`, `op` (CHECK `EntityChangeOp`), `field`, `old_value` JSONB, `new_value` JSONB, `source_journal_id`, `source_deleted_at`, `proposal_id`, `canon_note_id`, `actor_user_id`, `reverted_change_id`, `created_at`. `proposal_id` and `canon_note_id` are indexed UUIDs **without** FKs, because their tables belong to E1 and E2.

**Given** the new tables
**When** the FK actions are inspected (CI-6 FK action test)
**Then** every Entity reference is the composite `(campaign_id, entity_id) → entities(campaign_id, id)`, so a cross-Campaign link fails at insert (FR-4)
**And** every FK to `journal_entries` is `ON DELETE SET NULL` (AD-10), and FKs to `campaigns` are `ON DELETE CASCADE`
**And** the FK `character_sheets.pc_entity_id → entities` deferred from F1-core is added here (AD-19).

**Given** existing `npcs` and `quests` rows
**When** the revision's set-based `INSERT … SELECT … WHERE NOT EXISTS` copy runs
**Then** each NPC with role `npc`, `pc` or `monster` becomes a `character` with kind `npc`, `pc` or `creature`, and role `faction` becomes a `faction` with no kind
**And** NPC status maps `alive → alive`, `dead → deceased`, `unknown → unknown`. A faction's `alive` maps to `active` and `dead` to `disbanded`
**And** each Quest becomes a `quest` with `title → name` and its status unchanged. A `completed` Quest gets `attributes.completed_at = quests.updated_at`
**And** on every copied row `description` carries over, `notes → gm_notes`, `visibility = gm`, `field_visibility = {}`, `created_by_user_id = user_id`, `created_at`/`updated_at` are preserved, and `legacy_npc_id` or `legacy_quest_id` is set
**And** one `entity_changes` row with `op = migrated` is written per copied Entity (actor = the Campaign Owner, no source), so History starts with "Came over from your NPC list".

**Given** the copy has already run
**When** the revision runs again against a copy of production data (downgrade/upgrade or a re-applied SQL block)
**Then** the row counts and contents are identical (idempotent), and the boot (`alembic upgrade head` in the web command) completes without error on the seeded `a3e7c1f9d258` snapshot (CI-6). A row the copy can't map (unknown enum value) maps to `unknown` status, gets logged, and never fails the revision.

**Given** every existing Campaign
**When** the revision runs
**Then** it inserts the default `relationship_types` (`ally_of`, `enemy_of`, `member_of`, `located_in`, `owns`, `related_to`, each with label and inverse label) for that Campaign
**And** it inserts one `data_backfills` row `name = 'suggested_mentions_v1'`, `status = pending` (consumed by E0-WorldCore.7).

**Given** the access registry (`access/registry.py`, shared append point)
**When** the models are registered
**Then** `entities`, `entity_relationships` and `relationship_types` are `stored`, `entity_aliases` and `quest_steps` are `derived` from their Entity, `entity_mentions` is `derived` with the binding Mention formula `most_restrictive(entry, entity, field_aud(source_field), visibility_floor)`, and `entity_changes` is `derived` from its Entity and field (AD-12)
**And** the CI-11 property test (`visible_clause` ≡ `audience_of`) passes with the new models
**And** the models live in `app/db/models/entity.py` (all seven), are registered in `app/db/models/__init__.py`, and every CHECK is generated from `domain/enums.py`.

**Given** `npcs` and `quests` after F3-world
**When** any service writes to them
**Then** a test fails: they are frozen (AD-18). Reads go through the adapters in E0-WorldCore.6.

**Given** the default `relationship_types` rows (Reconciliation RC-13)
**When** they are inserted
**Then** only `enemy_of` has `hostile = true`, and the Relationship type API (E3.1) lets a GM set `hostile` on custom types.

**Given** the optional story E0-Access.14 (owner decision OD-1, option B)
**When** it shipped before this revision
**Then** the copy takes each Entity's `visibility` from the legacy `npcs.visibility`/`quests.visibility` column instead of `gm`. When it did not ship (option A, the default), every copied Entity starts `gm`, as written above.

- **Covers:** FR-4, FR-5 (copy, GM-only start, idempotent, no crash loop), AR-9, AR-18, AR-19 F3-world, NFR-8, CI-6.
- **Technical notes:** AD-9, AD-10, AD-12, AD-18, AD-19. The revision id comes from `alembic revision` and its `down_revision` is the F2-jobs-files head. Alembic contains only schema and set-based SQL (AD-18). The release note text is added to `docs/UPGRADING.md` (new): "Your NPCs and Quests are now Entities. They start GM-only. Your Players, who were Members before this release, see none of them until you publish them from World." Existing source files: `app/db/models/npc.py:9-32`, `app/db/models/quest.py:9-25`.
- **Dependencies:** E0-WorldCore.1, E0-Access.1 (F1-core), E0-Access.3 (access registry, Audiences), E0-Jobs.1 (F2-jobs-files, `data_backfills`), E0-Jobs.5 (`data_backfills` runner), E0-QA.6 (CI-6, CI-7), E0-QA.10 (CI-11 wiring).
- **Size:** L

### Story E0-WorldCore.3: `apply_change`, history and revert

As a GM,
I want every change to my world recorded with its source, its approver and its time, and to be able to revert any of them,
So that I can always see why the world looks the way it does and undo a mistake.

**Acceptance Criteria:**

**Given** `app/services/world_service.py`
**When** `apply_change(db, ctx, change: CanonChange) -> EntityChange` is called
**Then** `CanonChange` (in `app/schemas/entities.py`) is a discriminated model whose `op` is one of `create_entity`, `update_field`, `set_status`, `set_kind`, `add_alias`, `remove_alias`, `add_relationship`, `update_relationship`, `end_relationship`, `add_quest_step`, `update_quest_step`, `add_mention`, `confirm_mention`, `remove_mention`, `delete_entity`, `merge`, `revert`, `source_deleted`, `canon_note` (plus `migrated`, used only by the migration)
**And** it carries optional `source_journal_id`, `proposal_id`, `canon_note_id` and a `quote`
**And** in the same transaction it performs the write on the owning table, appends one `entity_changes` row (`op, field, old_value, new_value, source_journal_id, proposal_id, canon_note_id, actor_user_id`) and adds a `canon_changed` hook event with payload `{campaign_id, refs:[entity ids], actor_ctx}` to `session.info` (AD-17), which fires only after commit.

**Given** a ctx that is not GM and not `ctx.as_system(reason)`
**When** it calls `apply_change`
**Then** the call raises and writes nothing
**And** `ctx.as_system` is accepted only for `reason ∈ {"entry_deleted", "merge"}`. A test asserts that no other module builds it (grep test over `app/`).

**Given** a `set_status` change that moves a Quest into a `closed_success` status
**When** it applies
**Then** `attributes.completed_at` is stamped with the current UTC time, and leaving `closed_success` clears it. Both values are recorded in the change row.

**Given** a change whose `status` isn't valid for the Entity Type, or whose target belongs to another Campaign, is merged or is soft-deleted
**When** it applies
**Then** it raises a typed `CanonChangeError` (`invalid_status`, `not_found`, `merged`, `deleted`) and writes nothing.

**Given** an `entity_changes` row
**When** `revert_change(db, ctx, change_id)` is called
**Then** it applies the inverse change through `apply_change` with `op = revert` and `reverted_change_id = change_id`, so the revert is itself in history (FR-16)
**And** when the field's current value is no longer the reverted row's `new_value` (a later change touched it), it raises `CanonChangeError("superseded")` and the caller must ask the GM to confirm with `force=True`
**And** reverting `create_entity` soft-deletes the Entity. Reverting `merge` is refused (`not_revertible`).

**Given** a change that narrows who can see existing content (`delete_entity`, `remove_mention`, `remove_alias`, or a merge that sets a `visibility_floor`)
**When** it applies
**Then** it marks every `derived_sources` dependent of that Entity (`ref_kind = entity_field`, `ref_id = entity_id`) stale, using the same staleness helper that `access.set_visibility` uses, in the same transaction (AD-13, AD-14).

**Given** a visibility change on an Entity, field, alias, Mention or Relationship
**When** any code path wants it
**Then** it goes through `access.set_visibility`, which calls `apply_change` for these Canon tables (`update_field` with field `visibility` or `field_visibility.<key>`). `apply_change` never takes a visibility value from any other caller.

**Given** the module
**When** `scripts/check_scoped_queries.py` (CI-8) runs
**Then** `world_service.py` adds no unscoped `select(<registered model>)`: reads go through `access.scoped_select`.

- **Covers:** FR-16, AR-10, NFR-7 (Canon changes only through a GM action or a named system reason).
- **Technical notes:** AD-10, AD-12, AD-13, AD-17. `app/hooks/world.py` (new, owned here) handles `canon_changed` by publishing `{domain: "entities", id}` invalidations on `campaign:{campaign_id}:events` through `core/pubsub.py`, registered in `app/hooks/__init__.py`. It adds no channel. `world_service` is consumed through the §3.3 contract by B4 (E3 relationships), B6 (E10 "Create Location…") and E1/E2 in this batch.
- **Dependencies:** E0-WorldCore.2, E0-Access.2 (`CampaignContext`), E0-Access.3 (`scoped_select`), E0-Access.9 (`set_visibility` writer slot, `mark_dependents_stale`), E0-Journal.1 (hook dispatcher, `canon_changed`), E0-Jobs.1 (`derived_sources`), E0-Jobs.6 (`core/pubsub.py`).
- **Size:** L

### Story E0-WorldCore.4: Name matching with `normalize_name` and `match_names`

As a GM,
I want "Brother Aldric", "aldric" and "Áldric" all recognised as the Aldric I already have,
So that features find the right Entity instead of creating duplicates.

**Acceptance Criteria:**

**Given** `world_service.normalize_name(text)`
**When** it is called
**Then** it applies NFKC, casefolds, strips diacritics for comparison only, collapses whitespace, and drops leading articles and honorifics from a configured list (`the`, `a`, `an`, `brother`, `sister`, `lord`, `lady`, `sir`, `captain`, `king`, `queen`) while the stored alias keeps its original surface form.

**Given** `world_service.match_names(ctx, text, *, types=None)`
**When** it is called on a Narrative
**Then** it returns `list[NameMatch(entity_id, surface, start, end, score, exact)]` for every exact match of an Entity name or alias (`score = 1.0`, `exact = True`), longest match first, with no overlapping spans
**And** it uses only names and aliases visible to `ctx` (a Player ctx never matches a GM-only Entity or alias), and never returns merged or deleted Entities. Merged ones resolve to the survivor when ctx can see it (AD-9).

**Given** `world_service.candidates(ctx, surface, *, type=None, limit=3)`
**When** a surface form has no exact match
**Then** it returns up to `limit` fuzzy candidates ranked by RapidFuzz `WRatio` over normalized names and aliases, each with `score ∈ [0, 1]` and `mention_count`, restricted to ctx-visible Entities of the same Campaign.

**Given** two Campaigns that both contain "Mira"
**When** either function is called with one Campaign's ctx
**Then** only that Campaign's Mira is returned (FR-4).

**Given** RapidFuzz is a new dependency
**When** the story merges
**Then** `licenses/register.yaml` has its line (MIT) and the web/worker requirements pin it.

**Given** a Campaign with 300 Entities and 600 aliases
**When** `match_names` runs on a 500-word Narrative
**Then** it completes in ≤ 200 ms on the test runner (a recorded benchmark row in `docs/BENCHMARKS.md` for B5's quick lookup and STT `initial_prompt`).

- **Covers:** FR-14 (matcher part), AR-9 (sole matchers).
- **Technical notes:** AD-9. The automaton is built per call from a ctx-scoped query (cache only with the audience and `access_epoch` in the key, AD-13). E1's embedding shortlist builds on `candidates`, and no other module matches names (B5 live tappable names, lookup, `initial_prompt`; B4 search).
- **Dependencies:** E0-WorldCore.2, E0-Access.3 (`scoped_select`, Audiences), E0-QA.7 (licence register).
- **Size:** M

### Story E0-WorldCore.5: Entity API with GM and Party projections

As a GM,
I want to list, create, edit and delete Entities of every type through one API,
So that my world is editable directly and my Players get only what I've published.

**Acceptance Criteria:**

**Given** `api/routes/entities.py`
**When** it is mounted
**Then** it exposes `GET /api/entities/?campaign_id=&type=&status=&q=&visibility=` (paginated), `POST /api/entities/`, `GET /api/entities/{id}`, `PATCH /api/entities/{id}`, `DELETE /api/entities/{id}`, `POST/DELETE /api/entities/{id}/aliases[/{alias_id}]`, `POST/PATCH /api/entities/{id}/steps[/{step_id}]` (Quests), `GET /api/entities/{id}/history` and `POST /api/entities/{id}/history/{change_id}/revert`
**And** every write calls `world_service.apply_change` or `revert_change` with "Manual edit" provenance (no source entry), and `DELETE` is a soft delete (`delete_entity`)
**And** collections take `campaign_id` as a query parameter, and item routes resolve the Campaign from the row through `require_campaign` (conventions).

**Given** a GM
**When** they read an Entity
**Then** they get `EntityGMResponse` (all fields, `gm_notes`, `visibility`, `field_visibility`, aliases, steps, Mention count)
**And** given a Player or an anonymous Share Link holder, they get `EntityPartyResponse` through `access.project`, which has no `gm_notes` and no `field_visibility`, and in which each hidden field renders exactly as its unset value from E0-WorldCore.1.

**Given** a Campaign right after the F3-world upgrade, with every migrated Entity GM-only, and a Member who was migrated to Player by F1-core
**When** that Player calls `GET /api/entities/?campaign_id=`
**Then** the response is an empty list with total `0`, the same response as a Campaign with no Entities, and `GET /api/entities/{id}` for any migrated Entity returns `404 {"detail":"Not found"}`
**And** once the GM publishes some of them (E0-WorldCore.10's bulk action), the Player sees exactly the published ones on the next request.

**Given** a GM-only Entity, a deleted one, a nonexistent id and an id from another Campaign
**When** a Player requests each
**Then** all four return the identical `404 {"detail":"Not found"}` with the same headers and body.

**Given** a Player
**When** they call any write route above
**Then** it returns `404 {"detail":"Not found"}` and writes nothing (FR-7 write rule).

**Given** `POST /api/entities/{id}/visibility` (body `{visibility, field?}`) and `POST /api/entities/visibility` (body `{campaign_id, entity_ids[], visibility}`, at most 500 ids)
**When** a GM calls them
**Then** each goes through `access.set_visibility`, the bulk one in a single transaction, and returns the updated count. These are the only Entity visibility writers in the API.

**Given** the duplicate check on `POST`
**When** a GM creates an Entity whose normalized name equals an existing one of the same type
**Then** it returns 409 with the existing id, counting only rows visible to the ctx (AD-13).

**Given** the standing ACs for new routes
**When** the story merges
**Then** `tests/ev4/probes/entities.py` covers every route with the families canary, hidden vs nonexistent, hidden vs unset field (`status` hidden → `"unknown"`), counts (`total` equals the Party-only fixture) and Public vs Members vs Owner(other)
**And** each route has a `locations.conf` line in the generic `api` zone.

**Given** `access.register_resolver` (E0-Access.8) (Reconciliation RC-10)
**When** this story lands
**Then** it registers the `entity_field` resolver (title = Entity name and field label, quote = the field's current value through `project`), so E2 and E5 citations of Entity fields resolve.

- **Covers:** FR-11 (CRUD, list per type, Player view), FR-4, FR-5 (Players see nothing until published), FR-8 (Entity projection), FR-16 (history and revert routes), NFR-5.
- **Technical notes:** AD-9, AD-10, AD-12, AD-13, AD-20. Schemas `EntityGMResponse`, `EntityPartyResponse`, `EntityCreate`, `EntityPatch` in `app/schemas/entities.py`. History responses are projected per row (derived from Entity and field). The bulk route is the Entity-specific path for UX-DR19. E7 owns bulk controls on the other list views (D-4 style split, see Decisions).
- **Dependencies:** E0-WorldCore.3, E0-WorldCore.4, E0-Access.2 (`require_campaign`), E0-Access.4 (`project`, uniform 404), E0-Access.8 (`register_resolver`), E0-Access.9 (`set_visibility`), E0-QA.11 (EV-4 harness).
- **Size:** L

### Story E0-WorldCore.6: Legacy NPC and Quest adapters and old-link resolver

As a GM with bookmarks and habits from before the upgrade,
I want the old NPC and Quest pages and links to keep working,
So that nothing breaks while the World pages take over.

**Acceptance Criteria:**

**Given** `api/routes/npcs.py` and `api/routes/quests.py`
**When** the story merges
**Then** every existing route keeps its path and response shape (`NpcRole`, `NpcStatus`, `QuestStatus` legacy enums) but reads `entities` filtered by `legacy_npc_id`/`legacy_quest_id` or by type (Characters and Factions for `/npcs`, Quests for `/quests`), with ids translated so existing clients keep working
**And** an Entity created after the upgrade appears in the matching legacy list with its Entity id
**And** every write (`POST`, `PUT`) goes through `apply_change` and never touches the frozen `npcs`/`quests` tables, with the status mapped back (`deceased → dead`; `missing → unknown`; Location/Item types are not listed in `/npcs`).

**Given** a Player
**When** they call the legacy list routes
**Then** they see only Party Entities through `access.project`, which means none right after the upgrade, and the legacy write routes return 404.

**Given** `GET /api/npcs/{id}/entries` and `GET /api/quests/{id}/entries`
**When** they are called
**Then** they return the Entity's **confirmed** Mentions' entries, newest first, filtered by the Mention audience formula, and no longer run the ILIKE on name or Shorthand (`npcs.py:103-115`, `quests.py:108,132`; AR-26).

**Given** `GET /api/entities/legacy/{npc|quest}/{id}`
**When** it is called with an old NPC or Quest id
**Then** it returns `{entity_id, type}` for a ctx that can see the Entity, follows `merged_into_id` to a visible survivor, and otherwise returns `404 {"detail":"Not found"}`.

**Given** `POST /api/npcs/extract`, `POST /api/npcs/{id}/generate` and `POST /api/quests/suggest`
**When** a GM calls them
**Then** they behave as before (draft only, nothing persisted) and read Entity data. For Players they stay locked out (E0-Access lockout list).

**Given** EV-4
**When** it runs
**Then** the existing probes for `npcs.py` and `quests.py` pass against the adapters, and `tests/ev4/probes/entities.py` covers the resolver route.

- **Covers:** FR-5 (old links resolve), AR-18 (legacy routes become adapters), AR-26 (`/entries` ILIKE removed).
- **Technical notes:** AD-18, AD-13. `CharactersPage.tsx`, `QuestsPage.tsx`, `NpcDetailPanel.tsx` and `QuestDetailPanel.tsx` keep working unchanged against the adapters until E0-UX's redirects (`/characters`, `/quests` → `/world?type=…`) and E0-WorldCore.10 replace them. The frontend redirect for an old panel link (`?npc=<id>`) calls the resolver.
- **Dependencies:** E0-WorldCore.5, E0-Access.4 (Party schemas for existing routes), E0-Access.6 (Player lockout list).
- **Size:** M

### Story E0-WorldCore.7: Suggested Mentions backfill and Mention confirm/remove

As a GM,
I want my old entries linked to the Entities they name, as suggestions I confirm or remove,
So that every Entity page shows where it appears in my journal from day one.

**Acceptance Criteria:**

**Given** the `data_backfills` row `suggested_mentions_v1` in `pending`
**When** the worker starts it
**Then** a `backfill.mentions` cursor Job runs per Campaign with that Campaign's Owner GM ctx, processes one Journal Entry per step in Session order, records progress on the same row, and re-enqueues itself with the next cursor (AD-3, B2 cursor contract)
**And** for each `kind = gm` entry it calls `match_names` on the Narrative only and writes, through `apply_change(op = add_mention)`, one Mention per Entity per entry with `confirmed = false`, `origin = migration`, `source_field = narrative` and `quote` = the sentence holding the first match (≤ 300 characters)
**And** re-running it (or a crash and resume) never creates a duplicate Mention (`UNIQUE (journal_id, entity_id, source_field)` for suggested rows, upsert on conflict), and the row ends in `done`.

**Given** `jobs/registry.py`
**When** `backfill.mentions` is registered
**Then** it has `queue = backfill`, `timeout_s = 120`, `resources = {}`, `live_safe = true`, `result_audience = gm`, and its idempotency key is `backfill.mentions:{campaign_id}:{cursor}`.

**Given** `GET /api/entities/{id}/mentions?confirmed=&page=` and `GET /api/entities/mentions?journal_id=`
**When** a GM calls them
**Then** the first returns the Entity's Mentions newest first (Session order) in pages of 20, each with `quote`, `journal_id`, entry title, `confirmed` and `origin`
**And** the second returns the Entities a given entry mentions, used by the entry view (FR-12)
**And** for a Player both return only confirmed Mentions whose audience under the binding formula includes them, so a Shorthand- or `gm_notes`-sourced Mention never reaches a Player.

**Given** a suggested Mention
**When** a GM calls `POST /api/entities/{id}/mentions/{mention_id}/confirm` or `DELETE /api/entities/{id}/mentions/{mention_id}`
**Then** `apply_change` records `confirm_mention` or `remove_mention`, the Mention list updates, and only confirmed Mentions count toward NPC Knowledge, "my character" and most-mentioned stats (§3.3 Mentions contract).

**Given** EV-4
**When** it runs
**Then** `tests/ev4/probes/entities.py` covers the Mention routes, including a canary that appears only in Shorthand: it creates no Party-visible Mention and doesn't change a Player's Mention counts.

- **Covers:** FR-5 (suggested Mentions), FR-12 (Mentions table, Entity and entry Mention lists), NFR-5.
- **Technical notes:** AD-3, AD-12, AD-18. The handler is `app/jobs/world.py` (owned here), with the handler signature `async def handle(job, ctx, db)`. The `UNIQUE` index for suggested Mentions is added in this story's own small revision on top of F3-world, because it isn't in AD-19's F3 list (see Decisions). Extraction-created Mentions come from E1 through `add_mention` proposals.
- **Dependencies:** E0-WorldCore.5, E0-Jobs.2 (`jobs/registry.py`), E0-Jobs.5 (cursor backfill, `data_backfills` runner), E0-QA.11 (EV-4 harness).
- **Size:** M

### Story E0-WorldCore.8: Journal delete detaches the entry from the world

As a GM,
I want deleting an entry to remove its Mentions and to flag any Canon fact that rested only on it,
So that my world never cites a deleted entry and I decide what happens to the orphaned facts.

**Acceptance Criteria:**

**Given** `world_service.detach_entry(db, ctx, journal_id)` (B2 "Journal delete → World" contract)
**When** `journal_service.delete_journal_entry` calls it with `ctx.as_system("entry_deleted")` in the delete transaction, before the row is removed
**Then** every Mention of the entry is removed through `apply_change(op = remove_mention)`
**And** every `entity_changes`, `entity_relationships` and `quest_steps` row that cites the entry gets `source_deleted_at = now()` (the FK then sets `source_journal_id` to NULL on delete)
**And** for each current Canon field (status, description, attribute, Relationship, Quest step) whose latest change cites only this entry, it writes an `entity_changes` row `op = source_deleted` with `new_value = {journal_id, field, current_value}`, which History shows as "source deleted".

**Given** the delete commits
**When** the hooks fire
**Then** `canon_changed` fires for every touched Entity, and approved Canon values themselves are unchanged (FR-6: "approved Canon never changes automatically").

**Given** the delete is rolled back
**When** the transaction aborts
**Then** no Mention is removed and no `source_deleted` row exists.

**Given** a citation to the deleted entry (`SourceRef kind = journal`)
**When** `access.resolve_sources` resolves it
**Then** it no longer resolves to content. That is E0-Access behaviour, and this story asserts it in a test.

- **Covers:** FR-6 (delete removes Mentions, flags single-source Canon fields, history shows "source deleted"), AR-10 (delete).
- **Technical notes:** AD-10, AD-17. This story replaces B2's no-op stub. Supersession of pending proposals and the `confirm_field` review items are raised by E1's `entry_deleted` handler from these `source_deleted` rows (E1.3), because `change_proposals` doesn't exist yet. NPC Knowledge grants (E6) and `map_pin_entries` (E10) are cleaned up by their own epics.
- **Dependencies:** E0-WorldCore.7, E0-Journal.3 (`delete_journal_entry` calls `detach_entry`, `entry_deleted`).
- **Size:** S

### Story E0-WorldCore.9: Merge two Entities

As a GM,
I want to merge two Entities of the same type,
So that the duplicate "Brother Aldric" disappears into Aldric without losing anything or exposing GM-only facts.

**Acceptance Criteria:**

**Given** `world_service.merge(db, ctx, survivor_id, absorbed_id, *, preview=False)`
**When** a GM calls it with two Entities of the same type in the same Campaign
**Then** it builds `ctx.as_system("merge")` internally and, through `apply_change(op = merge)`, re-points the absorbed Entity's aliases, Mentions, Relationships (both ends, dropping self-loops), Quest steps and history to the survivor
**And** it adds the absorbed name as an alias of the survivor
**And** it sets `absorbed.merged_into_id = survivor_id`, keeping the absorbed row
**And** it sets `visibility_floor` on every moved alias, Mention and Relationship to the absorbed Entity's visibility. Each field that both carried keeps the more restrictive visibility (FR-17)
**And** it returns `MergeResult{downgrades:[{kind, id, from, to}], moved_counts}`.

**Given** `preview=True`
**When** it is called
**Then** it returns the same `MergeResult` plus the combined aliases, the Mention count and the Relationships, and writes nothing.

**Given** a Party survivor and a GM-only absorbed Entity
**When** the preview runs
**Then** `downgrades` is non-empty, and the API sets `warning = "party_with_gm_only"`.

**Given** two Entities of different types or Campaigns, or an already merged one
**When** merge is called
**Then** it returns 422 (type), or 404 for another Campaign or a merged id, and writes nothing.

**Given** `POST /api/entities/{id}/merge` (body `{absorbed_id, preview}`)
**When** it is called
**Then** it is GM-only (404 for Players), registered in `locations.conf`, and covered in `tests/ev4/probes/entities.py`, including a downgrade probe: after merging a GM-only Entity into a Party one, a Player sees none of the moved aliases, Mentions or Relationships.

**Given** a link or resolver call to the absorbed Entity
**When** a GM or a Player who can see the survivor follows it
**Then** it resolves to the survivor (FR-17), and to a Player who can't see the survivor it is `404`.

**Given** merge narrows an audience
**When** it commits
**Then** `derived_sources` dependents of both Entities are marked stale (E0-WorldCore.3 rule), and merge is not revertible.

- **Covers:** FR-17, AR-10 (merge sets `visibility_floor`).
- **Technical notes:** AD-9, AD-10, AD-12. Proposals whose target was merged become stale at apply and are redirected (E1.4). That works because `merged_into_id` is kept.
- **Dependencies:** E0-WorldCore.5, E0-Access.2 (`as_system("merge")`), E0-Access.9 (`visibility_floor` exception).
- **Size:** M

### Story E0-WorldCore.10: World hub, Entity page and panel, with bulk publish

As a GM,
I want one World page listing every Entity with a wiki page for each, and a way to publish many at once,
So that I can browse my world and show my Players what they have met.

**Acceptance Criteria:**

**Given** the routes `/world` (with `?type=`), `/world/:type/:id` and their `App.tsx` lines and a `NAV_GROUPS` "World" line (shared append points)
**When** a GM opens `/world`
**Then** they see type chips (All · Characters · Locations · Factions · Items · Quests), a search field and a card grid. Each card shows name, type icon, StatusBadge, VisibilityBadge (GM only) and Mention count
**And** loading shows card skeletons, the empty state reads "No entities yet. They appear as you save journal entries and approve the changes." with "Add an entity", and a Player's empty state reads "Nothing has been shared with the party yet."

**Given** a Campaign where every Entity has `legacy_npc_id`/`legacy_quest_id` and is GM-only (just upgraded)
**When** a GM opens `/world`
**Then** a callout reads "{n} entities came over from your old NPC and Quest lists. They're GM-only until you publish them." with "Review and publish", which opens selection mode filtered to GM-only (UX-DR19)
**And** the callout disappears once none of the migrated Entities is GM-only, or when the GM dismisses it (stored per Campaign on the device).

**Given** selection mode
**When** the GM selects 24 Entities and chooses Set visibility › Party
**Then** an inline confirm asks "Make 24 entities visible to players?", and on confirm one `POST /api/entities/visibility` call publishes them and a Toast confirms. Moving to GM-only needs no confirmation.

**Given** `/world/:type/:id` (EntityPage, `md:grid-cols-[1fr_280px]`) and `EntityPanel` (the same content in a wide SlideOver, with "Open full page")
**When** either opens
**Then** `components/entities/EntityDetailPanel.tsx` renders the sections registered in `components/entities/panelSections.ts` for that Entity Type, in registry order. This story registers Overview (description, aliases, status, GM notes as a SecretField), Mentions and History. Relationships (E3), On maps (E10), Knowledge and "Talk to" (E6) register later and never edit the panel
**And** a section with no data shows a one-line hint for GMs ("No relationships yet") and is absent for Players, leaving no gap
**And** the header overflow has Edit · Merge… · Set visibility · Delete (Re-run extraction is added by E1 through a registered overflow action) and each section edits inline with Save and Cancel, like `NpcDetailPanel.tsx`.

**Given** an Entity that is merged or deleted while its page is open
**When** a `campaign:{id}:events` invalidation arrives through `useCampaignEvents`
**Then** the page shows "This entity was merged into *Aldric*" with a link, or "This entity was deleted".

**Given** a Player, or a GM in preview mode
**When** they open the same routes
**Then** the data comes from the server's Party read path, write controls are absent (Player) or disabled with "Preview is read-only" (preview flag, B4 contract), and no SecretField is rendered.

**Given** the standing UI ACs
**When** the story merges
**Then** the surfaces use theme and semantic tokens only, work at 375 px with no horizontal scroll, are keyboard operable with visible focus, respect reduced motion, and use `EmptyState`, skeletons and inline `danger` errors with Retry.

**Given** `components/entities/worldTabs.ts` exporting `registerWorldTab({id, path, label, roles})` (Reconciliation RC-14, a new shared append point)
**When** E3 registers `{id: "web", path: "/world/web", label: "Web"}` (or E10 registers Maps)
**Then** the World hub shows that tab next to "Entities" without this story's code changing, and with nothing registered the hub shows only the entity grid and no tab bar
**And** for a GM, the Entity page overflow includes "Preview this page as a Player", which calls `usePreview().enter(campaignId)` (E0-UX.6) and keeps the current route.

- **Covers:** FR-11 (list pages and detail panel), FR-5 (publish path), UX-DR19, UX-DR20, NFR-10.
- **Technical notes:** AR-24 conventions: `services/api/entities.ts`, `types/entities.ts`, `hooks/useEntities.ts` with keys `["entities", campaignId, …]`. The panel is built from `components/NpcDetailPanel.tsx` + `components/SlideOver.tsx` (`size="wide"`). Primitives come from E0-UX (`Tabs`, `Combobox`, `VisibilityBadge`, `SecretField`, `EmptyState`, `Toast`). `panelSections.ts` exports `registerPanelSection({id, types, order, gmOnly, component})` and `registerOverflowAction({id, types, gmOnly, label, onSelect})`. Entity Type icons are lucide.
- **Dependencies:** E0-WorldCore.5, E0-WorldCore.7, E0-UX.3 (SlideOver wide), E0-UX.4 (Tabs, Combobox), E0-UX.5 (Toast, EmptyState), E0-UX.6 (VisibilityBadge, SecretField, `usePreview`), E0-UX.7 (`useCurrentCampaign`), E0-UX.8 (`NAV_GROUPS`, route registry), E0-Access.2 (`useCampaignRole`), E0-Access.11 (`useCampaignEvents`).
- **Size:** L

### Story E0-WorldCore.11: Status, history, Mentions and merge on the Entity page

As a GM,
I want to change a status in one click, see and revert every change with its source, confirm suggested Mentions, and merge duplicates from the Entity page,
So that I can curate my world without hunting through menus.

**Acceptance Criteria:**

**Given** the StatusBadge (colour + icon + word, semantic tokens)
**When** a GM clicks it and picks another status valid for the type
**Then** `PATCH /api/entities/{id}` records a "Manual edit" history row, and the badge shows "since *{entry}*" when the latest status change has a source entry.

**Given** the HistoryList section
**When** it renders
**Then** each row shows a mono date, the diff (old struck, new bold), the source entry as a link (or "Manual edit"), and the approver
**And** "Revert" asks inline ("Restore *alive*?") and, on confirm, calls the revert route. A `superseded` answer asks again with "A later change touched this. Revert anyway?"
**And** `source_deleted` rows show "source deleted" with a Review action that opens the Reviews queue entry when one exists
**And** `canon_note` rows render as a Canon Note block ("Retcon · {reason}") from the row's snapshot, and `migrated` rows read "Came over from your NPC list" (UX-DR21).

**Given** the MentionList section
**When** it renders
**Then** it lists Mentions newest first in pages of 20. Suggested Mentions are dashed with Confirm and Remove. Clicking a quote opens `/journal/:id` scrolled to and highlighting the quote.

**Given** Merge… in the overflow menu
**When** the GM picks the other Entity (a `Combobox` limited to the same type)
**Then** a SlideOver shows the preview (combined aliases, Mention count, Relationships). If `warning = party_with_gm_only`, it explains that merged fields keep the more restrictive Visibility. "Merge" applies it and navigates to the survivor.

**Given** an `EntityCard` (name, type, status, one-line description, latest Mention)
**When** another epic needs a compact Entity view (lookup, graph hover, pin popover)
**Then** it imports `components/entities/EntityCard.tsx`, which renders from `EntityPartyResponse` or `EntityGMResponse` without extra requests.

**Given** the standing UI ACs
**When** the story merges
**Then** every control is keyboard operable, inline confirms trap no focus and return focus to the trigger, and every touch target is at least 44 px.

- **Covers:** FR-16 (history UI and revert), FR-17 (merge UI and warning), FR-12 (Entity Mention list), UX-DR21, NFR-10.
- **Technical notes:** AD-10, AR-24. `components/entities/StatusBadge.tsx`, `HistoryList.tsx`, `MentionList.tsx`, `MergeDialog.tsx`, `EntityCard.tsx`. These are registered as the Overview/History/Mentions section components from E0-WorldCore.10. Quote highlighting on `EntryDetailPage.tsx` reads a `?quote=` parameter (a one-line addition).
- **Dependencies:** E0-WorldCore.9, E0-WorldCore.10.
- **Size:** M

## Epic E1: The journal updates the world (extraction and Review Checklist)

After saving her notes, the GM gets a short grouped Review Checklist (New / Changed / Quest progress) of proposed world changes. She approves, rejects or edits each item, or uses "Approve all", and applies the ones she approves. Nothing becomes Canon without her. The checklist extends the look, copy and draft-then-commit contract of `NarrativeReviewPanel` (owner decision). EV-1 measures extraction on a committed, seeded demo Campaign, and EV runs happen on the remote GPU desktop. Phase 1.

**Covers:** FR-12, FR-13, FR-14, FR-15, FR-18, FR-6 (supersede and re-queue handler), FR-55 (renderer slot), FR-3 (EV-1 schema-valid measurement), NFR-6 (extraction row), NFR-7, NFR-9, NFR-10 (keyboard checklist), AR-11 (proposals), EV-1, SM-1, SM-6, DS-1, UX-DR15, UX-DR16, UX-DR17, UX-DR18, UX-DR22 (Mentions strip).

### Story E1.1: Proposal tables and per-op payload schemas

As a GM,
I want every proposed world change stored as a typed, deduplicated item tied to its entry,
So that nothing I reject comes back and nothing I approve is applied twice.

**Acceptance Criteria:**

**Given** a new Alembic revision rebased onto head
**When** it runs
**Then** it creates `proposal_batches(id, campaign_id, journal_id, job_id, entry_hash, origin, created_at)` with `origin ∈ {extraction, override, promotion, source_deleted}` (CHECK from a StrEnum), and FKs to `journal_entries` `ON DELETE SET NULL`
**And** it creates `change_proposals(id, campaign_id, batch_id, journal_id, op, target_entity_id, target_ref, payload JSONB, old_value JSONB, new_value JSONB, quote, source_field, default_visibility, chosen_visibility, state, fingerprint, match_candidates JSONB, attention JSONB, decided_by, decided_at, applied_change_ids UUID[], created_at)`
**And** `op ∈ {create_entity, update_field, set_status, add_alias, add_relationship, end_relationship, quest_progress, add_mention, confirm_field}`, `state ∈ {pending, edited, approved, rejected, stale, superseded}` and `source_field ∈ {narrative, shorthand, gm_notes}`, each a CHECK generated from `domain/enums.py` StrEnums (appended lines)
**And** `UNIQUE (journal_id, fingerprint) WHERE state <> 'superseded'` exists
**And** `target_entity_id` is a composite FK `(campaign_id, target_entity_id) → entities`.

**Given** `app/schemas/proposals.py`
**When** a payload is validated
**Then** each op has its own pydantic model (`extra="forbid"`). `create_entity` and `update_field` carry per-field `field_visibility`. `add_relationship` may reference a sibling `create_entity` proposal by `target_ref` (a batch-local id) instead of an Entity id
**And** `fingerprint(origin, op, target, field, new_value) = sha256` of `origin|op|target|field|normalize(new_value)`, where `target` is the Entity id or the normalized name for a new Entity, and `normalize` uses `world_service.normalize_name` for names and lower-cased trimmed text otherwise.

**Given** `access/registry.py`
**When** the models are registered
**Then** `proposal_batches` and `change_proposals` are `always_gm`, so no Player or Share Link response, count or AI context can contain them (FR-15 "Players never see Change Proposals").

**Given** CI-6, CI-7 and CI-10
**When** they run
**Then** there is a single head, the boundary map shows E1 as the only owner of both tables, and the StrEnums match their CHECKs.

- **Covers:** AR-11 (proposal part), FR-15 (states, Players never see proposals), FR-18 (fingerprint basis).
- **Technical notes:** AD-11, AD-19. Models are in `app/db/models/proposal.py`. `confirm_field` has no LLM origin: it is raised from `source_deleted` history rows (E1.3).
- **Dependencies:** E0-WorldCore.2 (F3-world tables), E0-WorldCore.4 (`normalize_name`), E0-Access.3 (access registry), E0-QA.6 (CI-6, CI-7), E0-QA.10 (CI-10).
- **Size:** S

### Story E1.2: Extraction service turns an entry into Change Proposals

As a GM,
I want the local AI to read my entry against my current world and propose new Entities, status and field changes, Relationships, Quest progress and Mentions, each with its quote,
So that I only have to check its work instead of updating every page by hand.

**Acceptance Criteria:**

**Given** `extraction_service.extract(db, ctx, journal_id, *, origin, llm_class, options) -> ExtractionResult`
**When** it runs on a saved entry
**Then** it builds an Entity shortlist: every `match_names` hit in the Narrative and Shorthand, plus, for each NER span from `ml /v1/ner` (when `options.ner_prepass` is on), the top 5 of `world_service.candidates` re-ranked by `ml /v1/embed` cosine similarity over the RapidFuzz top 20
**And** `options.entity_list ∈ {shortlist, full, none}` selects what goes in the prompt (operating points for EV-1 and SPIKE-6), defaulting to `shortlist`
**And** the prompt is fitted with `prompt_budget.fit("extraction", parts)`, which drops the lowest-scored shortlist entries first. An entry that still doesn't fit is processed as paragraph windows in sequence, and the proposals are de-duplicated by fingerprint.

**Given** `schemas/llm/extraction.py`
**When** the schema is defined
**Then** `ExtractionOutput{changes: list[ExtractedChange]}` is flat: no `$ref`, no `anyOf`, `extra="forbid"`, enums for `op`, `entity_type`, `field` and `source_field`, and strings for `entity_name`, `new_value`, `related_entity_name`, `relationship_type`, `quest_step` and `quote` (CI-9)
**And** the call is `async with llm_slot(llm_class)` then `complete_structured(messages, ExtractionOutput, config, task="extraction", timeout=…)`, so an invalid answer gets at most 2 repairs and then raises `StructuredOutputError` with nothing written (FR-3).

**Given** the parsed changes
**When** each is resolved
**Then** a name that `match_names` resolves exactly to a ctx-visible Entity (name or alias) becomes an op on that Entity, never `create_entity` (FR-14)
**And** a name whose best `candidates` score is in the uncertain band (`EXTRACTION_MATCH_LOW` ≤ score < `EXTRACTION_MATCH_HIGH`, defaults 0.60 and 0.90, tuned by EV-1) becomes `create_entity` with up to 3 `match_candidates` (`entity_id, name, type, mention_count, score`) and `attention` contains `possible_duplicate`
**And** a score ≥ `EXTRACTION_MATCH_HIGH` becomes an `add_alias` on that Entity (with any field changes as sibling items).

**Given** a resolved change
**When** `old_value` is read from current Canon
**Then** a change whose `new_value` equals the current value (after normalization) is dropped and never shown (FR-13 "no-op proposals hidden")
**And** a `quote` that doesn't occur in the entry's `source_field` text (after whitespace normalization) is dropped and counted in `ExtractionResult.dropped_unquoted` (NFR-7 grounding).

**Given** each kept change
**When** its default Visibility is computed
**Then** `default_visibility = most_restrictive(entry audience, field_aud(source_field))`, so any fact quoted only from Shorthand or `gm_notes` defaults to `gm`, a Narrative fact in a Party GM entry defaults to `party`, and anything from a Private Player Journal (`origin = promotion`) defaults to `gm` (AD-11)
**And** `create_entity` sets per-field `field_visibility` the same way per field, and `attention` gets `from_shorthand` when `source_field = shorthand`, and `gm_default_on_party_fact` when the default is `gm` while the same fact also appears in the Narrative.

**Given** Mentions
**When** a change targets an Entity
**Then** a supporting `add_mention` (`source_field`, quote, span) is produced for each Entity the entry mentions that has no confirmed Mention from this entry yet, so approving the main item can also confirm the Mention (E1.5).

**Given** the fake LLM provider (`ENVIRONMENT=test`) and the `ml` client fakes
**When** the unit tests run on a fixture entry with "Mira died in the fire", "Brother Aldric" and a new "Sunken Archive"
**Then** the result holds `set_status` Mira alive→deceased, `create_entity` Brother Aldric with candidate Aldric and `possible_duplicate`, `create_entity` Sunken Archive (location), and no proposal for an unchanged fact.

- **Covers:** FR-13 (proposal types, quote, default Visibility, old/new values, no-ops hidden), FR-14 (alias or candidate matching, ≤ 3 candidates), FR-12 (extraction Mentions), FR-3, NFR-7.
- **Technical notes:** AD-8, AD-11, AD-12. `extraction_service.py` writes nothing: it returns `ExtractionResult{proposals, dropped_unquoted, schema_attempts, timings}`. Settings `extraction_match_low`, `extraction_match_high`, `extraction_entity_list`, `extraction_ner_prepass` go in `app/core/config.py`. The prompt puts grounding instructions in the final user turn (conventions). The prompt shape is internal and deferred to SPIKE-6/EV-1 (spine Deferred).
- **Dependencies:** E1.1, E0-WorldCore.4 (`match_names`, `candidates`), E0-LLM.2 (`llm_slot`), E0-LLM.3 (`prompt_budget.fit`), E0-LLM.4 (`complete_structured`), E0-LLM.5 (fake provider), E0-Platform.3 (`ml` client `ner`, `embed`).
- **Size:** L

### Story E1.3: `extraction.run` Job, save and edit hooks, and delete handling

As a GM,
I want extraction to start by itself after I save or edit an entry, without ever slowing the save,
So that my checklist is ready a few minutes later and always matches the latest text.

**Acceptance Criteria:**

**Given** `app/hooks/extraction.py` registered in `app/hooks/__init__.py` for `entry_saved` and `entry_updated`
**When** a GM-authored (`kind = gm`) entry is saved or edited and the transaction commits
**Then** it calls `enqueue(db, ctx, "extraction.run", {journal_id, entry_hash}, idempotency_key="extraction.run:{journal_id}:{entry_hash}")` with the actor's ctx
**And** for `kind = player` entries it does nothing (FR-42: extraction only when a GM triggers it)
**And** the save response is unaffected by the hook, which never raises into the save (NFR-9).

**Given** `jobs/registry.py`
**When** `extraction.run` is registered
**Then** it has `queue = onsave`, `timeout_s = 600`, `resources = {llm}`, `live_safe = false` and `result_audience = gm`.

**Given** the handler `jobs/extraction.py: handle(job, ctx, db)`
**When** it runs
**Then** it reports stages `"Reading for world changes"` then `"Matching entities"` with progress and an ETA on the row, calls `extraction_service.extract(..., origin="extraction", llm_class="job_onsave")`, and writes one `proposal_batches` row (with the Job's `entry_hash`) plus its `change_proposals` with `INSERT … ON CONFLICT (journal_id, fingerprint) DO NOTHING`
**And** so a fingerprint already `approved`, `rejected`, `edited` or `pending` for that entry is never inserted again (FR-15 "rejected never re-raised", FR-18 "never duplicates pending")
**And** `result_ref = {batch_id, counts:{new, changed, quest_progress}}`
**And** an entry whose current `entry_hash` no longer matches the Job's ends `cancelled` with no batch (a newer Job exists).

**Given** a `StructuredOutputError` or `LLMConfigError`
**When** it occurs
**Then** the Job fails without retry (AD-4 terminal) with `error_code` mapped to "The model's answer couldn't be read" / the config message, the entry stays saved, and no partial batch exists. Other errors retry at 10 s then 60 s.

**Given** an `entry_updated` event (FR-6)
**When** the handler runs before enqueuing
**Then** every `pending` proposal of that entry's earlier batches becomes `superseded`. `edited` proposals are kept and become `stale` at apply because their batch `entry_hash` differs (AD-10). Approved Canon is untouched.

**Given** an `entry_deleted` event
**When** the handler runs
**Then** every `pending`/`edited` proposal of that entry becomes `superseded`
**And** for each `source_deleted` history row written by `world_service.detach_entry` for that journal id, it creates one `proposal_batches(origin = source_deleted, journal_id = NULL)` per Entity with a `confirm_field` proposal (`old_value` = current value, quote = "Its only source was deleted"), so the GM can keep or clear the fact (FR-6).

**Given** EV-5
**When** `scripts/eval_extraction.py --benchmark` (E1.10) runs
**Then** this Job's wall-clock time on a ≈ 500-word entry is recorded as the NFR-6 "Change Proposals ready after save" row in `docs/BENCHMARKS.md` (targets ≤ 3 min CPU, ≤ 30 s GPU; hardware labelled).

**Given** a GM ctx that enqueues `extraction.run` with payload `{journal_id, entry_hash, origin: "promotion"}` for a `kind = player` entry (Reconciliation RC-16, for E7.8)
**When** the handler runs
**Then** it runs only because `origin = promotion` and the ctx is GM (a Player ctx, or a `kind = player` entry without that origin, ends `cancelled` with no batch), calls `extract(..., origin="promotion")`, and writes `proposal_batches(origin = promotion)` whose proposals all default to `gm` (Decision B4-D10)
**And** its idempotency key is `extraction.run:{journal_id}:{entry_hash}:promotion`, so it never collides with a hook-started Job, and the save and edit hooks still skip `kind = player` entries.

- **Covers:** FR-13 (queued on save and edit), FR-6 (supersede and re-queue; delete supersedes and raises `confirm_field`), FR-15 (never re-raised), NFR-9, NFR-6 (row), AR-11.
- **Technical notes:** AD-2, AD-4, AD-11, AD-17. Hook handlers may import only services, `jobs.enqueue`, access, schemas, domain and core (AD-1). The continuity Job ordering is set by E2's hook, which looks this Job up by its idempotency key (see E2.3 and Decisions).
- **Dependencies:** E1.2, E0-Jobs.2 (`enqueue`, registry), E0-Jobs.3 (handler signature), E0-Jobs.7 (Job API), E0-Journal.1 (hook events), E0-WorldCore.8 (`detach_entry` `source_deleted` rows).
- **Size:** M

### Story E1.4: Proposals API: checklist read, apply with re-check, undo

As a GM,
I want to fetch an entry's checklist and apply my decisions in one step, with stale items caught and merged targets redirected,
So that what I approve is exactly what lands in my world.

**Acceptance Criteria:**

**Given** `GET /api/proposals/?journal_id=`
**When** a GM calls it
**Then** it returns the entry's non-superseded proposals with `group ∈ {new, changed, quest_progress}` (new = `create_entity`, `add_relationship`; changed = `update_field`, `set_status`, `add_alias`, `end_relationship`, `confirm_field`, Mention-only `add_mention`; quest_progress = `quest_progress`), `attention[]`, `match_candidates`, `default_visibility`, state, quote and source field, and the supporting `add_mention` items nested under the item for the same Entity
**And** Players and Share Links get `404 {"detail":"Not found"}`.

**Given** `GET /api/proposals/summary?campaign_id=`
**When** a GM calls it
**Then** it returns one row per entry with `pending + edited > 0` (`journal_id, title, session_date, pending, flags`) oldest first, plus `total_pending`, which the Job tray's pending-reviews count and the Reviews queue use. `flags` is 0 until E2 registers a counter (`proposals_service.register_summary_counter`).

**Given** `POST /api/proposals/apply` with `{journal_id, decisions:[{proposal_id, decision ∈ {approve, reject}, edited_payload?, chosen_visibility?, match: entity_id | "new" | null}]}`
**When** a GM applies
**Then** each `reject` sets `rejected` (kept forever for fingerprint suppression)
**And** for each `approve`, in one transaction, the server re-reads current Canon. The item becomes `stale` (returned with the new current value, nothing applied) when its `old_value` differs, when its batch `entry_hash` isn't the entry's current hash, or when its target was deleted. When the target was merged into a survivor the GM can see, the item is redirected and returned with `redirected_to`
**And** every other approved item applies through `world_service.apply_change` with `proposal_id`, `source_journal_id` and the quote, in dependency order (creates before Relationships that reference them by `target_ref`)
**And** a Relationship whose `target_ref` create was rejected becomes `stale` with reason `target_rejected`
**And** choosing `match: entity_id` on a `create_entity` item applies `add_alias` (the surface form) on that Entity plus its field changes instead of creating (FR-14)
**And** `chosen_visibility` defaults to `default_visibility`. Approving never changes Visibility on its own (UX-DR16 rule 4), and a non-default visibility is applied through `access.set_visibility`
**And** approving an item also confirms its nested `add_mention` items
**And** the response is `{applied:[{proposal_id, change_ids}], stale:[…], redirected:[…], rejected:[…]}`, and `applied_change_ids` is stored on each proposal.

**Given** a decision for a proposal of another entry, a superseded proposal, or one already decided
**When** apply runs
**Then** that item is skipped and reported (`not_pending`), and the rest still apply (partial apply leaves untouched items pending).

**Given** `POST /api/proposals/undo` with `{proposal_ids}`
**When** a GM calls it after an apply
**Then** the server reverts each proposal's `applied_change_ids` newest first through `world_service.revert_change` and sets those proposals back to `pending`. A change that a later edit superseded is reported, not forced. The UI offers Undo for 10 s (UX-DR16 rule 9).

**Given** the standing ACs for new routes
**When** the story merges
**Then** `tests/ev4/probes/proposals.py` asserts that every proposals route is `404` for Players, anonymous Share Links and Player-in-this/GM-elsewhere users, with an identical body for an existing and a nonexistent `journal_id`
**And** each route has a `locations.conf` line in the generic `api` zone and `@limiter.limit` keyed `user_or_ip` on `apply` and `undo`.

- **Covers:** FR-15 (states, approve all, re-check, stale, merged redirect, partial apply, Players never see), FR-14 (alias on choose), FR-16 (provenance on apply), FR-8, AR-10 (approval re-reads), NFR-7.
- **Technical notes:** AD-10, AD-11, AD-13, AD-20. Route `api/routes/proposals.py`, service functions in `extraction_service.py` (`list_checklist`, `apply_decisions`, `undo`, `summary`), schemas in `app/schemas/proposals.py`. "Approve all" is a client-side staging action that sends `approve` for every pending or edited item (E1.5).
- **Dependencies:** E1.3, E0-WorldCore.3 (`apply_change`, `revert_change`), E0-WorldCore.9 (`merged_into_id` semantics), E0-Access.2 (`require_campaign(gm)`), E0-Access.9 (`set_visibility`), E0-QA.11 (EV-4 harness).
- **Size:** L

### Story E1.5: Review Checklist core, with grouped items, staging and Apply

As a GM,
I want one checklist per entry, grouped into New, Changed and Quest progress, where I can approve, reject or edit each item, or approve them all, and then apply,
So that reviewing a session's changes takes minutes, and nothing is applied until I say so.

**Acceptance Criteria:**

**Given** `components/review/ReviewChecklist.tsx`
**When** it opens for an entry
**Then** it is a wide SlideOver titled "Review Checklist · *{entry title}*" with the subtitle "Edit freely — nothing's applied yet.", the same look and copy pattern as `components/NarrativeReviewPanel.tsx` (draft, then decide, then commit)
**And** it shows the groups **New**, **Changed** and **Quest progress**, each headed with a count and collapsible. A **Continuity** section slot renders first when any registered `flag` items exist (filled by E2)
**And** within each group, items with `attention` come first (contradicts canon, stale, possible duplicate, GM-only default on a Party fact), then the rest in entry order.

**Given** `components/review/itemRenderers.ts`
**When** an item renders
**Then** the renderer is looked up by key `proposal:<op>` (and `flag` for E2), and `registerItemRenderer(key, component)`, `registerAttentionProvider(id, fn)` (adds chips and needs-attention sorting to items, used by E2.6) and `registerFollowUp(id, component)` are exported. The follow-up slot renders in the footer area after Apply with the apply result (FR-55's renderer registers here)
**And** this story registers renderers for all nine proposal ops.

**Given** a `ProposalItem`
**When** it renders
**Then** it shows the change (diff: old struck, new bold), its quote in the `quote` style with the source entry, an editable VisibilityBadge with the default, Approve, Reject and Edit, and attention chips "Possible duplicate", "Stale", "From your Shorthand" (and "Contradicts canon" when E2 sets it)
**And** it has four visible states: pending, edited, approved and rejected. Edit opens the fields inline (name, status from the type's vocabulary, field value, relationship type, quest step), and saving the edit sets *edited*.

**Given** a `create_entity` item with `match_candidates`
**When** it renders
**Then** the `MatchPicker` radio list is expanded by default, with up to 3 candidates ("Aldric · Character · 6 Mentions") plus "New entity". Choosing a candidate re-targets the item to "Add alias *Brother Aldric* to Aldric" and marks it edited (FR-14).

**Given** staged decisions
**When** the GM works through the list
**Then** decisions stay local until **Apply to world**. The sticky footer reads "{a} approved · {r} rejected · {p} pending" with **Approve remaining ({n})**, which approves every pending or edited item and leaves rejected ones alone (FR-15 "Approve all"), and **Apply to world**
**And** each group header has "Approve group".

**Given** Apply to world
**When** the response returns
**Then** stale items come back pending with a "Stale: Canon changed since this was proposed" chip and the new current value, redirected items show "Now applies to *Aldric* (merged)", and everything else applies
**And** a Toast reads "Applied {n} changes to the world · Undo", where Undo calls `POST /api/proposals/undo` for 10 s
**And** Entity queries for the touched Entities are invalidated so open pages update without refresh.

**Given** an entry with no proposals
**When** the checklist opens
**Then** it shows "Nothing to change in the world from this entry." and closes itself after 4 s when it was opened from a Toast.

**Given** keyboard and screen-reader users (NFR-10)
**When** they use the checklist
**Then** every action is reachable by Tab with visible focus, each item is a `listitem` labelled "{op} {entity}: {old} to {new}, {state}", decisions are announced through an `aria-live="polite"` region, and focus stays on the item after a decision
**And** at 375 px the SlideOver is full-screen and the footer stays visible.

- **Covers:** FR-15 (grouped, four states, approve all, edit, re-check display), FR-14 (MatchPicker), FR-55 (renderer and follow-up slot), UX-DR16 (rules 1–6, 8, 9), UX-DR17, NFR-10.
- **Technical notes:** AR-24 (`components/review/*`, `hooks/useProposals.ts` keyed `["proposals", campaignId, journalId]`, `services/api/proposals.ts`, `types/proposals.ts`). This extends `NarrativeReviewPanel` by pattern and copy, not by changing its props, since it is still used by `JournalInput.tsx`, `SessionPlansPage.tsx` and `RecordSessionPage.tsx`. Primitives come from E0-UX (SlideOver wide, VisibilityBadge, Toast, SegmentedControl).
- **Dependencies:** E1.4, E0-UX.1 (tokens), E0-UX.3 (SlideOver wide with focus trap), E0-UX.5 (Toast), E0-UX.6 (VisibilityBadge).
- **Size:** L

### Story E1.6: Checklist at scale: filters, keyboard triage and local drafts

As a GM facing 23 proposals after my first post-upgrade entry,
I want filters, keyboard shortcuts and a saved draft of my decisions,
So that a long checklist still takes about three minutes and closing it never loses work.

**Acceptance Criteria:**

**Given** a checklist with any items
**When** it renders
**Then** a filter row offers All · Needs attention ({n}) · Pending ({n}), and a progress line under the title reads "{d} of {t} decided"
**And** a group with more than 8 items shows its first 5 plus "Show {n} more".

**Given** keyboard focus inside the checklist and not in a text input
**When** the GM presses `j`/`k`, `a`, `r`, `e`, `u`, `Shift+A` or `Ctrl/⌘+Enter`
**Then** focus moves to the next or previous item, the focused item is approved, rejected or opened for edit, the last decision is undone, the remaining items in the focused group are approved, or Apply runs
**And** the shortcuts are listed in the `?` overlay (E0-UX shortcut registry) and never fire while typing in an input.

**Given** staged but unapplied decisions
**When** the GM closes the checklist
**Then** the decisions are saved to `localStorage` under `lk:review-draft:{campaignId}:{journalId}:{batch entry_hash}` (wrapped in try/catch) and the footer said "Your decisions are kept on this device until you apply them."
**And** reopening restores them, and a draft whose `entry_hash` no longer matches is discarded with a notice.

**Given** a partial apply
**When** some items are still pending
**Then** they stay pending in the Reviews queue and in the tray count.

- **Covers:** FR-15 (scale), UX-DR16 (rules 7, 11), NFR-10, SM-6 (review burden support).
- **Technical notes:** Shortcut registration goes through E0-UX's registry. No server change.
- **Dependencies:** E1.5, E0-UX.9 (shortcut registry).
- **Size:** M

### Story E1.7: Post-save card, Reviews queue and entry Mentions strip

As a GM,
I want to see my entry saved at once, watch the world-reading progress, and find every pending review in one place,
So that I never wait on the AI and never lose track of a checklist.

**Acceptance Criteria:**

**Given** a GM saves an entry in `JournalInput.tsx`, or edits one on `EntryDetailPage.tsx`
**When** the save returns
**Then** a post-save card under the entry reads "Saved." and lists one row per Job of that entry (`useJobStream`, filtered by `payload.journal_id`), labelled from `components/review/jobLabels.ts` (`extraction.run → "Reading for world changes"`). E2 appends its label line. Each row shows a 4 px bar and a mono ETA ("about 1–3 min on this machine")
**And** when the Jobs finish, the card becomes "{n} changes to review" (plus "· {f} continuity flag(s)" once E2 counts them) with a primary **Review** button that opens the checklist
**And** a failed Job shows its reason in `danger` with Retry (`POST /api/jobs/{id}/retry`), and the entry stays saved
**And** the card never blocks writing the next entry (NFR-9).

**Given** an extraction Job finishes while the GM is elsewhere
**When** its event arrives
**Then** a Toast reads "{n} changes to review from *{title}* · Review" (B2 completion notice with this action), and the tray's pending-reviews slot shows `total_pending` from `GET /api/proposals/summary`.

**Given** `/reviews` (an `App.tsx` route and a `NAV_GROUPS` line)
**When** a GM opens it
**Then** it lists one row per entry with pending items, oldest first ("*The Bell Tower* · 12 Mar · 5 pending · 1 flag" and Open)
**And** an empty queue shows "All caught up. New entries will show here after you save them."
**And** a Player gets the unified not-found page.

**Given** the Dashboard
**When** a GM has pending reviews
**Then** `DashboardPage.tsx` shows an "{n} to review" pill linking to `/reviews`.

**Given** `EntryDetailPage.tsx`
**When** any user opens an entry
**Then** a Mentions strip lists the Entities the entry mentions (`GET /api/entities/mentions?journal_id=`, Party-filtered for Players), and each chip opens that Entity's panel (FR-12, UX-DR22).

**Given** the standing UI ACs
**When** the story merges
**Then** all three surfaces use tokens only, work at 375 px, are keyboard operable, respect reduced motion (static progress, no pulse), and have empty, loading and error states.

- **Covers:** FR-15 (opens from post-save flow and pending-reviews indicator), FR-12 (entry view lists its Entities), UX-DR15, UX-DR18, UX-DR22 (Mentions strip), NFR-9, NFR-10.
- **Technical notes:** `JournalInput.tsx` (post-save hook-in, owned by E1), `components/review/PostSaveCard.tsx`, `pages/ReviewsPage.tsx` (named export behind `lazy`), `components/review/MentionsStrip.tsx`. The edits to `EntryDetailPage.tsx` and `DashboardPage.tsx` are additive insertions (one component each).
- **Dependencies:** E1.5, E0-Jobs.9 (`useJobStream`), E0-Jobs.10 (Job tray `registerTraySection`, completion Toast), E0-WorldCore.7 (entry Mentions route), E0-WorldCore.10 (EntityPanel), E0-Journal.4 (entry edit UI).
- **Size:** M

### Story E1.8: Re-run extraction for one entry or backfill the whole Campaign

As a GM,
I want to re-read one entry, or my whole Campaign, for world changes,
So that entries written before the World Model existed feed it too, without repeating decisions I already made.

**Acceptance Criteria:**

**Given** `POST /api/proposals/rerun` with `{journal_id}`
**When** a GM calls it
**Then** it enqueues `extraction.run` with the entry's current `entry_hash` and returns the Job id in < 1 s. If the same key is already queued or running, it returns that Job's id
**And** the resulting batch inserts only fingerprints new for that entry, so nothing pending is duplicated and nothing decided is re-raised (FR-18).

**Given** `POST /api/proposals/backfill` with `{campaign_id}`
**When** a GM calls it
**Then** it enqueues one `extraction.backfill` cursor Job (`queue = backfill`, `timeout_s = 600`, `resources = {llm}`, `live_safe = false`, `result_audience = gm`, idempotency key `extraction.backfill:{campaign_id}:{cursor}`) that processes one `kind = gm` entry per step in Session order with `llm_class = "job_backfill"`, records "{i} of {n} entries" progress on the same row, and re-enqueues itself with the next cursor (AD-3)
**And** each processed entry gets its own batch, so the Reviews queue shows one checklist per entry, never one 200-item list (UX-DR16 rule 7)
**And** a second backfill request while one is active returns the active Job.

**Given** another Campaign's on-save extraction
**When** a backfill is running
**Then** the on-save Job is delayed by at most one backfill step (FR-1, NFR-11), asserted with `JOBS_EAGER=0` in a queue-order test.

**Given** the overflow registry on the Entity panel and the entry detail menu
**When** a GM opens them
**Then** "Re-run extraction" (entry) and "Re-run extraction for mentions" (Entity: re-runs each entry that mentions it) are registered actions, and Settings › World has "Read all entries for world changes" with a confirm that states the estimated duration.

**Given** the standing ACs for new routes
**When** the story merges
**Then** both routes are GM-only (404 otherwise), have `@limiter.limit` keyed `user_or_ip`, `locations.conf` lines, and probes in `tests/ev4/probes/proposals.py`.

- **Covers:** FR-18, NFR-11, FR-1 (priority bound).
- **Technical notes:** AD-2, AD-3, AD-4. The handler lives in `jobs/extraction.py`. The UI is a registered `panelSections.ts` overflow action plus a menu item on `EntryDetailPage.tsx`.
- **Dependencies:** E1.3, E1.7, E0-Jobs.5 (cursor backfill, queues), E0-WorldCore.10 (overflow action registry).
- **Size:** M

### Story E1.9: Seeded demo Campaign with EV-1 labels

As the owner preparing the capstone demo and evaluation,
I want the demo Campaign's world and a hand-labelled extraction set committed to the repo,
So that EV-1 and DS-1 run the same way on any machine.

**Acceptance Criteria:**

**Given** `seeds/demo_campaign.json` (E0-QA's 9 entries: Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker)
**When** this story appends to it
**Then** it adds at least 6 GM entries with deliberate status changes (Mira alive → deceased), Quest Progress, Relationships, a new Location (Sunken Archive), an alias trap ("Brother Aldric" for Aldric), a Shorthand-only fact, and a Party-looking fact in `gm_notes`, so there are at least 15 entries in total
**And** it adds a `world` block of pre-existing Entities (with aliases and statuses) that `scripts/seed_demo.py` creates through `world_service.apply_change` with a GM ctx (never raw SQL).

**Given** `seeds/labels/extraction.json`
**When** it is read
**Then** it holds at least 60 hand-labelled changes as `{entry_key, op, target_name, entity_type, field, new_value, source_field, expected_visibility, split ∈ {tune, heldout}}`, split by entry roughly in half, and documents the matching rule: same op, same normalized target (or a labelled alias), same field, `new_value` exact for statuses and RapidFuzz ratio ≥ 85 otherwise.

**Given** `scripts/seed_demo.py --with-world`
**When** it runs twice against an empty test database
**Then** it produces the same Campaign, entries and Entities (idempotent by fixed keys), and `pytest tests/seeds/test_demo_seed.py` asserts the counts and that every label's `entry_key` exists.

- **Covers:** EV-1 (labelled set ≥ 15 entries / ≥ 60 changes, tune/held-out split), DS-1 (fixture), AR-21 (evals on the committed seed).
- **Technical notes:** AD-21. The seed format and loader belong to E0-QA. This story appends entries, the `world` block and the labels file, which is the "each eval epic appends its labelled entries" rule in `epics.md`. The extra demo entries are written so E2 can add its contradiction entries after them without renumbering.
- **Dependencies:** E1.4, E0-QA.12 (`seeds/demo_campaign.json`, `scripts/seed_demo.py`), E0-WorldCore.3 (`apply_change`).
- **Size:** M

### Story E1.10: EV-1 extraction eval on the remote GPU desktop, and DS-1

As the owner,
I want extraction quality and speed measured on the labelled set at several operating points,
So that I can show the capstone reviewers that the World Model's proposals are good enough to trust, and choose the production settings from evidence.

**Acceptance Criteria:**

**Given** `scripts/eval_extraction.py --campaign-id <uuid> [--entity-list shortlist|full|none] [--ner on|off] [--split heldout] [--benchmark]`
**When** it runs inside the backend image
**Then** it runs `extraction_service.extract` on every labelled entry and reports, per operating point (entity list {shortlist, full, none} × NER pre-pass {on, off}), the precision, recall and F1 per proposal type and overall, the status-change precision, the duplicate-Entity rate (new-Entity proposals for already-known Entities ÷ new-Entity proposals), the first-pass and first-or-second-pass schema-valid rates, and Visibility-default correctness (no Shorthand-only fact defaulting to Party)
**And** it reports per-entry wall-clock time and the median, and with `--benchmark` writes the NFR-6 extraction row.

**Given** the remote test desktop (CachyOS, RTX 5080 16 GB, native Ollama 0.40.3 serving `lorekeeper`, Postgres+pgvector and Redis over Tailscale)
**When** the eval runs there from the cached backend Docker image, with `OLLAMA` pointing at the native host Ollama and `TEST_DATABASE_URL`/`DATABASE_URL` set by env (the conftest override from E0-QA)
**Then** the GPU results are recorded with the hardware named
**And** the CPU row is measured with the GPU hidden from a second Ollama instance (`CUDA_VISIBLE_DEVICES=""`), or on the x86 Reference Box when available, labelled as such and marked provisional (D-8).

**Given** `docs/EXTRACTION_EVAL.md`
**When** it is written
**Then** it follows the `docs/RETRIEVAL_EVAL.md` format: method, labelled set and split, a results table across the operating points, the chosen operating point with its reason (which also sets `extraction_entity_list`, `extraction_ner_prepass`, `extraction_match_low/high`), a "measured failure → fix" table, the known limits of a small set, and the reproduce command
**And** it states pass or fail against SM-1 (held-out F1 ≥ 0.75, status precision ≥ 0.80), FR-14 (duplicate rate ≤ 10%) and FR-3 (≥ 95% valid on first or second attempt)
**And** it records SM-6 (median review time per entry ≤ 3 min, ≤ 25% of approved items edited) from the owner-graded demo run, with that caveat.

**Given** DS-1
**When** it is run offline (the host's internet disconnected, NFR-1) on the seeded Campaign
**Then** the documented script passes: save the Mira-dies / Sunken-Archive entry, see the post-save card, open the grouped checklist, edit one item, Approve remaining, Apply, and see Mira's page show "Deceased · since *The Bell Tower*" with the quote in History. The Web step is checked when E3 is present.

- **Covers:** EV-1, SM-1, SM-6, FR-3 (measurement), FR-14 (duplicate-rate target), NFR-6 (extraction row), DS-1, NFR-1.
- **Technical notes:** AD-21 (eval format), EV-5 row format from E0-QA. The script imports services the same way `scripts/eval_retrieval.py` does (`sys.path.insert(0, "/app")`), so it lives in `src/backend/scripts/eval_extraction.py`. Bring up the full model stack only for this run (§4.3 "one lane at a time").
- **Dependencies:** E1.8, E1.9, E0-QA.4 (env-overridable test DB URL), E0-QA.15 (eval format, `docs/BENCHMARKS.md`).
- **Size:** M

## Epic E2: Canon guard catches continuity mistakes

When an entry contradicts Canon, the GM is warned with both quotes. She can dismiss the flag with a reason, or override it with a Canon Note (a retcon with a required reason) that later checks and the Chronicler respect. Detection is NLI (`nli-deberta-v3-xsmall`) on pairs that share an Entity, followed by a **mandatory 7B confirmation**. SPIKE-1 found confident false contradictions (p ≥ 0.99) on neutral pairs, so no flag is raised on NLI alone. The check is best-effort and never blocks a save. Phase 2.

**Covers:** FR-19, FR-20, FR-21, FR-22, NFR-6 (continuity row), NFR-7, NFR-9, AR-11 (flags, Canon Notes), EV-2, SM-2, DS-2, UX-DR23, SPIKE-1 decision (xsmall vs base).

### Story E2.1: Continuity Flag and Canon Note tables, and Canon Notes as a retrieval source

As a GM,
I want my retcons stored as Canon Notes that the Chronicler can cite,
So that the record explains why the story changed, and answers respect it.

**Acceptance Criteria:**

**Given** a new Alembic revision rebased onto head
**When** it runs
**Then** it creates `continuity_flags(id, campaign_id, journal_id, proposal_id, entity_id, attribute, canon_ref JSONB SourceRef, claim_quote, canon_quote, nli_score, verdict, state, dismiss_reason, dismiss_note, conflict_key, job_id, created_at, resolved_at, resolved_by, canon_note_id)` with `state ∈ {open, dismissed, overridden}` and `dismiss_reason ∈ {false_alarm, flashback_or_framing, other}`, CHECKs from StrEnums, and FKs to `journal_entries` and `change_proposals` `ON DELETE SET NULL`
**And** it creates `canon_notes(id, campaign_id, reason NOT NULL, body, visibility (default gm), conflict_key, flag_id, created_by, created_at, tsv, embedding vector(EMBEDDING_DIM))`, where `reason` must be non-empty after trim (CHECK)
**And** it creates `canon_note_entities(canon_note_id, campaign_id, entity_id)` with a composite FK to `entities`
**And** `attribute ∈ ContinuityAttribute {status, location, possession, relationship, identity, event, other}` (StrEnum in `domain/enums.py`, appended).

**Given** `access/registry.py`
**When** the models are registered
**Then** `continuity_flags` is `always_gm`, `canon_notes` is `stored`, and `canon_note_entities` is `derived` from its Canon Note.

**Given** `retrieval_service.register_source("canon_note", fn)`
**When** chat or the Chronicler retrieves for a ctx
**Then** `fn` returns Canon Notes the ctx can see (so a Player sees only Party notes), ranked by hybrid `tsv` and embedding against the query, as `SourceRef{kind: canon_note, id}`. `access.resolve_sources` turns them into `ResolvedSource{title: "Canon Note · {reason}", quote: body}`.

**Given** a Canon Note is created
**When** its embedding is computed through `ml.embed`
**Then** an `ml` failure leaves `embedding` NULL with a "must not block" comment, and the note is still found by `tsv`.

**Given** EV-4
**When** it runs
**Then** `tests/ev4/probes/continuity.py` seeds a GM-only Canon Note with a canary and asserts that the canary never appears in a Player's chat sources, retrieval candidates or captured LLM context, and doesn't change a Player's ranking.

**Given** `access.register_resolver` (E0-Access.8) (Reconciliation RC-10)
**When** this story lands
**Then** it registers the `canon_note` resolver (title "Canon Note", quote = the note body), so Canon Note citations resolve for every ctx that can see the note.

- **Covers:** AR-11 (flags, Canon Notes), FR-21 (Chronicler cites Canon Notes subject to Visibility), NFR-5, NFR-7.
- **Technical notes:** AD-11, AD-12, AD-13. Models are in `app/db/models/continuity.py`. `SourceKind.canon_note` already exists in `schemas/sources.py` (B1). The Canon Note retrieval provider lives in `continuity_service.py`. Canon Notes are append-only in v1: there is no delete route, and their visibility changes only through `access.set_visibility`.
- **Dependencies:** E1.1 (`change_proposals` FK), E0-Access.3 (access registry), E0-Access.7 (`register_source`), E0-Access.8 (`resolve_sources`, `register_resolver`, `SourceKind`), E0-Platform.3 (`ml` client `embed`), E0-QA.11 (EV-4 harness).
- **Size:** M

### Story E2.2: Continuity service: shared-Entity pairs, NLI, then a mandatory 7B confirmation

As a GM,
I want my new entry's claims compared with what Canon already says about the same Entities, and only confirmed contradictions raised,
So that I catch a dead NPC walking in without drowning in false alarms.

**Acceptance Criteria:**

**Given** `continuity_service.check(db, ctx, journal_id, *, options) -> ContinuityResult`
**When** it runs on a GM entry
**Then** it splits the Narrative into sentences and keeps as claims only sentences with at least one `world_service.match_names` hit (GM ctx)
**And** for each claimed Entity it builds Canon statements from (a) the Entity's current status and attributes rendered as sentences through `entity_types` ("Mira is deceased."), cited as `SourceRef{kind: entity_field}` with the quote of the change that set them; (b) sentences mentioning the Entity in earlier entries in Session order (`session_date ?? created_at`), from confirmed Mentions first and then `hybrid_search_journal` restricted to entries that mention the Entity, cited as `kind: journal`; and (c) Canon Notes linked to the Entity, cited as `kind: canon_note`
**And** it compares only claim–Canon pairs that share an Entity (FR-19), capped at `continuity_pair_budget` (default 50) by retrieval score.

**Given** the pairs
**When** they are scored
**Then** they are sent to `ml /v1/nli` (`nli-deberta-v3-xsmall`, the `ml` default) in one batched call, and pairs with `contradiction ≥ continuity_nli_threshold` (default 0.90, set by EV-2) are kept, at most `continuity_verify_max` (default 8) by score.

**Given** each kept pair
**When** it is verified
**Then** **every** kept pair goes to the 7B through `async with llm_slot(cls)` then `complete_structured(messages, ContinuityVerdict, config, task="continuity", timeout=…)`, where `ContinuityVerdict` is flat (`verdict ∈ {contradiction, consistent, flashback_or_framing, rumour_or_belief, unclear}`, `attribute ∈ ContinuityAttribute`, `claim_quote`, `canon_quote`, `explanation`) and the instruction to treat flashbacks, rumours, dreams and character beliefs as non-contradictions goes in the final user turn
**And** only `verdict = contradiction` produces a candidate flag. An NLI score alone never produces a flag, whatever its value
**And** when the 7B is unavailable or times out, the check raises (the Job fails visibly) rather than raising unverified flags.

**Given** a candidate flag
**When** its key is computed
**Then** `conflict_key = sha256(entity_id|canon_ref.kind|canon_ref.id|attribute)`, and the flag is dropped when any `continuity_flags` row with that key is `dismissed` or `overridden`, or a `canon_notes` row has that `conflict_key` (FR-21 "the same conflict is not raised again")
**And** both quotes must occur verbatim in their sources (after whitespace normalization), or the flag is dropped (FR-19 "quotes both sides").

**Given** the SPIKE-1 pairs as a unit fixture ("Aldric swore an oath never to take a life" vs "Aldric ordered supper and asked about the weather") with the `ml` fake returning contradiction 0.99 and the fake LLM returning `consistent`
**When** the check runs
**Then** no flag is produced
**And** for "Mira died in the fire" vs "Mira greeted the party at the inn" with the fake LLM returning `contradiction`, one flag cites the earlier entry and quotes both sentences.

**Given** `options.verify ∈ {on, off}` and `options.threshold`
**When** EV-2 runs
**Then** these switches exist for the eval sweep only. Production always uses `verify = on`, and a test asserts that the production config can't turn it off.

- **Covers:** FR-19 (shared-Entity comparison, citations, both quotes), FR-21 (no re-raise), NFR-7, SPIKE-1 decision (xsmall default, mandatory confirmation).
- **Technical notes:** AD-6 (`ml /v1/nli` shape, lazy NLI under `ML_RESIDENT_BUDGET_MB`, 503 then client retry), AD-8, AD-11. Settings `continuity_pair_budget`, `continuity_nli_threshold`, `continuity_verify_max` go in `app/core/config.py`. `schemas/llm/continuity.py` passes CI-9. The service writes nothing.
- **Dependencies:** E2.1, E0-WorldCore.1 (`entity_types`), E0-WorldCore.4 (`match_names`), E0-WorldCore.7 (Mentions), E0-Access.7 (`hybrid_search_journal` with ctx), E0-Platform.4 (`ml` client `nli`), E0-LLM.2 (`llm_slot`), E0-LLM.4 (`complete_structured`), E0-LLM.5 (fake provider).
- **Size:** L

### Story E2.3: `continuity.check` Job, after extraction

As a GM,
I want the continuity check to run by itself after each save or edit, once the world-reading step is done,
So that it sees the proposals from the same entry and never holds up my writing.

**Acceptance Criteria:**

**Given** `app/hooks/continuity.py`, registered in `app/hooks/__init__.py` **after** `hooks/extraction.py`, for `entry_saved` and `entry_updated`
**When** a `kind = gm` entry commits
**Then** it enqueues `continuity.check` with payload `{journal_id, entry_hash}`, idempotency key `continuity.check:{journal_id}:{entry_hash}`, and `depends_on_job_id` set to the active Job with key `extraction.run:{journal_id}:{entry_hash}` when one exists (AD-11 Job ordering)
**And** a dependency that ends `failed` or `cancelled` still lets the check run, without proposal marking. `kind = player` entries are ignored.

**Given** `jobs/registry.py`
**When** `continuity.check` is registered
**Then** it has `queue = onsave`, `timeout_s = 600`, `resources = {nli, llm}`, `live_safe = false` and `result_audience = gm`.

**Given** the handler `jobs/continuity.py`
**When** it runs
**Then** it reports the stage "Checking continuity" with progress and an ETA, calls `continuity_service.check` with `llm_class = "job_onsave"`, deletes the entry's previous `open` flags (dismissed and overridden ones are kept), inserts the new flags, and sets `result_ref = {open_flags: n}`
**And** an entry whose `entry_hash` changed since enqueue ends `cancelled`
**And** `ModelServiceUnavailable` from `ml` and LLM errors follow AD-4 (retry at 10 s then 60 s, then `failed` with a readable reason), and the entry stays saved (NFR-9).

**Given** `components/review/jobLabels.ts`
**When** this story appends `continuity.check → "Checking continuity"`
**Then** the post-save card shows the second stage row without any edit to `PostSaveCard.tsx`.

**Given** EV-5
**When** `scripts/eval_continuity.py --benchmark` (E2.7) runs
**Then** this Job's time on a ≈ 500-word entry is recorded as the NFR-6 "Continuity check complete after save" row (≤ 3 min CPU, ≤ 30 s GPU; hardware labelled).

- **Covers:** FR-19 (queued on save and edit), FR-20 (pending or failed check never blocks saving), NFR-6 (row), NFR-9, AR-11 (Job ordering).
- **Technical notes:** AD-2, AD-3, AD-4, AD-11, AD-17. The ordering is set here rather than in E1's hook, because `continuity.check` doesn't exist when E1 is built (no forward dependency). The behaviour is the same as the §3.3 contract.
- **Dependencies:** E2.2, E1.3 (extraction Job and its idempotency key), E0-Jobs.2 (`enqueue` with `depends_on_job_id`), E0-Jobs.3 (handler), E0-Journal.1 (hook events).
- **Size:** M

### Story E2.4: Show Continuity Flags and dismiss them with a reason

As a GM,
I want each flag beside the entry and in its checklist, with both quotes side by side, and a quick way to dismiss it with a reason,
So that I can judge a warning in seconds and keep a record of why I ignored it.

**Acceptance Criteria:**

**Given** `api/routes/continuity.py`
**When** it is mounted
**Then** it exposes `GET /api/continuity/flags/?journal_id=` (open, dismissed and overridden flags of the entry, with resolved source titles), `GET /api/continuity/status?journal_id=` (`{state ∈ {checking, done, failed, none}, job_id}`), `POST /api/continuity/flags/{id}/dismiss` with `{reason, note?}` and `POST /api/continuity/flags/{id}/undo-dismiss` (accepted within 30 s of the dismissal)
**And** every route is GM-only: Players, Share Links and Player-here/GM-elsewhere users get `404 {"detail":"Not found"}`, with probes in `tests/ev4/probes/continuity.py`, `locations.conf` lines, and `@limiter.limit` keyed `user_or_ip` on the writes.

**Given** `EntryDetailPage.tsx` for a GM
**When** the entry has open flags
**Then** a `ContinuityFlag` card per flag sits above the Narrative: the header "Continuity flag · {Entity}", two quote columns (*This entry* on the left and *Canon ({source title}, {date})* on the right) that stack below `sm`, and the footer "Canon guard is best-effort. No flag doesn't prove the entry is consistent."
**And** while the check runs, a "Checking continuity…" chip sits by the entry title, and a failed check shows "Canon guard couldn't check this entry · Retry" (Job retry)
**And** an entry with no flags carries the best-effort sentence in its footer meta (FR-20).

**Given** the Review Checklist
**When** E2 registers the `flag` renderer in `itemRenderers.ts` and a summary counter with `register_summary_counter`
**Then** the checklist's Continuity section lists the entry's open flags first, the post-save card and Reviews queue show "{f} continuity flag(s)", and none of this edits `ReviewChecklist.tsx`.

**Given** Dismiss
**When** the GM picks False alarm · Flashback or in-fiction framing · Other (with optional text)
**Then** the flag becomes `dismissed` with the reason, collapses to "Dismissed · {reason}" with Undo for 10 s, and its `conflict_key` stops the same conflict from being raised again.

**Given** the standing UI ACs
**When** the story merges
**Then** the card uses `warning`/`danger` semantic tokens (no hardcoded colours), the Dismiss menu is keyboard operable, the quotes use the `quote` style, and new flags are announced politely.

- **Covers:** FR-20 (beside the entry and in the checklist, never blocks, dismiss reasons, best-effort statement), FR-19 (both quotes shown), UX-DR23 (ContinuityFlag), NFR-7, NFR-10.
- **Technical notes:** `components/continuity/ContinuityFlag.tsx`, `services/api/continuity.ts`, `hooks/useContinuity.ts` keyed `["continuity", campaignId, journalId]`. The addition to `EntryDetailPage.tsx` is one component. `register_summary_counter` comes from E1.4.
- **Dependencies:** E2.3, E1.5 (renderer registry), E1.7 (post-save card, summary), E0-UX.1 (tokens), E0-UX.4 (menu primitives), E0-UX.5 (Toast), E0-QA.11 (EV-4 harness).
- **Size:** M

### Story E2.5: Override a flag with a Canon Note (retcon)

As a GM,
I want to record "Mira was resurrected by the Lantern cult" as a Canon Note with a reason when a flagged change is deliberate,
So that the retcon becomes part of the record, the same flag never returns, and the matching world change is offered to me.

**Acceptance Criteria:**

**Given** `POST /api/continuity/flags/{id}/override` with `{reason, body?, also_propose: bool}`
**When** a GM submits an empty or whitespace-only reason
**Then** it returns 422 and nothing is written (FR-21 "reason required").

**Given** a valid override
**When** it commits
**Then** in one transaction a `canon_notes` row is created (`reason`, `body` defaulting to the claim quote, `visibility = gm`, `conflict_key` = the flag's key, `flag_id`), linked to the flag's Entity through `canon_note_entities`
**And** for each linked Entity, `world_service.apply_change(op = canon_note, canon_note_id, new_value = {reason, body})` writes a history row, so the note appears in that Entity's History as "Retcon · {reason}" (FR-21)
**And** the flag becomes `overridden` with `canon_note_id`
**And** when `also_propose` is true and the flag's attribute maps to an Entity change (status → `set_status` with the claim's implied value from the verdict, for example deceased → alive), a `proposal_batches(origin = override, journal_id = flag.journal_id)` with that one proposal is created. It appears in that entry's checklist marked "From Canon Note" and is applied only when the GM approves it.

**Given** the overridden conflict
**When** the GM re-saves the entry after an edit
**Then** `continuity.check` doesn't raise a flag with the same `conflict_key` (DS-2 climax), even before the offered proposal is approved.

**Given** the `CanonNoteForm` inside the ContinuityFlag card
**When** the GM chooses "Override with Canon Note"
**Then** the form shows a required Reason field (Save stays disabled until it has text), an optional body, and "Also propose: {change}" checked by default when a change is available
**And** on save the card resolves into a Canon Note block ("Retcon · {reason}"), and the checklist item appears.

**Given** a Canon Note
**When** the GM sets it to Party with `POST /api/continuity/canon-notes/{id}/visibility` (through `access.set_visibility`)
**Then** Players' Chronicler answers can cite it, and they can't before that (FR-21 "subject to Visibility")
**And** `GET /api/continuity/canon-notes/?campaign_id=&entity_id=` lists notes for a GM, returns only Party notes for Players, and both routes have EV-4 probes and `locations.conf` lines.

- **Covers:** FR-21 (reason required, Canon, offered proposal, no re-raise, Chronicler citation, appears in Entity history), UX-DR23 (CanonNoteForm), NFR-7 (offered change still needs approval).
- **Technical notes:** AD-10 (the history row goes through `apply_change` op `canon_note`), AD-11 (`origin = override`), AD-13. `components/continuity/CanonNoteForm.tsx`. The "From Canon Note" chip comes from `batch.origin` in the E1 renderer, so no E1 file changes.
- **Dependencies:** E2.4, E1.4 (proposal batches and apply), E0-WorldCore.3 (`apply_change` op `canon_note`), E0-WorldCore.11 (HistoryList Canon Note block), E0-Access.9 (`set_visibility`).
- **Size:** M

### Story E2.6: Mark proposals that contradict Canon

As a GM,
I want a proposal that contradicts Canon, such as progress on a Quest already marked failed, flagged in the checklist with the Canon it contradicts,
So that I don't approve a contradiction by accident, and I can record why when I approve one on purpose.

**Acceptance Criteria:**

**Given** the `continuity.check` handler after the extraction Job is done
**When** the entry's latest batch has pending proposals
**Then** it runs deterministic rules from `entity_types` categories: `quest_progress` on a Quest in a `closed_*` category; `set_status` from a `closed_*` status without a Canon Note for that Entity; `add_relationship` involving a `deleted`/`destroyed`/`disbanded` Entity. Each match becomes a flag with `proposal_id` set, `canon_ref` = the `entity_field` change that set the status, and both quotes
**And** an NLI-and-7B-confirmed flag whose claim quote overlaps a proposal's quote for the same Entity also gets that `proposal_id`
**And** these flags obey the same `conflict_key` suppression.

**Given** the checklist
**When** a proposal has an open flag with its `proposal_id`
**Then** the item shows the chip "Contradicts canon" with the cited Canon quote and source, and sorts with the needs-attention items. The flag isn't repeated in the Continuity section.

**Given** a marked proposal
**When** the GM approves it in the staged checklist
**Then** the `CanonNoteForm` opens inline ("Record why this is right?"), where the note is optional for proposals (UX-DR16 rule 12). Saving it calls the override route for that flag (reason still required for a note), and skipping it leaves the flag open and approves the item
**And** on Apply the proposal applies normally (FR-22: the GM can still approve).

- **Covers:** FR-22, UX-DR16 (rule 12), UX-DR17 ("Contradicts canon" chip).
- **Technical notes:** AD-11 (`continuity_flags.proposal_id`). The chip is driven by the flag data the `flag` renderer supplies through the `itemRenderers.ts` registry (`registerAttentionProvider` from E1.5's registry). Rules live in `continuity_service.mark_proposals`.
- **Dependencies:** E2.5; E1.5 (renderer and attention registry).
- **Size:** M

### Story E2.7: EV-2 continuity eval on the remote GPU desktop, and DS-2

As the owner,
I want Canon guard measured on seeded contradictions, clean controls and traps, at several thresholds with and without the 7B confirmation,
So that the reviewers see that the mandatory confirmation removes the false alarms, and I can choose xsmall or base from evidence.

**Acceptance Criteria:**

**Given** `seeds/demo_campaign.json` and `seeds/labels/continuity.json`
**When** this story appends to them
**Then** there are at least 10 seeded contradictions (dead NPC reappears, Location moved, Item held by two Characters, failed Quest progressed, and others), at least 10 clean controls that share an Entity with Canon (including the SPIKE-1 "Aldric oath / ordered supper" neutral pair), 2 flashback or rumour traps and 1 overridden-retcon trap (a Canon Note seeded through the E2.5 service)
**And** each label records `{entry_key, entity, expected: flag|no_flag, expected_canon_source, split ∈ {tune, heldout}}`.

**Given** `scripts/eval_continuity.py --campaign-id <uuid> [--nli-model xsmall|base] [--thresholds 0.8,0.9,0.95] [--verify on|off] [--benchmark]`
**When** it runs
**Then** it reports per operating point the detection rate, false-alarm rate, citation correctness (the cited source is the labelled conflicting source), flashback/rumour-trap holds and retcon-trap holds, plus NLI ms per pair, 7B verifications per entry and wall-clock per entry
**And** it covers both `nli-deberta-v3-xsmall` and `-base` (through the `ml` sidecar's model setting), so the SPIKE-1 decision rule can be applied: keep xsmall unless base shows a clear gain on at least 50 real pairs.

**Given** the remote test desktop (RTX 5080, native Ollama `lorekeeper`, Postgres and Redis over Tailscale, `ml` with the `docker-compose.gpu.yml` override)
**When** the eval runs there from the cached backend image
**Then** the GPU results are recorded with the hardware named, and the CPU timing row is measured as in E1.10 and marked provisional.

**Given** `docs/CONTINUITY_EVAL.md`
**When** it is written
**Then** it follows the `docs/RETRIEVAL_EVAL.md` format and states the chosen threshold, `continuity_pair_budget`, `continuity_verify_max` and NLI model with reasons, the "measured failure → fix" table (starting with SPIKE-1's confident false positive and the verify-on fix), and pass or fail against SM-2 (detection ≥ 8/10, false alarms ≤ 2/10, citation correctness 100% on true flags, retcon trap 1/1, flashback or rumour traps ≥ 1/2)
**And** `--benchmark` writes the NFR-6 continuity row to `docs/BENCHMARKS.md`.

**Given** DS-2
**When** it is run offline (NFR-1) on the seeded Campaign
**Then** the documented script passes: save "Mira greets the party at the gate", see the flag with both quotes, override it with the Canon Note "Resurrected by the Lantern cult" with "Also propose" ticked, approve and apply the offered change, re-save after a small edit, and see that no flag returns. Mira's History shows the death, the Canon Note and the return, each cited.

- **Covers:** EV-2, SM-2, DS-2, NFR-6 (continuity row), SPIKE-1 (x86/GPU decision input), NFR-1.
- **Technical notes:** AD-6, AD-21. The script lives in `src/backend/scripts/eval_continuity.py`. Switching the `ml` NLI model for the base run uses the sidecar's model environment setting (E0-Platform). If base isn't baked into the image, the run documents the extra image build and its licence line (Apache-2.0, already in the register for xsmall's family) and never downloads at runtime.
- **Dependencies:** E2.6, E1.9 (seed and labels format), E0-QA.15 (eval format, `docs/BENCHMARKS.md`), E0-Platform.4 (`ml` NLI model setting), E0-Platform.7 (GPU override).
- **Size:** M

## Epic E3: See the relationship web

GMs and Players explore who is allied with, opposed to or carrying what, through an interactive graph or an equivalent list, with Players seeing only Party content.

**Covers:** FR-23, FR-24, FR-25, NFR-10, UX-DR24, EV-4 probes. **Owns:**

- backend: `api/routes/graph.py` and `api/routes/relationship_types.py`, which also serves `/api/relationships/`;
- frontend: `pages/RelationshipWebPage.tsx`, `components/graph/*`, `hooks/useGraph.ts`, `services/api/graph.ts`, the relationships panel section and the Portal web slot.

It owns no tables: `relationship_types` and `entity_relationships` belong to E0-WorldCore, and all writes go through `apply_change` or `set_visibility`. **Depends on:** E0-WorldCore, E0-Access, E0-UX. Soft: E1 (approved Relationships appear live), E7.1 (Portal slot). **Phase:** 2 (may start at Phase 0 exit, D-10).

### Story E3.1: Relationship types and Relationship create, edit and end API

As Dana,
I want to record typed, directed relationships between Entities from a per-Campaign list of types, and end them without erasing them,
So that "formerly allied with" stays part of the story.

**Acceptance Criteria:**

**Given** `GET /api/relationship-types/?campaign_id=`
**When** a Campaign has no types yet and a GM calls it
**Then** the defaults are created once for that Campaign (idempotently) and returned: ally of, enemy of, rival of, member of, leads, serves, located in, carries, parent of, related to. "enemy of" and "rival of" are flagged hostile, for edge styling.
**And** a Player or anon ctx gets only the types used by at least one Relationship visible to them (the spine rule), and never triggers seeding.

**Given** a GM and `POST`, `PATCH /{id}` or `DELETE /{id}` on `/api/relationship-types/`
**When** Dana adds "sworn to", renames a type or deletes one
**Then** create and rename succeed (names unique per Campaign after `normalize_name`)
**And** deleting a type still used by any Relationship returns `409 {"detail":"In use by 4 relationships"}`, GM-only, so no leak.

**Given** `POST /api/relationships/` with `{campaign_id, source_entity_id, target_entity_id, type_id, note?, visibility, source_journal_id?}` from a GM
**When** both Entities are in that Campaign, distinct and not merged
**Then** the Relationship is written through `world_service.apply_change(op=add_relationship)`, creating an `entity_changes` row (actor, source entry) and queuing `canon_changed`
**And** a cross-Campaign Entity id returns 404, because the composite FK makes it impossible anyway.

**Given** `PATCH /api/relationships/{id}` (type, note, direction swap) and `POST /api/relationships/{id}/end` with `{note?}`
**When** Dana edits or ends one
**Then** each change is a recorded `apply_change` (an end sets `ended_at` through `op=end_relationship`), an ended Relationship stays readable with `status: "ended"`, and the history lists both rows with their sources
**And** Visibility changes use `PUT /api/relationships/{id}/visibility`, which calls `set_visibility`. No other path writes visibility.

**Given** a Player or anon ctx
**When** they call any write route, or `GET /api/relationships/{id}` for a GM-only Relationship or one whose endpoint is GM-only
**Then** they get `404 {"detail":"Not found"}`, identical to a random UUID.

**Given** the standing ACs
**When** the routes ship
**Then** `tests/ev4/probes/relationships.py` covers the canary (a GM-only "secretly serves" edge between two Party Entities, and a Party edge to a GM-only Entity), hidden vs nonexistent, the type-list leak (a type used only by hidden edges is absent for Players), and the downgrade suite
**And** `locations.conf` has `/api/relationship-types/` and `/api/relationships/` lines.

**Covers:** FR-23, FR-8, NFR-5, EV-4.
**Technical notes:**
- AD-10 (`apply_change` is the only writer of `entity_relationships`; history in `entity_changes`) and AD-13 (`project`, uniform 404, `set_visibility`).
- Relationships created by approved proposals arrive through E1's apply and need nothing here.
- The hostile flag assumes `relationship_types` carries a `hostile` boolean (see the closing summary). If F3-world doesn't define one, the default hostile names live in `domain/` as a constant, with no table change.
**Dependencies:** E0-WorldCore.3 (`apply_change`), E0-WorldCore.5 (Entity API), E0-Access.2, E0-Access.4 (`project`, uniform 404), E0-Access.9 (`set_visibility`), E0-QA.11.
**Size:** M

### Story E3.2: Graph endpoint filtered by access

As any Member, or a Share Link visitor,
I want one request that returns the web of Entities and Relationships I'm allowed to see,
So that the graph loads fast and can never reveal hidden nodes.

**Acceptance Criteria:**

**Given** `GET /api/campaigns/{id}/graph` with `require_campaign("player")`
**When** it returns
**Then** the body is `{nodes:[{id,type,kind,status,label}], edges:[{id,source,target,type,status}]}` (the plan §3.4 contract), where `type` on an edge is the relationship type name and `status ∈ {active, ended}`
**And** the GM projection additionally carries `visibility` on nodes and edges (additive and GM-only; the Party projection never has it)
**And** nodes are visible, unmerged Entities of type Character, Location, Faction and Item. Quests are excluded in v1.
**And** an edge is present only when the Relationship itself and both of its endpoints are visible to ctx, so a Party Relationship pointing at a GM-only Entity is omitted entirely.

**Given** the read-only Share Link route `GET /api/portal/shared/{token}/graph` (declared in `graph.py`)
**When** a visitor calls it
**Then** it returns the same shape built with the `anon` ctx from `access.share_ctx(token)` (E0-Access.4), and an invalid or expired token returns 404.

**Given** a Player
**When** the graph is fetched
**Then** node and edge counts, labels and ids include nothing GM-only
**And** the response size and ordering don't depend on hidden rows: they are sorted by id, and there is no pagination cursor that could skip ids.

**Given** a Campaign with 300 nodes and 600 edges
**When** the endpoint is measured warm on the Reference Box
**Then** it responds in ≤ 300 ms p95, and the row is added to `docs/BENCHMARKS.md`.

**Given** the standing ACs
**When** the route ships
**Then** `tests/ev4/probes/graph.py` covers the canary node and edge, counts (Player node count equals the number of visible Entities of the four types), Public vs Members vs Owner(other), GM-in-one/Player-in-another, and the downgrade suite (Party → GM removes the node and its edges on the next read)
**And** any cache key includes the audience and `access_epoch` (AD-13)
**And** `locations.conf` has an anchored-regex line for `/api/campaigns/{id}/graph` and for the shared route.

**Covers:** FR-25 (graph response holds no GM-only nodes or edges), FR-24 (data), FR-40 (web for Share Links), NFR-5, EV-4.
**Technical notes:**
- AD-13: one query per table through `scoped_select`, joined in Python, with no raw SQL on registered tables (CI-8).
- Labels use the Party "unset" rendering if a name field is hidden.
- The function `build_graph(db, ctx)` serves both routes.
**Dependencies:** E3.1, E0-Access.3 (`scoped_select`), E0-Access.4 (`project`, `share_ctx`).
**Size:** M

### Story E3.3: Relationships section in the Entity panel, with Add, Edit and End forms

As Dana,
I want to see and edit an Entity's relationships from its page or panel,
So that I can wire up the world while reading about a character.

**Acceptance Criteria:**

**Given** `components/graph/RelationshipsSection.tsx` registered in `components/entities/panelSections.ts` for every Entity Type (a one-line registration)
**When** an Entity page or panel renders
**Then** the section lists active Relationships grouped by type, outgoing as "→ enemy of → *Grukk*" and incoming as "← member of ← *Iron Fang*", each with "since *{entry}*" when it has a source
**And** ended Relationships appear under a collapsed "Formerly" with their end note
**And** each target name opens that Entity in the same SlideOver through `push` (E0-UX.3), with "← Back to {name}".

**Given** a GM
**When** Dana clicks "Add relationship"
**Then** an inline form opens with: type (a Combobox of the Campaign's types with a trailing "Create type…"), target (an Entity Combobox excluding self), direction (SegmentedControl "This → target · Target → this"), an optional note, and a VisibilityBadge
**And** the badge defaults to the more restrictive of the two endpoints' Visibility, and shows the field hint "Visible to players" when that resolves to Party
**And** saving calls E3.1's API, and the list updates without a reload.

**Given** a GM on an existing Relationship
**When** she chooses Edit or End
**Then** Edit swaps the row for the same form, prefilled
**And** End confirms inline ("End *enemy of → Grukk*? It stays in history.") with an optional note, then moves the row to "Formerly"
**And** each row's VisibilityBadge changes Visibility through E3.1's visibility route (moving to Party confirms inline).

**Given** a Player or a preview session
**When** the section renders
**Then** it shows only Party Relationships, with no edit controls, and the section is absent when there are none (no "No relationships" hint and no gap)
**And** a GM with none sees the hint "No relationships yet".

**Given** the Web toolbar overflow (GM only)
**When** Dana opens "Relationship types"
**Then** a SlideOver lists the types with rename, mark hostile and delete (delete shows the "In use by N" message from E3.1).

**Covers:** FR-23 (UI), FR-25 (Player view without gaps), UX-DR24 (Add and End relationship forms), NFR-10.
**Technical notes:**
- B3 contract: register sections only and never edit `EntityDetailPanel.tsx`.
- `hooks/useRelationships.ts` uses the key `["relationships", campaignId, entityId]`.
- On `useCampaignEvents` invalidations with `{domain: "relationships" | "entities"}` (E0-Access.11), the hook invalidates its key.
**Dependencies:** E3.1, E0-WorldCore.10 (`panelSections.ts`), E0-UX.3, E0-UX.4, E0-UX.6.
**Size:** M

### Story E3.4: Graph canvas with a settled, persisted layout and live updates

As a Member,
I want the web to appear already arranged, styled by type and status, and to stay where I left it,
So that I can read the world at a glance without a jiggling simulation.

**Acceptance Criteria:**

**Given** the new dependencies `sigma`, `graphology`, `@react-sigma/core` and `graphology-layout-forceatlas2` (versions pinned per the spine Stack table), plus `@sigma/node-image` if it is used for shapes
**When** they are added to `package.json`
**Then** each has a line in `licenses/register.yaml` (MIT) in the same story, and the frontend licence scan passes.

**Given** `/world/web`, registered as the World hub's "Web" tab (E0-WorldCore.10 owns the hub and its `registerWorldTab` registry, RC-14), which renders `pages/RelationshipWebPage.tsx`
**When** it opens
**Then** a skeleton "Arranging 214 entities…" holds the space while ForceAtlas2 runs in a Web Worker (capped at 2 s or convergence), and only then is the settled graph shown, with no on-screen simulation
**And** positions persist per Campaign, per device and per audience in `localStorage` under `lk-web-layout:{campaignId}:{role}`, so a later visit renders instantly with no reshuffle
**And** the layout is computed only from the nodes the viewer received, so a Player's layout carries no trace of hidden nodes.

**Given** node and edge styling from DESIGN.md
**When** the graph renders in any of the six themes
**Then** the node shape follows the type (Character circle, Location rounded square, Faction hexagon, Item diamond), with a lucide glyph inside
**And** a PC has a `primary` stroke, a GM-only node (GM view) a dashed `gm` stroke, and a deceased or destroyed node 50% opacity with a Skull or Ban glyph
**And** edges are `muted-foreground` at 60% with arrowheads, hostile types use `danger` at 70%, and ended edges are dashed (or, if dashing isn't feasible in a sigma program, lighter with a "formerly" label, never colour alone)
**And** labels show at zoom ≥ 1 or on hover or focus, and colours are read from the theme's CSS variables, re-rendering on a theme change.

**Given** pointer interaction
**When** a Member drags the background, uses the wheel or pinches, or drags a node
**Then** the view pans or zooms, and a dragged node moves and is pinned (saved to the layout)
**And** hovering or focusing a node highlights it and its neighbours, dims the rest, shows edge labels, and (at `md` and up) shows E0-WorldCore's `EntityCard` as a popover
**And** clicking or Enter opens the Entity in the standard SlideOver while the graph stays mounted behind it
**And** a long-press on touch opens the node's actions menu.

**Given** a Relationship or Entity approved from a checklist (E1) or added in a panel (E3.3)
**When** `useCampaignEvents` delivers `{domain: "relationships" | "entities"}`
**Then** `["graph", campaignId]` refetches, new nodes are placed at their neighbours' centroid (plus a small offset) without moving existing nodes, and removed nodes disappear, all without a manual refresh.

**Given** the Portal web slot
**When** this story lands
**Then** `components/portal/portalSections.ts` gains a "web" section (a compact "Explore the web" card linking to `/world/web`) for Members and Share Link visitors (via the shared graph route).

**Covers:** FR-24 (pan, zoom, open panels, node style by type and status, live updates), FR-25 (layout reveals nothing), FR-40 (web on the Portal), UX-DR24 (GraphCanvas, settled persisted layout, neighbour highlight), NFR-4 (licence register), NFR-10.
**Technical notes:**
- Spine Graph convention: `sigma` + `graphology` + `@react-sigma/core` + `graphology-layout-forceatlas2` (in a worker) in `components/graph/`.
- The reduced-motion camera behaviour is in E3.6.
- WebGL detection runs here: without WebGL, the page renders the list view's placeholder message, which E3.5 completes.
**Dependencies:** E3.2, E3.3, E0-WorldCore.10 (World hub, `registerWorldTab`), E0-Access.11, E7.1 (Portal slot registry, RC-17), E0-QA.7 (licence register).
**Size:** L

### Story E3.5: Toolbar, search, filters, legend and the list view

As a Member,
I want to search, filter and switch to an equivalent list,
So that I can find Grukk's enemies in a 200-node web on any device, with or without WebGL.

**Acceptance Criteria:**

**Given** `components/graph/GraphToolbar.tsx`, floating top-left
**When** it renders
**Then** it has a search input (`/` focuses it), filter chips for Entity Type, a Relationship type multi-select Combobox, a Faction Combobox, a "List view" toggle, zoom +/−, and "Fit"
**And** filter state lives in the URL (`/world/web?type=character&rel=enemy-of&faction=…`), so it survives reloads and can be shared.

**Given** a search for "Grukk" (diacritic- and case-insensitive over labels, and over visible aliases through the Entity API search)
**When** a match is selected
**Then** the camera centres on that node and focuses it.

**Given** active filters
**When** they hide nodes
**Then** the toolbar reads "Showing 48 of 214 · Clear filters", where 214 is the count of nodes the viewer received (visible nodes only)
**And** the Faction filter keeps the chosen Faction and every node with an edge to it.

**Given** `components/graph/NodeLegend.tsx`
**When** the Web opens for the first time on a device
**Then** the legend is expanded, and on later visits it is collapsed (remembered)
**And** it shows shape → type, and line style → meaning (arrow = direction, dashed = ended, gm dashed ring = GM only, GM view only), and never covers the focused node.

**Given** `components/graph/GraphListView.tsx`, a peer view and not a fallback
**When** it is toggled (`L`, or the button, remembered per device), or by default below 640 px, above 1,000 nodes, or without WebGL
**Then** it is a sortable table (Entity · Type · Status · Relationships) of the same filtered set, and each row expands to its edges ("→ enemy of → *Aldric* (since *Karak Dun*)")
**And** row and edge targets open the Entity in the SlideOver
**And** in the over-1,000-nodes and no-WebGL cases it says "Showing list view: the web is too large for this device." or "…this device can't draw the web."
**And** it is a native `table` with sortable `th` buttons (`aria-sort`), works fully by keyboard, and works at 375 px.

**Given** a Player
**When** they use search, filters or the list
**Then** results and counts cover Party data only, with no "+2 hidden" and no count mismatch.

**Given** an empty graph
**When** the Web opens
**Then** EmptyState reads "Relationships appear as you approve them, or add one from any entity."

**Covers:** FR-24 (search, filters by Entity Type, Relationship type and Faction, list view), FR-25 (search and counts reveal nothing), UX-DR24 (GraphToolbar, GraphListView, NodeLegend), NFR-10.
**Technical notes:**
- Filtering is client-side over the received graph, so nothing hidden can be counted.
- `useShortcut('/', …)` and `useShortcut('L', …)` are scoped to the Web (E0-UX.9).
**Dependencies:** E3.4, E0-UX.4, E0-UX.9.
**Size:** M

### Story E3.6: Keyboard navigation, announcements, reduced motion and the 300-node performance check

As a keyboard or screen-reader user, and as the Owner verifying FR-24,
I want to move through the web by keyboard with spoken context, and proof that it stays smooth at 300 nodes,
So that the graph is one tool with the list, not a picture only mouse users can use.

**Acceptance Criteria:**

**Given** the canvas region
**When** it renders
**Then** it is a focusable `role="application"` with the label "Relationship web. Arrow keys move between connected entities. Enter opens. L for list view."
**And** the first focusable element in the region is a link to the list view.

**Given** a focused node
**When** I press an arrow key
**Then** focus moves to the neighbour nearest in that direction (by angle, then distance), or to the nearest node in that direction if there are no neighbours
**And** `Tab` and `Shift+Tab` cycle the focused node's edges and neighbours, and Tab past the last one leaves the region (no keyboard trap)
**And** Enter opens the panel, `+`, `-` and `0` zoom and fit, and the focused node shows the 3px `ring` focus ring
**And** a polite live region announces "Iron Fang, Faction, active, 9 relationships" (and the edge "enemy of, Grukk" when an edge is focused).

**Given** `prefers-reduced-motion: reduce` (via `useReducedMotion()`, E0-UX.3)
**When** the camera centres, fits or zooms to a node
**Then** it jumps with no animation, and the layout never animates.

**Given** a dev-only route `/dev/graph-bench?nodes=300&edges=600`, compiled only when `import.meta.env.DEV`
**When** it runs a scripted 10 s pan-and-zoom loop over a synthetic graph styled like production, measuring frame times with `requestAnimationFrame`
**Then** on the reference laptop named in `docs/BENCHMARKS.md`, in current Chrome, p50 ≥ 30 fps and the 5th percentile ≥ 24 fps
**And** the measured numbers, the browser version and the machine are recorded in `docs/BENCHMARKS.md`
**And** a miss blocks the story.

**Given** the whole E3 surface
**When** a keyboard-only pass is done (Flow 9 in EXPERIENCE.md: `/` "Grukk" → arrows → filter "enemy of" → `L` → expand → open Aldric)
**Then** every step works without a pointer, the result is recorded in the PR, and EV-4 for `graph.py` and `relationships.py` is green.

**Covers:** FR-24 (300 nodes / 600 edges at ≥ 30 fps; keyboard-accessible), UX-DR24 (keyboard navigation and announcements), UX-DR5 (graph reduced motion), NFR-10, EV-5 (graph row).
**Technical notes:**
- Node focus state lives in graphology node attributes, and the sigma reducers apply highlight and dim.
- The bench route is excluded from production builds and isn't registered in `lib/routes.ts`.
**Dependencies:** E3.5, E0-UX.3, E0-QA.15.
**Size:** M

## Epic E4: Live Session at the table

During play the GM gets chunked captions, a Rolling Recap and two-second Entity lookup on a tablet, and turns the session into a draft entry at the end. Phase 2 (can move earlier). Governed by AD-15, AD-3 (Live admission), AD-8 (`live_recap` gate class), AD-14 (audio files) and AD-6/AD-7 (`stt` faster-whisper **base**: `small` fails live use, worst chunk RTF 1.03, `spikes/cpu-benchmarks.md` §3.1).

**Covers:** FR-26, FR-27, FR-28, FR-29, FR-30, NFR-6 (caption, recap, lookup rows), NFR-2 (Live case), NFR-5 (audio deletion), NFR-7, NFR-10, AR-15, AR-3 (Live admission use), SPIKE-4, EV-6 (Rolling), SM-7, DS-4 (first half), UX-DR26.

### Story E4.1: Start a Live Session and stream audio chunks to the server

As a GM,
I want to start, pause, resume and end a Live Session, with my browser streaming audio chunks that the server stores and acknowledges,
So that table audio reliably reaches the server and background Jobs stand aside while I play.

**Acceptance Criteria:**

**Given** a new Alembic revision (from `alembic revision`, rebased onto head)
**When** it is applied
**Then** it creates `live_sessions` (`id`, `campaign_id`, `started_by`, `state ∈ {recording, paused, ended}`, `chunk_seconds` 10–30 with default 15, `keep_audio` bool default false, `diarize_requested` bool default false, `started_at`, `ended_at`, `session_date`, recap columns `recap_points` JSONB default `[]`, `recap_now` text, `recap_through_seq` int, `recap_updated_at`, plus `draft_shorthand` text and `journal_id` nullable FK) and `live_chunks` (`id`, `live_session_id`, `seq`, `start_ms`, `duration_ms`, `received_at`, `file_id` nullable, `status ∈ {received, transcribed, skipped, failed}`, `UNIQUE(live_session_id, seq)`)
**And** CHECKs come from StrEnums in `domain/enums.py` (append), there is a partial unique index allowing one non-ended session per Campaign, and both tables are registered `always_gm` in `access/registry.py`.

**Given** a GM ctx (`require_campaign("gm")`)
**When** they call `POST /api/live/` with `{campaign_id, session_date?, chunk_seconds?, keep_audio?, diarize_requested?}`
**Then** a `recording` session is created, `admission.hold("live", ttl=90)` is taken, and `201` returns the session
**And** a second start in the same Campaign returns `409`, and `POST /api/live/{id}/pause`, `/resume` and `/end` move the state (end releases the lease; pause stops renewal so the lease lapses within 90 s, AD-3).
**And** `diarize_requested=true` is accepted only when the diarization option is available (E4.10). Until then it is ignored and reported as `false`.

**Given** a WebSocket to `wss://…/api/live/{id}/ws`
**When** the first message is not `{"type":"auth","token":...}` within 5 s, or the token is not a GM of that session's Campaign, or the session doesn't exist
**Then** the socket closes with the same code `4404` in every case (uniform not-found, AD-13), and the token is never accepted from the URL.

**Given** an authenticated socket and a `recording` session
**When** the client sends a binary frame with a 12-byte little-endian header (`uint32 seq`, `uint64 start_ms`) followed by PCM16 16 kHz mono bytes of at most `chunk_seconds`
**Then** the server stores the bytes through `file_service.put` (kind `live_audio`, GM audience), inserts the `live_chunks` row, pushes its id onto the Redis list `live:{id}:pending`, renews the `live` lease and replies `{"type":"ack","seq"}`
**And** a resent `seq` is acknowledged again with no new row or file, an oversized or malformed frame gets a `notice` and is dropped, and frames for a `paused` or `ended` session get a `notice` and are not stored.

**Given** a grant change for the connected user (`access:{campaign_id}:{grant_id}`, or the 15 s poll)
**When** it arrives
**Then** the socket closes with `4404`.

**Given** the proxy
**When** `nginx/locations.conf` is read
**Then** it has one `location /api/live/` block with `Upgrade`/`Connection` headers and `proxy_read_timeout 4h`, and the REST lifecycle routes carry `@limiter.limit` keyed `user_or_ip`
**And** `tests/ev4/probes/live.py` shows that a Player, an anonymous user and a GM of another Campaign get identical `404`s and `4404` closes for an existing session and a nonexistent one.

- **Covers:** FR-26 (start, pause, end), AR-15 (connection, session state, frames, ack, nginx), AR-3 (Live admission hold and renew), NFR-5.
- **Technical notes:** AD-15, AD-3, AD-14, AD-20. New files: `app/api/routes/live.py`, `app/api/ws/live.py`, `app/services/live_session_service.py`, `app/schemas/live.py` (frame header, messages). Router include in `main.py` (append). `keep_audio` and `diarize_requested` are fixed at start, per AD-15 (see Decisions). The socket subscribes to `live:{id}:out` (B2 pub/sub) but has nothing to relay until E4.2.
- **Dependencies:** E0-Access.2 (`CampaignContext`, `require_campaign`), E0-Access.3 (access registry), E0-Access.10 (grant-change publish), E0-Jobs.5 (`admission.hold/renew/release`), E0-Jobs.8 (`file_service`), E0-Jobs.6 (`core/pubsub.py`, `live:{id}:out`), E0-Platform.8 (`user_or_ip`), E0-QA.11 (EV-4 harness).
- **Size:** L

### Story E4.2: One drainer transcribes chunks into captions and reports backlog

As a GM,
I want each audio chunk transcribed by the local speech model as soon as possible, in order, with names from my world spelled right and the lag reported,
So that captions keep pace with the table and I can see when they fall behind.

**Acceptance Criteria:**

**Given** a new revision creating `live_segments` (`id`, `live_session_id`, `chunk_id`, `seq`, `start_ms`, `end_ms` (session-relative), `text`, `created_at`), registered `always_gm`
**When** it is applied
**Then** `access.resolve_sources` can resolve `SourceKind.live_segment` refs to `ResolvedSource {title: "Live Session {date} · {m:ss}", quote: text}` through a resolver registered in `access/registry.py` (append).

**Given** an open socket for session `{id}`
**When** the handling process acquires the Redis lock `live:{id}:drainer` (SET NX, TTL 15 s, renewed every 5 s)
**Then** it drains `live:{id}:pending` in `seq` order inside a connection-scoped `asyncio.TaskGroup`, so it is cancelled with the socket and is not fire-and-forget background work (AD-2)
**And** at most one drainer exists per session across gunicorn workers. A test with two sockets on two processes asserts that each chunk is transcribed exactly once. If the holder's socket closes, another socket's process takes over within 15 s.

**Given** a pending chunk
**When** the drainer processes it
**Then** it calls `clients/stt.transcribe(pcm, format="pcm16", initial_prompt=...)`. The prompt is built from the Campaign's Entity names and aliases visible to the GM ctx plus glossary terms, ordered by recent Mention count and capped at about 200 tokens (Whisper's prompt window).
**And** it stores `live_segments`, sets the chunk to `transcribed`, renews the `live` lease and publishes `caption {seq, text, start_ms, end_ms, lag_ms}` on `live:{id}:out`, which every socket process relays. Here `lag_ms` is the publish time minus the chunk's `received_at` (NFR-6's "chunk end → text shown").

**Given** that the session has neither `keep_audio` nor `diarize_requested`
**When** a chunk is transcribed
**Then** its audio file is deleted through `file_service.delete` in the same step (FR-29, NFR-5), and a test asserts that no `live_audio` file survives a transcribed chunk.

**Given** unprocessed chunks
**When** their total duration is above zero and changes
**Then** `backlog {seconds}` is published
**And** when the backlog exceeds 600 s, the oldest pending chunks are marked `skipped` and their audio is deleted, and `notice {kind:"skipped", from_ms, to_ms}` is published once per range (FR-26's 10-minute cap).

**Given** the `stt` sidecar fails (`ModelServiceUnavailable`)
**When** a chunk fails
**Then** it is retried twice (2 s, then 10 s). It is then marked `failed` with `notice {kind:"stt_failed", from_ms, to_ms}`, and later chunks continue.

**Given** a recorded 20-minute table clip replayed through the socket at real time on the remote desktop
**When** it runs against the `stt` sidecar (faster-whisper base, int8) on CPU and again with the GPU override
**Then** mean processing per 15 s chunk is ≤ chunk duration (FR-26) and lag p95 is ≤ 30 s on CPU and ≤ 5 s on GPU (NFR-6), recorded in `docs/BENCHMARKS.md` as "caption lag" rows with the compute type.

**Given** `access.register_resolver` (E0-Access.8) (Reconciliation RC-10)
**When** this story registers the `live_segment` resolver
**Then** it is a one-line append, and `access` checks the segment's `always_gm` Audience before the resolver runs.

- **Covers:** FR-26 (captions, lag, backlog, skip), FR-29 (audio deletion after transcription), AR-15 (drainer, `initial_prompt`, server messages, backlog cap), NFR-6 (caption row), NFR-3, NFR-5.
- **Technical notes:** AD-15 (The drainer; Backlog; Audio deletion), AD-6 (`stt` contract), AD-7 (`stt` 1.25g, base). The name list reads Entities and aliases via `scoped_select` (no raw `select`, CI-8). Uses `clients/stt.py` as is: no model choice from E4. If the `stt` `/v1/status` reports a model other than `base`, the Live pre-check (E4.3) warns that live captions may fall behind. GPU numbers come from the `docker-compose.gpu.yml` `stt` override. Its CUDA runtime libraries are a licence-register item owned by E0-Platform/E0-QA, not this story.
- **Dependencies:** E4.1, E0-Platform.5 (`stt` sidecar, `clients/stt.py` and its fake in `app/clients/fakes.py`), E0-WorldCore.2 (Entities, aliases), E0-Access.3 (`scoped_select`), E0-Access.8 (`resolve_sources`).
- **Size:** L

### Story E4.3: Live Session page with honest captions and a lag meter

As a GM with a tablet on the table,
I want a Live Session page that checks the speech model, HTTPS and microphone, then shows captions chunk by chunk with a lag meter and backlog notices,
So that I can trust what the screen tells me while I run the game.

**Acceptance Criteria:**

**Given** `/live` (Chronicle › Live Session in `NAV_GROUPS`; `/record` redirects there, and `/live?mode=record` renders today's `RecordSessionPage`)
**When** it opens
**Then** pre-checks run in order: speech model available (`stt` status via the existing admin/model status API), HTTPS (`window.isSecureContext`), microphone permission. Each failure has its own EXPERIENCE.md state ("Live Session needs a secure (HTTPS) connection…", "Lorekeeper can't hear the table…", or a ModelMissingNotice), and each offers the "Record only" link.

**Given** the pre-checks pass
**When** the GM presses **Start Live Session** (Campaign, optional Session date, chunk length 10–30 s defaulting to 15, plus "Keep raw audio" off by default)
**Then** `POST /api/live/` is called, the AudioWorklet in `lib/audio/pcmCaptureWorklet.ts` captures mono audio, downsamples to 16 kHz PCM16 and emits a frame every `chunk_seconds`, and `lib/liveSocket.ts` sends it with the `{seq, start_ms}` header after the auth message
**And** a screen wake lock is requested (re-acquired on `visibilitychange`). Where unsupported, the page says "Keep this screen on — your browser may sleep it."

**Given** recording
**When** the LiveStatusBar is shown
**Then** it is pinned in the top 56 px with the REC dot and the word "REC", mono elapsed time, the **LagMeter** ("Captions ≈ 18 s behind", plus a three-segment glyph Listening · Transcribing · Shown that turns `warning` when lag exceeds the chunk window), Pause and End
**And** **Space** (with nothing focused) pauses and resumes. Paused shows "Paused" and keeps everything.

**Given** chunks in flight
**When** captions arrive
**Then** the newest chunk shows as a CaptionPending row ("Transcribing 0:42–1:02…"), which caption text replaces in place without moving earlier rows. Before the first caption the page shows "Listening. First captions in about 20–30 s."
**And** auto-scroll happens only while the GM is at the bottom. Otherwise a "Jump to live" button appears.

**Given** `backlog` and `notice{kind:"skipped"}` messages
**When** they arrive
**Then** the BacklogBanner reads "Falling behind — 3 min of audio queued. Nothing is lost up to 10 min.", and skipped ranges render in-line ("Skipped 41:10–41:40 (backlog over 10 min)")
**And** the caption list is an `aria-live="polite"` log announcing only new chunks. Backlog and skip notices are announced `assertive` once, and the LagMeter is readable on focus but not live.

**Given** the UI floor
**When** it is checked
**Then** it uses `live`, `warning` and `danger` semantic tokens only, `{typography.caption-live}` for captions and `{spacing.tap-target-table}` targets. At 375 px it uses bottom tabs (Captions now; the Lookup and Recap tabs are added by E4.6 and E4.5). At ≥ 1024 px it has two columns (captions `1fr`, a 360 px rail). Under reduced motion the REC dot is static and captions jump-scroll. It is keyboard operable with visible focus.

- **Covers:** FR-26 (UI: start, pause, lag shown, backlog), UX-DR26 (pre-checks, Start, LiveStatusBar, LagMeter, CaptionChunk, CaptionPending, jump-to-live, BacklogBanner, wake lock, aria-live, phone tabs), NFR-10, NFR-1 (HTTPS through the existing front end).
- **Technical notes:** EXPERIENCE.md "Live Session behaviour", "Responsive", "Accessibility Floor". DESIGN.md `live-status-bar` and LagMeter specs. New: `pages/LiveSessionPage.tsx` (named export, `lazy`), `lib/liveSocket.ts`, `lib/audio/pcmCaptureWorklet.ts`, `components/live/*`, `services/api/live.ts`, `types/live.ts`, `hooks/useLiveSession.ts`. The page uses `getUserMedia({audio:{echoCancellation:false, noiseSuppression:true, autoGainControl:true}})`. The existing `RecordSessionPage.tsx` stays for `?mode=record`. Uses E0-UX primitives (`EmptyState`, `ModelMissingNotice`, `Toast`).
- **Dependencies:** E4.2, E0-UX.5 (EmptyState, ModelMissingNotice, Toast), E0-UX.8 (`NAV_GROUPS`, redirects), E0-UX.9 (shortcut registry).
- **Size:** L

### Story E4.4: Reconnect or refresh resumes the same Live Session with nothing lost

As a GM on flaky venue Wi-Fi,
I want a dropped connection or a page refresh to pick up the same Live Session with every caption intact and unsent audio delivered,
So that a network blip never costs me the session.

**Acceptance Criteria:**

**Given** the socket drops while recording
**When** the client is still capturing
**Then** it keeps capturing and buffers unacknowledged chunks in memory and in IndexedDB (best-effort, capped at 10 minutes, the same as the server backlog cap), and reconnects with exponential backoff (1 s up to 15 s)
**And** a close code `4404` (access lost or session gone) stops reconnecting and shows the not-found state, not a retry loop.

**Given** a reconnect or a page refresh on `/live` with an active session for the current Campaign
**When** the new socket authenticates
**Then** the server sends `notice {kind:"resume", received:[[from_seq,to_seq],…]}`, replays every stored segment as `caption` messages in order, and sends the latest `recap` if one exists
**And** the client resends only the chunks missing from `received`, which the server acks idempotently.

**Given** the resume completes
**When** the caption list is rebuilt
**Then** it matches the server's segments exactly (a test compares text before and after a forced disconnect mid-chunk), and a toast says "Reconnected — nothing lost"
**And** if buffered audio was lost (for example IndexedDB was unavailable across a refresh), the gap renders in-line as "Not received 12:00–12:15", never silently.

**Given** a GM opens `/live` while a session in the Campaign is `paused`
**When** the page loads
**Then** it offers Resume and End for that session, not a new Start.

- **Covers:** FR-26 (reconnect and refresh resume with no loss of transcribed text), AR-15 (Reconnect), UX-DR26 (reconnect toast).
- **Technical notes:** AD-15 (Reconnect). `notice` is extended with `kind:"resume"`. The protocol is internal to E4 (parallel plan §3.5). Server work is in `app/api/ws/live.py` and `live_session_service.replay(...)`. Client work is in `lib/liveSocket.ts` (buffer and resend) and `hooks/useLiveSession.ts`. The client keeps capturing while disconnected (see Decisions).
- **Dependencies:** E4.3.
- **Size:** M

### Story E4.5: Rolling Recap of the session so far

As a GM,
I want a recap of the session that refreshes about every minute from new transcript text, keeps earlier points and cites the transcript,
So that I (and the table) can remember what happened an hour ago without scrolling.

**Acceptance Criteria:**

**Given** `jobs/registry.py`
**When** the `live.recap` kind is registered
**Then** it has `queue=interactive`, `live_safe=True`, `resources={llm}`, `timeout_s=120`, `result_audience=gm` and idempotency key `live.recap:{id}`, and calls the LLM under `llm_slot("live_recap")`.

**Given** a recording session with segments after `recap_through_seq`
**When** the drainer stores a segment and `recap_updated_at` is at least 60 s old (or null)
**Then** it calls `enqueue(db, ctx, "live.recap", {"live_session_id": id}, idempotency_key=f"live.recap:{id}")`, so at most one recap Job is queued or running per session
**And** while the `live` lease is held, the worker still runs it (it is `live_safe`) and skips `{llm, nli, tts, cpu_heavy}` kinds that aren't (AD-3).

**Given** the handler
**When** it runs
**Then** it reads the `live_sessions` row `FOR UPDATE`, takes the segments after `recap_through_seq`, and calls `complete_structured(..., schema=RollingRecapUpdate, task="live_recap")`, where `RollingRecapUpdate` in `schemas/llm/live.py` is flat: `new_points: list[str]`, `now: str`
**And** it appends each new point to `recap_points` with its `from_seq`/`to_seq`, replaces `recap_now`, advances `recap_through_seq`, writes `derived_sources(derived_type="live_recap", derived_id=id, ref_kind=live_segment, …)`, and publishes `recap {text, through_seq}`.

**Given** earlier points
**When** the recap grows
**Then** existing points are never sent back to the LLM for rewriting. Only when `prompt_budget.fit("live_recap", …)` reports that the points no longer fit as context does a compaction step merge the oldest points per 15-minute window, keeping every proper noun (a check re-runs compaction once if a name is lost).
**And** on a recorded 2-hour clip, a fact stated only in minute 5 is still in the final recap (FR-27, test fixture plus the EV-6 run in E4.9).

**Given** the LLM is busy past the Job timeout, unavailable, or the output is unusable
**When** the Job fails
**Then** captions continue, the card shows "Recap paused: the AI model is busy or unavailable. Captions continue.", and the next 60 s tick tries again.

**Given** the RollingRecapCard in the right rail (the Recap tab on phones)
**When** it renders
**Then** it is always labelled "From the transcript, not your journal", shows "Updated 40 s ago · covers to 1:02:10" (mono) and an "Updating…" chip during a refresh, and keeps the old text readable until replaced. Changed text gets a left rule (no animation under reduced motion). Each point's disclosure lists its cited segments (`ResolvedSource[]`, `grounded=true`).
**And** its empty state reads "The first recap arrives about a minute after captions start."

**Given** the remote desktop runs
**When** a 30-minute clip runs on CPU (compose `ollama` without GPU) and on GPU
**Then** cadence and per-update wall time are recorded in `docs/BENCHMARKS.md` (target ≤ 45 s per update on CPU, NFR-6), together with the NFR-2 Live case: peak RSS of `stt`, `ollama`, `web` and `worker` stays within their AD-7 limits during STT plus Rolling Recap.

- **Covers:** FR-27, AR-15 (Rolling Recap), AR-3 (`live_safe` under the lease), NFR-6 (recap row), NFR-2 (Live case), NFR-7, UX-DR26 (RollingRecapCard).
- **Technical notes:** AD-15 (Rolling Recap), AD-3, AD-8 (gate class `live_recap`, `complete_structured`, `prompt_budget`), AD-14 (`derived_sources`; `live_recap` is added to `DERIVED_REGISTRY` as derived from `live_segment`, GM-only). The Job handler lives in `app/jobs/live.py`. The current recap is stored on the `live_sessions` row (see Decisions). Hosted metering goes through `llm_config_service.meter` when the GM's config is the hosted default.
- **Dependencies:** E4.4, E0-LLM.5, E0-Jobs.2 (registry, `enqueue`), E0-Jobs.3 (worker wrapper), E0-Jobs.5 (admission skip), E0-Jobs.1 and E0-Jobs.8 (`derived_sources`).
- **Size:** L

### Story E4.6: Tap a name for its card, or ask the Chronicler, in under two seconds

As a GM mid-game,
I want names in captions to be tappable, and a lookup box where I can type a name or ask a question,
So that I can answer "who was that dwarf smith?" without leaving the game.

**Acceptance Criteria:**

**Given** a caption
**When** the drainer publishes it
**Then** it carries `names: [{start, end, entity_id}]` from `world_service.match_names(ctx, text)` (GM ctx; Entity names and aliases only), and the client renders those spans as dotted-underlined buttons.

**Given** a tapped name or a typed name in QuickLookup
**When** the client calls `GET /api/live/{id}/lookup?q=<text>|entity_id=<id>`
**Then** the server answers without the LLM: the best `match_names`/`normalize_name` match, its EntityCard data (GM projection, status with its "since" source) and its 2 latest Mentions with quotes (confirmed first; suggested ones labelled "suggested")
**And** p95 response time is ≤ 2 s on the Reference-Box-like CPU setup with a 300-Entity seeded Campaign, recorded in `docs/BENCHMARKS.md` (NFR-6 lookup row).

**Given** QuickLookup on tablet or desktop (right rail) or phone (bottom sheet; the Lookup tab)
**When** a lookup starts
**Then** a skeleton shows at once and the card replaces it. Typing matches names and aliases as the GM types (Combobox). `/` focuses the box.

**Given** input that isn't a name match (a question such as "who was the dwarf smith?")
**When** the GM submits it
**Then** `POST /api/live/{id}/ask` streams an answer through `sse_response` under `llm_slot("gm_interactive")`, using the Chronicler's retrieval for the GM ctx (`hybrid_search_journal`) plus a keyword match over this session's `live_segments`, with grounding instructions in the final user turn
**And** the answer carries `ResolvedSource[]` (journal and `live_segment` refs) and `grounded`. When nothing passes the relevance gate, it shows "not from your journal".

**Given** the ask route
**When** it is registered
**Then** it has `@limiter.limit` keyed `user_or_ip`, an anchored regex `location ~ ^/api/live/[0-9a-f-]+/ask$` in the `ai_gen` zone with `proxy_buffering off` (which takes precedence over the `/api/live/` prefix block), BYOK resolution and hosted metering
**And** `tests/ev4/probes/live.py` covers lookup and ask: a non-GM gets a uniform `404`.

- **Covers:** FR-28, NFR-6 (lookup row), NFR-7, NFR-8, UX-DR26 (QuickLookup, tappable names, skeleton, bottom sheet).
- **Technical notes:** AD-15, AD-8, AD-13 (AI context via ctx), AD-20 (anchored regex). `match_names` and `normalize_name` are the only name matchers (B3 contract). `EntityCard` comes from `components/entities/` (B3). The `caption` message gains `names` (internal E4 protocol). The Chronicler call reuses `chat_service` context building with the ctx refactor from E0-Access. No legacy-NPC fallback (see Decisions).
- **Dependencies:** E4.5, E0-WorldCore.4 (`match_names`), E0-WorldCore.7 (Mentions), E0-WorldCore.11 (`EntityCard`), E0-Access.7 (ctx-aware retrieval), E0-Access.8 (Chronicler ctx path), E0-Jobs.6 (`sse_response`), E0-UX.4 (Combobox), E0-LLM.2.
- **Size:** L

### Story E4.7: End the session and turn the full transcript into a draft entry

As a GM,
I want ending a Live Session to turn the whole transcript into draft notes I review before saving,
So that nothing from a long session is lost or saved without my approval.

**Acceptance Criteria:**

**Given** a session in `recording` or `paused`
**When** the GM presses End and confirms inline ("End session? Captions stop.")
**Then** the state becomes `ended`, the `live` lease is released, the `live_session_ended` hook event is dispatched (`{campaign_id, refs:[live_session], actor_ctx}`), and `live.draft` is enqueued (`queue=interactive`, `resources={llm, stt}`, `live_safe=False`, `timeout_s=1800`, `result_audience=gm`, idempotency `live.draft:{id}:{last_seq}`).

**Given** the `live.draft` handler
**When** it runs
**Then** it first transcribes any chunks still `received`, then builds shorthand notes from the **full** transcript with `prompt_budget.map_reduce(task="live_draft")`, with no truncation (a test with a sentinel phrase in the last chunk of a transcript over 60,000 characters asserts it reaches the notes)
**And** it stores the result in `live_sessions.draft_shorthand` and reports stage, progress and ETA ("Summarising part 3 of 9"). The result is never a saved journal entry.

**Given** the Job is done
**When** the End screen shows
**Then** it displays the full transcript (collapsible), then hands `draft_shorthand` to the existing summarise-and-review flow: shorthand → narrative draft (`/api/journals/generate-draft`) → `NarrativeReviewPanel` → Save
**And** Save creates the entry only through the E0-Journal writers, sets `live_sessions.journal_id`, and lets `entry_saved` trigger F1/F2 Jobs where present. Discard leaves no entry.

**Given** audio rules
**When** the session ends
**Then** with `keep_audio=false` and no diarization pending, every remaining `live_audio` file is deleted once its chunk is transcribed or skipped
**And** with `keep_audio=true`, audio is kept, a "Delete raw audio" action is offered on the session, and the audio is excluded from backups unless the GM opts in (AD-14). With `diarize_requested=true`, deletion waits for `diarize.run` (E4.10).

**Given** the End confirm
**When** it is shown
**Then** it restates the start-time choices read-only ("Raw audio: kept" or "deleted after transcription") and allows switching a kept-audio session to "delete now", but not the reverse.

- **Covers:** FR-29, AR-15 (End-of-session draft; Audio deletion), NFR-5, NFR-9 (a failed draft Job leaves the transcript and allows Retry), UX-DR26 (End confirm).
- **Technical notes:** AD-15, AD-17 (journal writers, hooks), AD-14, AD-8 (`map_reduce`). The handler goes in `app/jobs/live.py`. `chat_service.summarize_session_transcript` (`chat_service.py:276`) gains a `prompt_budget`-based path for `live_draft` in place of its 12,000-character truncation. Its existing single-recording caller keeps its contract. The UI reuses `components/NarrativeReviewPanel.tsx` unchanged.
- **Dependencies:** E4.6, E0-Journal.2 (writers), E0-Journal.1 (hook dispatcher, `live_session_ended`), E0-LLM.3 (`map_reduce`), E0-Jobs.9 (`useJobStream`), E0-Jobs.10 (Job tray).
- **Size:** L

### Story E4.8: Table view the players can read from across the table

As a GM,
I want a Table view with huge captions and the Rolling Recap,
So that I can prop the tablet up for the players or glance at it from a standing position.

**Acceptance Criteria:**

**Given** a Live Session
**When** the GM presses `t` or the status-bar toggle
**Then** Table view hides the nav and rails and shows the latest two captions in `{typography.caption-table}` (36 px) and the Rolling Recap below in `{typography.recap-table}` (32 px), with Lookup and Exit buttons at `{spacing.tap-target-table}`, and the status bar (REC, lag, recap age) stays pinned
**And** it has no shadows and no translucency, works with every theme's tokens, and `Esc` or Exit leaves it.

**Given** a real-table check at about 1.5–2 m on a 10–13" tablet in room light
**When** the owner reads the captions and the recap
**Then** the result (readable, or the sizes adjusted) is recorded in `docs/BENCHMARKS.md` under "Table view legibility". If sizes change, the DESIGN.md tokens are proposed as a follow-up, not edited here (D-6(5)).

- **Covers:** UX-DR26 (Table view), UX-DR9 (`caption-table`, `recap-table`), NFR-10.
- **Technical notes:** EXPERIENCE.md "Table view", DESIGN.md table-view rules. The shortcut is registered in the E0-UX shortcut registry, and it never fires in inputs. Frontend only.
- **Dependencies:** E4.6.
- **Size:** S

### Story E4.9: Live Session evaluation: caption quality, Rolling Recap faithfulness and DS-4 part one

As the owner presenting the capstone,
I want measured caption quality and Rolling Recap faithfulness and a rehearsed offline DS-4 first half,
So that the Live Session's claims are backed by numbers, not anecdote.

**Acceptance Criteria:**

**Given** a recorded 10-minute table clip with a hand-checked reference transcript (stored outside git; its path and sha256 are recorded)
**When** `scripts/eval_live_captions.py` replays it through the Live socket against `stt` base int8
**Then** it reports WER (jiwer-free, implemented with a stdlib edit distance), fantasy-name accuracy with and without `initial_prompt`, and lag p50/p95, written to `docs/LIVE_EVAL.md` in the RETRIEVAL_EVAL format
**And** SM-7 (WER ≤ 30%, provisional) is reported as pass or fail, not tuned to pass.

**Given** 2 Rolling Recaps produced from recorded clips (one of 2 hours, including the minute-5 fact)
**When** `scripts/eval_recap_rolling.py` runs
**Then** every recap sentence is labelled supported or unsupported by its cited `live_segment`s (keyword pre-screen, then owner judgement against a written rubric), and the share of supported sentences is written to a "Rolling Recaps" section of `docs/RECAP_EVAL.md` (created if E5 hasn't created it yet) against SM-8 (≥ 90%)
**And** the minute-5 fact check (FR-27) is reported explicitly.

**Given** DS-4 first half
**When** it is run on the remote desktop with networking to the internet disconnected (Tailscale and LAN only)
**Then** a Live Session from a recorded clip shows captions, a Rolling Recap, and a tapped NPC whose card appears in ≤ 2 s. The run is recorded (date, commit, timings) in `docs/BENCHMARKS.md`.

- **Covers:** SM-7, EV-6 (Rolling), FR-26/FR-27 verification, NFR-6 (caption, recap and lookup rows confirmed end to end), NFR-1, DS-4 (first half).
- **Technical notes:** AD-21 (Evals in RETRIEVAL_EVAL format, run on the committed demo seed). Scripts go in `src/backend/scripts/`. No new dependencies (no jiwer). Clip audio is not committed, so this adds no licence-register item for clips.
- **Dependencies:** E4.7, E0-QA.12 (demo seed, eval scaffold), E0-QA.15 (`docs/BENCHMARKS.md`).
- **Size:** M

### Story E4.10: SPIKE-4, decide whether offline speaker labels ship

As the owner,
I want measured diarization time and a verified offline install for the candidate engines,
So that I can decide whether FR-30 ships and with which engine, before anyone builds it.

**Acceptance Criteria:**

**Given** pyannote `community-1` (MIT code, CC-BY-4.0 gated weights) and sherpa-onnx (Apache-2.0) speaker diarization
**When** each diarizes a recorded 1-hour table clip on the remote desktop, CPU-only, in a container with a 2.5 GB memory limit and 4 threads
**Then** the wall time, peak RSS and a speaker-turn accuracy spot check (10 sampled turns) are recorded in `_bmad-output/planning-artifacts/spikes/diarization.md`.

**Given** an offline install
**When** each engine's image is built with weights baked in and started with `--network none`
**Then** whether it runs is recorded, along with how the gated pyannote weights can be distributed (licence and redistribution notes for `licenses/register.yaml`)
**And** the image uses CPU-only torch or ONNX runtime wheels. The proprietary NVIDIA CUDA wheels must not be pulled into the `diarize` image (E0-Platform.2 removes them from the backend image, and the CPU-only licence check would miss them).

**Given** the results
**When** the spike record is written
**Then** it states ship or no-ship for FR-30, the engine, and the `diarize` profile memory limit (outside the AD-7 sum, run only while `stt` is unloaded)
**And** diarization stays **off by default** and hidden, whatever the result, until E4.11 is done.

- **Covers:** SPIKE-4, FR-30 (decision), NFR-4 (licence findings).
- **Technical notes:** AD-7 (Diarization outside the sum), AD-22. Spike only, with no product code. Cut order: FR-30 is cut first, so cutting it removes E4.11, and E4.10 is optional.
- **Dependencies:** E4.7.
- **Size:** S

### Story E4.11: Optional offline speaker labels as a Job

As a GM,
I want to ask for speaker labels on a finished Live Session transcript when the diarization model is installed,
So that I can tell who said what without the app ever doing it by default.

**Acceptance Criteria:**

**Given** SPIKE-4 (E4.10) recorded "ship" with an engine
**When** the `diarize` compose profile is enabled and its `/healthz` responds
**Then** the Live Start panel shows "Label speakers afterwards (Job)" (off by default), which sets `diarize_requested` at start. When the profile is absent, the option is hidden, not disabled (FR-30, UX ModelMissingNotice rule).

**Given** a session that ended with `diarize_requested=true`
**When** `diarize.run` runs (`queue=backfill`, `resources={cpu_heavy}`, `live_safe=False`, `timeout_s` from the spike, `result_audience=gm`, idempotency `diarize.run:{id}`)
**Then** it waits until no `live` lease is held and `stt` is idle-unloaded, sends the kept chunk audio to the `diarize` sidecar, and writes a `speaker` label onto each `live_segment` (a nullable column added by this story's revision)
**And** when it finishes, successfully or with a final failure, every `live_audio` file for the session is deleted unless `keep_audio` is set (FR-29, AD-15).

**Given** labels exist
**When** the transcript shows on the End screen or session page
**Then** segments are grouped by "Speaker 1, 2…" and the GM can rename speakers for that view only. Labels never change the draft unless the GM regenerates it.

**Given** the new image
**When** it is added
**Then** `licenses/register.yaml` lists the engine, its runtime and its weights, and the image passes the licence scan in the edition it is allowed in.

- **Covers:** FR-30, AR-15 (audio kept until diarization), NFR-2 (outside the sum, run after the session), NFR-4.
- **Technical notes:** AD-7, AD-15, AD-6 (sidecar contract shape `POST /v1/diarize` multipart audio → `{turns:[{start_ms,end_ms,speaker}]}`, defined here because no other epic uses it). New: `app/jobs/diarize.py`, `src/services/diarize/` with its Dockerfile, a profile in the compose files (one-line additions; compose is owned by E0-Platform). This is the first story to cut.
- **Dependencies:** E4.10 (must say "ship"), E4.7.
- **Size:** M

## Epic E5: "Previously on…" narrated recaps

The GM opens a Session with a genre-voiced recap she has reviewed. In the AGPL build it is narrated locally by Kokoro. In the commercial build the browser reads it. Players can replay Party recaps. Narration always goes through the `TTSProvider` interface (AD-16), synthesizes one sentence per call (SPIKE-3: about 2.1 GB peak per sentence, 3.9 GB per paragraph, which is forbidden), and refuses any engine configuration that drops proper nouns.

### Story E5.1: Draft and save a "Previously on…" recap with citations

As a GM,
I want to generate a "Previously on…" recap of the last few Sessions in my Campaign's genre voice and save it only after I've reviewed it,
So that I can open the next Session with a faithful summary that cites where every fact came from.

**Acceptance Criteria:**

**Given** a Campaign with entries in at least 3 Sessions (Session key = `session_date ?? created_at::date`)
**When** the GM calls `POST /api/recaps/draft` with `{campaign_id, sessions: N}` and N = 1 (the default)
**Then** the recap text streams through `sse_response`, starts with "Previously on…", and uses the voice of `ai_service.GENRE_SYSTEM[campaign.genre]`
**And** it draws only on entries from the most recent N Sessions, and the final event carries `sources: ResolvedSource[]` (kind `journal`, built by `access.resolve_sources`) and `grounded`.

**Given** N is outside 1–5
**When** the draft is requested
**Then** the response is 422 and no LLM call is made.

**Given** the default `include_gm=false`
**When** the draft context is built
**Then** it is built with `audience_ctx(campaign_id, member)`, so only Party Narratives are used, with no Shorthand, GM-only entries or GM-only Entity fields
**And** the EV-4 capture hook shows no canary string in the prompt.

**Given** the GM sets `include_gm=true`
**When** the draft is built
**Then** GM-only entries' Narratives may be used (Shorthand never is), and the draft is labelled "GM-only" before saving.

**Given** a draft has streamed
**When** the GM closes the panel without saving
**Then** no `recaps` row, `derived_sources` row or Job exists, so the draft endpoint persists nothing.

**Given** the GM edits the text and calls `POST /api/recaps` with `{campaign_id, text, source_refs, include_gm, sessions}`
**When** it saves
**Then** a `recaps` row is written with `text_version=1`, and one `derived_sources(derived_type="recap", ref_kind=journal, ref_id)` row is written per cited entry
**And** the recap's Audience is `most_restrictive(sources)`: Public when every source is a Party GM-kind entry, GM when any source is GM-only.

**Given** a saved recap
**When** the GM calls `PATCH /api/recaps/{id}` with new text, or `DELETE /api/recaps/{id}`
**Then** an edit increments `text_version`, and a delete removes the row and its `derived_sources`.

**Given** a Player or an anonymous Share Link ctx
**When** it calls `POST /api/recaps/draft`, `POST /api/recaps`, `PATCH` or `DELETE`
**Then** each returns `404 {"detail":"Not found"}`.

**Given** the LLM gate is busy for 60 s
**When** a draft is requested
**Then** the route returns 503 `{code:"llm_busy"}` through the E0-LLM error helper, and nothing is written.

**Standing ACs:** SA-Route (`tests/ev4/probes/recaps.py`: a GM-only recap is absent from `GET /api/recaps?campaign_id=` for Player and anon, `GET /api/recaps/{id}` returns the same 404 as a nonexistent id, and the captured draft context for `include_gm=false` holds no canary; `locations.conf` adds an anchored `ai_gen` location for `/api/recaps/draft` with `proxy_buffering off`, and the draft route gets `@limiter.limit` keyed `user_or_ip`). SA-Table (`recaps`, class `derived` from `derived_sources`). SA-AI.

**Covers:** FR-31, FR-34 (list route projection), NFR-7, AR-16 (recap part), AR-23.

**Technical notes:**
- New `services/recap_service.py` builds the prompt (Decision B6-3), `api/routes/recaps.py` holds the routes, and `schemas/recaps.py` holds `RecapGMResponse` and `RecapPartyResponse`. The `recaps` columns are `id, campaign_id, created_by, text, text_version, sessions (date[]), include_gm, genre, created_at, updated_at`. There is no `visibility` column: the Audience is derived (AD-12, AD-14).
- Recap drafts stream in-request and are not Jobs (AD-3). They use the gate class `gm_interactive` (AD-8). `prompt_budget.fit("recap", parts)` uses map-reduce per Session when 5 Sessions exceed `OLLAMA_CONTEXT_LENGTH`. Grounding instructions ("cite only the listed entries; say nothing not in them") go in the final user turn.
- The existing `POST /api/journals/recap` (`api/routes/journals.py:253`, `chat_service.generate_session_recap:249`) is left unchanged. Keepsakes uses the new route.
- `GET /api/recaps?campaign_id=` returns recaps projected for the ctx, newest first. Players see only recaps whose derived Audience includes them (FR-34).

**Dependencies:** E0-Access.2 (`require_campaign`), E0-Access.3 (`audience_ctx`, `scoped_select`, registry), E0-Access.4 (Party projection, uniform 404), E0-Access.8 (`SourceRef`, `resolve_sources`), E0-Jobs.1 (`derived_sources`), E0-Jobs.6 (`sse_response`), E0-LLM.1 (typed errors), E0-LLM.2 (`llm_slot`), E0-LLM.3 (`prompt_budget.fit`), E0-LLM.5 (fake provider), E0-Platform.8, E0-QA.11.

**Size:** M

### Story E5.2: Keepsakes page and the "Previously on…" tab

As a GM,
I want a Keepsakes page where I pick Sessions, watch the recap stream into the familiar review panel, edit it and save it,
So that I can prepare the recap in a minute before the group arrives.

**Acceptance Criteria:**

**Given** no `/keepsakes` route exists yet (E8.5 has not landed)
**When** this story merges
**Then** it creates `pages/KeepsakesPage.tsx` (named export, lazy) with route-mapped Tabs "Previously on…" (`/keepsakes/previously-on`) and "Chronicle" (`/keepsakes/chronicle`, rendering an EmptyState until E8.5), plus a `NAV_GROUPS` line under Chronicle
**And** if E8.5 already created the shell, this story only fills the "Previously on…" tab.

**Given** the GM is on the "Previously on…" tab
**When** she chooses "Last 1–5 Sessions" in a SegmentedControl and taps Generate
**Then** the text streams into a review panel styled like `NarrativeReviewPanel`, with a Party or GM-only label, the cited entries listed by italic title, and a "Include GM-only entries" toggle that is off by default and carries a gm badge.

**Given** the streamed draft
**When** she edits the text and taps Save
**Then** the recap is saved through `POST /api/recaps`, appears at the top of the saved recaps list, and the toast "Recap saved" appears
**And** closing without saving asks "Discard this recap?" and stores nothing.

**Given** no Sessions exist
**When** the tab opens
**Then** EmptyState shows "Pick the Sessions to recap." (EXPERIENCE.md "Per surface"), and Generate is disabled.

**Given** the request fails with `llm_busy` or a network error
**When** the error returns
**Then** an inline `danger` message with Retry appears, and the selected Sessions and toggle are kept (UX-DR13).

**Given** a saved recap and a device with no server TTS
**When** the GM presses "Read aloud"
**Then** `hooks/useNarration.ts` reads the text with the browser voice, so the tab is useful before E5.3 to E5.6 land.

**Given** a Player
**When** they open `/keepsakes`
**Then** the "Previously on…" tab shows the saved Party recaps read-only, with no Generate, edit or include-GM controls.

**Standing ACs:** SA-UI (Tabs and SegmentedControl from E0-UX, 375 px single column, streaming text announced politely, reduced motion with no caret animation). PreviewBanner read-only flag disables Generate and Save.

**Given** E8.5 may land first and create the Keepsakes shell (Reconciliation RC-18)
**When** this story merges after it
**Then** it fills only the "Previously on…" tab and keeps the existing route, Tabs and `NAV_GROUPS` line. Whichever story lands first creates `pages/KeepsakesPage.tsx`; the other only fills its tab.

**Covers:** FR-31 (UI), NFR-10, UX-DR27 (Keepsakes page and tabs), UX-DR13.

**Technical notes:** `services/api/recaps.ts`, `types/recaps.ts`, `hooks/useRecaps.ts` (keys `["recaps", campaignId]`), and `components/recap/RecapDraftPanel.tsx`. Streaming uses `lib/sse.ts` only, with no EventSource and no `?token=` (AR-24). One line each in `App.tsx` and `NAV_GROUPS`.

**Dependencies:** E5.1, E0-UX.4, E0-UX.5, E0-UX.6, E0-UX.8, E0-Jobs.9 (`lib/sse.ts`).

**Size:** M

### Story E5.3: TTSProvider interface, build editions and the proper-noun guard

As a self-hosting Owner,
I want narration to run behind one provider interface that knows which edition I'm running and refuses any voice engine that drops names,
So that the commercial build never ships GPL code and no recap ever silently loses "Borin" or "Karak Dun".

**Acceptance Criteria:**

**Given** `services/tts_service.py`
**When** it is imported
**Then** it defines the `TTSProvider` protocol with `name`, `available() -> Availability(ok, reason)`, `voices()` and `synthesize_sentence(text, preset) -> bytes` (MP3)
**And** `tts_service.PROVIDERS` is the only registry, and no other module names an engine (enforced by an import-linter contract or a grep test).

**Given** the provider `none`
**When** `available()` is called
**Then** it returns `ok=False, reason="browser_only"`, `voices()` is empty, and `synthesize_sentence` raises `ModelServiceUnavailable`.

**Given** `LOREKEEPER_EDITION=commercial`
**When** settings load with `TTS_PROVIDER` unset or set to `kokoro_http`
**Then** `core/config.py` forces `tts_provider="none"`, logs one warning when the value was overridden, and never selects `kokoro_http`.

**Given** `domain/narrators.py`
**When** it loads
**Then** it holds at least one preset per `(provider, genre)` for the genres `fantasy, scifi, horror, videogame, other`. Each preset has an `id`, a provisional display name, a voice expression and a speed. The `none` presets carry browser hints (`rate`, `pitch`, `lang`), and `other` falls back to the fantasy preset (addendum).

**Given** text with abbreviations ("St. Aldric", "Mr. Grukk"), ellipses, quotes and one 900-character run-on sentence
**When** `tts_service.split_sentences(text)` runs
**Then** it returns sentences in order that join back to the original text with only whitespace removed, no abbreviation is split, and no piece is longer than `TTS_MAX_SENTENCE_CHARS` (300). Long sentences split at `;`, `—`, `,` and then at word boundaries.

**Given** a provider and its presets
**When** `tts_service.qualify(provider)` runs
**Then** it synthesizes the proper-noun probe set (every Entity name in `seeds/demo_campaign.json`: Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker), transcribes each clip through `clients/stt.transcribe` without an `initial_prompt`, and aligns the transcript to the input with difflib
**And** the provider passes only when every name has an aligned transcript span with normalized similarity ≥ 0.6, which tolerates STT misspellings such as "Karak Don" or "Grok" but not missing words
**And** the result is stored as `tts:qualified:{provider}:{engine_version}` in Redis, and `available()` returns `ok=False, reason="proper_nouns_dropped"` until qualification passes.

**Given** the recorded negative control (a fixture of clips from the SPIKE-3 configuration with the espeak fallback disabled, where 7 words were silently dropped)
**When** `tests/test_tts_qualify.py` runs the detector on it with the STT client fake replaying the spike transcripts
**Then** qualification fails and names the dropped names, which proves the guard rejects that configuration.

**Given** `TTS_PROVIDER=kokoro_http` and an engine config known to drop proper nouns (`TTS_ESPEAK_FALLBACK=false` or any option `domain/narrators.py` marks `drops_oov`)
**When** settings load
**Then** startup fails with "This TTS configuration drops proper nouns (FR-33). Enable the espeak fallback (AGPL build) or use TTS_PROVIDER=none."

**Covers:** FR-33, NFR-4 (edition rule), AR-16, LIC-1 (guard part), CI-3 (TTS package list confirmed).

**Technical notes:**
- AD-16 is the binding rule. The settings `tts_provider`, `tts_url`, `lorekeeper_edition` and `tts_max_sentence_chars` go in `core/config.py`.
- The CI-3 gate (E0-QA) already forbids `kokoro`, `kokoro-onnx`, `misaki`, `phonemizer` and `espeakng-loader` in the web and worker images. This story adds a test that asserts the list is present.
- Qualification runs once per engine version, at worker boot when a provider is configured, and from the admin System tab "Test narrator" (one button, GM or admin only, via the existing admin route pattern). It needs `stt`, which is resident-on-demand (AD-7).
- The lexicon override path (Entity names as Kokoro inline phonemes) stays a deferred spike. It would be a new provider that must pass this same `qualify`.

**Dependencies:** E0-Platform.5 (`stt` and `clients/stt.py`), E0-Platform.6 (CI-3 model-package gate), E0-QA.5 (client fakes on `TEST_DATABASE_URL` substrate), E0-QA.10, E0-QA.12 (demo seed).

**Size:** M

### Story E5.4: Kokoro narrator sidecar for the AGPL build

As a GM on the AGPL build,
I want a local Kokoro Narrator that speaks recaps one sentence at a time inside its memory limit,
So that narration works offline on the 16 GB Reference Box without starving the LLM.

**Acceptance Criteria:**

**Given** `LOREKEEPER_EDITION=agpl` and `COMPOSE_PROFILES=tts`
**When** `docker compose up` runs
**Then** a `tts` service starts from the pinned Kokoro-FastAPI CPU image v0.9.2 with `mem_limit: ${TTS_MEM_LIMIT:-2.5g}` (already counted in the AD-7 sum), no published ports, only the internal compose network, and a healthy `/health`
**And** without the `tts` profile, or with `LOREKEEPER_EDITION=commercial`, no `tts` container is created and the app runs with `TTS_PROVIDER=none`.

**Given** the `tts` image started with `--network none` in CI (CI-5)
**When** its health check runs
**Then** it passes, because weights and voices are baked in. If the upstream image downloads at first start, the story adds `src/services/tts/Dockerfile`, which bakes them in at build time.

**Given** the provider `kokoro_http`
**When** `synthesize_sentence(text, preset)` is called
**Then** it makes exactly one `POST /v1/audio/speech` call with `{model:"kokoro", input:<that sentence>, voice:<preset blend>, speed, response_format:"mp3"}` through `clients/tts.py`, and raises `ModelServiceUnavailable` on timeout or 5xx.

**Given** any recap
**When** `tts_service.narrate(text, preset)` runs
**Then** it calls `split_sentences` and makes one request per sentence (a test with a recording fake asserts that no request `input` exceeds 300 characters and none contains two sentences)
**And** it concatenates the MP3 frames in the worker after stripping per-clip ID3 tags, with no ffmpeg, and returns `(mp3_bytes, timings)`, where `timings[i] = {start_ms, end_ms}` per sentence is derived from the frame count.

**Given** the AGPL stack on the Reference Box
**When** `tts_service.qualify("kokoro_http")` runs with the espeak fallback on (the default in the image)
**Then** it passes, and the result is recorded.

**Given** a 300-word recap synthesized sentence by sentence
**When** the `tts` container's RSS is sampled
**Then** the peak stays under the 2.5g limit, and the measured peak is written to `docs/BENCHMARKS.md` (SPIKE-3 remaining item: Linux RSS).

**Standing ACs:** SA-Dep (`licenses/register.yaml`: Kokoro-FastAPI image (Apache-2.0, `editions: [agpl]`), Kokoro-82M weights (Apache-2.0), each shipped voice pack (Apache-2.0), espeak-ng inside the image (GPL-3.0-or-later, `editions: [agpl]`, note "process-isolated in tts container; never in web/worker"), and the LIC-1 findings from `spikes/cpu-benchmarks.md` §3.2). Total TTS model plus voice disk ≤ 500 MB, asserted from the image layer sizes in the register-vs-artifacts check.

**Given** `app/clients/tts.py` (Reconciliation RC-5: the file is built here, not in E0-Platform)
**When** it is written
**Then** it follows the AD-6 shape of `clients/ml.py` and `clients/stt.py`: `ModelServiceUnavailable` from `app/clients/errors.py`, timeouts from settings, and its fake in `app/clients/fakes.py` (one appended class), and an E0-Platform owner reviews it.

**Covers:** FR-32 (engine), FR-33 (AGPL Narrators), NFR-1, NFR-2, NFR-3, NFR-4, AR-6 (tts row), AR-7, AR-16, AR-22, SPIKE-3 (RSS part), LIC-1 (register part).

**Technical notes:** The compose service goes in `docker-compose.prod.yml` and `docker-compose.dev.yml` under `profiles: [tts]`, with `.env.example` `TTS_MEM_LIMIT=2.5g` (CI-14 sum unchanged). The AD-6 table fixes the endpoint shapes. No B2 story creates `app/clients/tts.py`, so this story adds it (async httpx, `tts_url` timeout, `ModelServiceUnavailable`, plus a client fake beside the other E0-Platform fakes) as a one-file addition to the E0-Platform-owned directory (Decision B6-16). The voice blend expressions in `domain/narrators.py` stay provisional until E5.7.

**Dependencies:** E5.3, E0-Platform.7 (`TTS_MEM_LIMIT` reserved), E0-Platform.3 (CI-5 `scripts/sidecar_smoke.sh` pattern), E0-QA.7.

**Size:** M

### Story E5.5: Narration Job, audio cache, invalidation and the Party audio route

As a GM,
I want to narrate a saved recap as a background Job and have unchanged recaps replay from cache,
So that I can prepare minis while it renders, and Players hear only recaps they're allowed to.

**Acceptance Criteria:**

**Given** a saved recap and an available provider
**When** the GM calls `POST /api/recaps/{id}/narrate` with `{preset_id}`
**Then** it returns `{job_id}` in under 1 s, and the Job kind `recap.narrate` runs `tts_service.narrate` and stores the audio through `file_service.put` as kind `recap_audio`, with `cache_key = sha256(provider|preset|text|audience)` and the `timings` JSON
**And** it writes `derived_sources` rows for the recap and each of its source entries.

**Given** the same recap text, preset, provider and audience
**When** narration is requested again
**Then** the Job takes the same path and finishes by returning the existing non-stale file without calling the provider (cache hit, AD-16).

**Given** a narrated recap
**When** the GM edits its text
**Then** the old `recap_audio` file is marked stale, `GET /api/recaps/{id}` reports `audio: null` with `audio_state: "out_of_date"` for the GM, and the next Narrate produces a new file.

**Given** a narrated Party recap
**When** a GM changes any source entry to GM-only through `set_visibility`
**Then** the recap's derived Audience becomes GM, its audio is marked stale through `derived_sources`, and both the recap and the audio return 404 to Players (FR-32, FR-41).

**Given** `TTS_PROVIDER=none` or a provider whose `available()` is false
**When** Narrate is requested
**Then** the route returns 503 `{code:"tts_unavailable", detail:"Narrator unavailable"}`, and no Job is created.

**Given** the `tts` container goes down mid-Job
**When** a sentence call fails
**Then** the Job retries per AD-4 (10 s, then 60 s), and after 3 attempts it is `failed` with `error_code=model_unavailable` and the readable reason "The Narrator service is not responding." The recap text is unaffected.

**Given** a Player
**When** they list recaps or fetch `GET /api/recaps/{id}`
**Then** Party recaps include `audio_file_id` and `timings` only when the audio is non-stale, and the audio downloads through `GET /api/files/{id}` (access-checked, `X-Accel-Redirect`).

**Given** a GM-only recap with audio
**When** a Player or anon ctx requests the recap, its audio file id, the Job stream or the campaign events
**Then** the recap and audio return the same 404 as a nonexistent id, and no Job event or `result_ref` for it reaches them (FR-34).

**Standing ACs:** SA-Job (`recap.narrate`: `queue=interactive`, `timeout_s=600`, `resources={tts}`, `live_safe=False`, `result_audience=` the recap's derived Audience; idempotency key `recap.narrate:{recap_id}:{text_version}:{preset_id}:{provider}`). SA-Route (extends `tests/ev4/probes/recaps.py` with the audio route, the downgrade suite for the `recap` and `recap_audio` `DERIVED_REGISTRY` types, and Job-event leakage; `@limiter.limit` on narrate; `locations.conf` anchored location for `/api/recaps/[^/]+/narrate`). SA-Bench (NFR-6 row "narration of 300 words ≤ 2 min CPU / ≤ 30 s GPU", measured on the Reference Box with the GPU override off).

**Covers:** FR-32, FR-34, FR-41 (derived invalidation for recaps), NFR-5, NFR-6 (narration row), AR-14, AR-16.

**Technical notes:** `jobs/recap.py` (handler `async def handle(job, ctx, db)`, which writes the stage as "Narrating sentence 7 of 22" with progress and ETA), with the route added to `api/routes/recaps.py`. While the Live admission lease is held, the worker skips this kind because it uses `tts` (AD-3). Register `recap` and `recap_audio` in `DERIVED_REGISTRY`.

**Dependencies:** E5.1, E5.3, E0-Jobs.2, E0-Jobs.3, E0-Jobs.7, E0-Jobs.8, E0-Access.3, E0-Access.9 (`set_visibility` marks derived dependents stale), E0-Access.10. Soft: E5.4 (needed only for real audio; tests use a recording fake provider).

**Size:** M

### Story E5.6: RecapPlayer, Narrator choice and Table play

As a GM at the table (and a Player on the Portal),
I want a player that shows the recap text, highlights the sentence being spoken and falls back to my browser's voice,
So that everyone can follow along even when the Narrator is unavailable.

**Acceptance Criteria:**

**Given** a saved recap on Keepsakes
**When** the GM opens it
**Then** a Narrator chip shows the genre's default preset, any other preset can be chosen from a Combobox, and Narrate starts the Job, shows the row "Narrating… about 1 min" and ends with the toast "Recap narrated · Play".

**Given** a recap with audio
**When** `components/recap/RecapPlayer.tsx` renders
**Then** it shows a 44 px play/pause button, a scrubber, speed 0.75×–1.5×, Download and Table play
**And** the full text is always visible, and the current sentence (from `timings`) is highlighted and kept in view unless the user has scrolled in the last 5 s.

**Given** the provider is `none` or unavailable, or the audio is missing or stale for a non-GM
**When** the player renders
**Then** it uses `useNarration` sentence by sentence (one `SpeechSynthesisUtterance` per sentence, so the same highlight works) and shows "Narrator unavailable — using your browser's voice" (FR-33).

**Given** Table play
**When** it opens
**Then** a full-screen view shows the text in `typography.recap-table` (32 px) with large controls, Space toggles play, Esc exits, and focus returns to the opener.

**Given** any surface
**When** the player mounts
**Then** nothing plays until the user presses play (no autoplay).

**Given** a GM-only recap
**When** a GM views it
**Then** the badge "Only GMs can play this recap." is shown.

**Given** `prefers-reduced-motion`
**When** the sentence changes
**Then** the highlight moves without smooth scrolling or animation.

**Given** the Portal (B4) imports `RecapPlayer` with a recap from `GET /api/recaps?campaign_id=`
**When** a Player opens it
**Then** it renders the same way, with no Narrate or Narrator controls (the component takes `mode: "gm" | "listener"`).

**Standing ACs:** SA-UI (375 px, all controls keyboard operable, the scrubber is a slider with `aria-valuetext` in mm:ss, the sentence highlight announces nothing, play state is announced politely).

**Given** `components/portal/portalSections.ts` (E7.1) (Reconciliation RC-17)
**When** this story lands
**Then** it appends one line registering `{id: "recap", position: "top", component: LatestRecapCard}`, which shows the latest Party recap with `RecapPlayer` and renders nothing when there is none.

**Covers:** FR-32 (play, replay, download), FR-33 (fallback notice), FR-34 (component for the Portal), NFR-10, UX-DR27.

**Technical notes:** `components/recap/RecapPlayer.tsx` and `NarratorPicker.tsx`, and `hooks/useNarration.ts` extended with per-sentence mode (existing file, `EntryDetailPage.tsx:166` behaviour unchanged). The Job row comes from `useJobStream`. The recap card in the Portal slot is B4's.

**Dependencies:** E5.2, E5.5, E7.1 (Portal slot registry), E0-UX.4, E0-UX.5, E0-Jobs.9.

**Size:** M

### Story E5.7: EV-6 recap faithfulness, Narrator listening test and DS-5 recap step

As the capstone owner,
I want narrated recaps measured for faithfulness and the Narrator voices chosen by a listening test,
So that the recap feature has evidence behind it and the presets have final names.

**Acceptance Criteria:**

**Given** `seeds/demo_campaign.json`
**When** `scripts/eval_recap.py --kind narrated` runs offline with the bundled model
**Then** it generates 5 Narrated Recaps (Sessions N = 1, 1, 2, 3, 5), splits them into sentences and scores each sentence supported or unsupported against its cited entries (labelled by a human in `seeds/recap_labels.json`, with NLI-assisted pre-labelling allowed)
**And** it writes `docs/RECAP_EVAL.md` in the RETRIEVAL_EVAL format with the share of supported sentences, and SM-8 passes at ≥ 90%. If it fails, the doc records the gap and the prompt changes tried.

**Given** `docs/RECAP_EVAL.md` already exists from E4
**When** this story runs
**Then** it appends a "Narrated" section and leaves the Rolling section unchanged (and the other way round if E5 lands first).

**Given** the AGPL stack on the Reference Box
**When** the listening test runs (3 candidate voice blends per genre, each reading the same 300-word fantasy recap with the demo names, rated by the owner)
**Then** the chosen voice expressions, speeds and display names (for example "Fantasy · warm storyteller") are committed to `domain/narrators.py`, re-qualified with `tts_service.qualify`, and recorded in `docs/BENCHMARKS.md` (D-6.8).

**Given** DS-5 run offline
**When** the GM generates, edits, saves, narrates and plays a recap in Table play
**Then** each step succeeds with the internet disconnected (NFR-1), and the run is recorded in `docs/BENCHMARKS.md`.

**Covers:** EV-6 (Narrated), SM-8, SPIKE-3 (listening test), DS-5 (recap part), NFR-1, NFR-6 (confirmation), D-6.8.

**Technical notes:** The eval format follows the E0-QA contract (`scripts/eval_<name>.py` plus `docs/<NAME>_EVAL.md`). Labelled entries are appended to the seed per the E0-QA ownership rule.

**Dependencies:** E5.4, E5.5, E5.6, E0-QA.12, E0-QA.15.

**Size:** M

## Epic E6: Talk to an NPC

The GM preps by interviewing an NPC who answers in character from what it plausibly knows, and says "I don't know" otherwise. The GM can enable this for Players per NPC. Phase 2. Governed by AD-11 (NPC Knowledge), AD-13 (one enforcement point, AI context via ctx, stored AI output as `SourceRef`s), AD-8 and AD-12 (Mention audience formula).

**Owner decision (scope-input.md):** NPC Knowledge = the entries the NPC is linked to through confirmed Mentions, plus GM `grant`/`hide` overrides. All retrieval is scoped to that set **and** passes through `app/access/` visibility for the requesting ctx (E0-Access.3 registry and `scoped_select`, E0-Access.4 projections, E0-Access.7 retrieval with `entry_ids`). **Player NPC Conversations are off for every NPC by default.**

**Covers:** FR-35, FR-36, FR-37, FR-38, FR-39, NFR-6 (first token), NFR-7, NFR-5, AR-11 (NPC Knowledge), EV-3, SM-3, SM-C2, DS-4 (second half), UX-DR28.

### Story E6.1: Compute an NPC's knowledge and scope retrieval to it

As a GM,
I want each NPC's knowledge to be computed from the entries it is confirmed in, adjusted by my grants and hides and always filtered by visibility,
So that an NPC can only ever draw on what it plausibly knows and what the asker may see.

**Acceptance Criteria:**

**Given** a new revision (rebased onto head)
**When** it is applied
**Then** it creates `npc_knowledge` (`id`, `campaign_id`, `entity_id` with the composite FK `(campaign_id, entity_id)` to `entities`, `ref_kind ∈ {journal, entity_field, canon_note}`, `ref_id`, `ref_field` (an empty string when not a field), `how ∈ {grant, hide}`, `created_by`, `created_at`, `UNIQUE(entity_id, ref_kind, ref_id, ref_field)`) and `npc_settings` (`entity_id` PK and composite FK, `campaign_id`, `player_chat_enabled` bool default **false**, `voice_notes` text default `''`)
**And** both are registered `always_gm`. `npc_settings.voice_notes` is GM-only by rule (AD-12), and CHECKs come from StrEnums.

**Given** `npc_chat_service.knowledge_set(db, ctx, npc_entity) -> KnowledgeSet`
**When** it is computed
**Then** the default entries are the journal entries with a **confirmed** `entity_mentions` row for the NPC (or for any Entity merged into it) whose Mention audience (AD-12 formula) is visible to `ctx`, queried through `scoped_select` (E0-Access.3), never a raw `select`
**And** `grant` rows add entries, entity fields (including Secrets) or Canon Notes, and `hide` rows remove entries or the NPC's own persona fields. Hide wins over the default, and a grant beats a hide on the same ref only if the hide is older (the latest override wins).
**And** every granted ref is re-checked through `access` for the ctx, so a grant to GM-only content is dropped for a non-GM ctx.

**Given** suggested Mentions (`confirmed=false`), Change Proposals in any state, and other NPCs' or other users' chat sessions
**When** the knowledge set is computed
**Then** none of them contributes (a unit test seeds one of each with a canary string and asserts that it is absent from the set and from captured retrieval).

**Given** E0-Access.7's `retrieval_service.hybrid_search_journal(db, query_text, *, ctx, ..., entry_ids)`, which already restricts candidates to `entry_ids` after visibility
**When** NPC retrieval calls it with the knowledge set's entry ids
**Then** a test shows that an empty set returns no results, and that a set of 3 ids among 500 entries still returns up to k results from those 3 (the filter runs before ranking, so k is never starved)
**And** NPC retrieval passes `narrative_only=True`, the keyword E0-Access.7 provides (Reconciliation RC-9), so the search uses the Narrative-only `party_tsv`/`party_embedding` columns for every ctx, because an NPC witnessed the story, not the GM's Shorthand. E6 does not edit `retrieval_service`.

**Given** `GET /api/npc/{entity_id}/knowledge` (GM only)
**When** it is called for an NPC (`type=character`, `kind=npc`)
**Then** it returns rows `{ref, title, state ∈ {knows, granted, hidden}, is_secret}` and counts `{knows, granted, hidden}` for the KnowledgeScope chip
**And** a non-GM, a non-NPC Entity, or a missing id gets the uniform `404`, which `tests/ev4/probes/npc_chat.py` checks.

- **Covers:** FR-36 (knowledge set and exclusions), AR-11 (NPC Knowledge tables, `always_gm`), NFR-5.
- **Technical notes:** AD-11 (NPC Knowledge), AD-12 (Mention formula), AD-13 (`entry_ids` from E0-Access.7; retrieval takes ctx). New: `app/services/npc_chat_service.py`, `app/api/routes/npc_chat.py` (prefix `/api/npc`), `app/schemas/npc_chat.py`. `entity_mentions` is read through `access`. Canon Note grants are possible only once E2 registers `canon_note` (soft), and the ref kind is accepted but unused until then. Research row 8 covers the exact-search pre-filter.
- **Dependencies:** E0-WorldCore.2 (entities, `entity_mentions`), E0-WorldCore.7 (confirmed Mentions), E0-Access.2 (`CampaignContext`), E0-Access.3 (registry, `scoped_select`), E0-Access.7 (ctx-aware `hybrid_search_journal` with `entry_ids`, `party_*` columns), E0-QA.11 (EV-4 harness). E1 soft (more confirmed Mentions).
- **Size:** M

### Story E6.2: A GM's NPC Conversation streams in character from the NPC's knowledge

As a GM prepping a Session,
I want to talk to an NPC who replies in character, drawing only on its knowledge, and cites what it drew on,
So that I can rehearse scenes and trust the NPC not to invent things.

**Acceptance Criteria:**

**Given** a GM ctx and an NPC
**When** they call `POST /api/npc/{entity_id}/conversations`
**Then** a `chat_sessions` row is created with `npc_entity_id` set, owned by the user (Private), titled "{NPC name}", and returned
**And** `GET /api/npc/conversations?campaign_id=&npc_entity_id=` lists only the requester's own NPC Conversations, unarchived.

**Given** `POST /api/npc/conversations/{session_id}/stream` with a message
**When** the reply is built
**Then** the persona (a Character Card V2-style block) uses the NPC's name, description, status, attributes, `npc_settings.voice_notes` and the Campaign genre voice (`ai_service.GENRE_SYSTEM`). `gm_notes` (Secrets) are excluded unless explicitly granted, and hidden persona fields are excluded.
**And** context comes from `hybrid_search_journal(ctx, query, entry_ids=knowledge.entry_ids, narrative_only=True)` plus the text of granted entity fields, fitted with `prompt_budget.fit("npc_chat", …)` (history drops oldest first). The rule "you only know what is in your memories; if it isn't there, say in character that you don't know" is re-injected in the **final user turn** every turn (AD-8, chat_service measured pattern).

**Given** the stream
**When** it runs
**Then** it uses `sse_response` under `llm_slot("gm_interactive")` with the GM's resolved config (BYOK bypasses the gate), meters hosted usage, checks for `access:` messages between chunks and aborts upstream on a grant change
**And** the final event carries `sources: ResolvedSource[]` (built only by `access.resolve_sources`) and `grounded` (true when at least one knowledge item passed the relevance gate, the same 0.65 gate as the Chronicler). The stored message holds only `SourceRef`s, never quoted text.

**Given** a deceased or missing NPC (status category per `domain/entity_types.py`)
**When** a conversation starts
**Then** the first stored message is a system notice "{name} is {status} since *{entry title}*. You can still talk to them.", citing the status's source from `entity_changes`, and the GM can continue (FR-35).

**Given** a conversation in progress
**When** a grant or hide is changed (E6.5) between turns
**Then** the next reply uses the new knowledge set, because the set is recomputed per turn and never cached across turns.

**Given** the route
**When** it is registered
**Then** it has `@limiter.limit` keyed `user_or_ip`, an anchored regex location `~ ^/api/npc/conversations/[0-9a-f-]+/stream$` in `ai_gen` with `proxy_buffering off`, and EV-4 probes (uniform 404 for other users' sessions; captured LLM context holds no text outside the knowledge set, checked with a canary entry the NPC is not mentioned in).

**Given** the remote desktop
**When** first-token latency is measured over 20 turns on GPU (native Ollama) and on CPU (compose `ollama`, no GPU)
**Then** the p50/p95 rows go in `docs/BENCHMARKS.md` against NFR-6 (≤ 20 s CPU, ≤ 3 s GPU).

- **Covers:** FR-35, FR-36 (replies only from knowledge; changes apply from the next reply), FR-37 (backend: `grounded`, sources), NFR-6 (first token), NFR-7, NFR-8.
- **Technical notes:** AD-8, AD-11, AD-13 (Stored AI output; Grant changes), AD-5 (`sse_response`), AD-20. This is a variant of `chat.py` `_prepare_chat` and `/stream` in `npc_chat_service.build_npc_messages`. It adds a `prompt_budget` task line `npc_chat`. Message JSONB shape matches the existing `chat_sessions.messages` plus `refs`. The `chat_sessions.npc_entity_id` column comes from F1-core.
- **Dependencies:** E6.1, E0-Access.1 (`chat_sessions.npc_entity_id`), E0-Access.4 (`project`), E0-Access.8 (`resolve_sources`, `SourceRef` chat storage), E0-Access.10 (grant-change close), E0-Jobs.6 (`sse_response`), E0-LLM.2, E0-LLM.3, E0-Platform.8 (`user_or_ip`).
- **Size:** L

### Story E6.3: NPC Conversation screen with honest limits

As a GM,
I want an NPC mode in Chat that shows who I'm talking to, what they know, when they're thinking, and when a reply isn't from their memories,
So that I can see the boundary at a glance and trust it at the table.

**Acceptance Criteria:**

**Given** an NPC's Entity panel or page
**When** it renders for a GM
**Then** a "Talk to {name}" section (registered in `components/entities/panelSections.ts` for `character`/`npc`) opens `/chat?npc=:id`, resuming the latest conversation or starting one.

**Given** `/chat?npc=:id`
**When** it loads
**Then** the sidebar groups NPC Conversations under their NPC, and `NpcChatHeader` shows an initials avatar, the name in the heading face, a StatusBadge, a KnowledgeScope chip ("Knows 14 entries · 2 hidden") and a "Private" VisibilityBadge. A deceased or missing NPC shows the notice banner above the first message with no blocking confirmation.

**Given** a sent message
**When** the first token hasn't arrived after 5 s
**Then** a "{name} is thinking… 12 s — slower on CPU" row counts elapsed seconds, not a frozen spinner
**And** replies stream with the NPC's name above each as a section label (`npc-message`).

**Given** a finished reply
**When** `grounded` is true
**Then** a "Drawn from N entries" disclosure lists its `ResolvedSource`s (reusing the existing sources list)
**And** when `grounded` is false, a text `NotFromMemoriesLabel` warning pill reads "Not from this NPC's memories" (text, not an icon, so screen readers hear it).

**Given** an NPC with an empty knowledge set
**When** the conversation opens
**Then** the EmptyState reads "{name} has no memories yet. Confirm Mentions or grant entries in Knowledge." and links to the Knowledge section. Otherwise a greeting suggestion is shown ("Ask {name} what they saw at {latest entry title}.").

**Given** the UI floor
**When** it is checked
**Then** it uses tokens only, works at 375 px (sidebar as a sheet), is keyboard operable with visible focus, announces streaming politely, and has loading, error (`llm_busy` → "The AI model is busy. Try again in a moment.") and empty states.

- **Covers:** FR-35 (UI), FR-37 (refusal label, citations), UX-DR28 (NPC mode, sidebar grouping, NpcChatHeader, KnowledgeScope chip, notice banner, thinking row, Drawn-from disclosure, NotFromMemoriesLabel), NFR-7, NFR-10.
- **Technical notes:** EXPERIENCE.md "NPC Conversation", "NPC reply", Flow 5. DESIGN.md `NpcChatHeader`, `NotFromMemoriesLabel`. New: `hooks/useNpcChat.ts` (through `lib/sse.ts` only), `services/api/npcChat.ts`, `types/npcChat.ts`, NPC mode in `pages/ChatPage.tsx`, `components/npc/*`. `useChat` is not modified beyond its E0-Jobs migration to `lib/sse.ts`.
- **Dependencies:** E6.2, E0-Jobs.9 (`lib/sse.ts`), E0-WorldCore.10 (`panelSections.ts`, Entity panel), E0-UX.5 (EmptyState, Toast), E0-UX.6 (VisibilityBadge).
- **Size:** M

### Story E6.4: Copy a line into a journal draft; conversations never change Canon

As a GM,
I want to copy a good NPC line into a new journal draft that goes through normal review, knowing the conversation itself never touches the world or journal,
So that I keep what I want from improvisation and nothing more.

**Acceptance Criteria:**

**Given** an NPC reply
**When** the GM chooses "Copy to a journal draft" from the message menu
**Then** the journal composer opens with the passage prefilled as unsaved Shorthand, with a source line "From a conversation with {name}" and nothing persisted (draft-then-save)
**And** saving goes through the normal flow and E0-Journal writers, so extraction runs on it like any other GM entry.

**Given** any number of NPC Conversation turns
**When** a test runs a conversation that mentions a status change ("Veyra is dead now")
**Then** no row is written to `entities`, `entity_mentions`, `entity_changes`, `change_proposals` or `journal_entries`, and no Job is enqueued (asserted through DB row counts and the Jobs table)
**And** NPC chat sessions are not a retrieval source for the Chronicler, extraction or other NPCs (asserted with a canary in chat history).

- **Covers:** FR-38, FR-36 (other NPCs' Conversations never enter knowledge), NFR-7 (AI never changes Canon).
- **Technical notes:** AD-10 (only `apply_change` writes Canon; E6 never calls it), Draft-then-save convention. The composer prefill uses a router-state parameter on the existing `JournalInput.tsx` entry route (a one-line read; no change to its save path). Frontend plus one backend test.
- **Dependencies:** E6.3, E0-Journal.2.
- **Size:** S

### Story E6.5: Grant or hide what an NPC knows

As a GM,
I want to see an NPC's knowledge and mark entries or fields as Known, Granted or Hidden, including granting a Secret explicitly,
So that the NPC knows exactly what the story says it should.

**Acceptance Criteria:**

**Given** `PUT /api/npc/{entity_id}/knowledge/{ref_kind}/{ref_id}` with `{ref_field?, how: grant|hide|none}` (GM only)
**When** it is called
**Then** it upserts or deletes the `npc_knowledge` override and returns the row's new state and counts, and the next reply uses it (E6.2)
**And** granting a ref the GM ctx cannot see, or a ref in another Campaign, returns the uniform `404`. A Player gets `404` on every knowledge route (EV-4 probe).

**Given** the KnowledgeEditor (opened from the NPC page's Knowledge section and from the KnowledgeScope chip, in a `SlideOver`)
**When** it renders
**Then** it lists entries with a confirmed Mention (default "Knows"), plus any granted or hidden refs, each with a three-state SegmentedControl Knows (from Mention) · Granted · Hidden, and a search (Combobox) to add other entries or Entity fields
**And** suggested Mentions are never listed as knowledge, a Secret (`gm_notes` or a GM-only field) can only be Granted by an explicit choice labelled "Secret", and the footer says "Applies from the next reply."

**Given** the editor
**When** it is used by keyboard at 375 px
**Then** the SegmentedControl follows the WAI-ARIA radio pattern, changes are announced politely ("Hidden. 13 known, 3 hidden."), and the counts in the chat chip update without reload (query invalidation).

- **Covers:** FR-36 (GM views the list and grants or hides entries or fields, including Secrets; applies from the next reply), UX-DR28 (KnowledgeEditor three-state rows, Secrets grant-only explicitly), NFR-10.
- **Technical notes:** AD-11, AD-13. The route goes in `app/api/routes/npc_chat.py`. Frontend: `components/npc/KnowledgeEditor.tsx`, registered as a "Knowledge" section in `panelSections.ts` for NPCs. Uses E0-UX `SegmentedControl`, `Combobox`, `SlideOver` (`size="wide"`).
- **Dependencies:** E6.3, E0-UX.3 (SlideOver), E0-UX.4 (SegmentedControl, Combobox).
- **Size:** M

### Story E6.6: EV-3, measure whether NPCs leak what they shouldn't know

As the owner,
I want a repeatable eval of each NPC's answer rate on known facts and leak rate on unknown and GM-hidden facts,
So that "the NPC only knows what it should" is a measured claim (SM-3), not a hope.

**Acceptance Criteria:**

**Given** the committed demo seed (`seeds/demo_campaign.json`)
**When** `scripts/eval_npc_knowledge.py --campaign-id <uuid>` runs
**Then** for each of 3 NPCs it asks at least 8 probes about facts the NPC witnessed (in its knowledge set) and at least 8 about facts it never encountered, including same-Campaign hard negatives and one fact the GM has explicitly **hidden** (via `npc_knowledge` `hide`), each with a written answer key in the script, like `eval_retrieval.py`'s labelled set
**And** it runs through the real `npc_chat_service` path (knowledge set, scoped retrieval, persona, re-injected rule) with `llm_provider.capture()` on.

**Given** the replies
**When** they are scored
**Then** a keyword check pre-screens each reply for the key fact or a paraphrase list, and every pre-screen miss on an unknown probe and every hit on a known probe is listed for owner judgement against the written rubric in `docs/NPC_KNOWLEDGE_EVAL.md`
**And** the report gives **answer rate** on known facts, **leak rate** on unknown facts, leak count on GM-hidden facts, and how many unknown-probe replies carried "not from this NPC's memories".

**Given** the captured contexts
**When** the eval checks them
**Then** no unknown-probe key fact appears in any captured prompt. A fact in the prompt is a retrieval leak, reported separately from a model leak.

**Given** the run on the remote desktop against the real `lorekeeper` model (native Ollama 0.40.3)
**When** results are recorded in `docs/NPC_KNOWLEDGE_EVAL.md` (RETRIEVAL_EVAL format: method, set, table, verdict, how to reproduce)
**Then** they are compared with SM-3 (leak ≤ 5% overall, **0** on GM-hidden facts, answer ≥ 75%) and SM-C2 (no over-refusal)
**And** DS-4 second half (talk to the NPC tapped in E4.9 and watch it decline an out-of-knowledge question) is rehearsed offline and recorded in `docs/BENCHMARKS.md`.

- **Covers:** EV-3, SM-3, SM-C2, FR-36 (EV-3 target), FR-37 (refusal rate), DS-4 (second half), NFR-1.
- **Technical notes:** AD-21 (Evals; demo seed). The script goes in `src/backend/scripts/eval_npc_knowledge.py` and reuses the `eval_retrieval.py` structure. If the demo seed lacks the needed confirmed Mentions or a hidden fact, the script sets up its own overrides in a throwaway Campaign copy and never edits the committed seed (which E0-QA owns). A Player-ctx section is added by E6.7.
- **Dependencies:** E6.5, E0-QA.12 (demo seed, eval scaffold), E0-LLM.5 (capture hook).
- **Size:** M

### Story E6.7: Let Players talk to chosen NPCs, with Party-only knowledge

As a GM,
I want to switch on NPC Conversations for Players per NPC, with the NPC limited to Party content when a Player asks,
So that my players can interview NPCs between Sessions without any chance of spoilers.

**Acceptance Criteria:**

**Given** `PATCH /api/npc/{entity_id}/settings` `{player_chat_enabled, voice_notes}` (GM only), and the NPC page toggle "Players can talk to {name}"
**When** the GM hasn't enabled it
**Then** it is **off for every NPC by default**, and a Player calling any NPC conversation route for that NPC gets the uniform `404`.

**Given** a Party-visible NPC with `player_chat_enabled=true`
**When** a Player calls `GET /api/npc/available?campaign_id=`
**Then** that NPC is listed (Party projection only). This is the hook B4's Portal uses to show "Talk to {name}" on the Portal Entity page.
**And** an NPC that is GM-only, or has the toggle off, is absent, with no count or ordering hint.

**Given** a Player's NPC Conversation
**When** a reply is built
**Then** the persona comes from `access.project(npc, player_ctx)` (Party fields only; a hidden status renders as its unset value), with **no** `voice_notes`, no Secrets and no GM-only grants. Knowledge is `knowledge_set(db, player_ctx, npc)`, so only Mentions whose audience the Player can see, minus hides, plus grants the Player could see anyway. Retrieval uses the Player ctx (`party_*` columns, no glossary, no trace system prompt), and the gate class is `player_interactive`.
**And** each Player's history is separate (sessions owned by that user), and role demotion or removal archives them (`chat_sessions.archived_at`, E0-Access).

**Given** EV-4
**When** `tests/ev4/probes/npc_chat.py` runs the Player families
**Then** with canaries in a GM-only entry the NPC is Mentioned in, a GM-only grant, `voice_notes`, `gm_notes` and a GM-only field, none appears in any Player response, stored message, error or captured LLM context. A Player's request for another Player's session is a uniform `404`, and toggling the setting off closes the Player's open stream within 15 s.

**Given** EV-3 (E6.6)
**When** the eval is re-run with a Player ctx for the same 3 NPCs
**Then** a "Player" section in `docs/NPC_KNOWLEDGE_EVAL.md` reports 0 leaks of GM-only facts and the Player answer rate on Party-known facts.

- **Covers:** FR-39, FR-36 (Party-only knowledge), NFR-5, EV-3 (Player variant), EV-4 probes, UX-DR28 (Player NPC toggle).
- **Technical notes:** AD-12, AD-13 (`project`, AI context via ctx, demotion archive), AD-11 (`npc_settings`), AD-8 (gate class). The settings route goes in `app/api/routes/npc_chat.py`. The toggle is added to the Knowledge section. The Player chat surface reuses `/chat?npc=:id` with GM-only chrome (KnowledgeScope chip, voice notes) hidden by `useCampaignRole`. The data is already server-filtered, and B4 links to it from the Portal. Turning the toggle off publishes `campaign:{id}:events {domain:"npc_chat"}` so open Player streams close (via the E0-Access grant-change path where applicable). Cut order #3 (FR-39): this story can be cut whole.
- **Dependencies:** E6.6, E0-Access.4 (Party projection), E0-Access.3 (`audience_ctx`), E0-Access.7 (Player-scoped retrieval), E0-Access.12 (demotion archives chat sessions), E0-Access.8 (archived sessions never replayed), E0-Access.10 (stream close). B4's E7 Portal consumes `GET /api/npc/available` (a soft, later consumer, not a dependency).
- **Size:** M

## Epic E7: Player Portal

Players catch up between Sessions on their phones: a spoiler-safe wiki, their character's story, their own private journal, and a Chronicler limited to what they may see. GMs publish deliberately and can preview exactly what Players see.

**Covers:** FR-40, FR-41 (bulk controls and preview UI), FR-42, FR-43 (Player chat surface), FR-44 (PC link and "my character", D-4), FR-34 (Portal placement), NFR-5, NFR-6 (portal load), NFR-10, EV-4 probes, DS-3, UX-DR29, UX-DR30 (PC link). **Owns:**

- backend: `api/routes/portal.py`, `api/routes/player_journals.py`, and `services/portal_service.py` (new, E7-only helper module);
- frontend: `pages/PortalPage.tsx`, `pages/PortalJournalPage.tsx`, `pages/MyCharacterPage.tsx`, `components/portal/*` (including the `portalSections.ts` slot registry), `components/visibility/*` (bulk controls), and the preview data wiring in `lib/preview.ts`.

It owns no tables. **Access model:** this epic uses E0-Access's contracts (`require_campaign`, `audience_ctx`, `project`, `can_write`, `set_visibility`, `register_source`) and the Audience mapping of AD-12 exactly as defined there. It defines no access rules of its own. **Depends on:** E0-Access, E0-WorldCore, E0-Journal, E0-UX. Soft: E1 (E7.8 only), E3, E5, E9 and E10 (Portal slots). **Phase:** 2 (the wiki can start at Phase 0 exit).

### Story E7.1: Portal home for Players at 375 px

As Sam, a Player,
I want a Portal home on my phone with the latest story, my character and the world by type,
So that I can catch up between Sessions in under a minute.

**Acceptance Criteria:**

**Given** a Player ctx (`require_campaign("player")`) and `GET /api/portal/home?campaign_id=`
**When** the request succeeds
**Then** it returns the Party Narratives of the last 5 Sessions (title, `session_date ?? created_at`, Narrative excerpt of ≤ 280 chars, id), the linked PC summary or `null`, and the count of each Entity Type
**And** every element is built through `scoped_select`/`project` with the requester's ctx, so counts are computed only over rows visible to that ctx
**And** no response field contains Shorthand, `gm_notes`, `field_visibility` or a GM-only id
**And** a GM ctx gets the same shape for their own campaign, used only for preview (E7.7).

**Given** a non-member, or a Campaign id that doesn't exist
**When** they call the endpoint
**Then** both get `404 {"detail":"Not found"}` with identical bodies.

**Given** `pages/PortalPage.tsx` at `/portal`, registered in `lib/routes.ts` with `roles: ["player"]` and the Player nav entry "Portal"
**When** Sam opens it at 375 px
**Then** it shows, top to bottom: the slot sections registered in `components/portal/portalSections.ts` with `position: "top"` (the latest recap); "My character" (or "Your GM hasn't linked your character yet."); "Recent story" (entries by italic title and date, each opening `/journal/:id`); "World" (type chips with counts, linking to `/world?type=…`); and "Ask the Chronicler" (an input that opens `/chat` with the question)
**And** at `md` and up it uses two columns, with the story on the left and the character and recap on the right
**And** nothing scrolls horizontally at 375 px, and the PC-less and empty states use `EmptyState` with the EXPERIENCE.md copy
**And** no GM jargon appears ("Shorthand", "proposal", "Canon Note").

**Given** the Portal slot registry `portalSections.ts`, keyed `{ id, position, component, requiresRoute? }`
**When** E5 (recap, `RecapPlayer`), E3 (web), E10 (maps) or E9 (milestone) register a section
**Then** it renders in its position
**And** when no section is registered for a slot, the slot renders nothing (no heading, no gap).

**Given** a Player opens `/dashboard`
**When** the redirect table resolves
**Then** they land on `/portal` (one line added to E0-UX.8's table), and GMs still land on Dashboard.

**Given** the standing route ACs
**When** the route ships
**Then** `tests/ev4/probes/portal.py` covers `GET /api/portal/home` with the canary, counts, hidden-vs-nonexistent and Public-vs-Members-vs-Owner(other) families
**And** `nginx/locations.conf` has a line for `/api/portal/`.

**Given** `portalSections.ts` positions (Reconciliation RC-17)
**When** a section registers
**Then** `position` is one of `top` (above "My character"), `main` (after "World") or `bottom`, sections in one position render in registration order, and the registering epic owns its component. E3.4 (web), E5.6 (recap), E9.5 (milestone) and E10.4 (maps) each add one line here.

**Covers:** FR-40, FR-34 (Portal placement slot), NFR-10, UX-DR29 (home), EV-4.
**Technical notes:**
- AD-12, AD-13.
- `portal_service.home(db, ctx)` composes from E0-WorldCore's Entity queries and journal queries through access helpers. There is no `select(Model)` outside `app/access/` (CI-8).
- `react-query` key `["portal", campaignId, "home"]`.
- `useCurrentCampaign()` (E0-UX.7) supplies `campaignId`.
**Dependencies:** E0-Access.2, E0-Access.3, E0-Access.4, E0-WorldCore.5 (Entity API), E0-UX.5, E0-UX.8, E0-QA.11.
**Size:** M

### Story E7.2: Portal search and the read-only Share Link Portal

As a Player, or a friend with a read-only Share Link,
I want to search the Party world and browse the same Party content from a link,
So that I can find "that dwarf smith" quickly, and a shared link shows the group's story without spoilers.

**Acceptance Criteria:**

**Given** `GET /api/portal/search?campaign_id=&q=` for a Player ctx
**When** Sam searches "borin"
**Then** results list Party Entities matched by name or visible alias through `world_service.match_names(ctx, q)` and Party journal entries ranked on `party_tsv` only
**And** results, ranking and the total count are computed only over content visible to ctx, so a GM-only Entity named "Borin's brother" never changes the order, the count or the page size.

**Given** a read-only Share Link token
**When** a visitor calls `GET /api/portal/shared/{token}/home` or `GET /api/portal/shared/{token}/search?q=`
**Then** the ctx is the `anon` ctx from `access.share_ctx(token)` (E0-Access.4; Public Audience, AD-18), and the responses have the same shapes as the member routes, without `my_character`
**And** no Player Journal entry appears, not even ones shared with Members, because the Members Audience is wider than Public
**And** an expired, revoked or unknown token returns `404 {"detail":"Not found"}`.

**Given** `/shared/:token`
**When** the visitor opens it
**Then** it renders `PortalPage` in `mode="anon"`, with home, search, Entity list and journal reading, no "My character" section, no "My Journal" and no Chronicler box
**And** `pages/SharedCampaignPage.tsx` (E0a, shipped) becomes a thin wrapper that renders `<PortalPage mode="anon" token={token} />`
**And** the page works at 375 px with no horizontal scroll.

**Given** the search box on Portal home (`/` focuses it on desktop)
**When** results return
**Then** each result shows the type icon and name, or the italic entry title and date, and opens the Entity page or the entry
**And** "No matches" uses EmptyState wording, with no hint that hidden content exists.

**Given** the standing route ACs
**When** the routes ship
**Then** `tests/ev4/probes/portal.py` adds the counts-and-ranking family for search (GM-only near-duplicates don't change the Player's k) and the anon family for both shared routes
**And** `locations.conf` covers `/api/portal/shared/`.

**Covers:** FR-40 (search; the Share Link sees the same Party content without Player Journals or "my character"), FR-8, NFR-5, EV-4.
**Technical notes:**
- AD-13: uniqueness and ranking run only over visible rows.
- Keyword search only, with no embedding search on this route, so no AI rate limit applies; it uses the generic nginx zone.
- Token resolution reuses `access.share_ctx(token)` (E0-Access.4), including link expiry, and doesn't re-implement it.
**Dependencies:** E7.1, E0-Access.4, E0-Access.7, E0-WorldCore.5 (Entity API).
**Size:** M

### Story E7.3: Player Journals, private by default

As Sam,
I want to write my own journal entries in Kael's voice, private unless I choose to share them with the party,
So that I can keep my character's story without the GM's AI rewriting it or spoilers leaking either way.

**Acceptance Criteria:**

**Given** `api/routes/player_journals.py`
**When** a Player calls `POST /api/player-journals/` with `{campaign_id, title, body, session_date?}`
**Then** the entry is created through E0-Journal's `journal_service.create_journal_entry` (E0-Journal.2) with `kind=player`, `visibility=private`, the author's `user_id`, and the body stored as the Narrative (there is no Shorthand and no AI draft step)
**And** the response is the author's projection, with `visibility: "private"`.

**Given** an existing Player Journal entry
**When** its author calls `PATCH /api/player-journals/{id}` or `DELETE /api/player-journals/{id}`
**Then** the change goes through `update_journal_entry` or `delete_journal_entry`, gated by `can_write(ctx, obj)`
**And** another Player, a GM or an anon ctx trying the same write gets `404 {"detail":"Not found"}`. GMs can read but not edit Player Journals, per FR-6.

**Given** `PUT /api/player-journals/{id}/visibility` with `{value: "party" | "private"}` from the author
**When** it runs
**Then** it calls `set_visibility(db, ctx, ref, value)`, the only visibility writer
**And** `party` on a `kind=player` entry maps to the **Members** Audience (AD-12), so other Players and GMs see it and read-only Share Links never do.

**Given** `GET /api/player-journals/?campaign_id=&author=`
**When** different ctxs list
**Then** the author sees all of their own entries, other Players see only Members-shared entries, GMs see every Player Journal entry, and anon gets 404.

**Given** a Player Journal save or edit
**When** hooks fire (`entry_saved`, `entry_updated`)
**Then** no `extraction.run` or `continuity.check` Job is enqueued: the `jobs` table gains no row for that `journal_id`. This follows E1's handler rule for `kind=player`, which this story asserts in a test.

**Given** `pages/PortalJournalPage.tsx` at `/portal/journal` (Player nav "My Journal") and `components/portal/PlayerJournalComposer.tsx`
**When** Sam writes an entry
**Then** the composer has a title `Input`, a `Textarea` and a `SegmentedControl` "Private · Share with party" (Private selected), with a VisibilityBadge showing "Private" or "Shared"
**And** choosing "Share with party" confirms inline ("The party will see this entry. Share it?")
**And** the empty state reads "Write about the last Session in your character's voice. It's private until you share it."
**And** the page works at 375 px, by keyboard, with visible focus, and with inline errors that keep the typed text.

**Given** the standing ACs
**When** the routes ship
**Then** `tests/ev4/probes/player_journals.py` covers the canary in a Private entry (absent for other Players, anon and Owner(other)), Members-shared visible to Members and absent from anon, hidden-vs-nonexistent on GET, PATCH and DELETE, and the downgrade suite (party → private hides it on the next read)
**And** `locations.conf` has a line for `/api/player-journals/`.

**Covers:** FR-42 (write, edit, delete, Private default, Members-only sharing, no auto extraction), FR-6 (Player own-entry rules), FR-8, NFR-5, UX-DR29 (PlayerJournalComposer), EV-4.
**Technical notes:**
- AD-12 (`kind=player` → Members), AD-13 (`can_write`, `set_visibility`), AD-17 (journal writers only; `entry_hash` computed on the server, unique per `(campaign_id, user_id, entry_hash)`).
- `SourceKind.player_journal` already exists in `schemas/sources.py`.
**Dependencies:** E7.1, E0-Journal.1, E0-Journal.2, E0-Journal.3, E0-Access.6, E0-Access.9.
**Size:** L

### Story E7.4: Link a Player to their PC, and the "My character" page

As the Owner,
I want to link each Player to their PC,
So that Sam's "My character" page shows Kael's Party story and Sam's own journal.

**Acceptance Criteria:**

**Given** the Owner ctx (`require_campaign("owner")`) and `PUT /api/portal/pc-links` with `{campaign_id, entity_id, user_id | null, character_sheet_id?}`
**When** the Entity is a Character with `kind=pc` in that Campaign and the user is a Member with Role `player`
**Then** `entities.linked_user_id` is set through `world_service.apply_change` (a recorded `update_field` with the Owner as actor), and the optional `character_sheets.pc_entity_id` is set through the access-scoped writer
**And** linking a user who already has a PC in that Campaign moves the link and records both changes
**And** `user_id: null` unlinks
**And** a non-Owner, a non-PC Entity or a non-Player user gets `404 {"detail":"Not found"}`.

**Given** `GET /api/portal/my-character?campaign_id=` for a linked Player
**When** it returns
**Then** it holds the PC's Party projection (name, aliases, status, description; hidden fields render as unset), the PC's confirmed Mentions whose Mention Audience (AD-12 formula) the Player can see (newest first, 20 per page, each with quote and italic entry title), and the Player's own Player Journal entries, both Private and Shared (newest first, 20 per page)
**And** an unlinked Player gets `{linked: false}`, and an anon ctx gets 404.

**Given** `pages/MyCharacterPage.tsx` at `/portal/character`
**When** Sam opens it
**Then** he sees Kael's header (`entity-title`, StatusBadge), "Kael's story so far" (Mentions as `mention-quote` blocks linking to the entry at the highlighted quote) and "My journal" (with a "Write an entry" button that opens the composer)
**And** with no link it shows "Your GM hasn't linked your character yet." while the rest of the Portal keeps working
**And** Mentions and journal lists paginate in 20s (no infinite scroll), and the page works at 375 px.

**Given** Sharing › Members (`pages/SharingPage.tsx`, where E0-Access.12 owns the Role controls)
**When** the Owner views a Player row
**Then** a "Character" cell, `components/portal/MemberPcLinkCell.tsx` added as one cell, offers a Combobox of PC Characters plus "No character"
**And** the change saves immediately and shows the toast "Linked Sam to *Kael*"
**And** changing a Member from Co-GM to Player in the same row still shows E0-Access's notice "Their NPC Conversations and chat history in this Campaign will be archived." (verified here, owned there).

**Given** the standing ACs
**When** the routes ship
**Then** `tests/ev4/probes/portal.py` covers `my-character`: a GM-only Mention of Kael (a Shorthand-sourced quote, and one in a GM-only entry) is absent; another Player's Private journal is absent; and the `pc-links` write as a Player or anon returns 404.

**Covers:** FR-44 (PC link and "my character" consequence, D-4), FR-40 (PC on the Portal), UX-DR29 (My character), UX-DR30 (PC link), EV-4.
**Technical notes:**
- AD-10: `linked_user_id` lives on `entities`, so the write goes through `apply_change`.
- AD-12: the Mention formula with `source_field`.
- B3 contract: only confirmed Mentions count for "my character".
- `can_write` already lets a Player edit the sheet whose `pc_entity_id.linked_user_id` is them, so this story has no new write rule.
**Dependencies:** E7.3, E0-WorldCore.3, E0-Access.4, E0-Access.6, E0-Access.12.
**Size:** L

### Story E7.5: Player Chronicler limited to what the Player may see

As Sam,
I want to ask the Chronicler about the Campaign and get cited answers from what I'm allowed to see, plus my own private notes,
So that I can recall details without ever being shown, or hinted at, a GM secret.

**Acceptance Criteria:**

**Given** `services/portal_service.py` registering `retrieval_service.register_source("player_journal", fn)`
**When** a Player ctx retrieves
**Then** candidates include the Player's own Private Player Journal entries and Members-shared Player Journal entries, through `party_tsv`/`party_embedding` and the access-scoped query
**And** a GM ctx sees all Player Journal entries, and an anon ctx none
**And** sources resolve only through `access.resolve_sources` as `ResolvedSource` with `kind=player_journal`.

**Given** Sam asks "who hired us in Karak Dun?" on `/chat` (blocking or streaming)
**When** the reply returns
**Then** it cites Party entries by italic title and carries `grounded: true`
**And** the reply holds no retrieval trace, system prompt or glossary (as E0-Access.8 guarantees, re-asserted here for the Player surface)
**And** the LLM call uses the `player_interactive` gate class (`llm_slot`, E0-LLM.2).

**Given** Sam asks "is anyone in the party a traitor?", and the traitor fact is GM-only
**When** the reply returns
**Then** it is labelled "not from your journal" (`grounded: false`)
**And** the reply text, sources, timing class and response shape match those of a question about a fact that doesn't exist at all (the hidden-vs-nonexistent family)
**And** the captured LLM context (the EV-4 capture hook) contains no GM-only canary.

**Given** `pages/ChatPage.tsx` with `useEffectiveRole() === "player"`
**When** it renders
**Then** the retrieval-debug and trace panels are absent, the sources disclosure lists only `ResolvedSource` titles and quotes, and the "not from your journal" label is text (screen readers hear it)
**And** the Portal "Ask the Chronicler" box (E7.1) opens `/chat` with the question pre-filled and the current Campaign selected
**And** the page works at 375 px.

**Given** the standing ACs
**When** the story ships
**Then** `tests/ev4/probes/player_chat.py` runs the captured-LLM-context family for Player, anon (if chat is reachable from a Share Link; otherwise the reasoned exemption "chat requires a Member") and Owner(other), using a Private-journal canary of Player A asked by Player B
**And** the existing `/api/chat/` and `/api/chat/stream` keep their `@limiter.limit` keyed `user_or_ip`.

**Covers:** FR-43, FR-8, NFR-5, NFR-7 (grounded labels), EV-4.
**Technical notes:**
- AD-13 (AI context uses `party_*` columns; no glossary or trace for non-GMs).
- `chat.py` and `chat_service` are E0-Access's. This story adds only the `player_journal` source registration and the frontend Player mode. E6 later adds the NPC mode in `ChatPage.tsx`.
**Dependencies:** E7.3, E0-Access.7, E0-Access.8, E0-LLM.1 (typed errors), E0-LLM.2 (`llm_slot`).
**Size:** M

### Story E7.6: GM bulk Visibility from list views, with derived-content notice

As Dana, the GM,
I want to publish or hide many records at once from a list, and be told what derived content that affects,
So that I can publish 120 migrated Entities in one deliberate step and trust that recaps and exports won't leak.

**Acceptance Criteria:**

**Given** E0-Access's bulk route `POST /api/campaigns/{campaign_id}/visibility` (E0-Access.9, body `{items: [{kind, id, field?}], value}`, ≤ 500 items, all-or-nothing, response `{updated: n}`)
**When** the bulk controls apply a change
**Then** they call that route through `services/api/visibility.ts` and define no backend route of their own (B1-D6)
**And** a selection of more than 500 items is split into batches of 500 client-side, and the confirmation states the total
**And** a 404 for any item (deleted meanwhile, or another Campaign) shows the inline error "Some of these changed since you selected them. Refresh and try again." with nothing applied.

**Given** `components/visibility/BulkVisibilityBar.tsx`, a selection-mode bar showing the count of selected items, "Set visibility ▾" (Party · GM only) and Cancel
**When** Dana chooses Party for 24 selected items
**Then** it confirms inline "Make 24 entries visible to players?" (the noun follows the list), and GM only applies without confirmation
**And** after apply, a toast reads "24 entries now visible to players" (the count is the route's `updated`)
**And** after a change to GM only, the toast adds the derived notice "Recaps, exports and audio made from these are hidden from players until they're regenerated." The server enforces this (`set_visibility` marks `derived_sources` dependents stale through E0-Jobs' stale marker), and the toast doesn't claim specific counts, because the route doesn't return them.

**Given** the History list (`pages/HistoryPage.tsx`)
**When** a GM enters "Select" mode
**Then** each row gets a checkbox, the BulkVisibilityBar appears, and the selection works by keyboard (Space toggles, Shift+click selects a range)
**And** each row shows its VisibilityBadge (GM view).

**Given** E0-WorldCore's World hub selection mode (E0-WorldCore.10)
**When** this story lands
**Then** `BulkVisibilityBar` is exported for reuse there, and the hub's own per-item behaviour isn't changed by this story.

**Given** a Party → GM change
**When** a Player reads the record on their next request
**Then** it is absent (applies on next read). This is tested through the EV-4 downgrade suite for `journal_entries` and `entities` refs.

**Given** this story adds no route
**When** EV-4 runs
**Then** the bulk route keeps its E0-Access.9 probe, and this story adds downgrade-suite cases for bulk changes that mix `journal_entries` and `entities` items.

**Covers:** FR-41 (bulk from list views; changes apply on the next read; derived content is invalidated or hidden), NFR-5, UX-DR19 (bulk confirm copy, shared with E0-WorldCore), EV-4.
**Technical notes:**
- AD-13: `set_visibility` is the only writer, reached here only through E0-Access's bulk route. For Canon tables it goes through `apply_change`.
- AD-14: derived dependents are marked stale and 404 to non-GMs.
- Inserting the selection mode into `HistoryPage.tsx` is a contained component mount.
**Dependencies:** E7.1, E0-Access.9, E0-WorldCore.10 (World hub selection mode), E0-UX.5, E0-UX.6.
**Size:** M

### Story E7.7: Preview as Player through the real read path

As Dana,
I want to see the app exactly as a Player sees it, on every screen, until I choose to leave,
So that I can check that the traitor stays hidden before I invite anyone.

**Acceptance Criteria:**

**Given** preview is active for Campaign C (`usePreview().enter(C)`, from the CampaignSwitcher or an Entity overflow "Preview this page as a Player")
**When** the frontend makes any API request or SSE connection scoped to C
**Then** `lib/preview.ts` adds the request header `X-Lorekeeper-Preview: member` through the axios interceptor in `services/api.ts` and through `lib/sse.ts`
**And** the server serves the request with the reduced ctx `audience_ctx(C, member)` that E0-Access's `require_campaign` builds from a GM ctx carrying that header. This story doesn't define how the downgrade works.
**And** a non-GM sending the header gets no change in privilege, because the header can only narrow.

**Given** entering or exiting preview
**When** the mode changes
**Then** the react-query cache is cleared (`queryClient.clear()`), so no GM data renders in preview and no preview data lingers afterwards
**And** the nav switches to the Player set (`useEffectiveRole() === "player"`), and the Entity page that was open re-renders in place.

**Given** preview is active
**When** Dana navigates World, Web, Maps, Portal, an Entity page or an entry
**Then** the PreviewBanner (E0-UX.6) shows on every screen, `Esc` never exits, and only "Exit preview" does
**And** every control using `useWriteGuard()` is disabled with the tooltip "Preview is read-only"
**And** any write that reaches the server still fails closed with `404 {"detail":"Not found"}`, because the generic member ctx owns nothing.

**Given** a GM-only Entity, a GM-only Relationship between two Party Entities and a GM-only Secret field on a Party Entity
**When** Dana previews `/world` and that Entity's page
**Then** the GM-only Entity is absent from lists, counts and search, the Secret field is not rendered, and no gap or placeholder shows where it was
**And** "My character" in preview shows "Previewing as a generic Player — no character is linked." (D-6(4)).

**Given** the standing ACs
**When** the story ships
**Then** an EV-4 probe asserts that a GM request with the preview header returns byte-identical bodies to a real Player request with no PC, for `GET /api/portal/home`, the Entity list and the graph (once E3 lands).

**Covers:** FR-41 (preview through the same filtered read path), NFR-5, UX-DR11 (PreviewBanner wiring), UX-DR29, EV-4.
**Technical notes:**
- AD-13: `audience_ctx` is the only reduced-ctx constructor.
- The header name and the GM-only narrowing are the cross-batch contract this batch assumes from E0-Access (see the closing summary).
**Dependencies:** E7.1, E0-UX.6, E0-UX.7, E0-Access.2, E0-Access.3 (`audience_ctx`), E0-Access.4 (`project`), E0-Jobs.9 (`lib/sse.ts`).
**Size:** M

### Story E7.8: GM-triggered extraction of a Player Journal entry

As Dana,
I want to turn a Player's journal entry into proposed world changes only when I choose to,
So that good Player notes can enrich the world without the Player's private writing becoming Canon on its own.

**Acceptance Criteria:**

**Given** a GM ctx and `POST /api/player-journals/{id}/extract`
**When** Dana triggers it on a Player Journal entry she can read
**Then** it enqueues E1's `extraction.run` through `enqueue(db, ctx, "extraction.run", {journal_id, origin: "promotion"}, idempotency_key="extraction.run:{journal_id}:{entry_hash}")`
**And** the response returns the Job id in < 1 s (FR-1)
**And** repeating the call on unchanged content returns the same active Job rather than a duplicate.

**Given** the extraction finishes
**When** proposals are written
**Then** they land in a `proposal_batches` row with `origin=promotion` and appear in Dana's Review Checklist and Reviews queue (E1.5, E1.7), never to Players
**And** every proposal defaults to Visibility GM-only, whatever the entry's sharing, so Private or Members-only words never become Public Canon without Dana choosing Party.

**Given** the GM views a Player Journal entry (`pages/EntryDetailPage.tsx` for a `kind=player` entry)
**When** the entry renders
**Then** `components/portal/PlayerJournalGMActions.tsx` (one mount) shows "Player journal · Sam", the Private or Shared badge, and a button "Find world changes" with the Job's progress (stage and ETA through `useJobStream`)
**And** Players never see this control.

**Given** a Player, anon or Owner(other)
**When** they call the extract route
**Then** they get `404 {"detail":"Not found"}`, covered in `tests/ev4/probes/player_journals.py`
**And** the route has an anchored-regex `locations.conf` entry and `@limiter.limit` keyed `user_or_ip`, because it starts AI work.

**Covers:** FR-42 (extraction only when a GM triggers it; proposals go to the GM's checklist), FR-1, EV-4.
**Technical notes:**
- B3 contract: `proposal_batches.origin=promotion`, with the `extraction.run` idempotency key.
- AD-2: `enqueue` only.
- AD-11.
- This story is the only E7 story that needs E1. If E1 slips, it is cut alone and the rest of E7 ships.
**Dependencies:** E7.3, E1.3 (`extraction.run` with `origin: "promotion"`, RC-16), E1.4 (proposals API), E1.7 (Reviews queue), E0-Jobs.2, E0-Jobs.7, E0-Jobs.9 (`useJobStream`).
**Size:** S

### Story E7.9: DS-3 run, the EV-4 zero-leak gate for the Portal, and the portal load benchmark

As the Owner preparing the capstone demo,
I want the Portal proven spoiler-safe and fast on the Reference Box,
So that DS-3 can be shown live with 0 leaks and a warm load ≤ 2 s.

**Acceptance Criteria:**

**Given** the EV-4 harness (E0-QA.11) and its hard gate (E0-QA.14) enumerating `app.routes` and the nginx locations
**When** CI runs after E7 merges
**Then** every route under `/api/portal/` and `/api/player-journals/` has a probe or a reasoned exemption, and an uncovered route fails CI
**And** the families canary, hidden vs nonexistent, hidden vs unset field, counts and ranking, captured LLM context, Public vs Members vs Owner(other), and the downgrade suite all report 0 leaks for these routes.

**Given** the demo seed (`seeds/demo_campaign.json` via `scripts/seed_demo.py`)
**When** this story appends its fixtures
**Then** the seed has: a GM-only "traitor" Character with a canary string; a Party PC "Kael" linked to the Player "Sam"; a Private and a Shared Player Journal entry by Sam; a Private entry by a second Player; and a GM-only Mention of Kael from Shorthand.

**Given** `scripts/demo_ds3.md` (a manual runbook) and an automated `tests/ev4/test_ds3.py`
**When** DS-3 runs offline (NFR-1)
**Then** Sam browses the wiki, "My character", the graph (if E3 has landed) and the Map (if E10 has landed), and asks the Chronicler about the traitor, which returns "not from your journal"
**And** EV-4 is run live against the real local model before release, with the result recorded in `docs/SPOILER_EVAL.md` (0 leaks).

**Given** the EV-5 suite (E0-QA.15)
**When** `GET /api/portal/home` and the `/portal` first contentful render are measured warm on the Reference Box (16 GB, CPU-only) with the demo seed
**Then** `docs/BENCHMARKS.md` gets the row "Portal page load (warm) ≤ 2 s", with p50 and p95 over 20 loads
**And** a miss fails this story's acceptance and is reported against NFR-6.

**Given** a 375 px audit of the Portal views (home, Entity page as Player, journal entry, recap card when present, Map when present)
**When** it is done
**Then** none scrolls horizontally, the results are listed in the PR, and defects in views other epics own are filed against those epics.

**Covers:** NFR-5 (EV-4 hard gate for E7), NFR-6 (portal load row), FR-40 (375 px check), DS-3, EV-4, EV-5.
**Technical notes:**
- AD-21: the harness and seed format belong to E0-QA, and this story only appends probes and fixtures (shared append points: `tests/ev4/probes/`, the seed).
**Dependencies:** E7.1, E7.2, E7.3, E7.4, E7.5, E7.6, E7.7, E0-QA.11, E0-QA.12 (demo seed), E0-QA.14, E0-QA.15 (EV-5). Soft: E7.8 (its probe joins when it ships).
**Size:** M

## Epic E8: Campaign Chronicle export

At the end of an arc, the group gets the Campaign as a well-typeset PDF and a valid EPUB, in a GM edition or a spoiler-safe Player edition. Both formats come from one Jinja2 HTML source: WeasyPrint renders the PDF, and a stdlib `zipfile` plus Jinja2 builder produces the EPUB3. **EbookLib is not used** (AGPL). The LGPL `fpdf2` dependency and its Latin-1 `_s()` sanitizer are removed. The export covers every Member's entries (fixing the owner-only bug at `api/routes/campaigns.py:119-156`) and is always built through the visibility layer. A Player-audience export contains zero GM-only content (EV-4).

### Story E8.1: Book model built through the visibility layer

As a GM or Player,
I want the Chronicle's content assembled from exactly what my edition's audience may see, across every Member's entries,
So that the Player edition is safe to share and the book includes everyone's writing, not just the Owner's.

**Acceptance Criteria:**

**Given** `services/chronicle_service.py`
**When** `build_book(db, ctx, options) -> Book` is called
**Then** it returns a cover (Campaign name, genre, first and last Session date), chapters in Session order (`session_date ?? created_at::date`), each holding its entries by `created_at`, and, when `options.appendix` is set and Entities exist, an appendix grouped by Entity Type
**And** every query uses `scoped_select(Model, ctx)` and every Entity goes through `project(obj, ctx)`, so the Party rendering of a hidden field is the registry's "unset" rendering (for example `status → "unknown"`).

**Given** a Campaign with entries from three Members (Owner, a Co-GM and a Player with a shared Player Journal)
**When** the GM edition is built with `include_player_journals=true`
**Then** all three Members' entries appear in their Sessions' chapters (FR-10)
**And** with `include_player_journals=false`, `kind=player` entries are left out.

**Given** a Player edition
**When** it is built
**Then** `ctx` is `audience_ctx(campaign_id, member)`, whether a GM or a Player requested it, and `options` cannot widen it: `shorthand=true` or `secrets=true` with `edition=player` raises `ValueError` before any query.

**Given** the EV-4 canary seed (canaries in Shorthand, `gm_notes`, a GM-only entry, a GM-only Entity, a GM-only field on a Party Entity, a GM-only Relationship and another Player's Private journal entry)
**When** the Player edition `Book` is rendered to HTML with `render_html(book)`
**Then** the HTML contains zero canary strings, zero GM-only Entity names and zero ids of GM-only records, and the appendix entry counts equal the Party-only counts.

**Given** a GM edition with `shorthand=true` and `secrets=true`
**When** it is built with the GM ctx
**Then** Shorthand renders under each entry as a labelled "Notes" block, and `gm_notes` and GM-only fields render in the appendix under "Secrets". With both false (the default), neither appears.

**Given** an entry whose Narrative contains `<script>`, `&` and HTML-like text
**When** it renders
**Then** Jinja autoescaping outputs it as text, and Narrative paragraphs become `<p>` elements.

**Given** the legacy `GET /api/campaigns/{id}/export?format=markdown`
**When** it is called after this story
**Then** it delegates to `chronicle_service.render_markdown(build_book(db, ctx, options))` with the caller's ctx. A Player gets the Party content of all Members, never Shorthand (today's builder prints Shorthand, `export_service.py:27`).

**Covers:** FR-45 (content), FR-48, FR-10 (export part), NFR-5, AR-13.

**Technical notes:**
- The templates are `templates/chronicle/book.html.j2`, `chapter.html.j2`, `appendix.html.j2` and `chronicle.css` (the one source both formats use).
- `Book`, `Chapter`, `EntryBlock` and `AppendixSection` are frozen dataclasses that store the `SourceRef` of every included row, so E8.4 can write `derived_sources`.
- The appendix uses `domain/entity_types.py` for the type order and status labels.
- This story touches only the body of the export handler in `campaigns.py` (E0-Access.13 owns the route's access scope). See Decision B6-6.
- The FR-10 regression test is `tests/test_chronicle_book.py::test_all_members_included`.

**Dependencies:** E0-Access.3 (`audience_ctx`, `scoped_select`), E0-Access.4 (`project`), E0-Access.13 (FR-10 export scope), E0-WorldCore.1, E0-WorldCore.5, E0-QA.11 (canary seed).

**Size:** M

### Story E8.2: WeasyPrint PDF with full Unicode, and fpdf2 removed

As a GM,
I want the Chronicle PDF typeset with a cover, a table of contents with page numbers, running headers and fonts that render every character,
So that "Ælfrida", "Ōkami", em dashes and curly quotes print correctly instead of as "?".

**Acceptance Criteria:**

**Given** a `Book`
**When** `chronicle_service.render_pdf(book) -> bytes` runs through WeasyPrint
**Then** the PDF has a cover page, a TOC whose entries show page numbers through `target-counter(attr(href), page)`, one chapter per Session starting on a new page, the Session date as a running header through `string-set`, and page numbers in the `@page` margin boxes.

**Given** an entry containing "Ælfrida", "Ōkami", "—", "“quotes”", "Þórr" and "Ведьма"
**When** it renders
**Then** text extracted from the PDF (pypdf, a test-only dependency) contains each string exactly, no `?` replaces any of them, and every font used is embedded.

**Given** the bundled fonts in `assets/fonts/`
**When** the PDF renders
**Then** body text uses an OFL serif covering Latin, Latin Extended, Greek and Cyrillic, chapter titles use Cinzel (OFL), and the fallback chain lists the bundled Noto Serif before any system font. Each font's `OFL.txt` ships next to it.

**Given** `src/backend/requirements.txt`
**When** this story merges
**Then** `fpdf2` is removed, `export_service.build_campaign_pdf` and `_s()` are deleted, the `fpdf2` exception in `.github/license-policy.toml` is removed, and `GET /api/campaigns/{id}/export?format=pdf` returns `render_pdf(build_book(db, ctx, options))` (synchronously, for compatibility only; the app UI moves to the Job in E8.4 and E8.5).

**Given** the web and worker images
**When** they are built
**Then** they install WeasyPrint's apt libraries (Pango, PangoFT2, HarfBuzz, fontconfig) dynamically linked, the AD-22 image scan passes, and a CI smoke test renders the Unicode fixture in the built worker image.

**Standing ACs:** SA-Dep (`licenses/register.yaml`: WeasyPrint (BSD-3-Clause), its Python dependencies (tinycss2, cssselect2, pydyf, fonttools, Pillow), the apt `libpango-1.0-0`, `libpangoft2-1.0-0`, `libharfbuzz0b` and `fontconfig` entries under the dynamic-LGPL system-library allowlist, each bundled font (OFL-1.1), and `pypdf` (BSD-3-Clause, test-only); the `fpdf2` entry is removed).

**Covers:** FR-45 (PDF format, cover, TOC), FR-46, NFR-4, AR-22, UX-DR31 (Chronicle typography).

**Technical notes:** WeasyPrint's version is pinned per the spine Stack table. `chronicle.css` uses `@page { @top-center { content: string(session) } @bottom-center { content: counter(page) } }`. Rendering runs in the worker from E8.4 onward (worker 1g limit, AD-7). This story records the PDF render time for the demo seed. The 100-entry row is E8.4's.

**Dependencies:** E8.1, E0-QA.7.

**Size:** M

### Story E8.3: EPUB3 builder on zipfile and Jinja2, validated by EPUBCheck

As a Player reading on an e-reader,
I want the Chronicle as a valid EPUB3 with working navigation,
So that the book opens in any reader and I can jump between Sessions.

**Acceptance Criteria:**

**Given** a `Book`
**When** `chronicle_epub.render_epub(book) -> bytes` runs
**Then** it writes, with stdlib `zipfile` only, `mimetype` as the first entry (`ZIP_STORED`, no extra field, content `application/epub+zip`), `META-INF/container.xml`, `OEBPS/content.opf` (EPUB 3.3: `dc:identifier` as a stable `urn:uuid` per campaign and edition, `dc:title`, `dc:language` defaulting to `en`, `dcterms:modified`), `OEBPS/nav.xhtml` (a toc nav with one item per chapter, the appendix, and landmarks), one XHTML file per chapter rendered from the same `chapter.html.j2` partials in XHTML mode, `chronicle.css` and the embedded fonts declared in the manifest.

**Given** every generated XHTML file
**When** the test parses it with `xml.etree.ElementTree`
**Then** it is well-formed, Narrative text is XML-escaped, and the FR-46 Unicode fixture strings appear unchanged.

**Given** CI
**When** the `epubcheck` job runs EPUBCheck 5.x (Java, in a CI container) on EPUBs generated from the demo seed (both editions) and the Unicode fixture
**Then** it reports 0 errors and 0 fatal errors, and the build fails otherwise (FR-45). Warnings are printed and listed in the job summary.

**Given** any requirements file, lock file or image
**When** the licence and import checks run
**Then** `ebooklib` is absent: `tests/test_no_ebooklib.py` fails if it appears in `requirements*.txt`, and the strict licence gate would reject it as AGPL in any case.

**Standing ACs:** SA-Dep (EPUBCheck, BSD-3-Clause, `scope: ci-only`, in `licenses/register.yaml`).

**Covers:** FR-45 (EPUB format and navigation, EPUBCheck), FR-46, NFR-4.

**Technical notes:** `services/chronicle_epub.py` sits beside `chronicle_service.py` (E8-owned). Templates `templates/chronicle/epub/{content.opf.j2,nav.xhtml.j2,container.xml.j2}`. No cover image is needed (the cover is XHTML). Only the TOC is generated, with no `toc.ncx`, because EPUB3 doesn't need it. The CI job goes in `.github/workflows/` as one added job in the backend workflow (an E0-QA append point).

**Dependencies:** E8.1, E0-QA.6.

**Size:** M

### Story E8.4: Chronicle export Job, editions, download and staleness

As a GM (or a Player, for the Player edition),
I want to start an export, leave the page, and download the PDF and EPUB when the Job finishes,
So that a 100-entry Campaign exports without blocking anything, and an out-of-date book is flagged.

**Acceptance Criteria:**

**Given** a GM
**When** they call `POST /api/chronicle/exports` with `{campaign_id, edition: "player"|"gm", formats: ["pdf","epub"], include: {appendix, player_journals, shorthand, secrets}}`
**Then** the response is `202 {job_id}` in under 1 s, and the Job `chronicle.export` builds the `Book` once, renders the chosen formats and stores each as a `stored_files` row of kind `chronicle_pdf` or `chronicle_epub`, with `derived_sources` rows for every included entry, Entity and field ref.

**Given** a Player
**When** they request `edition: "gm"`
**Then** the response is `404 {"detail":"Not found"}`
**And** a Player edition request succeeds and is built with `audience_ctx(campaign_id, member)`, never the requester's own wider ctx (so their own Private entries are not included).

**Given** `edition: "player"` with `include.shorthand` or `include.secrets` set to true
**When** the request is validated
**Then** it is rejected with 422 for every role.

**Given** an export identical in edition, options and content version to a finished, non-stale one
**When** it is requested again
**Then** the same files are returned without re-rendering (cache key `sha256(campaign_id|edition|options|content_version|audience)`).

**Given** finished exports
**When** a ctx calls `GET /api/chronicle/exports?campaign_id=`
**Then** it lists exports whose derived Audience the ctx can see (GM: all; Player: Player editions), each with date, edition, formats, file ids and `state ∈ {ready, out_of_date}`
**And** downloads go only through `GET /api/files/{id}`.

**Given** a ready Player edition
**When** a GM moves an included entry or field to GM-only through `set_visibility`
**Then** the export's files are marked stale, the list shows `out_of_date` with `reason: "visibility_changed"` to the GM, and Players get 404 for those files (downgrade suite, FR-41).

**Given** an entry included in an export is edited after it
**When** the list is read
**Then** the export shows `out_of_date` with `reason: "content_changed"`, and its files remain downloadable.

**Given** EV-4
**When** `tests/ev4/probes/chronicle.py` runs against the canary seed
**Then** the Player edition PDF (text extracted) and EPUB (every XHTML file unzipped) contain zero canary strings and zero GM-only names or ids, its page and entry counts equal the Party-only counts, every chronicle route returns 404 to an anon Share Link ctx, and Job events for GM-edition Jobs never reach a Player stream.

**Given** the Reference Box CPU-only
**When** a 100-entry Campaign exports in both formats
**Then** the time is ≤ 3 min (NFR-6), the worker peak RSS stays under its 1g limit, and both are recorded in `docs/BENCHMARKS.md`.

**Standing ACs:** SA-Route (`tests/ev4/probes/chronicle.py`; `locations.conf` generic-zone lines for `/api/chronicle/`; `@limiter.limit` on POST keyed `user_or_ip`). SA-Job (`chronicle.export`: `queue=interactive`, `timeout_s=900`, `resources={cpu_heavy}`, `live_safe=False`, `result_audience=` the edition's Audience (GM or Members); idempotency key `chronicle.export:{campaign_id}:{edition}:{options_hash}:{content_version}`, where `content_version = sha256` of the sorted `(ref, updated_at)` of included rows plus `access_epoch`). SA-Bench (NFR-6 Chronicle row).

**Covers:** FR-45 (Player may export Player edition), FR-47, FR-48, FR-41 (Chronicle staleness), FR-10, NFR-5, NFR-6, AR-14, EV-4.

**Technical notes:** `jobs/chronicle.py` sets the stages "Collecting entries", "Typesetting PDF", "Building EPUB" and "Saving". `api/routes/chronicle.py` and `schemas/chronicle.py` hold the routes and schemas. Register `chronicle_pdf` and `chronicle_epub` in `DERIVED_REGISTRY`. Map images in the book are deferred (Decision B6-9).

**Dependencies:** E8.1, E8.2, E8.3, E0-Jobs.2, E0-Jobs.3, E0-Jobs.7, E0-Jobs.8, E0-Access.3, E0-Access.9, E0-Access.10, E0-QA.11, E0-QA.15.

**Size:** L

### Story E8.5: Chronicle export panel on Keepsakes

As a GM,
I want an export panel where I pick the edition, formats and extras, see a summary, and find past exports with their state,
So that I can produce the right book without guessing what's inside it.

**Acceptance Criteria:**

**Given** no `/keepsakes` route exists yet (E5.2 has not landed)
**When** this story merges
**Then** it creates the Keepsakes page shell with the same route-mapped Tabs and `NAV_GROUPS` line as E5.2 specifies, with "Previously on…" showing an EmptyState. If the shell exists, it only fills the "Chronicle" tab.

**Given** the Chronicle tab as a GM
**When** it opens
**Then** `ChronicleExportPanel` shows an edition SegmentedControl (Player edition by default, with "Party content only. Safe to share with your group."; GM edition with a gm badge), PDF and EPUB checkboxes (both on), and include toggles: Entity appendix (on when Entities exist), shared Player Journal entries, and, for the GM edition only, Shorthand and Secrets (both off, with gm badges).

**Given** the chosen options
**When** they change
**Then** a summary line such as "38 Sessions · 112 entries · 214 entities · about 180 pages" updates from `GET /api/chronicle/preview?campaign_id=&edition=`, which returns counts computed through the same ctx as the export, with a cover preview thumbnail.

**Given** Export is pressed
**When** the Job runs
**Then** the panel shows the Job's stage, bar and ETA from `useJobStream`, the user can leave (the Job tray tracks it), and on completion "Download PDF" and "Download EPUB" appear.

**Given** past exports
**When** the list renders
**Then** each row shows the date, edition and formats, and an out-of-date row shows "Out of date — visibility changed since" (or "Entries changed since") with Re-export.

**Given** a Player
**When** they open the tab
**Then** only the Player edition is offered, with no edition control and no Shorthand or Secrets toggles.

**Given** no exports, or a failed Job
**When** the tab renders
**Then** it shows "No exports yet." or the failure reason with Retry (EXPERIENCE.md "Per surface").

**Standing ACs:** SA-UI. The PreviewBanner read-only flag disables Export. The legacy export button that calls `api.exportCampaign` (`services/api.ts:83`) is replaced by a link to `/keepsakes/chronicle`. SA-Route for `GET /api/chronicle/preview` (probe: Party counts are identical with and without GM-only canary rows).

**Covers:** FR-45, FR-47 (UI), FR-48 (UI), NFR-10, UX-DR31, DS-5 (book part).

**Technical notes:** `components/chronicle/ChronicleExportPanel.tsx`, `services/api/chronicle.ts`, `types/chronicle.ts` and `hooks/useChronicle.ts`. The page estimate uses about 600 words per page, computed on the server. DS-5 step 4 (Player edition PDF and EPUB with shared Player Journals) runs offline and is recorded in `docs/BENCHMARKS.md`.

**Dependencies:** E8.4, E0-UX.4, E0-UX.5, E0-UX.6, E0-UX.8, E0-Jobs.9, E0-Jobs.10.

**Size:** M

## Epic E9: Milestones and stats

Members see the Campaign's story in numbers and celebrate Milestones and opt-in Achievements. They are never nagged, and they are never shown counts that hint at hidden content. Every stat is computed for the recipient's ctx through the visibility layer and covers every Member's entries (FR-10). Streaks count **Sessions played, not days**. They are off by default, can be hidden, and include a one-Session automatic grace. There is no loss messaging.

### Story E9.1: Campaign stats API computed per recipient

As a Member,
I want Campaign stats (Sessions played, entries per Session, contributions per Member, most-mentioned Entities and Quest completion rate) computed from what I'm allowed to see,
So that I can enjoy the story in numbers without the numbers spoiling anything.

**Acceptance Criteria:**

**Given** `GET /api/stats?campaign_id=`
**When** a GM calls it
**Then** it returns `CampaignStatsGMResponse` with `sessions_played`, `entries_per_session[{session_key, count}]`, `entries_per_week` (the existing chart), `contributions[{member_display_name, entries, words}]`, `most_mentioned[{entity_id, name, type, count}]` (top 10) and `quest_completion {completed, closed_or_active, rate, definition}`.

**Given** a Campaign with entries from three Members
**When** stats are computed
**Then** all three Members' entries count (FR-10). Today's analytics count only the Owner's (`campaigns.py:158-209`).

**Given** a Player
**When** they call the same route
**Then** they get `CampaignStatsPartyResponse`, computed with their ctx through `scoped_select`, so GM-only entries, other Players' Private entries, GM-only Entities and Mentions whose Audience (AD-12 Mention formula) excludes them do not count
**And** the EV-4 counts-and-ranking probe shows the Player's JSON is byte-identical before and after adding a GM-only entry, a GM-only Quest marked completed, and 50 GM-only Mentions of a Party Entity.

**Given** confirmed Mentions exist in the Campaign
**When** `most_mentioned` is computed
**Then** it counts confirmed Mentions visible to the ctx. With no confirmed Mentions, it falls back to the tag counts of visible entries, labelled `source: "tags"`.

**Given** Quests with `domain/entity_types.py` status categories
**When** `quest_completion` is computed over Quests visible to the ctx
**Then** `completed` = Quests in `closed_success`, `closed_or_active` = Quests in `open` plus every `closed_*`, `rate = completed / closed_or_active` (null when 0), and `definition` = "Completed Quests ÷ Quests that are active or closed".

**Given** the legacy `GET /api/campaigns/{id}/analytics`
**When** it is called
**Then** it delegates to `stats_service` with the caller's ctx and returns the existing `CampaignAnalytics` shape (`schemas/campaign.py:62-67`), now Member-wide and visibility-filtered.

**Given** an anon Share Link ctx, or a user who is not a Member
**When** it calls `GET /api/stats`
**Then** the response is `404 {"detail":"Not found"}`.

**Standing ACs:** SA-Route (`tests/ev4/probes/stats.py`: the counts-and-ranking family, Public vs Members vs Owner(other) for Private Player Journal word counts, and 404 parity; `locations.conf` generic zone). No cache in this story. If one is added later, its key includes the audience and `access_epoch` (AD-13).

**Covers:** FR-49, FR-10 (analytics part), NFR-5, AR-13.

**Technical notes:** New `services/stats_service.py` (Decision B6-3) and `api/routes/stats.py`, with `schemas/stats.py` holding both the GM and Party responses. Contributions show display names only, never emails. Session key = `session_date ?? created_at::date` (AR-23). Only the analytics handler body in `campaigns.py` changes (Decision B6-6).

**Dependencies:** E0-Access.3 (`audience_ctx`, `scoped_select`), E0-Access.4, E0-Access.13 (FR-10 analytics scope), E0-WorldCore.1, E0-WorldCore.7, E0-QA.11.

**Size:** M

### Story E9.2: Opt-in Session Streaks with automatic grace

As a Member,
I want to opt in to a Session Streak that counts the Sessions I contributed to, forgiving one missed Session,
So that I can enjoy a run of Sessions without being guilted about real life.

**Acceptance Criteria:**

**Given** this story's Alembic revision
**When** it is applied
**Then** it adds `activity_events(id, campaign_id, user_id, kind, ref_kind, ref_id, session_key, occurred_at)` with `kind` a CHECK generated from the `ActivityKind` StrEnum (`entry_created`, `entry_updated`, `entry_deleted`, `canon_approved`), plus `user_settings.streaks_enabled` and `user_settings.achievements_enabled` (boolean, default false)
**And** a set-based `INSERT … SELECT` backfills `entry_created` events from existing `journal_entries`, and running it twice adds nothing.

**Given** `hooks/stats.py` registered in `hooks/__init__.py`
**When** `entry_saved`, `entry_updated`, `entry_deleted` or `canon_changed` fires
**Then** it appends the matching `activity_events` row. A failure logs `hook_failed` and never blocks the save (NFR-9).

**Given** `domain/achievements.py: session_streak(campaign_sessions, contributed) -> Streak(current, best)`, a pure function
**When** it walks the Campaign's Sessions in order
**Then** a contributed Session adds 1, and one missed Session is covered by grace (it adds 0 and keeps the run). Two consecutive missed Sessions end the run (current returns to 0 on the next contribution). Grace is restored after each contributed Session. The latest Session, if not yet contributed, never ends a run
**And** unit tests cover: C C C → 3; C M C → 2; C M M C → 1; C M C M C → 3; C C M (latest) → 2; and no Sessions → 0. Days between Sessions never matter.

**Given** a user's Sessions
**When** `campaign_sessions` and `contributed` are built
**Then** `campaign_sessions` = distinct Session keys of entries visible to the user's ctx, and `contributed` = Session keys of entries the user authored (including their own Private Player Journal entries).

**Given** `GET /api/stats/me?campaign_id=`
**When** a user with streaks off calls it
**Then** it returns `{streaks_enabled:false, achievements_enabled:false, streak:null}`, and nothing about streaks is computed or stored for them.

**Given** streaks on
**When** they call it
**Then** `streak = {current, best}`, and the response has no "at risk", "next session", deadline or countdown fields.

**Given** `PATCH /api/stats/preferences` with `{streaks_enabled?, achievements_enabled?}`
**When** a user calls it
**Then** only their own `user_settings` row changes, and turning streaks off hides them at once with no confirmation and no warning copy.

**Given** the copy constants in `domain/achievements.py`
**When** `tests/test_stats_copy.py` scans them
**Then** none contains "lose", "lost", "broken", "break", "miss", "don't", "hurry", "only … left" or a number of days.

**Standing ACs:** SA-Table (`activity_events`, class `derived`, `derive_from=[ref]`, so an event is visible exactly when its ref is; `user_settings` columns added in the same revision). SA-Route (`tests/ev4/probes/stats.py` extended: `/api/stats/me` for user A never reflects user B's data, and Player streak Sessions exclude GM-only Session keys, so a Session recorded only in a GM-only entry does not appear; generic `locations.conf`).

**Covers:** FR-51, FR-50 (no nags), NFR-9, AR-17 (hook use).

**Technical notes:** `hooks/stats.py`, `domain/achievements.py` (streak part) and `services/achievement_service.py` (`get_me`). Owned tables per the spine: `activity_events` and `user_settings.streaks_enabled`. `achievements_enabled` is an E9 addition (Decision B6-10). The settings routes live in `stats.py`, so `api/routes/settings.py` is untouched.

**Dependencies:** E9.1, E0-Journal.1, E0-Access.3, E0-WorldCore.3 (`canon_changed`).

**Size:** M

### Story E9.3: Achievements and Milestones with idempotent awards

As a Member,
I want Milestones celebrated for the whole table and, if I opt in, personal Achievements awarded once,
So that the Campaign's big moments are marked without any pressure to play more.

**Acceptance Criteria:**

**Given** this story's Alembic revision
**When** it is applied
**Then** it adds `user_achievements(id, user_id, campaign_id, code, kind ∈ {achievement, milestone}, awarded_at, seen_at)` with `UNIQUE(user_id, campaign_id, code)`, and CHECKs from the `AwardKind` StrEnum and from the code list in `domain/achievements.py`.

**Given** `domain/achievements.py`
**When** it loads
**Then** it defines this starter list of Achievements, each a pure rule over the user's visible facts, with a lucide icon:

| Code | Title | Rule (computed from the user's ctx) |
|---|---|---|
| `first_tale` | First Tale | Authored their first Journal Entry in this Campaign |
| `regular` | Regular at the Table | Contributed to 5 Sessions |
| `veteran` | Veteran of the Table | Contributed to 25 Sessions |
| `wordsmith` | Wordsmith | 10,000 words across their own Narratives and Player Journal entries |
| `in_character` | In Character | Wrote their first Player Journal entry |
| `know_your_cast` | Know Your Cast | Their entries carry confirmed Mentions of 20 distinct Entities visible to them |
| `world_builder` | World Builder | Approved 25 Canon changes (`entity_changes.approved_by`, GM only) |
| `quest_complete` | Quest Complete | A Quest visible to them reached `closed_success` while they were a Member |
| `on_a_roll` | On a Roll | Session Streak of 3 (streaks on) |
| `unbroken_fellowship` | Unbroken Fellowship | Session Streak of 10 (streaks on) |

**And** it defines these Milestones: `session_10`, `session_25`, `session_50`, `session_100` ("The party reached its 10th Session"), `first_quest_completed`, `entries_100` ("100 Journal Entries") and `entities_100` ("100 Entities in the world").

**Given** `achievement_service.evaluate(db, campaign_id, user_ids)`
**When** it runs, from `hooks/stats.py` after each event and when `GET /api/stats/achievements` is read
**Then** for each user it builds `audience_ctx(campaign_id, as_user(user_id))`, computes facts only through `scoped_select`, and inserts newly met codes with `ON CONFLICT DO NOTHING`
**And** running it twice, or concurrently, never creates a second row (a test with two parallel sessions).

**Given** a user with `achievements_enabled=false`
**When** evaluation runs
**Then** no Achievement rows are created for them, while Milestones still are. Turning Achievements on triggers one evaluation, so past play counts at once and nothing is lost by opting in late.

**Given** 99 Party Entities and 5 GM-only Entities
**When** a Player and the GM are evaluated
**Then** the GM gets `entities_100` and the Player does not. Milestone counts a Player sees come only from visible content (FR-50).

**Given** an award
**When** later content is hidden or deleted
**Then** the award is never revoked, and no copy mentions losing it.

**Given** `GET /api/stats/achievements?campaign_id=`
**When** a user calls it
**Then** it returns only their own rows: earned Achievements (only when opted in), the unearned starter list as titles without progress counters or countdowns, and Milestones
**And** `GET /api/stats/milestones?campaign_id=&unseen=true` lists unseen Milestones, and `POST /api/stats/milestones/{id}/seen` sets `seen_at` on the caller's own row only (any other id returns 404).

**Standing ACs:** SA-Table (`user_achievements`, class `stored` with `Owner(user_id)` audience; rows never appear in another user's response). SA-Route (`tests/ev4/probes/stats.py` extended: Milestones from visible counts only, cross-user 404 on `/seen`, no award row for user B reachable by user A; generic `locations.conf`).

**Covers:** FR-50, FR-51 (opt-in for Achievements), NFR-5, DS-5 (milestone data).

**Technical notes:** `services/achievement_service.py` and `domain/achievements.py`. Evaluation is cheap (indexed counts) and runs inline in the hook inside try/except ("must not block the save"), so it needs no Job kind. Quest completion uses `entities.completed_at` stamped by `apply_change` (B3 contract).

**Dependencies:** E9.2, E0-Access.3, E0-WorldCore.3, E0-WorldCore.7.

**Size:** M

### Story E9.4: Stats page with Achievements and Milestones

As a Member,
I want the Analytics page to become a Stats page that celebrates the Campaign, with my Achievements shown only if I opted in,
So that I can see the story in numbers and the moments we've reached.

**Acceptance Criteria:**

**Given** `/stats`
**When** a Member opens it
**Then** `pages/StatsPage.tsx` (the renamed `AnalyticsPage.tsx`, named export, reusing `StatTile`, `WeeklyBarChart` and `TagRankList`) shows tiles for Sessions played, entries, and entries per Session, a contributions list, a most-mentioned list linking each Entity to its panel, and a Quest completion tile whose tooltip states "Completed Quests ÷ Quests that are active or closed" (keyboard-focusable, not hover-only).

**Given** streaks are on
**When** the page renders
**Then** a Session Streak tile shows "current · best" in `mono` tabular figures. When streaks are off, the tile is absent (no greyed-out tile).

**Given** Achievements are off (the default)
**When** the Achievements section renders
**Then** EmptyState shows "Achievements are off. Turn them on for yourself.", with one action that sets the preference.

**Given** Achievements are on
**When** the section renders
**Then** `AchievementBadge` (56 px circle, lucide glyph) shows a foil ring only when earned and a muted outline otherwise, with title and award date, and no progress bars or "N to go".

**Given** Milestones
**When** the page renders
**Then** every earned Milestone is listed permanently with its date.

**Given** no Sessions yet
**When** the page renders
**Then** EmptyState shows "Stats start after your first Session.", and tile skeletons show while loading.

**Given** a Player
**When** they open `/stats`
**Then** the same page renders from the Party response, with no hint (gaps, "hidden" labels, different totals text) that anything was left out.

**Standing ACs:** SA-UI (foil only on earned badges and Milestone rules, no shimmer under reduced motion, tokens only, 375 px with tiles in one column). The `/analytics` → `/stats` redirect and nav rename are E0-UX's (UX-DR10). This page uses that route.

**Covers:** FR-49 (UI), FR-50 (UI), FR-51 (UI hiding), NFR-10, UX-DR32.

**Technical notes:** `services/api/stats.ts`, `types/stats.ts` and `hooks/useStats.ts` (keys `["stats", campaignId]`), and `components/stats/AchievementBadge.tsx` and `MilestoneList.tsx`. Each section is guarded by its API fields, so a cut of E9.2 or E9.3 removes the section and nothing else.

**Dependencies:** E9.1, E9.2, E9.3, E0-UX.4, E0-UX.5, E0-UX.8.

**Size:** M

### Story E9.5: Milestone celebrations and personal milestone settings

As a Member,
I want a new Milestone to appear once as a card on my Dashboard (or Portal), and a Settings switch for my Streaks and Achievements,
So that we celebrate together and I decide for myself whether to track personal runs.

**Acceptance Criteria:**

**Given** an unseen Milestone
**When** the user opens the Dashboard
**Then** `MilestoneCard` (foil top rule, `stat-display` title such as "The party reached its 10th Session", date) appears once, can be dismissed, and is marked seen through `POST /api/stats/milestones/{id}/seen` on dismiss or after it has been on screen for 5 s
**And** it never appears again on Dashboard or Portal, and it stays listed on Stats.

**Given** the Portal (B4) mounts the exported `MilestoneSlot` component
**When** a Player has an unseen Milestone
**Then** the same card and seen behaviour apply.

**Given** Settings › Notifications & milestones
**When** the user opens it
**Then** two switches, "Session Streaks" and "Achievements", both off by default, save through `PATCH /api/stats/preferences` with the toast "Saved", and the copy reads "Just for you. Nobody else sees whether these are on."

**Given** any E9 surface or copy string
**When** the CI-15 grep plus `tests/test_stats_copy.py` run
**Then** they contain no loss messaging, countdowns, reminders or nags. No browser notification is ever sent for streaks or Achievements.

**Given** DS-5 offline
**When** the demo seed (extended in `seeds/` with enough Sessions to reach `session_10`) is loaded
**Then** the MilestoneCard "The party reached its 10th Session" appears on the Dashboard, and the step is recorded in `docs/BENCHMARKS.md`.

**Standing ACs:** SA-UI (dismiss is keyboard reachable, the card is announced politely once, reduced motion shows no foil animation).

**Given** `components/portal/portalSections.ts` (E7.1) (Reconciliation RC-17)
**When** this story lands
**Then** it appends one line registering `{id: "milestone", position: "top", component: MilestoneSlot}`, so E7 imports nothing from E9.

**Covers:** FR-50 (celebration display), FR-51 (settings), NFR-10, UX-DR32, DS-5 (milestone part).

**Technical notes:** `components/stats/MilestoneCard.tsx`, `MilestoneSlot.tsx` and `MilestoneSettings.tsx`, each mounted with one line in `DashboardPage.tsx` and `SettingsPage.tsx`. The Portal slot is a B4 contract (§3.4 "Portal slots").

**Dependencies:** E9.3, E9.4, E7.1 (Portal slot registry), E0-UX.5.

**Size:** S

## Epic E10: Maps and pins

The GM uploads Maps and pins Locations and entries to them. Players explore Party Maps without any trace of GM-only Pins. The frontend uses plain Leaflet 1.9.4 with `CRS.Simple` behind an in-house wrapper (**no react-leaflet**: it is Hippocratic-2.1 and v5 needs React 19). Tiles come from libvips (`pyvips dzsave`, apt libvips, never `pyvips[binary]`). Maps can be up to 50 MB and 16,000 px on the longest side. A keyboard-accessible PinList is a complete equivalent of the map. Pins are stored normalized and never drawn into tiles.

### Story E10.1: Upload, rename, replace and delete Maps

As a GM,
I want to upload a Map image, and later rename, replace or delete it, with clear messages when a file is not accepted,
So that my world's maps live in Lorekeeper and are served only to the people allowed to see them.

**Acceptance Criteria:**

**Given** this story's Alembic revision
**When** it is applied
**Then** it adds `maps(id, campaign_id, name, visibility (PG enum, default gm), image_file_id, width_px, height_px, version, status, max_zoom, created_by, created_at, updated_at)`, with `status` a CHECK from the `MapStatus` StrEnum (`preparing`, `ready`, `failed`).

**Given** a GM
**When** they call `POST /api/maps` (multipart `campaign_id`, `name`, `file`) with a PNG, JPEG or WebP
**Then** the type is checked from the file's bytes with Pillow `Image.open` (header only, never decoding pixels in web), the image is stored through `file_service.put` as kind `map_image`, and the Map is returned with its dimensions.

**Given** a file over 50 MB
**When** it is uploaded
**Then** the upload is cut off once the stream passes 50 MB (nginx `client_max_body_size 55m` on `/api/maps`, plus a streaming byte counter), and the response is 413 with "Maps can be up to 50 MB and 16,000 px on the longest side."

**Given** an image whose longest side is over 16,000 px, an animated PNG or WebP, a GIF, an SVG, or a renamed non-image
**When** it is uploaded
**Then** it is rejected with 422 and a message naming the rule ("Maps must be PNG, JPEG or WebP." or the size message). `Image.MAX_IMAGE_PIXELS` is set to 16,000², so a decompression bomb is rejected.

**Given** an existing Map
**When** the GM calls `PATCH /api/maps/{id}` with `{name}`, `PUT /api/maps/{id}/image` with a new file, or `DELETE /api/maps/{id}`
**Then** rename updates the name. Replace stores the new image, increments `version`, and returns `aspect_changed: true` when `|new_ratio − old_ratio| / old_ratio > 0.01`. Delete removes the Map, then its files through `file_service.delete`.

**Given** a Map's Visibility
**When** the GM changes it through `POST /api/maps/{id}/visibility`
**Then** the change is written only by `access.set_visibility` (moving to Party is confirmed in the UI per UX-DR11).

**Given** a Player
**When** they call `GET /api/maps?campaign_id=` or `GET /api/maps/{id}`
**Then** they see only Party Maps, a GM-only Map returns the same 404 as a nonexistent id, its image file id returns 404 through `/api/files/{id}`, and every write route returns 404.

**Given** this story alone (tiling not yet built)
**When** a Map is uploaded
**Then** its status is `ready`, and the viewer can load the original image through `GET /api/files/{image_file_id}`. E10.2 replaces this with tiles.

**Given** a restart, and the `files_data` backup procedure in `docs/DATABASE_BACKUPS.md`
**When** the stack comes back, or is restored from a backup
**Then** Map files persist and are included in the backup (FR-52).

**Standing ACs:** SA-Table (`maps`, class `stored`). SA-Route (`tests/ev4/probes/maps.py`: a GM-only Map absent from the Player and anon list, 404 parity for item and file, list counts unchanged by GM-only Maps; `locations.conf` lines for `/api/maps` with `client_max_body_size 55m`; `@limiter.limit` on upload keyed `user_or_ip`).

**Covers:** FR-52 (upload, rename, replace, delete, limits, persistence, access-checked serving), FR-54 (Map part), FR-8 (files), AR-14.

**Technical notes:** `services/map_service.py`, `api/routes/maps.py` and `schemas/maps.py` (`MapGMResponse` and `MapPartyResponse`). The upload pattern follows `api/routes/sources.py:48-106` and `ingest.py`. Pillow is an existing dependency (`auth.py:163-187`). The web tier never decodes a full image (AD-7: web is 1g).

**Dependencies:** E0-Jobs.8, E0-Access.2, E0-Access.3 (`audience_ctx`, `scoped_select`), E0-Access.4, E0-Access.9 (`set_visibility` for Map Visibility), E0-QA.11, E0-Platform.8.

**Size:** M

### Story E10.2: Tile large Maps with libvips as a Job, and serve tiles

As a GM with a 16,000 px world map,
I want large Maps prepared into zoomable tiles in the background,
So that panning and zooming stay fast on the Reference Box.

**Acceptance Criteria:**

**Given** an upload or replace
**When** it is stored
**Then** the Map's status is `preparing` and the Job `maps.tile` is enqueued. The response carries `job_id`, and the Map card shows the Job's state.

**Given** the `maps.tile` Job in the worker
**When** it runs
**Then** it opens the image with `pyvips.Image.new_from_file(path, access="sequential")`, autorotates it, and runs `dzsave(layout="google", tile_size=256, suffix=".jpg[Q=85]", overlap=0)` into a temporary directory. It then stores the tile tree as one `stored_files` row of kind `map_tiles` (storage key = a directory under `/data/files/{campaign_id}/map_tiles/{uuid}/`) plus a 512 px thumbnail of kind `map_thumb`, sets `max_zoom`, and sets the status to `ready`.

**Given** a tiling failure (a corrupt image, or memory)
**When** the Job ends `failed`
**Then** the Map's status is `failed`, the card shows the reason with Retry, and the original image remains.

**Given** a Map replaced or deleted while its Job runs
**When** the Job finishes
**Then** output for an outdated `version` is discarded and garbage-collected, and the Job ends `done` with no effect.

**Given** `GET /api/maps/{id}/tiles/{z}/{y}/{x}.jpg`
**When** a ctx that can see the Map requests a tile within bounds
**Then** the route checks access, returns `X-Accel-Redirect: /_files/<key>/{z}/{y}/{x}.jpg` with `Cache-Control: private, no-cache` and an ETag that includes `access_epoch` and the Map `version`
**And** a hidden Map, an out-of-range or non-integer `z/y/x`, or a non-ready Map returns 404.

**Given** a 16,000 × 12,000 px PNG and JPEG on the Reference Box
**When** `maps.tile` runs
**Then** the worker's peak RSS stays under its 1g limit, and the wall-clock time and peak RSS are recorded in `docs/BENCHMARKS.md` (SPIKE-5 input, NFR-2). If 1g is exceeded, the story sets `VIPS_CONCURRENCY=1` and `VIPS_DISC_THRESHOLD`, or raises the worker limit by lowering another in the same PR (CI-14).

**Given** any tile
**When** pins are added, moved or removed
**Then** tile bytes and ETags are unchanged (AD-14: tiles never contain pins), which the E10.3 EV-4 probe verifies.

**Standing ACs:** SA-Job (`maps.tile`: `queue=interactive`, `timeout_s=900`, `resources={cpu_heavy}`, `live_safe=False`, `result_audience=` the Map's Audience; idempotency key `maps.tile:{map_id}:{version}`). SA-Dep (`licenses/register.yaml`: pyvips (MIT), apt `libvips42` (LGPL-2.1, dynamic system-library allowlist); `pyvips[binary]` is forbidden by a requirements test). SA-Route (`tests/ev4/probes/maps.py` extended: tile route 404 parity for hidden Maps, anon 404; `locations.conf` generic zone for `/api/maps/[^/]+/tiles/`).

**Covers:** FR-52 (large Maps as a Job), NFR-2, AR-14 (tiles), SPIKE-5 (tiling measurement).

**Technical notes:** `jobs/maps.py`. The worker image adds `libvips42` from apt. `file_service` must support a directory-valued `storage_key` for `map_tiles`. This is a one-function addition (`put_tree`) to `file_service.py`, coordinated as a shared-contract append (Decision B6-11). The tile route reuses `file_service.open` and `file_service.accel_response` (E0-Jobs.8). `files.gc` removes superseded tile trees.

**Dependencies:** E10.1, E0-Jobs.2, E0-Jobs.3, E0-Jobs.7, E0-Jobs.8, E0-Platform.10, E0-QA.7, E0-QA.15.

**Size:** M

### Story E10.3: Pins with normalized positions and Visibility rules

As a GM,
I want to place Pins with a label, a Location and linked entries at image-relative positions, with Visibility that follows the Location unless I override it,
So that Pins stay put at every zoom and Players never learn about GM-only places.

**Acceptance Criteria:**

**Given** this story's Alembic revision
**When** it is applied
**Then** it adds `map_pins(id, campaign_id, map_id, label, x, y, location_entity_id, visibility_override, needs_review, created_by, created_at, updated_at)` with `CHECK (x BETWEEN 0 AND 1 AND y BETWEEN 0 AND 1)`, a composite FK `(campaign_id, location_entity_id) → entities` `ON DELETE SET NULL`, and `map_id → maps ON DELETE CASCADE`
**And** it adds `map_pin_entries(pin_id, journal_id)`, with `journal_id ON DELETE CASCADE` (AD-10 unlink on entry delete).

**Given** `POST /api/maps/{id}/pins` with `{label, x, y, location_entity_id?, journal_ids?}`
**When** a GM calls it
**Then** a label is required (422 otherwise), `x` and `y` must be in [0,1], the Location must be a `type=location` Entity in the same Campaign, and `visibility_override` defaults to null when a Location is given and `gm` when none is given (set through `set_visibility`).

**Given** a Pin's Audience
**When** `access` computes it
**Then** it is `most_restrictive(aud(map), visibility_override ?? aud(location) ?? GM)`, declared once in `access/registry.py` so that `visible_clause` and `audience_of` agree (CI-11 property test includes `map_pins`)
**And** a `map_pin_entries` link's Audience is `most_restrictive(aud(pin), aud(entry))`.

**Given** a Party Map with one Party Pin, one GM-only Pin, one Pin whose Location is GM-only (no override), and one Pin with `visibility_override=party` pointing at a GM-only Location linked to one GM-only entry
**When** a Player calls `GET /api/maps/{id}/pins`
**Then** they get exactly two Pins: the Party Pin, and the override Pin with `location_entity_id` and the GM-only entry link removed (the reference removed, per FR-8)
**And** the response length, ordering and ETag are the same as when the hidden Pins don't exist.

**Given** `PATCH /api/pins/{id}` and `DELETE /api/pins/{id}`
**When** a GM moves (`x`, `y`), relabels, relinks or deletes a Pin
**Then** the change persists. A Player or anon ctx gets 404 on every Pin write and on a hidden Pin's id.

**Given** a Map replaced with the same aspect ratio
**When** pins are read
**Then** every Pin keeps its `x,y` and `needs_review=false`
**And** when `aspect_changed` is true, every Pin on the Map gets `needs_review=true`, and `POST /api/pins/{id}/confirm-position` (optionally with a new `x,y`) clears it.

**Given** `GET /api/maps/pins?campaign_id=&location_entity_id=`
**When** a ctx calls it
**Then** it returns the visible Pins of that Location across visible Maps, with the Map name (used by "On maps").

**Given** EV-4
**When** `tests/ev4/probes/maps.py` runs
**Then** a GM-only Pin on a Party Map is absent from every Player and anon response, the Party Pin count is unchanged by hidden Pins, the sha256 of every tile and its ETag are identical before and after adding the GM-only Pin, and the downgrade suite (Location party → gm) hides dependent Pins on the next read.

**Standing ACs:** SA-Table (`map_pins` and `map_pin_entries`, class `derived`, with `visibility_override` written only by `set_visibility`). SA-Route (probe as above; `locations.conf` lines for `/api/pins/`).

**Covers:** FR-53 (backend), FR-54, FR-8, NFR-5, EV-4.

**Technical notes:** Pins are stored normalized, `x = px/width` and `y = px/height` (spine Map convention). `map_service` exposes `list_pins(db, ctx, map_id)`. Creating a Location from the PinEditor goes through the Entity API (`apply_change`), never from `map_service`.

**Dependencies:** E10.1, E0-Access.3, E0-Access.9 (`set_visibility` for `visibility_override`), E0-WorldCore.3, E0-WorldCore.5, E0-QA.11.

**Size:** M

### Story E10.4: Map list, Leaflet viewer and the keyboard PinList

As a Member,
I want to browse Maps, pan and zoom a Map smoothly, open a Pin's Location or entries, and use a full list of Pins by keyboard,
So that I can explore the world's geography on any device, with or without a mouse.

**Acceptance Criteria:**

**Given** `/world/maps`
**When** a Member opens it
**Then** `pages/MapsPage.tsx` shows a card grid with thumbnails. A GM also sees an "Upload map" card (PNG, JPEG or WebP, up to 50 MB and 16,000 px), and a `preparing` Map shows "Preparing map… about 1 min" from `useJobStream`.

**Given** no Maps
**When** the page renders
**Then** a GM sees "Upload a map image to start placing pins." and a Player sees "No maps shared yet."

**Given** `/world/maps/:id`
**When** the viewer mounts
**Then** `components/map/LeafletMap.tsx` creates a plain `L.map` with `crs: L.CRS.Simple`, bounds from `width_px` and `height_px`, and an `AuthedTileLayer` (an `L.GridLayer` subclass) that fetches each tile from the tile route with the bearer header, shows it through `URL.createObjectURL`, and revokes it on `tileunload`. No tile URL carries a token
**And** `package.json` contains `leaflet@1.9.4` and no `react-leaflet` (`tests` grep plus the licence gate).

**Given** Pins
**When** they render
**Then** positions convert only through `lib/mapCoords.ts` (`toLatLng(x, y, map)` and `toNormalized(latlng, map)`), markers use `divIcon` `map-pin` (and `map-pin-gm`, dashed `colors.gm`, in the GM view only), and markers keep their screen size at every zoom.

**Given** a Pin is clicked or activated
**When** the popover opens
**Then** it shows the Location's `EntityCard` (B3) and its visible linked entries by italic title, and "Open" opens the EntityDetailPanel or the entry.

**Given** a keyboard user
**When** they use the page
**Then** the map container is focusable (arrow keys pan, `+` and `−` zoom, a Fit button), and `PinList` shows every visible Pin sorted by label with a filter box. Arrow keys move through rows, and Enter centres and selects the Pin and opens its popover. PinList is a complete equivalent (every Pin action reachable from it) and is the default view below 640 px, with a Map/List toggle.

**Given** `prefers-reduced-motion`
**When** the map is created
**Then** `zoomAnimation`, `fadeAnimation` and `markerZoomAnimation` are false, and centring jumps instead of flying.

**Given** a prepared 16,000 px Map on the Reference Box and Chrome on the reference laptop
**When** a scripted run of 20 pan and zoom views is measured
**Then** each view's tiles finish loading in under 1 s, and the result is recorded in `docs/BENCHMARKS.md` (FR-52).

**Given** the exported `MapViewer` component
**When** the Portal (B4) mounts it for a Player
**Then** it renders read-only from the same Party responses.

**Standing ACs:** SA-UI (375 px, touch targets ≥ 44 px, visible focus on markers and rows, Leaflet CSS loaded only on map routes). SA-Dep (`leaflet` BSD-2-Clause in `licenses/register.yaml`).

**Given** `components/portal/portalSections.ts` (E7.1) and `registerWorldTab` (E0-WorldCore.10) (Reconciliation RC-17, RC-14)
**When** this story lands
**Then** it appends one line registering `{id: "maps", position: "bottom", component: PortalMapsCard, requiresRoute: "/maps"}` listing Party Maps, and one `registerWorldTab` line for Maps.

**Covers:** FR-52 (view performance), FR-53 (click opens Location or entries), FR-54 (Player view), NFR-10, UX-DR25 (list, viewer, PinList), UX-DR12.

**Technical notes:** `pages/MapsPage.tsx`, `components/map/{LeafletMap,AuthedTileLayer,MapPin,PinList,MapViewer}.tsx`, `lib/mapCoords.ts`, `services/api/maps.ts`, `types/maps.ts` and `hooks/useMaps.ts`. The World hub tab and the route are one line each (`App.tsx`, World Tabs). Leaflet is wrapped in `useEffect` with cleanup and is never re-created on re-render.

**Dependencies:** E10.2, E10.3, E7.1 (Portal slot registry), E0-UX.4, E0-UX.5, E0-UX.8, E0-WorldCore.10 (panel, `registerWorldTab`), E0-WorldCore.11 (`EntityCard`), E0-Jobs.9.

**Size:** L

### Story E10.5: GM pin placement, editing and moving

As a GM,
I want to place a Pin with one click (or from the keyboard), fill in its label, Location, entries and Visibility, and move it by drag or arrow keys,
So that I can mark places quickly and precisely.

**Acceptance Criteria:**

**Given** a Map in the GM view
**When** the GM presses "Add pin" or the `p` shortcut (registered in the shortcut registry; never fires in inputs)
**Then** placement mode starts with a PlacementBar ("Placing pin… · Esc to cancel") and a crosshair cursor. A click places the Pin, and "Place at centre" places it at the view centre for keyboard users. Either way, the PinEditor opens.

**Given** the PinEditor
**When** it opens
**Then** it has a required label, a Location Combobox over visible `location` Entities with "Create Location…" (creates a GM-only Location through `POST /api/entities` and selects it), a linked-entries multi-select, and a VisibilityBadge defaulting to the Location's Visibility (GM-only when there is no Location). Moving to Party asks "Players will see this. Make visible?"
**And** Save is disabled until a label exists, with the message "A pin needs a label."

**Given** a selected Pin
**When** the GM drags it, or chooses Move and presses the arrow keys (2 screen px per press, Shift ×10)
**Then** Enter or Save persists the new `x,y` through `PATCH /api/pins/{id}`, and Esc restores the old position without a request.

**Given** a Pin
**When** the GM deletes it
**Then** an inline confirm appears, and the Pin is removed with a 10 s Undo toast that recreates it with the same fields.

**Given** a replace with `aspect_changed: true`
**When** the upload finishes
**Then** a warning reads "This image has a different shape. Check where your pins landed.", and "Review pin positions" lists each `needs_review` Pin. The GM confirms or moves each one, and the mode ends when none remain.

**Given** the GM manages the Map
**When** they rename, replace or delete it from the viewer header menu
**Then** the E10.1 routes are called. Delete asks "Delete *{name}* and its {n} pins?"

**Given** the PreviewBanner read-only flag
**When** it is active
**Then** every placement and edit control is disabled with "Preview is read-only".

**Standing ACs:** SA-UI (PlacementBar announced, focus moves to the PinEditor and returns to the Pin, everything reachable from PinList, 375 px with placement by tap).

**Covers:** FR-53 (place, move, edit, delete), FR-52 (rename, replace, delete UI), NFR-10, UX-DR25 (PlacementBar, PinEditor, move, replace review, `p`).

**Technical notes:** `components/map/{PlacementBar,PinEditor,ReviewPinPositions}.tsx`, which use `lib/mapCoords.ts` for every conversion. The Combobox, VisibilityBadge and Toast come from E0-UX. Entity creation uses the B3 Entity API contract.

**Dependencies:** E10.4, E0-UX.4, E0-UX.5, E0-UX.6, E0-UX.9 (shortcut registry), E0-WorldCore.5.

**Size:** L

### Story E10.6: "On maps" and "Place on a map" from a Location

As a GM or Player viewing a Location,
I want its panel to list the Pins that mark it, and as a GM to place it on a Map from there,
So that places and maps link both ways.

**Acceptance Criteria:**

**Given** a `location` Entity panel
**When** it renders
**Then** an "On maps" section registered in `components/entities/panelSections.ts` (no edit to `EntityDetailPanel.tsx`) lists the Location's visible Pins from `GET /api/maps/pins?location_entity_id=`, grouped by Map name. Selecting one opens `/world/maps/:id?pin=:pinId`, centred on that Pin with it selected.

**Given** a Location with no visible Pins
**When** a Player views it
**Then** the section is hidden. A GM sees the hint "Not on any map yet" and the action "Place on a map".

**Given** "Place on a map"
**When** the GM chooses a Map (Combobox over the GM's Maps)
**Then** the viewer opens at `/world/maps/:id?place=:entityId` in placement mode, with the PlacementBar "Placing *{Location}*…" and the PinEditor prefilled with label = Location name, Location = it, and Visibility inherited.

**Given** a deep link `?place=` to a Map or Entity the ctx can't see
**When** it opens
**Then** the unified not-found page shows, identical to a missing record.

**Standing ACs:** SA-UI (the section's keyboard order follows the panel's, and the links are real anchors).

**Covers:** FR-53 ("A Location's panel lists its Pins"), UX-DR20 (On maps section), UX-DR25 ("On maps", "Place on a map").

**Technical notes:** `components/map/OnMapsSection.tsx`, registered with one line in `panelSections.ts`. The `?place=` and `?pin=` query handling lives in `MapsPage.tsx`.

**Dependencies:** E10.5, E0-WorldCore.10.

**Size:** S

### Story E10.7: Offer to place a newly approved Location on a Map (FR-55)

As a GM applying my Review Checklist,
I want to be offered to place a newly approved Location on one of my Maps,
So that the map grows with the story without a separate trip.

**Acceptance Criteria:**

**Given** a Review Checklist where an approved `proposal:create_entity` with `type=location` has just been applied, and the Campaign has at least one Map visible to the GM
**When** Apply completes
**Then** the renderer registered in the follow-up slot of `components/review/itemRenderers.ts` shows "Place *{Location}* on a map?" with a Map picker (default: the most recently opened Map), "Place" and "Not now".

**Given** the GM chooses Place
**When** it is activated
**Then** the app navigates to `/world/maps/:id?place=:entityId` (E10.6 placement mode).

**Given** the GM chooses "Not now", or closes the checklist
**When** it is dismissed
**Then** no Pin and no request are created, and the offer isn't shown again for that Location in this checklist.

**Given** a Campaign with no Maps, or a checklist that approved no new Location
**When** Apply completes
**Then** no offer is rendered.

**Given** several new Locations approved in one Apply
**When** the slot renders
**Then** it offers them one at a time in checklist order, each skippable.

**Standing ACs:** SA-UI (the offer is focusable right after the Apply announcement, Esc dismisses it, and the copy follows the voice rules).

**Covers:** FR-55, UX-DR16 (FR-55 follow-up prompt).

**Technical notes:** `components/map/PlaceLocationFollowUp.tsx`, registered with one line in `itemRenderers.ts` per the B3 contract "Review item renderers (footer follow-up slot after Apply)". This is the cut-order #2 story. Removing it removes only this file and that line.

**Dependencies:** E10.6, E1.5 (`registerFollowUp`).

**Size:** S

## Cross-batch contract reconciliation

The six batch files (`epic-stories/B1.md` to `B6.md`) were written in parallel, and each assumed contracts that another batch owns. The merge resolved every one of them in the story text above. Each fix is tagged `Reconciliation R-n` in the story it changes. The batch files are kept unchanged for provenance, so this list is the diff between them and this document.

| Id | Assumed by | Owner story (what was added) | Resolution |
| --- | --- | --- | --- |
| RC-1 | B3 (E2.3) | E0-Jobs.2 (AC), E0-Jobs.4 (AC) | `enqueue(depends_on_job_id=…)`: the dependent is held until the dependency is terminal (`done`, `failed` or `cancelled`) and then always runs; the reaper pushes stranded dependents. |
| RC-2 | B3 (E0-WorldCore.2, .7) | E0-Jobs.5 (AC) | `data_backfills` runner: `register_backfill(name, kind)`, one Job per Campaign as the Owner's GM ctx (`ctx_for`), idempotent per Campaign, `done` when every Campaign is terminal. |
| RC-3 | B6 (E10.2) | E0-Jobs.8 (AC) | `file_service.put_tree` stores a tile tree as one directory and one `stored_files` row; `accel_response(file, subpath)` serves files inside it. |
| RC-4 | B5 (E0-LLM.1, .2) | E0-Jobs.1 (text), E0-Jobs.3 (text + AC) | `JobErrorCode` includes `llm_config`, `ai_output_unusable` (renamed from B2's `structured_output` to match `StructuredOutputError.code`), `llm_busy`, `llm_unavailable`. The worker classifies with `errors.RETRYABLE/TERMINAL` and sets `llm_gate.current_class` per Job: the kind's `gate_class`, otherwise `class_for_queue(queue)`. |
| RC-5 | B6 (B6-16) | E5.4 (AC) | **Decision:** `app/clients/tts.py` stays in E5.4, not E0-Platform. No E0-Platform story needs it, and the `tts` container is AGPL-only and optional. It follows the AD-6 client shape and an E0-Platform owner reviews it. The boundary map records the exception. |
| RC-6 | B2 (E0-Journal.3), B3 (E0-WorldCore.9) | E0-Access.2 (AC) | `ctx.as_system(reason)` is allowed only for `SystemReason {entry_deleted, merge}`, can't come from a request, and is CI-checked to two call sites. `access.ctx_for(db, user_id, campaign_id)` rebuilds a ctx for workers, hooks and backfills. |
| RC-7 | B4 (E7.7) | E0-Access.3 (AC) | `X-Lorekeeper-Preview: member` on a GM request makes `require_campaign` return `audience_ctx(campaign_id, member)`. The header is ignored for Player, anon and Share Link requests (it can only narrow), and writes under it return 404. |
| RC-8 | B5 (E4.5) | E0-Access.3 (AC) | `DERIVED_REGISTRY` accepts non-file derived types such as `live_recap`. |
| RC-9 | B5 (E6.1) | E0-Access.7 (AC), E6.1 (text) | `hybrid_search_journal(..., narrative_only=False)` is built in E0-Access.7, because E0-Access owns `retrieval_service`. E6.1 now only passes it. (The brief called this keyword `narrow_only`; the batch name `narrative_only` is kept because it describes what it does.) |
| RC-10 | B5 (E4.2), B3 (E2.1), B6 | E0-Access.8 (AC) + one-line registrations in E0-WorldCore.5, E2.1, E4.2 | `access.register_resolver(kind, fn)`. `resolve_sources` checks visibility before any resolver runs, and an unregistered kind fails closed. |
| RC-11 | B3 (E0-WorldCore.3, .9) | E0-Access.9 (AC) | Public `access.mark_dependents_stale(db, refs)` shared by `set_visibility` and `apply_change`. The merge `visibility_floor` write in `apply_change(op="merge")` is the one allowlisted exception in `check_scoped_queries.py`. |
| RC-12 | B1/B2/B3 enum clash | E0-WorldCore.1 (text + AC) | Two different enums were both called `source_field`. They are now `TagSourceField {shorthand, narrative, manual}` (journal tags) and `MentionSourceField {narrative, shorthand, gm_notes}` (Mentions). |
| RC-13 | B4 (E3) | E0-WorldCore.2 (text + AC) | `relationship_types.hostile boolean NOT NULL DEFAULT false`. Only the default `enemy_of` is hostile. |
| RC-14 | B4 (E3.4), B6 (E10.4) | E0-WorldCore.10 (AC) | `components/entities/worldTabs.ts` `registerWorldTab` (new shared append point) for the `/world/web` and Maps tabs, plus the "Preview this page as a Player" overflow item that calls `usePreview().enter`. |
| RC-15 | B4 (E7.8) | E1.3: hooks already skip `kind = player` | Confirmed: E1.3's save/edit hooks and E2.3's continuity hook ignore `kind = player` entries. |
| RC-16 | B4 (E7.8) | E1.3 (AC) | A GM-enqueued `extraction.run` with `origin: "promotion"` runs on a Player Journal entry, writes `proposal_batches(origin = promotion)` with every default `gm`, and uses its own idempotency key. |
| RC-17 | B4 vs B6 (who mounts Portal cards) | E7.1 (AC), E5.6, E9.5, E10.4 (AC + dependency on E7.1) | The **producing** epic registers its Portal section with one line in `portalSections.ts` (positions `top`, `main`, `bottom`), so E7 imports nothing from E5, E9 or E10. E3.4 already did this. |
| RC-18 | B6 (Keepsakes shell) | E5.2 (AC) | Whichever of E5.2 and E8.5 lands first creates `pages/KeepsakesPage.tsx`, and the other fills only its own tab (E8.5 already said so). |
| RC-19 | B4 guessed ids | E0-UX.8, E3.1, E3.3, E3.4, E7.1, E7.2, E7.5, E7.6, E7.8, E7.9 | Remapped to the real ids: guessed E0-WorldCore.4 (Entity API) → **.5**; .8 (World hub) → **.10**; E0-LLM.1 (gate) → **E0-LLM.2**; E1.2/E1.4 (extraction, checklist) → **E1.3, E1.4, E1.7**. E0-WorldCore.3 (`apply_change`) was already correct. |
| RC-20 | B6 guessed E0-LLM ids | E5.1 | B6's id table had the wrong E0-LLM order. Remapped: fake provider → **E0-LLM.5**, gate → **.2**, `prompt_budget` → **.3**. |
| RC-21 | B1 (E0-QA.14) | E0-QA.14 | "E0-LLM fake provider + capture hook (B5)" → **E0-LLM.5**. |
| RC-30 | B2, B3 | every B2/B3 cross-batch dependency | B2 and B3 named other batches' contracts (`E0-Access [set_visibility]`) instead of story ids. Every one is now a real story id, with the contract kept in brackets. Soft dependencies are written after "Soft:" and are not ordering edges. |
| RC-31 | B5 dependency text | E0-LLM.2, E0-LLM.5, E0-LLM.6, E5.5 | Prose in the Dependencies lines ("the fake provider arrives in E0-LLM.5", "Consumers: E0-QA.11 and E0-QA.14", "E5.4 is needed only for real audio") read as dependency edges and made a 23-story cycle and one forward dependency. It is reworded so consumers and soft needs are labelled as such. |

**SPIKE-6** is measured only in E0-Platform.10 on the remote x86 desktop. E0-LLM.6 consumes those results: it calibrates `prompt_budget`, makes the shortlist decision and measures gate contention through the production gate. It runs no second throughput spike.

### Build-DAG amendments

Story-level dependencies are the authority for build order (`build-waves.md`). They add three edges to the epic DAG in `epics-parallel-plan.md` §4:

- **A-1** E0-LLM.6 → E0-Platform.10. Both are Wave 0 epics, so this edge only orders work inside Phase 0.
- **A-2** E7.1 (Portal home and the `portalSections.ts` registry) comes before E3.4, E5.6, E9.5 and E10.4. E7.1 needs only Phase 0, so it is pulled forward to the first post-Phase-0 wave. E5 and E9 (minimum-launch Phase 1) therefore take E7.1 into Phase 1.
- **A-3** The E0-QA EV-4 probe stories (E0-QA.13, E0-QA.14) run after E0-Access and E0-LLM.5, as the plan's "EV-4 probes" node already showed. The rest of E0-QA is Wave 0.

## Boundary map additions

These files, tables and append points were introduced by the batches and are not in the spine's "Capability → Architecture Map". They are recorded here and **the spine is not edited**. CI-12's "one owner per table" check and reviewers should read the spine table plus this section.

### New shared append points (one line per epic, never restructured)

| Append point | Owner (creates it) | Appended by |
| --- | --- | --- |
| `components/portal/portalSections.ts` | E7 (E7.1) | E3.4, E5.6, E9.5, E10.4 |
| `components/entities/worldTabs.ts` (`registerWorldTab`) | E0-WorldCore (E0-WorldCore.10) | E3.4, E10.4 |
| `components/jobs/traySections.ts` (`registerTraySection`) | E0-Jobs (E0-Jobs.10) | E1.7 |
| `components/review/jobLabels.ts`, `registerAttentionProvider`, `registerFollowUp` (in `itemRenderers.ts`) | E1 (E1.5) | E2.4, E2.6, E10.7 |
| `lib/routes.ts` (route registry and redirects) | E0-UX (E0-UX.8) | every epic that adds a page (for example E0-WorldCore.10, E5.2 or E8.5, E7.1) |
| `access.register_resolver` (`access/registry.py`) | E0-Access (E0-Access.8) | E0-WorldCore.5, E2.1, E4.2 |
| `access.register_stale_marker`, `register_visibility_listener` | E0-Access (E0-Access.9) | E0-Jobs.8, E0-Journal.1 |
| `jobs/backfill.py` `register_backfill` | E0-Jobs (E0-Jobs.5) | E0-WorldCore.7, E1.8 |
| `app/clients/fakes.py` | E0-Platform (E0-Platform.3) | E0-Platform.5, E5.4 |
| `docs/BENCHMARKS.md` rows | E0-QA (E0-QA.15) | E0-Platform.10, E0-LLM.6, E1.10, E2.7, E3.6, E4.9, E5.7, E6.6, E7.9, E8.4, E10.2 |

### New files by owning epic

| Epic | New backend / infra files | New frontend files |
| --- | --- | --- |
| E0a | `tests/test_share.py`, `docs/RELEASE_NOTES.md` | — |
| E0-QA | `.github/workflows/gates.yml`, `.github/workflows/license-check.yml`, `.github/license-policy.toml`, `scripts/check-licenses.py`, `scripts/check_table_owners.py`, `scripts/check_memory_budget.py` (wires E0-Platform's `check_mem_limits.py`), `scripts/model_packages_baseline.txt`, `scripts/make_snapshot.py`, `scripts/eval_common.py`, `scripts/eval_spoiler.py`, `scripts/eval_benchmarks.py`, `seeds/ev4_canary.json`, `tests/ev4/{routes,families,fixtures,test_coverage}.py`, `tests/ev4/exemptions.yaml`, `tests/ev4/pending_baseline.txt`, `tests/migrations/test_upgrade_snapshot.py`, `tests/test_enum_check_sync.py`, `tests/test_migrations_match_models.py`, `docs/LICENSING.md`, `docs/EVAL_TEMPLATE.md`, `docs/SPOILER_EVAL.md` | — |
| E0-Platform | `app/clients/errors.py`, `app/clients/fakes.py`, `src/services/ml/`, `src/services/stt/`, `docker-bake.hcl`, `.github/workflows/images.yml`, `scripts/check_mem_limits.py`, `scripts/check_model_packages.py`, `scripts/sidecar_smoke.sh`, `scripts/restore-db.sh`, `scripts/spikes/spike5_memory.py`, `scripts/spikes/spike6_llm_throughput.py`, `docs/OCI_DEPLOYMENT.md`, `spikes/x86-desktop-benchmarks.md` | — |
| E0-Access | `app/access/{context,enums}.py`, `api/routes/visibility.py` (bulk Visibility, B1-D6), `scripts/backfill_party_embeddings.py`, `tests/access/test_registry_property.py` | `services/api/members.ts`, `types/members.ts` |
| E0-Jobs | `app/jobs/backfill.py`, `app/jobs/admission.py` | `components/jobs/JobTrayButton.tsx`, `components/jobs/traySections.ts`, `services/api/jobs.ts`, `types/jobs.ts` |
| E0-LLM | `scripts/bench_llm_gate.py`, `tests/fixtures/fake_llm.py`, `tests/integration/test_llm_structured_ollama.py`, `spikes/llm-throughput-decisions.md` | — |
| E0-Journal | `world_service.py` stub holding only `detach_entry` (ownership passes to E0-WorldCore, B2-D13) | `services/api/journals.ts` additions |
| E0-UX | `scripts/check-ui-tokens.mjs` | `contexts/PreviewContext.tsx`, `lib/{routes,layers,focusTrap,shortcuts,format}.ts`, `components/shell/{CampaignSwitcher,PreviewBanner,RouteAnnouncer,ShortcutHelp}.tsx`, `components/ui/{segmented-control,tabs,combobox,toast,empty-state,model-missing-notice,visibility-badge,secret-field,role-badge,skeleton,inline-error,offline-notice,field-visibility-hint}.tsx`, `hooks/{useCurrentCampaign,useEffectiveRole,useDebounce}.ts`, `pages/NotFoundPage.tsx` |
| E0-WorldCore | `app/hooks/world.py`, `app/jobs/world.py`, `docs/UPGRADING.md`, `tests/domain/test_entity_types.py` | `components/entities/{EntityCard,StatusBadge,HistoryList,MentionList,MergeDialog}.tsx`, `components/entities/worldTabs.ts`, `services/api/entities.ts`, `types/entities.ts` |
| E1 | `seeds/labels/extraction.json` | `components/review/{PostSaveCard,MentionsStrip,jobLabels}.ts(x)`, `pages/ReviewsPage.tsx`, `services/api/proposals.ts`, `types/proposals.ts` |
| E2 | `scripts/eval_continuity.py`, `seeds/labels/continuity.json` | `components/continuity/{ContinuityFlag,CanonNoteForm}.tsx`, `hooks/useContinuity.ts`, `services/api/continuity.ts` |
| E3 | Relationship CRUD routes `/api/relationships/` inside `relationship_types.py` (B4-D14) | `components/graph/{GraphToolbar,NodeLegend,GraphListView,RelationshipsSection}.tsx`, `hooks/{useGraph,useRelationships}.ts`, `services/api/graph.ts` |
| E4 | `src/services/diarize/` (optional `diarize` profile), `scripts/eval_live_captions.py`, `scripts/eval_recap_rolling.py`, `docs/LIVE_EVAL.md`, `spikes/diarization.md` | `lib/audio/pcmCaptureWorklet.ts`, `hooks/useLiveSession.ts`, `services/api/live.ts`, `types/live.ts` |
| E5 | `services/recap_service.py` (B6-3), `seeds/recap_labels.json`, `docs/RECAP_EVAL.md`; `app/clients/tts.py` (RC-5 exception to E0-Platform's `app/clients/*`) | `pages/KeepsakesPage.tsx` (shared with E8, RC-18), `components/recap/{RecapPlayer,RecapDraftPanel,NarratorPicker,LatestRecapCard}.tsx`, `hooks/useRecaps.ts`, `services/api/recaps.ts`, `types/recaps.ts` |
| E6 | `scripts/eval_npc_knowledge.py` | `components/npc/KnowledgeEditor.tsx`, `services/api/npcChat.ts`, `types/npcChat.ts` |
| E7 | `services/portal_service.py` (B4-D8), `scripts/demo_ds3.md`, `tests/ev4/test_ds3.py` | `pages/{PortalJournalPage,MyCharacterPage}.tsx`, `components/portal/{portalSections.ts,PlayerJournalComposer,PlayerJournalGMActions,MemberPcLinkCell}.tsx`, `components/visibility/BulkVisibilityBar.tsx`, `lib/preview.ts`, `services/api/visibility.ts` |
| E8 | `services/chronicle_epub.py` (B6-3), `templates/chronicle/{book,chapter,appendix}.html.j2`, `chronicle.css`, `assets/fonts/` + `OFL.txt`, `tests/test_no_ebooklib.py` | `components/chronicle/ChronicleExportPanel.tsx`, `hooks/useChronicle.ts`, `services/api/chronicle.ts`, `types/chronicle.ts` |
| E9 | `services/stats_service.py` (B6-3), `tests/test_stats_copy.py` | `pages/StatsPage.tsx`, `components/stats/{MilestoneCard,MilestoneSlot,MilestoneSettings,MilestoneList,AchievementBadge}.tsx`, `hooks/useStats.ts`, `services/api/stats.ts`, `types/stats.ts` |
| E10 | tile trees under `/data/files/{campaign_id}/map_tiles/{uuid}/` (RC-3) | `components/map/{LeafletMap,AuthedTileLayer,MapPin,PinList,MapViewer,PlacementBar,PinEditor,ReviewPinPositions,OnMapsSection,PlaceLocationFollowUp,PortalMapsCard}.tsx`, `services/api/maps.ts`, `types/maps.ts` |

### New tables and columns beyond the spine

| Owner | Table / column | Story | Note |
| --- | --- | --- | --- |
| E0-Access | `campaign_share_tokens.expires_at` (in F1-core) | E0-Access.1 | Expiry enforced in E0-Access.4 (B1-D3). |
| E0-Access (optional) | `npcs.visibility`, `quests.visibility` | E0-Access.14 | Only if the owner picks option B of OD-1. |
| E0-WorldCore | `relationship_types.hostile` | E0-WorldCore.2 | RC-13. |
| E0-WorldCore | `entities.deleted_at` (soft delete) | E0-WorldCore.2 | B3-D3. |
| E0-WorldCore | unique index on suggested `entity_mentions` (own small revision) | E0-WorldCore.7 | B3-D5. |
| E4 | `live_sessions.recap_points`, `recap_now`, `recap_through_seq` | E4.5 | B5-7: Rolling Recap stored on the session row. |
| E4 | `live_segments.speaker` (nullable) | E4.11 | Cuttable with FR-30. |
| E9 | `user_settings.achievements_enabled` (next to the spine's `streaks_enabled`) | E9.2 | B6-10. `user_settings` is an existing table; E9 owns only these two columns. |
| E10 | none beyond the spine (`maps`, `map_pins`, `map_pin_entries`) | E10.1, E10.3 | Tiles are one `stored_files` row per tree (RC-3). |

### Files more than one epic edits (non-owner touches)

Each is an additive mount or a class-only change, as the batch decisions record. These are what `build-waves.md` keeps apart within a wave.

- `pages/EntryDetailPage.tsx`: E0-Journal.4 (owner of the edit UI), E1.7, E2.4, E7.8 (one mount each).
- `components/journal/JournalInput.tsx`: E1.7 (post-save hook-in), E6.4 (copy to draft).
- `DashboardPage.tsx`, `SettingsPage.tsx`: E0-Jobs.10 (notifications toggle), E1.7, E9.5 (one mount each).
- `SharingPage.tsx`: E0-Access.12 (owner of Role controls), E7.4 (PC-link cell, B4-D9).
- `HistoryPage.tsx`: E7.6 (selection mode mount).
- `SharedCampaignPage.tsx`: E0a.2 (owner), E0-UX.2 (class-only colour change), E7.2 (delegates to `PortalPage mode="anon"`).
- `ChatPage.tsx`, `api/routes/chat.py`: E0-Access.8 (owner), E6.3 (NPC mode), E7.5 (Player Chronicler surface).
- `campaigns.py`: E0-Access.5, .12, .13 (owner); E8.1 and E9.1 replace handler bodies with delegations (B6-6).
- License tooling (`scripts/check-licenses.py`, `.github/license-policy.toml`): E0-QA (owner); E0-Platform.2 and E8.2 add policy lines.
- `components/NavBar.tsx`: E0-UX (owner); E0-Jobs.10 adds one tray mount line.

## Open owner decisions

- **OD-1 (open, recorded but not decided): legacy NPC/Quest visibility in the gap between the E0-Access and E0-WorldCore releases.** **Option A (current default, B1-D4):** legacy `npcs`/`quests` are `always_gm` from F1-core, so Players and Share Links see empty NPC and Quest lists until the GM publishes the copied Entities (bulk publish ships in E0-WorldCore.5/.10). The release notes must say so. **Option B:** a temporary `visibility` column on `npcs`/`quests`, defaulting to `party`, copied by F3-world. It is written up as the OPTIONAL story **E0-Access.14** ("pending owner decision"), with a conditional AC already in E0-WorldCore.2. To choose B, schedule E0-Access.14 inside the E0-Access release. To keep A, drop it.
- **OD-2 (open, from B1-D10):** whether to redistribute a GPU image under the NVIDIA EULA (`docs/LICENSING.md`).
- **OD-3 (owner action, E0-QA.9):** confirm or replace the three licence exceptions.
- **D-7 (resolved):** only `pages.yml` deploys GitHub Pages (PR #4, E0-QA.3 Done).

## Story count summary

| Epic | Stories | Of which Done | Optional |
| --- | --- | --- | --- |
| E0a | 2 | 1 | 0 |
| E0-QA | 15 | 3 | 0 |
| E0-Platform | 10 | 0 | 0 |
| E0-Access | 14 | 0 | 1 |
| E0-Jobs | 10 | 0 | 0 |
| E0-LLM | 6 | 0 | 0 |
| E0-Journal | 4 | 0 | 0 |
| E0-UX | 9 | 0 | 0 |
| E0-WorldCore | 11 | 0 | 0 |
| E1 | 10 | 0 | 0 |
| E2 | 7 | 0 | 0 |
| E3 | 6 | 0 | 0 |
| E4 | 11 | 0 | 0 |
| E5 | 7 | 0 | 0 |
| E6 | 7 | 0 | 0 |
| E7 | 9 | 0 | 0 |
| E8 | 5 | 0 | 0 |
| E9 | 5 | 0 | 0 |
| E10 | 7 | 0 | 0 |
| **Total** | **155** | **4** | **1** |
