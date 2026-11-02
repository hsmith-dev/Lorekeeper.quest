# Lorekeeper — Expansion Scope Input (owner-approved)

Owner: Harrison (capstone project). Date: 2026-10-31.
This file is the single source of truth for scope handed to every BMAD planning run. Owner approved ALL 10 features below.

## Product today (brownfield)
Self-hosted AI campaign companion for tabletop RPGs. Docker stack: FastAPI + SQLAlchemy + Alembic + Postgres/pgvector, Redis, Ollama (fine-tuned Lorekeeper-Mistral-7B GGUF), nginx; React + Vite + TS + Tailwind (shadcn-style ui) frontend. Existing: shorthand→narrative journal with review panel, hybrid RAG chat (vector + tsvector, measured relevance gate, retrieval trace, streaming, "not from your journal" labelling — see docs/RETRIEVAL_EVAL.md), session co-planner, co-writing suite (NPC bios, quest hooks, recaps), campaigns with membership + share tokens, NPC & quest tracking (flat records), character sheets (JSONB templates), tags, timeline, source ingestion (PDF/text chunks), voice recording + transcription, shorthand glossaries, analytics page, admin portal, optional per-user BYOK cloud model.

## Key gap observed
The world is not connected. NPCs/quests are standalone text rows related to journal entries only via tags. No Location/Faction/Item entities, no entity↔entry mention links, nothing updates as the story progresses.

## Hard constraints
- **Everything local.** No required external/cloud services. All new AI (LLM, STT, TTS, embeddings) runs in the Docker stack. New containers allowed. Cloud BYOK stays optional only.
- Must run on the documented baseline (~8 GB RAM, CPU-only acceptable; NVIDIA GPU optional). Heavy features must degrade gracefully on CPU (async jobs, progress, smaller models).
- Preserve the grounding ethos: AI outputs cite journal sources; human approves before canon changes.
- Brownfield: extend existing patterns (services/, api/routes/, Alembic migrations, hooks/, pages/), don't rewrite.
- Capstone: demo-ability and measurable evaluation matter (extend docs/RETRIEVAL_EVAL.md style metrics where AI is involved).

## The 10 features (all in scope)
1. **Living world model / auto-extraction** — on journal save, local LLM proposes entity changes (new NPC/Location/Faction/Item, status changes like "Mira → deceased", quest progress) as a reviewable diff the user approves. Adds Location, Faction, Item entities + entity-mention links to entries. FOUNDATION for 2, 3, 6, 7.
2. **Canon guard / continuity checker** — flags contradictions between a new entry and established canon (dead NPC reappears, location moved), citing the conflicting entries. Reuses retrieval + relevance gate.
3. **Relationship web** — interactive graph of PCs, NPCs, factions, locations, and their relationships.
4. **Live session mode** — streaming transcription during play, rolling recap, quick "who was that NPC?" lookup.
5. **Narrated "Previously on…" recaps** — genre-voiced recap with local TTS (e.g. Piper).
6. **Talk to an NPC** — roleplay chat in an NPC's voice, constrained to what that NPC plausibly knows.
7. **Player portal** — GM-only/secret flags on fields; players get a spoiler-filtered wiki and their own character journals. Builds on existing membership/sharing.
8. **Campaign chronicle export** — whole campaign as a formatted PDF/EPUB "book" (extends export_service).
9. **Milestones & stats** — session streaks, most-mentioned NPCs, quest completion rates, achievements (extends analytics).
10. **Map pins** — upload map images, drop pins linked to locations and entries.

Suggested sequencing (owner leaned this way, not locked): 1 first, then 2/3/6/7 which depend on it; 4/5/8/9/10 largely independent.

## Owner decisions (2026-10-31)
- **Extraction review (F1):** one grouped review checklist after save (New / Changed / Quest progress), approve/reject/edit per item plus "approve all"; extends NarrativeReviewPanel. Nothing becomes canon without approval.
- **NPC knowledge (F6):** default = facts from entries the NPC is linked to (via world-model mentions); GM can grant or hide specific facts/secrets per NPC.
- **Retcons (F2):** GM override of a contradiction flag is stored as a canon/retcon note with a reason; it becomes part of the record that later checks and chat retrieval consider.
- **Live STT (F4):** rolling ~10–30 s chunked transcription with a small Whisper model on CPU; the recap and NPC lookup refresh about every minute. Near-real-time is a GPU-only enhancement.
- Remaining open questions from the brief (default TTS voices/disk budget, migrating existing NPC/Quest rows into the entity model) are delegated to the PRD and architecture to propose defaults.
- **Licence correction:** the project is **AGPL-3.0** (LICENSE) dual-licensed with a commercial licence — not GPL-3.0 as earlier docs said. Dependency rule is unchanged: only permissive deps may be bundled, because the commercial edition must be distributable without copyleft obligations.

## Owner decisions — round 2 (2026-10-31)
- **Member role migration (PRD Q2):** existing members migrate to **Player** (privacy-first). Owner promotes co-GMs manually.
- **RAM baseline (PRD Q4):** **raise the documented baseline to 16 GB** — one simple profile. (Supersedes the 8 GB baseline in earlier docs; CPU-only still supported, GPU optional.)
- **TTS licence (PRD Q1):** decide after spike. Spike result (spikes/cpu-benchmarks.md): `pip install kokoro` bundles GPL-3.0 espeak-ng; with the fallback disabled, fantasy proper nouns are silently dropped from audio. → Kokoro+espeak is acceptable for the AGPL build as an optional container; the commercial build must not bundle it — use a TTS provider interface so the commercial build can swap in a permissive engine or browser speech.
- **Dev/test environment:** owner is moving development to a desktop machine with Docker. Tests should use docker-compose.dev.yml Postgres+pgvector (built from migrations).
- **Pages workflows:** pages.yml, static.yml, jekyll-gh-pages.yml all deploy to the same Pages site; static.yml publishes the whole repo. Pending owner decision (recommend keeping only pages.yml).

## Owner decisions — round 4 (2026-11-01)
- **Pre-publish history stays GM-only:** history rows (`entity_changes`) recorded while an Entity — or the specific field — was hidden from an audience stay hidden from that audience after it is published / un-hidden. Players see only changes made after publication. (Implement by recording the write-time audience on each history row and filtering on it, not on current visibility.)
- **Tighter CPU targets approved (NFR-6):** live caption lag on CPU ≤ 10 s (was ≤ 30 s); narration on CPU ≤ 60 s (was ≤ 2 min). Basis: E0-QA.15 x86 benchmarks (`docs/BENCHMARKS.md`).
- **Character Sheet stopgap:** until E7 links Players to their PCs, a Player may edit Character Sheets they themselves created (`created_by_user_id`), in Campaigns where they are a member. GM retains full control; preview/reduced contexts still refused.
- **Mac hygiene:** builder agents must not install into the owner's Homebrew/system prefixes or run local servers (pgvector files a builder added to Homebrew postgresql@16 were removed 2026-11-01).
