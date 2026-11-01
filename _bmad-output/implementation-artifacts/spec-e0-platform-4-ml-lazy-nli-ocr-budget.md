---
title: 'E0-Platform.4: `ml` lazy NLI and OCR under a resident-memory budget'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '56a28028dbe46f881bb3e9f3bc72253051acf028'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      Resident models plus the full 2000 MB lazy budget may not fit under the 2.5g ml limit; the default declared costs (NLI 600, OCR 900) are unmeasured.
    evidence: |-
      AD-7 fixes ml at 2.5g and ML_RESIDENT_BUDGET_MB=2000; MiniLM + en_core_web_trf + torch are already resident.
      SPIKE-1 measured 844 MB peak for a whole xsmall process. Only a desktop RSS run settles it (E0-Platform.7 / .10).
    location: >-
      docker-compose.prod.yml (ml deploy.resources); src/services/ml/ml_service/config.py DEFAULT_*_COST_MB
    severity: medium (unverified)
  - summary: >-
      The first NLI/OCR call pays the model load inside the client's single 30 s ml_timeout_s.
    evidence: |-
      Cold EasyOCR/DeBERTa load on cpus 1.0 plus a large image or 256 pairs could exceed 30 s; the client then retries
      behind the still-running request. Needs desktop timing.
    location: >-
      src/backend/app/clients/ml.py; src/backend/app/core/config.py ml_timeout_s
    severity: medium (unverified)
  - summary: >-
      OCR decode has no pixel cap; a highly compressed 10 MiB PNG can decode to ~100M+ pixels outside the declared budget.
    evidence: |-
      PIL only raises DecompressionBombError above 2x MAX_IMAGE_PIXELS. Same exposure as today's in-process vision_service;
      the sidecar is internal-only and the backend route caps uploads at 10 MB.
    location: >-
      src/services/ml/ml_service/models.py (EasyOcrReader.read)
    severity: medium
  - summary: >-
      python-multipart 0.0.12 (shared pin with the backend) predates the CVE-2024-53981 fix (0.0.18).
    evidence: |-
      Pre-existing backend pin, now also in the ml image. Bump both images and the register together in a separate change.
    location: >-
      src/services/ml/requirements.txt; src/backend/requirements.txt; licenses/register.yaml
    severity: medium
  - summary: >-
      NLI/OCR are never called inside a --network none container in CI (story AC 5).
    evidence: |-
      Offline is configured (HF/TRANSFORMERS offline env, download_enabled=False, baked paths) but the CI-5 sidecar smoke
      job is not wired (E0-QA); desktop verification runs it.
    location: >-
      scripts/sidecar_smoke.sh; .github/workflows
    severity: medium
---

<intent-contract>

## Intent

**Problem:** The `ml` sidecar (E0-Platform.3) serves only embeddings and NER. Continuity checks (E2) need NLI, and image ingest needs OCR. Holding both models permanently would take memory that the Live Session needs on a 16 GB box.

**Approach:** Bake `cross-encoder/nli-deberta-v3-xsmall` (pinned revision, sha256-checked) and the EasyOCR English weights (the registered zips, sha256-checked) into the `ml` image. Serve `POST /v1/nli` and `POST /v1/ocr`, which load their models on first use. A resident-memory budget (`ML_RESIDENT_BUDGET_MB`, default 2000) sums the declared cost of each loaded lazy model. When a load would go over the budget, `ml` evicts the least-recently-used idle lazy models if that frees enough room, and otherwise answers `503 {"detail":"ml budget exceeded","code":"ml_budget"}`. Add `nli()` and `ocr()` to `app/clients/ml.py` and to the fake.

## Boundaries & Constraints

