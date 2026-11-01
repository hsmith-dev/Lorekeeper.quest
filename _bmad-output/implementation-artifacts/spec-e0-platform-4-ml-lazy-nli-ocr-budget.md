---
title: 'E0-Platform.4: `ml` lazy NLI and OCR under a resident-memory budget'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '56a28028dbe46f881bb3e9f3bc72253051acf028'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
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

## Design Notes

The budget counts declared costs (`ML_*_COST_MB`), not measured RSS deltas. RSS moves with whatever else is in flight, such as NER activations and allocator caching, so measured deltas would make the 503 decision noisy. `/v1/status` reports RSS, so the desktop run can tune the declared costs. The defaults (NLI 600, OCR 900, budget 2000) let both models be resident together. Eviction appears only when the budget is lowered or the costs are raised. The tests set NLI to 1200 and OCR to 1000, which follows the story's AC.

Lock order is the budget lock, then a slot lock, and never the reverse. `in_use` changes only under the budget lock, so a model with `in_use == 0` that is chosen while the budget lock is held cannot start serving until the lock is released.

## Verification

Do not install torch/transformers/easyocr on this Mac; real-model behaviour is verified by the CI image build (bake) and the desktop later.

**Commands:**
- `uv run --python 3.11 --with fastapi==0.115.0 --with httpx==0.27.2 --with python-multipart==0.0.12 --with pillow --with numpy --with pytest python -m pytest -q` in `src/services/ml`. Expected: pass.
- `uv run --python 3.11 python -m py_compile` on the changed files. Expected: success.
- GitHub CI on the draft PR. Expected: green, including `image-licenses (ml)`, which runs the real bake.
