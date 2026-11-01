# Numeric alias for sprint_plan.py (generated)

## Epic 1: Share Links stop leaking GM content (P0 hotfix)

### Story 1.1: Share Links serve only player-visible fields

### Story 1.2: Exact-field share test, frontend Public types and release notes

## Epic 2: Trustworthy tests, CI gates and evaluation harness

### Story 2.1: Backend CI runs on `main`

### Story 2.2: Dependency licence gate for Python and npm packages

### Story 2.3: One GitHub Pages deployer

### Story 2.4: The test database URL can be overridden from the environment

### Story 2.5: Tests build the schema from Alembic migrations

### Story 2.6: Migration-chain gates, and CI with no path filters

### Story 2.7: Licence register and strict commercial mode

### Story 2.8: The licence check scans the Docker images we actually ship

### Story 2.9: Owner confirms or replaces the three licence exceptions

### Story 2.10: Structural CI gates: layers, model packages, table owners, enum sync, memory sum

### Story 2.11: EV-4 harness scaffolding: route enumeration, actors and probe families

### Story 2.12: Demo seed and the shared eval-script scaffold

### Story 2.13: EV-4 probes for every existing route

### Story 2.14: EV-4 is a zero-leak hard gate, with chat and captured-context probes

### Story 2.15: EV-5 benchmark suite and the x86 spike re-run

## Epic 3: Runs offline on one 16 GB box with models outside the web tier

### Story 3.1: Dev compose ports bind to localhost by default

### Story 3.2: CPU-only torch in the backend image (closes the NVIDIA wheel licence gap)

### Story 3.3: `ml` sidecar for embeddings and NER, with its client

### Story 3.4: `ml` lazy NLI and OCR under a resident-memory budget

### Story 3.5: `stt` sidecar with faster-whisper, and voice upload switched to it

### Story 3.6: Web and worker image without models: async client wrappers and lifespan cleanup

### Story 3.7: One 16 GB profile with container limits, GPU override and sum check

### Story 3.8: Per-user rate-limit keying in slowapi and nginx

### Story 3.9: Multi-arch images, upgrade-safe boot and OCI deploy

### Story 3.10: SPIKE-5 and SPIKE-6 re-run on the remote x86 desktop, limits confirmed

## Epic 4: Roles and one Visibility enforcement point

### Story 4.1: F1-core migration, with existing Members migrated to Player

### Story 4.2: `CampaignContext`, `require_campaign` and the Role map

### Story 4.3: Access registry, Audiences, `scoped_select` and `audience_ctx`

### Story 4.4: Party projections and a uniform 404 on existing read and write responses, including Share Links with expiry

### Story 4.5: Per-Campaign permission checks replace `accessible_campaign_ids` and inline owner checks

### Story 4.6: Players are locked out of GM authoring and AI routes, and write rules are enforced

### Story 4.7: Party-only search and retrieval using `party_tsv` and `party_embedding`

### Story 4.8: Player-safe Chronicler chat with `SourceRef` citations

### Story 4.9: `set_visibility`, the only Visibility writer

### Story 4.10: Grant changes bump `access_epoch` and close open streams

### Story 4.11: Campaign events route and `useCampaignEvents`

### Story 4.12: Members API and Roles in Sharing › Members

### Story 4.13: Analytics and export cover every Member, scoped by Role

### Story 4.14: OPTIONAL (pending owner decision OD-1): Legacy NPCs and Quests stay visible to Players during the upgrade gap

## Epic 5: Background Jobs with visible progress

### Story 5.1: F2-jobs-files revision and models

### Story 5.2: `enqueue` with outbox push and the kind registry

### Story 5.3: `LorekeeperWorker`: ctx rebuild, LLM config, retries and the worker service

### Story 5.4: Reaper and restart recovery

### Story 5.5: Queue priority, per-model serialisation, cursor backfills and Live admission

### Story 5.6: `core/pubsub.py` and `core/sse.py`

### Story 5.7: Job routes and the SSE stream

### Story 5.8: File service, access-checked file route and backups

### Story 5.9: `lib/sse.ts`, `useChat` migration and `useJobStream`

