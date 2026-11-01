# Epic 3 Context: Runs offline on one 16 GB box with models outside the web tier

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

A self-hoster brings up the whole Lorekeeper stack with one `docker compose up`, fully offline, on a 16 GB CPU-only box (GPU optional and speed-only). Today the four gunicorn web workers each load spaCy `en_core_web_trf`, MiniLM and (lazily) Whisper/EasyOCR in-process, which costs about 6.4 GB idle and 11.9 GB peak, blocks the event loop and contradicts the README baseline. This epic moves all inference into dedicated `ml` and `stt` sidecars behind async clients, strips model packages from the web/worker image, sets one memory-limited compose profile, keys AI rate limits per user, ships multi-arch images with an upgrade-safe boot, and confirms the limits by measurement on x86. Later epics (continuity NLI, Live Session STT, narrated recaps, jobs) build on these sidecars and the memory budget.

## Stories

- Story 3.1: Dev compose ports bind to localhost by default
- Story 3.2: CPU-only torch in the backend image (closes the NVIDIA wheel licence gap)
- Story 3.3: `ml` sidecar for embeddings and NER, with its client
- Story 3.4: `ml` lazy NLI and OCR under a resident-memory budget
- Story 3.5: `stt` sidecar with faster-whisper, and voice upload switched to it
- Story 3.6: Web and worker image without models: async client wrappers and lifespan cleanup
- Story 3.7: One 16 GB profile with container limits, GPU override and sum check
- Story 3.8: Per-user rate-limit keying in slowapi and nginx
- Story 3.9: Multi-arch images, upgrade-safe boot and OCI deploy
- Story 3.10: SPIKE-5 and SPIKE-6 re-run on the remote x86 desktop, limits confirmed

## Requirements & Constraints

- **Offline and local:** every feature works with no internet after install; no new outbound calls except opt-in BYOK and model install; all weights installable offline; one `docker compose up` brings up everything. Remote access is LAN or self-run (e.g. Tailscale) through the HTTPS front end.
- **No data exposure:** dev compose must never publish Postgres/Redis/backend/Vite to the LAN by default (bind `${BIND_IP:-127.0.0.1}`; warn against `0.0.0.0`). Prod publishes only nginx 80/443.
- **Reference Box = 16 GB, CPU-only, one profile.** Sum of all container limits ≤ 14.5 GB (≥ 1.5 GB for OS/Docker). Peak RSS must fit for three cases: idle; one heavy Job (NLI batch + 7B completion); Live Session (STT continuous + Rolling Recap every 60 s). No feature may fail for lack of a GPU.
- **Model isolation:** embeddings, NER, NLI, OCR, STT (and later TTS, diarization) never run inside web workers. During a Live Session STT is the only newly resident model; exactly one loaded LLM (the bundled 7B).
- **Licences:** every new dependency, image, weight and apt package is distributable under AGPL and the commercial licence and is added to the licence register in the same PR. Image must contain no NVIDIA-proprietary wheels (CPU torch only; GPU STT target is local-only, never published). TTS image only in the AGPL edition.
- **Brownfield consistency:** existing behaviour is preserved (journal save never blocks on AI failure; voice upload keeps 25 MB cap, 422-on-empty, rate limits; retrieval eval stays at hybrid@0.65 = 14/16 hit@3, 5/5 gate-holds; embeddings ≥ 0.9999 cosine to old output so no re-embed). AI/streaming routes get slowapi and nginx limits keyed per user, not per IP. Migrations are forward-only and safe at boot.
- Measured results inform but do not change NFR-6 performance targets; any reset is flagged for owner sign-off.

## Technical Decisions

- **Layering (AD-1):** all inference goes through `app/clients/*` (async httpx, timeouts from settings) or `llm_provider`. `nlp_service`, `embedding_service`, `transcription_service`, `vision_service` become `async def` wrappers; every caller is updated in the same PR. `main.py` lifespan loads no models (only `init_redis()`); boot to healthy < 10 s without sidecars. CI check fails if web/worker requirements or image contain torch, spaCy, sentence-transformers, whisper, faster-whisper, easyocr, onnxruntime, kokoro or any TTS package.
- **Sidecar contracts (AD-6):** sidecars live on the internal compose network only, no `ports:`, no nginx route. Weights baked at build; run with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; CI starts each image with `--network none` and checks health (`scripts/sidecar_smoke.sh`). `ml` and `stt` serve `/healthz` and `/v1/status` (loaded models, RSS), surfaced read-only in the admin System tab.
  - `ml`: `POST /v1/embed {texts}` → `{model, dim:384, vectors}` (normalized all-MiniLM-L6-v2); `POST /v1/ner {text}` → `{ents:[{text,label,start,end}]}` (spaCy labels plus existing Matcher item/quest labels); `POST /v1/nli {pairs}` → `{scores:[{entailment,neutral,contradiction}]}` batched 32, input order; `POST /v1/ocr` multipart → `{text}`. Embeddings+NER resident at boot; NLI (`nli-deberta-v3-xsmall`) and EasyOCR lazy under LRU `ML_RESIDENT_BUDGET_MB=2000`; evict LRU lazy model, else `503 {"detail":"ml budget exceeded","code":"ml_budget"}`.
  - `stt`: faster-whisper 1.2.1 / ctranslate2 4.8.4, `base` model, `POST /v1/transcribe` multipart audio or `?format=pcm16` (16 kHz mono, converted to float32 inside) with optional `initial_prompt` → `{text, language, segments:[{start_ms,end_ms,text}], rtf}`. `STT_COMPUTE_TYPE=int8` default (`float32` override), lazy load, unload after `STT_IDLE_UNLOAD_S=600`.
