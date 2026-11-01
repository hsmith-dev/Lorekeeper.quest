---
status: final
created: 2026-10-31
source: _bmad-output/planning-artifacts/epics.md (story Dependencies lines)
companions: [epics.md, epics-parallel-plan.md, epics-validation-report.md, ../implementation-artifacts/sprint-status.yaml]
---

# Build waves: what can be built in parallel worktrees

This is the implementation order for the 155 stories in `epics.md`, derived from the story dependency graph. A **wave** is a set of stories that can be built at the same time, each in its own git worktree, because:

1. every hard dependency of every story in the wave is in an earlier wave, and
2. no two stories in the wave edit the same owned file or create or alter the same table. Shared append points (`App.tsx`, `NAV_GROUPS`, `main.py` includes, `hooks/__init__.py`, `jobs/registry.py`, `access/registry.py`, `SourceKind`, `locations.conf`, `licenses/register.yaml`, `itemRenderers.ts`, `panelSections.ts`, `portalSections.ts`, `worldTabs.ts`, `traySections.ts`, `lib/routes.ts`, `app/clients/fakes.py`, `docs/BENCHMARKS.md`, `.env.example`, `tests/ev4/probes/`) take one-line additions and don't count as conflicts. Everything else uses the file lists in the stories and in `epics.md` "Boundary map additions".

**How it was computed.** `Dependencies` lines were parsed into 559 hard edges (text after "Soft:" is not an edge) and sorted topologically (no cycles). Each story goes in the earliest wave after its dependencies. If it shares a file with a story already in that wave, it moves to the next wave. Feature epics (E1 to E10) don't start before the **Phase 0 exit gate** (parallel plan §4.1: EV-4 green, SPIKE-5 memory verified, x86 spikes recorded). The four Done stories (E0a.1, E0-QA.1, E0-QA.2, E0-QA.3) are treated as merged.

**Reading the waves.** A wave is a ceiling on parallelism, not a quota. The 16 GB box runs worktrees with fakes (`JOBS_EAGER=1`, fake LLM, client fakes) and one test database per worktree (`lorekeeper_test_<lane>`). A practical cap is 4 to 6 concurrent worktrees, plus at most one EV or benchmark run at a time (parallel plan §4.3). Stories marked *migration* add an Alembic revision. When more than one is in a wave, they merge **one at a time** through the serialized queue, each rebasing `down_revision` onto the current head (CI-6 single head). E0a.2 merges and ships first as its own release. E0-Access ships as one release unit (FR-7 with FR-9(b)), after E0-Access.13.

**Tags:** *migration* = adds a revision; *cut n* = position in the PRD §9 cut order (first cut first); *never cut* = PRD §9.

**29 waves.** Phase 0 is waves 1 to 19 (the last Phase 0 story is in wave 19). The Phase 0 exit gate sits between wave 19 and wave 20. Feature waves are 20 to 29.


## Wave 1

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0a.2 | Exact-field share test, frontend Public types and release notes | `SharedCampaignPage.tsx`, `share.py` | never cut |
| E0-QA.4 | The test database URL can be overridden from the environment | `backend-tests.yml` |  |
| E0-QA.7 | Licence register and strict commercial mode | `check-licenses.py`, `license-check.yml`, `license-policy.toml` |  |
| E0-Platform.1 | Dev compose ports bind to localhost by default | `docker-compose.dev.yml`, `docker-compose.prod.yml`, `docker-compose.yml` |  |
| E0-Platform.8 | Per-user rate-limit keying in slowapi and nginx | `limiter.py`, `nginx.conf` |  |
| E0-LLM.1 | Typed LLM errors and one LLM-config resolver | `deps.py`, `errors.py` |  |
| E0-UX.1 | Semantic colour tokens and type roles in all six themes | `*.ts`, `arcane.ts`, `cyberpunk.ts`, `dnd.ts` … |  |

