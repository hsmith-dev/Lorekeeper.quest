---
title: 'E0-Platform.3: `ml` sidecar for embeddings and NER, with its client'
type: 'feature'
created: '2026-11-01'
status: 'in-review'
baseline_revision: '7336dd0386f2630aab091b8ee82f87c6cb3c3b74'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Each of the 4 gunicorn workers loads sentence-transformers MiniLM and spaCy `en_core_web_trf` itself (about 6.4 GB idle, 11.9 GB boot peak). There is no shared model service and no client contract for one.

**Approach:** Add `src/services/ml/`, a standalone FastAPI sidecar (Python 3.11, CPU torch from the PyTorch CPU index, spaCy 3.8.18 + `en_core_web_trf` 3.8.0, MiniLM baked at a pinned revision), serving `/healthz`, `/v1/status`, `/v1/embed`, `/v1/ner`. Add the backend client `app/clients/ml.py` with typed errors and a deterministic fake, the single embedding contract `app/domain/embedding.py`, settings, compose services on an internal-only network, the CI-5 smoke script and licence register entries. Callers are NOT switched (E0-Platform.6).

## Boundaries & Constraints

**Always:** The sidecar package (`ml_service`) never imports the backend `app` package. Heavy imports (torch, sentence_transformers, spacy) happen only inside the real model loaders, so the HTTP app is testable with fakes. Torch pin `2.15.0+cpu` from `--index-url https://download.pytorch.org/whl/cpu` in its own layer before requirements, with the E0-Platform.2 CUDA/NVIDIA guard RUN after every install. Weights are baked at build; the container runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. `ml` has no `ports:` and no nginx route, and sits only on an `internal: true` compose network that the backend also joins. Every package, image and weight in the `ml` image is in `licenses/register.yaml`. Client timeouts come from `settings.ml_url` / `settings.ml_timeout_s`.

