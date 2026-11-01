---
title: "Reconcile: brief + brief addendum vs PRD + PRD addendum"
created: 2026-10-31
inputs:
  - briefs/brief-Lorekeeper.quest-2026-10-31/brief.md
  - briefs/brief-Lorekeeper.quest-2026-10-31/addendum.md
  - prds/prd-Lorekeeper.quest-2026-10-31/prd.md
  - prds/prd-Lorekeeper.quest-2026-10-31/addendum.md
---

# Input reconciliation: brief to PRD

Overall the PRD is a faithful and much deeper expansion of the brief. All ten features, the dependency order, the four success-criteria families, the eval sketches, the six open questions and nearly all of the out-of-scope list carry through, usually in stronger form. The Piper replacement is handled well: the PRD addendum §A and §F record the reason (GPL-3.0), the replacement, the espeak-ng residual risk (R-6, LIC-1, §12 Q1) and the disk budget (§11). That is not a gap. The one new limit it brings, English-only narration in v1, is stated openly.

The gaps below are mostly qualitative ideas and persona-level success signals that the FR structure lost. They are ordered by importance.

## High

### G1. A Player has no link to their own PC
- **Input:** brief addendum, Persona depth: "Wants to see their own character's story and the NPCs they've met". Brief, Secondary persona: "keep a character journal".
- **PRD:** missing. The Glossary has Character kind PC, and the Player Journal is "in their character's voice", but nothing ties a Player Member to a PC Entity. Without that link the portal has no "my character" view, Player Journal entries can't attach to the PC's page, and the PC's story can't be filtered.
- **Fix:** add an FR under §5.7 (or extend FR-42 and FR-40): "A GM can link a Player Member to one or more PC Character Entities. The portal shows a 'My character' page with the PC's Mentions, Relationships and the Player's own journal entries." Add the term to §3 Glossary.

### G2. The between-session pull and retention problem is never solved or measured
- **Input:** brief, The Problem: "nothing that pulls them back before the next session" and "The engagement loop ends at 'save entry.' … a record that just sits there gets abandoned." Brief, Secondary persona success: "opens the portal between sessions." Theme D is titled "Keepsakes and retention".
- **PRD:** weakened. §1 and §2.1 restate the player JTBD, but no FR, SM or DS addresses the pull-back. Several defaults lean against it. Streaks and Achievements are off by default (FR-51). Player NPC Conversation is off for every NPC (FR-39). FR-50 bans reminders. Each choice is defensible ("celebration, not compulsion", SM-C4), but together they leave the brief's retention problem without a mechanism or a proxy signal. There is also no adoption telemetry (NFR-5), so the persona's success criterion can't be observed.
- **Fix:** add a short "Retention without compulsion" paragraph to §5.9 or §1 saying which features carry the pull-back (the new Narrated Recap and recent Narratives on the portal home, a non-nagging "since your last visit" panel, and so on). Add a secondary SM or a DS step that demonstrates it, for example DS-3 showing a "new since last visit" view. Alternatively, record in §10 or §12 that between-session pull is deliberately limited to passive surfaces.

### G3. The "honest limits" ethos becomes engineering mitigations, with nothing said to the user
- **Input:** brief, What Makes This Different: "**Honest limits.** None of this is a deep moat… A 7B model on CPU is slow, and features have to be designed around that." Brief addendum persona: the GM is "skeptical of AI that invents facts."
- **PRD:** partly kept. Slowness is designed around (Jobs, NFR-2, NFR-6, the lag indicator in FR-26). But honesty toward the user is missing. Nothing requires the UI to say that the Canon guard is best-effort, so the lack of a flag doesn't prove consistency. Nothing requires it to say that extraction can miss things, or to give an expected wait at Job start (FR-2 shows progress, not an ETA or explanation). The "no deep moat" positioning stance also has no home, because the PRD has no differentiation section at all.
- **Fix:** add to NFR-7 (or a new NFR "Honest limits"): "AI features state their limits in the UI: the continuity check says it is not exhaustive, the Review Checklist says proposals may be incomplete, and CPU Jobs show an expected duration." Optionally add a short §1 or §2 paragraph carrying the brief's differentiators (local, grounded, self-maintaining, evaluated) with the honest-limits caveat, so downstream UX copy inherits the stance.

### G4. The review step must stay "short", but nothing bounds GM review effort
- **Input:** brief addendum, Persona depth: "writes shorthand … about 10 minutes per session today. They would accept a **short** review step if it saves prep time later." Brief success: "the world model stays current without hand-editing."
- **PRD:** weakened. SM-C1 tracks proposals per entry and rejection rate, but neither has a ceiling, and nothing measures review time. SM-6 counts edited proposals as accepted, so a high hand-edit rate would still score as success.
- **Fix:** add a secondary SM such as "median Review Checklist completion time ≤ N minutes per entry on the demo run" plus a ceiling on SM-C1 (for example a median of ≤ 12 proposals per entry `[ASSUMPTION]`). Split SM-6 into approved-as-is versus edited, so the "without hand-editing" signal stays visible.

