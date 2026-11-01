---
title: "Product Brief: Lorekeeper, from AI journal to living campaign world"
status: draft
created: 2026-10-31
updated: 2026-10-31
mode: headless-create
inputs:
  - _bmad-output/planning-artifacts/scope-input.md
  - README.md
  - site/index.html
  - docs/RETRIEVAL_EVAL.md
---

# Product Brief: Lorekeeper, from AI journal to living campaign world

## Executive Summary

Lorekeeper is an open-source, self-hosted AI companion for tabletop RPG groups. Today it does one job well: it turns terse session notes into narrative journal entries, and it answers questions about the campaign using only what was recorded. It cites its sources, and when the journal is silent it labels the reply "not from your journal" instead of inventing lore. A fine-tuned Mistral 7B, hybrid retrieval and a relevance gate tuned on a labeled eval set all run in one Docker stack on the owner's hardware.

The weakness is that the world isn't connected. NPCs and quests are standalone text rows. Locations, factions and items don't exist as entities, and nothing changes as the story moves on. Lorekeeper remembers what was written, but it doesn't model the world that writing describes.

This expansion is the owner's capstone. It turns Lorekeeper from an AI journal into a living campaign world. Each journal entry proposes updates to a structured world model, and the GM reviews and approves every one. That world model then powers a continuity checker, a relationship graph, in-character NPC conversation, a spoiler-safe player portal, and keepsakes like narrated recaps and an exported campaign "book". All of it runs locally, on CPU if it has to. No feature needs a cloud service.

## The Problem