**Never:** Change `nlp_service`/`embedding_service` callers or `main.py` lifespan (E0-Platform.6). Edit `.github/workflows/*`, `.github/license-policy.toml`, `LICENSING.md`, `tests/conftest.py`, `migrations/env.py`, `docker-compose.dev.yml`, `llm_gate.py`, `pubsub.py`, frontend, `sprint-status.yaml`, `epics.md`. Edit historical migration files. Add NLI/OCR (E0-Platform.4) or memory-limit tables (E0-Platform.7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| embed | `POST /v1/embed {"texts":["a","b"]}` | `{model:"all-MiniLM-L6-v2", dim:384, vectors:[[384 floats],[...]]}`, unit-norm, input order | — |
| embed empty | `{"texts":[]}` | `{..., vectors: []}` | — |
| embed too many / bad body | > 256 texts, or missing `texts` | 422 | pydantic validation |
| ner | `POST /v1/ner {"text":"..."}` | `{ents:[{text,label,start,end}]}`; spaCy ents first, then Matcher `ITEM`/`QUEST`; `text[start:end] == ent.text` | — |
| status | `GET /v1/status` | `{models:[{name,kind,state:"loaded"}], rss_bytes}` | — |
| client: sidecar down / timeout / 5xx | connect error, `httpx.TimeoutException`, 502/503/500 | — | `ModelServiceUnavailable` |
| client: contract break | 4xx, wrong `dim`/`model`, vector count ≠ texts | — | `ModelServiceError` (not retried) |
| client in tests | `ENVIRONMENT=test` | `get_ml_client()` returns `FakeMLClient`: stable 384-d unit vectors, rule-based ents | — |

</intent-contract>

## Code Map

- `src/backend/app/services/embedding_service.py:5-6` -- defines `EMBEDDING_MODEL`/`EMBEDDING_DIM`; must import from `app/domain/embedding.py`. `embed()` uses `encode(text, normalize_embeddings=True)` (parity reference).
- `src/backend/app/db/models/journal.py:9`, `source.py:8` -- local `EMBEDDING_DIM = 384` copies to replace with the import. Migrations `7ffedba22a12`, `402ad2866114` hardcode `Vector(384)`: frozen history, left alone.
- `src/backend/app/services/nlp_service.py:10-36` -- `ITEM_PATTERNS`, `QUEST_PATTERNS`, Matcher labels `ITEM`/`QUEST`, label→TagType mapping (PERSON; GPE/LOC/FAC; ORG). Sidecar copies the patterns verbatim.
- `src/backend/tests/test_nlp.py` -- 3 cases; move to `src/services/ml/tests/test_nlp.py` (backend file deleted).
- `src/backend/app/core/config.py` -- `Settings`; add `ml_url`, `ml_timeout_s`. `environment` drives fake selection.
- `src/backend/app/core/errors.py` -- LLM error style reference (class attrs `code`); sidecar errors live separately in `app/clients/errors.py`.
- `src/backend/Dockerfile.prod:22-33` -- CPU-torch layer + guard pattern to copy.
- `.github/workflows/backend-tests.yml` -- read-only. Runs `pytest` in `src/backend` with full backend requirements and `en_core_web_trf` 3.7.3 installed; only path-filtered on `src/backend/**`. The only CI runner available for sidecar tests.
- `licenses/register.yaml` -- flow-style python rows; multiple rows per name allowed if versions differ (`scripts/check-licenses.py:254-257`); model rows need `download` + `sha256` (+ `pip_package`).
- `docker-compose.yml`, `docker-compose.prod.yml` -- add `ml`; prod gives every service `deploy.resources.limits`.
- Resolved ml set (uv pip compile, identical on x86_64 and aarch64): 74 packages; new vs register: setuptools 84.2.1; new versions: blis 1.3.4, confection 1.3.4, httpx 0.28.1, numpy 2.4.6 (licence expr `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`), smart-open 9.0.1, spacy 3.8.18, spacy-curated-transformers 0.3.1, thinc 8.3.14, weasel 1.0.1, en_core_web_trf 3.8.0 (wheel `https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.8.0/en_core_web_trf-3.8.0-py3-none-any.whl`, sha256 `272a31e9d8530d1e075351d30a462d7e80e31da23574f1b274e200f3fff35bf5`). Reproduce the lock with `uv pip compile <in> --python-version 3.11 --python-platform x86_64-manylinux_2_28 --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match` where `<in>` = fastapi==0.115.0, uvicorn==0.30.0, pydantic==2.9.0, sentence-transformers==5.5.1, spacy==3.8.18, the trf wheel URL, torch==2.15.0+cpu. MiniLM revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, `model.safetensors` sha256 `53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db` (register row). New-version licence strings from PyPI: blis `BSD` (alias → BSD-3-Clause), smart-open MIT (classifier), setuptools MIT, others match their existing rows.

## Tasks & Acceptance

**Execution:**
- `src/services/ml/ml_service/{__init__,config,models,app}.py` -- sidecar: env config, real loaders (SentenceTransformer from baked path; spaCy + Matcher), per-model locks, routes per the matrix, RSS from `/proc/self/statm` with `resource` fallback; `app = create_app()` module attribute.
- `src/services/ml/bake_models.py` -- build-time: `snapshot_download` MiniLM at revision `1110a243…` into `/models/all-MiniLM-L6-v2`, verify `model.safetensors` sha256, then load both models once.
- `src/services/ml/requirements.txt` (full pin lock, trf wheel URL with `#sha256=`), `requirements-dev.txt`, `Dockerfile`, `.dockerignore`.
- `src/services/ml/tests/{conftest,test_app,test_nlp,test_embed_parity}.py` -- fake-model HTTP tests; moved `test_nlp` cases + Borin Stonebeard case (skip if `en_core_web_trf` not installed); parity test opt-in via `ML_REAL_MODELS=1`.
- `src/backend/tests/test_ml_sidecar_suite.py` -- runs the sidecar suite in a subprocess (interim CI hook; skips if `src/services/ml` absent).
- `src/backend/app/domain/{__init__,embedding}.py`; update `embedding_service.py`, `journal.py`, `source.py`.
- `src/backend/app/clients/{__init__,errors,ml,fakes}.py` -- client, errors, `FakeMLClient`, `get_ml_client()`.
- `src/backend/app/core/config.py` -- `ml_url = "http://ml:8000"`, `ml_timeout_s = 30.0`.
- `src/backend/tests/test_ml_client.py` -- matrix client rows via `httpx.MockTransport`, fake determinism, selection, single-definition check.
- `src/backend/tests/test_nlp.py` -- delete (moved).
- `scripts/sidecar_smoke.sh` -- `sidecar_smoke.sh <service> [image]`: `docker run -d --network none`, wait for Docker health `healthy` (timeout `SMOKE_TIMEOUT_S`, default 300), dump logs and fail otherwise, always remove the container.
- `docker-compose.yml`, `docker-compose.prod.yml` -- `ml` service (build `./src/services/ml`, no ports, `models` internal network, healthcheck; prod `restart` + limits `${ML_MEM_LIMIT:-2560m}`); backend joins `default` + `models`.
- `.env.example` -- `ML_URL`, `ML_TIMEOUT_S` (commented defaults).
- `licenses/register.yaml` -- add `ml` to `images` of every reused row (python image, MiniLM, torch, shared packages); new rows for the new versions/packages and `en_core_web_trf` 3.8.0 model.

**Acceptance Criteria:**
- Given backend CI, when the suite runs, then the existing tests (minus the 3 moved `test_nlp` cases) pass plus the new client tests, and the wrapper test runs the sidecar suite green (including the moved NER cases against the installed trf model).
- Given the licence workflow, when it runs on this PR, then backend and register jobs pass in both editions.
- Given both compose files, when parsed, then `ml` has no `ports` and is attached only to the internal network.

## Spec Change Log

## Review Triage Log

## Design Notes

The sidecar suite runs inside backend CI through a subprocess wrapper because workflows belong to E0-QA; a dedicated `ml` job (and path filter on `src/services/ml/**`) is deferred to E0-QA. Image build and `--network none` smoke in CI belong to E0-QA.8's image list. spaCy 3.8 (not the backend's 3.7.6) because 3.7.6 has no linux-aarch64 wheels (architecture tech-currency review D6); tag parity with 3.7.3 is a desktop check.

## Verification

**Commands:**
- `uv run --python 3.11 --with fastapi==0.115.0 --with httpx==0.27.2 --with pytest python -m pytest -q src/services/ml/tests` -- expected: pass (real-model tests skip)
- `python -m py_compile` on changed backend files; `docker compose -f docker-compose.prod.yml config -q` if docker available -- expected: success
- GitHub CI on the draft PR -- expected: green
