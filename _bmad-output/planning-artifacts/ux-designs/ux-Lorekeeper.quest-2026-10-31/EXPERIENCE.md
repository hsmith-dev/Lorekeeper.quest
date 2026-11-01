---
name: Lorekeeper
status: final
created: 2026-10-31
updated: 2026-10-31
mode: headless-create
sources:
  - ../../prds/prd-Lorekeeper.quest-2026-10-31/prd.md
  - ../../prds/prd-Lorekeeper.quest-2026-10-31/addendum.md
  - ../../scope-input.md
  - ../../brownfield-context.md
design: ./DESIGN.md
---

# Lorekeeper — Experience Spine (living-world expansion, F1–F10)

## Foundation

Lorekeeper is a responsive web app (React 18, Vite, TypeScript, Tailwind 3, shadcn-style primitives in `components/ui`, lucide icons, react-query, PWA) served from the group's own host. **DESIGN.md is the visual identity reference.** This spine covers behaviour only.

- **Brownfield.** New pages follow the existing conventions: named exports behind the `lazy` adapter, `PageHeader`, theme tokens only, `md:`-first responsive classes, and react-query keys `[domain, campaignId]`. Detail views open in `SlideOver`. AI drafts go through the draft-then-commit contract of `NarrativeReviewPanel` (brownfield §5, §8).
- **Two audiences, one app.** The **Role** in the current **Campaign** decides what the shell shows. A GM (Owner or Co-GM) gets the full authoring app. A Player gets the **Player Portal** set. A read-only **Share Link** gets the Portal without "my character" or Player Journals (FR-40).
- **Glossary.** UI copy and this spine use the PRD §3 terms exactly (Visibility, Change Proposal, Review Checklist, Continuity Flag, Canon Note and the rest); they are not redefined here.
- **Out of scope here.** Transport, storage, models and queueing belong to architecture. This spine states only what the user sees, such as latency, progress and failure. Where the UI needs data, the need is phrased as a requirement on the UI (for example "the Job reports a stage and an ETA"), not as an API design.

## Information Architecture

### Shell

The NavBar keeps its shape: wordmark, **one grouped dropdown**, avatar. Two controls are added between the dropdown and the avatar:

1. **CampaignSwitcher.** The current Campaign's name with a RoleBadge, plus a menu listing every Campaign the user belongs to, each with its Role, and "Preview as Player" for GMs. The choice is remembered per device. Existing pages with their own campaign tab row keep it, but it defaults to the current Campaign. `[ASSUMPTION: global "current campaign" is new app state; brownfield has none. See Open Questions]`
2. **JobTrayButton.** Shows the count of running Jobs plus pending Review Checklists. It opens the Job tray (see Component Patterns).

### GM navigation (`NAV_GROUPS`)

| Group | Links (← = changed from today) | Notes |
|---|---|---|
| Chronicle | Journal · History · Timeline · **Live Session** ← *Record Session* · **Keepsakes** (new) · **Stats** ← *Analytics* | `/record` redirects to `/live?mode=record`. Keepsakes holds Previously-on recaps and Chronicle export, so the two "UJ-6" keepsakes share one page. |
| Campaign | **World** (new; absorbs *Characters* and *Quests*) · Character Sheets · Session Plans · Sources · Shorthand | `/characters` → `/world?type=character`, `/quests` → `/world?type=quest`. Old NPC and Quest detail links resolve to the migrated Entity (FR-5). |
| Collaborate | Sharing (now includes Roles and members) · Feedback | |
| Admin | Admin | Unchanged. |

The net link count is unchanged (13, plus Admin), so the ten features add no nav bloat. The Chronicler (`/chat`) is reached as today. NPC Conversations are a *mode* of the chat page, launched from an Entity, and have no nav item.

### World hub (`/world`)

| Tab | Route | Content |
|---|---|---|
| Entities | `/world?type=…` | Type chips: All · Characters · Locations · Factions · Items · Quests. A search field. A card grid with StatusBadge, VisibilityBadge (GM only) and Mention count. For GMs, a selection mode for bulk Visibility. |
| Web | `/world/web` | The relationship web (FR-24), with List view. |
| Maps | `/world/maps`, `/world/maps/:id` | Map list, then the map viewer. |
| Entity page | `/world/:type/:id` | The wiki page. The same content also opens as `EntityPanel` in a SlideOver from the graph, map, lookup, checklist and chat, with "Open full page". |

### Other new or changed surfaces

| Surface | Reached from | Purpose |
|---|---|---|
| Review Checklist (SlideOver, wide) | The post-save card on the journal; the Job tray; the "N to review" pill on Dashboard; `/reviews` | Decide Change Proposals for one Journal Entry (FR-15). |
| Reviews queue `/reviews` | Job tray "See all"; Dashboard | Every Journal Entry with pending proposals, oldest first. Backfill results land here (FR-18). |
| Entry detail (existing `/journal/:id`) | History, Timeline, citations | Gains a Mentions strip, ContinuityFlags, an Edit button (FR-6) and a VisibilityBadge. |
| Live Session `/live` | Chronicle › Live Session | Captions, Rolling Recap, Quick lookup; End → draft entry (FR-26 to FR-29). `?mode=record` keeps today's batch recorder. |
| Keepsakes `/keepsakes` | Chronicle › Keepsakes | Tabs: **Previously on…** (generate, edit, narrate, play) · **Chronicle** (export and past exports). |
| Stats `/stats` | Chronicle › Stats | The existing analytics plus Milestones and opt-in Achievements (FR-49 to FR-51). |
| NPC Conversation `/chat?npc=:id` | "Talk to {name}" on an NPC's page or panel | In-character chat. The sidebar groups NPC Conversations under their NPC (FR-35). |
| NPC Knowledge | The NPC page › Knowledge section; the chat header's KnowledgeScope chip | Grant or hide entries and fields (FR-36). |
| Sharing › Members | Collaborate › Sharing | Invite with Role, change Role, link a Player to a PC, link expiry (FR-7, FR-44). |
| Settings › Notifications & milestones | Avatar › Settings | Browser notifications, Streaks and Achievements toggles (FR-51). |

### Player navigation (Role = Player in the current Campaign)

| Link | Route | Notes |
|---|---|---|
| Portal | `/portal` (`/dashboard` redirects here for Players) | Home: latest Narrated Recap, My character, Recent story, World by type, Ask the Chronicler. |
| World | `/world` | Party Entities, Web and Maps only. Counts and search are Party-only (FR-25). |
| My Journal | `/portal/journal` | The Player's Player Journal (Private by default; "Share with party"). |
| Chronicler | `/chat` | Player-scoped. NPC Conversations appear only for NPCs the GM enabled (FR-39). |
| Recaps | `/keepsakes` | Party Narrated Recaps; Player-edition Chronicle export. |

