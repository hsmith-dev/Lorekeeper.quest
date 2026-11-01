# Lorekeeper — Brownfield Context for Planning (features 1–10)

Generated 2026-10-31 from a read of the repo at commit `0c35e21` (branch `main`). Scope source: `scope-input.md` (same folder).
Path conventions: backend paths are relative to `src/backend/` (e.g. `app/services/x.py`), frontend paths relative to `src/frontend/src/` (e.g. `pages/X.tsx`), infra paths relative to the repo root. `file:N` = line number.

---

## 0. Surprises / things planners must know first

- **There is no background job system.** No Celery, RQ, arq, APScheduler, `BackgroundTasks` or `asyncio.create_task` anywhere. Every AI call runs inline in the request (gunicorn `--timeout 180`, nginx `proxy_read_timeout 600s`). Long work is either blocking or streamed over SSE. Redis is used only for dedup hashes and a 5-minute JSON cache. Features 1, 4, 5 and 8 need a job/queue decision (see §3.9).
- **Entity extraction exists, but only as spaCy NER that produces tags.** `app/services/nlp_service.py` runs `en_core_web_trf` with PERSON→character, GPE/LOC/FAC→location, ORG→faction, plus Matcher patterns for items (`ring of X`, `+1 sword`) and quests (`defeat/find/retrieve… X`). It runs on **every journal save** (`journal_service.py:84`) and writes **global** `Tag` rows. `POST /api/npcs/extract` (`api/routes/npcs.py:154`) reuses it to suggest new NPC names. It has no LLM, no status changes, no relationships and no review step.
- **Streaming STT does not exist.** Whisper `base` (openai-whisper, CPU, fp16=False) transcribes whole files in batch (`transcription_service.py`). `RecordSessionPage` fakes "live" by cutting a new `MediaRecorder` every 30 s (`SEGMENT_MS`, `pages/RecordSessionPage.tsx:12,65-77`) and POSTing each blob to `/api/ingest/voice`.
- **TTS exists only in the browser.** `hooks/useNarration.ts` wraps `window.speechSynthesis`, used for "Read Aloud" on `pages/EntryDetailPage.tsx:166`. The server has no TTS.
- **The LLM has no JSON or structured output.** Every prompt asks for free text and parses it by hand (numbered lists in `suggest_quests`, `TITLE:/PREMISE:` in `_parse_concept`, `chat_service.py:409-459`). Feature 1's diff extraction needs a new structured-output path (Ollama `format: json` or a JSON-schema `response_format`, plus a fallback parser and retry).
- **Tags are global, not campaign-scoped.** `Tag` is unique on `(name, tag_type)` and has no `campaign_id` (`db/models/tag.py:19`). Two campaigns that both mention "Mira" share one tag row. Campaign scoping happens only through the `journal_tags`→`journal_entries.campaign_id` join.
- **Journal entries cannot be edited.** There is no PUT/PATCH on `/api/journals/{id}` (create, list, get, tag attach/detach and delete only). "On journal save" for features 1 and 2 currently means create only. An edit flow would also have to re-embed and recompute `narrative_tsv`.
- **The NPC↔entry and quest↔entry link is a substring ILIKE on the name** (`api/routes/npcs.py:103-115`, `quests.py:108,132`), capped at 20. Nothing is stored.
- **No charting library.** `pages/AnalyticsPage.tsx` hand-rolls bars from Tailwind divs. There is no graph library either (feature 3 needs one, e.g. react-force-graph or cytoscape, to be chosen).
- **No file or blob storage.** Source uploads keep only the extracted text chunks (the original file is discarded, `api/routes/sources.py:48-106`). Avatars are base64 data URLs in `users.avatar_data`. Map images (feature 10) need a new volume or table.
- **Analytics and export are owner-only and author-only.** Both filter `Campaign.user_id == user.id` and `JournalEntry.user_id == user.id` (`api/routes/campaigns.py:119-156,158-209`), so collaborators' entries are silently left out. Features 8 and 9 should switch to `get_campaign_with_access` and campaign-wide scope.
- **The memory budget conflicts with the "~8 GB" README baseline** (`README.md:17`). Four gunicorn workers each load spaCy trf and MiniLM, plus Whisper lazily on first transcription: about 6.4 GB idle and about 11.9 GB peak at boot (`docker-compose.prod.yml:172-194`). Ollama is capped at 14g. Any new in-process model is loaded ×4, so new heavy models (faster-whisper streaming, Piper) belong in their own container.
- **Backend CI never runs on `main`.** `.github/workflows/backend-tests.yml` triggers on `push: branches: [master]`, but the default branch is `main`. Only PRs trigger it.

---

## 1. Stack and runtime

**Production compose** (`docker-compose.prod.yml`). All services are on the default network and only nginx exposes ports.

| Service | Image / build | Limits | Healthcheck | Volumes |
|---|---|---|---|---|
| postgres | `pgvector/pgvector:pg16` | 1 CPU / 3g (`:54-58`) | `pg_isready` 10s | `postgres_data` |
| redis | `redis:7-alpine`, `--save 60 1` | 0.5 / 512m | `redis-cli ping` | `redis_data` |
| ollama | `ollama/ollama:latest`; `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_KEEP_ALIVE=60m` (`:97-98`) | 3 CPU / 14g | `ollama list` 15s, start 20s | `ollama_data`, `./src/ml/models:/import-models:ro` |
| backend | `src/backend/Dockerfile.prod` (py3.11-slim, spaCy trf baked in, non-root `appuser`) | 2 CPU / 14g | GET `/api/health` 30s, start 30s | `./src/ml/data:/ml/data:ro`, `backend_logs:/var/log/lorekeeper` |
| nginx | `nginx/Dockerfile` (multi-stage: builds the Vite frontend, serves static) | 0.5 / 256m | none | `nginx_logs`, `/etc/letsencrypt:ro` |

- Backend command (`:164`): `alembic upgrade head && gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --timeout 180 --forwarded-allow-ips='*'`. **Migrations run on every boot.**
- Dev: `docker-compose.yml` runs `uvicorn --reload` with the backend source bind-mounted and Vite on :5173 (proxying `/api` to :8000, `vite.config.ts`). `docker-compose.dev.yml` runs only postgres and redis.
- Two models live in Ollama: `lorekeeper` (fine-tuned Mistral-7B Q4 GGUF from `hf.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF`) and `lorekeeper-base` (`mistral:7b-instruct-q4_0`). The admin portal can install them over SSE (`app/services/ollama_service.py:147-183`, `api/routes/admin.py:378`).
- GPU is optional, via a compose override that adds a device reservation to `ollama` (`README.md:86-103`).

