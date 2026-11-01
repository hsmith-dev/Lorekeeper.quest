---
title: "PRD: Lorekeeper living campaign world"
status: final
created: 2026-10-31
updated: 2026-10-31
mode: headless-update
inputs:
  - _bmad-output/planning-artifacts/scope-input.md
  - _bmad-output/planning-artifacts/briefs/brief-Lorekeeper.quest-2026-10-31/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-Lorekeeper.quest-2026-10-31/addendum.md
  - _bmad-output/planning-artifacts/brownfield-context.md
  - _bmad-output/planning-artifacts/research-decisions-summary.md
---

# PRD: Lorekeeper living campaign world

## 0. Document purpose

This PRD defines the Lorekeeper expansion that turns the existing AI journal into a living campaign world. It is for the owner (Harrison) and for the downstream BMAD workflows: UX (`bmad-ux`), architecture (`bmad-architecture`) and epics (`bmad-create-epics-and-stories`). It builds on four inputs and does not repeat them: the owner-approved scope (`scope-input.md`, whose "Owner decisions" this PRD treats as requirements), the product brief and its addendum, the brownfield recon (`brownfield-context.md`) and the technical research summary.

How to read it: §3 Glossary fixes the vocabulary. §4 lists the **Foundations** that several features depend on, including a P0 privacy fix. §5 holds the ten features. FRs are numbered globally (FR-1 to FR-55) and stay stable if the work is re-sliced. Cross-cutting NFRs are in §6, evaluation in §7, risks and time-boxed spikes in §8, and the proposed release phases and cut line in §9. Mechanisms and technology choices live in `addendum.md`, not in the FRs. Inferred values carry inline `[ASSUMPTION]` tags and are indexed in §13.

## 1. Vision

Lorekeeper already turns a GM's terse session notes into narrative and answers questions from that record. It cites its sources and says "not from your journal" rather than inventing lore. What it does not do is model the world the journal describes. NPC and Quest records are loose text rows, places, factions and items don't exist as records, and nothing changes as the story moves on.

After this expansion, writing the session journal is how the world gets updated. Each saved entry proposes changes to a structured **World Model**: new characters, places, factions and items, deaths and departures, Quest Progress, new Relationships. The GM approves each change, so nothing becomes canon on the model's say-so. Everything else is built on that model:

- a continuity checker that catches the dead NPC who walks back in;
- a relationship web;
- in-character conversation with an NPC that knows only what it plausibly could;
- a spoiler-safe portal where players browse the world and keep their own character journals.

Keepsakes follow: a narrated "Previously on…" and the whole Campaign exported as a book.

It all runs on the group's own machine with the network unplugged, on CPU if there is no GPU. The new AI features are evaluated with the same published, reproducible method as the existing retrieval layer, because a capstone has to show its numbers. The limits are honest ones. A 7B model on CPU is slow, so features are designed around Jobs and progress. The continuity checker is best-effort. Nothing here is a deep moat: the edge is local-first operation, grounding discipline and integration.

## 2. Target user

### 2.1 Jobs to be done

- **GM (primary).** "Stop being the group's database." The GM wants to:
  - track who is alive, who owes whom and where the artifact went, without hand-editing a wiki;
  - catch continuity mistakes before a player does;
  - answer "who was that?" mid-session in seconds;
  - prep faster by questioning NPCs and reading a recap.

  The GM accepts a *short* review step after each Session, but not a long one.
- **Player (secondary).** Between Sessions, a Player wants to look back at the story, follow their own character, keep a character journal and explore the NPCs and places the party has met, without ever seeing what the GM is hiding.
- **Self-hoster and capstone reviewer (tertiary).** Wants to set the product up with one Docker command, run it on modest hardware without a cloud account, and reproduce the evaluation numbers.

### 2.2 Non-users (v1)

- Groups that want a virtual tabletop (tokens, dice, combat, line of sight).
- Groups that will not self-host, or that want a hosted multi-tenant SaaS.
- Anyone who wants AI that generates new lore without a source.

### 2.3 Key user journeys

`[ASSUMPTION: journeys composed from the brief's personas; they were not narrated by the owner]`

- **UJ-1. Dana updates the world by writing her session notes.** Dana runs a two-year fantasy campaign for five players. After Friday's Session she types her shorthand, reviews the narrative and saves it. A minute or two later a **Review Checklist** appears with three groups:
  - *New:* "Location: the Sunken Archive".
  - *Changed:* "Mira: alive → deceased (entry 'The Bell Tower')".
  - *Quest progress:* "Find the Dawnbreaker: step 2 done".

  She edits one item, rejects a false positive and approves the rest in about two minutes. The NPC page and the relationship web now show Mira as deceased, with a citation. **Edge case:** the model proposes a new NPC "Brother Aldric", but Aldric already exists. The item shows the existing match. Dana picks "same as Aldric", and the system adds an alias.
- **UJ-2. Dana is warned before a dead NPC reappears.** Three weeks later Dana writes "Mira greets the party at the gate." The save goes through, and a **Continuity Flag** appears beside the entry: "Mira is deceased since 'The Bell Tower'", with both sentences quoted. The return is deliberate (a resurrection arc), so she chooses "Override", writes "resurrected by the Lantern cult" and accepts the offered change "Mira: deceased → alive". That **Canon Note** is now part of the record.
- **UJ-3. Sam catches up between Sessions without spoilers.** Sam, a player, opens the **Player Portal** on his phone on Tuesday. His character page shows Kael's story so far. He sees the party's NPCs and locations and plays the narrated recap. He adds a **Player Journal** entry in Kael's voice. He asks the **Chronicler** "who hired us in Karak Dun?" and gets a cited answer. Nothing he can reach hints at the traitor Dana has marked **GM-only**.
- **UJ-4. Dana answers "who was that?" during play.** At the table, Dana starts a **Live Session**. Captions arrive in chunks every 10 to 30 seconds, and a **Rolling Recap** refreshes about every minute. A player asks who the dwarf smith was. Dana taps "Borin" in the transcript, and an Entity card with his latest Mentions opens within 2 seconds. When the Live Session ends, the transcript becomes a draft Journal Entry, which then follows UJ-1.
- **UJ-5. Dana preps by interviewing an NPC.** Before a Session Dana opens Veyra's page and chooses "Talk to Veyra". Veyra answers in character about what she witnessed. Asked about the cult's leader, whom she has never met, she deflects in character, and the reply is labelled "not from this NPC's memories". Each reply lists the entries it drew on.
- **UJ-6. The table opens with "Previously on…" and closes the arc with a book.** Dana plays a two-minute narrated recap in a fantasy narrator voice at the start of a Session. At the end of the arc she exports the Campaign as an EPUB and a PDF Chronicle and shares the Player edition with the group.

## 3. Glossary

Downstream documents must use these terms exactly.

- **Campaign**: the top-level container. Every other record belongs to exactly one Campaign.
- **Owner**: the user who created the Campaign. The Owner always has the GM Role.
- **Role**: a Member's permission level in one Campaign. A **GM** is the Owner or a Member granted **Co-GM**. A **Player** is any other Member. A GM sees and edits everything. A Player sees only content their Visibility allows and writes only their own Player Journal entries and their own PC's Character Sheet. A user may hold different Roles in different Campaigns.
- **Member**: a user with access to a Campaign, either the Owner or a user with a membership record. Each Member has one Role.
- **Share Link**: a token URL. A **read-only Share Link** gives anonymous read access to Party content. A **collaborate Share Link** lets a signed-in user join as a Member with the Role stored on the link.
- **Visibility**: an access label on every record and on every Entity text field. It takes one of three values:
  - **Party**: visible to all Members and to read-only Share Links.
  - **GM-only**: visible to GMs only.
  - **Private**: visible to the author and GMs only (used for Player Journal entries and NPC Conversations).

  A **Secret** is a GM-only field on a Party record. **Derived content** (Mentions, generated text, audio, exports, statistics) is never more visible than the most restrictive input it was built from.