## Wave 2

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.5 | Tests build the schema from Alembic migrations | `docker-compose.dev.yml`, `env.py` |  |
| E0-Platform.2 | CPU-only torch in the backend image (closes the NVIDIA wheel licence gap) | `check-licenses.py`, `license-check.yml`, `license-policy.toml` |  |
| E0-LLM.2 | One priority gate for the local LLM, and one fixed local model | `llm_gate.py`, `pubsub.py` |  |
| E0-UX.3 | SlideOver focus trap, wide and full-screen variants, push header, and reduced motion | `NpcDetailPanel.tsx`, `QuestDetailPanel.tsx`, `focusTrap.ts`, `index.css` … |  |
| E0-UX.4 | SegmentedControl, Tabs and Combobox primitives | `button.tsx`, `combobox.tsx`, `segmented-control.tsx`, `tabs.tsx` … |  |
| E0-UX.5 | Toast, EmptyState, ModelMissingNotice and shared state patterns | `empty-state.tsx`, `format.ts`, `inline-error.tsx`, `model-missing-notice.tsx` … |  |

## Wave 3

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.6 | Migration-chain gates, and CI with no path filters | `backend-tests.yml`, `license-check.yml`, `make_snapshot.py` |  |
| E0-QA.9 | Owner confirms or replaces the three licence exceptions | `LICENSING.md`, `license-policy.toml` |  |
| E0-QA.12 | Demo seed and the shared eval-script scaffold | `EVAL_TEMPLATE.md`, `RETRIEVAL_EVAL.md`, `demo_campaign.json`, `eval_<name>.py` … |  |
| E0-Platform.3 | `ml` sidecar for embeddings and NER, with its client | `docker-compose.prod.yml`, `docker-compose.yml`, `embedding.py`, `embedding_service.py` … |  |
| E0-LLM.3 | Backend detection and prompt budgets | `prompt_budget.py` |  |
| E0-UX.6 | Spoiler-safety components and the Preview shell | `PreviewBanner.tsx`, `PreviewContext.tsx`, `button.tsx`, `field-visibility-hint.tsx` … |  |

## Wave 4

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.8 | The licence check scans the Docker images we actually ship | `LICENSING.md`, `license-check.yml`, `license-policy.toml` |  |
| E0-QA.10 | Structural CI gates: layers, model packages, table owners, enum sync, memory sum | `ARCHITECTURE-SPINE.md`, `check_memory_budget.py`, `check_model_packages.py`, `check_table_owners.py` … |  |
| E0-QA.15 | EV-5 benchmark suite and the x86 spike re-run | `.memlog.md`, `cpu-benchmarks.md`, `eval_benchmarks.py` |  |
| E0-Platform.4 | `ml` lazy NLI and OCR under a resident-memory budget | `ml.py` |  |
| E0-Platform.5 | `stt` sidecar with faster-whisper, and voice upload switched to it | `docker-compose.gpu.yml` |  |
| E0-LLM.4 | `complete_structured` with schema enforcement and at most two repairs | `llm_provider.py`, `research-decisions-summary.md` |  |
| E0-UX.2 | Fix destructive-text contrast, migrate hardcoded colours, and gate them in CI | `AdminPage.tsx`, `CharactersPage.tsx`, `ChatPage.tsx`, `EntryDetailPage.tsx` … |  |
| E0-UX.7 | Global current Campaign and the CampaignSwitcher | `CampaignSelector.tsx`, `CampaignSwitcher.tsx`, `useCurrentCampaign.ts`, `useEffectiveRole.ts` |  |

## Wave 5

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.11 | EV-4 harness scaffolding: route enumeration, actors and probe families | `<feature>.py`, `ev4_canary.json`, `families.py`, `fixtures.py` … | never cut |
| E0-Platform.6 | Web and worker image without models: async client wrappers and lifespan cleanup | `RETRIEVAL_EVAL.md`, `admin.py`, `check_model_packages.py`, `ml.py` |  |
| E0-LLM.5 | Deterministic fake LLM provider and the EV-4 context-capture hook | `fake_llm.py`, `llm_provider.py` |  |
| E0-UX.8 | Nav restructure, route redirects, unified not-found and route announcements | `NotFoundPage.tsx`, `RouteAnnouncer.tsx` |  |
| E0-WorldCore.1 | Entity Type registry and closed-set enums | `achievements.py`, `embedding.py`, `entity_types.py`, `narrators.py` |  |

## Wave 6

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Platform.7 | One 16 GB profile with container limits, GPU override and sum check | `check_mem_limits.py`, `docker-compose.prod.yml` |  |
| E0-Access.1 | F1-core migration, with existing Members migrated to Player | — | migration, never cut |
| E0-UX.9 | Shortcut registry, help overlay and touch-target audit | `ShortcutHelp.tsx`, `shortcuts.ts` |  |

