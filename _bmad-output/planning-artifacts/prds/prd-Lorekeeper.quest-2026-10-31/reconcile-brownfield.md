# Input reconciliation: brownfield-context.md vs PRD + addendum

Input: `_bmad-output/planning-artifacts/brownfield-context.md` (BF). Targets: `prd.md`, `addendum.md` (ADD).
Code spot-checks were made at commit `0c35e21` under `src/backend/app/`. Findings marked **[code]** were confirmed in source; they go beyond what the recon itself says.

Severity: **P0** = privacy leak or factual error that would mislead architecture. **P1** = missing requirement or contradiction. **P2** = detail worth carrying.

---

## A. Privacy leak paths that FR-8 / FR-9 can miss

### A1. P0: chat `sources[]` carries full Shorthand, and the trace's candidate list carries Shorthand for entries that never passed the gate [code]
- **Source:** BF §3.6 (`_prepare_chat`, `RetrievalCandidate`/`JournalSource`). `api/routes/chat.py:226-249`: every candidate gets `RetrievalCandidate(shorthand=r.entry.shorthand[:120])`, including entries that failed the gate. Every used entry gets `JournalSource(shorthand=r.entry.shorthand)` in full. Both go out in the response and the SSE `meta` event. The prompt context also includes `Notes: {shorthand}` (`chat_service.py:133`).
- **PRD:** FR-9 names only "the retrieval trace and the returned system prompt". ADD §C says "drop Shorthand from the context... strip the trace". Neither mentions the `sources` array that the "Not from your journal"/citation UI consumes, or that rejected candidates leak too.
- **Fix:** FR-9: for Players and share-link holders, `sources[]`, `retrieval.candidates[]` (all of them, not only used ones), `system_prompt` and `canon_sources` contain no Shorthand, no GM-only entry ids or snippets, and no GM-only source titles. Add a Player-specific `JournalSource`/`RetrievalCandidate` schema with no `shorthand` field instead of blanking the value. EV-4 asserts it on both `/api/chat/` and `/api/chat/stream`.