- **Journal Entry**: a session write-up made of the GM's **Shorthand** (raw notes, GM-only) and the **Narrative**. A **Player Journal** entry is a Journal Entry authored by a Player, Private by default, which the author can share with Members.
- **Session**: one played meeting of the group, identified by a session date. A Journal Entry belongs to at most one Session.
- **World Model**: the Entities, Mentions and Relationships of a Campaign.
- **Entity**: a campaign-scoped record of a thing in the fiction. The **Entity Types** are Character (kind PC, NPC or creature), Location, Faction, Item and Quest. Each Entity has a name, aliases, a status, a description, GM notes (a Secret) and a change history. A PC Character can be linked to the Player who plays it.
- **Mention**: a stored link between a Journal Entry and an Entity, with the quoted text span that supports it. A Mention is **confirmed** or **suggested**.
- **Relationship**: a typed, directed link between two Entities (for example "member of", "enemy of", "located in", "carries") with the Journal Entry that established it.
- **Change Proposal**: one suggested change to the World Model (a new Entity, a field or status change, a Relationship, Quest Progress, or a Mention), derived from a Journal Entry. It stays pending until a GM decides on it. Change Proposals are always GM-only.
- **Review Checklist**: the list of Change Proposals from one Journal Entry, grouped into **New** (Entities and Relationships), **Changed** (field, status and Relationship changes) and **Quest progress**. Mentions are shown inline on the items they support.
- **Canon**: the approved state of the World Model, plus GM-authored Journal Entries and Canon Notes. Only a GM changes Canon. A Player Journal entry is not Canon unless a GM promotes its proposals.
- **Quest Progress**: a change to a Quest Entity's status or steps.
- **Continuity Flag**: a GM-only warning that a Journal Entry or Change Proposal contradicts Canon. It cites the conflicting Canon.
- **Canon Note**: a GM ruling that resolves a Continuity Flag (a retcon or a confirmed in-fiction explanation). It always has a reason and is GM-only by default. It is part of Canon.
- **NPC Knowledge**: the Journal Entries and Entity fields an NPC Character can draw on. By default these are the entries with a confirmed Mention of the NPC, plus GM **grants** and minus GM **hides**. Grants and hides apply to whole Journal Entries or to individual Entity fields.
- **NPC Conversation**: an in-character chat with an NPC Character, bounded by its NPC Knowledge. It is Private to the user who holds it.
- **Chronicler**: the existing grounded chat assistant that answers questions from the journal.
- **Live Session**: a recording mode during play that produces a chunked transcript, a Rolling Recap and quick lookup.
- **Rolling Recap**: a short summary of the current Live Session, updated about every minute.
- **Narrated Recap**: a "Previously on…" recap text plus the audio spoken by a **Narrator**, which is a local TTS voice preset tied to a genre.
- **Chronicle**: a whole-campaign book export in PDF or EPUB. The **GM edition** can include everything. The **Player edition** includes Party content only.
- **Milestone**: a notable campaign event shown in stats. An **Achievement** is a defined award given once. A **Session Streak** counts the consecutive Sessions a user contributed to.
- **Map**: an uploaded image in a Campaign. A **Pin** is a point on a Map linked to a Location Entity and/or Journal Entries.
- **Job**: a unit of background work with a visible status and progress. The Job's owner is the GM, or the user who started it.
- **Reference Box**: the documented baseline machine: 16 GB RAM, CPU-only, no GPU (owner decision, 2026-10-31). A GPU is optional.
- **Spike**: a time-boxed benchmark or investigation that produces measured numbers for this PRD.

## 4. Foundations and enablers

The recon found that several features rest on capabilities that don't exist yet. All of these foundations, including FR-4 and FR-5, ship in Phase 0 (§9), so the Visibility work (FR-8) protects one Entity table rather than the legacy NPC and Quest tables. FR-9 is a **P0 privacy fix** for leaks in the shipped product. Part (a) ships immediately and on its own. Part (b) is a release gate for Roles (FR-7) and must ship in the same release.

#### FR-1: Background Jobs
The system can run long AI and file work as background Jobs, outside the web request, so users are not blocked and requests don't time out.

**Consequences (testable):**
- Extraction, continuity checks, narration, Chronicle export, Map preparation and backfills run as Jobs. The request that starts one returns a Job ID in under 1 second.
- A Job survives a web-worker restart. After a full stack restart, each pending Job either resumes or is marked failed. No Job is silently lost.
- On the Reference Box, Jobs that need a heavy model run one at a time per model.
- Priority order is: interactive work (quick lookup, NPC replies, Rolling Recap), then on-save Jobs, then backfills. A backfill in one Campaign never delays another Campaign's on-save Jobs by more than one Job.
- A Job uses its owner's LLM configuration, resolved when the Job runs. It never stores raw API keys in the queue, and it meters hosted usage the same way routes do. A missing or exhausted AI configuration fails the Job with a readable reason and no retry.
- Any other failure retries at most twice, then the Job shows `failed` with a readable reason. The Journal Entry that triggered the Job stays saved.

#### FR-2: Job progress in the UI
A user can see the status of their Jobs (queued, running with progress and an estimated time remaining, done, failed) and retry failed ones.

**Consequences (testable):**
- Status changes reach the UI within 5 seconds, with no page reload.
- Job results (Change Proposals, Continuity Flags, failure reasons) are visible only to GMs, whoever triggered the Job.

#### FR-3: Structured AI output
AI features can ask the local LLM for output that matches a declared schema, and they reject output that doesn't.

**Consequences (testable):**
- Every structured response is validated before use. Invalid output gets at most two repair attempts. After that the Job fails with "AI output unusable", and nothing is proposed or written.
- Structured output works with the bundled local model. A BYOK provider without schema support falls back to prompted JSON with the same validation.
- On the EV-1 set, at least 95% of structured responses validate on the first or second attempt. `[ASSUMPTION: threshold]`

#### FR-4: Campaign-scoped Entities
Each Entity belongs to exactly one Campaign. The same name in two Campaigns refers to two different Entities.

**Consequences (testable):**
- Creating "Mira" in Campaign A and in Campaign B creates two Entities. Edits to one never appear in the other.
- Mentions, Relationships and NPC Knowledge never cross Campaigns.
- Existing global tags keep working unchanged. New features read Entities and Mentions, not tags.

#### FR-5: Migrate existing NPC and Quest records into the World Model
On upgrade, existing NPC and Quest records become Entities with no data loss. `[ASSUMPTION: mapping in §11]`

**Consequences (testable):**
- NPC records with role npc, pc or monster become Character Entities. Records with role faction become Faction Entities. Quests become Quest Entities. Name, status, description and notes carry over, and notes become a Secret.
- Migrated Entities start **GM-only**. The GM publishes them to Party in bulk (FR-41), so no existing record surfaces to a Player by default. `[ASSUMPTION]` Because existing Members migrate to Player (FR-7), they don't see migrated NPCs and Quests until the GM publishes them, and the release notes say so.
- Existing links to the old NPC and Quest pages resolve to the migrated Entity.
- Journal Entries whose Narrative matches an Entity name get *suggested* Mentions, which the GM confirms or removes.
- The migration gives identical results on repeated runs against a copy of production data, and it does not crash-loop the backend at boot.

#### FR-6: Edit and delete a Journal Entry
The author or a GM can edit an existing Journal Entry's Shorthand, Narrative, Session and Visibility. Today entries can only be created and deleted. Deleting an entry has defined effects on everything derived from it.

**Consequences (testable):**
- After an edit, search, chat retrieval, tags and duplicate detection reflect the new text.
- When F1 or F2 is present, editing a GM-authored entry supersedes that entry's pending, unedited Change Proposals and queues new extraction (FR-13) and a new continuity check (FR-19). Editing a Player Journal entry queues neither.
- Approved Canon is never changed automatically by an edit. Any change goes through the Review Checklist.
- Deleting an entry removes its Mentions and its NPC Knowledge links. Canon fields whose only source was that entry are flagged for GM review, and their history shows "source deleted". Citations to the entry stop resolving to its content.
- A Player can edit or delete only their own Player Journal entries.

#### FR-7: Membership Roles
Every Member has a Role. The Owner assigns and changes Roles.

**Consequences (testable):**
- The Owner is always a GM and cannot be demoted.
- A collaborate Share Link stores the Role it grants, which defaults to Player, and can have an expiry. `[ASSUMPTION]` Collaborate links already issued migrate to grant Player. `[ASSUMPTION]`
- Existing Members migrate to **Player** (owner decision, privacy first). The Owner promotes Co-GMs by hand. Their existing chat sessions in that Campaign are archived, and the Journal Entries they already wrote stay Party-visible but become editable only by GMs. FR-9(b) therefore protects existing Members from the day Roles ship.
- A Player can write only their own Player Journal entries and their own PC's Character Sheet. Any other write route returns the same response as "not found". Every write response passes through the same Visibility filter as reads.
- Campaign management (Share Links, Roles, deletion) stays Owner-only.
- Joining as a Player does not require a paid or granted account for Party-content routes. Hosted-AI routes still apply the existing BYOK and quota rules. `[ASSUMPTION]`