## Wave 7

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Platform.9 | Multi-arch images, upgrade-safe boot and OCI deploy | `OCI_DEPLOYMENT.md`, `deploy-oci.sh`, `docker-bake.hcl`, `images.yml` … |  |
| E0-Platform.10 | SPIKE-5 and SPIKE-6 re-run on the remote x86 desktop, limits confirmed | `.memlog.md`, `spike5_memory.py`, `spike6_llm_throughput.py` |  |
| E0-Access.2 | `CampaignContext`, `require_campaign` and the Role map | `check_scoped_queries.py`, `context.py`, `members.py`, `members.ts` … | never cut |

## Wave 8

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.3 | Access registry, Audiences, `scoped_select` and `audience_ctx` | `audience.py` | never cut |
| E0-LLM.6 | Act on SPIKE-6: calibrate prompt budgets, decide the extraction prompt shape, and measure gate contention | `.memlog.md`, `bench_llm_gate.py` |  |

## Wave 9

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.4 | Party projections and a uniform 404 on existing read and write responses, including Share Links with expiry | `<domain>.py`, `campaigns.py`, `character_sheets.py`, `journals.py` … | never cut |
| E0-Access.7 | Party-only search and retrieval using `party_tsv` and `party_embedding` | `backfill_party_embeddings.py` | never cut |
| E0-Jobs.1 | F2-jobs-files revision and models | `errors.py` | migration |

## Wave 10

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.6 | Players are locked out of GM authoring and AI routes, and write rules are enforced | — | never cut |
| E0-Access.8 | Player-safe Chronicler chat with `SourceRef` citations | `chat.py`, `chat_service.py` | never cut |
| E0-Access.9 | `set_visibility`, the only Visibility writer | `check_scoped_queries.py`, `visibility.py` | never cut |
| E0-Jobs.2 | `enqueue` with outbox push and the kind registry | — |  |

## Wave 11

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.5 | Per-Campaign permission checks replace `accessible_campaign_ids` and inline owner checks | `campaigns.py`, `check_scoped_queries.py`, `gates.yml`, `tags.py` | never cut |
| E0-Access.10 | Grant changes bump `access_epoch` and close open streams | `pubsub.py` | never cut |
| E0-Access.14 | OPTIONAL (pending owner decision OD-1): Legacy NPCs and Quests stay visible to Players during the upgrade gap | — | migration, OPTIONAL, OD-1, never cut |
| E0-Jobs.3 | `LorekeeperWorker`: ctx rebuild, LLM config, retries and the worker service | `docker-compose.prod.yml`, `docker-compose.yml`, `worker.py` |  |

## Wave 12

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.13 | Analytics and export cover every Member, scoped by Role | `campaigns.py` | never cut |
| E0-Jobs.4 | Reaper and restart recovery | `enqueue.py`, `worker.py` |  |
| E0-Jobs.6 | `core/pubsub.py` and `core/sse.py` | `pubsub.py`, `sse.py` |  |
| E0-Journal.1 | Hook dispatcher on `after_commit` | `<feature>.py` |  |

## Wave 13

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-Access.11 | Campaign events route and `useCampaignEvents` | `events.py`, `pubsub.py`, `sse.py`, `sse.ts` … | never cut |
| E0-Access.12 | Members API and Roles in Sharing › Members | `SharingPage.tsx`, `campaigns.py`, `members.py`, `members.ts` … | never cut |
| E0-Jobs.5 | Queue priority, per-model serialisation, cursor backfills and Live admission | `admission.py`, `backfill.py` |  |
| E0-Jobs.7 | Job routes and the SSE stream | `jobs.py` |  |
| E0-Journal.2 | Journal writers recompute every index column | `hashNotes.ts`, `ml.py` |  |

## Wave 14

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.13 | EV-4 probes for every existing route | `campaigns.py`, `character_sheets.py`, `ingest.py`, `journals.py` … | never cut |
| E0-Jobs.8 | File service, access-checked file route and backups | `DATABASE_BACKUPS.md`, `file_service.py` |  |
| E0-Jobs.9 | `lib/sse.ts`, `useChat` migration and `useJobStream` | `jobs.ts`, `sse.ts`, `useChat.ts`, `useJobStream.ts` |  |
| E0-Journal.3 | Edit and delete routes with Player rules and the delete contract | `world_service.py` |  |
| E0-WorldCore.2 | F3-world migration with the legacy NPC/Quest copy | `entity.py` | migration |