**nginx** (`nginx/nginx.conf`, `nginx/locations.conf`, `nginx/proxy_common.conf`):
- Rate-limit zones: `api` 30r/s, `auth` 5r/m, `ai_gen` 10r/m (`nginx.conf` http block). HTTP redirects to HTTPS, and a self-signed cert is generated when none is mounted (`nginx/ensure-certs.sh`).
- Every AI endpoint has an **exact-match** `location =` in `locations.conf:11-64` put in the `ai_gen` zone: journals generate-draft/generate/autocomplete/recap/summarize-session, `/api/chat/`, `/api/chat/stream` (with `proxy_buffering off`), session-plans/generate, settings test/evaluate, ingest voice/image. **Every new AI or STT/TTS endpoint must be added here**, or it falls into the generic 30r/s zone. SSE endpoints also need `proxy_buffering off` or an `X-Accel-Buffering: no` response header (the admin install SSE uses the header).
- Upstream `backend:8000` keepalive 32. `proxy_read_timeout 600s`. Static `/` uses `try_files … /index.html` with 1y immutable caching for assets. **No WebSocket upgrade headers are configured** (`Connection ""`). Feature 4 would need `Upgrade`/`Connection: upgrade` in a new location, or else chunked POST/SSE.

**How the services talk:** browser → nginx → `/api/*` → backend. Backend → postgres (asyncpg, pool 10 + 20 overflow, `app/db/session.py`), → redis (`app/core/redis_client.py`, `decode_responses=True`), → Ollama via `KOBOLD_URL` (`http://ollama:11434` in `.env.example`). It uses the OpenAI-compat `/v1/chat/completions` for completions and native `/api/tags|pull|create|copy` for management. ML models run **in-process** in the backend: spaCy, sentence-transformers, Whisper, EasyOCR.

**Config** (`app/core/config.py`, pydantic-settings, `.env` at repo root, `extra="ignore"`). Fields: `database_url`, `redis_url`, `secret_key`, JWT expiry (1440 min access, 7 d refresh), `kobold_url`, `kobold_timeout_seconds` (120 by default, 600 in `.env.example`), `kobold_max_length` 800, `kobold_temperature` 0.72, `kobold_top_p` 0.95, `kobold_model="lorekeeper"`, `kobold_base_model="lorekeeper-base"`, `environment`, `cors_origins`, `log_level`, `log_file`, `open_access_mode`, `frontend_url`, Stripe ids, Resend, `admin_email`. `get_settings()` is `lru_cache`d. The runtime "open access" flag also lives in the DB `app_config` row (`app/services/app_config_service.py`). Other core modules: `core/security.py` (JWT, bcrypt), `core/limiter.py` (slowapi, keyed by remote IP), `core/logging.py` (JSON formatter, ring buffer, optional rotating file).

**App bootstrap** (`app/main.py`). The lifespan (`:31-41`) calls `init_redis()`, `load_nlp_model()` and `load_embedding_model()` per worker. The global exception handler returns 500 `{"detail": "An unexpected error occurred…"}` (`:80-86`). `/api/health` reports db + kobold reachability (`:89-107`). Routers are registered at `:118-142`. Feature routers get `dependencies=[Depends(require_active_account)]`; auth, billing and settings are ungated; share is ungated (public); admin uses `require_admin`.

---

## 2. Data model

All models are in `app/db/models/`, exported in `__init__.py` (note that `AppConfig` is imported **after** `__all__` at `:33`). The base is `app/db/base.py`: `Base(DeclarativeBase)` + `TimestampMixin` (`created_at`, `updated_at` timestamptz with server defaults). Every PK is a `UUID(as_uuid=True)` with a uuid4 default, except `app_config.id` (int, singleton 1). Enums are SQLAlchemy `SAEnum` (native PG enum types, named after the lowercase class unless overridden).

| Model (table) | Key fields | Ownership / relationships |
|---|---|---|
| `User` (users) `user.py` | email (unique), hashed_password, display_name, avatar_data (base64 Text), access_granted/access_source, is_suspended(+reason, at), is_admin, has_completed_tutorial, password_changed_at, failed_login_attempts, locked_until | campaigns (cascade), journal_entries, chat_sessions, subscription |
| `Campaign` (campaigns) `campaign.py:17` | user_id (owner, FK CASCADE), name(200), genre `Genre`, description | `user`, `journal_entries` (cascade). **No back-refs** to npcs/quests/members |
| `Genre` `campaign.py:9` | fantasy, scifi, horror, videogame, other | drives the prompt voice in `ai_service.GENRE_SYSTEM` |
| `CampaignMember` (campaign_members) `campaign_member.py:8` | campaign_id, user_id, **no role column** | UQ(campaign_id,user_id). Owner is NOT a row |
| `CampaignShareToken` (campaign_share_tokens) `share_token.py:8` | campaign_id, created_by_user_id, token(64, unique, `secrets.token_urlsafe(24)`), revoked bool, kind str(20) `"read_only"`/`"collaborate"` | |
| `JournalEntry` (journal_entries) `journal.py:12` | user_id (author), campaign_id, shorthand Text, narrative Text, narrative_tsv TSVECTOR (GIN `ix_journal_narrative_fts`), entry_hash(64, **globally unique**), session_date Date?, embedding Vector(384)? | tags via `journal_tags` |
| `Tag` (tags) `tag.py:17` | name(200, indexed), tag_type `TagType`?, custom_category_id? (exactly one set) | **global**, UQ(name,tag_type) |
| `TagType` `tag.py:9` | character, location, item, quest, faction | |
| `JournalTag` (journal_tags) | PK(journal_id, tag_id), both CASCADE | |
| `TagCategory` (tag_categories) | campaign_id, created_by_user_id, name(50) | UQ(campaign_id,name) |
| `NpcEntry` (**npcs**) `npc.py:22` | user_id (creator), campaign_id, name(200), role `NpcRole`, status `NpcStatus`, description, notes | no entry links |
| `NpcRole` `npc.py:9` | npc, pc, monster, **faction** | factions are currently NPC rows with role=faction |
| `NpcStatus` `npc.py:16` | alive, dead, unknown | |
| `Quest` (quests) `quest.py:16` | user_id, campaign_id, title(300), description, status `QuestStatus`, notes | no progress/steps, no entry links |
| `QuestStatus` `quest.py:9` | active, completed, failed, abandoned | |
| `CharacterSheetTemplate` / `CharacterSheet` `character_sheet.py` | template.fields JSONB `[{key,label,type: text/number/long_text/list}]`, sheet.data JSONB `{key: value}`, created_by_user_id | campaign-scoped, any member can read/write |
| `ChatSession` (chat_sessions) `chat.py:8` | user_id, campaign_id? (SET NULL), title, messages JSONB `[{role,content}]`, message_count | private per user |
| `SourceDocument` / `SourceChunk` `source.py` | doc: title, filename. chunk: chunk_index, content, embedding Vector(384) | campaign-shared |
| `SessionPlan` (session_plans) | user_id, campaign_id, title, content Text | |
| `ShorthandTerm` (shorthand_terms) | campaign_id, term(50), meaning, usage | fed to prompts |
| `UserSettings` (user_settings) | llm_provider (default "kobold"), llm_api_url/key/model, llm_temperature, llm_max_tokens, narrative_paragraph_limit, hosted_model_variant ("finetuned"/"base") | 1:1 user |
| `ModelEvaluation` | label, sample_size, avg_length, avg_word_overlap, avg_semantic_similarity, has_content_pct, error_count | per user |
| Billing/admin | `Subscription`, `PromoCode`/`PromoCodeRedemption`, `Feedback`(+`FeedbackCategory`), `PasswordResetToken`, `AdminMessage`, `AppConfig`, `TrainingSample`(+TrainingGenre/GameSystem/ScenarioType) | not relevant to features 1–10 |