The Player shell has no Job tray badge for GM Jobs, no Review Checklists, and none of Sources, Shorthand, Session Plans or Live Session. A Player who opens a GM URL sees the normal not-found page, identical to a missing record (FR-8).

**Surface closure.** Each of the ten features has a surface and a Key Flow: F1 → Review Checklist and Entity page (Flows 1, 8); F2 → ContinuityFlag (Flow 2); F3 → Web (Flow 9); F4 → Live Session (Flow 4); F5 → Keepsakes › Previously on (Flow 6); F6 → NPC Conversation (Flow 5); F7 → Portal and preview (Flows 3, 8); F8 → Keepsakes › Chronicle (Flow 6); F9 → Stats (Flow 6); F10 → Maps (Flow 7).

## Voice and Tone

Microcopy. Brand voice lives in DESIGN.md › Brand & Style. The model is the existing review panel ("Edit freely — nothing's saved yet"): plain, calm, a little warm, never cute. It is honest about what the machine did and how long it takes.

| Do | Don't |
|---|---|
| "7 changes to review from *The Bell Tower*." | "✨ AI magic found 7 updates!" |
| "Edit freely — nothing's applied yet." | "Are you sure? This cannot be undone!" (when it can) |
| "Reading this entry for world changes. Usually 1–3 min on this machine. You can keep working." | "Processing…" with no time or context |
| "Captions ≈ 18 s behind. That's normal on CPU." | Hiding the lag or showing a fake live cursor |
| "Canon guard is best-effort. A missing flag doesn't prove the entry is consistent." | "No contradictions found ✓" |
| "Mira is deceased since *The Bell Tower*." | "Error: entity state conflict" |
| "Not from this NPC's memories" | "I'm sorry, as an AI…" |
| "GM only. Players can't see this." | "Hidden" (hidden from whom?) |
| "The party reached its 10th Session." | "Don't break your streak!" / "You missed 2 weeks" |
| "The speech model isn't installed. An admin can add it in Admin › Models (~1.5 GB)." | "STT unavailable (503)" |
| Player-facing: "Your journal is private. Share it with the party when you like." | GM jargon (Shorthand, proposals, Canon Note) in the Portal |

Rules:

- Name Journal Entries by title in italics and Entities by name. Never show a raw ID.
- Every ETA is a range or "about", and comes from the Job.
- AI-made text is labelled with where it came from: "From the transcript, not your journal", "Drawn from 3 entries".
- Use sentence case for buttons. The heading face renders section labels in capitals through CSS, never by typing capitals.

## Component Patterns

Behavioural. Visual specs are in DESIGN.md › Components.