## Medium

### G5. The vision's "narrated, illustrated chronicle of a story they told together" gets thinner
- **Input:** brief, Vision: "Years later, the group has a narrated, illustrated chronicle of a story they told together."
- **PRD:** weakened. FR-45 to FR-48 define a text book with optional Map images. "Narrated": the Chronicle carries no audio, and Narrated Recaps aren't included or linked (EPUB3 can embed audio). "Illustrated": the only images are Maps, and there's no user-uploaded art for entries or Entities. AI image generation stays out of scope, correctly. "Told together": whether Player Journal entries appear in the Chronicle, and in which edition, is unspecified.
- **Fix:** in FR-45 or FR-48, state whether shared Player Journal entries (FR-42) appear and in which edition. Either add optional embedded Narrated Recap audio in the EPUB and user-uploaded images, or record in §10 that the v1 Chronicle is text plus Maps, and adjust the §1 vision wording to match.

### G6. "Any field" becomes "designated fields"
- **Input:** brief, Feature 7: "**Any field** can be flagged GM-only or secret."
- **PRD:** narrowed. §3 Visibility, FR-8: "designated fields can be Secrets". FR-41 says "mark individual fields as Secrets" without saying which ones.
- **Fix:** either list the designated fields in FR-8 and note the deliberate narrowing from the brief, or restore "any user-editable field on an Entity, Relationship or Journal Entry".

### G7. "Easy to set up" for the tertiary persona has no requirement
- **Input:** brief, Tertiary persona: "Evaluates the project by whether it is easy to set up, whether it runs on modest hardware, and whether its evaluation can be reproduced."
- **PRD:** partly kept. Modest hardware (NFR-2) and reproducibility (§7) are covered. Ease of setup is not, even though the expansion adds `stt`, `tts`, worker and NLI containers, a map volume and gated pyannote weights (R-4).
- **Fix:** add an NFR or consequences under NFR-1: one documented command brings up the full stack, optional sidecars (STT, TTS, diarization) are opt-in profiles, and a fresh-install time target `[ASSUMPTION]` is measured in EV-5.

### G8. Player NPC questioning is off by default, which weakens the secondary persona
- **Input:** brief, Secondary persona: "question NPCs between sessions."
- **PRD:** FR-39 makes it GM-enabled per NPC and off by default. That is reasonable for safety, but no journey, DS or SM exercises a Player talking to an NPC. UJ-5 and DS-4 are GM-only.
- **Fix:** add a Player NPC Conversation step to UJ-3 or DS-3, with a probe for a GM-only fact, so EV-3 and EV-4 cover the Player path end to end.

## Low

### G9. "Content marketplace" was dropped from the non-goals
- **Input:** brief, Scope Out: "A content marketplace".
- **PRD:** missing from §10.
- **Fix:** add it to §10.

### G10. The differentiators and competitive context are dropped entirely
- **Input:** brief, What Makes This Different ("The world maintains itself… In World Anvil, Kanka or LegendKeeper, the GM builds and updates the wiki by hand", "no per-token cost"). Brief addendum, competitive table, including "Foundry … a possible future integration target" and "Validation is needed before any public claim."
- **PRD:** missing. That's acceptable for a PRD, but the "no per-token cost" benefit, the Foundry future-integration note and the "UNVERIFIED, validate before public claims" caveat are lost to downstream readers.
- **Fix:** add one line to §0 or §1 pointing to the brief's differentiators and competitive notes. Add the Foundry integration as a deferred idea in §12 or §10.

### G11. The relevance-gate reuse for the Canon guard is underspecified
- **Input:** brief addendum, dependency table: Canon guard reuses "retrieval_service plus the relevance gate (≤0.65)".
- **PRD:** the §5.2 description says it "reuses the existing retrieval and relevance gate", but PRD addendum §A routes candidates through `hybrid_search_journal` and NLI with no mention of the gate threshold.
- **Fix:** state in addendum §A whether the ≤0.65 gate filters candidate Canon before NLI scoring, and add it as an EV-2 operating point.

### G12. Two of the brief's performance-eval units were dropped
- **Input:** brief addendum, Performance eval: "TTS per 100 words, and transcription real-time factor".
- **PRD:** EV-5 covers only NFR-6 rows (narration per 300 words, caption lag). Real-time factor (RTF) appears only in SPIKE-2.
- **Fix:** add the STT real-time factor and the TTS seconds per 100 words to EV-5's results table, so they're tracked after the spikes as well.