## Wave 15

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-QA.14 | EV-4 is a zero-leak hard gate, with chat and captured-context probes | `SPOILER_EVAL.md`, `chat.py`, `eval_spoiler.py`, `gates.yml` | never cut |
| E0-Jobs.10 | Job tray, Job rows, completion notices and the NavBar tray contract | `JobTrayButton.tsx`, `NavBar.tsx`, `SettingsPage.tsx` |  |
| E0-Journal.4 | Entry edit and delete UI on the entry detail page | `EntryDetailPage.tsx`, `journals.ts` |  |
| E0-WorldCore.3 | `apply_change`, history and revert | `check_scoped_queries.py`, `entities.py`, `pubsub.py`, `world.py` … |  |
| E0-WorldCore.4 | Name matching with `normalize_name` and `match_names` | — |  |

## Wave 16

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-WorldCore.5 | Entity API with GM and Party projections | `entities.py` |  |

## Wave 17

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-WorldCore.6 | Legacy NPC and Quest adapters and old-link resolver | `CharactersPage.tsx`, `NpcDetailPanel.tsx`, `QuestDetailPanel.tsx`, `QuestsPage.tsx` … |  |
| E0-WorldCore.7 | Suggested Mentions backfill and Mention confirm/remove | `world.py` | migration |
| E0-WorldCore.9 | Merge two Entities | — |  |

## Wave 18

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-WorldCore.8 | Journal delete detaches the entry from the world | — |  |
| E0-WorldCore.10 | World hub, Entity page and panel, with bulk publish | `EntityDetailPanel.tsx`, `NpcDetailPanel.tsx`, `SlideOver.tsx`, `entities.ts` … |  |

## Wave 19

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E0-WorldCore.11 | Status, history, Mentions and merge on the Entity page | `EntityCard.tsx`, `EntryDetailPage.tsx`, `HistoryList.tsx`, `MentionList.tsx` … |  |

---

> **Phase 0 exit gate** (after wave 19): EV-4 zero-leak gate green (E0-QA.14), AD-7 memory verified (E0-Platform.10, SPIKE-5), x86 spikes recorded (E0-QA.15, E0-Platform.10), NFR-6 targets reset. Feature lanes start below.

---


## Wave 20

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.1 | Proposal tables and per-op payload schemas | `proposal.py`, `proposals.py` | migration |
| E3.1 | Relationship types and Relationship create, edit and end API | — |  |
| E4.1 | Start a Live Session and stream audio chunks to the server | `live.py`, `live_session_service.py`, `pubsub.py` | migration, cut 6 (all E4) |
| E5.1 | Draft and save a "Previously on…" recap with citations | `recap_service.py`, `recaps.py` | migration |
| E5.3 | TTSProvider interface, build editions and the proper-noun guard | `demo_campaign.json`, `narrators.py`, `stt.py`, `tts_service.py` |  |
| E6.1 | Compute an NPC's knowledge and scope retrieval to it | `npc_chat.py`, `npc_chat_service.py` | migration, cut 7 (all E6) |
| E7.1 | Portal home for Players at 375 px | `PortalPage.tsx` |  |
| E9.1 | Campaign stats API computed per recipient | `campaigns.py`, `entity_types.py`, `stats.py`, `stats_service.py` |  |
| E10.1 | Upload, rename, replace and delete Maps | `DATABASE_BACKUPS.md`, `ingest.py`, `map_service.py`, `maps.py` | migration, cut 4 (all E10) |

