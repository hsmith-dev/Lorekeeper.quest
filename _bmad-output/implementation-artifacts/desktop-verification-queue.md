---
title: Desktop verification queue
purpose: Checks that GitHub CI cannot run (real Docker host, live Ollama/GPU, nginx in front, benchmarks). Run these on the RTX test box when it is back, then tick them off.
---

# Desktop verification queue

Stories were merged on green GitHub CI while the desktop was offline (owner decision 2026-11-01: "keep building without testing, we will test later"). Each entry lists the exact checks; full detail is in the story's spec under `_bmad-output/implementation-artifacts/`.

## E0-Platform.2 — CPU-only torch in the backend image (PR #20)
- [ ] `docker build -f src/backend/Dockerfile.prod -t lk-backend-cpu src/backend` and the same with `-f src/backend/Dockerfile` (build guard must pass)
- [ ] `docker run --rm lk-backend-cpu pip list | grep -iE 'nvidia|cuda'` prints nothing; `python -c "import torch; assert not torch.cuda.is_available()"` passes
- [ ] In-image: `LOREKEEPER_EDITION=commercial` and `agpl` → `scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact backend` = 0 violations
- [ ] `docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod src/backend` succeeds
- [ ] Image size vs a `main` build before this change (record in PR #20)
- [ ] Backend suite + `/api/health`, journal save, retrieval, `test_nlp.py` against the new image

## E0-QA.5 — Tests build the schema from Alembic migrations (PR #21)
- [ ] Run the suite on a lane DB that still has tables from the old `create_all` era (`-e TEST_DATABASE_URL=… -e DATABASE_URL=<same>`); expect green and `alembic_version` = `a3e7c1f9d258` afterwards
- [ ] Known drift to decide on (reported, not fixed): duplicate unique constraint+index on `password_reset_tokens.token_hash` and `promo_codes.code`; 12 migration-only server defaults; `app_config` seeds open-access ON while the app default is OFF

## E0-QA.8 — Licence scan of the shipped images (PR #24)
- [x] ~~E0-Platform.2 amd64 `Dockerfile.prod` build + in-image scan~~ — **verified in CI** by the new `image-licenses` job: CPU torch from the CPU index, nvidia/cuda guard passed, 129 pip packages / 0 violations in both editions
- [ ] arm64: `docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod -t lk-backend-arm src/backend --load`, then the scan from `docs/LICENSING.md` (expect a few new Debian register entries)
- [ ] Regression check: in-image scan with `--artifact backend` against the old CUDA `lorekeeper-backend-test` image → exit 1 listing the NVIDIA wheels; with `--artifact ml-gpu` → pending warnings
- [ ] Stack: `docker compose -f docker-compose.prod.yml up -d --build`, `/api/health`, spaCy `en_core_web_trf` loads
- [ ] Dev image `docker build -f src/backend/Dockerfile src/backend` (not shipped, so not in CI)
- [ ] **Owner action before publishing any built image:** meet the GPL source obligation for OS packages (ship source or a written offer) — see `docs/LICENSING.md`

## E0-LLM.2 — LLM priority gate and one fixed local model (PR #23)
- [ ] Priority under real load (Redis/Valkey + Ollama up): hold a `job_backfill` call while `gm_interactive` and `live_recap` queue → `live_recap` is served first (watch `llm_gate.snapshot()` and `llm_gate_granted` logs)
- [ ] Record `waited_ms` from `llm_gate_granted` when a request waits behind a background Job (SPIKE-6 measurement itself is E0-Platform.10)
- [ ] Disconnect frees the slot: drop an SSE chat client mid-stream → `ZCARD llm_gate:holders` is 0 within ~1 s
- [ ] Known open items: no hard cap on slot hold time (a leaked Slot renews forever); short helper calls (autocomplete, query rewrite) can wait the full 60 s gate timeout

## E0-Platform.3 — `ml` sidecar for embeddings and NER (PR #27)
- [x] ~~Image build + in-image licence scan (amd64)~~ — covered in CI by the `image-licenses (ml)` matrix leg added in PR #27
- [ ] arm64: `docker buildx build --platform linux/arm64 src/services/ml`
- [ ] Offline health: `scripts/sidecar_smoke.sh ml` → `ml: healthy`
- [ ] `docker compose -f docker-compose.prod.yml up -d ml` → healthy, no host port; backend reaches `http://ml:8000/v1/status`
- [ ] Embedding parity on the 9 demo narratives: sidecar `/v1/embed` vs in-process `embedding_service.embed`, cosine ≥ 0.9999; `ML_REAL_MODELS=1 pytest src/services/ml/tests` inside the image
- [ ] NER parity: sidecar spaCy 3.8.0 `/v1/ner` → tags vs backend `nlp_service.extract_tags` (3.7.x) on the same narratives
- [ ] Memory: per-gunicorn-worker RSS vs the `ml` container (`docker stats`, `/v1/status` `rss_bytes`)

## E0-LLM.3 — Backend detection and prompt budgets (PR #28)
- [ ] Budget estimate ≥ real usage: send `fit`-built prompts (prose, transcript, entity list) to `lorekeeper` via `POST /api/chat` (`stream:false`); `estimate_messages(messages)` must be ≥ `prompt_eval_count`. Confirm the real context window (`ollama ps` / `POST /api/show`) with `OLLAMA_CONTEXT_LENGTH=4096` on the server
- [ ] Detection: `detect_backend('http://100.119.62.5:11434')` → `ollama`; an OpenAI-compatible BYOK endpoint (KoboldCpp / llama.cpp server) → `openai_compat`; note what KoboldCpp's Ollama emulation returns
- [ ] Known gap: compose `ollama` doesn't set `OLLAMA_CONTEXT_LENGTH` yet (E0-Platform.7)

## E0-QA.12 — Demo seed and shared eval scaffold (PR #30)
- [ ] Scaffold smoke vs desktop Ollama: `cd src/backend && python scripts/eval_common.py --database-url <url> --llm-url http://100.119.62.5:11434 --llm-model lorekeeper` → 4 windows, all `ok yes`
- [ ] Seed a real DB twice: `python scripts/seed_demo.py --database-url <url> --embeddings require` → second run `created 0`, same Campaign id; also under `docker compose run --network none`
- [ ] **Capstone-relevant:** re-measure retrieval on the rebuilt seed: `python scripts/eval_retrieval.py --database-url <url> --campaign-id <id> --embeddings require --out docs/RETRIEVAL_EVAL.md`. Target hybrid@0.65 = 14/16 ±1 hit@3 and **5/5 gate-holds**. Local Mac run got 4/5 (the off-topic "queen of the elven court?" passes the gate via rebuilt entry e09 "Sunless Throne"). If confirmed: re-publish the doc's numbers or reword e09. (The original 9 demo entries were never committed; the seed was rebuilt to match the eval's phrases.)

