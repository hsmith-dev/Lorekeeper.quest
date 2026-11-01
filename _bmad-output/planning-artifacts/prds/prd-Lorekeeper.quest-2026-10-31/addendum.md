---
title: "Addendum: Lorekeeper living campaign world PRD"
created: 2026-10-31
updated: 2026-10-31
---

# Addendum

This addendum holds detail for architecture, UX and stories that would clutter the PRD. Nothing here overrides an FR. Technology picks come from `research-decisions-summary.md` (numbers in brackets are that research's citations), and brownfield facts come from `brownfield-context.md`. Package versions must be re-checked from 2026-11-01. **Caveat:** the research's claims ledger shows 3 verified and 33 single-source claims, so treat every performance and RAM figure below as unverified until SPIKE-1 to SPIKE-6 measure it on x86. The first Apple-silicon measurements (`spikes/cpu-benchmarks.md`, summarised in PRD §8) supersede the research figures where they conflict.

## A. Mechanism picks per requirement

| PRD item | Recommended mechanism | Runner-up / rejected |
|---|---|---|
| FR-1, FR-2 Jobs | A worker container on the existing Redis (arq or RQ), with concurrency 1 per heavy model and progress reported over SSE in the existing `ollama_service.install_model_events` pattern. Job rows persist status in Postgres so they survive a Redis flush. | FastAPI `BackgroundTasks` (dies with the worker, no restart survival). |
| FR-3 Structured output | Ollama `format` with a JSON schema [1][2], kept flat (enums, `additionalProperties:false`, no anyOf or $ref [3]), temperature 0. Extend `llm_provider.complete_messages` with an optional schema argument, and add a validate, repair and retry layer. For relations, write free text first, then convert it to JSON [4]. | Grammar-constrained generation through llama.cpp directly. |
| FR-13, FR-14 Extraction and matching | The prompt carries the schema plus the current Entity list. Resolution goes through the alias table, then a RapidFuzz plus embedding top-5 shortlist, then LLM adjudication for borderline cases [8]. The existing spaCy NER can seed candidates. | GLiNER v2.1 (Apache-2.0, 209M) as a CPU NER pre-pass. **Avoid the GLiNER v0/v1 weights (NC, non-commercial)** [7]. |
| FR-19 Continuity | Claim-to-canon sentence pairs scored with `cross-encoder/nli-deberta-v3-xsmall` by default (batched at 32; base only if EV-2 shows a clear gain), aggregated SummaC-style [13]. Only pairs that share an Entity are scored. Contradictions with p ≥ ~0.9 go to the 7B, which verifies them and checks for flashback framing. The spike found a p = 0.99 false contradiction on a neutral pair sharing an Entity, so this confirm step is mandatory. Run the cross-encoder as ONNX or OpenVINO int8 [17]. Candidates come from `retrieval_service.hybrid_search_journal` plus Entity state. | The 7B as sole judge (no reliability evidence). DeBERTa-v3-large NLI on a GPU (MIT) [12]. **Avoid MiniCheck-7B (NC)** [16]. |
| FR-26 to FR-30 Live STT | **Owner decision first:** 10–30 s chunked transcription on CPU (chunked POST, or a WebSocket carrying chunks). Replace openai-whisper with **faster-whisper `base`** for live use, 15 s chunks, compute type configurable (`int8` default, `float32` override). The spike measured 1.6–3.7× faster than openai-whisper base and 39–49% less memory; `small` failed the live chunk budget with int8 and is offered only for batch transcription. Seed name accuracy with an `initial_prompt` from the Entity list (untested). faster-whisper has had no release in about 12 months, so whisper.cpp is the fallback if SPIKE-2 finds problems. The research's streaming design (2–4 s CPU lag, unverified) is the candidate for the near-real-time enhancement, and SPIKE-2 tests whether it is viable on CPU at all: a WebSocket taking AudioWorklet PCM16 at 16 kHz, Silero VAD and LocalAgreement-2 (the WhisperLive/WhisperLiveKit pattern [24][25]), in a separate `stt` container that also serves the existing `/api/ingest/voice` path. nginx needs a new location with Upgrade headers. Diarization: pyannote community-1 offline after the session [31]. | whisper.cpp (MIT, least RAM) [21]. Diarization: sherpa-onnx [35]. Chunked POST plus SSE as a fallback transport if WebSocket proves fragile behind nginx. |
| FR-31 to FR-34 TTS | **Kokoro-82M** (kokoro-onnx or the Kokoro-FastAPI CPU image) as a `tts` sidecar. 54 voices, with weighted blending for genre Narrators [36][37]. The model is about 300 MB, or 80 MB quantized [38]. The first chunk on CPU takes about 1 to 3.5 s [37]. | Chatterbox Nano (MIT, 110M, output always watermarked) [45][46]. **Rejected: Piper (now GPL-3.0) [47], XTTS-v2 (CPML, NC), F5-TTS (NC)** [42][43]. The brief's "e.g. Piper" no longer fits the licence constraint. |
| FR-24 Graph | **Sigma.js 4.0.4 + graphology + @react-sigma/core 6** (WebGL, ForceAtlas2 in a worker, Louvain clusters) [52][53][54], about 94 KB gz. | react-force-graph-2d (MIT, Canvas) [49][51]. Not React Flow (DOM nodes) [57]. |
| FR-45 to FR-48 Chronicle | One Jinja HTML/CSS source. **WeasyPrint** for PDF (margin boxes, `target-counter` TOC, `string-set` headers) [69]. A stdlib `zipfile` EPUB3 writer validated with EPUBCheck. A bundled Unicode font with an OFL licence. | Typst via typst-py (no EPUB) [71]. **Rejected: EbookLib (AGPL) [70], Pandoc (GPL, large image) [72]**, and the existing fpdf2 core font (Latin-1 only). |
| FR-52 to FR-54 Maps | **Plain Leaflet 1.9.4** with an in-house React wrapper and `CRS.Simple`. Pins are stored as image pixel `[y, x]` [61]. pyvips `dzsave` DeepZoom tiles for large maps [65]. Files on a new named volume. | OpenLayers 10 [63][64]. **Rejected: react-leaflet (Hippocratic-2.1, v5 needs React 19)** [58][59]. |
| FR-36 NPC Knowledge | An `npc_knowledge(entity, entry_or_field, how: mention/grant/hide)` link table populated from Mentions, plus GM grant and hide rows. Retrieval is filtered to those entries, using exact search with a B-tree pre-filter or the pgvector ≥ 0.8 iterative scan [73]. Prompt follows Character Card V2. The in-character "if it isn't in your memories, you don't know" rule is re-injected after the history every turn [80][78], matching the brownfield finding that the 7B ignores anti-hallucination notes placed in the system prompt. | RoleRAG-style graph retrieval [77]. |
| FR-49 to FR-51 Stats | An `activity_events` log, pure rule functions and `UNIQUE(user, campaign, achievement)` for idempotent awards. Streaks count Sessions played, with automatic grace. Messaging favours celebration over loss [81][82][84]. Add `completed_at` to Quest. | Achievements only, no streaks. |

## B. Brownfield extension points (from recon §9)

- **Data:** a unified `entity` table with a type enum, or one table per type (decide in architecture), plus `entity_alias`, `entity_mention` (journal_id, quote, confidence, confirmed), `entity_relationship`, `change_proposal` (op, target, field, old/new, source journal_id, status), `canon_note`, `continuity_flag`, `npc_knowledge`, `map`, `map_pin`, `job`, `activity_events`, `campaign_achievement`. Add `campaign_members.role`, plus `visibility` on journal entries, entities, relationships, sources, maps and pins, and a `secret_fields` mechanism. The migration chain continues after head `a3e7c1f9d258`. Check hand-typed revision IDs for collisions, and register new models in `models/__init__.py` and `migrations/env.py`.
- **Services:** `extraction_service`, `continuity_service`, `tts_service`, `live_session_service`, `chronicle_service` (extends `export_service`), `achievement_service`, and a `visibility` helper in `api/deps.py` (role-aware `get_campaign_role` and a query filter).
- **Job identity:** a Job resolves the owning GM's LLM configuration when it runs (the `get_user_llm_config` order), reads BYOK keys from `UserSettings` at that point and never from the queue payload, and calls `record_hosted_usage` after hosted completions.
- **Routes:** `entities.py`, `proposals.py`, `live.py`, `maps.py`, `portal.py` (or an extended `share.py`), plus the graph endpoint. Every AI route copies the `get_user_llm_config`, `get_campaign_with_access` and `record_hosted_usage` pattern and gets both slowapi and an nginx `ai_gen` `location =` block. SSE needs `X-Accel-Buffering: no`.
- **Frontend:** `EntityDiffReviewPanel` (keeps the `NarrativeReviewPanel` look, copy and draft-then-commit contract, rendering typed grouped items), entity pages cloned from `NpcDetailPanel`/`SlideOver`, `RelationshipWebPage`, `LiveSessionPage` (extending `RecordSessionPage`), `MapsPage`, `PortalPage`, and role-aware `NavBar`. Pages use named exports with the `lazy` adapter and theme tokens only.

## C. P0 leak detail (FR-9, FR-8)

Code line references are in `reconcile-brownfield.md` §A.

- `api/routes/share.py`: `/{token}/journals` and `/{token}/journals/{id}` serialize `shorthand`. `/{token}/npcs` and `/{token}/quests` serialize `notes`. Fix with share-specific response schemas that omit these fields, then add the Visibility filter once FR-8 lands.
- Chat: `hybrid_search_journal(campaign_id=…)` returns all campaign entries. Embeddings and `narrative_tsv` index Shorthand + Narrative, so GM notes influence retrieval even when they aren't printed. `source_service.retrieve_canon_context` exposes uploaded module text. The SSE `meta` event returns the full system prompt in the trace. For Players: filter candidates by Visibility, drop Shorthand from the context, filter sources and strip the trace. A narrative-only embedding for Player retrieval is required in Phase 0 (see the Lexical oracles bullet).
- Chat response payload: `chat.py:226-249` puts the full Shorthand in every `JournalSource` and the first 120 characters of Shorthand in every `RetrievalCandidate`, including candidates that were gated out. Both go out in the response and in the SSE `meta` event. Use Player-specific schemas with no `shorthand` field rather than blanking it. The glossary is injected into every chat prompt (`chat.py:263-266`).
- Lexical oracles: `narrative_tsv` indexes Shorthand + Narrative (migration `a3e7c1f9d258`). `/npcs/{id}/entries` and `/quests/{id}/entries` match `shorthand ILIKE` and return `JournalLiteResponse` with Shorthand. For Players, match on Narrative-only text, using a second tsvector or `to_tsvector(narrative)` at query time, and a narrative-only embedding (Phase 0, not a later refinement).
- Routes that check access against every campaign the user can reach (`accessible_campaign_ids`), rather than one: journal list, get-by-id, tag attach and detach, delete, and `tags.py` counts. Replace them with a role-aware `{campaign_id: role}` map.
- Authoring and AI routes that must be GM-only, closed to Players: `npcs/{id}/generate`, `npcs/extract`, `quests/{id}/generate`, `quests/suggest`, `journals/recap|summarize-session|autocomplete|reindex`, `session-plans/generate`, source upload and delete.
- Records that have no Visibility today: Session Plans, Character Sheets, `ShorthandTerm`, Tag Categories, and chat sessions (`ChatSession`, which are replayed as history).
- Write responses (`PUT /npcs`, `PUT /quests`) serialize `notes`, so writes must use the filtered serializer.
- Redis `cache:journals:{user_id}` is keyed by user rather than by role, so invalidate it when a role changes.
- Stored files must be served with nginx `internal` + `X-Accel-Redirect` after a backend check, never from a static volume path.

## D. Memory budget notes (NFR-2, SPIKE-5)

Recon measured the **backend web tier only**: 4 gunicorn workers, each loading spaCy `en_core_web_trf` and MiniLM (with Whisper and EasyOCR loaded lazily in each worker), at about 6.4 GB idle and about 11.9 GB peak at boot. Ollama is capped at `14g`, and the 7B Q4 is about 4.4 GB. The fine-tuned and base models already use both slots of `OLLAMA_MAX_LOADED_MODELS=2`.

Candidate mitigations for SPIKE-5 to test:

- A "baseline profile" with 2 web workers.
- Moving spaCy and the embedding model into the worker container (loaded once).
- Swapping `en_core_web_trf` for `en_core_web_sm` in the baseline profile.
- `OLLAMA_MAX_LOADED_MODELS=1` with only the fine-tuned model in the baseline.
- Lazy STT, TTS and NLI sidecars that unload when idle.
- Ollama `keep_alive` tuned so the 7B unloads between Rolling Recap updates if a Live Session cannot otherwise fit.

Estimated added cost per new model (unverified, from research):

- NLI cross-encoder: 0.3–0.8 GB.
- faster-whisper: base int8 < 1 GB, small int8 about 1.5 GB.
- Kokoro: about 80–300 MB plus runtime.
- pyannote (offline, transient): to be measured.
- GLiNER pre-pass (if adopted): about 0.5 GB.
- pyvips tiling of a 16,000 px map (transient): to be measured.

A Live Session's worst case is STT plus the 7B at the same time, which is the NFR-2 case that SPIKE-5 must prove.

**Update 2026-10-31 (owner decision).** The Reference Box is now 16 GB with one CPU-only profile (GPU optional), and the sum of container limits stays at or below 14.5 GB. The per-container split lives in the architecture spine (AD-7). First measured peaks from `spikes/cpu-benchmarks.md` (Apple M5 Max, 4 threads, n=1; re-run on x86):

- NLI xsmall 844 MB, base 1.14 GB.
- faster-whisper base 754–912 MB; small int8 1.19 GB, small float32 1.82 GB (small is not used live).
- Kokoro (torch package) about 1.3–1.4 GB idle, about 2.1 GB per sentence, 3.9 GB per paragraph (paragraph calls are ruled out).

The research's Kokoro estimate (80–300 MB plus runtime) was far too low.

## E. Default Narrator proposal (FR-33, §11)

Map genres to Kokoro voice presets (exact voice IDs chosen after SPIKE-3 listening tests): fantasy uses a warm British-English male or female blend, sci-fi a neutral American voice, horror a low, slower-rate voice, and video game a brighter, faster-rate voice. Other uses the fantasy preset. Speed and blend weights are stored per preset. Disk: the quantized model is about 80 MB and full precision about 300 MB, and the voice packs are small. A budget of ≤ 500 MB leaves headroom for a second model. These presets apply to the AGPL build's Kokoro container. The commercial edition has no local Narrators until a permissive engine passes the proper-noun test (PRD FR-33). One untested candidate is a non-GPL pronunciation path: a lexicon of Entity names passed to Kokoro as inline phoneme overrides.

## F. Licence register seed (NFR-4)

| Dependency | Licence | Commercial-build status |
|---|---|---|
| Ollama / llama.cpp | MIT | OK |
| RapidFuzz | MIT | OK |
| nli-deberta-v3 cross-encoders | Apache-2.0 | OK |
| faster-whisper (code and weights) | MIT | OK |
| Silero VAD | MIT (not sourced in research) | Verify the licence of the exact version |
| pyannote community-1 | Code MIT, weights CC-BY-4.0 (gated) | OK with attribution. Offline install needs a pre-downloaded bundle. |
| Kokoro-82M weights | Apache-2.0 | OK |
| kokoro-onnx / Kokoro-FastAPI / misaki (code) | To verify (reported MIT/Apache) | LIC-1 confirms |
| espeak-ng (bundled by `espeakng-loader`, pulled in by both `kokoro` and kokoro-onnx; misaki's out-of-vocabulary fallback) | GPL-3.0+ | **Excluded** from the commercial build (owner decision). The AGPL build ships it only inside the optional `tts` container. Without it, fantasy proper nouns are silently dropped. |
| arq or RQ (job runner) | To verify (reported MIT / BSD-2) | Verify before adoption |
| Pango, HarfBuzz, cairo (WeasyPrint system libraries) | LGPL-2.1+ / MIT, dynamically linked | Allowlist with a note |
| Book font (for example Noto Serif or EB Garamond) | SIL OFL 1.1 | OK (OFL permits embedding) |
| Sigma.js, graphology, @react-sigma | MIT | OK |
| WeasyPrint | BSD | OK |
| Leaflet | BSD-2 | OK |
| pyvips / libvips | MIT / LGPL-2.1 (dynamic; not sourced in research) | Review: LGPL dynamic linking is generally acceptable, so put it on the allowlist with a note |
| pgvector | PostgreSQL | OK |
| Rejected | Piper (GPL-3.0), XTTS-v2 (CPML), F5-TTS (NC), MiniCheck-7B (NC), GLiNER v0/v1 (NC), EbookLib (AGPL), Pandoc (GPL), react-leaflet (Hippocratic-2.1) | — |

## G. Eval harness notes

- Each eval doc follows `docs/RETRIEVAL_EVAL.md`: method, results table across operating points, chosen point with reason, a "measured failure → fix" table and a reproduce command (`docker compose -f docker-compose.prod.yml exec backend python scripts/eval_<name>.py --campaign-id <uuid>`).
- The demo campaign seed (9 entries: Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker) is not in the repo yet. Commit it as a fixture with added entries for status changes, contradictions and traps.
- Test-infrastructure gaps to plan for: route tests don't run the lifespan (Redis, spaCy and MiniLM aren't loaded), there is no fake LLM provider (add a deterministic stub for CI), and the frontend has no test runner (EV-4 runs against the API).

## H. UX defaults proposed for open UX questions (provisional)

The orchestrator proposed these defaults for the UX spec's open questions on 2026-10-31, and the owner did not object. They are provisional: they hold until the owner revisits them, and they change no FR.

- **Campaign switcher.** One app-wide campaign switcher, rather than a switcher per page.
- **Navigation.** Characters and Quests fold into a single **World** area, and Analytics is renamed **Stats**. Old routes redirect to their new homes (consistent with FR-5's legacy-link rule).
- **Themes.** The 6 built-in themes are the contract that new UI must support (NFR-10). Custom themes are not in scope.
- **Preview as Player.** The GM's "Preview as Player" starts as a generic Player view (Party content only). A per-Player preview (including one Player's Private content and PC) can come later.
- **Notifications.** Browser notifications (for example, Job done or Review Checklist ready) are opt-in and off by default.