#### FR-8: Visibility everywhere, with one enforcement point
Every record and every Entity text field has a Visibility. A single shared enforcement point applies the requester's Role to every read path, write response, file download and AI context in a Campaign.

**Consequences (testable):**
- **Covered records:** Journal Entries, Entities and all their text fields, aliases, Mentions, Relationships, Entity history, Quest steps, Canon Notes, Continuity Flags, Change Proposals, source documents, Session Plans, Character Sheets, Shorthand glossary terms, Tag Categories, Narrated Recaps (text and audio), NPC Conversations, Live Session transcripts and Rolling Recaps, Maps, Pins, map tiles, Chronicle files, Jobs and stats.
- **Defaults:**
  - GM-only: Shorthand, GM notes, Session Plans, Shorthand glossary, uploaded source documents, Canon Notes, Live Session transcripts and Rolling Recaps.
  - Always GM-only, whatever their setting: Change Proposals and Continuity Flags.
  - Private: Player Journal entries and NPC Conversations.
  - Party: Narratives, PC Character Sheets.
- **Visibility follows evidence:** a Change Proposal whose supporting quote is in a Party Narrative defaults to Party. One supported only by Shorthand, a GM-only entry or GM notes defaults to GM-only. The Review Checklist shows each item's Visibility, the GM can change it, and "Approve all" never changes it.
- A Party record that points at a GM-only record (a Relationship to a hidden Entity, a Mention in a hidden entry) is served to Players with that reference removed.
- Reads that span Campaigns, and fetches by bare ID, apply the requester's Role in each record's Campaign. When a Player fetches a GM-only record, the response is identical to "not found".
- For Players, the following GM authoring and AI routes are unavailable: NPC and Quest generation, NPC name extraction, Quest suggestion, journal recap, summarize, autocomplete and reindex, Session Plan generation, and source upload and delete. Calling them returns "not found".
- Every AI feature acting for a Player assembles its context only from content that Player may see, so no generated output can carry a GM-only fact.
- Every stored file (map tiles, audio, Chronicle files, kept raw audio) is served only through an access-checked route with unguessable URLs, never as a public static path.

#### FR-9: P0. Stop GM content leaking through Share Links, chat and search
Today a read-only Share Link anonymously serves every Journal Entry with its Shorthand, plus NPC and Quest notes. Chat responses carry Shorthand in the cited sources and in every retrieval candidate, including ones that failed the gate. The system prompt in the trace and the injected glossary carry GM content. Keyword search and entry matching index Shorthand. Today every Member is a collaborator, so the chat and search paths become leaks the moment Player Roles exist.

**Consequences (testable):**
- **(a) Ships now, independently.** Read-only Share Link responses contain no Shorthand, no NPC or Quest notes and no Secrets, and once FR-8 exists, no GM-only records. An automated test asserts this field by field. Release notes tell Owners what existing links no longer show.
- **(b) Ships in the same release as FR-7.** For Players and read-only Share Links:
  - chat sources, all retrieval candidates, the canon sources and the returned system prompt contain no Shorthand, no GM-only record IDs or snippets, and no GM-only source titles;
  - the Shorthand glossary is never injected into their prompts;
  - keyword search, chat retrieval and entry-for-Entity matching rank and match on Party content only, so a word that appears only in Shorthand cannot change their result set or ranking.

  Both the blocking and the streaming chat endpoints are covered.
- When a Member becomes a Player (by migration or by demotion), their existing NPC Conversations and chat sessions in that Campaign are archived and never replayed into new prompts.

#### FR-10: Campaign-wide analytics and export
Campaign analytics and export cover every Member's Journal Entries, not only the Owner's.

**Consequences (testable):**
- In a Campaign with entries from three Members, analytics totals and the export include all three Members' entries.
- Access uses the standard per-Campaign check. GMs get everything. Players get only what FR-8 allows them.

## 5. Features

### 5.1 Living World Model and auto-extraction (F1, the foundation)

**Description.** When a GM-authored Journal Entry is saved or edited, a Job reads it alongside the current World Model and produces Change Proposals: new Entities, status and field changes ("Mira: alive → deceased"), Quest Progress, Relationships and Mentions. The GM reviews them in one Review Checklist grouped by New, Changed and Quest progress (owner decision). The checklist extends the existing narrative review panel's look, copy and draft-then-commit contract to a list of typed items. Nothing becomes Canon without GM approval. Entities get detail panels like today's NPC panel, each with a change history that cites its sources. Realizes UJ-1. F2, F3, F6 and F7 depend on F1. F4 (lookup), F8 (appendix), F9 (Mention stats) and F10 (Location links) are richer with it.

#### FR-11: Entity records
A GM can view, create, edit and delete Entities of every Entity Type. A Player can view Party Entities.

**Consequences (testable):**
- Each Entity Type has a list page and a detail panel. The panel shows name, aliases, status, description, GM notes (GMs only), Mentions and Relationships.
- Character status values include at least alive, deceased, missing and unknown. Location, Faction and Item status values include at least active, destroyed or disbanded, and unknown. Quests keep today's statuses and add steps.

#### FR-12: Mentions
A Journal Entry links to the Entities it mentions, with the supporting quote stored.

**Consequences (testable):**
- An Entity's panel lists its confirmed Mentions newest-first, each with its quote. This replaces today's name-substring lookup.
- A Journal Entry's view lists the Entities it mentions, and each one opens that Entity's panel.

#### FR-13: Generate Change Proposals on save
Saving or editing a GM-authored Journal Entry queues an extraction Job that produces Change Proposals.

**Consequences (testable):**
- Proposal types are new Entity, field or status change, new or changed Relationship, Quest Progress and Mention.
- Each proposal carries its source entry, its supporting quote, its default Visibility (FR-8) and, for changes, the old and new values.
- Proposals that would change nothing in Canon are not shown.
- The Job meets the provisional target in NFR-6.

#### FR-14: Entity matching
When the text names an existing Entity or one of its aliases, the proposal refers to that Entity instead of proposing a duplicate.

**Consequences (testable):**
- An uncertain match offers up to three candidate Entities plus "new Entity". Choosing a candidate adds the surface form as an alias.
- On EV-1, duplicate-Entity proposals for already-known Entities are at most 10% of new-Entity proposals. `[ASSUMPTION: target]`

#### FR-15: Review Checklist
A GM reviews all Change Proposals from one Journal Entry in one checklist grouped into New, Changed and Quest progress.

**Consequences (testable):**
- Each item is in one of four states: pending, edited, approved or rejected. The GM can edit, approve or reject any item. "Approve all" approves every pending or edited item. Items already approved or rejected stay as they are.
- The checklist opens from the post-save flow and from a pending-reviews indicator.
- At approval, the system re-checks each item's old value against current Canon. If Canon has changed since the proposal was made, or the target Entity was merged or deleted, the item is marked stale and needs re-confirmation, and it is redirected to the surviving Entity where one exists.
- A rejected proposal is not raised again for that entry.
- Players never see Change Proposals.

#### FR-16: Provenance and history
Every approved change is recorded with its source entry, its approver and its time, and can be reverted.

**Consequences (testable):**
- An Entity's history lists each change with a link to its source.
- A revert restores the previous value and is itself recorded.

#### FR-17: Merge Entities
A GM can merge two Entities of the same type.

**Consequences (testable):**
- The surviving Entity keeps both Entities' aliases, Mentions, Relationships and history. Links to the removed Entity resolve to the survivor.
- Each merged field and alias keeps the more restrictive Visibility of its two sources. The GM is warned when a merge combines a Party Entity with a GM-only one.

#### FR-18: Re-run extraction
A GM can re-run extraction for one Journal Entry, or for the whole Campaign as a backfill.

**Consequences (testable):**
- A re-run never duplicates pending proposals and never raises proposals that were already decided.
- A backfill runs as one low-priority Job (FR-1) with per-entry progress.

### 5.2 Canon guard: continuity checker (F2)

**Description.** After a GM-authored Journal Entry is saved or edited, a Job checks the entry's claims against Canon (Entity state, earlier entries and Canon Notes). It raises Continuity Flags for likely contradictions: a dead NPC who reappears, a Location that has moved, an Item held by two Characters. The check is best-effort. A flag never blocks saving, and it always cites the conflicting Canon. The GM dismisses the flag or overrides it with a Canon Note (owner decision). The check reuses the existing retrieval and relevance gate. Realizes UJ-2.

#### FR-19: Continuity check on save
Saving or editing a GM-authored Journal Entry queues a continuity check.