## Wave 21

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.2 | Extraction service turns an entry into Change Proposals | `extraction.py`, `extraction_service.py` |  |
| E2.1 | Continuity Flag and Canon Note tables, and Canon Notes as a retrieval source | `continuity.py`, `continuity_service.py` | migration |
| E3.2 | Graph endpoint filtered by access | `graph.py` |  |
| E3.3 | Relationships section in the Entity panel, with Add, Edit and End forms | `EntityDetailPanel.tsx`, `RelationshipsSection.tsx`, `useRelationships.ts` |  |
| E4.2 | One drainer transcribes chunks into captions and reports backlog | `docker-compose.gpu.yml`, `stt.py` | migration, cut 6 (all E4) |
| E5.2 | Keepsakes page and the "Previously on…" tab | `KeepsakesPage.tsx`, `RecapDraftPanel.tsx`, `recaps.ts`, `sse.ts` … |  |
| E5.5 | Narration Job, audio cache, invalidation and the Party audio route | `recap.py`, `recaps.py` |  |
| E6.2 | A GM's NPC Conversation streams in character from the NPC's knowledge | `chat.py`, `entity_types.py` | cut 7 (all E6) |
| E7.2 | Portal search and the read-only Share Link Portal | `SharedCampaignPage.tsx` |  |
| E7.3 | Player Journals, private by default | `PlayerJournalComposer.tsx`, `PortalJournalPage.tsx`, `player_journals.py` |  |
| E7.6 | GM bulk Visibility from list views, with derived-content notice | `BulkVisibilityBar.tsx`, `HistoryPage.tsx`, `visibility.ts` |  |
| E9.2 | Opt-in Session Streaks with automatic grace | `achievement_service.py`, `achievements.py`, `settings.py`, `stats.py` | migration, cut 5 (FR-50/51) |
| E10.2 | Tile large Maps with libvips as a Job, and serve tiles | `file_service.py`, `maps.py` | cut 4 (all E10) |
| E10.3 | Pins with normalized positions and Visibility rules | — | migration, cut 4 (all E10) |

## Wave 22

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.3 | `extraction.run` Job, save and edit hooks, and delete handling | `extraction.py` |  |
| E2.2 | Continuity service: shared-Entity pairs, NLI, then a mandatory 7B confirmation | `continuity.py` |  |
| E3.4 | Graph canvas with a settled, persisted layout and live updates | `RelationshipWebPage.tsx` |  |
| E4.3 | Live Session page with honest captions and a lag meter | `LiveSessionPage.tsx`, `RecordSessionPage.tsx`, `live.ts`, `liveSocket.ts` … | cut 6 (all E4) |
| E5.4 | Kokoro narrator sidecar for the AGPL build | `cpu-benchmarks.md`, `docker-compose.dev.yml`, `docker-compose.prod.yml`, `errors.py` … |  |
| E5.6 | RecapPlayer, Narrator choice and Table play | `NarratorPicker.tsx`, `RecapPlayer.tsx`, `useNarration.ts` |  |
| E6.3 | NPC Conversation screen with honest limits | `ChatPage.tsx`, `npcChat.ts`, `sse.ts`, `useNpcChat.ts` | cut 7 (all E6) |
| E7.4 | Link a Player to their PC, and the "My character" page | `MemberPcLinkCell.tsx`, `MyCharacterPage.tsx`, `SharingPage.tsx` |  |
| E8.1 | Book model built through the visibility layer | `appendix.html.j2`, `book.html.j2`, `campaigns.py`, `chapter.html.j2` … |  |
| E9.3 | Achievements and Milestones with idempotent awards | `achievement_service.py`, `achievements.py`, `stats.py` | migration, cut 5 (FR-50/51) |
| E10.4 | Map list, Leaflet viewer and the keyboard PinList | `LeafletMap.tsx`, `MapsPage.tsx`, `mapCoords.ts`, `maps.ts` … | cut 4 (all E10) |