- **GMs carry the world in their heads.** Who is dead, who owes whom, where the party left the artifact: this lives in scattered notes. The journal holds it as prose, but nothing pulls it out, so the GM still has to be the database. [ASSUMPTION: drawn from the product's premise and common GM pain points, not from user interviews]
- **Continuity breaks quietly.** A dead NPC turns up again, or a town moves across the map. Nobody notices until a player does.
- **Players disengage between sessions.** They have no safe way to browse the world without seeing GM secrets, no place for their own character journal, and nothing that pulls them back before the next session.
- **The engagement loop ends at "save entry."** Once an entry is written, it does nothing more for the group. Campaigns go on for months or years, and a record that just sits there gets abandoned.
- **Existing tools force a trade-off.** Worldbuilding wikis are manual and mostly cloud-hosted. AI tools are cloud-first and can't show where an answer came from. A privacy-minded group that wants AI help has to give up either grounding or control of its data.

## The Solution: four themes, ten features

**A. World model backbone** (the foundation; built first)
1. **Living world model / auto-extraction.** When an entry is saved, the local LLM proposes a reviewable diff: new NPCs, locations, factions or items; status changes ("Mira → deceased"); quest progress. Entries are linked to the entities they mention. Nothing becomes canon until a human approves it.
2. **Canon guard.** Flags contradictions between a new entry and established canon and cites the conflicting entries. It reuses the existing retrieval and relevance gate.
3. **Relationship web.** An interactive graph of PCs, NPCs, factions and locations, and the relationships between them.

**B. At the table**
4. **Live session mode.** Transcription streams during play. It keeps a rolling recap and gives a one-tap answer to "who was that NPC?"
6. **Talk to an NPC.** In-character chat, limited to what that NPC could plausibly know.
10. **Map pins.** Upload a map image and drop pins linked to locations and journal entries.

**C. Player-facing**
7. **Player portal.** Any field can be flagged GM-only or secret. Players get a spoiler-filtered wiki and their own character journals. This builds on the existing campaign membership and share tokens.

**D. Keepsakes and retention**
5. **Narrated "Previously on…"** A recap in the campaign's genre voice, spoken by local TTS (for example, Piper).
8. **Campaign chronicle export.** The whole campaign as a formatted PDF or EPUB "book", built on the existing export service.
9. **Milestones and stats.** Session streaks, most-mentioned NPCs, quest completion rates and achievements, added to the existing analytics page.

Features 2, 3, 6 and 7 depend on feature 1. Features 4, 5, 8, 9 and 10 are largely independent. That build order is the owner's current preference and isn't locked.

## What Makes This Different

- **Everything local.** The LLM, speech-to-text, TTS and embeddings all run inside the Docker stack. A group's campaign never leaves its machine, and there's no per-token cost. As far as the owner knows, the major campaign managers and AI GM tools are hosted services. [UNVERIFIED: competitor notes are from general knowledge; see the addendum]
- **Grounded, not generative.** Lorekeeper's existing rule carries over to every new feature: cite the journal, say so when the record is silent, and require human approval before canon changes. Most AI tools generate fluent lore. Lorekeeper is built to avoid making things up.
- **The world maintains itself.** In World Anvil, Kanka or LegendKeeper, the GM builds and updates the wiki by hand. Here, writing the session journal is what updates the world model.
- **Evaluated, not just demoed.** The retrieval layer already has published, reproducible metrics (hit@3 14/16, gate-holds 5/5 at the production threshold). The new AI features get the same treatment.
- **Honest limits.** None of this is a deep moat. The advantages are the local-first architecture, the grounding discipline and the integration of features. A 7B model on CPU is slow, and features have to be designed around that.

## Who This Serves

- **Primary: the GM-archivist.** Runs a long campaign for a home group of 3–6 players and is comfortable running Docker. Needs to stop being the group's memory, catch continuity mistakes, and prep faster. Success: the world model stays current without hand-editing, and a "who was that?" mid-session gets answered in seconds. [ASSUMPTION]
- **Secondary: the engaged player.** Wants to look back at the story, keep a character journal and question NPCs between sessions, without running into GM secrets. Success: opens the portal between sessions.
- **Tertiary: the self-hosting tinkerer and the capstone reviewer.** Evaluates the project by whether it is easy to set up, whether it runs on modest hardware, and whether its evaluation can be reproduced.

## Success Criteria

These signals can be measured on a self-hosted capstone with no adoption telemetry. Targets are placeholders until baselines exist. [ASSUMPTION]

- **Extraction quality (F1):** precision and recall of proposed entity changes against a labeled set on the seeded demo campaign, plus the GM acceptance rate of proposed diffs.
- **Canon guard:** detection rate on seeded contradictions and false-alarm rate on clean entries. Every flag cites the conflicting entry.
- **NPC knowledge boundary:** the rate at which NPC chat leaks facts the NPC shouldn't know, measured with probe questions.
- **Spoiler safety:** zero GM-only fields reachable through player routes, enforced by automated tests. This is a hard gate, not a target.
- **Local performance:** latency and memory on the 8 GB CPU-only baseline. Heavy jobs run asynchronously with visible progress. Live-session transcription lag stays within an acceptable bound (bound to be set).
- **Demo scenarios:** four end-to-end scripted runs on the demo campaign: (1) save an entry, approve the diff, and see the graph update; (2) write a contradiction and get it flagged with citations; (3) a player logs in and sees no spoilers; (4) generate a narrated recap and export the chronicle, all with the network disconnected.

## Scope

**In:** the ten features above, built on existing patterns (services/, api/routes/, Alembic migrations, hooks/, pages/). New local containers are allowed (for example, TTS). The existing optional BYOK cloud model stays optional.

**Out:**
- Required cloud services, hosted SaaS or sync
- Virtual tabletop functions (tokens, combat, dice, line of sight). Foundry and other VTTs cover these.
- Native mobile apps
- Rules engines and system-specific automation
- AI image and map generation
- Real-time collaborative co-editing
- A content marketplace
- Rewriting the existing architecture [ASSUMPTION: these exclusions are inferred from the constraints and a capstone-sized scope]

## Vision

A group's campaign becomes a living, private world that keeps itself current. The GM writes up the session as usual. The world updates, continuity stays intact, and players explore their own spoiler-safe view of it. Years later, the group has a narrated, illustrated chronicle of a story they told together, and none of it ever left the table.

## Open Questions

1. What does an entity-change diff look like in the UI, and how does the GM review it when one entry produces many proposals?
2. How does the NPC knowledge boundary get defined: from the entries where the NPC appears, explicit GM tags, or both?
3. What is the canon model for retcons? Can the GM deliberately override a canon-guard flag, and is that override recorded?
4. What latency budget is acceptable for live session mode on CPU, and should streaming transcription fall back to chunked batch?
5. Which TTS voices and genre "narrators" ship by default, and how much disk do they add to the image?
6. How is existing flat NPC and quest data migrated into the new entity model?