| Component | Use | Behavioural rules |
|---|---|---|
| **CampaignSwitcher** | NavBar | Lists Campaigns with Roles. Switching updates every Campaign-scoped query and the nav set. "Preview as Player" (GM only) enters preview. When the current Campaign is deleted or access is lost, it falls back to the first remaining Campaign and shows a toast. |
| **PreviewBanner** | Every screen during preview | Persists across navigation until "Exit preview". All write controls are disabled with the tooltip "Preview is read-only". Data comes from the Player read path (FR-41), never from client-side hiding. `Esc` doesn't exit; only the button does, so the mode can't be left by accident. |
| **VisibilityBadge** | Records, fields, proposals, pins, nodes (GM view) | For a GM it is a menu button: Party · GM-only (and Private where it applies). Changing it applies on save of the surrounding form, or immediately on list rows. Moving to Party asks inline: "Players will see this. Make visible?" Moving to GM-only needs no confirmation. Hidden from Players, except "Private" / "Shared" on their own journal. |
| **SecretField** | GM notes and any Secret | Shows the label "GM only". It is never rendered in preview or for Players. |
| **Field visibility hint** | Party text fields while focused (GM) | Helper text: "Visible to players". It appears only on focus, so it doesn't add clutter. |
| **JobTrayButton / Job tray** | NavBar | Opens a popover listing, newest first, the running and queued Jobs and those finished in the last 24 h, plus pending Review Checklists. Each row has a stage, progress, ETA and an action: View result, Retry (failed), Download (exports), Cancel (queued only). The count covers running Jobs plus pending reviews. Status updates arrive with no reload, within 5 s (FR-2). |
| **Job completion notice** | Global | On completion, a Toast with an action ("7 changes to review · Review"). The document title gets a "(1)" prefix while unseen results exist. With opt-in browser notifications, a system notification appears only when the tab is hidden. Failures toast once with "Details". |
| **Post-save card** | Journal composer and Entry detail | After a GM saves, it shows the stages: "Reading for world changes" and "Checking continuity", each with its own progress and ETA. The save itself is already done and says so ("Saved."). When the Jobs finish, the card becomes "7 changes to review · 1 continuity flag" with a primary "Review" button. It never blocks writing the next entry (NFR-9). |
| **ReviewChecklist** (`EntityDiffReviewPanel`) | Wide SlideOver | Detailed in "Review Checklist behaviour" below. |
| **ProposalItem** | Inside the checklist | Detailed below. |
| **MatchPicker** | Uncertain Entity match | Shown expanded by default. Options: up to three candidates plus "New entity". Choosing a candidate re-targets the item ("same as Aldric") and adds the surface form as an alias on Apply (FR-14). |
| **EntityPanel / EntityPage** | World, graph, map, lookup, chat | Same content in two containers. Sections: Overview (description; GM notes as a SecretField), Relationships, Mentions, On maps, History, and for NPCs, Knowledge plus "Talk to {name}". The header overflow menu has Edit · Merge… · Set visibility · Re-run extraction for mentions · Delete. Editing is inline per section with Save and Cancel, as in NpcDetailPanel. A Player sees the same layout with GM-only content removed and no empty gaps where it was. |
| **StatusBadge** | Entities | GMs can click it to change the status, which records a history row with "Manual edit" as the source. The badge shows a "since {entry}" citation when a source exists. |
| **HistoryList** | Entity page | Each row links to its source entry. "Revert" asks inline ("Restore *alive*?") and records the revert itself (FR-16). Rows from a deleted source show "source deleted" with a Review action (FR-6). |
| **MentionList** | Entity page, entry detail | Newest first. Suggested Mentions (from migration or matching) carry Confirm and Remove buttons. Clicking a quote opens the entry scrolled to and highlighting the quote. |
| **Merge dialog** | Entity overflow menu | A SlideOver. Pick the survivor and preview the combined aliases, Mention count and Relationships. If a Party Entity is merged with a GM-only one, a warning explains that merged fields keep the more restrictive Visibility (FR-17). |
| **ContinuityFlag** | Entry detail (above the Narrative), the checklist's Continuity section, Entity page History (when resolved) | Actions: **Dismiss** (menu: False alarm · Flashback or in-fiction framing · Other, with optional text) and **Override with Canon Note**. A dismissed flag collapses to a one-line "Dismissed · Flashback" with Undo for 10 s. While the check is still running, a small chip "Checking continuity…" sits by the entry title, and a failed check shows "Canon guard couldn't check this entry · Retry". |
| **CanonNoteForm** | Inside the flag | The reason is required, and Save stays disabled until it has text. "Also propose: {change}" is checked by default. On save, the flag resolves into a Canon Note, and the offered change appears as a new Change Proposal in that entry's checklist, marked "From Canon Note". |
| **GraphCanvas / GraphToolbar / GraphListView** | World › Web | Detailed in "Relationship web behaviour" below. |
| **MapViewer / MapPin / PinEditor / PlacementBar / PinList** | World › Maps | Detailed in "Map behaviour" below. |
| **LiveStatusBar, LagMeter, CaptionChunk, CaptionPending, BacklogBanner, RollingRecapCard, QuickLookup** | Live Session | Detailed in "Live Session behaviour" below. |
| **RecapPlayer** | Keepsakes, Portal home, Table play | Play, pause, seek, speed, download. It highlights the sentence being spoken and keeps it in view unless the user has scrolled. "Table play" opens a full-screen view with `{typography.recap-table}` text and big controls, and **Space** toggles play. When the Narrator is unavailable, it falls back to browser read-aloud (`useNarration`) and says "Narrator unavailable — using your browser's voice" (FR-33). |
| **NpcChatHeader / KnowledgeScope chip** | NPC Conversation | The chip opens the KnowledgeEditor in a SlideOver (GM). A deceased or missing NPC shows a notice banner above the first message: "Veyra is missing since *Ashfall Road*. You can still talk to her." It has no blocking confirmation (FR-35). |
| **NPC reply** | NPC Conversation | Streams. Before the first token, a "Veyra is thinking…" row shows elapsed seconds after 5 s ("12 s — slower on CPU"). Under each reply: "Drawn from 3 entries" (a disclosure that reuses the existing sources list) or the NotFromMemoriesLabel. The per-message menu has "Copy to a journal draft" (FR-38). |
| **KnowledgeEditor** | NPC page, chat chip | Rows: the entries with a confirmed Mention (default "Knows"), plus a search to add other entries or fields. A three-state control per row: Knows (from Mention) · Granted · Hidden. A Secret can be granted only explicitly. "Applies from the next reply." Suggested Mentions are never listed as knowledge (FR-36). |
| **Player NPC toggle** | NPC page (GM) | "Players can talk to {name}", off by default. When on, the Player sees "Talk to {name}" on the Portal Entity page (FR-39). |
| **PlayerJournalComposer** | Portal › My Journal | A textarea with a title, and a visibility control: Private (default) or "Share with party". No AI draft step. Saving never triggers extraction (FR-42). |
| **ChronicleExportPanel** | Keepsakes › Chronicle | Detailed in "Chronicle export behaviour" below. |
| **MilestoneCard / AchievementBadge** | Stats, Dashboard, Portal | A new Milestone shows once as a card on Dashboard or Portal and can be dismissed. It is also listed permanently on Stats. Achievements show only to users who opted in. |
| **ModelMissingNotice** | Inline, on the surface of the affected feature | Names the missing model and the feature it affects. Admins get a link to Admin › Models with the size. Others get "Ask your admin". A feature whose model is optional (speaker labels) is hidden instead (FR-30). |
| **Toast** | Global | Up to 3 stacked, auto-dismissing after 6 s, except those with Undo (10 s) and failures (persist until dismissed). Toasts are announced politely. |
| **EmptyState** | Every list | One sentence about what will appear here and how, plus one primary action. |
| **NodeLegend** | Web | Collapsed by default after the first visit (remembered). Toggle with its button; it never covers the focused node. |
| **SegmentedControl / Tabs / Combobox** | New primitives in `components/ui` | SegmentedControl and Tabs follow the WAI-ARIA tabs/radio patterns (arrow keys move, Enter or Space selects). Tabs that map to routes (World, Keepsakes) update the URL. Combobox filters as the user types, opens on ArrowDown, and offers a trailing "Create…" option only where creation is allowed. |
| **Reviews queue row** | `/reviews` | One row per Journal Entry with pending proposals: title, date, "5 pending · 1 flag", and an Open button that opens that entry's checklist. |

### Review Checklist behaviour (FR-15, FR-14, FR-20, FR-22, FR-8, FR-55)

1. **Open.** It opens in a wide SlideOver over the entry the GM just saved. The title is "Review Checklist · *The Bell Tower*", with the subtitle "Edit freely — nothing's applied yet."
2. **Order.** First a **Continuity** section, if any flags exist. Then **New**, **Changed** and **Quest progress**, each headed with a count and collapsible. Within a group, **needs-attention items come first**: contradicts Canon, stale, uncertain match, or a GM-only default on a Party-looking fact. The rest follow in the order they appear in the entry.
3. **Each item** shows the change, its quote and source, its default Visibility (editable), and Approve, Reject and Edit. Edit opens the fields inline (name, status, field value, relationship type, quest step). Saving the edit puts the item in the *edited* state. Mentions that support an item appear as quotes on that item, not as separate rows.
4. **Staging.** Decisions are local until **Apply to world**. The sticky footer reads "12 approved · 2 rejected · 4 pending" with the buttons **Approve remaining (4)** and **Apply to world**. Approve remaining approves every pending or edited item and leaves rejected ones alone (FR-15). It never changes an item's Visibility (FR-8).
5. **Group approve.** Each group header has "Approve group".
6. **Partial apply.** Applying leaves still-pending items pending. They stay in the Reviews queue and the tray count.
7. **Handling 20+ proposals.**
   - A filter row offers All · Needs attention (n) · Pending (n).
   - Groups with more than 8 items collapse to their first 5 plus "Show 12 more".
   - Keyboard triage: `j`/`k` move, `a` approves, `r` rejects, `e` edits, `u` undoes the last decision, `Shift+A` approves the remaining items in the focused group.
   - A progress line under the title reads "14 of 23 decided".
   - A backfill (FR-18) produces one checklist *per entry* in the Reviews queue, never one 200-item list.