## Wave 23

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.4 | Proposals API: checklist read, apply with re-check, undo | `extraction_service.py`, `proposals.py` |  |
| E2.3 | `continuity.check` Job, after extraction | `PostSaveCard.tsx`, `continuity.py`, `extraction.py` |  |
| E3.5 | Toolbar, search, filters, legend and the list view | `GraphListView.tsx`, `GraphToolbar.tsx`, `NodeLegend.tsx` |  |
| E4.4 | Reconnect or refresh resumes the same Live Session with nothing lost | `live.py`, `liveSocket.ts`, `useLiveSession.ts` | cut 6 (all E4) |
| E5.7 | EV-6 recap faithfulness, Narrator listening test and DS-5 recap step | `<NAME>_EVAL.md`, `RECAP_EVAL.md`, `demo_campaign.json`, `eval_<name>.py` … |  |
| E6.4 | Copy a line into a journal draft; conversations never change Canon | `JournalInput.tsx` | cut 7 (all E6) |
| E6.5 | Grant or hide what an NPC knows | `KnowledgeEditor.tsx`, `npc_chat.py` | cut 7 (all E6) |
| E7.5 | Player Chronicler limited to what the Player may see | `ChatPage.tsx`, `chat.py`, `portal_service.py` |  |
| E7.7 | Preview as Player through the real read path | `preview.ts`, `sse.ts` |  |
| E8.2 | WeasyPrint PDF with full Unicode, and fpdf2 removed | `chronicle.css`, `license-policy.toml` |  |
| E9.4 | Stats page with Achievements and Milestones | `AchievementBadge.tsx`, `AnalyticsPage.tsx`, `MilestoneList.tsx`, `StatsPage.tsx` … |  |
| E10.5 | GM pin placement, editing and moving | `mapCoords.ts`, `{PlacementBar,PinEditor,ReviewPinPositions}.tsx` | cut 4 (all E10) |

## Wave 24

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.5 | Review Checklist core, with grouped items, staging and Apply | `JournalInput.tsx`, `NarrativeReviewPanel.tsx`, `RecordSessionPage.tsx`, `ReviewChecklist.tsx` … |  |
| E1.9 | Seeded demo Campaign with EV-1 labels | `demo_campaign.json`, `epics.md`, `extraction.json`, `seed_demo.py` |  |
| E3.6 | Keyboard navigation, announcements, reduced motion and the 300-node performance check | `graph.py`, `relationships.py` |  |
| E4.5 | Rolling Recap of the session so far | `live.py` | cut 6 (all E4) |
| E8.3 | EPUB3 builder on zipfile and Jinja2, validated by EPUBCheck | `chapter.html.j2`, `chronicle.css`, `chronicle_epub.py`, `chronicle_service.py` |  |
| E9.5 | Milestone celebrations and personal milestone settings | `DashboardPage.tsx`, `MilestoneCard.tsx`, `MilestoneSettings.tsx`, `MilestoneSlot.tsx` … | cut 5 (FR-50/51) |
| E10.6 | "On maps" and "Place on a map" from a Location | `EntityDetailPanel.tsx`, `MapsPage.tsx`, `OnMapsSection.tsx` | cut 4 (all E10) |

## Wave 25

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.6 | Checklist at scale: filters, keyboard triage and local drafts | — |  |
| E1.7 | Post-save card, Reviews queue and entry Mentions strip | `DashboardPage.tsx`, `EntryDetailPage.tsx`, `JournalInput.tsx`, `MentionsStrip.tsx` … |  |
| E4.6 | Tap a name for its card, or ask the Chronicler, in under two seconds | — | cut 6 (all E4) |
| E6.6 | EV-3, measure whether NPCs leak what they shouldn't know | `NPC_KNOWLEDGE_EVAL.md`, `demo_campaign.json`, `eval_npc_knowledge.py`, `eval_retrieval.py` | cut 7 (all E6) |
| E8.4 | Chronicle export Job, editions, download and staleness | `chronicle.py` |  |
| E10.7 | Offer to place a newly approved Location on a Map (FR-55) | `PlaceLocationFollowUp.tsx` | cut 2 (FR-55) |

## Wave 26

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E2.4 | Show Continuity Flags and dismiss them with a reason | `ContinuityFlag.tsx`, `EntryDetailPage.tsx`, `ReviewChecklist.tsx`, `continuity.py` … |  |
| E4.7 | End the session and turn the full transcript into a draft entry | `NarrativeReviewPanel.tsx`, `live.py` | cut 6 (all E4) |
| E4.8 | Table view the players can read from across the table | — | cut 6 (all E4) |
| E6.7 | Let Players talk to chosen NPCs, with Party-only knowledge | `NPC_KNOWLEDGE_EVAL.md`, `npc_chat.py` | cut 3 (FR-39) |
| E7.9 | DS-3 run, the EV-4 zero-leak gate for the Portal, and the portal load benchmark | `SPOILER_EVAL.md`, `demo_campaign.json`, `demo_ds3.md`, `seed_demo.py` |  |
| E8.5 | Chronicle export panel on Keepsakes | `ChronicleExportPanel.tsx`, `chronicle.ts`, `useChronicle.ts` |  |