**Multi-tenancy rule.** Data is **campaign-scoped**, with `user_id` meaning author/creator, not access. Access is: owner (`campaigns.user_id`) or a `CampaignMember` row. Members can read and write journals, NPCs, quests, sheets, sources, plans and shorthand. Journal delete is author-or-owner (`api/routes/journals.py:318-339`). Campaign management (share links, members, tag categories, PATCH, delete, export, analytics) is owner-only. **There is no GM/player distinction and no per-field visibility** (feature 7 adds both).

**Alembic** (`migrations/`, `alembic.ini`; `env.py` loads the repo `.env` and imports `Base.metadata`, though only a few models are imported explicitly at `env.py:40`. Autogenerate needs the new models imported).
- **Current head: `a3e7c1f9d258`** (`index_shorthand_in_tsv`, revises `8c1d5f3a92e7`). The chain is linear, 28 revisions, root `fc4226e829a0_initial_schema`.
- Naming: `<12-hex-id>_<snake_description>.py`. Many recent ids are hand-typed pseudo-sequential hex (`a1b2c3d4e5f6`, `b2c3d4e5f6a7`, `c3d4e5f6a7b8`, …), so **check for id collisions** before reusing that pattern. Typing is `revision: str`, `down_revision: Union[str, None]`.
- Vectors: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` + `sa.Column('embedding', Vector(384))` from `pgvector.sqlalchemy` (`7ffedba22a12_add_journal_embeddings.py:20-22`). **No ANN index (ivfflat/hnsw)** exists. Cosine distance runs as a sequential scan, which is fine at demo scale.
- tsvector: the column was created in the initial schema with a GIN index (`fc4226e829a0…:58,68`). **There is no DB trigger.** The app writes it manually after insert with `UPDATE journal_entries SET narrative_tsv = to_tsvector('english', :doc)` where doc = `f"{notes} {narrative}"` (`app/services/journal_service.py:113-116`). Backfills are raw SQL `op.execute(UPDATE …)` (`a3e7c1f9d258…:29-32`). Any new searchable entity text must follow the same manual pattern, or a trigger has to be introduced.
- `EMBEDDING_DIM = 384` is defined three times (`db/models/journal.py:9`, `db/models/source.py:8`, `services/embedding_service.py:6`) and must stay in sync.
- The schema is documented in `docs/database-schema.md` / `.html`.

---

## 3. AI pipeline

### 3.1 `app/services/llm_provider.py` (provider routing / BYOK)
- `LLMConfig(provider, api_url, api_key, model, temperature=0.72, max_tokens=800)` (`:9-16`). Providers: `kobold` (= the stack's Ollama or KoboldCpp, via OpenAI-compat), `openai`, `custom` (OpenAI-compat), `anthropic`, `gemini`.
- `get_default_config()` (`:19`) builds the platform Ollama config. `is_hosted_default(cfg)` (`:30`) gates billing metering.
- `complete_messages(messages, config, max_tokens, temperature, timeout)` (`:41`) takes OpenAI-format messages and returns a string. **All failures surface as `HTTPException(503, "AI model unavailable: …")`** (400 when an Anthropic/Gemini key is missing).
- `stream_messages(...)` (`:62-130`) is an async generator of deltas. It does real SSE streaming for kobold/openai/custom. Anthropic/Gemini yield one chunk. It raises 503 before the first token, and a mid-stream error ends the stream quietly.
- No `response_format`, `format: json`, tools or grammar support. Payload is `{model, messages, max_tokens, temperature, stream}` only (`:98-104,166-171`).
- **BYOK resolution** is `api/deps.py:152-260` `get_user_llm_config`, injected into AI routes with `Depends`. Order: a personal UserSettings config wins, then open-access mode (platform default, with `hosted_model_variant=="base"` swapping in `kobold_base_model`), then a hosted subscriber with quota, then 402 with header `X-Gate-Reason: llm-config`. After hosted completions, routes call `billing_service.record_hosted_usage(db, user, *texts)` when `is_hosted_default(config)`. **Copy this into every new AI route.**

### 3.2 `app/services/ai_service.py` (journal narrative)
- `GENRE_SYSTEM` dict per `Genre` (`:7-30`), plus a fantasy few-shot example (`:32-41`).
- Prompt assembly: system = genre prompt + `_canon_block(canon_context)` (`:60`, source-document RAG) + `_shorthand_block(glossary)` (`:69`) + `_length_block(paragraph_limit)` (`:43`). User = `"Input: {notes}\nOutput:"`.
- `generate_narrative` (`:87`) tries KoboldCpp-native `/api/v1/generate` first when provider is kobold (`_generate_kobold_native`, `:128`, with `stop_sequence ["\nInput:"]`, `rep_pen 1.1`, 3 retries). On Ollama that 404s and silently falls through to `complete_messages`. **On Ollama every narrative pays a wasted failed request first.**
- Caller: `journal_service.generate_draft_narrative` (`:19-61`). Canon context, glossary and paragraph-limit lookups are all wrapped in `try/except` so they never block generation.

### 3.3 `app/services/ollama_service.py`
Native Ollama management only: status/tags, pull with progress, create (with `MISTRAL_TEMPLATE` and stops), copy, and `install_model_events` (an SSE event generator that never raises). It does not do completions or embeddings. This is the reference pattern for a **long-running job that streams progress over SSE**.

### 3.4 `app/services/embedding_service.py`
`sentence-transformers` `all-MiniLM-L6-v2`, `EMBEDDING_DIM=384`, `normalize_embeddings=True`. `embed(text) -> list[float]` is **synchronous, CPU-bound, and called on the event loop** (no executor). It is loaded per worker in the lifespan. Used by journal save (`journal_service.py:120`), reindex (`api/routes/journals.py:299`), sources upload (one call per chunk), retrieval, and eval scoring.

### 3.5 `app/services/retrieval_service.py` (hybrid RAG; reuse for features 2, 4 and 6)
- `hybrid_search_journal(db, query_text, *, campaign_id, user_id, limit=3, max_distance=0.65) -> list[RetrievedEntry]` (`:75`). Scope is `campaign_id` (all members' entries) or else `user_id`.
- Dense: pgvector `cosine_distance`, top 10 (`_CANDIDATE_POOL`). Lexical: per-content-word `narrative_tsv @@ plainto_tsquery` flags summed (OR recall, ranked by matched-word count; `_STOPWORDS` at `:52`). Fused with RRF K=60 (`:186-201`).
- **Relevance gate** (`:197`): passes if `vector_distance <= RAG_RELEVANCE_MAX_DISTANCE (0.65, :44)`, or lexical evidence is "strong". Strong means a case-sensitive literal proper-noun match from the query in `shorthand+narrative`, or ≥3 matched words covering ≥75% of the content words (`:175`). Lexical-only grazes boost rank but cannot pass the gate.
- `RetrievedEntry` (`:59`) has entry, vector_distance, lexical_rank, rrf_score, passed_gate, used, and `.method` (both/semantic/keyword). **All candidates are returned for the trace.**
- Source-document canon retrieval is separate and vector-only: `source_service.retrieve_canon_context` (`app/services/source_service.py:41-89`), same 0.65 gate, returns `(text, titles)`.

### 3.6 `app/services/chat_service.py` and `api/routes/chat.py`
- `_SYSTEM_PROMPT` "ancient chronicler" persona (`chat_service.py:9`). `rewrite_search_query` (`:47`) rewrites pronoun follow-ups into standalone retrieval queries using the LLM; it is retrieval-only and never blocks.
- `build_chat_messages` (`:94-163`) builds: system = persona + campaign + canon + glossary + journal context (each narrative truncated to 350 chars), then `history[-8:]`. **The "no relevant entries" anti-hallucination note is prepended to the user message, not the system prompt** (`:139-158`; a 7B model ignores it in the system prompt, measured). This matters for features 2 and 6.
- Other generators, all free-text `complete_messages`: `autocomplete_notes` (:183, 8s timeout), `suggest_quests` (:214), `generate_session_recap` (:249, last-10 entries, third-person 2–4 paragraphs), `summarize_session_transcript` (:276, transcript truncated to 12000 chars to bullets), `generate_npc_bio` (:301), `generate_quest_description` (:330), `generate_session_plan` (:358, RECAP/OBJECTIVES/… headers), `generate_campaign_concept` + `_parse_concept` (:409-459).
- Route (`api/routes/chat.py`): `_ChatPrep` + `_prepare_chat` (`:136-318`) does campaign access (falls back silently on no access), rewrite, hybrid search, then `RetrievalCandidate`/`JournalSource` lists, canon, glossary, then loads or creates the `ChatSession`. `POST /api/chat/` (`:330`) blocks. `POST /api/chat/stream` (`:355-405`) is SSE with events `meta` (session_id, sources, canon_sources, grounded, retrieval trace incl. system prompt), `delta {text}`, `done {reply}`, `error {detail}`. Both use slowapi `20/minute`. `grounded()` is false when a campaign is set but no sources are found, and drives the "Not from your journal" label. Schemas are in `app/schemas/chat.py` (`RetrievalDebug`, `RetrievalCandidate`, `JournalSource`).
- Frontend consumer: `hooks/useChat.ts:65-130` uses `fetch` + `ReadableStream` reader with a manual SSE parse, and falls back to the blocking endpoint.

### 3.7 `app/services/nlp_service.py`
See §0. `extract_tags(text) -> list[ExtractedTag(name.title(), TagType)]`, deduped case-insensitively. Raises `RuntimeError` if the model is not loaded (so tests that hit journal save need the model). `en_core_web_trf` is a transformer model: heavy, slow on CPU, loaded per worker.

### 3.8 Transcription / vision
- `app/services/transcription_service.py`: openai-whisper `base`, **lazy-loaded on first call per worker** (the compose comment claims startup load; the code is lazy), `ThreadPoolExecutor(max_workers=1)` per process, writes a temp file, returns `result["text"]`. Batch only, with no timestamps, segments or diarization kept.
- `/api/ingest/voice` (`api/routes/ingest.py:67-86`): 25 MB max, content-type sniffed to an extension, 422 on empty text, slowapi 10/min **and** nginx `ai_gen` 10r/m. Feature 4's 30s segments are about 2/min, but several users share an IP bucket only if they are behind the same NAT.
- `app/services/vision_service.py`: EasyOCR `en`, CPU, lazy, single-thread executor. `/api/ingest/image` (10 MB). `/api/ingest/discord` cleans pasted chat with regex.

### 3.9 Eval and background work
- `app/services/eval_service.py`: runs `/ml/data/processed/validation_set.jsonl` through `complete_messages`, scoring word overlap, MiniLM cosine semantic similarity, length and has_content. Results are persisted to `ModelEvaluation` via `POST /api/settings/evaluate` (`api/routes/settings.py:211`). This is a generation-quality eval.
- `docs/RETRIEVAL_EVAL.md` + `scripts/eval_retrieval.py` (136 lines): 21 labeled queries (16 on-topic, 5 off-topic incl. the hard negative "queen of the elven court") against the seeded 9-entry demo campaign (Grukk, Aldric, Borin Stonebeard, Karak Dun, Veyra, Dawnbreaker). Metrics: **hit@3** and **gate-holds**, swept across thresholds 0.55/0.65/0.75 × vector-only vs hybrid. Production point: hybrid@0.65 = 14/16 hit@3, 5/5 gate-holds. The doc format (method, results table, chosen operating point, "measured failure → fix" table, reproduce command) is the **template to copy** for features 1, 2, 4, 5 and 6 evals. Run with `docker compose -f docker-compose.prod.yml exec backend python scripts/eval_retrieval.py --campaign-id <uuid> --thresholds …`. The demo-campaign seed data is not in the repo.
- Background jobs: **none**. The only concurrency primitives are per-process `ThreadPoolExecutor(1)` for Whisper/OCR and SSE generators. Redis keys: `dedup:{hash}` TTL 24h (`dedup_service.py`) and `cache:journals:{user_id}` TTL 300 (`cache_service.py`, barely used). Redis has a 512m limit and RDB persistence, so it is a natural broker for an arq/RQ worker container.

---

## 4. API

Route modules live in `app/api/routes/`. Every collection endpoint takes `campaign_id` as a query param, not a path segment (except `/campaigns/{id}/…`). Note the trailing slashes (`"/"`), which the frontend relies on.

| Module (prefix) | Main endpoints |
|---|---|
| `auth.py` (/api/auth) | register (first account becomes admin, `:73-83`), login (lockout), me, tutorial-complete, me/avatar, forgot/reset-password |
| `campaigns.py` (/api/campaigns) | POST / ; generate-concept ; GET / (owned + joined, adds `is_owner` and `owner_display_name`, `:71-96`) ; PATCH /{id} ; GET /{id}/export?format=pdf\|markdown (`:119`) ; GET /{id}/analytics (`:158`) ; share list/create/revoke (`:212-264`) ; members list/remove (`?delete_entries`) (`:267-324`) ; POST /{id}/leave ; tag-categories CRUD ; DELETE /{id} |
| `journals.py` (/api/journals) | generate-draft (`:38`, no persist) ; generate (`:58`, persist; 409 on dup hash) ; GET / (search uses tsv `plainto_tsquery` + ts_rank, `tag_id`, pagination) ; GET /{id} ; tags attach/detach ; autocomplete ; recap (`:253`) ; summarize-session (`:279`) ; reindex (`:299`) ; DELETE /{id} |
| `npcs.py` / `quests.py` | CRUD (PUT = partial via `exclude_none`) ; GET /{id}/entries (ILIKE) ; POST /{id}/generate (bio/description) ; npcs POST /extract ; quests POST /suggest |
| `chat.py` (/api/chat) | health, sessions list/get/delete, POST /, POST /stream |
| `ingest.py` (/api/ingest) | image, voice, discord |
| `sources.py`, `session_plans.py` (generate/CRUD), `shorthand.py`, `character_sheets.py` (templates + sheets), `tags.py` (GET / with counts), `feedback.py`, `settings.py` (LLM settings, model-status, test, evaluate, evaluations), `billing.py`, `admin.py` (users, promo codes, config, models install SSE, logs, support-bundle) |
| `share.py` (/api/share, **no auth**) | GET /{token} (either kind; metadata + `share_kind`) ; GET /{token}/journals, /journals/{id}, /npcs, /quests (**read_only kind only**) ; POST /{token}/join (collaborate kind, needs `require_active_account`). All slowapi 30/min (join 10/min) |

**Auth dependency pattern** (`app/api/deps.py`):
- `get_current_user` (`:15-44`): HTTPBearer JWT → `decode_token_payload` → User. Rejects tokens issued before `password_changed_at`, and suspended users (403). A missing bearer gives **403** (HTTPBearer default), not 401.
- `require_active_account` (`:47-77`): 402 with `X-Gate-Reason: account-gate` unless `access_granted` or open-access. Applied router-wide in `main.py`.
- `require_admin` (`:94`): `is_admin` or `ADMIN_EMAIL`.
- Handlers still declare `user: User = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)` per route.

**Permission checks:**
- `get_campaign_with_access(db, campaign_id, user, require_owner=False)` (`deps.py:103-136`) is the single gate. The owner always passes. A member passes unless `require_owner`. Failure is **404 (never 403)** so existence does not leak.
- `accessible_campaign_ids(db, user)` (`:139-149`) gives owned ∪ joined, for cross-campaign lists.
- `campaigns.py:_get_owned_campaign` (`:32`) is an owner-only equivalent. Several routes inline `Campaign.user_id == user.id` instead: export, analytics, PATCH, and **autocomplete** (`journals.py:241`, so members get no campaign context).
- Entity routes fetch the row, then call `get_campaign_with_access(row.campaign_id)` (e.g. `npcs.py:23-31 _get_accessible_npc`).

**Share tokens and members, for the player portal (feature 7):**
- Two token kinds, string not enum (`share_token.py:16-18`). `read_only` gives anonymous read of **everything**: journals (incl. GM shorthand), NPC notes, quests. `collaborate` gives a `CampaignMember` row on join, with full write access identical to the owner except management.
- `CampaignMember` has **no role column**, so "player vs co-GM" does not exist. Revocation sets `revoked=True` (soft). There is no expiry.
- Feature 7 needs: a `role` on `campaign_members` (e.g. `co_gm|player`) with a migration default for existing rows; a visibility flag (`gm_only`/`secret`) on entities, entries and possibly fields; a filtered read path (extend `share.py` or a new `/api/portal`); and player-owned journals (JournalEntry already has `user_id` as author; add a visibility column). Every list query in npcs/quests/journals/tags/chat retrieval must apply the filter. **The RAG retrieval (`hybrid_search_journal` with `campaign_id`) would leak secrets to players unless it is filtered too.**

Frontend share pages: `pages/SharedCampaignPage.tsx` (`/shared/:token`), `pages/JoinCampaignPage.tsx` (`/join/:token`), `pages/SharingPage.tsx` (owner management), hook `hooks/useSharing.ts`.

---

## 5. Frontend

**Stack:** React 18 + Vite 5 + TS (strict, noUnusedLocals/Parameters) + Tailwind 3 + shadcn-style primitives + `@tanstack/react-query` v5 + axios + react-router-dom v6 + lucide-react + vite-plugin-pwa (`package.json`). No state library, no form library, no chart or graph library, no test runner, no ESLint or Prettier scripts. Build: `tsc && vite build`.

**Routing** (`App.tsx`): `BrowserRouter` with `ThemeProvider` › `QueryClientProvider` (staleTime 30s, retry 1, `:53-55`) › `TourProvider`. Core pages are eagerly imported (Home, Login, Register, Dashboard, History). Everything else uses `lazy(() => import(...).then(m => ({ default: m.XPage })))` because **pages use named exports** (`:28-51`). `PrivateRoute` only checks `localStorage.lk_token` (`:57-60`). Routes are at `:84-110`. To add a page: lazy import, add a `<Route>`, then add a link to `NAV_GROUPS` in `components/NavBar.tsx:11-38` (groups Chronicle / Campaign / Collaborate, plus Admin).

**Data fetching:**
- `services/api.ts`: one axios instance (`baseURL = VITE_API_URL ?? ""`) with a bearer interceptor from `localStorage.lk_token`. On 401 it clears the token and redirects to `/login`. On 402 it routes by `x-gate-reason` (`:17-44`). It contains ~100 thin exported functions (`export const getNpcs = (campaign_id) => api.get(...)`). Blob downloads (`exportCampaign`, `:83`) and multipart uploads (`transcribeVoice :309`, `uploadSource :324`) live here.
- `hooks/useX.ts`: one file per domain wrapping react-query. Pattern (`hooks/useNpcs.ts`): `useQuery({ queryKey: ["npcs", campaign_id], queryFn, enabled: !!campaign_id })`, mutations `invalidateQueries({ queryKey: [...] })` on success. Query keys are plain arrays `[domain, id]`.
- Streaming bypasses axios: `hooks/useChat.ts` uses raw `fetch("/api/chat/stream")` with the token header and a manual SSE parser.
- Offline: `lib/offlineQueue.ts` + `hooks/useOfflineQueue.ts` queue journal notes for later one-step `/generate` (no review).
- Types: `types/index.ts` (450 lines, hand-maintained mirror of the pydantic schemas). Errors: `utils/apiError.ts` `apiErrorMessage(err)`.

**State / contexts:** `contexts/ThemeContext.tsx` (theme id + custom themes in localStorage, applies CSS vars `--background` … `--ring`, `--radius`, `--font-heading`, `--font-body` to `:root`). `contexts/TourContext.tsx` drives onboarding (`components/TourOverlay.tsx`). The selected campaign is per-page local state through `components/CampaignSelector.tsx` + `hooks/useCampaigns.ts`, with no global "current campaign" context.

**UI kit:** `components/ui/` has only `badge`, `button`, `card`, `input`, `textarea` (cva + `lib/utils.ts` `cn`). Most UI is hand-written Tailwind using theme tokens (`bg-card`, `border-border`, `text-muted-foreground`, `bg-primary/5`). Six themes in `themes/` (dnd = default, arcane, highseas, forest, cyberpunk, light), typed by `types/theme.ts`. No modal or dialog primitive except `SlideOver`. Shared: `PageHeader`, `ErrorBoundary`, `ModelReadyBanner`.

**Approve-before-save, `components/NarrativeReviewPanel.tsx`:** a stateless, controlled single-textarea panel. Props are `narrative`, `onChange`, `onSave`, `onDiscard`, `onRegenerate?`, `saving`, `regenerating?`, `title`, `saveLabel`, `rows`, optional `itemTitle`/`onItemTitleChange`, and `error` (`:1-23`). It shows "Edit freely — nothing's saved yet". Used by `JournalInput.tsx`, `SessionPlansPage.tsx` and `RecordSessionPage.tsx`. The backend contract it pairs with is a **draft endpoint that never persists** (`/generate-draft`, `/session-plans/generate`), then a separate save POST. **For feature 1's entity diffs it is a pattern, not a drop-in.** It edits one free-text blob, so a new `EntityDiffReviewPanel` must keep the same look, copy and contract (draft, then per-change accept/reject/edit, then commit) and render a list of typed changes.

**Detail panel pattern:** `components/SlideOver.tsx` (right drawer, `md:max-w-lg`, Esc and backdrop close, `role="dialog"`). `components/NpcDetailPanel.tsx` / `QuestDetailPanel.tsx` copy server data into local `useState` on `npc.id` change, save via the mutation, show "AI generate" (bio) and list related entries via `useNpcEntries` (ILIKE). New Location/Faction/Item panels should clone `NpcDetailPanel`.

**Charts:** `pages/AnalyticsPage.tsx` has the `StatTile`, `WeeklyBarChart` (flex divs with % heights and hover) and `TagRankList` (horizontal bars) components, with no library. They consume `CampaignAnalytics` from `hooks/useAnalytics.ts`.

**Audio capture:** `pages/RecordSessionPage.tsx` uses `getUserMedia({audio:true})` once (`:81`), then a chain of `MediaRecorder`s restarted every 30s. Each stop builds a `Blob(audio/webm)` and calls `transcribeVoice`, and segment status (`recording/transcribing/done/error`) is shown per chunk (`:14-19,55-77`). When finished, the concatenated transcript goes to `summarizeSession` → shorthand notes → `NarrativeReviewPanel` → journal save. `components/JournalInput.tsx:336-479` has a simpler single-shot recorder. No AudioWorklet, VAD or PCM capture.

**Timeline:** `pages/TimelinePage.tsx` fetches up to 100 entries (`useJournals({limit:100})`, `:138`) and sorts by `session_date ?? created_at` client-side. It shows entries only, no entities or events.

---

## 6. Existing features to extend, per planned feature

| # | What exists today |
|---|---|
| 1 Living world | spaCy NER tags on save (`journal_service.py:84-107`); `/api/npcs/extract` name suggestions; NPC/Quest CRUD with status enums; draft→review→save UX + `NarrativeReviewPanel`; `TagType` already names location/faction/item (tags only); `NpcRole.faction` overloads factions into NPCs (migration and backfill decision needed). |
| 2 Canon guard | `hybrid_search_journal` + 0.65 gate + trace; canon prompt blocks ("treat as authoritative / do not contradict", `ai_service.py:60-66`); `NpcStatus.dead`; `grounded`/"not from your journal" labelling; the eval harness. Nothing compares claims. |
| 3 Relationship web | No relationship table. Only implicit co-occurrence via `journal_tags` (tags shared across entries). Needs an entity-relationship model (depends on 1) and a graph library. |
| 4 Live session | 30s segment recorder + batch Whisper + `summarize-session` + SSE chat streaming infrastructure; `rewrite_search_query`. Missing: incremental STT, rolling recap state, quick entity lookup (could reuse `hybrid_search_journal` or ILIKE on npcs). |
| 5 Narrated recaps | `generate_session_recap` (`chat_service.py:249`, `POST /api/journals/recap` `:253`; frontend `api.generateRecap :211`); `GENRE_SYSTEM` voices; browser `useNarration`. No server TTS or audio storage. |
| 6 Talk to an NPC | Chat pipeline (`_prepare_chat`, `build_chat_messages`, SSE stream, `ChatSession` JSONB). `generate_npc_bio` shows how NPC context is built (ILIKE entries). Knowledge constraint needs entity-mention links (1) to restrict retrieval to entries the NPC appears in or witnessed. `ChatSession` has no `npc_id`. |
| 7 Player portal | Share tokens (read_only/collaborate), `CampaignMember`, `is_owner` on the campaign list, `SharedCampaignPage`, `get_campaign_with_access`. No roles, no visibility flags (see §4). |
| 8 Chronicle export | `app/services/export_service.py` (67 lines): `build_campaign_markdown`, `build_campaign_pdf` with fpdf2 **core Helvetica, Latin-1 sanitized via `_s()`** (non-Latin text becomes `?`), one page per entry, no TOC, chapters, cover, entities or images. No EPUB library in `requirements.txt`. The route is owner-only and author-only (§0). It returns bytes synchronously. |
| 9 Milestones & stats | `GET /campaigns/{id}/analytics` → `CampaignAnalytics{total_entries, avg_entry_length, entries_per_week, top_characters, top_quests}` (`schemas/campaign.py:62-67`), owner/author-scoped, tag-based "mentions". No streaks, quest completion rates or achievements. `Quest.status` + `updated_at` exist (no `completed_at`). |
| 10 Map pins | Nothing. No image storage and no Location entity. Upload patterns to copy: `UploadFile` + size/type checks (`ingest.py`, `sources.py`), Pillow already a dependency (avatar resize, `auth.py:163-187`). |

---

## 7. Tests

- Backend: `src/backend/tests/` holds `conftest.py`, `test_auth.py` (5 tests: register/login, duplicate, lockout, reset invalidates tokens), `test_journals.py` (2: auth required → 403, cross-user isolation), `test_nlp.py` (3: spaCy person/location/dedup). **10 tests total.** Services, retrieval, chat, sharing and permissions are not covered.
- Fixtures (`tests/conftest.py`): hardcoded `TEST_DB_URL = postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test` (`:13`, no env override). A session-scoped autouse fixture runs `CREATE EXTENSION vector` + `Base.metadata.drop_all/create_all` (**the schema comes from models, not Alembic**, so migrations themselves are untested). Other fixtures: `db` (fresh engine per test, rollback at end), `client` (httpx `AsyncClient(ASGITransport(app))`, `limiter.reset()`, overrides `get_db`), `promo_code` (creates `TESTCODE` so registered users get `access_granted`).
- Gotcha: `ASGITransport` does not run the FastAPI lifespan, so Redis, spaCy and MiniLM are **not initialized** in route tests. Anything calling `get_redis()`/`extract_tags`/`embed` (e.g. `POST /api/journals/generate`) will raise unless it is mocked or the loaders are called in a fixture. LLM calls need mocking (no fake provider exists).
- Config: `pytest.ini` has `asyncio_mode = auto`, function loop scope. Dev deps: pytest 8.3, pytest-asyncio 0.24, httpx, factory-boy (unused).
- Run: start a pgvector PG with that DB (`docker compose -f docker-compose.dev.yml up -d postgres` and create `lorekeeper_test`, or match CI), then `cd src/backend && DATABASE_URL=… POSTGRES_PASSWORD=changeme SECRET_KEY=x python -m pytest -v` (`python -m spacy download en_core_web_trf` is needed for test_nlp). CI is `.github/workflows/backend-tests.yml` (py3.11, PG service), but it triggers on `master` (§0).
- Frontend: **no tests and no test runner.** `npm run build` (tsc strict) is the only check.

---

## 8. Conventions and pitfalls

- **Code style:** long explanatory "why" comments everywhere, often citing measurements ("confirmed live", "measured"). Keep this voice. Python uses SQLAlchemy 2.0 typed `Mapped[]`/`mapped_column`, async sessions, `select()` style, and explicit `await db.commit(); await db.refresh(obj)` in routes. Pydantic v2 schemas live in `app/schemas/<domain>.py` with `model_config = {"from_attributes": True}`. Services are module-level functions (no classes or DI), and routes import them directly. Lazy imports inside functions are common to dodge cycles.
- **Error handling:** routes raise `HTTPException` (404 for not-found or no-access, 409 duplicate, 413/415 upload, 422 empty or unusable input, 402 gates, 503 model unavailable). Auxiliary AI or RAG steps are wrapped in `try/except Exception: pass` with a "must not block X" comment (`journal_service.py:36-55`, `chat.py` throughout). Admin/diagnostic services return error dicts instead of raising (`ollama_service`). Frontend shows `apiErrorMessage(err)`.
- **Logging:** `logger = logging.getLogger(__name__)`. JSON lines to stdout, ring buffer and optional `LOG_FILE` (read by the admin System tab). Not consistently used in routes; many failures are swallowed silently.
- **Rate limiting is two layers.** Add slowapi `@limiter.limit(...)` (which requires a `request: Request` param) **and** an nginx `location =` block for AI routes.
- **Draft-then-save is a product invariant.** AI output is never persisted without an explicit user save (journals, session plans, campaign concept, NPC bio fills a form field). The offline queue is the only exception (unattended one-step generate). Feature 1 diffs must follow it.
- **Every new AI route** needs `config: LLMConfig = Depends(get_user_llm_config)` + `get_campaign_with_access` + `record_hosted_usage` when `is_hosted_default`, a timeout from `settings.kobold_timeout_seconds`, and the `GENRE` voice via `campaign.genre.value`, and must pull `get_glossary` (the docstring says every campaign generator should).
- **CPU reality:** a 7B Q4 on CPU takes minutes per long generation and about 60s to cold-load per model. `OLLAMA_MAX_LOADED_MODELS=2` is already used by finetuned + base, so a **third model (e.g. a small extraction/JSON model) will evict one** unless that env var and the 14g limit are raised. Extraction prompts should be short, and output JSON should be small.
- **Per-worker model duplication:** anything loaded at import or in the lifespan costs ×4 RAM. `embed()` and `extract_tags()` block the event loop (synchronous CPU). For heavy new work, prefer a separate worker container.
- **Fragile spots:** `entry_hash` is globally unique and Redis dedup TTL is 24h (client computes the hash, `utils/hashNotes.ts`). `narrative_tsv` is updated manually, so any new write path to journal text must update it and the embedding. `JournalEntry` has no edit endpoint. Tags are global. `ai_service` tries the Kobold-native path first on Ollama. Prod migrations run on boot (a broken migration means a crash-looping backend). The 12000-char transcript truncation in `summarize_session_transcript` means long sessions lose content (relevant for feature 4's rolling recap). Several `EMBEDDING_DIM` copies. Hand-typed revision ids. `AppConfig` is imported after `__all__`. The fpdf Latin-1 limit.
- **Frontend:** named exports for pages, `lazy` adapter, Tailwind theme tokens (never hardcoded colors, since six themes exist), `style={{ fontFamily: "var(--font-heading)" }}` for headings, mobile-first (`md:` breakpoints), react-query keys `[domain, campaignId]`. No global campaign context.

---

## 9. Extension points (feature → files/modules)

1. **Living world / auto-extraction**
   - New models: `app/db/models/{location,faction,item}.py` (or a unified `entity.py` with a type enum), `entity_mention.py` (entity_id/type, journal_id, span/quote, confidence), `entity_change_proposal.py` (pending diff rows: op, target, field, old/new, source journal_id, status). Register them in `models/__init__.py` and `migrations/env.py`, and add a migration after `a3e7c1f9d258`.
   - Decide how `NpcRole.faction` rows migrate into Faction, and how global `Tag`s relate to new entities.
   - New `app/services/extraction_service.py` (LLM structured prompt plus a JSON parse/repair layer; may seed candidates from `nlp_service.extract_tags`). Extend `llm_provider.complete_messages` with an optional `response_format`/`format="json"`. Hook it after `journal_service.create_journal_entry` (as a job, or a draft endpoint like `POST /api/journals/{id}/propose-changes`) and add routes `api/routes/entities.py` (CRUD, mentions) + `api/routes/proposals.py` (list/accept/reject/edit).
   - Frontend: `hooks/useEntities.ts`, `hooks/useProposals.ts`, a new `components/EntityDiffReviewPanel.tsx` (styled like `NarrativeReviewPanel`), entity pages/panels cloned from `CharactersPage` + `NpcDetailPanel`, and NavBar "Campaign" group links. Wire it into `JournalInput.tsx` after save.
   - Eval: a new `docs/EXTRACTION_EVAL.md` + `scripts/eval_extraction.py` measuring precision/recall of proposed changes on the demo campaign.
2. **Canon guard**: new `app/services/continuity_service.py` that retrieves via `retrieval_service.hybrid_search_journal` + entity state (status=dead, location), then runs an LLM claim check. Call it from `journal_service.generate_draft_narrative` or a `POST /api/journals/check-continuity` route, return conflicts with cited entry ids (reuse the `JournalSource`/`RetrievalCandidate` schemas in `app/schemas/chat.py`), and add an nginx `ai_gen` location. Frontend: a warning list inside `JournalInput.tsx`'s review step. Eval: seeded contradiction set, metric = flag precision/recall + false-alarm rate (in RETRIEVAL_EVAL style).
3. **Relationship web**: model `entity_relationship.py` (source, target, type, since_entry_id, gm_only). Proposals come from feature 1's extraction. Route `GET /api/campaigns/{id}/graph` (in `campaigns.py` or `entities.py`). Frontend: new `pages/RelationshipWebPage.tsx` + a graph library dependency in `package.json`, opening nodes in `SlideOver` panels.
4. **Live session mode**: STT engine choice (faster-whisper / whisper.cpp streaming in a **new container**, or keep 30s chunks with a smaller window and overlap). New `api/routes/live.py` (chunk POST, or WebSocket, which needs an nginx upgrade location in `locations.conf`). A rolling recap service (incremental summarization in `chat_service`, state in Redis or a `live_sessions` table). Quick lookup = `npcs`/entities name search + `hybrid_search_journal`. Frontend: extend `pages/RecordSessionPage.tsx` (segment recorder) or a new `pages/LiveSessionPage.tsx`, plus an SSE consumer modelled on `hooks/useChat.ts`.
5. **Narrated recaps**: new TTS container (e.g. Piper HTTP) in `docker-compose.prod.yml` + `.env`/`config.py` URL setting. New `app/services/tts_service.py`. Extend `chat_service.generate_session_recap` with genre-voice prompts (`ai_service.GENRE_SYSTEM`). New route (e.g. `POST /api/journals/recap/narrate`) returning audio (stream or stored file; needs storage). nginx `ai_gen` location. Frontend: a recap player that falls back to `hooks/useNarration.ts`.
6. **Talk to an NPC**: extend `ChatSession` with `npc_id` (migration) or add a new model. Add `build_npc_chat_messages` in `chat_service.py` with a persona from the NPC row and retrieval restricted to entries mentioning the NPC (entity_mention from 1) through a filter argument added to `hybrid_search_journal`. Routes as a variant of `chat.py` `_prepare_chat`/`/stream`. Frontend: an NPC chat mode in `pages/ChatPage.tsx`/`hooks/useChat.ts`, launched from `NpcDetailPanel`. Eval: an "out-of-knowledge refusal" rate, like gate-holds.
7. **Player portal**: migrations adding `campaign_members.role` and `gm_only`/`visibility` on journal_entries, npcs, quests, new entities and (for fields) a JSONB `secret_fields` list. Extend `api/deps.py` with a role-aware helper (e.g. `get_campaign_role`) and a visibility filter used in **every** list/get in `journals.py`, `npcs.py`, `quests.py`, `tags.py`, `share.py`, entity routes, and in `retrieval_service.hybrid_search_journal` + `source_service.retrieve_canon_context`. Add player journals as an entry visibility value plus author scope. Frontend: a portal route/page (extend `SharedCampaignPage.tsx` or a new `pages/PortalPage.tsx`), role management in `SharingPage.tsx`, GM-only toggles in the detail panels, and an `is_owner`/role-aware NavBar.
8. **Chronicle export**: extend `app/services/export_service.py` (add a Unicode TTF font to fpdf2 so text is not Latin-1-sanitized, a cover page, TOC, chapters by session, entity appendix) + an EPUB builder (new dependency, e.g. `ebooklib`, in `requirements.txt`). Extend `campaigns.py:119` with `format=epub`, switch it to `get_campaign_with_access` and all authors, and consider a job for large campaigns. Frontend: the `api.exportCampaign` format union (`services/api.ts:83`) and the export UI.
9. **Milestones & stats**: extend `campaigns.py:158` analytics (streaks from `session_date` weeks, entity-mention counts from 1 instead of global tags, quest completion rates from `Quest.status`; consider a `completed_at` column), extend the `CampaignAnalytics` schema (`app/schemas/campaign.py:62`) + `types/index.ts`, and add an achievements service (computed on read, or a `campaign_achievements` table). Frontend: `pages/AnalyticsPage.tsx` (reuse `StatTile`/`TagRankList`; a chart library is optional).
10. **Map pins**: new models `map.py` (campaign_id, title, image storage ref, width/height) + `map_pin.py` (map_id, x/y normalized, location_id from 1, journal_id?, label, gm_only). Storage: a new named volume mounted into backend (e.g. `/data/uploads`) + a serving route, or a Postgres `bytea`. Use Pillow for size checks and thumbnails (pattern in `auth.py:163-187`). Routes in `api/routes/maps.py` (multipart upload as in `sources.py:48`). Frontend: `pages/MapsPage.tsx` (image + absolutely-positioned pins, click opens the Location `SlideOver`), `hooks/useMaps.ts`, and multipart helpers in `services/api.ts`.