8. **At Apply.** Items are re-checked against current Canon (FR-15). Items that went stale return with a "Stale: Canon changed since this was proposed" chip and show the new current value. Items redirected after a merge show "Now applies to *Aldric* (merged)". Everything else applies.
9. **After Apply.** A toast reads "Applied 12 changes to the world · Undo", where Undo reverts the batch for 10 s. Pages showing those Entities update without a refresh.
10. **New Location with Maps present.** When a new Location is approved and the Campaign has a Map, a follow-up prompt appears in the footer area after Apply: "Place *Sunken Archive* on a map?" with the choices Choose map and Not now. Not now creates nothing (FR-55).
11. **Closing with staged decisions.** Closing keeps the decisions as a local draft for that entry and says so: "Your decisions are kept on this device until you apply them."
12. **Marked proposals** (FR-22) can still be approved. Approving one opens the CanonNoteForm inline ("Record why this is right?"). The note is optional for proposals; only a flag override requires a reason.

### Relationship web behaviour (FR-23 to FR-25)

- **First render.** The layout is computed before it is shown. A skeleton ("Arranging 214 entities…") holds the space, then the settled graph appears. There is no animated force simulation on screen. Positions persist per Campaign per device, so the web doesn't reshuffle between visits.
- **Pointer.** Drag pans, the wheel or a pinch zooms, and dragging a node moves it, which pins it. Hovering or focusing a node highlights its neighbours, dims the rest, and shows edge labels. Clicking opens the EntityPanel in a SlideOver, and the graph stays mounted behind it.
- **Search** (`/`) centres and focuses the matching node. Filters (Entity Type, Relationship type, Faction) hide what doesn't match and say so: "Showing 48 of 214 · Clear filters".
- **Editing (GM).** From a node's panel, "Add relationship" opens a form (type from the Campaign's list, target Combobox, direction, note, Visibility). Ending a Relationship asks for an optional note and draws the edge dashed with "formerly". Approved Relationships from checklists appear live.
- **List view** is a peer, not a fallback. The toggle is remembered. It is a sortable table of the same filtered set, and rows expand to their edges, which open panels. It is the default under 640 px and when the graph has more than 1,000 nodes.
- **Player view** uses the same interactions on Party data only. No placeholder hints at a hidden node: no "+2 hidden", no gaps in counts.

### Map behaviour (FR-52 to FR-55)

- **Map list.** A card grid with thumbnails. A GM sees an "Upload map" card (PNG, JPEG or WebP, up to 50 MB and 16,000 px). A large Map shows "Preparing map…" as a Job, and the card becomes usable when it finishes.
- **Viewing.** Drag pans, the wheel or a pinch zooms, and Fit is available. Pins keep their screen size across zoom levels. Clicking a Pin opens a popover EntityCard (its Location) with its linked entries, and "Open" leads to the panel.
- **Adding a pin (GM).** "Add pin" enters placement mode. The PlacementBar appears and the cursor becomes a crosshair; one click places the Pin and opens the PinEditor. A Pin can't be saved without a label. The Location is optional, with "Create Location…" inline (which creates a GM-only Entity draft that the GM names). The Pin's Visibility defaults to its Location's, or GM-only when it has no Location.
- **Moving a pin.** Drag a selected Pin, or use "Move" in the PinEditor and then arrow keys (Shift for ×10) and Enter. Save confirms the new position, and Esc restores the old one.
- **Replacing an image.** If the replacement has the same aspect ratio, pins stay put. If the ratio differs, a warning appears and a "Review pin positions" mode lists every Pin to confirm.
- **PinList** shows every Pin on the current Map, sorted by label, with a filter. Selecting a row centres and selects that Pin.
- **From a Location's page.** "On maps" lists its Pins. "Place on a map" chooses a Map and enters placement mode for that Location (FR-55).

### Live Session behaviour (FR-26 to FR-30)

- **Before start.** The page checks, in this order, that the speech model is installed, that the page is on HTTPS (needed for the microphone), and that microphone permission is granted. Each failure gets its own state (State Patterns). A "Record only" link keeps today's batch recorder.
- **Start.** A large primary "Start Live Session" button, plus the Campaign and an optional Session date. Once it starts, the screen keeps itself awake and the LiveStatusBar is pinned to the top.
- **Captions are honest.**
  - The newest chunk is a **CaptionPending** row that shows the time range it covers ("Transcribing 0:42–1:02…").
  - Text replaces that row when it arrives. Earlier rows don't move.
  - The LagMeter shows the measured lag ("≈ 18 s behind") and turns warning when lag exceeds the chunk window.
  - Captions auto-scroll only while the GM is at the bottom. Scrolling up shows a "Jump to live" button.
- **Backlog.** If processing falls behind, the BacklogBanner reads "Falling behind — 3 min of audio queued. Nothing is lost up to 10 min." Past 10 min, the skipped range is shown in-line as a row: "Skipped 41:10–41:40 (backlog over 10 min)" (FR-26).
- **Rolling Recap.** It refreshes about every 60 s. The card shows "Updated 40 s ago · covers to 1:02:10" and a small "Updating…" chip during a refresh. The old text stays readable until the new text replaces it, and text that changed is briefly marked with a left rule (no animation under reduced motion). It is always labelled "From the transcript, not your journal" (FR-27).
- **Quick lookup.** Tapping an underlined name in a caption opens the EntityCard in the right rail (tablet or desktop) or a bottom sheet (phone). A skeleton appears at once and the card arrives within 2 s. Typing in QuickLookup matches names and aliases as the GM types. A question ("who was the dwarf smith?") goes to the Chronicler, and the cited answer appears in the same card, with "not from your journal" when nothing passes the gate (FR-28). Without F1, lookup searches the legacy NPC records and says "Searching NPC records".
- **Pause** stops capture, shows "Paused" in the status bar, and keeps everything. **Resume** continues the same session.
- **Reconnect or refresh.** The page resumes the same Live Session with every caption already transcribed. A toast reads "Reconnected — nothing lost" (FR-26).
- **End.** Confirm inline ("End session? Captions stop."). Then the full transcript is shown with the summarize step and the existing draft review (`NarrativeReviewPanel`). There are two choices: "Keep raw audio" (off by default) and, when the diarization model is installed, "Label speakers afterwards (Job)" (FR-29, FR-30).
- **Table view** is a toggle in the status bar (`t`). It hides the nav and the rails and shows the latest two captions in `{typography.caption-table}` with the Rolling Recap below in `{typography.recap-table}`, plus Lookup and Exit buttons at `{spacing.tap-target-table}`. It is meant to be propped up facing the players, or for a GM glancing from a standing position.

### Chronicle export behaviour (FR-45 to FR-48)