## E0-UX.8 — Nav restructure, redirects, not-found, route announce (PR #31)
- [ ] UI pass with `npm run dev` + one owned and one joined campaign: open `/analytics`, `/record?x=1`, `/nope`, and `/sources` with the joined campaign selected; check the route announcement with VoiceOver

## E0-LLM.4 — `complete_structured`: schema enforcement + ≤2 repairs (PR #32)
- [ ] Real structured output on `lorekeeper`: from the cached backend image with host networking, `OLLAMA_TEST_URL=http://100.119.62.5:11434 OLLAMA_TEST_MODEL=lorekeeper python -m pytest -m ollama -s tests/integration/test_llm_structured_ollama.py` (+ `TEST_DATABASE_URL`/`DATABASE_URL`). 50 calls over 3 flat schemas; reports first-try / after-repair / failed rates and latency; expects ≥95% valid. Pass ~20 `seeds/demo_campaign.json` paragraphs via `OLLAMA_TEST_PARAGRAPHS=<file>` (JSON list of strings). Record as the FR-3 row in `docs/BENCHMARKS.md` with the Ollama version
- [ ] Same with `OLLAMA_TEST_MODEL=lorekeeper-base` (set `LOCAL_LLM_MODEL` or a different `KOBOLD_URL`, otherwise the test skips)
- [ ] Grep `structured_attempt` log lines with `valid:false` for recurring error locations (= schema features Ollama silently ignores)
- [ ] Note: the E1 relationship fields (`source,target,kind`) in the integration schema are a placeholder until E1.1 fixes the extraction schema

## E0-QA.11 — EV-4 harness scaffolding (PR #34)
- [ ] Sync the WHOLE repo (the harness reads `seeds/` and `nginx/` from the root), then run the docker test command with `python -m pytest -q tests/ev4`

## E0-Platform.4 — `ml` lazy NLI + OCR under a resident-memory budget (PR #37)
- [x] ~~Real NLI + OCR model sanity~~ — exercised during the CI image build: NLI scored "Mira died in the fire" vs "Mira greeted the party" contradiction 0.998; OCR read a rendered test image exactly
- [ ] NLI on the 6 spike pairs (`spikes/cpu-benchmarks.md` §5) via `POST http://ml:8000/v1/nli`: contradiction ≥ 0.97 on Mira, black dagger, Grukk (Aldric pair is a known false positive); 50 pairs < 10 s
- [ ] OCR: `curl -F file=@sample.png http://ml:8000/v1/ocr` matches `vision_service.extract_notes_from_image` on the same file
- [ ] RSS: `/v1/status` `rss_bytes` + `docker stats ml` at boot, after first NLI, after first OCR; restart with `ML_RESIDENT_BUDGET_MB=1000`, call NLI then OCR → NLI evicted, RSS drops; tune `ML_NLI_COST_MB`/`ML_OCR_COST_MB`; peak < 2560m
- [ ] Offline: `scripts/sidecar_smoke.sh ml`, then `/v1/nli` and `/v1/ocr` in a `--network none` container
- [ ] First-call latency of NLI and OCR vs the 30 s `ML_TIMEOUT_S`
- [ ] arm64: `docker buildx build --platform linux/arm64 src/services/ml`

## E0-UX.9 — Shortcut registry, help overlay, touch targets (PR #38)
- [ ] Optional UI pass: `cd src/frontend && npm run dev`; press `?` on a page and inside an open NPC panel; type `?` in the journal (must not open help); VoiceOver over the help list

## E0-Access.1 — F1-core migration, Members → Player (PR #39)
- [x] ~~Upgrade/downgrade/upgrade on snapshot + adversarial data~~ — done by an independent data-safety review on a local Postgres16+pgvector: no row loss, chat archive only sets `archived_at`, forced mid-revision failure rolls back fully
- [ ] `pytest tests/migrations tests/test_enum_check_sync.py tests/test_share.py tests/ev4` on a lane DB
- [ ] On a COPY of a real production DB: `alembic upgrade head`, then `SELECT role, count(*) FROM campaign_members GROUP BY role` → only `player`
