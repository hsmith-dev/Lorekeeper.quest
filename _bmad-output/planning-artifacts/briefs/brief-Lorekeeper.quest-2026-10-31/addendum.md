---
title: "Addendum: Lorekeeper living campaign world brief"
created: 2026-10-31
updated: 2026-10-31
---

# Addendum

This addendum holds material for downstream documents (PRD, architecture) that is too detailed for the brief.

## Current product baseline (brownfield)

The current stack is FastAPI, SQLAlchemy and Alembic, with Postgres and pgvector, Redis, Ollama serving the fine-tuned Lorekeeper-Mistral-7B as a Q4 GGUF, and nginx. The frontend is React, Vite, TypeScript and Tailwind.

Existing backend services include `retrieval_service`, `chat_service`, `export_service`, `transcription_service` (openai-whisper), `embedding_service` (sentence-transformers, 384-dim), `nlp_service`, `dedup_service` and `eval_service`. NPCs and quests are flat records, linked to journal entries only through tags.

## Feature dependencies

| # | Feature | Depends on | Reuses |
|---|---|---|---|
| 1 | Living world model | none | ai_service, nlp_service, dedup_service, journal save hook |
| 2 | Canon guard | 1 | retrieval_service plus the relevance gate (≤0.65) |
| 3 | Relationship web | 1 | new entity and relationship tables |
| 4 | Live session mode | none (better with 1 for NPC lookup) | transcription_service (whisper) |
| 5 | Narrated recap | none | existing recap co-writer; new Piper TTS container |
| 6 | Talk to an NPC | 1 | chat_service, retrieval scoped to entries mentioning the NPC |
| 7 | Player portal | 1 for entity-level secrets | campaign membership, share tokens |
| 8 | Chronicle export | none (richer with 1) | export_service |
| 9 | Milestones and stats | none (richer with 1) | analytics page |
| 10 | Map pins | richer with 1 (Location entity) | file upload |

## Eval sketches (following the RETRIEVAL_EVAL.md method)

- **Extraction:** hand-label the expected entity changes for each of the 9 seeded demo entries, then report precision, recall and F1 per change type (new entity, status change, quest progress). The demo data needs a few added entries with deliberate status changes.
- **Canon guard:** seed about 5 contradictions (a dead NPC who reappears, a moved location, an item held by two characters) and about 5 clean controls. Report the detection rate, the false-alarm rate, and citation correctness, i.e. whether the cited entry is the actual source of the conflict.
- **NPC knowledge boundary:** for each of 3 NPCs, write probe questions about facts the NPC witnessed and facts it never encountered. Report the answer rate on the first set and the leak rate on the second.
- **Spoiler safety:** an automated test that walks every player-scoped API route and asserts that no GM-only field is serialized. The target is a hard zero.
- **Performance:** wall-clock time and peak RSS for extraction, NPC chat turns, TTS per 100 words, and transcription real-time factor, on the 8 GB CPU-only baseline and optionally on a GPU.

## Competitive notes (UNVERIFIED, from general knowledge, no research run)

| Tool | Shape | Relevance |
|---|---|---|
| World Anvil | Hosted worldbuilding wiki with campaign manager features; freemium | Rich but manual. Cloud-hosted. Has player-facing secrets. |
| Kanka | Hosted campaign manager with entities, relations and maps; open-source core (self-hosting reportedly possible but not the main path) | Closest entity model (characters, locations, organisations, items, relations). Manual entry. |
| LegendKeeper | Hosted wiki, map and whiteboard tool | Strong maps and atlas. Manual. Cloud. |
| Foundry VTT | Self-hosted virtual tabletop with journals and a module ecosystem | Self-hosted, but a VTT rather than a campaign memory. AI help comes through third-party modules, often cloud-backed. A possible future integration target, not a competitor to copy. |
| AI GM / campaign tools (various) | Cloud LLM chat for lore, NPCs and recaps | Fluent output, usually ungrounded and cloud-only. Lorekeeper's case against them rests on grounding plus local operation. |

Validation is needed before any public claim. Run `bmad-deep-recon` (market) if the competitive section has to hold up to scrutiny.

## Persona depth

- **GM-archivist:** writes shorthand right after a session, about 10 minutes per session today. They would accept a short review step if it saves prep time later. Skeptical of AI that invents facts, which is the existing product's core promise.
- **Player:** uses a phone or laptop between sessions and reaches the app through a share link or membership. Wants to see their own character's story and the NPCs they've met, and nothing the GM is hiding.

## Local-runtime constraints to carry into architecture

- 8 GB RAM baseline. The LLM (~4.4 GB), embeddings, whisper and TTS can't all stay resident at once. Plan for model swapping or a job queue (Redis is already present) and for progress UI.
- Streaming transcription on CPU may need a smaller whisper model, or a faster-whisper/whisper.cpp variant, with chunked fallback.
- Piper voices are small (tens of MB each) and run well on CPU [UNVERIFIED].
