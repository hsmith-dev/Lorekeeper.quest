---
title: "Adversarial review: PRD Lorekeeper living campaign world"
reviewed: prd.md, addendum.md (2026-10-31 draft)
date: 2026-10-31
---

# Adversarial review

**Verdict:** Not ready for architecture or epics. The zero-leak privacy gate (NFR-5) is not achievable as specified: the Visibility model has gaps, the extraction defaults launder GM-only Shorthand into Party records, and EV-4 cannot detect several leak classes. On top of that, the Reference Box requirement is already known to be false, and the scope has no cut line for a solo capstone.

Counts: **8 critical, 16 high, 17 medium, 9 low.**

---

## Critical

### C1. Extraction turns GM-only Shorthand into Party Canon by default
FR-13 says the extraction Job "reads it" (the Journal Entry), and a Journal Entry is "GM **Shorthand** … plus the **Narrative**" (§3). FR-8 then says "One from a Party entry creates Party records whose GM notes are Secrets." Shorthand is where a GM writes "Mira is secretly the traitor" or "Aldric dies offscreen". Extracted from a Party entry, that becomes a Party status change ("alive → deceased"), a Party Relationship ("member of Lantern cult"), or a Party alias. A status, a Relationship or an alias is not a "GM note", so the Secret default does not cover it. With "Approve all" (FR-15) a GM can publish it in one click. The Mention quote (FR-12) can also be a Shorthand span, and it is shown on the Entity panel.
**Fix:** Each proposal records which text it came from (Shorthand or Narrative). Anything sourced from Shorthand, or from any GM-only field, defaults to GM-only, and the Review Checklist shows a visible "from GM notes" badge. Mention quotes inherit the Visibility of their source field. Add EV-4 cases: a canary placed only in Shorthand must never appear in Party Entities, statuses, aliases, Relationships or quotes after Approve all.

### C2. The Visibility model doesn't cover every kind of record, and has no rule for references between records
FR-8 lists "Journal Entry, Entity, Relationship, Canon Note, source document, Map and Pin". It leaves out Mentions and their quotes, aliases, Entity change history (FR-16), Quest steps, Sessions, Narrated Recaps (FR-34 assumes they have Visibility), NPC Conversation history (FR-38), Live Session transcripts and Rolling Recaps, Milestones and Achievements, Jobs, and the NPC Knowledge grant and hide rows. "Designated fields can be Secrets" never names the fields: can status, aliases, description or Relationship type be Secret? Canon Notes have no default Visibility at all. Yet UJ-2's reason, "resurrected by the Lantern cult", is a spoiler, and FR-21 puts Canon Notes into Entity history and chat retrieval. There is also no rule for a Party record that points at a GM-only one: a Party Relationship whose other end is a GM-only Entity, a Party Pin linked to a GM-only Location, a Party entry highlighting a Mention of a GM-only Entity (FR-12), or an FR-16 history row linking to a GM-only source entry. FR-25 forbids revealing hidden nodes in the graph only.
**Fix:** Add a Visibility table that lists every record type and every field that can be Secret, each with its default. Make Canon Notes GM-only by default. Add a general rule: "A Party record that references a GM-only record is filtered for Players, or the reference is removed. A Player never sees a dangling reference, a placeholder or a redacted marker." Every new record type must state its Visibility in its FR.

### C3. Derived artifacts don't follow later Visibility changes
FR-41: "A Visibility change takes effect on the next read, with no caching window that leaks." But plenty of content is generated before the GM marks something GM-only, and it keeps the facts:
- saved Narrated Recap text and cached audio (FR-31, FR-32)
- Player NPC Conversation history (FR-38)
- Rolling Recaps
- generated Player-edition files (FR-47)
- Party Entities derived from the entry (FR-8 inheritance applies only at creation)
- embeddings and `narrative_tsv`

