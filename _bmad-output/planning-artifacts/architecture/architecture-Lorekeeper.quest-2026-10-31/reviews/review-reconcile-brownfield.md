# Review: reconcile spine against brownfield, scope-input and research

Date: 2026-10-31. Reviewed `ARCHITECTURE-SPINE.md` (draft) against `brownfield-context.md`, `scope-input.md` and `research-decisions-summary.md`, with spot checks of the real code at commit `0c35e21`. The spine itself was not edited.

## Verdict

**Mostly reconciled, with 5 high-severity gaps to fix before epics run in parallel.** The paradigm, job system, model sidecars, access module, migration discipline and most research picks match the inputs, and they ratify the real code: `get_campaign_with_access` returns 404, chat SSE already sets `X-Accel-Buffering: no`, the Alembic head is still `a3e7c1f9d258`, and CI really does trigger on `master`. But several brownfield pitfalls are either ignored or contradicted by a spine rule. Those pitfalls are the global `entry_hash`, the offline queue, the ambiguous `kobold` provider, the nginx `ai_gen` zone and global tags. If they stay open, parallel epics will each improvise their own fix.

## What landed correctly (no action)

- **CI on `master`:** AD-21 says "CI runs on `main` and on PRs" (but see F8 on the path filter).
- **Hand-typed revision ids and migrations on boot:** AD-19 requires generated ids and asserts a single head. AD-18 keeps heavy work out of boot migrations.
- **Model RAM multiplied per worker:** AD-1 and AD-7 move all models into sidecars.
- **No job system:** AD-2 to AD-5 add one.
- **Manual tsv, and `narrative_tsv` including Shorthand:** AD-17 recomputes `narrative_tsv`/`party_tsv` on every write path, and `party_tsv` is built from the Narrative only.
- **Analytics and export scoped to owner and author:** E0-Access owns the scope fix.
- **Share link leaks Shorthand:** handled by E0a.
- **Owner decisions:** F6 (default knowledge from Mentions, with GM grant/hide overrides) maps to AD-11 `npc_knowledge`. F4 (chunks of 10–30 s on CPU, recap about every 60 s, near-real-time on GPU only) maps to AD-15 and Deferred. The NPC/Quest migration default maps to AD-18. The AGPL correction is reflected as open-source vs commercial builds in AD-16 and AD-22.
- **Research picks kept:** Ollama JSON schema (flat), faster-whisper int8, Kokoro-FastAPI sidecar with GPL isolated, Sigma + graphology, WeasyPrint, plain Leaflet (no react-leaflet), NLI xsmall/base deferred to SPIKE-1, pyannote/sherpa deferred to SPIKE-4, rapidfuzz, pgvector 0.8 and `activity_events`.
- **Changed with a reason:** `npc_knowledge` holds GM overrides only, not a full link table (the reason given is drift).

## Findings (ranked)

### F1 [HIGH] `entry_hash` is globally unique, Redis dedup is global, and AD-17 makes it worse

**Reality.** `journal_entries.entry_hash` is `String(64), unique=True` (`db/models/journal.py:24`). The client computes it as `sha256(lower(trim(notes)))` (`utils/hashNotes.ts`). `POST /generate` returns 409 if Redis `dedup:{hash}` exists (`journals.py:65`), and `store_hash` runs only on create, with a 24 h TTL (`journal_service.py:125`).

**Spine.** AD-17 says the update path "recomputes … `entry_hash`" and changes nothing about scope.

**Consequences:**

- Two users in **different Campaigns** who type the same short notes ("session 1 recap") collide. The second user gets 409, which is also a cross-tenant existence oracle. Player Journals (FR-40+) make this collision far more likely.
- An edit that recomputes the hash can hit the global unique index. That raises `IntegrityError`, which surfaces as 500 through the global handler, not 409.
- After an edit, the Redis key for the old hash stays alive. The original notes then stay blocked for 24 h, and the new hash is never stored. FR-6 requires that "duplicate detection reflect the new text".
- The server cannot "recompute" a hash that the client computes unless the algorithm is pinned server-side.

**Fix.** Add to AD-17 and to the Foundation migration in AD-19:

- Replace the global unique with `UNIQUE(campaign_id, user_id, entry_hash)`.
- Compute the hash server-side in `journal_service` (same normalisation as `hashNotes.ts`). The client value becomes advisory.
- Scope the Redis key as `dedup:{campaign_id}:{user_id}:{hash}`.
- `update_entry` deletes the old key and sets the new one. `delete_entry` deletes the key.
- A collision returns 409, never 500.

### F2 [HIGH] The offline queue persists unreviewed AI narratives, which contradicts Draft-then-save and the Visibility defaults