**Consequences (testable):**
- Every Continuity Flag cites at least one conflicting Journal Entry, Entity field or Canon Note, and quotes both sides.
- Only claims that share an Entity with the cited Canon are compared.
- On EV-2, the check meets the provisional targets in §7.

#### FR-20: Continuity Flag display
A GM sees Continuity Flags beside the entry and in that entry's Review Checklist, and can dismiss them.

**Consequences (testable):**
- A pending or failed check never blocks or delays saving.
- A dismissal records a reason: false alarm, flashback or in-fiction framing, or other.
- The UI states that the check is best-effort and that the absence of a flag does not prove consistency.

#### FR-21: Override with a Canon Note (retcon)
A GM can override a Continuity Flag by recording a Canon Note with a reason. The Canon Note becomes part of Canon.

**Consequences (testable):**
- The reason field is required.
- An override offers the matching Entity change (for example "Mira: deceased → alive") as a Change Proposal.
- Later checks do not raise the same conflict again. A conflict is "the same" when it involves the same Entity, the same Canon reference and the same attribute.
- The Chronicler can cite Canon Notes as sources, subject to Visibility.
- A Canon Note appears in the history of the Entities it concerns.

#### FR-22: Contradicting proposals are marked
A Change Proposal that contradicts Canon (for example, progress on a Quest already marked failed) is marked in the Review Checklist, with the conflicting Canon cited.

**Consequences (testable):**
- The GM can still approve a marked proposal. On approval the system offers a Canon Note.

### 5.3 Relationship web (F3)

**Description.** An interactive graph of Characters, Factions, Locations and Items and the Relationships between them, built from Canon and filtered by Visibility. Realizes UJ-1 and UJ-3.

#### FR-23: Relationships
A GM can create, edit and end typed, directed Relationships. Approved Change Proposals can also create them.

**Consequences (testable):**
- Each Relationship has a type from a per-Campaign editable list, a direction, an optional note, a Visibility and the source entry.
- An ended Relationship (for example "formerly allied with") stays in the history.

#### FR-24: Interactive graph
A Member can pan, zoom, search and filter the graph by Entity Type, Relationship type or Faction, and open any node's detail panel.

**Consequences (testable):**
- Node style reflects Entity Type and status, so a deceased Character is visibly distinct.
- With 300 nodes and 600 edges, the graph pans and zooms at 30 fps or better in current Chrome on the reference laptop named in `docs/BENCHMARKS.md`. `[ASSUMPTION: target]`
- An approved Relationship appears without a manual refresh.
- A keyboard-accessible list view shows the same nodes and edges.

#### FR-25: Player view of the graph
A Player sees only Party Entities and Relationships. The graph's layout, counts and search reveal nothing about hidden nodes.

**Consequences (testable):**
- For a Player, the graph response contains no GM-only nodes or edges (EV-4).

### 5.4 Live Session mode (F4)

**Description.** During play, a GM starts a Live Session. The browser captures table audio and sends it in chunks. A small local speech-to-text model transcribes chunks of about 10 to 30 seconds, and captions appear chunk by chunk. A Rolling Recap and the lookup panel refresh about every minute (owner decision). Near-real-time captions are a GPU-only enhancement. At the end of the Live Session the transcript feeds the existing summarize-to-shorthand flow and becomes a draft entry. Speaker labels are optional and run after the session. The existing single-recording transcription keeps working. Quick lookup by Entity needs F1. Without F1, lookup searches the legacy NPC records. Realizes UJ-4.

#### FR-26: Start and run a Live Session
A GM can start, pause and end a Live Session. Transcript text appears chunk by chunk.

**Consequences (testable):**
- On the Reference Box, transcription keeps pace with speech over a 2-hour Live Session: average processing time per chunk is no more than the chunk's duration, and caption lag meets NFR-6. The UI shows the current lag.
- If transcription falls behind, a backlog indicator appears. Audio is queued, not dropped, up to a 10-minute backlog. Beyond that, the oldest unprocessed audio is skipped with a visible notice. `[ASSUMPTION]`
- A dropped connection or a page refresh resumes the same Live Session with no loss of already-transcribed text.

#### FR-27: Rolling Recap
During a Live Session, the Rolling Recap updates about every 60 seconds.

**Consequences (testable):**
- The recap is updated incrementally from new transcript text, and it keeps earlier content. In a recorded 2-hour clip, a fact stated only in minute 5 is still in the final Rolling Recap.
- The recap is labelled as generated from the transcript, not from the journal.

#### FR-28: Quick lookup
During a Live Session, a GM can tap a recognized name in the transcript, or type a name, to see the Entity card and its latest Mentions.

**Consequences (testable):**
- A name lookup returns the card in under 2 seconds on the Reference Box.
- Transcript words that match an Entity name or alias are tappable.
- A free-text question ("who was the dwarf smith?") gets a cited answer from the Chronicler, with the "not from your journal" label when nothing passes the gate.

#### FR-29: End-of-session hand-off
Ending a Live Session lets the GM turn the transcript into a draft Journal Entry through the existing review-then-save flow.

**Consequences (testable):**
- The full transcript is used, with no silent truncation.
- The draft is never saved without explicit GM approval. Once saved, it triggers F1 and F2 Jobs when those features are present.
- Raw audio is deleted once it has been transcribed, unless the GM chooses to keep it. If speaker labelling (FR-30) is requested, the audio is kept until that Job finishes. `[ASSUMPTION]`

#### FR-30: Offline speaker labels (optional)
A GM can ask for speaker labels on a finished Live Session transcript, which run as a Job.

**Consequences (testable):**
- Off by default. Requesting labels before the Live Session ends keeps the audio until the Job finishes. If the diarization model isn't installed, the option is hidden.

### 5.5 Narrated "Previously on…" recaps (F5)

**Description.** A GM generates a short recap of recent Sessions in the Campaign's genre voice, edits the text, and has a local TTS Narrator speak it. The audio is produced in a Job, cached, and replayed at the table. The brief's example engine (Piper) is no longer licence-compatible. The PRD therefore states the capability, and the addendum names the engine. Realizes UJ-6.

#### FR-31: Recap text
A GM can generate a "Previously on…" recap of the last N Sessions (default 1, up to 5) in the genre voice, then edit it before saving.

**Consequences (testable):**
- The recap opens with "Previously on…" and is written in the Campaign genre's voice.
- It draws only on the selected Sessions' entries and cites them. It is never persisted without an explicit save.
- By default it is built from Party content only, because it is meant for the table. If the GM includes GM-only content, the recap becomes GM-only.
- On EV-6, the recap meets the faithfulness target.

#### FR-32: Narration
A GM can narrate a saved recap with a chosen Narrator as a Job, then play, replay or download the audio.

**Consequences (testable):**
- Narrating a 300-word recap meets NFR-6.
- Replaying an unchanged recap uses the cached audio. Editing the text, or changing the Visibility of any source entry, invalidates the cache.

#### FR-33: Narrators and fallback
Each genre has a default Narrator, and the GM can choose a different one.

**Consequences (testable):**
- At least one Narrator ships for each genre: fantasy, sci-fi, horror, video game and other. Narrators may share base voices. `[ASSUMPTION: defaults in §11]`
- If the TTS service is down, the recap text is shown with a read-aloud option that uses only on-device browser voices. The UI says that the Narrator is unavailable.
- **Editions (owner decision).** The AGPL build ships the local Narrator engine (Kokoro with espeak-ng) as an optional TTS container. The commercial edition ships no local TTS engine and offers only browser read-aloud until a permissively licensed engine passes the proper-noun test: every Entity name in the demo seed survives a TTS-then-STT round-trip. Narration code doesn't depend on one engine, so a passing engine can be added without changing these FRs.
- Narrators never silently drop words. The spike showed that Kokoro without espeak-ng drops every fantasy name from the audio, so any engine configuration that loses proper nouns fails this FR.

#### FR-34: Players hear Party recaps
Players can play Party Narrated Recaps from the Player Portal.

**Consequences (testable):**
- A GM-only recap's text and audio are absent from every Player response and audio route (EV-4).

### 5.6 Talk to an NPC (F6)

**Description.** A GM, and a Player where the GM allows it, can hold an NPC Conversation in character. The NPC speaks from its persona and is limited to its NPC Knowledge. By default that knowledge is the entries where the NPC has a confirmed Mention, and the GM can grant or hide entries and fields per NPC (owner decision). When asked about something outside its knowledge, the NPC deflects in character rather than inventing an answer. Conversations are not Canon. Realizes UJ-5.

#### FR-35: Start an NPC Conversation
A GM can start an NPC Conversation from an NPC's panel. The NPC replies in character using its name, description, status and any voice notes.