Re-filtering the source record doesn't reach any of these.
**Fix:** Track lineage: every derived artifact records the source records it drew on. When any source becomes GM-only, the artifact is made GM-only (or invalidated) and flagged to the GM. Write down the limit too: content a Player has already seen or downloaded cannot be recalled. Add an EV-4 case that flips a record to GM-only after generation.

### C4. EV-4 cannot support a "0 leaks" claim
EV-4 "fails on any canary in any response body or generated output", and its "route list is derived from the router table". The gaps:
- **Paraphrase.** An LLM restates "the innkeeper betrayed you" without the canary string. CI uses a "deterministic stub" for the LLM (addendum G), so generated paths never exercise real model behaviour. FR-8 "a GM-only fact cannot reach a Player through a generated answer" and FR-43 "never hints at hidden content" cannot be tested this way.
- **Parts of the system outside the router.** The WebSocket STT endpoint, nginx static locations, SSE event types (the `meta` trace event), downloadable files, and query-parameter variants.
- **Inference channels.** A 403 versus a 404 on a GM-only ID reveals that the record exists. Counts, pagination totals and result ordering do too. Retrieval ranking is also steered by Shorthand: addendum C admits embeddings and `narrative_tsv` index Shorthand, and calls the narrative-only embedding only "a possible later refinement". So for a Player, a GM-only fact decides which Party entries rank top, with no canary in sight.
- **Canaries only in free text.** Nothing seeds canaries in status values, aliases, Relationship types or tag names.

**Fix:**
- (a) Assert on the *assembled LLM context*, not only the output. The stub echoes its full prompt, and the test fails if any canary appears in the context of a Player-scoped call. This is the only way to test FR-8's AI-context clause.
- (b) Build a Player-only retrieval index (Narrative-only embeddings and tsv) in Phase 0, not "later".
- (c) Return 404 for every GM-only ID a Player requests, and test it.
- (d) Put canaries in every structured field.
- (e) Enumerate nginx locations, WebSocket and SSE event types, and file URLs alongside the router table.
- (f) Reword the NFR-5 claim to "0 leaks across the enumerated channels". Add a manual red-team checklist for paraphrase and inference.

### C5. Files served outside the API bypass the Visibility filter
FR-52 stores maps and DeepZoom tiles "on a new named volume" (addendum A). FR-32 caches narration audio, FR-47 produces export files, and FR-29 can keep raw audio. If nginx or a static mount serves any of these, by tile path or by a guessable file or Job ID, a Player or anonymous Share Link holder can fetch GM-only maps, the GM-edition Chronicle, or GM-only recap audio. EV-4 never sees these requests (C4). FR-2 also shows Jobs to "the user"; a Job ID for the GM-edition export must not be downloadable by others.
**Fix:** Require that every file download goes through an authorised API route that checks Visibility, or through short-lived signed URLs scoped to the requester. Never use a public static path. Add each file type to EV-4.

### C6. A Player's NPC Conversation is fed GM-only material
FR-35 builds the persona from "name, description, status and any GM-written voice notes". Voice notes are where a GM writes "secretly the traitor; act innocent". FR-39 only limits NPC Knowledge (the entries) for Players. It does not limit the persona inputs, GM grants, or conversation history. FR-38 doesn't say whether history is per user or per NPC. If it is per NPC, the GM's earlier prep chat, which drew on granted GM-only facts, becomes the context for the Player's chat. FR-35's deceased notice shows "its source entry", which may be GM-only. FR-37 "Players see citations only to entries they may see" assumes replies can draw on entries the Player can't see. That is already the leak: hiding the citation hides the evidence, not the fact. EV-3 has a single GM-hidden fact per NPC, which is too few to gate on.
**Fix:**
- For Players, assemble the persona from Party fields only. Voice notes become a Secret, with a separate "Player-safe voice notes" field.
- Make conversation threads per user, and never share history across Roles.
- Drop GM grants of GM-only entries from a Player's context.
- Replace FR-37's citation clause with "a Player's NPC reply draws only on content the Player may see". Assert it with the context check from C4(a).