### Story 5.10: Job tray, Job rows, completion notices and the NavBar tray contract

## Epic 6: Reliable, prioritised local-LLM access with structured output

### Story 6.1: Typed LLM errors and one LLM-config resolver

### Story 6.2: One priority gate for the local LLM, and one fixed local model

### Story 6.3: Backend detection and prompt budgets

### Story 6.4: `complete_structured` with schema enforcement and at most two repairs

### Story 6.5: Deterministic fake LLM provider and the EV-4 context-capture hook

### Story 6.6: Act on SPIKE-6: calibrate prompt budgets, decide the extraction prompt shape, and measure gate contention

## Epic 7: Edit and delete Journal Entries safely

### Story 7.1: Hook dispatcher on `after_commit`

### Story 7.2: Journal writers recompute every index column

### Story 7.3: Edit and delete routes with Player rules and the delete contract

### Story 7.4: Entry edit and delete UI on the entry detail page

## Epic 8: A consistent, accessible app shell for the expansion

### Story 8.1: Semantic colour tokens and type roles in all six themes

### Story 8.2: Fix destructive-text contrast, migrate hardcoded colours, and gate them in CI

### Story 8.3: SlideOver focus trap, wide and full-screen variants, push header, and reduced motion

### Story 8.4: SegmentedControl, Tabs and Combobox primitives

### Story 8.5: Toast, EmptyState, ModelMissingNotice and shared state patterns

### Story 8.6: Spoiler-safety components and the Preview shell

### Story 8.7: Global current Campaign and the CampaignSwitcher

### Story 8.8: Nav restructure, route redirects, unified not-found and route announcements

### Story 8.9: Shortcut registry, help overlay and touch-target audit

## Epic 9: The world as Campaign-scoped Entities with history

### Story 9.1: Entity Type registry and closed-set enums

### Story 9.2: F3-world migration with the legacy NPC/Quest copy

### Story 9.3: `apply_change`, history and revert

### Story 9.4: Name matching with `normalize_name` and `match_names`

### Story 9.5: Entity API with GM and Party projections

### Story 9.6: Legacy NPC and Quest adapters and old-link resolver

### Story 9.7: Suggested Mentions backfill and Mention confirm/remove

### Story 9.8: Journal delete detaches the entry from the world

### Story 9.9: Merge two Entities

### Story 9.10: World hub, Entity page and panel, with bulk publish

### Story 9.11: Status, history, Mentions and merge on the Entity page

## Epic 10: The journal updates the world (extraction and Review Checklist)

### Story 10.1: Proposal tables and per-op payload schemas

### Story 10.2: Extraction service turns an entry into Change Proposals

### Story 10.3: `extraction.run` Job, save and edit hooks, and delete handling

### Story 10.4: Proposals API: checklist read, apply with re-check, undo

### Story 10.5: Review Checklist core, with grouped items, staging and Apply

### Story 10.6: Checklist at scale: filters, keyboard triage and local drafts

### Story 10.7: Post-save card, Reviews queue and entry Mentions strip

### Story 10.8: Re-run extraction for one entry or backfill the whole Campaign

### Story 10.9: Seeded demo Campaign with EV-1 labels

### Story 10.10: EV-1 extraction eval on the remote GPU desktop, and DS-1

## Epic 11: Canon guard catches continuity mistakes

### Story 11.1: Continuity Flag and Canon Note tables, and Canon Notes as a retrieval source

### Story 11.2: Continuity service: shared-Entity pairs, NLI, then a mandatory 7B confirmation

### Story 11.3: `continuity.check` Job, after extraction

### Story 11.4: Show Continuity Flags and dismiss them with a reason

### Story 11.5: Override a flag with a Canon Note (retcon)

### Story 11.6: Mark proposals that contradict Canon

### Story 11.7: EV-2 continuity eval on the remote GPU desktop, and DS-2

## Epic 12: See the relationship web

### Story 12.1: Relationship types and Relationship create, edit and end API

### Story 12.2: Graph endpoint filtered by access

### Story 12.3: Relationships section in the Entity panel, with Add, Edit and End forms