- **Client errors:** sidecar down/timeout/503 raises `ModelServiceUnavailable` (`app/clients/errors.py`), which is a retried error in the job lifecycle (10 s then 60 s). In request paths, auxiliary AI failure is caught with a "must not block X" comment; the voice route returns `503 {"detail":"Speech model unavailable"}`. Deterministic fakes in `app/clients/fakes.py` (stable 384-d vectors, rule-based ents, nli/ocr/stt fakes) are selected when `ENVIRONMENT=test`.
- **Embedding contract:** `app/domain/embedding.py` (`EMBEDDING_MODEL`, `EMBEDDING_DIM = 384`) is the single definition; all existing copies import it. Changing it requires a re-embed backfill and a retrieval-eval rerun.
- **Config:** new settings in `app/core/config.py` (`ml_url`, `ml_timeout_s`, `stt_url`, `stt_compute_type`); sizing in `.env.example`.
- **Memory table (AD-7), `.env.example` `*_MEM_LIMIT` → `deploy.resources.limits.memory`:** ollama 5.25g (`OLLAMA_MAX_LOADED_MODELS=1`, `NUM_PARALLEL=1`, `CONTEXT_LENGTH=4096`, `KEEP_ALIVE=30m`); ml 2.5g; tts 2.5g (reserved, AGPL `tts` profile); stt 1.25g; web 1g (gunicorn `-w 4`); worker 1g (reserved); postgres 768m (`shared_buffers=192MB`); redis 128m (`--maxmemory 96mb --maxmemory-policy noeviction`); nginx 128m. Sum = 14.5 GB exactly. Raising a limit requires lowering another in the same PR and re-running EV-5. `diarize` profile is excluded from the sum. `scripts/check_mem_limits.py` enforces sum and per-service limit presence.
- **GPU:** `docker-compose.gpu.yml` adds device reservations to `ollama` and `stt` (local `gpu` build target) only. Native host Ollama is supported via `KOBOLD_URL=http://host.docker.internal:11434` + `extra_hosts: host-gateway`; its 5.25g reserve still counts.
- **Rate limiting (AD-20):** `core/limiter.py` exports `user_or_ip(request)` → `user:<sub>` from a signature-checked bearer JWT (no DB call), else remote address; unauthenticated routes keep `get_remote_address`. nginx `ai_gen` zone keys on `map $http_authorization $lk_rate_key` (bearer hash, fallback `$binary_remote_addr`); `api`/`auth` zones unchanged. `locations.conf` template shows anchored regex locations for AI routes with ids, generic-zone streaming with `proxy_buffering off`, and `/_files/` internal. Never log the bearer or its hash.
- **Deployment:** all images multi-arch `linux/amd64,linux/arm64` via `docker-bake.hcl` (targets `web` [also worker], `ml`, `stt`, `nginx`; `stt` gpu excluded) and a new `.github/workflows/images.yml` on every PR and `main`, no path filter. Web boot runs `pg_dump` to the `backups` volume (timestamp + Alembic revision) before `alembic upgrade head`; dump failure aborts with non-zero exit. Rollback = restore dump (`scripts/restore-db.sh`) + redeploy previous tag. `scripts/deploy-oci.sh` targets the arm64 OCI Ampere A1 host with the same profile and refuses `COMPOSE_PROFILES=tts` when `LOREKEEPER_EDITION=commercial`.
- **Stack:** Python 3.11 for web/worker/ml/stt; torch from the PyTorch CPU index (`torch==<ver>+cpu`) on amd64; sentence-transformers 5.5.1; spaCy 3.8.18.
- **Ownership boundaries:** this epic owns `app/clients/*`, `src/services/ml`, `src/services/stt`, compose files, `.env.example` limits, `docker-compose.gpu.yml`, buildx, `deploy-oci.sh`, `domain/embedding.py`, `core/limiter.py`, nginx `ai_gen` keying. It owns no tables. E0-QA owns CI workflows, `tests/conftest.py` and import-linter config: provide scripts and make code pass, but do not edit those workflows here. Feature epics append their own `locations.conf` lines.

## Cross-Story Dependencies

- 3.1, 3.2 and 3.8 have no dependencies. 3.3 depends on 3.2 (CPU-index pattern); 3.4 and 3.5 depend on 3.3 (client error types, fake pattern, smoke script); 3.6 depends on 3.3, 3.4, 3.5 and supersedes 3.2's interim torch for web/worker; 3.7 depends on 3.6; 3.9 depends on 3.7; 3.10 depends on 3.4, 3.5, 3.7.
- External: installing the `lorekeeper` model into containerised Ollama relies on the `fix/hf-model-install` branch (soft dependency for 3.7 and 3.10; do not re-specify it). 3.10 soft-depends on E0-QA's EV-5 format (fallback to the RETRIEVAL_EVAL format) and uses E0-QA's `TEST_DATABASE_URL` override with 3.1's `BIND_IP` for remote dev over Tailscale.
- Downstream consumers: E0-QA wires `check_model_packages.py`, `check_mem_limits.py` and the sidecar smoke into CI and switches fakes on in conftest; E0-Jobs adds the `worker` service (starting after `web` healthy) and job counts in the admin System tab; E0-Journal owns the `journal.reembed` fallback; E0-LLM owns prompt budgets and production benchmark wiring; E2 consumes `ml` NLI (any `-base` swap must keep the 2.5g limit); E4 uses the `stt` PCM16 path and defines the `diarize` profile; E5 adds the `tts` service under the reserved limit.