### C7. NFR-2 is a hard requirement the PRD already admits is false
"Every feature works on the Reference Box (about 8 GB RAM, CPU-only)", yet NFR-2 itself records "about 6.4 GB idle and 11.9 GB peak today". The 7B Q4 alone is about 4.4 GB (addendum D), and the plan adds STT, TTS, NLI, a worker container and Postgres. In UJ-4 the GM's browser probably runs on the same box. The Phase 0 exit criteria ("EV-4 green, spikes recorded, NFR-6 re-set") never require the memory problem to be *solved*, only measured. §12 Q4 leaves the outcome open. SM-5 then lets every target be "re-set". As written, the capstone's headline hardware claim can't be falsified, and it is probably untrue.
**Fix:** Make "SPIKE-5 shows a configuration where the full stack's peak RSS stays ≤ 7.5 GB, with one heavy feature and the GM's browser running" a Phase 0 exit gate. Otherwise, before Phase 1, formally change the Reference Box to 16 GB and update §1, §2.1 and §3. Name which features are allowed to be absent or degraded on the baseline profile.

### C8. No timeline or cut line for a solo capstone
The plan has 55 FRs, 10 NFRs, 5 evals with hand-labelled sets, 6 spikes, 4 new sidecars (STT, TTS, NLI, diarization), a WebSocket audio pipeline, WebGL graphs, deep-zoom maps, an EPUB and PDF engine, gamification and a role system. Three of the four test-infrastructure gaps in addendum G (no fake LLM, no frontend test runner, route tests that skip the lifespan) must be closed before EV-4 can exist. The PRD gives no capstone deadline, no capacity estimate, and no must-have versus stretch split. §9 is "not locked", and every phase ends with a DS demo.
**Fix:** State the capstone deadline and weekly hours. Define a capstone MVP, for example Foundations, F1, F2, F7, EV-1, EV-2, EV-4 and DS-1 to DS-3. Mark F4, F9, F10, FR-30, FR-39 and FR-17 as stretch, in writing, with a cut order. Give each phase a time-box and a rule for what gets dropped when it overruns.

---

## High

### H1. The glossary's definition of "Canon" contradicts the approval rule
§3: "Canon. The approved state of the World Model plus **all Journal Entries** and Canon Notes. Only GM approval changes it." Journal Entries need no approval, and a Player Journal entry is a Journal Entry. So a Player saving an in-character lie changes Canon. FR-42 says Player Journals "never update Canon directly", and FR-19 checks continuity "against Canon".
**Fix:** Define Canon as "GM-authored Journal Entries + approved World Model + Canon Notes". Exclude Player Journals explicitly from Canon and from continuity sources.

### H2. Player Journal visibility needs a third state, and "Party" conflicts with FR-40
FR-42: "author chooses whether other Players can read it", with a default of "author and GMs only". That third state (author plus GMs) doesn't exist in §3, where Visibility is only Party or GM-only. A shared Player Journal would be "Party", which §3 defines as visible "to read-only Share Links". FR-40 says Share Links show content "without Player Journals". FR-48 doesn't say which Player Journals go into a group-shared Player edition (UJ-6).
**Fix:** Add a Visibility value (for example "Author + GMs") or a separate Player Journal sharing flag. State explicitly that Player Journals are never served to Share Links. Specify whether Player edition exports include shared Player Journals.

### H3. Phase 0 depends on work scheduled in later phases
Phase 0 holds FR-4, FR-5, FR-6 and FR-8. FR-5 creates Entities and "unconfirmed Mentions", but Entities and Mentions are defined in FR-11 and FR-12 (Phase 1). FR-6 "queues re-extraction (FR-18) and a continuity check (FR-19)", both Phase 1 and 2 features, and the reference is wrong besides: automatic re-extraction on edit is FR-13, while FR-18 is the GM-triggered re-run. FR-8 applies Visibility to Relationships, Canon Notes, Maps and Pins, none of which exist yet. The Phase 0 exit needs "EV-4 green", but EV-4 covers "NPC Conversation, graph, … maps, recaps", which don't exist in Phase 0.
**Fix:** Split the Foundations into what Phase 0 really needs (FR-1–3, FR-7, FR-9, FR-10, the Visibility mechanism and the Journal Entry part of FR-8). Move FR-4 and FR-5 into F1. Have FR-6 queue the FR-13 and FR-19 Jobs "when present". Grow EV-4 per phase: each phase's exit requires EV-4 green over that phase's routes.