**Reality.** `hooks/useOfflineQueue.ts:32` calls `api.generateJournal` with no `narrative`. `create_journal_entry` then generates the narrative and saves it in one step (the docstring calls this out as the unattended exception, `journal_service.py:74-80`).

**Spine.** The Draft-then-save convention says "AI output is never persisted … without an explicit GM action". FR-8 defaults Narratives to **Party**. The spine never mentions the offline path.

**Consequences:**

- A synced offline entry becomes Party-visible with an AI narrative that nobody read.
- That entry gets `party_tsv` and `party_embedding`, so Players retrieve it.
- It fires `entry_saved`. E1 then creates proposals whose `default_visibility` is Party, because the quote sits in a "Party Narrative".
- Each epic will hit this independently: E1 (proposals), E7 (portal) and E0-Journal (write path).

**Fix.** Add one rule under AD-17. Pick either option, but write it down:

- (a) Offline sync saves Shorthand only, as a server-side draft. The Review panel opens when the GM is next online.
- (b) Keep the one-step path, but force `visibility=gm`, set `needs_review=true`, and suppress `entry_saved` extraction until the GM approves the narrative.

Option (a) also removes the inline LLM call from a sync request.

### F3 [HIGH] AD-8 routes provider `kobold` to Ollama's native `/api/chat`, but `kobold` also means real KoboldCpp, and the wasted native call is ignored

**Reality.** The `kobold` provider covers both the bundled Ollama and a self-hosted KoboldCpp (`llm_provider.py:11-12`; BYOK users can point `api_url` at KoboldCpp). `ai_service.generate_narrative` always tries KoboldCpp's native `/api/v1/generate` first. On Ollama that returns 404. `HTTPStatusError` is caught and **retried 3 times** (`ai_service.py:155-165`), and only then does the code fall through to `/v1/chat/completions`. So every narrative on the default stack pays three failed requests.

**Spine.**

- AD-8 says "kobold/Ollama: native `/api/chat` with `format=<schema>`". Real KoboldCpp has no `/api/chat`, so `complete_structured` breaks for those users and has no fallback. (The openai/custom path does have a 400 fallback.)
- "The existing `complete_messages` and `stream_messages` keep their current behaviour" freezes the wasted retries in place.
- The baseline has a single Ollama slot (AD-7), so the wasted calls add latency to every save that generates a narrative.

**Fix.** Add to AD-8: `llm_provider.detect_backend(api_url) -> ollama | koboldcpp | openai_compat`, probed once and cached (reuse the logic in `check_kobold_health`). Then:

- `ai_service` uses the native Kobold path only when the backend is `koboldcpp`.
- `complete_structured` sends Ollama to `/api/chat` with `format`. It sends KoboldCpp to `/v1/chat/completions` with `response_format` json_schema or a grammar, falling back to prompted JSON. Validation and repair stay the same as now.

E0-LLM owns this.

### F4 [HIGH] AD-20 promises "a table sharing one IP" is not throttled together, but nginx `ai_gen` is IP-keyed and exact-match only

**Reality.** `limit_req_zone $binary_remote_addr zone=ai_gen … rate=10r/m` (`nginx/nginx.conf:52`). Every `ai_gen` entry is a `location =` exact match (`nginx/locations.conf:11-61`). Parameterised AI routes such as `POST /api/npcs/{id}/generate` already fall through to the generic 30 r/s `/api/` zone.

**Spine.** AD-20 requires "an nginx `location =` in `ai_gen`" for every new AI or streaming route, and adds a `user_or_ip` key only to slowapi. Many new routes carry ids in the path: NPC chat stream, recap narrate, `POST /api/jobs/{id}/retry`, `GET /api/files/{id}` and tiles. An exact match cannot express those. Meanwhile a GM and five Players behind one NAT share **10 r/m** at nginx (for portal chat, NPC chat and lookups), so the "Prevents" clause is false.

**Fix.** Amend AD-20:

- Parameterised AI routes use anchored regex locations, e.g. `location ~ ^/api/npc-chat/[^/]+/stream$`, with `proxy_buffering off` for SSE.
- Key `ai_gen` by a `map` over `$http_authorization` that falls back to `$binary_remote_addr`, or raise the burst. State which one.
- EV-4 asserts that every AI route matches an `ai_gen` location under nginx's real matching rules, not by string equality.

### F5 [HIGH] Global tags sit outside the visibility model, and edits don't refresh them

**Reality.**