## Wave 27

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.8 | Re-run extraction for one entry or backfill the whole Campaign | `EntryDetailPage.tsx`, `extraction.py` |  |
| E2.5 | Override a flag with a Canon Note (retcon) | `CanonNoteForm.tsx` |  |
| E4.9 | Live Session evaluation: caption quality, Rolling Recap faithfulness and DS-4 part one | `LIVE_EVAL.md`, `RECAP_EVAL.md`, `eval_live_captions.py`, `eval_recap_rolling.py` | cut 6 (all E4) |
| E4.10 | SPIKE-4, decide whether offline speaker labels ship | — | cut 1 (FR-30) |

## Wave 28

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E1.10 | EV-1 extraction eval on the remote GPU desktop, and DS-1 | `EXTRACTION_EVAL.md`, `RETRIEVAL_EVAL.md`, `eval_extraction.py`, `eval_retrieval.py` |  |
| E2.6 | Mark proposals that contradict Canon | — |  |
| E4.11 | Optional offline speaker labels as a Job | `diarize.py` | migration, cut 1 (FR-30) |
| E7.8 | GM-triggered extraction of a Player Journal entry | `EntryDetailPage.tsx`, `PlayerJournalGMActions.tsx` |  |

## Wave 29

| Story | Title | Files it edits (from the story text; append points excluded) | Tags |
| --- | --- | --- | --- |
| E2.7 | EV-2 continuity eval on the remote GPU desktop, and DS-2 | `CONTINUITY_EVAL.md`, `RETRIEVAL_EVAL.md`, `continuity.json`, `demo_campaign.json` … |  |


## Capstone cut line (PRD §9)

**Minimum launch** = Phase 0 (waves 1 to 19), then E1, E5, E8 and E9, then E2, E3 and E7. That covers DS-1, DS-2, DS-3 and DS-5. In the schedule above the minimum-launch stories finish in **wave 29**. The critical path has no slack: E0-QA.4 → E0-QA.5 → E0-QA.6 → E0-QA.10 → E0-QA.11 → E0-Access.1 → E0-Access.2 → E0-Access.3 → E0-Jobs.1 → E0-Jobs.2 → E0-Jobs.3 → E0-Jobs.4 → E0-Jobs.5 → E0-WorldCore.2 → E0-WorldCore.4 → E1.1 → E1.2 → E1.3 → E1.4 → E1.5 → E1.7 → E2.4 → E2.5 → E2.6 → E2.7. So cutting stories narrows waves 20 to 29 but doesn't shorten the schedule. Spend the freed worktrees on that chain and on the E7 lane (DS-3).

**E7.1 is pulled into Phase 1** (amendment A-2): E5.6 and E9.5 register their Portal sections in `portalSections.ts`, which E7.1 creates, so E7.1 is built in the first feature wave even though E7 is a Phase 2 epic.

**Cut order, first cut first** (each cut removes whole stories):

| # | Cut | Stories removed |
| --- | --- | --- |
| 1 | FR-30 diarization | E4.10, E4.11 |
| 2 | FR-55 place-on-map offer | E10.7 |
| 3 | FR-39 Player NPC chat | E6.7 |
| 4 | all of E10 | E10.1 to E10.6 (and E10.4's Portal maps card) |
| 5 | FR-50 and FR-51 in E9 | E9.2, E9.3, E9.5 (E9.4 then shows Stats only) |
| 6 | all of E4 | E4.1 to E4.9 |
| 7 | all of E6 | E6.1 to E6.6 |

**Never cut:** E0-Access, E0a and the EV-4 harness in E0-QA (E0-QA.11, .13, .14).

Cutting E4, E6 or E10 removes no dependency of any minimum-launch story. The only cross-lane hard edges after Phase 0 are E1 → E2, E1 → E7.8, E1.5 → E10.7, and E7.1 → E3.4, E5.6, E9.5 and E10.4 (all checked in `epics-validation-report.md`).

## Optional story

E0-Access.14 (owner decision OD-1, option B) is placed in the wave its dependencies allow. If the owner picks option B, it must merge **inside the E0-Access release and before E0-WorldCore.2** (the F3-world copy reads its column). If option A stays, drop it. Nothing depends on it.