### H4. "F4 works without F1" is false
§5.4: "Works without F1". §9: "F4 and F10 don't depend on F1 and can move earlier". But FR-28 returns "the Entity card and its latest Mentions" and highlights "Names … that match Entities or aliases". FR-29 "triggers F1 and F2 Jobs". F10's FR-53 needs Location Entities, as does FR-53's third clause. §5.1's list of dependents ("F2, F3, F6 and F7") leaves out F4, F8 (appendix), F9 (Mention stats) and F10.
**Fix:** Specify FR-28 behaviour without F1 (full-text journal lookup, or no lookup), or make F4 depend on F1. Correct §5.1 and §9.

### H5. FR-29 audio deletion makes FR-30 diarization impossible
FR-29 deletes raw audio "once transcribed" by default. FR-30 diarizes "a finished Live Session transcript" after the session, and diarization needs the audio.
**Fix:** If speaker labels are enabled, keep the audio until the diarization Job finishes, then delete it. Otherwise hide FR-30 for sessions whose audio is gone. Tell the GM at session start.

### H6. No spike measures the 7B on CPU, and several LLM targets look infeasible
SPIKE-1 to SPIKE-5 cover NLI, STT, TTS, diarization and memory. None measures 7B prompt and generation throughput on the Reference Box. Several targets depend on it:
- FR-27: a Rolling Recap "covers the whole session" and refreshes "about every 60 seconds" while STT competes for the same CPU. CPU prompt evaluation of a few thousand tokens already takes tens of seconds before generation starts.
- FR-35 / NFR-6: NPC first token "≤ 20 s" with persona plus retrieved knowledge.
- FR-13 / NFR-6: extraction "≤ 3 min" while the prompt "carries … the current Entity list" (addendum A), which grows without limit as the campaign does.
- FR-1 runs heavy models "one at a time per model". So a campaign backfill (FR-18), or one Job that takes 3 minutes per entry, can starve recap, NPC and chat calls. There is no rule for who goes first.

**Fix:** Add SPIKE-6: 7B tokens/s for prompt and generation at 1k, 4k and 8k context, idle and under STT load. Use it to set FR-27 (incremental summarisation, refresh only when idle), FR-35 and FR-13 targets. Cap the Entity list in the prompt to the top-k shortlist. Define Job priority (interactive work before backfill) and let users pause or cancel a backfill.

### H7. The success metrics can't fail
SM-5: "Every NFR-6 row met …, or re-set with measured justification". Any outcome passes. NFR-6 says the targets "are re-set in the same PRD revision that records the results". SM-7 has no target ("target set after SPIKE-2"). SM-6's acceptance rate is measured on "the demo run", graded by the owner, who also wrote the demo entries and the prompts.
**Fix:** Freeze targets after Phase 0 and allow no later re-set without a recorded waiver. Give SM-7 a WER ceiling once SPIKE-2 is done, or drop it. Make SM-6 a counter-metric, or measure it on entries written by someone other than the prompt author.