- Every save runs spaCy over the Narrative and upserts **global** `Tag` rows plus `journal_tags` (`journal_service.py:84-107`).
- `GET /api/tags` returns tag names with entry counts, scoped only by campaign (`api/routes/tags.py:18-34`).
- The PRD keeps global tags (FR-4) and requires that "tags … reflect the new text" after an edit (FR-6).
- FR-8's covered-record list names Tag Categories, but not Tags or JournalTags.

**Spine.** Tags never appear. AD-12 and AD-13 do not register `Tag`/`JournalTag`. AD-17's recompute list leaves out tag re-extraction. E9 falls back to tags before F1 (PRD l.549).

**Consequences:**

- A tag named after a hidden NPC, extracted from a GM-only entry's Narrative, appears to Players with a count through `/api/tags` and through the tag list on each entry.
- E7 and E9 will each patch this differently.

**Fix.** Add to AD-13:

- Tags are derived records. Non-GM reads of tags go only through `journal_tags` joined to an `access.scoped_select(JournalEntry, ctx)`, and counts are computed over that scoped set.
- Register `JournalTag` in `VISIBILITY_REGISTRY` with effective visibility taken from its entry.

Add to AD-17: `update_entry` re-runs `extract_tags` and replaces that entry's `journal_tags`. Orphaned global tags are left in place.

### F6 [MED-HIGH] AD-1 "keep current function signatures" turns `embed`/`extract_tags` into blocking network calls on the event loop

**Reality.** `embed(text) -> list[float]` and `extract_tags(text)` are synchronous (`embedding_service.py:14`, `nlp_service.py:37`). They are called from async code in 7 places: `journal_service:84,120`, `journals.py:313`, `sources.py:92`, `source_service:56`, `retrieval_service:97`, `eval_service:40` and `npcs.py:173`.

**Spine.** AD-1 says these become HTTP client wrappers that "keep their current function signatures". A sync HTTP call to `ml` from the event loop blocks the whole worker for the round trip, and on baseline `ml` is CPU-bound. New epics (canon notes, Entity embeddings, NPC retrieval) will copy whichever signature exists.

**Fix.**

- Make `embed`, `embed_many`, `extract_tags`, `transcribe_audio` and `ocr` `async`, and have E0-Platform update the 7 call sites.
- State that `app/clients/*` use a shared `httpx.AsyncClient`.
- Change the rule to "same names and return types, now `async`".

### F7 [MED] AD-7's `OLLAMA_MAX_LOADED_MODELS=1` contradicts the two bundled models and the per-user variant

**Reality.** The stack ships `lorekeeper` (fine-tuned) and `lorekeeper-base`. `hosted_model_variant=="base"` swaps in the base model for open-access/hosted users (`deps.py` `get_user_llm_config`). Prod runs with `OLLAMA_MAX_LOADED_MODELS=2`.

**Spine.** AD-8 says "every task resolves to the user's configured model, so the bundled 7B is never evicted". That holds only if every user on the instance has picked the same variant. With one slot, a fine-tuned user and a base user in the same Campaign evict each other on every job, with a cold load of about 60 s each time (brownfield §8). Jobs resolve the *starter's* config (AD-2, AD-13), so a Player's job and the GM's job can differ.

**Fix.** Add to AD-7/AD-8 one of these:

- On the baseline profile, `model_for` pins **all** Jobs and interactive tasks to one instance-wide model (`settings.kobold_model`), ignoring `hosted_model_variant`, and the variant toggle is hidden on baseline.
- Or name the variant thrash as accepted cost and make SPIKE-5 measure it.

Also clarify the wording in AD-2: "owner's `LLMConfig`" means the Job's `ctx.user_id`, not the Campaign owner, and the same user is billed.

### F8 [MED] The test substrate omits Redis, and the CI path filter misses the new trees

**Reality.**

- Tests have no Redis. `ASGITransport` skips the lifespan, so `init_redis()` never runs.
- CI has only a Postgres service.
- `POST /api/journals/generate` already calls `check_hash`/`store_hash` through Redis.
- `backend-tests.yml` filters on `paths: src/backend/**`.

**Spine.** Five things now need Redis even with `JOBS_EAGER=1`: AD-2 to AD-5 (RQ, `jobs:{campaign_id}` pub/sub), AD-15 (live backlog list), the dedup keys and the AD-13 stream re-checks. AD-21 says nothing about Redis, so every epic will invent its own mock. EV-4 enumerates `nginx/locations.conf`, and new code lands in `src/services/ml`, `src/services/stt`, `profiles/`, `licenses/` and `nginx/`. Under the current filter, changes there never trigger CI.

**Fix.** Add to AD-21:

- A session fixture that provides `fakeredis.aioredis` (in-process) and patches `get_redis`, plus a `redis:7-alpine` CI service for the RQ integration tests.
- Widen the trigger to `src/**`, `nginx/**`, `profiles/**`, `licenses/**` and `docker-compose*.yml`, while keeping `main` in place of `master`.

### F9 [MED] Inline owner checks (autocomplete and others) escape AD-13 and its CI script

**Reality.** `POST /api/journals/autocomplete` uses `select(Campaign).where(Campaign.user_id == user.id)` (`journals.py:241-246`), so members get no campaign context. Under AD-18 every existing member becomes a Co-GM, so Co-GMs lose autocomplete context. Export, analytics, PATCH and `campaigns.py:_get_owned_campaign` use the same inline pattern.

**Spine.** E0-Access lists "analytics and export scope" but not autocomplete. `check_scoped_queries.py` only catches `select(<registered model>)`. `Campaign` carries no visibility, so it is presumably not registered and these checks slip past CI. FR-8 requires that autocomplete is GM-only (Co-GM included) and returns not-found to Players.

**Fix.**

- Add to E0-Access's owned list: replace every inline `Campaign.user_id == user.id` with `require_campaign(min_role="gm")`, or with an explicit `is_owner` check for the management routes only.
- Extend `check_scoped_queries.py` to fail on `Campaign.user_id ==` outside `access.py`.

### F10 [MED] The review registry is keyed by proposal `op`, but E2's flags are not proposals

The Review UI convention keys `itemRenderers.ts` by "proposal `op`", yet E2 is told to add "flag UI and its renderer in the review registry". `continuity_flags` have no `op` (AD-11). E1 and E2 work in parallel, so one of them will reshape the registry key.

The owner decision also says the checklist "extends NarrativeReviewPanel". The spine creates a standalone `ReviewChecklist` and never mentions keeping that panel's look, copy ("Edit freely — nothing's saved yet") and Save/Discard contract (`components/NarrativeReviewPanel.tsx`).

**Fix.**

- Key the registry by `item_kind` (`proposal:<op>` | `flag:<flag_type>`).
- Have the checklist accept both item kinds in one grouped list. Flags form their own group, which matches the owner's single checklist.
- State that `ReviewChecklist` reuses NarrativeReviewPanel's header, button styles and copy, with a shared `components/review/ReviewShell.tsx` extracted by E1.

### F11 [MED] Retcon notes in chat retrieval have no owning epic and no rule

The owner decision on F2 says a retcon note "becomes part of the record that later checks **and chat retrieval** consider". AD-11 gives `canon_notes` `embedding` and `tsv`, and the citation shape includes `kind: canon_note`. But no AD says that `hybrid_search_journal` or `_prepare_chat` must retrieve Canon Notes. AD-13's list cites `retrieve_canon_context`, which is the **source-document** retriever (`source_service.py:41-89`), not Canon Notes. E2 owns `canon_notes`, and E0-Access owns the chat refactor, so neither epic clearly owns the change.

**Fix.** Add to AD-11 that `retrieval_service` gains `canon_notes` as a third RRF source behind the same 0.65 gate, filtered through `access`. Canon Notes default to GM, so Players never see them. E2 owns the change, behind the `ctx` signature that E0-Access lands.

### F12 [MED] The research pick for EPUB was dropped, and brownfield points to an AGPL library

Research #6 picks a stdlib `zipfile` EPUB3 writer checked with EPUBCheck, and says to avoid EbookLib (AGPL) and Pandoc (GPL). The spine's Stack lists WeasyPrint only and never names the EPUB approach. Brownfield §9.8 tells E8 to add `ebooklib` and an fpdf2 TTF font. AD-22 would catch EbookLib in CI, but only after E8 has built on it.

**Fix.**

- Add a Stack row: "EPUB: in-house EPUB3 writer (`zipfile`), validated with EPUBCheck in the EV harness; no EbookLib or Pandoc."
- State whether fpdf2 is retired (WeasyPrint renders both the legacy export and the Chronicle) or kept for the old route.
- Note that WeasyPrint's Pango/HarfBuzz libraries now go into the shared web/worker image (AD-1 "one image"). SPIKE-5 should measure whether the worker's 512m limit survives a book-length render.

### F13 [LOW-MED] `EMBEDDING_DIM` has three copies, and the spine adds more embedding columns without a single source

**Reality.** `EMBEDDING_DIM = 384` is defined in `db/models/journal.py:9`, `db/models/source.py:8` and `services/embedding_service.py:6`.

**Spine.** AD-6 pins "384" as a contract, and AD-11 and AD-12 add `party_embedding` and `canon_notes.embedding` (and possibly Entity embeddings later). Every new model will add a fourth or fifth copy.