**Consequences (testable):**
- Replies stream, and the first token arrives within NFR-6.
- If the NPC is deceased or missing in Canon, the conversation opens with a notice that states the status and its source. The GM can continue.

#### FR-36: NPC Knowledge boundary
An NPC's replies draw only on its NPC Knowledge.

**Consequences (testable):**
- The GM can view an NPC's knowledge list and grant or hide individual Journal Entries or Entity fields, including Secrets. Changes apply from the next reply.
- Suggested Mentions, unapproved proposals and other NPCs' Conversations never enter an NPC's knowledge.
- On EV-3, the leak rate and answer rate meet the provisional targets.

#### FR-37: In-character refusal and citations
When asked about something outside its NPC Knowledge, the NPC says in character that it doesn't know. Each reply lists the entries it drew on.

**Consequences (testable):**
- A reply with no supporting knowledge carries a "not from this NPC's memories" label.

#### FR-38: Conversations are not Canon
NPC Conversations are saved as Private chat history. They never change the World Model or the journal on their own.

**Consequences (testable):**
- A GM can copy a passage into a new Journal Entry draft, which then goes through normal review.

#### FR-39: Player NPC Conversations (GM-enabled)
A GM can enable NPC Conversations for Players on specific NPCs.

**Consequences (testable):**
- Off for every NPC by default. `[ASSUMPTION]`
- For a Player, the persona uses only the NPC's Party fields, and the knowledge is limited to Party content. GM voice notes, GM-only grants and Secrets are excluded. Each Player's conversation history is separate.
- On EV-3 and EV-4, a Player's NPC Conversation surfaces no GM-only content.

### 5.7 Player Portal (F7)

**Description.** Players get their own view of the Campaign:

- a spoiler-filtered wiki of Party Entities, Narratives, Relationships, Maps and Narrated Recaps;
- a "my character" page;
- their own Player Journal;
- a Chronicler limited to what they may see.

GMs set Visibility and can preview the portal as a Player. The portal requires FR-7, FR-8, FR-9 and F1. Realizes UJ-3.

#### FR-40: Portal home and wiki
A Player who opens the Campaign sees the Player Portal: recent Narratives, their PC, Party Entities by type, the relationship web, Maps, Narrated Recaps and search.

**Consequences (testable):**
- At 375 px wide, the home, Entity, journal, recap and Map views are usable with no horizontal scroll.
- A read-only Share Link shows the same Party content, but without Player Journals or the "my character" page.

#### FR-41: GM visibility controls
A GM can set the Visibility of any record or Entity field, change Visibility in bulk from list views, and preview the portal as a Player.

**Consequences (testable):**
- The "view as Player" preview renders through the same filtered read path a Player uses.
- A Visibility change applies on the next read. Derived content built from the changed record (cached audio, Chronicle files, tiles, caches) is invalidated or hidden until it is regenerated.

#### FR-42: Player Journals
A Player can write, edit and delete their own Player Journal entries. GMs can read them. The author can share an entry with all Members.

**Consequences (testable):**
- Entries are Private by default. `[ASSUMPTION]` Shared entries are visible to Members but never to read-only Share Links.
- Extraction runs on a Player Journal entry only when a GM triggers it. The resulting proposals go to the GM's Review Checklist.

#### FR-43: Player chat
A Player can ask the Chronicler questions. Answers draw only on content that Player may see, plus their own Private entries.

**Consequences (testable):**
- A question about a GM-only fact gets the "not from your journal" label, and the reply gives no hint of hidden content.

#### FR-44: Role and character management
The Owner can invite Members with a Role, change a Member's Role, remove a Member, and link a Player to a PC Character.

**Consequences (testable):**
- A Role change or removal takes effect on the Member's next request. Open streams for that Member close.
- A Player linked to a PC sees that PC's Party Mentions and their own Player Journal on the "my character" page.

### 5.8 Campaign Chronicle export (F8)

**Description.** The whole Campaign exported as a book: a cover, a table of contents, one chapter per Session, an Entity appendix, and optionally Map images and shared Player Journal entries. It comes in PDF and EPUB, as a GM edition and a Player edition. It extends today's export, which is author-only, limited to Latin-1, and prints one page per entry. Realizes UJ-6.

#### FR-45: Chronicle as PDF and EPUB
A GM can export either edition. A Player can export the Player edition.

**Consequences (testable):**
- The book includes:
  - a cover with the Campaign name, genre and date range;
  - a table of contents, with page numbers in the PDF and navigation in the EPUB;
  - chapters ordered by Session date;
  - when F1 data exists, an Entity appendix grouped by type.
- The GM can include shared Player Journal entries in their Sessions' chapters.
- The EPUB passes the standard EPUB validator with no errors.

#### FR-46: Full Unicode text
Exported text renders accented, non-Latin and typographic characters correctly.

**Consequences (testable):**
- An entry containing "Ælfrida", "Ōkami", "—" and "“quotes”" renders correctly in both formats, with no "?" substitution.

#### FR-47: Export as a Job
Export runs as a Job and produces a file that can be downloaded through an access-checked route.

**Consequences (testable):**
- On the Reference Box, a 100-entry Campaign exports within NFR-6.

#### FR-48: Editions follow Visibility
The Player edition includes Party content only. The GM edition includes Shorthand and Secrets when the GM opts in.

**Consequences (testable):**
- The Player edition is built through the FR-8 read path and is covered by EV-4.

### 5.9 Milestones and stats (F9)

**Description.** The analytics page grows into Campaign stats and celebrations: Sessions played, Session Streaks, most-mentioned Entities, Quest completion rate and Achievements. Streaks count Sessions, not days, and include an automatic grace. They are opt-in and can be hidden. The page celebrates; it never uses loss messaging. Stats cover every Member's entries (FR-10).

#### FR-49: Campaign stats
A Member can see Sessions played, entries per Session, contributions per Member, most-mentioned Entities and the Quest completion rate.

**Consequences (testable):**
- Most-mentioned Entities come from Mentions. Before F1 they come from tags.
- Quest completion rate is completed Quests divided by all Quests that are closed or active. A tooltip shows this definition.
- Every stat a Player sees is computed only from content that Player may see.

#### FR-50: Achievements and Milestones
The system awards each defined Achievement once per user per Campaign, and shows Milestones such as "10th Session", "first Quest completed" and "100 Entities in the world".

**Consequences (testable):**
- Recomputing never awards the same Achievement twice.
- The Milestone counts a Player sees come only from content that Player may see.
- There are no loss messages, countdowns or reminder nags.

#### FR-51: Streaks are opt-in and hideable
Each user can turn Session Streaks and Achievements on or off for themselves.

**Consequences (testable):**
- Off by default. A streak survives one missed Session through automatic grace. `[ASSUMPTION]`

### 5.10 Map pins (F10)

**Description.** A GM uploads Map images and places Pins linked to Location Entities and to Journal Entries. Large Maps are zoomable. Pins respect Visibility. Without F1, Pins link to entries only. Realizes UJ-3.

#### FR-52: Upload Maps
A GM can upload, rename, replace and delete Maps.

**Consequences (testable):**
- PNG, JPEG and WebP images are accepted, up to 50 MB and 16,000 px on the longest side. `[ASSUMPTION]` Other files are rejected with a clear message.
- Large Maps are prepared as a Job. Once prepared, a 16,000 px Map can be panned and zoomed on the Reference Box with each view loading in under 1 second.
- Map files persist across restarts, are included in backups, and are served only through access-checked routes (FR-8).

#### FR-53: Pins
A GM can place, move, edit and delete Pins. Each Pin has a label and links to a Location Entity and/or Journal Entries.

**Consequences (testable):**
- Pin positions are stored relative to the image. They stay correct at every zoom level and after the image is replaced with one of the same aspect ratio.
- Clicking a Pin opens the linked Location's panel or the list of linked entries. A Location's panel lists its Pins.

#### FR-54: Map and Pin Visibility
Players see only Party Maps and Party Pins.

**Consequences (testable):**
- A GM-only Pin on a Party Map is absent from the Player's response, and the Map's tiles reveal no GM-only Pin (EV-4).

#### FR-55: Pins in the World Model
When F1 approves a new Location and the Campaign has at least one Map, the Review Checklist offers to place that Location on a Map.

**Consequences (testable):**
- Choosing the offer opens the Map in placement mode for that Location. Declining it creates no Pin.

## 6. Cross-cutting non-functional requirements