### H8. The eval sets are too small, not held out, and EV-3 has no judging protocol
EV-2 has "at least 10 seeded contradictions". Detection then moves in steps of 10%, and the threshold is tuned with a sweep (0.8, 0.9, 0.95) on the same set it is scored on. EV-1 has about 60 labels split over 5 proposal types, so per-type F1 rests on a handful of items. EV-1 doesn't define when a proposal "matches" a label. EV-3 doesn't say who decides that a reply "leaked" or "answered" (human, rubric or LLM judge), so its leak rate can't be reproduced. SM-2 accepts "trap-holds ≥ 2/3", but FR-21 says a Canon Note is "authoritative" and the conflict is not raised again. That is deterministic behaviour, and it can't be allowed to fail one time in three.
**Fix:** Split each set into tuning and held-out halves, and report held-out numbers only. Write matching rules for EV-1 and a labelled rubric for EV-3, with two-rater agreement or a fixed judge prompt. Report confidence intervals. Turn the overridden-retcon trap into a deterministic unit test that must pass 100%.

### H9. Proposals go stale across entries and while Canon changes
Entries A and B are saved back to back. B's extraction runs against Canon before A's proposals are approved. A proposes "Mira → deceased" and B proposes "Mira alive" with an old value that no longer matches. FR-13 records "old and new values", but nothing says what happens when the old value no longer equals Canon at approval time. The same applies when the target Entity has since been merged (FR-17) or deleted. FR-18 dedups only "pending proposals" for the same entry.
**Fix:** At approval, check optimistically that the proposal's old value still equals current Canon. Mark stale proposals "needs re-check" and re-run them. Redirect proposals on merged Entities to the survivor, and void them on deleted Entities.

### H10. Deleting or editing a Journal Entry has no defined effect on what was derived from it
Deleting entries exists today (FR-6 context). The PRD never says what happens to the Mentions, Relationships, Entity history, Canon Notes, NPC Knowledge, pending proposals, Continuity Flags, recaps and citations derived from a deleted entry. Edits leave a related gap: FR-6 says approved Canon "is not changed automatically". After the GM rewrites an entry, Mira stays "deceased" with a citation quote that no longer exists in the text.
**Fix:** Add an FR for deletion (cascade, or tombstone with "source removed" citations, plus GM review of orphaned Canon). On edit, re-validate provenance quotes and flag Canon whose supporting quote was removed.

### H11. FR-21 Canon Note semantics are undefined, so overridden flags will recur
"Do not raise the same conflict again". The PRD never says what counts as "the same". In UJ-2 the override doesn't change Mira's status, which stays "deceased". So every later entry where Mira acts is a *new* sentence contradicting the same Entity field, and flags keep firing. SM-C3 lists flag volume as a trust risk.
**Fix:** Define conflict identity as (Entity, field, Canon value) rather than the sentence. Have override ask whether Entity state should change ("Mira: deceased → alive, Canon Note X"), and scope a Canon Note to an Entity and field from a date onward.

### H12. Phones, Players at home, and LAN microphones need HTTPS and remote access the PRD never mentions
UJ-3 has Sam using the portal "on his phone on Tuesday", between sessions, presumably from home, against a box that runs "with the network unplugged". Browser microphone capture (FR-26, AudioWorklet) needs a secure context. A GM's tablet reaching `http://192.168.x.x` gets no microphone at all. There are no requirements for TLS, exposing the box beyond the LAN, or hardening auth for an internet-facing self-host.
**Fix:** Add an NFR for the deployment modes: localhost only, LAN with TLS (local CA or mkcert), and remote access (reverse proxy or tunnel, outside v1 support or documented). State that FR-26 needs HTTPS or localhost. Rewrite UJ-3 to match the supported mode.

### H13. The TTS licence risk may block F5 entirely, and LIC-1 can't be time-boxed
R-6 calls espeak-ng Kokoro's "fallback". Common Kokoro ONNX packagings use espeak-ng (through phonemizer) as the *main* G2P path, not a fallback. If so, "English-only narration with the GPL fallback disabled" (§11, Q1) may leave no working TTS in the commercial build. LIC-1 is "½ day, plus legal review", and legal review is an external dependency with no fixed duration. The licence register also leaves out WeasyPrint's native dependencies (Pango, cairo, HarfBuzz: LGPL, dynamic) and the bundled font. pyannote community-1 is "gated", while NFR-1 promises "installable offline".
**Fix:** Before choosing Kokoro, verify which G2P path the exact chosen package uses. Make the commercial build's F5 (TTS) conditional, with the browser-speech fallback from FR-33 as the documented commercial behaviour. Complete the register with native libraries and fonts. Make FR-30 depend on SPIKE-4 confirming an offline bundle is allowed to be redistributed.