- **Edition** is a segmented control: Player edition (default) · GM edition (GM only, with a gm badge). The Player edition explains: "Party content only. Safe to share with your group."
- **Formats:** PDF and EPUB checkboxes, both on by default.
- **Include:**
  - Entity appendix (on when F1 data exists);
  - Map images;
  - shared Player Journal entries (in their Sessions' chapters);
  - for the GM edition only, Shorthand and Secrets (both off, each with a gm badge).
- **Summary line:** "38 Sessions · 112 entries · 214 entities · about 180 pages", with a cover preview thumbnail.
- **Export** starts a Job. The panel shows its progress, and the user can leave because the Job tray tracks it. When it's done, Download PDF and Download EPUB appear.
- **Past exports** are listed with date, edition and formats. An export made before a Visibility change shows "Out of date — visibility changed since" and offers Re-export (FR-41).

## State Patterns

### Global states

| State | Treatment |
|---|---|
| **Cold load** | Skeletons in the shape of the content, using the existing `animate-pulse` blocks (static under reduced motion). Never a full-page spinner. |
| **Long Job: queued** | "Queued · 1 ahead" with an hourglass icon, and an indeterminate track with no fake percentage. |
| **Long Job: running** | Stage text ("Matching entities · 2 of 3") plus a determinate bar when the Job reports progress, and an ETA range ("about 1–2 min left"). Progress lives in the Job tray and the post-save card, so leaving the page doesn't lose it. |
| **Long Job: done** | Toast with an action, a title-count prefix, and an optional system notification when the tab is hidden. |
| **Long Job: failed** | A danger icon and a readable reason. Retry is available, except for configuration failures ("No AI model is configured. Settings › AI"), which aren't retried (FR-1). The source Journal Entry is always shown as saved. |
| **AI output unusable** (FR-3) | "The model's answer couldn't be read, so nothing was proposed. Retry, or re-run later." |
| **Model not installed** | A ModelMissingNotice inline on the affected surface only: LLM (all AI), speech (Live Session), TTS (Narration falls back to the browser voice), NLI (Canon guard: "Canon guard is off: the continuity model isn't installed"). Diarization hides the option. The existing global ModelReadyBanner remains for the main LLM. |
| **Model server down** | As above, with "isn't reachable". Pages stay browsable, and only AI actions are disabled with a reason. |
| **Offline (client)** | Existing offline queue behaviour for journal notes. New surfaces are read-only offline, with "You're offline — changes are paused". The Live Session pauses capture and keeps the buffered audio locally until the connection returns `[ASSUMPTION: client buffering acceptable; architecture decides]`. |
| **Not found / no access** | One page for both: "This page doesn't exist or isn't shared with you." It is identical for Players hitting GM content (FR-8). |
| **Error (request)** | Inline `{colors.danger}` line via `apiErrorMessage`, with a Retry action. Form input is kept. |
| **Preview as Player** | PreviewBanner on every screen, and writes disabled. |

### Per surface

| Surface | Empty | Loading or long | Error or degraded |
|---|---|---|---|
| World › Entities | "No entities yet. They appear as you save journal entries and approve the changes." Action: "Add an entity". Players see: "Nothing has been shared with the party yet." | Card skeletons | — |
| World (just upgraded, FR-5) | A callout: "142 entities came over from your old NPC and Quest lists. They're GM-only until you publish them." Action: "Review and publish" (bulk Visibility) | — | — |
| Entity page | Sections with no data are hidden for Players and show a one-line hint for GMs ("No relationships yet"). | Skeleton | Deleted while open: "This entity was merged into *Aldric*" with a link, or "deleted". |
| Review Checklist | "Nothing to change in the world from this entry." Closes itself after 4 s if the GM opened it from a toast. | Post-save card stages; the checklist button is disabled until results are ready. | Job failed: reason + Retry; the entry stays saved. |
| Reviews queue | "All caught up. New entries will show here after you save them." | Rows skeleton | — |
| ContinuityFlag | (none = no flag, plus the disclaimer in the entry's footer meta) | "Checking continuity…" chip | "Canon guard couldn't check this entry · Retry" |
| Web | "Relationships appear as you approve them, or add one from any entity." | "Arranging N entities…" | Over 1,000 nodes, or WebGL unavailable: opens in List view with "Showing list view: the web is too large for this device." |
| Maps | "Upload a map image to start placing pins." (Player: "No maps shared yet.") | "Preparing map… about 1 min" on the card | Wrong type or too large: the reason names the limit ("Maps can be up to 50 MB and 16,000 px on the longest side."). |
| Live Session | Pre-start panel | First caption pending: "Listening. First captions in about 20–30 s." | Mic denied: "Lorekeeper can't hear the table. Allow microphone access in your browser's site settings." HTTP: "Live Session needs a secure (HTTPS) connection to use the microphone." Speech model missing: notice + "Record only" link. |
| Rolling Recap | "The first recap arrives about a minute after captions start." | "Updating…" chip | "Recap paused: the AI model is busy or unavailable. Captions continue." |
| Keepsakes › Previously on | "Pick the Sessions to recap." | Generate is streamed into the review panel; Narrate is a Job ("Narrating… about 1 min") | TTS down: text + browser read-aloud fallback with the note |
| Keepsakes › Chronicle | "No exports yet." | Job | Failure: reason + Retry |
| NPC Conversation | A greeting suggestion: "Ask Veyra what she saw at the Bell Tower." | "Veyra is thinking… 12 s" | No knowledge yet: "Veyra has no memories yet. Confirm Mentions or grant entries in Knowledge." |
| Stats | Before any Sessions: "Stats start after your first Session." | Tile skeletons | — |
| Stats › Achievements | Off (default): "Achievements are off. Turn them on for yourself." | — | — |
| Portal home | New Player with no PC linked: "Your GM hasn't linked your character yet." Story still shows. | Skeleton | — |
| My Journal | "Write about the last Session in your character's voice. It's private until you share it." | — | — |

## Interaction Primitives

**Keyboard (desktop).** Shortcuts never fire inside text inputs. Pressing `?` shows the list.

| Key | Scope | Action |
|---|---|---|
| `/` | World, Web, Maps, Live Session | Focus search or lookup |
| `j` / `k`, `a` / `r` / `e` / `u`, `Shift+A` | Review Checklist | Move, approve, reject, edit, undo, approve remaining in group |
| `Ctrl/⌘ + Enter` | Review Checklist | Apply to world |
| `Esc` | Global | Close the top SlideOver, popover or placement mode. Never exits preview. |
| Arrow keys | Graph (focused node) | Move focus to the nearest neighbour in that direction |
| `Tab` / `Shift+Tab` | Graph | Cycle the focused node's edges and neighbours |
| `Enter` | Graph node, Map pin | Open the panel or popover |
| `+` / `-` / `0` | Graph, Map | Zoom in, zoom out, fit |
| Arrow keys (+Shift) | Map (no pin selected) | Pan; with a selected pin in Move mode, nudge it |
| `p` | Map (GM) | Enter placement mode at a centred crosshair; arrows move it; Enter drops |
| `t` | Live Session | Toggle Table view |
| `Space` | Table play, Live Session (with nothing else focused) | Play/pause the recap; pause/resume capture |

**Pointer and touch.**
- Tapping a row opens it, matching the existing card links.
- Long-press on a graph node or pin (touch) opens its actions menu, equivalent to right-click.
- Bottom sheets on phones close on a swipe down or the close button.
- Drag is used only where it is spatial (graph nodes, map pins), and each drag has a keyboard or button alternative.
- No hover-only affordances below `md`.

**Confirmation discipline.**
- Destructive actions confirm inline (a "Delete *Mira*? Mentions are kept as text." row with Delete and Cancel), not in a modal stack.
- Reversible actions (approve, dismiss, apply) don't confirm; they offer Undo.
- Only one SlideOver at a time. Opening an Entity from inside the checklist pushes a "← Back to checklist" header inside the same SlideOver.

**Banned:** infinite scroll on Mentions and History (paginate in 20s); auto-applying anything to Canon; animated layout physics on screen; modal-over-modal; colour-only status; countdown timers.

## Accessibility Floor

Behavioural. Visual contrast lives in DESIGN.md (all new tokens are AA on every built-in theme).

- **WCAG 2.2 AA** on every new page (NFR-10). Every route change announces the page title, for example "World, Entities, 214 entities".
- **Review Checklist** is fully keyboard operable (NFR-10):
  - each item is a `listitem` with a label summarising the change ("Mira, status, alive to deceased, pending, GM only");
  - state changes are announced through `aria-live="polite"` ("Approved. 13 of 23 decided.");
  - focus stays on the item after a decision, and `j` moves on.
- **Graph.**
  - The canvas is a focusable `application` region with an instruction ("Arrow keys move between connected entities. Enter opens. L for list view.").
  - The focused node is announced with name, type, status and its number of Relationships.
  - GraphListView is the complete equivalent (FR-24) and is linked as the first focusable element in the region.
- **Map.**
  - Pins are focusable buttons in PinList order with labels ("Sunken Archive, Location pin, Party").
  - Placement and moving work by keyboard (Interaction Primitives).
  - PinList is the complete equivalent.
- **Live captions.** The caption list is an `aria-live="polite"` log announcing only new chunks. The LagMeter is not live, so it doesn't chatter, but it is readable on focus. Backlog and skip notices are `assertive` once.
- **Narrated Recaps** always show their text (NFR-10). Speed control is provided. Audio never autoplays except on an explicit Table play press.
- **Reduced motion** (`prefers-reduced-motion: reduce`):
  - SlideOver and bottom sheets appear without sliding;
  - the graph never animates layout or zoom-to-node (it jumps);
  - captions jump-scroll;
  - the REC dot and Job ring are static, the word "REC" carries the state, and skeletons don't pulse;
  - there is no foil shimmer or Milestone entrance;
  - changed recap text is marked by a rule only.

  The app has no reduced-motion handling today, so this is new global CSS plus checks in these components.
- **Visibility is never colour-only.** Badges carry the words "GM only", "Private" and "Party". Screen readers hear "GM only" before the field label of a Secret field.
- **Focus.**
  - Visible focus uses the theme `ring` token (`{components.graph-node.focus-ring}` on graph nodes) on every new control.
  - SlideOver traps focus and returns it to the opener on close, which today's SlideOver lacks and must be added.
  - Popovers return focus on close.
- **Targets** are at least `{spacing.tap-target}`, and `{spacing.tap-target-table}` in Live Session and Table view.
- **Language.** "Not from this NPC's memories" and "not from your journal" are text, not icons, so screen readers hear them.

## Responsive & Platform

| Breakpoint | Behaviour |
|---|---|
| `< sm` (375–639 px), phones | Single column. SlideOvers go full screen. Review Checklist actions are icons with labels in an overflow menu, and the footer stays sticky. Web defaults to List view. Maps use a full-screen viewer with PinList as a bottom sheet. Live Session uses bottom tabs (Captions · Lookup · Recap). Portal is fully usable at 375 px with no horizontal scroll (FR-40). |
| `sm`–`md` (640–1023 px), tablet portrait | Like phones, with two-column entity grids. Live Session keeps captions full width and lookup as a bottom sheet at half height. |
| `md`/`lg` landscape tablet (≥ 1024 px) | **The table target.** Live Session is two columns (captions plus a 360px rail). Graph and Map get side panels. Touch targets stay at 44–56px even with a pointer present. |
| `≥ lg` desktop | Page shell `max-w-5xl` for most pages. Live Session, Web and Maps go full width. |

**At the table:** the GM's device is most likely a tablet or laptop lying flat or propped up, glanced at between turns. Glanceability rules:

- Status (REC, lag, recap age) is in the top 56px and never scrolls away.
- The newest caption is always at the same place.
- Lookup is one tap from any name.
- Table view exists for reading from about 1.5–2 m.

The screen stays awake during a Live Session where the browser supports it; if it doesn't, the page says "Keep this screen on — your browser may sleep it."

**Players** most likely use phones between Sessions (UJ-3). The existing PWA lets them add the Portal to the home screen. Portal pages are expected to load warm within 2 s (NFR-6).

## Spoiler Safety (product-specific)

The rule: **what players can see is always obvious to the GM, and never inferable by the player.**

1. **Badges everywhere for GMs.** Every record, Secret field, proposal, Pin and graph node carries a VisibilityBadge in GM views. Party is quiet (neutral outline); GM-only and Private are tinted with a lock or person icon.
2. **Defaults follow evidence** (FR-8) and are shown, not hidden. Proposals sourced only from Shorthand arrive marked GM-only with a chip, "From your Shorthand", so the GM sees why.
3. **Publishing is a deliberate act.** Moving anything to Party confirms inline, and bulk changes say how many records they change ("Make 24 entities visible to players?").
4. **Preview as Player** renders through the real Player read path. It is reachable from the CampaignSwitcher and from an Entity's overflow menu ("Preview this page as a Player"), which opens that same page in preview.
5. **Derived content inherits.** Recaps, exports and audio show the most restrictive Visibility of their sources. A recap that includes GM-only content shows a gm badge and "Only GMs can play this recap."
6. **Player surfaces never show absences.** No "hidden" placeholders, no counts that differ from what is listed, and identical not-found pages.
7. **Role change notice.** When the Owner changes a Member from Co-GM to Player, the Owner is told "Their NPC Conversations and chat history in this Campaign will be archived." (FR-9).

## Inspiration & Anti-patterns

`[ASSUMPTION: references chosen by this headless run, not supplied by the owner]`

- **Lifted from code review (GitHub PR review):** decide per item, then submit once. This is the Review Checklist's stage-then-Apply model, plus "viewed" progress ("14 of 23 decided").
- **Lifted from note-graph tools (Obsidian-style graph):** neighbourhood highlight on hover or focus and a settled, persistent layout. Rejected from them: the perpetual jiggling simulation, and the graph as the *only* way in.
- **Lifted from live-caption apps:** a stable newest-line position and "jump to live". Changed: Lorekeeper shows its lag and pending chunks openly instead of faking a streaming cursor, because CPU chunking is 10–30 s (owner decision).
- **Lifted from the marketing site:** the Cinzel wordmark and the gold foil as the one celebratory flourish.
- **Rejected — streak guilt (habit apps):** no "don't lose your streak", no flames that go out, no reminder nags, no countdowns (FR-50, SM-C4). Grace is automatic and silent.
- **Rejected — wiki-as-forms (heavy worldbuilding tools):** no empty 30-field templates. Entity pages show only sections with content, and the World is filled by writing the journal.
- **Rejected — AI confidence theatre:** no "98% confident" percentages on proposals. Attention reasons are stated in words ("Possible duplicate of Aldric").
- **Rejected — chat-bot NPCs that never say no:** an NPC refusal is a feature and is labelled, not hidden.

## Key Flows

Protagonists are taken verbatim from PRD §2.3 (Dana, GM of a two-year fantasy Campaign for five players; Sam, a Player whose PC is Kael).

### Flow 1 — Dana updates the world by writing her session notes (UJ-1, DS-1)

1. Friday, 23:10, after the Session. Dana types her Shorthand in the Journal, reviews the Narrative in the existing review panel and saves *The Bell Tower*.
2. The post-save card says "Saved." and then shows two stages, "Reading for world changes · about 1–3 min on this machine" and "Checking continuity". She starts tidying her Session Plan.
3. Two minutes later a toast appears: "7 changes to review from *The Bell Tower* · Review". The tray badge shows 1.
4. The Review Checklist opens over the entry. **New:** "Location · Sunken Archive" (Party, quoted) and "Character · Brother Aldric" flagged "Possible duplicate". **Changed:** "Mira · status · ~~alive~~ → **deceased**". **Quest progress:** "Find the Dawnbreaker · step 2 done".
5. Brother Aldric is first in New. The MatchPicker lists "Aldric (Character, 6 Mentions)". She picks it and the item becomes "Add alias *Brother Aldric* to Aldric".
6. She presses `r` on a false-positive "Item · the bell" and `e` on the Dawnbreaker item to fix the step wording.
7. She presses **Approve remaining (4)**, then **Apply to world**.
8. **Climax:** the toast reads "Applied 6 changes to the world · Undo". She opens Mira from the checklist's toast link. The page shows **Deceased · since *The Bell Tower*** with the quote in her History, and in the Web, Mira's node is now dimmed with a dashed ring and a skull glyph. The world changed because she wrote her notes. Then: "Place *Sunken Archive* on a map?" She chooses "Not now."

Variant with 20+ proposals: a first entry after the FR-5 upgrade yields 23 items. Dana filters to "Needs attention (5)", resolves those, collapses the rest by group, and uses Shift+A per group, finishing in about 3 minutes (SM-6).

Failure: the extraction Job fails ("The model's answer couldn't be read"). The post-save card shows the reason and Retry, and the entry stays saved. If she closes the checklist mid-review, her staged decisions are kept on the device and the tray still counts the review.

### Flow 2 — Dana is warned before a dead NPC reappears (UJ-2, DS-2)

1. Three weeks later Dana saves an entry containing "Mira greets the party at the gate."
2. The save completes at once. The entry header shows the "Checking continuity…" chip.
3. A ContinuityFlag appears above the Narrative: "Continuity flag · Mira". On the left, *This entry*: "Mira greets the party at the gate." On the right, *Canon (The Bell Tower, 12 Mar)*: "Mira fell from the tower and did not rise." The footer reads "Canon guard is best-effort…".
4. The return is deliberate. She chooses **Override with Canon Note** and types "Resurrected by the Lantern cult". "Also propose: Mira · deceased → alive" is already ticked.
5. She saves. The flag resolves into a Canon Note block ("Retcon · Resurrected by the Lantern cult"), and the checklist for this entry gains "Mira · status · deceased → alive (From Canon Note)". She approves it and applies.
6. **Climax:** she re-saves the entry after a small edit. Canon guard runs and *no flag returns*. Mira's History shows the death, the Canon Note and the return, each cited. The record now explains itself.

Failure: if the flag was a flashback, she chooses Dismiss › "Flashback or in-fiction framing". If the check itself fails, the chip reads "Canon guard couldn't check this entry · Retry" and nothing blocks her.

### Flow 3 — Sam catches up between Sessions without spoilers (UJ-3, DS-3)

1. Tuesday lunch. Sam opens the Portal on his phone, added to his home screen. The CampaignSwitcher shows "Ashes of Karak · Player".
2. The top of Portal home is the latest "Previously on…" card. He taps play, and the text highlights sentence by sentence as the Narrator reads.
3. He taps **My character · Kael**: Kael's story so far (Party Mentions, newest first) and his Player Journal.
4. He writes a journal entry in Kael's voice. It shows "Private" and he leaves it that way.
5. In World he browses NPCs and opens Karak Dun's Map and its Party Pins. He asks the Chronicler "who hired us in Karak Dun?" and gets a cited answer.
6. **Climax:** he asks "is anyone in the party a traitor?" The answer is labelled "not from your journal" and nothing in the reply, the World counts, the graph or the search hints at the traitor Dana marked GM-only. For Sam the World is simply complete.

Failure: no PC linked yet. My character reads "Your GM hasn't linked your character yet." and everything else works.

### Flow 4 — Dana answers "who was that?" during play (UJ-4, DS-4)

1. Saturday, 19:30. Dana props her tablet in landscape and opens Live Session. The pre-checks pass and she taps **Start Live Session**. The screen stays awake.
2. The status bar shows REC, 00:00:12 and "Listening. First captions in about 20–30 s." A pending row reads "Transcribing 0:00–0:20…".
3. Captions arrive chunk by chunk. The LagMeter settles at "≈ 18 s behind". After a minute the Rolling Recap card fills in ("Updated 10 s ago · covers to 1:02").
4. A player asks who the dwarf smith was. In the previous chunk "Borin" is underlined.
5. **Climax:** Dana taps "Borin". Within 2 seconds the right rail shows Borin Stonebeard: alive, smith of Karak Dun, with his two latest Mentions quoted. She answers without leaving the game. Later she flips to Table view (`t`) so the players can read the recap from across the table.
6. At 22:15 she ends the session. The full transcript goes through summarize and then the draft review. She saves, and Flow 1 begins.

Failure: the backlog grows during a heated scene, and the banner reads "Falling behind — 3 min of audio queued. Nothing is lost up to 10 min." If the Wi-Fi drops, the session resumes on reconnect with "Reconnected — nothing lost". If the mic is denied, the pre-check names the browser setting.

### Flow 5 — Dana preps by interviewing an NPC (UJ-5, DS-4 second half)

1. Thursday evening. On Veyra's page Dana taps **Talk to Veyra**. Chat opens in NPC mode, and the header reads "Veyra · Alive · Knows 14 entries · Private".
2. She asks what Veyra saw at the bridge. "Veyra is thinking… 9 s" appears, then an in-character reply streams in with "Drawn from 3 entries".
3. She asks who leads the Lantern cult.
4. **Climax:** Veyra deflects in character ("I never saw the one they bow to. Only masks."), and the reply carries the **Not from this NPC's memories** label. The boundary holds, and Dana trusts it enough to improvise from it at the table.
5. She opens the KnowledgeScope chip and **Grants** Veyra the entry *Masks at Midnight*, because Veyra should know about the masks. "Applies from the next reply."
6. She copies a good line into a journal draft ("Copy to a journal draft"). The draft goes through normal review, and the conversation itself never changes Canon.

Failure: if the NPC has no confirmed Mentions, the empty state points to Knowledge. If the first token is slow on CPU, the thinking row shows elapsed seconds instead of a frozen spinner.

### Flow 6 — The table opens with "Previously on…" and the arc closes with a book (UJ-6, DS-5)

1. Before the Session, Dana opens Keepsakes › Previously on, picks the last Session and taps Generate. The recap streams into the familiar review panel, labelled Party with citations listed. She trims a line and saves.
2. She chooses the Narrator "Fantasy · warm storyteller" and taps Narrate. A Job runs ("Narrating… about 1 min"), and she prepares minis meanwhile. A toast reads "Recap narrated · Play".
3. At the table she taps **Table play**, and big text highlights as the Narrator speaks.
4. Months later, at the arc's end: Keepsakes › Chronicle › Player edition, PDF plus EPUB, include shared Player Journals. Export runs as a Job and she downloads both.
5. **Climax:** Stats shows a new MilestoneCard, "The party reached its 40th Session", with the foil rule. The book and the milestone mark the arc. Nothing asks her to come back sooner.

Failure: if the TTS service is down, the recap shows "Narrator unavailable — using your browser's voice". If the export fails, Retry is in the tray. An export made before a Visibility change is marked out of date.

### Flow 7 — Dana pins the Sunken Archive on the map (FR-52 to FR-55)

1. After applying Flow 1's checklist, Dana accepts "Place *Sunken Archive* on a map?" and picks "Karak Dun region".
2. The Map opens in placement mode with the PlacementBar "Placing *Sunken Archive*…". She clicks the marsh.
3. The PinEditor opens prefilled with label, Location and Visibility (Party, inherited). She links the entry *The Bell Tower* and saves.
4. She notices a GM-only Pin "Cult hideout" on the same Map, drawn as a `{components.map-pin-gm}` teardrop (dashed, `{colors.gm}`), and leaves it hidden.
5. **Climax:** she uses Preview this page as a Player. The Map shows the Archive Pin and no trace of the hideout. She exits the preview, confident.

Failure: an upload is too large ("Maps can be up to 50 MB and 16,000 px…"). If the image is replaced with a different aspect ratio, the "Review pin positions" mode appears.

### Flow 8 — Dana publishes her world before inviting players (FR-5, FR-41, FR-7)

1. After the upgrade, World shows: "142 entities came over from your old NPC and Quest lists. They're GM-only until you publish them."
2. She taps "Review and publish". Selection mode opens, filtered to GM-only, and she selects the 120 the party has met.
3. She chooses Set visibility › Party, and the inline confirmation asks "Make 120 entities visible to players?" She confirms.
4. She enters Preview as Player from the CampaignSwitcher. The PreviewBanner shows on every screen while she checks World, the Web and a Map.
5. **Climax:** satisfied, she exits the preview, opens Sharing › Members, creates a collaborate link with Role "Player", and sends it to Sam.

Failure: if a Party Entity shows a Relationship to a GM-only one, the Player view simply omits that edge (FR-8). Preview makes this visible to her, so she can publish the second Entity or leave it hidden.

### Flow 9 — Dana explores the relationship web by keyboard (FR-24)

1. In World › Web the graph appears already settled, with no animation.
2. She presses `/`, types "Grukk", and the view centres on Grukk's circle node.
3. Arrow keys move focus to connected nodes. The screen reader announces "Iron Fang, Faction, active, 9 relationships".
4. She filters Relationship type to "enemy of". The toolbar reads "Showing 18 of 214".
5. **Climax:** she presses `L` for List view. The same 18 entities appear as a sortable table, and expanding Grukk shows "→ enemy of → Aldric (since *Karak Dun*)". She opens Aldric's panel from the row, so the graph and list are one tool.

Failure: on her old laptop without WebGL, the Web opens in List view with an explanation.

## Open Questions

Non-blocking for architecture. They need the owner before the build of the named surface.

1. **Global current Campaign.** The CampaignSwitcher introduces app-wide campaign state that doesn't exist today (each page selects its own). Confirm before NavBar work.
2. **Nav consolidation.** Characters and Quests fold into World, Record Session becomes Live Session, and Analytics becomes Stats. Confirm the renames (old routes redirect).
3. **Theme count.** The brief for this run said 7 genre themes, but the repo has 6 built-ins (plus user custom themes). Is a seventh theme planned that needs token values?
4. **Preview as a specific Player?** This spine previews a generic Player. Previewing as Sam (including his Private journal, which GMs can read anyway) is possible. Is it wanted?
5. **Table view sizes** (36px captions, 32px recap) are estimates. Validate in a real table test at about 2 m.
6. **Achievement set and copy** (which Achievements exist, their names and glyphs) are not specified in the PRD.
7. **Browser notifications.** Opt-in in Settings is proposed. Confirm that it is acceptable for a self-hosted app, given that the permission prompt appears once.
8. **Narrator display names** depend on SPIKE-3 listening tests (addendum E).