**Fix.** Add to AD-6:

- `app/core/embedding.py` defines `EMBEDDING_MODEL_ID` and `EMBEDDING_DIM`. Models and `clients/ml.py` import them, and the duplicates are removed.
- Migrations keep the literal 384, since they are frozen history.
- A boot or health check asserts that `ml /v1/embed`'s `dim` equals the constant.

### F14 [LOW-MED] The per-user Redis cache conflicts with role- and visibility-dependent reads

`cache_service.journal_list_key(user_id)` (TTL 300) exists but nothing calls it. If any epic revives it for journal or entity lists, it will serve stale Party/GM projections after a role or visibility change, because the key ignores `role_version` and visibility.

**Fix.** Add to AD-13: "No response caching of visibility-bearing data. Any future cache key must include `(campaign_id, user_id, role_version)` and be invalidated on `visibility_changed`." Alternatively, delete `cache_service.py` in E0-Access.

### F15 [LOW] The SSE client transport is unspecified, and EventSource cannot send the bearer token

AD-5 and the Frontend data convention say "SSE only through `lib/sse.ts`". `EventSource` cannot set `Authorization`, and AD-15 forbids tokens in URLs. The existing pattern is `fetch` + `ReadableStream` with manual parsing (`hooks/useChat.ts:65-130`).

**Fix.** State that `lib/sse.ts` is extracted from `useChat`'s fetch-based parser, that it reconnects with backoff, and that no `EventSource` or `?token=` is allowed. `useChat` migrates onto it.

### F16 [LOW] A measured 7B prompt rule is not lifted into a shared convention

Brownfield §3.6 records a measured result: the 7B ignores the "no relevant entries" grounding note when it sits in the system prompt, so it is prepended to the user message. Research #8 likewise says to re-inject the "if it isn't in your memories you don't know" rule after the history on every turn. E2 (verify), E4 (lookup) and E6 (NPC) all build grounded prompts.

**Fix.** Add a Consistency Conventions row: "Grounding and refusal instructions go in the final user turn, re-injected each turn, never only in the system prompt (measured; `chat_service.py:139-158`)."

### F17 [LOW] AD-17 names journal functions that don't exist, and delete returns 403

The real write path is `journal_service.create_journal_entry`. Delete is inline in the route and returns **403** to a non-author (`journals.py:318-339`). AD-17 names `save_entry`/`update_entry`/`delete_entry`, so E0-Journal may add `save_entry` alongside the real function. The 403 also contradicts AD-13's "denied → 404".

**Fix.**

- Name `create_journal_entry` (kept), plus new `update_journal_entry` and `delete_journal_entry`.
- Move the delete logic out of the route.
- State that a not-permitted delete or edit returns 404, and that EV-4 probes it.

### F18 [LOW] `AppConfig` is imported after `__all__`, which makes the model-registration file a merge hotspot

AD-19 makes `app/db/models/__init__.py` an append point for every epic. The file ends with `from app.db.models.app_config import AppConfig` placed after `__all__`, so parallel epics will append below it inconsistently. `migrations/env.py:40` imports five named models; that works only because the package import executes the whole `__init__`.

**Fix.** Have E0-Access, in the Foundation migration PR, move `AppConfig` above `__all__` and add it to `__all__`. Rule: each epic adds one import line and one `__all__` entry. Change `env.py` to `import app.db.models  # noqa` to make the intent explicit.

### F19 [LOW] The PRD's delegated TTS disk budget (≤ 500 MB) and cache bound are not carried

`scope-input` delegates "default TTS voices / disk budget" to PRD and architecture. The PRD sets ≤ 500 MB for the model and voices (§11), but the spine never mentions it, and AD-16's narration cache in `stored_files` is unbounded.

**Fix.** Add to AD-16: a 500 MB budget for the tts image's model and voices (checked in SPIKE-3), and a narration cache cap (e.g. LRU by `created_at` per Campaign) or "the cache is cleared when the recap is regenerated".

### F20 [LOW] The map coordinate and tile layout change from research is unexplained

Research #7 stores pins as image pixels `[y, x]`, and the spine stores normalised `[0, 1]`. That choice is defensible because it is independent of resolution, but the spine gives no reason. The tile route `{z}/{x}_{y}` mirrors DeepZoom naming, and DeepZoom levels do not equal Leaflet zoom levels.

**Fix.** Add one line giving the reason for normalised coordinates, and state that `pyvips dzsave(layout="google")` emits XYZ tiles at 256 px so Leaflet consumes them without a level translation. This only affects E10. It is listed because `lib/mapCoords.ts` is the single converter.