### H14. FR-17 Merge can reveal GM-only aliases and history
Merging a GM-only Entity ("The Masked One") into a Party Entity ("Brother Aldric") gives the survivor "both sets of aliases, Mentions, Relationships and history". The Party Entity now shows the secret identity. The PRD sets no rule for the survivor's Visibility and adds no merge case to EV-4.
**Fix:** Each item keeps its own Visibility through a merge. Aliases, Mentions and history from a GM-only Entity stay GM-only. The merge UI warns when Visibility differs. Add a merge case to EV-4.

### H15. Milestones and Achievements reveal GM-only counts
FR-50 shows Milestones such as "100 Entities in the world" and "first Quest completed" to every Member. FR-49 filters stats for Players, but FR-50 has no such clause. A Player who sees "100 Entities" while their wiki shows 70 learns that 30 hidden ones exist. That is the exact inference FR-25 forbids for the graph.
**Fix:** Compute Milestones per Role from Party-visible content. Never award or show a Player a Milestone triggered by GM-only content. Add this to EV-4.

### H16. FR-5 migration never assigns Visibility
Existing NPCs and Quests become Entities, but no Visibility is given. Under FR-8's "Narratives are Party" plus Party-by-inheritance, every existing NPC (including the GM's secret villain) and every Quest appears in the Portal the moment a Player is invited.
**Fix:** Migrate existing Entities as GM-only, or put them in a "needs visibility review" state. Block Player invites until the GM completes a one-time visibility pass.

---

## Medium

