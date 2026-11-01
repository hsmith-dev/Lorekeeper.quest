# Input reconciliation: scope-input.md vs PRD + addendum

Input: `_bmad-output/planning-artifacts/scope-input.md` (owner-approved, 2026-10-31)
Reviewed: `prd.md`, `addendum.md` (same folder)
Reviewer date: 2026-10-31

Overall: the PRD covers all 10 features, all four Owner decisions and the hard constraints, mostly faithfully and often in more depth than the input. The gaps below are places where a binding constraint is weakened or left open, an Owner decision is paraphrased with drift, or a qualitative intent got lost in the FR structure. Ordered by severity.

---

## A. Hard constraints

### A1. 8 GB baseline: PRD offers to change the constraint instead of meeting it (HIGH)
- **Input:** "Must run on the documented baseline (~8 GB RAM, CPU-only acceptable; NVIDIA GPU optional). Heavy features must degrade gracefully on CPU (async jobs, progress, smaller models)."
- **PRD:** §12 Q4 offers "raise the documented baseline (for example to 12 to 16 GB)" as an option. NFR-2 says SPIKE-5 "must resolve this", and §8 R-5 lists "whether the Reference Box stays 8 GB or the documented baseline changes" as the decision.
- **Gap:** The constraint is binding. Raising the baseline is a scope change the owner has not approved, yet the PRD presents it as an ordinary outcome of the spike. Also, "smaller models" (one of the input's named degradation levers) only shows up as a fallback for extraction quality (R-7), not as a memory or CPU lever.
- **Fix:** In NFR-2, require a "baseline profile" that fits in about 8 GB (fewer workers, `en_core_web_sm`, one loaded Ollama model, lazy sidecars, smaller STT/NLI variants). Treat raising the baseline as an owner escalation only, and mark it in §12 as "contradicts a hard constraint". List "smaller model per feature" as a degradation lever in NFR-2.

### A2. Concurrent heavy load during Live Session isn't budgeted (HIGH)
- **Input:** 8 GB baseline. F4 decision: "rolling ~10–30 s chunked transcription with a small Whisper model on CPU; the recap and NPC lookup refresh about every minute."
- **PRD:** NFR-2 budgets memory "with one heavy feature running". NFR-3 keeps STT resident during a Live Session. FR-27 has a Rolling Recap (a 7B LLM call) every 60 s. NFR-6 gives a refresh interval but no generation time. FR-28 free-text lookup also calls the LLM.
- **Gap:** A Live Session is two heavy models at once (STT resident plus the 7B every minute), and a save during play adds extraction. Nothing says how this fits in 8 GB or in CPU time. It also isn't stated whether a 7B recap on CPU can finish inside a 60 s cycle. SPIKE-2 measures STT with the LLM busy, but it doesn't measure recap latency.
- **Fix:** Add an NFR-2 consequence for "Live Session active (STT + periodic recap)" as a named memory/CPU scenario. Add the recap generation time to NFR-6 and SPIKE-2. Specify degradation: the refresh interval stretches, or the recap is skipped while a backlog exists, and extraction/continuity Jobs are deferred until the session ends.

### A3. Browser speech fallback may not be local (MEDIUM)
- **Input:** "Everything local. No required external/cloud services. All new AI (LLM, STT, TTS, embeddings) runs in the Docker stack."
- **PRD:** FR-33 says that if the TTS service is down, the recap "can still be read aloud with the browser's built-in speech".
- **Gap:** Browser `speechSynthesis` voices can be network-backed (for example Chrome's Google voices), so recap text could leave the machine. That conflicts with "everything local" and with NFR-1/NFR-5 ("campaign never leaves the machine").
- **Fix:** Restrict the fallback to voices where `localService === true`, or drop it. Add the check to NFR-1.

### A4. Grounding/citation not specified for Rolling Recap (MEDIUM)
- **Input:** "Preserve the grounding ethos: AI outputs cite journal sources."
- **PRD:** FR-27 only labels the recap "generated from the transcript". NFR-7 requires citations for outputs that "state campaign facts".
- **Gap:** The Rolling Recap has no traceability back to transcript chunks or timestamps, and nothing prevents it from adding facts that aren't in the transcript.
- **Fix:** FR-27: each recap line links to the transcript chunk(s) or timestamps it came from. Apply the same rule to the end-of-session draft (FR-29).

### A5. Measurable evaluation missing for some AI features (MEDIUM)
- **Input:** "Capstone: demo-ability and measurable evaluation matter (extend docs/RETRIEVAL_EVAL.md style metrics where AI is involved)."
- **PRD:** §7 has EV-1 to EV-5, covering F1, F2, F6, F7 and performance. F4 only has SM-7 WER, with "target set after SPIKE-2". Nothing evaluates the AI text in F5 or F4.
- **Gap:** "Previously on…" recap text (F5) and Rolling Recap (F4) are AI outputs with no faithfulness/citation eval. Entity matching in the live transcript (F4 name highlighting) isn't measured either.
- **Fix:** Add an EV-6 recap faithfulness eval: unsupported-claim rate, citation correctness and GM-only leakage in Party recaps, on demo Sessions and a recorded clip. Optionally add name-highlight precision/recall for FR-28.

### A6. Demo coverage misses F9 (LOW-MEDIUM)
- **Input:** "demo-ability ... matter"; F9 is in scope.
- **PRD:** DS-1 to DS-5 don't include Milestones/stats, and SM-1 to SM-7 have no F9 metric. FR-51 makes streaks and Achievements **off by default** `[ASSUMPTION]`.
- **Gap:** F9 is approved scope but has no demo scenario. With the off-by-default setting, a fresh demo shows nothing.
- **Fix:** Add F9 to DS-5 (or a DS-6), using a seeded campaign with the stats visible and Achievements turned on for the demo user. Reconsider off-by-default for the campaign stats view; opt-in can apply to streaks only.

### A7. Brownfield: replacing an existing transcription engine isn't flagged (LOW)
- **Input:** "Brownfield: extend existing patterns ..., don't rewrite." Today's product has "voice recording + transcription".
- **PRD/addendum:** Addendum A says "Replace openai-whisper with faster-whisper", but the PRD has no FR about migrating the existing voice recording feature.
- **Fix:** Add a consequence (FR-26 or NFR-8): the existing record-and-transcribe flow keeps working, whether on the new `stt` container or unchanged, with no regression in the current feature.

---

## B. Owner decisions (binding)

### B1. F1 Review Checklist: groups and component drift (MEDIUM)
- **Input:** "one grouped review checklist after save (New / Changed / Quest progress), approve/reject/edit per item plus 'approve all'; extends NarrativeReviewPanel."
- **PRD:** FR-15 and the Glossary add a fourth group, "Relationships". UJ-1 still says "three groups", so the PRD contradicts itself. Addendum B creates a new `EntityDiffReviewPanel` that "keeps the NarrativeReviewPanel look", which is a new component, not an extension. FR-15 also excludes edited-but-unconfirmed items from "approve all", a constraint the owner didn't state.
- **Fix:** Either fold Relationships (and Mentions) into "New"/"Changed" to keep the owner's three groups, or flag the fourth group as a deviation for owner sign-off and fix UJ-1. State that the panel extends or reuses NarrativeReviewPanel (shared component/contract), or record why a sibling component is used. Keep the approve-all nuance but mark it `[ASSUMPTION]`.

### B2. F6 NPC Knowledge: "secrets" and which Mentions count (MEDIUM)
- **Input:** "default = facts from entries the NPC is linked to (via world-model mentions); GM can grant or hide specific facts/secrets per NPC."
- **PRD:** FR-36 allows granting or hiding "individual Journal Entries or facts". There's no explicit ability to grant **Secrets/GM-only facts** (for example, the NPC knows it is the traitor). It also doesn't say whether **unconfirmed** Mentions (FR-5 migration, pending proposals) count toward the default knowledge, or whether the NPC knows its own GM notes.
- **Gap:** The "secrets" part of the decision is weakened. Counting unapproved Mentions would also breach "nothing becomes canon without approval".
- **Fix:** FR-36: (a) only approved/confirmed Mentions populate the default knowledge; (b) a GM can grant specific Secrets/GM-only facts, including the NPC's own GM notes, and those stay excluded from Player NPC Conversations (FR-39); (c) the default for the NPC's own GM notes is stated explicitly. Add a granted-secret probe to EV-3.

### B3. F2 Retcons: Canon Note visibility and reason are under-specified (MEDIUM)
- **Input:** "GM override of a contradiction flag is stored as a canon/retcon note with a reason; it becomes part of the record that later checks and chat retrieval consider."
- **PRD:** FR-21 covers checks and chat retrieval "subject to Visibility", but FR-8 gives no **default Visibility for Canon Notes**. A retcon reason ("resurrected by the Lantern cult") is often a spoiler. The PRD doesn't say the reason is mandatory. It also doesn't say whether F6 NPC Knowledge, recaps (F5) or the Chronicle consider Canon Notes as part of "the record". FR-20 dismissals (no Canon Note) don't say whether a re-edit or re-check raises the same flag again.
- **Fix:** FR-8: Canon Notes default to GM-only, and the GM can mark one Party. FR-21: a reason is required. Say which consumers read Canon Notes (continuity, chat, NPC Knowledge when linked to the NPC, recaps, Chronicle GM edition). FR-20: a dismissed flag isn't raised again for the same claim pair unless the entry text changes.

### B4. F4 Live STT: "NPC lookup refresh" semantics (LOW)
- **Input:** "the recap and NPC lookup refresh about every minute."
- **PRD:** The F4 description mentions "the quick lookup panel refresh about every minute", but FR-28 only defines on-demand lookup. No FR says which part of the lookup panel refreshes each minute (for example, "NPCs mentioned in the last few minutes").
- **Fix:** Add an FR-28 consequence: the lookup panel shows the Entities recognized in the recent transcript and refreshes about every 60 s.

### B5. Delegated defaults: present, tagged correctly (OK)
- TTS voices/disk budget (§11, addendum E) and NPC/Quest migration (FR-5, §11) are proposed and tagged `[ASSUMPTION]`. No gap.

---

## C. Feature-level omissions

### C1. F5 "(e.g. Piper)" rejected: deviation should be visible in the PRD body (LOW)
- **Input:** "genre-voiced recap with local TTS (e.g. Piper)."
- **PRD:** The rejection of Piper (GPL-3.0) appears only in addendum A.
- **Fix:** Add a one-line note in §5.5 or §11 that Piper was swapped for Kokoro for licence reasons, so the owner sees the deviation from the input.

### C2. F7 "their own character journals": no link to the Player's character (LOW)
- **Input:** "players get a spoiler-filtered wiki and their own character journals."
- **PRD:** FR-42 Player Journal entries aren't tied to the Player's PC Entity or existing character sheet.
- **Fix:** FR-42: a Player Journal can be associated with the Player's PC (Character Entity, kind PC, and/or character sheet), and the portal shows "my character" with its journal.

### C3. F3 graph includes PCs: Player ownership of PCs unspecified (LOW)
- **Input:** "interactive graph of PCs, NPCs, factions, locations".
- **PRD:** PCs are a Character kind. There's no link from a Member to their PC Entity, so the graph can't highlight "you". This depends on C2.
- **Fix:** Mention it with C2 (Member ↔ PC link). This is optional polish.

---

## D. Qualitative intent dropped by the FR structure

### D1. "Genre-voiced" and "Previously on…" feel has no acceptance criteria (LOW-MEDIUM)
- **Input:** "Narrated 'Previously on…' recaps — genre-voiced recap"; "Talk to an NPC — roleplay chat in an NPC's voice".
- **PRD:** FR-31 says "in the Campaign's genre voice", FR-35 says "in character", and §11 describes narrator timbres. Nothing checks that the text style (cold-open, TV-recap cadence, genre diction) or the NPC voice consistency is actually achieved.
- **Fix:** Add a light rubric, rated by the owner or a small human panel, to the demo or EV-6: recap reads as a "Previously on…" teaser in genre tone, and NPC replies stay in persona. Add style guidance (length, second-person/present tense, cliffhanger close) to FR-31.

### D2. "Living world" / "story progresses" feel (LOW)
- **Input:** "nothing updates as the story progresses" is the key gap.
- **PRD:** This is covered functionally (FR-13 to FR-16). There's no surface that *shows* the world changing over time, such as an "As of session N" view, a world changelog per session, or a timeline of status changes. The existing timeline feature isn't connected to Entity history.
- **Fix (optional):** Add an FR or a consequence that a per-Session "what changed in the world" digest (approved Change Proposals grouped by Session) appears on the timeline or campaign home. This also strengthens DS-1.

### D3. Celebration tone carried (OK)
- The F9 celebration-over-compulsion tone is captured well (FR-50, SM-C4). No gap.