#### NFR-1: Local and offline
Every feature runs on the group's own host with no internet connection once installed. No feature needs a cloud service. Per-user BYOK stays optional.
- Demo scenarios DS-1 to DS-5 pass with the host's internet disconnected. Players and GMs reach the host over the local network, or over remote access the group runs itself, through the existing HTTPS front end. Microphone capture needs HTTPS.
- No new code makes outbound calls, except the existing opt-in BYOK and model-install paths.
- Every new model can be downloaded ahead of time and installed offline.
- One `docker compose up` brings up all new services. New models install through the existing admin model-install flow, or are baked into images.

#### NFR-2: Reference Box baseline and graceful degradation
Every feature works on the Reference Box. A GPU is optional and only makes features faster.
- No feature fails for lack of a GPU. Extraction, continuity checks, narration and export run as Jobs with progress. Live captions arrive in chunks. Speaker labels are offline and optional.
- There is **one profile**. It runs CPU-only on the 16 GB Reference Box, and a GPU only makes it faster. There is no separate low-memory profile.
- The sum of all container memory limits stays at or below **14.5 GB**, which leaves at least 1.5 GB for the OS and Docker. The stack stays within those limits in each of these cases: idle; one heavy Job; and a Live Session with speech-to-text plus Rolling Recap updates. Optional post-session speaker labels (FR-30) run outside the sum, only while speech-to-text is unloaded. The architecture holds the per-container split (spine AD-7).
- The recon measured the backend web tier alone at about 6.4 GB idle and 11.9 GB peak, with models loaded in each web worker, so today's stack does not fit. Phase 0 must deliver the profile, not just measure it (SPIKE-5).
- The owner set the 16 GB baseline on 2026-10-31, replacing the earlier 8 GB baseline with its ≤ 7.5 GB peak. Changing it again is an owner decision, not an outcome the implementation may choose.

#### NFR-3: Model isolation
New AI models (speech-to-text, TTS, NLI, diarization) run in their own containers or in queued Jobs that load them lazily. They are never loaded inside each web worker.
- Adding a feature does not multiply model memory by the number of web workers.
- The existing in-process speech-to-text and OCR also move out of the web workers, and the existing voice-upload path uses the new speech-to-text service.
- During a Live Session, speech-to-text is the only newly added model kept resident.
- The bundled 7B LLM is reused, and no third resident LLM is added.