- **M1. Untestable wording.** Examples: FR-24 "without visible stutter" on "a mid-range laptop browser"; FR-52 "pan and zoom smoothly"; FR-43 "never hints at hidden content"; FR-35 and FR-37 "in character"; FR-14 "When a match is uncertain"; FR-1 "user-readable reason"; FR-52 "clear message". *Fix:* use measurable criteria (for example ≥ 30 fps on a named device or CPU class), a match-score threshold, and rubric-scored samples.
- **M2. FR-26 backlog drops audio.** "Oldest unprocessed audio is skipped" contradicts FR-29's "full transcript" and FR-27's "no silent truncation". FR-26 doesn't say whether audio queues in the browser or on the server, and a browser refresh loses audio that was never sent. *Fix:* buffer on the server, warn before skipping, and record the gaps in the transcript.
- **M3. FR-33's fallback may need the network.** Several browser "built-in" voices (for example Chrome's Google voices) are network voices, which conflicts with NFR-1. *Fix:* restrict the fallback to local voices only (`localService`), and say when none are available.
- **M4. "Session" is never created by any FR.** The glossary says it is "identified by a session date". Chapters (FR-45), recaps over "last N Sessions" (FR-31) and streaks (FR-51) all depend on Sessions, but no FR creates one. FR-45 doesn't say where entries without a Session go. *Fix:* add a Session FR (created explicitly or from an entry's date), and handle entries without a Session.
- **M5. FR-16 revert of a middle change.** Reverting alive → deceased when a later deceased → missing exists is undefined. *Fix:* allow reverting only the latest change, or require resolving the later ones.
- **M6. FR-36 "facts" is undefined.** "Grant or hide individual Journal Entries or facts" has no unit for a fact (a sentence, a chunk, a Mention?). Retrieval works at chunk level. *Fix:* define a fact as a chunk or Mention, and state how hiding one interacts with an entry that is still granted.
- **M7. BYOK sends data to the cloud from background Jobs.** A save by a Co-GM with a cloud BYOK key may send the whole World Model, GM-only Entities included, to a cloud provider (extraction context, FR-13). NFR-5 says opt-in BYOK, but whose opt-in decides a campaign-wide Job is unclear. *Fix:* Jobs use a campaign-level provider setting chosen by the Owner, and never a Member's personal key.
- **M8. FR-6 contradicts FR-42.** FR-6: an edit "queues re-extraction … and a continuity check". FR-42: Player Journals run extraction "only when a GM chooses to". *Fix:* exempt Player Journal edits in FR-6.
- **M9. FR-48 contradicts itself.** "GM edition contains everything, including Shorthand and Secrets when the GM opts in": either it contains everything or Shorthand needs an opt-in. *Fix:* "GM edition: all records; Shorthand and Secrets are opt-in toggles."
- **M10. FR-44 "next request" doesn't cover open connections.** Open SSE and WebSocket streams, and any role claim cached in a JWT, keep the old Role. *Fix:* check the Role on every request, without trusting token claims, and close the user's open streams when their Role changes.
- **M11. Job status can leak to Players.** FR-2 shows Players their Jobs. Failure reasons or progress text (for example "3 proposals for Mira") can contain GM-only names. *Fix:* use generic Job messages for Players, and include Jobs in EV-4.
- **M12. Two grounding labels conflict.** NFR-7 requires citations or one of two labels. FR-27's Rolling Recap uses a third label, "generated from the transcript". *Fix:* name it in NFR-7.
- **M13. SM-4 misses FRs.** Its "Validates" list leaves out FR-34, FR-37, FR-40, FR-41, FR-42 and FR-49. *Fix:* list every FR with a Player-facing read path.
- **M14. FR-52 "included in backups" has no backup to point to.** No backup mechanism is defined anywhere. *Fix:* reference the backup procedure, or drop the clause.
- **M15. DS-4 has no way to feed a recorded clip.** "Run a Live Session from a recorded clip", but FR-26 captures from the microphone. *Fix:* add a dev or demo audio-file input to the same pipeline.
- **M16. Addendum D's model-loading change costs time.** `OLLAMA_MAX_LOADED_MODELS=1` with "only the fine-tuned model" means either swapping models (a reload of about 4.4 GB on every switch) or running extraction and NPC personas on a model fine-tuned for shorthand → narrative. Neither is evaluated. *Fix:* add both as SPIKE-5 and EV-1 operating points.
- **M17. No consent rule for recording people at the table.** FR-26 and FR-30 record and diarize Players. *Fix:* show a consent notice at Live Session start, and add a per-session indicator.

## Low

- **L1. Glossary drift.** "Co-GM" is used as a Role (FR-7, FR-44), but Role is only GM or Player. "GM notes", "Quest notes", "voice notes" and "Secret" are used loosely. The Review Checklist groups (New / Changed / Quest progress / Relationships) have no home for Mention proposals or Continuity Flags (FR-20). "NPC Character" doesn't say whether creatures count.
- **L2. Mechanism choices leak into the PRD.** §0 says mechanism choices are "not in the FRs", but EV-1 ("NER pre-pass") and EV-2 ("NLI threshold sweep") hard-code mechanisms.
- **L3. Two FRs have no testable consequences.** FR-34 and FR-55.
- **L4. FR-11 status wording is ambiguous.** "destroyed or disbanded" doesn't say which applies to Location, Faction and Item.
- **L5. Addendum date is odd.** "Package versions must be re-checked from 2026-11-01."
- **L6. FR-5 migration race.** "Runs at boot" with 4 gunicorn workers risks concurrent migration runs. Require a single migration runner or an advisory lock.
- **L7. Disk budget covers TTS only.** STT, NLI, diarization, maps and tiles have no disk budget.
- **L8. Narratives default to Party per entry.** A GM who forgets to mark one exposes it. Consider a per-campaign default and an "unreviewed" state for new entries.
- **L9. The §13 assumption index omits NFR-6 table values.** They are only flagged as provisional in the NFR-6 intro.