**Always:**
- Keep E0-Platform.3's rules:
  - `ml_service` never imports `app`.
  - torch, transformers, easyocr, spaCy and PIL are imported only inside the real loaders and readers. The HTTP app runs with fakes.
  - Weights are baked at build, and the container runs with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and EasyOCR `download_enabled=False`.
  - The CUDA/NVIDIA guard runs after every pip install. Torchvision comes from the CPU index (`0.29.2+cpu`, the backend's pin).
- Embeddings and NER load in the lifespan. NLI and OCR load only on their first request.
- `/healthz` depends only on the resident models.
- `/v1/status` reports every model's `state` (`not_loaded | loading | loaded | failed`), plus `lazy`, `cost_mb`, `resident_budget_mb`, `lazy_resident_mb` and `rss_bytes`.
- NLI scores in chunks of 32 (`ML_NLI_BATCH_SIZE`) and returns softmax probabilities in input order.
- OCR follows today's `vision_service._run_extraction`: PIL `convert("RGB")`, `readtext(detail=0, paragraph=True)`, then the stripped non-empty lines joined with `\n`.
- Eviction never touches a model that is serving a request.
- An evicted model drops its references, and the sidecar then runs `gc.collect()` and `malloc_trim(0)`, which is a no-op off glibc.
- Every new package and weight goes in `licenses/register.yaml` with `ml` in its `images`.

**Never:**
- Change `ML_MEM_LIMIT` (2.5g, AD-7).
- Switch `vision_service` or any other caller to the client (E0-Platform.6).
- Remove easyocr or torchvision from the backend.
- Edit workflows, `license-policy.toml`, `tests/conftest.py`, `docker-compose.dev.yml`, the frontend, `app/domain`, `llm_provider`, `sprint-status.yaml` or `epics.md`.
- Use the 7B confirmation step (E2), or add an NLI threshold.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| boot | container start | embed and NER `loaded`; NLI and OCR `not_loaded`; healthz 200 | — |
| nli | `POST /v1/nli {"pairs":[{premise,hypothesis}] x50}` | model loads; scorer called with chunks [32, 18]; `{scores:[{entailment,neutral,contradiction}] x50}` in input order, each summing to 1 | — |
| nli empty | `{"pairs":[]}` | `{scores:[]}`; model not loaded | — |
| nli bad | more than 256 pairs, a side over 4000 chars, or a missing field | 422 | pydantic |
| ocr | multipart `file` PNG | `{text}` | — |
| ocr bad | empty file, or bytes that are not an image | 422 | `InvalidImage` |
| ocr too big | more than 10 MB | 413 | — |
| evict | budget 2000; NLI (1200) resident and idle; OCR (1000) requested | NLI evicted (`not_loaded`), OCR loads, 200 | — |
| over budget | the needed room exists only by evicting a busy model, or the model's cost exceeds the budget | `503 {"detail":"ml budget exceeded","code":"ml_budget"}`; nothing evicted | — |
| load fails | loader raises | 500; slot `failed`; reservation released | — |
| client 503 ml_budget | sidecar 503 body | — | `ModelServiceUnavailable` (detail names `ml_budget`) |
| client nli | longer than 256 pairs | split into 256-pair requests; count and keys validated | `ModelServiceError` |
| client ocr | bytes | multipart `file`; returns `text` str | non-str `text` → `ModelServiceError` |

</intent-contract>

## Code Map

- `src/services/ml/ml_service/app.py`:
  - `create_app(config, embedder_factory, ner_factory)`. Add `nli_factory` and `ocr_factory`, the `BudgetExceeded`→503 and `InvalidImage`→422 handlers, and the routes.
  - Make healthz and lifespan resident-only.
  - The routes are plain `def` (threadpool).
- `src/services/ml/ml_service/models.py`:
  - `ModelSlot`: change its initial state `"unloaded"` to `"not_loaded"` and add `unload()`.
  - Add the NLI and OCR protocols, `TransformersNli` (AutoTokenizer and AutoModelForSequenceClassification, labels from `config.id2label`) and `EasyOcrReader` (with an injectable reader for tests).
- `src/services/ml/ml_service/budget.py` (new): `ResidentBudget`, `LazySlot`, `BudgetExceeded`, `release_memory()`.
- `src/services/ml/ml_service/config.py`:
  - Constants: NLI repo `cross-encoder/nli-deberta-v3-xsmall`, revision `a150876415327c80daeff35ca6f68f5ed8cf5c24`, `model.safetensors` sha256 `4e4fc4977f8d29d2a164255c8f69b9d6c158deeb309bb5e70445b94666ccd9e9`, and the EasyOCR zips with the sha256 values from the register.
  - Request limits.
  - Env: `ML_RESIDENT_BUDGET_MB=2000`, `ML_NLI_COST_MB=600`, `ML_OCR_COST_MB=900`, `ML_NLI_BATCH_SIZE=32`, `ML_NLI_MODEL_PATH`, `ML_OCR_MODEL_DIR`.
- `src/services/ml/bake_models.py`:
  - Bake NLI with `snapshot_download` and an sha256 check.
  - Bake OCR by downloading the zips with urllib, checking their sha256 and extracting the `.pth` files.
  - Load both models once.
  - Assert NLI calls the spike's "Mira died in the fire" pair a contradiction, and print the OCR output for a rendered text image.
- `src/services/ml/requirements.txt`: regenerate. The new top-level pins are `torchvision==0.29.2+cpu`, `easyocr==1.7.2`, `python-multipart==0.0.12` and `opencv-python-headless==4.11.0.86` (the backend's pin). Use the old lock as constraints and the same `uv pip compile` flags plus `--only-binary :all:`; x86_64 and aarch64 give the same result. A pre-compiled result is at `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/lock/lock-x86_64.txt` (inputs `ml.in` and `compile.sh` beside it). Keep the existing lock header style and the trf `#sha256=` fragment. This adds 13 packages: easyocr, imageio 2.38.1, lazy-loader, ninja, opencv-python-headless, pillow, pyclipper, python-bidi, python-multipart, scikit-image, shapely, tifffile and torchvision.
- `src/services/ml/Dockerfile`:
  - Install torchvision in the torch layer.
  - Add `ML_NLI_MODEL_PATH` and `ML_OCR_MODEL_DIR` to the env.
  - Update the comments.
- `src/services/ml/tests/test_dockerfile.py`: requires the `torch==` pin to match the lock. Extend it to torchvision.
- `src/backend/app/services/vision_service.py:24-30`: the OCR post-processing reference. Read-only.
- `src/backend/app/clients/{ml,fakes}.py`:
  - Add `NliScores`, `nli()`, `ocr()` and the multipart `_request`.
  - Pull the `code` out of the error body.
  - Update the Protocol.
- `src/backend/tests/test_ml_client.py`: MockTransport tests. The drift test reads the sidecar `config.py` constants with an AST read.
- `licenses/register.yaml`:
  - Add `ml` to the `images` of the 12 existing rows: easyocr, lazy-loader, ninja, opencv, pillow, pyclipper, python-bidi, python-multipart, scikit-image, shapely, tifffile and torchvision.
  - New row: `imageio` 2.38.1, BSD-2-Clause (from its License-Expression).
  - Add `ml` to the `easyocr-craft-mlt-25k` and `easyocr-english-g2` model rows, and update their notes.
  - New model row: `nli-deberta-v3-xsmall`, Apache-2.0, with its `download` URL and sha256.
  - The `python-bidi` LGPL exception in the policy is not artifact-scoped, so it covers `ml`.
- `docker-compose.prod.yml` `ml`: pass `ML_RESIDENT_BUDGET_MB` through only. Keep this edit minimal, because E0-Platform.5 also edits compose.
- `.env.example`: add a commented `ML_RESIDENT_BUDGET_MB=2000`.

## Tasks & Acceptance

**Execution:**
- `src/services/ml/ml_service/{config,models,budget,app}.py`: implement the budget, the lazy slots, the NLI and OCR models, and the routes, following the matrix.
- `src/services/ml/bake_models.py`, `Dockerfile`, `requirements.txt` and `requirements-dev.txt` (add python-multipart and pillow for local tests): bake and pin.
- `src/services/ml/tests/test_lazy.py` (new): test the matrix rows with fake NLI and OCR, the budget and eviction, concurrency (a busy model is not evicted), load failure, and `EasyOcrReader` post-processing with a stub reader against the `vision_service` rule (skip if PIL or numpy is missing). Update `test_app.py` status expectations and `test_dockerfile.py`.
- `src/backend/app/clients/{ml,fakes}.py` and `src/backend/tests/test_ml_client.py`: implement the client and fake, and test them.
- `licenses/register.yaml`, `docker-compose.prod.yml`, `.env.example`: as listed in the Code Map.

**Acceptance Criteria:**
- Given backend CI, when the suite runs, then the new client tests pass and the sidecar wrapper suite (including test_lazy) passes, with no regressions.
- Given the licence workflow, when `image-licenses (ml)` builds the image, then the bake succeeds: the sha256 values match, NLI flags the Mira contradiction, and OCR loads. The in-image scan also passes in both editions.
- Given `docker-compose.prod.yml`, when it is parsed, then `ml` still has `${ML_MEM_LIMIT:-2560m}` and the CI-14 sum is unchanged.

## Spec Change Log

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 45 findings — high 0, medium 11, low 22, false 7, maybe-false 5
- findings:
  - `[medium]` `[defer]` (blind) ml 2560m limit vs resident models + 2000 MB lazy budget — AD-7/story fix both numbers; desktop RSS measurement. Deferred.
  - `[medium]` `[patch]` (blind) OCR bake only prints its result — bake now fails on empty OCR text.
  - `[medium]` `[patch]` (blind) NLI silently truncates to 512 tokens while accepting 4000 chars/side — documented in the sidecar and client docstrings (E2 sends sentence-sized pairs).
  - `[low]` `[patch]` (blind) Fake OCR docstring claims 422 parity for non-images — docstring reworded (fake mirrors size/emptiness only).
  - `[low]` `[reject]` (blind) Cost > budget accepted by config — the 503 and /v1/status (cost_mb, resident_budget_mb) make it visible; a guard adds surface for an operator misconfiguration.
  - `[low]` `[reject]` (blind) Failed lazy loads retry per request and 500 is retryable — baked weights are proven by the build bake; retries are bounded by the Jobs lifecycle (10 s, 60 s).
  - `[low]` `[patch]` (blind) Cost knobs undocumented — commented ML_NLI_COST_MB / ML_OCR_COST_MB added to .env.example; compose passthrough rejected (keep compose minimal, wave sibling edits it).
  - `[maybe-false]` `[defer]` (blind) First lazy load inside 30 s timeout — needs desktop timing. Deferred medium (unverified).
  - `[medium]` `[defer]` (blind) No pixel cap on decoded images — pre-existing exposure (vision_service today); internal network. Deferred.
  - `[medium]` `[defer]` (blind) python-multipart 0.0.12 CVE — pre-existing backend pin reused. Deferred.
  - `[low]` `[reject]` (blind) Queued requests count as in_use and block eviction — intended: never evict a model with work pending; the other model gets a retryable 503.
  - `[low]` `[reject]` (blind) Missing tests for several waiters on a failed load, OCR 500, non-JSON 5xx suffix, fake cost constants — rare paths; the 500 path is covered on NLI and the suffix falls back to raw text.
  - `[low]` `[patch]` (blind) Stale torchvision note and prod compose comment — both updated.
  - `[low]` `[patch]` (edge) PIL EOFError escapes as 500 — EOFError added to the caught decode errors.
  - `[maybe-false]` `[reject]` (edge) readtext raising on a degenerate image — would only be low; not shown reachable for decodable images.
  - `[medium]` `[defer]` (edge) Pixel bomb up to ~178M pixels — same root cause as the blind pixel-cap row. Deferred.
  - `[low]` `[reject]` (edge) Starlette spools the body before the 413 — internal-only service behind the backend's 10 MB cap.
  - `[low]` `[reject]` (edge) Waiters re-run a failing loader — rare (baked weights proven at build); adds state.
  - `[low]` `[reject]` (edge) ml_load_failed treated as retryable — same as the blind retry row.
  - `[medium]` `[patch]` (edge) NLI truncation past 512 tokens — same root cause as the blind truncation row; documented.
  - `[false]` `[reject]` (edge) NaN/inf scores — softmax over finite logits is finite, and the sidecar's pydantic floats come from torch softmax.
  - `[false]` `[reject]` (edge) lazy as string "false" — the sidecar's response model types it as bool.
  - `[low]` `[reject]` (edge) A non-2-tuple pair raises ValueError — caller programming error, fails loudly.
  - `[low]` `[reject]` (edge) Non-numeric env value error does not name the key — fails loudly at boot with the value shown.
  - `[medium]` `[patch]` (edge) OCR bake not asserted — same as the blind bake row.
  - `[false]` `[reject]` (verification-gap) Sidecar suite runs in no CI workflow — src/backend/tests/test_ml_sidecar_suite.py runs it in backend CI (subprocess), and the backend env has numpy, pillow and python-multipart.
  - `[low]` `[patch]` (verification-gap) Empty-string ML_RESIDENT_BUDGET_MB untested — test added (code already handles it).
  - `[low]` `[patch]` (verification-gap) numpy missing from requirements-dev so reader tests skip locally — numpy==2.4.6 added (in CI they already run).
  - `[medium]` `[patch]` (verification-gap other) OCR bake output not asserted — same as the blind bake row.
  - `[low]` `[reject]` (intent 1) Contract reading A implemented with D1 fakes — descriptive; matches the caller's "tiny fakes" instruction.
  - `[maybe-false]` `[defer]` (intent 2) Declared costs not tied to real memory; NLI 600 < spike's 844 MB process peak — the spike figure is a whole process with torch; desktop RSS settles it. Grouped with the memory-limit deferral.
  - `[false]` `[reject]` (intent 3) AC4 never reached at defaults — the story states the budget and the behaviour; the tests reach it with tighter costs as the spec records.
  - `[maybe-false]` `[defer]` (intent 4) AC5 offline calls not exercised — desktop verification item; CI-5 wiring is E0-QA's. Deferred.
  - `[maybe-false]` `[reject]` (intent 5) OCR output parity with vision_service not shown on a real image — would be settled on the desktop (listed); the reader copies the post-processing and the drift test pins vision_service.
  - `[false]` `[reject]` (intent 6) Desktop checklist absent — it lives in this spec's Auto Run Result and the final report (the queue file is the orchestrator's).
  - `[false]` `[reject]` (intent 7) D2 tiny real checkpoints not used — the caller asked for tiny fakes; the real loaders run in the CI image bake.
  - `[false]` `[reject]` (intent 8) Memory-limit sum not checked — ML_MEM_LIMIT is unchanged and CI-14 runs on the PR.
  - `[low]` `[reject]` (intent 9) imageio became an `ml` tag on the existing ImageIO row — correct: the checker is case-insensitive and a duplicate row would fail.
  - `[low]` `[reject]` (blind) The prod comment staleness duplicate of the memory row — covered by the comment patch.
  - `[low]` `[reject]` (edge) OCR route 500 path untested — same as the blind missing-tests row.
  - `[low]` `[reject]` (blind) Fake cost constants not drift-tested — status fake values are informational only.
  - `[low]` `[reject]` (verification-gap) Backend 503 test uses a hand-built response — the sidecar side is tested in test_lazy through the wrapper.
  - `[low]` `[reject]` (intent) Eviction tested only as logic with fakes — by instruction; desktop RSS before/after eviction is listed.
  - `[low]` `[reject]` (edge) Whitespace-only env value — int(" ") raises loudly at boot.
  - `[low]` `[reject]` (blind) 256-pair NLI request duration — bounded by MAX_NLI_PAIRS; timing deferred with the timeout row.

## Design Notes

The budget counts declared costs (`ML_*_COST_MB`), not measured RSS deltas. RSS moves with whatever else is in flight, such as NER activations and allocator caching, so measured deltas would make the 503 decision noisy. `/v1/status` reports RSS, so the desktop run can tune the declared costs. The defaults (NLI 600, OCR 900, budget 2000) let both models be resident together. Eviction appears only when the budget is lowered or the costs are raised. The tests set NLI to 1200 and OCR to 1000, which follows the story's AC.

Lock order is the budget lock, then a slot lock, and never the reverse. `in_use` changes only under the budget lock, so a model with `in_use == 0` that is chosen while the budget lock is held cannot start serving until the lock is released.

## Verification

Do not install torch/transformers/easyocr on this Mac; real-model behaviour is verified by the CI image build (bake) and the desktop later.

**Commands:**
- `uv run --python 3.11 --with fastapi==0.115.0 --with httpx==0.27.2 --with python-multipart==0.0.12 --with pillow --with numpy --with pytest python -m pytest -q` in `src/services/ml`. Expected: pass.
- `uv run --python 3.11 python -m py_compile` on the changed files. Expected: success.
- GitHub CI on the draft PR. Expected: green, including `image-licenses (ml)`, which runs the real bake.

## Auto Run Result

Status: done

**Summary:** The `ml` sidecar now has two lazily loaded models:
- `POST /v1/nli` runs `cross-encoder/nli-deberta-v3-xsmall` at revision `a1508764…`. It scores in chunks of 32 and returns softmax `{entailment,neutral,contradiction}` in input order.
- `POST /v1/ocr` runs EasyOCR "en" on a multipart `file` and returns `{text}`. Its post-processing is the same as `vision_service`.

Both stay `not_loaded` until their first request. The budget sums each lazy model's declared cost (`ML_RESIDENT_BUDGET_MB`, default 2000; NLI 600 and OCR 900). When a load would go over, it evicts the least-recently-used idle models, only as many as needed. It never evicts a busy model. If eviction cannot make room, the request gets `503 {"detail":"ml budget exceeded","code":"ml_budget"}`. Evicted models are freed with `gc.collect()` and `malloc_trim(0)`.

`/healthz` and the lifespan cover only the resident models. `/v1/status` adds `lazy`, `cost_mb`, `resident_budget_mb` and `lazy_resident_mb`. The client and fake gain `nli()` (batches of 256 pairs) and `ocr()`. Error messages carry the sidecar's `code`, and a 503 maps to `ModelServiceUnavailable`.

The bake downloads and sha256-checks the NLI safetensors and both EasyOCR zips. It loads every model and fails the build unless NLI calls the spike's Mira pair a contradiction and OCR returns text. `ML_MEM_LIMIT` is unchanged.

**Files changed:**
- `src/services/ml/ml_service/budget.py` (new): the budget, `LazySlot`, `BudgetExceeded`, `ModelLoadFailed` and `release_memory`.
- `src/services/ml/ml_service/{app,config,models}.py`: the routes, error handlers, constants, env settings, and the `TransformersNli` and `EasyOcrReader` models.
- `src/services/ml/bake_models.py` and `Dockerfile`: the NLI and OCR bake. `torchvision==0.29.2+cpu` installs in the CPU-torch layer.
- `src/services/ml/requirements.txt`: the lock grows to 87 packages, 13 more, identical on x86_64 and aarch64. `requirements-dev.txt` adds python-multipart, pillow and numpy.
- `src/services/ml/tests/test_lazy.py` (new) plus `test_app.py` and `test_dockerfile.py`: the matrix rows, eviction, concurrency, load failure, OCR post-processing, and a check that the sha256 values match the register.
- `src/backend/app/clients/{ml,fakes}.py` and `tests/test_ml_client.py`: `nli`, `ocr`, the status fields, error codes and the drift tests.
- `licenses/register.yaml`: a new `nli-deberta-v3-xsmall` model row with its sha256. `ml` is added to 13 package rows and both EasyOCR model rows.
- `docker-compose.prod.yml`: passes `ML_RESIDENT_BUDGET_MB` through and updates the comment. Limits are untouched.
- `.env.example`: commented budget and cost settings.

**Review:** 45 findings: high 0, medium 11, low 22, false 7, maybe-false 5.
- Patched:
  - Medium: the bake now asserts the OCR returns text, and NLI 512-token truncation is documented.
  - Low: `EOFError` maps to a 422, the fake's docstring, numpy in the dev requirements, an empty-env test, stale notes and comments, and the cost settings documented.
- Deferred: 5 items, listed in the frontmatter. They are the memory fit under 2.5g, the first-load time against the 30 s timeout, the missing pixel cap, the python-multipart CVE pin, and offline AC5 in CI.
- Rejected: each has its reason in the triage log.
- Sprint-sync: skipped, because the orchestrator owns `sprint-status.yaml`.

**Follow-up review recommended: true.** Two medium entries were patched. The unverified risk is real memory: no measurement yet shows MiniLM, en_core_web_trf, NLI and OCR together fitting in the 2560m container, or that the declared costs are realistic.

**Verification:**
- Sidecar suite, locally: 51 passed, 5 skipped. The skips are the real-model tests.
- Backend `test_ml_client.py`: 69 passed.
- GitHub CI on draft PR #37 is all green.
  - The backend suite passed 380 tests, including the sidecar wrapper.
  - The licence jobs (backend, frontend, register) passed in both editions.
  - `image-licenses (ml)` built the real image and scanned it in both editions. The bake output: NLI scored the Mira pair as contradiction 0.998, and OCR of the rendered "Lorekeeper bake check" image returned `'Lorekeeper bake check'`.

### Needs desktop verification
- **Real NLI on the spike pairs:** after `docker compose -f docker-compose.prod.yml up -d ml`, from the backend container, POST the 6 pairs from `spikes/cpu-benchmarks.md` §5 to `http://ml:8000/v1/nli`. Expect contradiction ≥ 0.97 on Mira, the black dagger and Grukk. Aldric is a known false positive (≈0.99). Also time 50 pairs; expect < 10 s, about 1 s.
- **OCR on a sample image:** `curl -F file=@sample.png http://ml:8000/v1/ocr`. The text should equal `vision_service.extract_notes_from_image` on the same file in the backend container.
- **RSS before and after lazy loading and eviction:**
  1. Read `/v1/status` `rss_bytes` and `docker stats ml` at boot, then after the first NLI call, then after the first OCR call.
  2. Restart with `ML_RESIDENT_BUDGET_MB=1000`, call NLI, then OCR. NLI should go to `not_loaded`, and RSS should fall after the eviction.
  3. Use these numbers to tune `ML_NLI_COST_MB` and `ML_OCR_COST_MB`. Confirm the peak stays under `ML_MEM_LIMIT=2560m`.
- **Offline:** `scripts/sidecar_smoke.sh ml`. Then `docker run --rm -d --network none --name mltest lorekeeper-ml`, and once it is healthy, `docker exec` a Python urllib POST to `/v1/nli` and `/v1/ocr` inside it. Both should work with no download attempted.
- **First-load latency:** the time of the first `/v1/ocr` and `/v1/nli` calls against the client's 30 s `ML_TIMEOUT_S`.
- **arm64:** `docker buildx build --platform linux/arm64 src/services/ml`. The bake should pass.

**Residual risks:**
- Memory fit under 2.5g (deferred).
- With the default costs (600 + 900 < 2000), eviction is not exercised in production.