#### NFR-4: Licence compatibility
Lorekeeper has an open-source core and a commercial licence. Every new dependency must be distributable under both, including libraries, system packages, containers, model weights, voices and fonts. In practice this means permissive licences only in the commercial build. The core licence is **AGPL-3.0**, dual-licensed with a commercial licence (owner-confirmed, matching the repo's LICENSE and COMMERCIAL-LICENSE.md).
- The one sanctioned exception is TTS: the AGPL build may ship the GPL-3.0+ espeak-ng phonemizer, but only inside the optional TTS container. The commercial build never ships it (FR-33).
- A licence register lists every new dependency with its licence, source and use.
- On every PR and on `main`, whatever paths changed, CI runs a licence check. The check fails the commercial build on GPL, AGPL, statically linked LGPL, non-commercial, Hippocratic or unknown licences. Exceptions go on a reviewed allowlist, for example dynamically linked LGPL system libraries.
- Model weights, voices and container system packages that scanners can't read are checked against the register by a CI step that fails on unregistered artifacts.
- Backend CI runs on `main`. Today it triggers on `master` only, so it never runs on the default branch.

#### NFR-5: Privacy and spoiler safety
Players never see GM-only content. This is a hard gate, not a target.
- EV-4 runs in CI and must report zero leaks before a release ships.
- Live Session audio is processed locally and deleted after transcription by default (FR-29).
- No new telemetry is added. Campaign data leaves the host only through user-initiated exports and opt-in BYOK.

#### NFR-6: Latency targets (provisional)
These targets are provisional. SPIKE-1 to SPIKE-6 measure the Reference Box, and the targets are reset in the PRD update that records the results. Resetting a target needs owner sign-off, recorded in the PRD run log (`.memlog.md`).

| Operation | Reference Box (CPU) | With GPU |
|---|---|---|
| Change Proposals ready after save (≈500-word entry) | ≤ 3 min | ≤ 30 s |
| Continuity check complete after save | ≤ 3 min | ≤ 30 s |
| Live caption lag (chunk end → text shown) | ≤ 30 s, with sustained processing ≤ chunk duration | ≤ 5 s |
| Rolling Recap update | ≈ 60 s cadence, each update ≤ 45 s | ≈ 60 s |
| Quick lookup by name | ≤ 2 s | ≤ 2 s |
| NPC Conversation first token | ≤ 20 s | ≤ 3 s |
| Narration of a 300-word recap | ≤ 2 min | ≤ 30 s |
| Chronicle export, 100 entries | ≤ 3 min | n/a |
| Portal page load (warm) | ≤ 2 s | ≤ 2 s |

#### NFR-7: Grounding and honest limits
Every new AI output that states campaign facts either cites its sources or carries the "not from your journal" or "not from this NPC's memories" label. AI output never changes Canon without explicit GM approval. Where a feature is best-effort or slow, the UI says so: the continuity check states its limit (FR-20), and Jobs show estimated time remaining (FR-2).

#### NFR-8: Brownfield consistency
New work extends existing patterns rather than replacing them:
- AI routes keep BYOK resolution, the per-Campaign access check and hosted-usage metering.
- Every new AI or streaming endpoint gets both rate-limit layers. Authenticated AI routes are limited per user, not per IP, so a table sharing one network isn't throttled together.
- Migrations are forward-only, run safely at boot, and are tested by running the migration chain against a copy of an existing database. Tests that build the schema straight from the models are not enough.

#### NFR-9: Failure isolation
A failing AI step never blocks or loses a Journal Entry save. Every failure shows up in Job status (FR-2).

#### NFR-10: Theming and accessibility
New UI uses the six existing themes' tokens and works at 375 px wide. New pages meet WCAG 2.2 AA, and the Review Checklist can be operated entirely by keyboard. A Narrated Recap always shows its text alongside the audio.

#### NFR-11: Shared-server fairness (scope limit)
v1 targets one group per host. On a multi-Campaign server, the only v1 guarantees are FR-1's Job priority and the bound that keeps one Campaign's backfill from delaying another. Per-Campaign quotas are a non-goal.

## 7. Evaluation, success metrics and demo scenarios

Each new AI feature is evaluated the way `docs/RETRIEVAL_EVAL.md` evaluates retrieval. That means a labelled set on the seeded demo Campaign, named metrics, a results table across operating points, a chosen operating point with its reason, a "measured failure → fix" table and a reproduce command. Each eval gets its own doc (`docs/EXTRACTION_EVAL.md`, `CONTINUITY_EVAL.md`, `NPC_KNOWLEDGE_EVAL.md`, `SPOILER_EVAL.md`, `RECAP_EVAL.md`) and its own script. The demo Campaign seed must be committed to the repo (today it isn't).

Each labelled set is split into a tuning half and a held-out half. Results are reported on the held-out half. The small set sizes are a known limitation and are stated in each doc. Targets are provisional until the first baseline run. `[ASSUMPTION: targets]`

- **EV-1. Extraction (F1).** The 9 demo entries plus at least 6 new ones with deliberate status changes, Quest Progress and Relationships, totalling at least 60 hand-labelled changes. Metrics:
  - precision, recall and F1 for each proposal type;
  - duplicate-Entity rate;
  - first-pass schema-valid rate;
  - Visibility-default correctness (no Shorthand-only fact defaults to Party).

  Operating points: with and without an NER pre-pass, and with and without the existing-Entity list in the prompt.
- **EV-2. Continuity (F2).** At least 10 seeded contradictions, at least 10 clean controls, and traps: 2 flashback or rumour entries and 1 overridden retcon. Metrics: detection rate, false-alarm rate, citation correctness (the cited entry is the real source of the conflict), flashback-trap holds and retcon-trap holds. Operating points: a sweep of the NLI threshold (for example 0.8, 0.9, 0.95), with and without LLM verification.
- **EV-3. NPC knowledge leakage (F6).** For each of 3 NPCs, at least 8 probes about facts the NPC witnessed and at least 8 about facts it never encountered. The second set includes hard negatives from the same Campaign and one GM-hidden fact. Each probe has a written answer key. A reply **leaks** if it states the key fact or a paraphrase of it. A keyword check pre-screens replies, and the owner judges the rest against the key using a written rubric. Metrics: **answer rate** on known facts and **leak rate** on unknown facts, which mirror hit@3 and gate-holds in the retrieval eval.
- **EV-4. Spoiler leakage (Foundations, F7).** An automated CI test seeds a Campaign with GM-only records, Secrets, Private entries and unique canary strings. It then calls every route as a Player, as an anonymous read-only Share Link holder, and as a user who is GM in one Campaign and Player in another. Coverage:
  - reads, writes, search, tags, chat (blocking and streaming), NPC Conversation, graph, stats, Maps and tiles, audio and exports;
  - streaming and WebSocket endpoints and file URLs.

  The route list is derived from the backend router and the front-end proxy config, so an uncovered route fails the test. Pass criteria:
  - **Responses.** No canary may appear in any response.
  - **AI context.** For AI routes, the test captures the context sent to the LLM and asserts it holds no GM-only content. Because the check is on the context, it doesn't depend on what the model writes.
  - **Inference channels.** Hidden and nonexistent records produce identical responses and status codes. Counts match the Party-only fixture. A canary that appears only in Shorthand does not change a Player's search results or ranking.

  **Target: 0 leaks. This is a hard CI gate.** Before each release, a live-model run of the AI routes repeats the context and canary checks.
- **EV-5. Performance.** Wall-clock time and peak memory for every NFR-6 row and every NFR-2 memory case, on the Reference Box and optionally on a GPU. Results go in `docs/BENCHMARKS.md`.
- **EV-6. Recap faithfulness (F4, F5).** 5 Narrated Recaps and 2 Rolling Recaps from recorded clips. Metric: the share of sentences supported by a cited entry, or by the transcript.

### Success metrics

**Primary**
- **SM-1: Extraction quality.** EV-1 held-out F1 ≥ 0.75 overall, and precision ≥ 0.80 on status changes. Validates FR-13 and FR-14.
- **SM-2: Continuity detection.** EV-2 detection ≥ 8/10, false alarms ≤ 2/10, citation correctness on 100% of true flags, retcon trap 1/1 and flashback or rumour traps ≥ 1/2. Validates FR-19 and FR-21.
- **SM-3: NPC knowledge boundary.** EV-3 leak rate ≤ 5% overall and 0 on GM-hidden facts, with answer rate ≥ 75%. Validates FR-36, FR-37 and FR-39.
- **SM-4: Spoiler safety.** EV-4 finds 0 leaks. Validates FR-8, FR-9, FR-25, FR-34, FR-39, FR-43, FR-48 and FR-54.
- **SM-5: Local performance.** Every NFR-6 row and the NFR-2 memory bound are met on the Reference Box, or reset with measured justification and owner sign-off (EV-5). Validates NFR-2 and NFR-6.

**Secondary**
- **SM-6: Review burden.** On the demo run, the median review time per entry is ≤ 3 minutes, and ≤ 25% of approved items needed an edit. Validates FR-15 and the "short review step" JTBD. This measure is graded by the owner and reported with that caveat.
- **SM-7: Live caption quality.** Word error rate ≤ 30% on a recorded 10-minute table clip (provisional, reset after SPIKE-2). Validates FR-26.
- **SM-8: Recap faithfulness.** EV-6 shows ≥ 90% of sentences supported. Validates FR-27 and FR-31.
- **SM-9: Between-session return.** The share of Players who open the portal between Sessions, counted on the host and shown only to the Owner, with no telemetry. Reported, no target. Validates F7 against the Player JTBD.

**Counter-metrics (do not optimize)**
- **SM-C1: Proposals per entry.** Track the median number of proposals per entry (expect ≤ 8) and the rejection rate. Raising recall by flooding the checklist breaks the "short review step" promise.
- **SM-C2: NPC over-refusal.** A zero leak rate is trivial if the NPC refuses everything, so SM-3's answer rate must hold.
- **SM-C3: Flag volume.** False alarms on clean entries erode trust faster than missed contradictions do. Reducing false alarms takes priority over detection gains.
- **SM-C4: Streak engagement.** Usage of streaks and Achievements is not tracked as a goal. They exist to celebrate, not to compel.

### Demo scenarios (capstone)

Each demo is scripted and runs on the seeded demo Campaign on the Reference Box with the internet disconnected (NFR-1).

- **DS-1. Living world.** Save an entry in which an NPC dies and a new location appears. Review the grouped checklist, edit one item, approve all, and see the NPC page and the relationship web update with citations.
- **DS-2. Canon guard.** Write the dead NPC greeting the party and see the flag with both quotes. Override it with a Canon Note and re-save. The flag doesn't return.
- **DS-3. Spoiler-safe portal.** Log in as a Player and browse the wiki, the "my character" page, the graph and the Map. Ask the Chronicler about the GM-only traitor and get "not from your journal". Run EV-4 live and show 0 leaks.
- **DS-4. At the table.** Run a Live Session from a recorded clip and tap an NPC for its card. Then talk to that NPC and watch it decline a question outside its knowledge.
- **DS-5. Keepsakes.** Generate and narrate "Previously on…". Export the Chronicle as EPUB and PDF and open both. Show the stats page with a Milestone.

## 8. Risks and spikes

Most CPU performance figures in the research are unverified or come from a single source. The first work of the expansion is therefore a set of benchmark spikes on the Reference Box. Each spike records its numbers in `docs/BENCHMARKS.md`, with the hardware stated, and updates NFR-6 and the affected FRs through a PRD update.

**First measurements (2026-10-31, `spikes/cpu-benchmarks.md`).** A 45-minute spike ran speech-to-text, TTS and NLI on an Apple M5 Max capped at 4 threads, with one run per configuration. Read the timings as an optimistic upper bound, accurate to about ±50%. The x86 Reference Box is likely 2–5× slower, although arm64 makes int8 look pessimistic. Peak memory carries over better than the timings. The results partly de-risk SPIKE-1 to SPIKE-3. They did not cover diarization (SPIKE-4), 7B throughput (SPIKE-6) or structured extraction, because Ollama was not running. **Every spike must still be re-run on the x86 Reference Box with the Docker stack up.** That re-run sets the final NFR-6 numbers.

| ID | Risk | Measured so far | Spike (time-boxed, remaining work) | Decision it unblocks |
|---|---|---|---|---|
| R-1 | NLI contradiction scoring may be too slow on CPU, or too noisy to trust. | xsmall: 50 pairs in 0.71 s batched, 844 MB peak. Base: 2.58 s, 1.14 GB. Both found all 3 real contradictions (p ≥ 0.97). Both also gave a **confident false contradiction (p ≥ 0.99)** on a neutral pair that shares an Entity, above the planned 0.9 threshold. | **SPIKE-1 (½ day left):** re-measure on x86, especially base at 50 pairs. Speed is de-risked, but precision is not, so **the 7B confirm step on high-scoring pairs stays mandatory** and flags stay dismissible (FR-19, FR-20). Choose xsmall or base only from the EV-2 labelled set. | Model size, pair budget, threshold, FR-19 latency. |
| R-2 | Live caption lag on CPU may exceed the chunk window, so the backlog grows without bound. | faster-whisper **base** fits live use: a 15 s chunk takes 1.5–4.7 s (worst-case RTF 0.31 int8, 0.11 float32), 0.75–0.9 GB peak. **Small doesn't**: worst chunk RTF 1.03 with int8, and float32 passes only at 1.8 GB. Base misspells fantasy names, and small also misspells some. | **SPIKE-2 (½ day left):** re-measure base on x86 with int8 and float32 (a 2–5× slowdown puts base int8 at about 0.6–1.5 RTF, which is marginal), with the LLM idle and busy, and test name prompting from the Entity list. Test the streaming transport only for the GPU enhancement. | Chunk size (15 s proposed), compute type, NFR-6 lag target, SM-7. |
| R-3 | Local TTS may be too slow or too memory-hungry on CPU, and may drop proper nouns. | Kokoro: RTF 0.25–0.38, so a 45 s recap takes 11–17 s. About 1.3–1.4 GB idle, about 2.1 GB peak **synthesising per sentence**, and 3.9 GB per paragraph. Without espeak-ng, **every fantasy name is silently dropped**. | **SPIKE-3 (½ day left):** re-measure peak memory on x86 (and kokoro-onnx), and run listening tests of the Narrator presets. Narration runs one sentence per call and doesn't overlap LLM generation. | FR-32 target, default Narrators, the TTS container limit. |
| R-4 | Diarization time on CPU is unverified. The recommended model's weights sit behind an account-gated download, which strains offline install. | Not measured. | **SPIKE-4 (½ day):** time to diarize a 1-hour recording, and confirm that a pre-downloaded offline install works. | Whether FR-30 ships, and with which model. |
| R-5 | The stack is already over budget, and new features add memory, including the 7B and speech-to-text both running during a Live Session. | The spike's per-model peaks fit the 14.5 GB container sum (NFR-2) only with one resident LLM, models out of the web workers, and Kokoro per sentence. | **SPIKE-5 (2 days):** per-container resident memory for the whole stack in each NFR-2 case on x86. Build and verify the single profile within the 14.5 GB sum. | Final container limits. |
| R-6 | 7B throughput on CPU may make extraction prompts with a growing Entity list, Rolling Recap updates and NPC first tokens too slow. | Not measured (Ollama unavailable). | **SPIKE-6 (1 day):** prompt-processing and generation tokens per second for each prompt shape, with Entity lists of 50 and 300, plus the skipped structured-extraction test. | NFR-6 rows for F1, F4 and F6. Whether extraction needs a shortlist instead of the full Entity list. |
| R-7 | The TTS phonemizer, espeak-ng, is GPL-3.0+. | Confirmed: `pip install kokoro` bundles a prebuilt libespeak-ng, and disabling it drops proper nouns. Resolved by the edition split (FR-33, §12). | **LIC-1 (closed by owner decision):** the AGPL build isolates espeak-ng in the optional TTS container, and the commercial edition uses browser read-aloud. Open follow-up: a permissive engine or a non-GPL pronunciation path that passes the proper-noun test. | When the commercial edition gets local narration. |
| R-8 | A 7B model may produce unreliable structured output and Entity matches. | — | Covered by EV-1 early in Phase 1. | Whether to add an NER pre-pass or a smaller extraction model. |
| R-9 | Visibility filtering is easy to miss on a new route. | — | EV-4 derives its route list from the router and the proxy config. | — |
| R-10 | The recommended speech-to-text library may be lightly maintained. Large-Map preparation time and memory are unmeasured. | faster-whisper base beat today's openai-whisper base at the same accuracy (1.6–3.7× faster, 39–49% less memory). | Covered by SPIKE-2 (choose an alternative if needed) and SPIKE-5 (tile a 16,000 px Map). | Speech-to-text library choice, FR-52 limits. |

The remaining spike work totals about 5 days and runs in Phase 0.

## 9. Proposed release phases and cut line (not locked)

The order follows the dependencies. The owner can re-slice it.

- **Phase 0: Foundations and privacy.** FR-9(a) first, shippable on its own. Then FR-1 to FR-3, FR-4 and FR-5 (the Entity schema and the NPC and Quest migration, so FR-8 protects one Entity table rather than the legacy tables; owner decision, spine AD-19), FR-6 to FR-8 with FR-9(b) in the same release, and FR-10. Also the NFR-4 CI licence check and CI on `main`, the EV-4 harness over existing routes (extended by each later feature), the x86 re-runs of SPIKE-1 to SPIKE-3, SPIKE-4 to SPIKE-6, and LIC-1's follow-up. **Exit:** EV-4 green, the single profile meets NFR-2, spikes recorded and NFR-6 reset.
- **Phase 1: World Model plus independent quick wins.** F1 (FR-11 to FR-18, on the Phase 0 Entity table) with EV-1. In parallel, the features that don't need F1: F8 Chronicle (FR-45 to FR-48), F9 stats (FR-49 to FR-51) and F5 Narrated Recaps (FR-31 to FR-34). **Exit:** DS-1 and DS-5.
- **Phase 2: The dependents.** F2 Canon guard (FR-19 to FR-22) with EV-2, F3 Relationship web (FR-23 to FR-25), F7 Player Portal (FR-40 to FR-44), F6 Talk to an NPC (FR-35 to FR-39) with EV-3, F4 Live Session (FR-26 to FR-30) and F10 Map pins (FR-52 to FR-55). F4 and F10 can move earlier if capacity allows. **Exit:** DS-2, DS-3 and DS-4.

**Proposed capstone cut line.** `[ASSUMPTION]` The minimum demonstrable launch is Phase 0, Phase 1, F2, F3 and F7, which means DS-1, DS-2, DS-3 and DS-5. If time runs short, cut in this order (first cut first):

1. FR-30 speaker labels.
2. FR-55.
3. FR-39 Player NPC Conversations.
4. F10 Map pins.
5. FR-50 and FR-51 Achievements and streaks.
6. F4 Live Session, keeping today's batch recording.
7. F6 Talk to an NPC.

The privacy foundations (FR-7 to FR-9) and EV-4 are never cut.

## 10. Non-goals

- Virtual tabletop functions: tokens, combat, dice, line of sight.
- Required cloud services, hosted SaaS, or cross-device cloud sync.
- Native mobile apps. The portal is a responsive web app.
- Rules engines or game-system automation.
- AI-generated images or maps.
- Real-time collaborative co-editing of entries.
- A content marketplace.
- Voice cloning of real people for Narrators.
- AI that writes to Canon without GM approval, in any feature.
- Per-Campaign quotas or fairness guarantees on multi-Campaign servers (NFR-11).
- A rewrite of the existing architecture.

## 11. Proposed defaults for delegated open questions

The owner delegated these questions to the PRD and the architecture. The answers below are proposals.

- **Default TTS Narrators and disk budget.** `[ASSUMPTION]` Ship one local TTS model with five genre Narrator presets: fantasy, a warm, measured storyteller; sci-fi, a crisp, neutral announcer; horror, a low, slow voice; video game, an energetic voice; other, the fantasy preset. The presets may blend base voices. The disk budget for the TTS model and voices together is **≤ 500 MB**. English is the only narration language guaranteed in v1. The AGPL build ships these Narrators in the optional TTS container. The commercial edition has no local Narrators and uses browser read-aloud until a permissive engine passes the proper-noun test (FR-33).
- **Migrating existing NPC and Quest records.** `[ASSUMPTION]` Migrate as in FR-5:
  - NPC records map to Character Entities by role.
  - Records with the faction role become Faction Entities.
  - Quests become Quest Entities.
  - Notes become Secrets.
  - Migrated records start GM-only.
  - Old links redirect to the new Entities.
  - Name matches in Narratives become suggested Mentions.

  Global tags stay as they are. An optional one-time backfill (FR-18) then proposes Relationships and statuses from the historical journal through the normal Review Checklist.

## 12. Open questions

These need the owner:

No phase-blocking questions remain. The owner resolved the four earlier blockers on 2026-10-31 (`scope-input.md`, "Owner decisions — round 2"):

1. ~~espeak-ng in the commercial edition~~ **Resolved.** The AGPL build ships Kokoro with espeak-ng as an optional TTS container. The commercial edition uses browser read-aloud until a permissive engine passes the proper-noun test (FR-33, NFR-4).
2. ~~The Role of existing Members~~ **Resolved.** They migrate to Player, and the Owner promotes Co-GMs by hand (FR-7).
3. ~~Core licence wording~~ **Resolved.** AGPL-3.0, dual-licensed with a commercial licence (NFR-4).
4. ~~The 8 GB baseline~~ **Resolved.** The baseline is 16 GB with one profile, CPU-only supported and a GPU optional, within a 14.5 GB container-limit sum (NFR-2).

Deferred, non-blocking; revisit after Phase 0:

5. Final NFR-6 and §7 targets. Owner: the PRD update after the x86 spike re-runs (§8).
6. The capstone cut line (§9). Owner: confirm before epics are sequenced.
7. Whether Players need a paid or granted account on hosted deployments (FR-7 assumption). Revisit if hosted billing is turned on.

## 13. Assumptions index

- §2.3: the user journeys are composed from the brief's personas.
- FR-3: 95% schema-valid threshold.
- FR-5 and §11: the NPC and Quest migration mapping, with migrated records starting GM-only.
- FR-7: links default to Player, already-issued collaborate links grant Player, and Players skip the account gate for Party routes. (Existing Members becoming Player is an owner decision, not an assumption.)
- FR-14: duplicate-Entity rate ≤ 10%.
- FR-24: 300 nodes and 600 edges at ≥ 30 fps.
- FR-26: 10-minute audio backlog limit.
- FR-29: raw audio is deleted after transcription by default.
- FR-33 and §11: the default Narrators and the 500 MB disk budget.
- FR-39: Player NPC Conversations are off by default.
- FR-42: Player Journal entries are Private by default.
- FR-51: streaks are off by default, with a one-Session grace.
- FR-52: the Map upload limits.
- NFR-6: every latency target is provisional until the spikes.
- §7: every evaluation target is provisional until the baseline run.
- §9: the capstone cut line and cut order.