### Story 12.4: Graph canvas with a settled, persisted layout and live updates

### Story 12.5: Toolbar, search, filters, legend and the list view

### Story 12.6: Keyboard navigation, announcements, reduced motion and the 300-node performance check

## Epic 13: Live Session at the table

### Story 13.1: Start a Live Session and stream audio chunks to the server

### Story 13.2: One drainer transcribes chunks into captions and reports backlog

### Story 13.3: Live Session page with honest captions and a lag meter

### Story 13.4: Reconnect or refresh resumes the same Live Session with nothing lost

### Story 13.5: Rolling Recap of the session so far

### Story 13.6: Tap a name for its card, or ask the Chronicler, in under two seconds

### Story 13.7: End the session and turn the full transcript into a draft entry

### Story 13.8: Table view the players can read from across the table

### Story 13.9: Live Session evaluation: caption quality, Rolling Recap faithfulness and DS-4 part one

### Story 13.10: SPIKE-4, decide whether offline speaker labels ship

### Story 13.11: Optional offline speaker labels as a Job

## Epic 14: "Previously on…" narrated recaps

### Story 14.1: Draft and save a "Previously on…" recap with citations

### Story 14.2: Keepsakes page and the "Previously on…" tab

### Story 14.3: TTSProvider interface, build editions and the proper-noun guard

### Story 14.4: Kokoro narrator sidecar for the AGPL build

### Story 14.5: Narration Job, audio cache, invalidation and the Party audio route

### Story 14.6: RecapPlayer, Narrator choice and Table play

### Story 14.7: EV-6 recap faithfulness, Narrator listening test and DS-5 recap step

## Epic 15: Talk to an NPC

### Story 15.1: Compute an NPC's knowledge and scope retrieval to it

### Story 15.2: A GM's NPC Conversation streams in character from the NPC's knowledge

### Story 15.3: NPC Conversation screen with honest limits

### Story 15.4: Copy a line into a journal draft; conversations never change Canon

### Story 15.5: Grant or hide what an NPC knows

### Story 15.6: EV-3, measure whether NPCs leak what they shouldn't know

### Story 15.7: Let Players talk to chosen NPCs, with Party-only knowledge

## Epic 16: Player Portal

### Story 16.1: Portal home for Players at 375 px

### Story 16.2: Portal search and the read-only Share Link Portal

### Story 16.3: Player Journals, private by default

### Story 16.4: Link a Player to their PC, and the "My character" page

### Story 16.5: Player Chronicler limited to what the Player may see

### Story 16.6: GM bulk Visibility from list views, with derived-content notice

### Story 16.7: Preview as Player through the real read path

### Story 16.8: GM-triggered extraction of a Player Journal entry

### Story 16.9: DS-3 run, the EV-4 zero-leak gate for the Portal, and the portal load benchmark

## Epic 17: Campaign Chronicle export

### Story 17.1: Book model built through the visibility layer

### Story 17.2: WeasyPrint PDF with full Unicode, and fpdf2 removed

### Story 17.3: EPUB3 builder on zipfile and Jinja2, validated by EPUBCheck

### Story 17.4: Chronicle export Job, editions, download and staleness

### Story 17.5: Chronicle export panel on Keepsakes

## Epic 18: Milestones and stats

### Story 18.1: Campaign stats API computed per recipient

### Story 18.2: Opt-in Session Streaks with automatic grace

### Story 18.3: Achievements and Milestones with idempotent awards

### Story 18.4: Stats page with Achievements and Milestones

### Story 18.5: Milestone celebrations and personal milestone settings

## Epic 19: Maps and pins

### Story 19.1: Upload, rename, replace and delete Maps

### Story 19.2: Tile large Maps with libvips as a Job, and serve tiles

### Story 19.3: Pins with normalized positions and Visibility rules

### Story 19.4: Map list, Leaflet viewer and the keyboard PinList

### Story 19.5: GM pin placement, editing and moving

### Story 19.6: "On maps" and "Place on a map" from a Location

### Story 19.7: Offer to place a newly approved Location on a Map (FR-55)