### A2. P0: Session Plans, Character Sheets, the Shorthand glossary and Tag Categories have no Visibility [code]
- **Source:** BF §2 (CharacterSheet "any member can read/write"; SessionPlan, ShorthandTerm "fed to prompts"), BF §2 multi-tenancy ("Members can read and write ... sheets, sources, plans and shorthand"). `api/routes/session_plans.py:101-120` lists and gets every plan for any member. `character_sheets.py` gates on membership only. `shorthand.py:26-36` lists the glossary for any member, and `chat.py:263-266` injects that glossary into every chat prompt.
- **PRD:** FR-8 lists "Journal Entry, Entity, Relationship, Canon Note, source document, Map and Pin". Session Plans (GM prep, the most spoiler-dense record in the app), Character Sheets, ShorthandTerms (for example "BBEG = the traitor Varn"), Tag Categories, ChatSessions and Narrated Recaps are not listed.
- **Fix:** FR-8: add Session Plans (GM-only, not Player-reachable), the Shorthand glossary (GM-only by default; never injected into a Player's prompt), Character Sheets (Party, with each Player able to edit only their own PC sheet; GM NPC sheets GM-only), Tag Categories, and Narrated Recap text and audio. EV-4 must cover `/api/session-plans/*`, `/api/shorthand/*` and `/api/character-sheets/*`.

### A3. P0: Player-reachable AI generators feed GM Shorthand and notes into prompts [code]
- **Source:** BF §3.6 (generators), §4 (npcs/quests generate, extract, suggest). `npcs.py:132-140` (bio from `shorthand` of ILIKE-matched entries), `npcs.py:163-172` (`/extract` runs NER over `shorthand + narrative` and returns the names), `quests.py:132-172` (description and suggest from `shorthand`), `journals.py:253-290` (recap and summarize use `get_campaign_with_access` only), `session_plans.py:35-65` (generate reads every entry, active quest and NPC). `chat_service.generate_session_recap` puts `Notes: {shorthand}` in the prompt.
- **PRD:** FR-8 has the general clause "AI features acting for a Player assemble their context only from content that Player may see". It never says which existing routes are GM-only. As written, an implementer could filter the new features and leave these existing ones open. `POST /npcs/extract` would hand a Player NPC names lifted from GM Shorthand, and that path has no LLM, so a "no generated answer" reading of FR-8 misses it.
- **Fix:** add an FR-8 consequence that names the existing authoring and AI routes, all GM-role only: `npcs/{id}/generate`, `npcs/extract`, `quests/{id}/generate`, `quests/suggest`, `journals/recap`, `journals/summarize-session`, `journals/autocomplete`, `journals/reindex`, `session-plans/generate`, and source upload and delete. A Player calling one gets 404, matching the existing `get_campaign_with_access` convention. EV-4 covers each.

### A4. P0: a per-campaign role check on `get_campaign_with_access` misses the routes that use `accessible_campaign_ids` [code]
- **Source:** BF §4 permission checks (`accessible_campaign_ids` = owned ∪ joined). `journals.py:104-109` (list without `campaign_id`), `:144`, `:156` (GET by id and tag attach/detach), `:325` (delete) and `tags.py:27` (tag counts without `campaign_id`) authorize against the union of campaigns, never calling `get_campaign_with_access`.
- **PRD:** FR-8 says "One shared enforcement point applies Visibility to every read". ADD §B proposes a role-aware `get_campaign_role` in `deps.py`. Neither notes that a user can be GM in campaign A and Player in campaign B, so a cross-campaign list or a fetch by bare entry id has to resolve the role per row's campaign. A helper keyed on a single `campaign_id` won't run for these routes.
- **Fix:** FR-8 consequence: cross-campaign lists and by-id fetches apply the requester's role per row campaign. Replace `accessible_campaign_ids` with a role-aware equivalent, for example returning `{campaign_id: role}`. A GM-only record fetched by id by a Player returns 404, so its existence isn't revealed. EV-4 tests a user who is GM in one campaign and Player in another.

### A5. P0: Shorthand-indexed search and ILIKE matching act as oracles even after the field is hidden [code]
- **Source:** BF §2 tsvector note (doc = `notes + narrative`), head migration `a3e7c1f9d258_index_shorthand_in_tsv`, BF §0 (ILIKE link). `journals.py:118-120`: `GET /journals?search=` matches and ranks on `narrative_tsv`, which includes Shorthand. `npcs.py:103-110` and `quests.py:108`: `/{id}/entries` matches `shorthand ILIKE %name%` and returns `JournalLiteResponse`, which serializes `shorthand` (`schemas/journal.py:61`).
- **PRD:** ADD §C covers the embedding side ("a possible later refinement is a narrative-only embedding") and says "also filter journal search". It doesn't say that lexical search over Shorthand is a membership oracle: a Player searching "traitor" learns which Party entries carry that word in GM notes. FR-12 replaces the ILIKE lookup only once F1 ships, and FR-9 ships before F1.
- **Fix:** FR-9 consequence: for Players and share links, keyword search and entry-for-entity matching use Narrative-only text (a second `narrative_only_tsv`, or `to_tsvector(narrative)` at query time), and `JournalLiteResponse` gets a Shorthand-free variant. Promote the narrative-only embedding for Player retrieval from "later refinement" to a Phase-0 requirement, or record it in §12 as an accepted residual risk with a measured test (EV-4 canary that appears only in Shorthand must not change a Player's ranking or result set).

### A6. P1: Player write paths echo GM-only fields and allow tampering [code]
- **Source:** BF §2 multi-tenancy ("Members can read and write journals, NPCs, quests, sheets, sources, plans and shorthand"), BF §4 (collaborate = "full write access identical to the owner except management"). `PUT /npcs/{id}` and `PUT /quests/{id}` return `NpcResponse`/`QuestResponse` including `notes`.
- **PRD:** FR-7 defines roles. FR-8 is framed around reads. FR-6 and FR-42 restrict Players to their own Player Journals, but nothing says Players lose write access to NPCs, Quests, sources, glossary, tags, sheets, plans and other members' entries. Any write response that serializes the full record leaks Secrets.
- **Fix:** FR-7 consequence: a Player-role write matrix. Players may write only their own Player Journal entries and their own PC sheet. Every other write route returns 404 for a Player. Write responses go through the same filtered serializer as reads. EV-4 also calls write routes with canary-bearing payloads.

### A7. P1: stored artefacts outlive a role change or Visibility change (chat history, cached files, Redis)
- **Source:** BF §2 (`ChatSession.messages` JSONB, "private per user"), BF §3.6 (`history[-8:]` goes into the prompt and `rewrite_search_query`), BF §3.9 (Redis `cache:journals:{user_id}` TTL 300).
- **PRD:** FR-44 says "Changing a Member from Co-GM to Player takes effect on that Member's next request", and FR-41 says "no caching window that leaks". Neither covers the Co-GM-era chat sessions, which hold GM-derived answers that are still listed, readable and replayed into new prompts. Cached narrated audio, rendered Chronicle files and map tiles produced while a record was Party also remain.
- **Fix:** FR-44: on demotion to Player, existing chat sessions in that campaign are archived (or purged) and never re-fed as history. FR-41: cached derivatives (audio, export files, tiles, the Redis journal cache) are keyed by Visibility state and invalidated on change. Note that `cache:journals:{user_id}` is keyed by user, not role.

### A8. P1: binary assets (map tiles, narration audio, export files) need an access-checked serving route
- **Source:** BF §0 (no blob storage), BF §9.10 (named volume plus a serving route), ADD §A (pyvips `dzsave` DeepZoom tiles).
- **PRD:** FR-54 tests "the Player's response" (the JSON). DeepZoom tiles and audio files are usually served as static paths. If nginx serves the volume directly, GM-only maps and audio are fetchable by URL with no check.
- **Fix:** FR-52, FR-32 and FR-47: every stored file is served only through an authenticated, role-checked backend route (or nginx `internal` plus `X-Accel-Redirect` after a backend check), never as a static path. URLs aren't guessable. EV-4 fetches the tile, audio and export URLs.

### A9. P1: Player Journal edits would trigger GM-only Jobs and surface GM-only output to the Player
- **Source:** BF §8 (draft-then-save invariant).
- **PRD (contradiction):** FR-6 says "An edit queues re-extraction (FR-18) and a continuity check (FR-19)" for any edit, and allows Players to edit their entries. FR-42 says Player entries run extraction "only when a GM chooses to". FR-2 shows Job status and reason to "the user who started it". A continuity Job started by a Player's edit would report Canon-quoting flags to a Player.
- **Fix:** FR-6: re-extraction and continuity on edit apply only to GM-authored entries. Player Journal Jobs run only when a GM triggers them, and the GM owns them. FR-2: Job payloads (proposals, flags, reasons) are visible only to GMs, whoever triggered the Job.

### A10. P1: outstanding collaborate links and the account gate
- **Source:** BF §4 share tokens (no expiry, soft revoke, `kind` string). `share.py:142` `join` requires `require_active_account` (402 unless `access_granted` or open-access). BF §1: every feature router is gated by `require_active_account`.
- **PRD:** FR-7 says new links default to Player and existing *Members* become Co-GM. It's silent on existing, unrevoked collaborate *tokens* already shared publicly. If migrated links grant Co-GM, they remain a full-GM door. Also, Players (UJ-3 Sam) need a paid or promo-granted account, or open-access mode, to join or use any route. Nothing in FR-40 addresses this gate.
- **Fix:** FR-7: existing collaborate tokens migrate to grant Player (or are marked legacy and the Owner is prompted), and the role is stored on the token row. Add a token expiry option. FR-40: state whether a Player needs `access_granted`. Propose that Player membership bypasses the account gate for portal routes only, and does not bypass it for hosted-AI routes (BYOK and quota still apply).

### A11. P2: smaller oracles
- `entry_hash` is **globally unique** (BF §2, §8). A 409 on a duplicate hash reveals that identical notes exist in another user's or campaign's entry, and a Player Journal could probe GM entries by hash. Fix: scope uniqueness to `(campaign_id, entry_hash)`, or return a generic response.
- Global `Tag` rows (BF §0): FR-4 keeps tags "unchanged". Tag *counts* must be computed over visible entries only (ADD §C covers counts). Analytics `top_characters` is tag-based today (BF §6.9), so FR-49's "falling back to tags" needs the same visibility filter.
- `GET /api/share/{token}` returns metadata for both kinds. Fine, but FR-40's read-only portal adds Party Entities, maps and recaps to an **unauthenticated, non-expiring** link. Call out the expanded blast radius in FR-9's release note and add expiry.
- `source_service.retrieve_canon_context` shares every source in the campaign (BF §3.5). FR-8 makes sources GM-only by default. Chat for a Player must therefore drop canon context entirely unless a source is marked Party, and must drop `canon_sources` titles.

---

## B. Factual errors and contradictions

### B1. P0: memory figures are the backend web tier only, but the PRD presents them as "the stack"
- **Source:** BF §0: "Four gunicorn workers each load spaCy trf and MiniLM ... about 6.4 GB idle and about 11.9 GB peak at boot ... Ollama is capped at 14g."
- **PRD:** NFR-2 says "the stack's peak memory ... measured about 6.4 GB idle and 11.9 GB peak today". R-5 says "The stack already exceeds 8 GB (about 6.4 GB idle ...)". 6.4 GB idle doesn't exceed 8 GB, so the sentence contradicts itself. The real stack adds Ollama (about 4.4 GB per 7B Q4, and up to two resident under `OLLAMA_MAX_LOADED_MODELS=2`, about 8.8 GB), Postgres (3g cap) and Redis (512m). Idle with one model warm is already well over 10 GB.
- **Fix:** NFR-2 and R-5: say "backend web tier (4 workers): ≈6.4 GB idle, ≈11.9 GB peak at boot, excluding Ollama, Postgres and Redis". Add an estimated whole-stack figure, and have SPIKE-5 measure per-service RSS for the whole stack. ADD §D already gives the 4.4 GB figure. Reconcile the two.

### B2. P1: Whisper is lazy-loaded per worker, and the existing `/api/ingest/voice` path is not in NFR-3
- **Source:** BF §3.8 (openai-whisper lazy per worker, `ThreadPoolExecutor(1)` per process; the compose comment is wrong). EasyOCR is the same.
- **PRD:** NFR-3 isolates *new* models. ADD §A says "Replace openai-whisper with faster-whisper" in an `stt` container. It never says whether the existing `/api/ingest/voice`, `RecordSessionPage` and `JournalInput` recorders move to that container. If they don't, Whisper ×4 workers stays in the peak.
- **Fix:** NFR-3: existing in-process Whisper and EasyOCR also move behind the STT container or the Job worker, and `ingest/voice` is re-pointed. SPIKE-5 counts them.

### B3. P1: FR-9 sequencing: the chat leak only exists once Roles exist
- **Source:** BF §4 (no role column; every member has full read).
- **PRD:** FR-9 calls chat retrieval a shipped leak "for every Member". Today all Members are equivalent collaborators, so the chat part only becomes a leak when Player roles ship (FR-7). The share-link part is a real shipped leak. That's fine, but FR-9's chat consequences must ship **in the same release as FR-7**, not later in Phase 0. Otherwise migration to roles opens the leak.
- **Fix:** FR-9: split into FR-9a (share link, ship now, standalone) and FR-9b (chat and every A1–A6 path), a release gate for FR-7.

---

## C. Omitted brownfield constraints

### C1. P1: background Jobs must carry the BYOK, quota and metering resolution
- **Source:** BF §3.1 (`get_user_llm_config` is a request `Depends`: personal config, then open-access, then hosted quota, then 402), BF §8 ("Every new AI route needs ... `record_hosted_usage`").
- **PRD:** FR-1 moves extraction, continuity and narration off the request. NFR-8 keeps "BYOK resolution ... and hosted-usage metering" for *routes*. Nothing says which user's LLM config a Job uses (the saver's? the Owner's?), how a BYOK API key is persisted for the worker (secret at rest in Redis or the job row), what happens when quota runs out between enqueue and run, or that the Job meters hosted usage.
- **Fix:** FR-1 consequences: the Job resolves the config of the GM who owns it at run time (never storing raw API keys in the queue), meters hosted usage via `record_hosted_usage`, and fails with a readable "AI quota or config" reason, not a silent retry, on a 402 condition.

### C2. P1: rate limiting per IP collides with the at-the-table use case
- **Source:** BF §1 nginx `ai_gen` 10r/m exact-match locations; BF §3.8 ("several users share an IP bucket ... behind the same NAT"); slowapi keyed by remote IP (`core/limiter.py`); chat 20/min.
- **PRD:** NFR-8 says "both rate-limit layers". UJ-4 and DS-4 put the GM and every Player on the same home Wi-Fi, so one IP. Live chunk POSTs (2–6/min at 10–30 s chunks), Rolling Recap (1/min), quick lookups, Player chat and NPC chat all share one 10 r/m `ai_gen` bucket.
- **Fix:** NFR-8: key slowapi on user id for authenticated routes. Give live-session chunk and lookup endpoints their own nginx zone sized for the chunk rate. Quick lookup (no LLM) stays out of `ai_gen`. Add a check to SPIKE-2.

### C3. P1: migrations: test harness reality and heavy data migration at boot
- **Source:** BF §1 (migrations run on every boot; healthcheck start 30 s), BF §2 (`env.py` imports only a few models; hand-typed revision ids), BF §7 (tests build the schema with `create_all`, so migrations are untested; `TEST_DB_URL` is hardcoded with no env override).
- **PRD:** NFR-8 says migrations are "tested against a copy of an existing database". FR-5 runs the NPC/Quest→Entity migration plus name-matching "unconfirmed Mentions" over every entry at boot. Neither notes that the existing test fixture can't test migrations at all, nor that a long data backfill inside `alembic upgrade head` delays gunicorn past the healthcheck.
- **Fix:** NFR-8: add a CI job that runs `alembic upgrade head` on a seeded pre-expansion dump, and make `TEST_DB_URL` env-overridable. FR-5: schema and row mapping go in the migration. Mention suggestion runs as a post-boot Job (FR-18 backfill), not in Alembic.

### C4. P1: CI trigger: path filters and the EV-4 gate
- **Source:** BF §0, §7: `backend-tests.yml` push on `master`, PRs only, with `paths: src/backend/**`.
- **PRD:** NFR-4 fixes the `main` trigger. It doesn't mention the path filter. A licence check on `package.json` (Sigma, Leaflet), `nginx/` or `docker-compose.prod.yml` (new sidecar images) would never run, and neither would EV-4 when only `nginx/locations.conf` changes.
- **Fix:** NFR-4: the licence check runs as a separate workflow without the backend path filter (covering `src/frontend/package*.json`, compose images and model manifests). EV-4 also triggers on `nginx/**`.

### C5. P1: test infrastructure for EV-4
- **Source:** BF §7: `ASGITransport` skips the lifespan, so Redis, spaCy and MiniLM aren't loaded; no fake LLM; a missing bearer returns **403**, not 401; slowapi limits apply (fixture calls `limiter.reset()`); share routes are 30/min.
- **PRD/ADD:** ADD §G covers lifespan, fake LLM and the frontend. It doesn't say EV-4 needs `embed`/`extract_tags` loaded or stubbed to exercise chat retrieval for real. A stubbed retrieval would test nothing. It also doesn't cover limiter resets between the many route calls, or that "no access" must be asserted as 404 (and anonymous as 403), not just "no canary".
- **Fix:** EV-4: run with real MiniLM and pgvector (spaCy may be stubbed) so retrieval filtering is exercised. Add a deterministic LLM stub that echoes its full prompt into the reply, so prompt-assembly leaks appear in the response body. Reset the limiter per call. Assert status codes too.

### C6. P1: draft-then-save details the PRD leaves open
- **Source:** BF §8 (the invariant; the offline queue is the only exception, an unattended one-step `/generate`), BF §5 (`NarrativeReviewPanel` is a pattern, not a drop-in; draft endpoints never persist).
- **PRD:** FR-15 and FR-31 respect the invariant. Not covered:
  1. Offline-queued entries (no review) still trigger F1 and F2 Jobs. Proposals stay pending, which is fine, but say so.
  2. FR-5 auto-creates "unconfirmed Mentions" and FR-36 defines NPC Knowledge as entries the NPC "has a Mention in". Say whether unconfirmed Mentions count. If they do, an unreviewed substring match drives NPC Knowledge, which violates the spirit of GM approval.
  3. FR-27 Rolling Recap and FR-28 lookups are generated text shown but not persisted. State that the Rolling Recap is never saved as Canon.
- **Fix:** add those three statements (FR-13, FR-36: only confirmed Mentions count; FR-27).

### C7. P1: journal edit (FR-6) misses tags, hash and offline queue
- **Source:** BF §0 (no edit endpoint; the edit must re-embed and recompute `narrative_tsv`), BF §8 (global unique `entry_hash`, client-computed in `utils/hashNotes.ts`, Redis dedup 24 h), BF §3.7 (spaCy tags on every save). [code] `journal_service.py:84-107` writes global tags from the narrative at create.
- **PRD:** FR-6 covers re-index, re-embed and duplicate detection. Missing: recompute the entry's spaCy tags (detach stale `journal_tags`), recompute `entry_hash` and refresh the Redis dedup key, invalidate the `cache:journals` key, and a rule for an edit that collides with another entry's hash.
- **Fix:** add these to FR-6's consequences.

### C8. P1: campaign and member deletion must cascade to new tables and files
- **Source:** BF §2: `Campaign` has **no back-refs** to npcs, quests or members. Cascades are FK-level only. BF §4 member removal `?delete_entries`. BF §0: no blob storage, so maps and audio live on a new volume.
- **PRD:** silent. Deleting a campaign leaves map files, tiles, audio and export files on the volume. Removing a member with `delete_entries` must also handle their Player Journals, proposals, Mentions sourced from those entries, and NPC Knowledge rows.
- **Fix:** add an FR, or extend FR-52 and FR-44: campaign delete removes every DB row (FK `ON DELETE CASCADE` on every new table) and every stored file. Member removal follows the `delete_entries` choice through derived World Model rows (pending proposals dropped; approved Canon kept with provenance "removed member").

### C9. P2: per-feature extension-point details not carried
- `EMBEDDING_DIM=384` is defined three times (BF §2). Canon Notes and any new embedded entity (FR-21 retrieval of Canon Notes) must reuse it. Carry it into ADD §B.
- No ANN index; cosine distance is a sequential scan (BF §2). Fine for the demo, but NPC Knowledge pre-filtering (ADD §A, "pgvector ≥ 0.8 iterative scan") presumes an index that doesn't exist. Check the pgvector version in the `pgvector/pgvector:pg16` image.
- `ai_service` makes a wasted Kobold-native request on Ollama before every narrative (BF §3.2). Any Job reusing `generate_narrative` doubles calls. Note for FR-1 latency.
- `summarize_session_transcript` truncates at 12,000 chars (BF §3.6, §8). FR-27 covers the Rolling Recap, but FR-29's end-of-session hand-off reuses the "existing summarize-to-shorthand flow", which would silently truncate a 3-hour session. Add a consequence to FR-29.
- The anti-hallucination note must go in the **user** message, not the system prompt (BF §3.6). ADD covers it for FR-36 only. FR-43 Player chat, FR-37 and FR-19's LLM verification should state the same placement.
- `autocomplete` inlines `Campaign.user_id == user.id` (BF §4), so collaborators get no campaign context today. Under roles, decide whether Co-GMs get it (yes) and Players don't (the route is GM-only per A3).
- New SSE endpoints (Job progress, FR-2; NPC chat, FR-35; live captions) each need an exact-match nginx location with `proxy_buffering off` or `X-Accel-Buffering: no`. ADD §B mentions the header. Make it an NFR-8 checklist item, alongside the WebSocket `Upgrade` location for FR-26.
- `OLLAMA_MAX_LOADED_MODELS=2` is already used by the finetuned and base models (BF §8). ADD §D proposes `=1` in the baseline profile. Say which model the Jobs use. Using `hosted_model_variant` per user means two GMs on different variants thrash model loads during queued Jobs.
- `ChatSession` has no `npc_id` (BF §6.6), and `campaign_id` is `SET NULL` on campaign delete. An NPC Conversation for a deleted NPC or campaign must not survive as a generic chat holding GM context.
- Frontend: `PrivateRoute` only checks `localStorage.lk_token`, and there's no global campaign context (BF §5). FR-41's "not a client-side hide" is right. Also state that the role-aware NavBar is cosmetic and every portal page relies on server filtering.
