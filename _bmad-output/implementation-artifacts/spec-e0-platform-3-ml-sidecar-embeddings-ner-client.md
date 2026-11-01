---
title: 'E0-Platform.3: `ml` sidecar for embeddings and NER, with its client'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: '7336dd0386f2630aab091b8ee82f87c6cb3c3b74'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      The sidecar suite only runs in CI when a PR also touches src/backend/**.
    evidence: |-
      backend-tests.yml is path-filtered on src/backend/** and is the only runner (through
      src/backend/tests/test_ml_sidecar_suite.py). A sidecar-only PR starts no workflow. Workflows are E0-QA's.
    location: >-
      .github/workflows/backend-tests.yml:8-17
    severity: medium
  - summary: >-
      CI runs the sidecar's real-model NER tests on the backend's spaCy 3.7.6 / trf 3.7.3, not the image's 3.8.18 / 3.8.0, and never builds the ml image.
    evidence: |-
      The wrapper uses the backend CI interpreter; src/services/ml/requirements.txt, bake_models.py,
      the HEALTHCHECK and scripts/sidecar_smoke.sh run nowhere in CI. E0-QA.8 adds the shipped-image
      build job (the ml image should join its list); tag parity on 3.8 is a desktop check.
    location: >-
      src/backend/tests/test_ml_sidecar_suite.py; src/services/ml/Dockerfile
    severity: medium
  - summary: >-
      Requests queue on the per-model lock with no bound, so a burst can outlast the client's 30 s timeout while the sidecar keeps working on abandoned requests.
    evidence: |-
      ModelSlot.run takes threading.Lock without a timeout. Real only under load; needs measurement
      and a 503-on-busy policy, which fits E0-Platform.4's budget/503 work.
    location: >-
      src/services/ml/ml_service/models.py (ModelSlot.run)
    severity: medium (unverified)
  - summary: >-
      Torch thread count is not tied to the container CPU limit (prod cpus 1.0).
    evidence: |-
      No OMP_NUM_THREADS / torch.set_num_threads; torch sizes its pool from host cores and is throttled
      under the CFS quota. Tune with the measured limits in E0-Platform.7.
    location: >-
      docker-compose.prod.yml (ml deploy.resources); src/services/ml/Dockerfile
    severity: low
  - summary: >-
      Embedding parity on the 9 demo-seed narratives against the old in-process embed has no harness.
    evidence: |-
      The demo seed (E0-QA) is not in the repo yet; test_embed_parity.py (ML_REAL_MODELS=1) checks batched vs
      per-text encoding on 4 texts only. Desktop verification compares the live sidecar with the backend container.
    location: >-
      src/services/ml/tests/test_embed_parity.py
    severity: low
  - summary: >-
      Backend tests get the fake only once ENVIRONMENT=test is set, which E0-QA's conftest does.
    evidence: |-
      Nothing calls get_ml_client() yet, so no test reaches the network today. The story assigns the
      switch to E0-QA's conftest (tests/conftest.py is off-limits here).
    location: >-
      src/backend/app/clients/ml.py (get_ml_client)
    severity: low
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

### 2026-11-01 — Review pass
- verdicts: 47 findings — high 0, medium 18, low 24, false 5, maybe-false 0 (the intent-alignment layer's 9 observations count as findings; medium includes duplicates of one root cause reported by several layers)
- findings:
  - `[medium]` `[patch]` (verification-gap) Deleting backend test_nlp.py left the live `nlp_service.extract_tags` (TagType mapping, name de-dup) untested until E0-Platform.6. Restored `src/backend/tests/test_nlp.py` unchanged; the sidecar copies stay too.
  - `[medium]` `[defer]` (verification-gap) Sidecar-only PRs trigger no CI. The workflow path filter is E0-QA's. Deferred.
  - `[medium]` `[defer]` (verification-gap) CI exercises spaCy 3.7.3, not the image's 3.8 stack, and never builds the image. E0-QA.8 image job plus a desktop check. Deferred.
  - `[low]` `[patch]` (verification-gap) `MLClient.status()` malformed paths untested. Added `test_status_contract_breaks`.
  - `[medium]` `[patch]` (verification-gap, other) The ml Dockerfile has no CPU-torch static guard. Added `src/services/ml/tests/test_dockerfile.py`: CPU index order, extra index, guard after every pip install, torch pin equals the lock, offline env after the bake, HEALTHCHECK present.
  - `[low]` `[defer]` (intent a) Parity covers 4 texts, batched vs per-text, not the 9 demo narratives vs the backend. The demo seed is absent; desktop check. Deferred.
  - `[medium]` `[patch]` (intent b) Moved NER cases assert raw labels, not the TagType mapping. Same root cause as the deleted backend test; restoring it covers the mapping. 3.8 tag parity is a desktop check.
  - `[low]` `[reject]` (intent c) Client and sidecar never run together. Doing it in one process means importing the sidecar from the backend, which the separation rule forbids; the shapes are pinned on both sides and the constants have a drift test.
  - `[low]` `[reject]` (intent d) Real normalisation is checked only opt-in. `normalize_embeddings=True` is the call the backend makes today; the bake step and the opt-in parity test cover it.
  - `[low]` `[reject]` (intent e) The sidecar keeps its own constants and migrations hardcode 384. The sidecar cannot import the backend (story rule), a drift test covers it, and migrations are frozen history.
  - `[low]` `[reject]` (intent f) Route-level use of the fake is not exercised. No route uses the client until E0-Platform.6, by instruction.
  - `[medium]` `[patch]` (intent g) The smoke script's default image name is never produced. Added `image: lorekeeper-ml:latest` to both compose `ml` services.
  - `[low]` `[reject]` (intent h) CI trigger surface. Same as the deferred path-filter row.
  - `[false]` `[reject]` (intent i) The prod memory limit, the dev compose service and the retry helper are additions. The story requires `ml` in both compose files, every prod service carries limits, and `is_retryable` is a two-line helper the epic's retry contract needs.
  - `[medium]` `[patch]` (blind) The client sends more than 256 texts in one request, which the sidecar rejects with 422. `MLClient.embed` now batches at `MAX_EMBED_TEXTS` (256, drift-tested against the sidecar config); test added.
  - `[medium]` `[patch]` (blind) Deleted backend test_nlp. Same as the verification-gap row (restored).
  - `[low]` `[patch]` (blind) No drift test for the copied ITEM/QUEST patterns. Added `test_sidecar_matcher_patterns_match_nlp_service` (ast.literal_eval of both files).
  - `[false]` `[reject]` (blind) Overlapping Matcher spans are not filtered. `nlp_service` passes the same overlapping matches today and de-dups by name; the sidecar keeps today's behaviour on purpose.
  - `[medium]` `[patch]` (blind) `/v1/ner` text is unbounded. Added `max_length=MAX_NER_CHARS` (100k) and a 422 test.
  - `[low]` `[defer]` (blind) Torch threads vs the CPU limit. Deferred to E0-Platform.7.
  - `[low]` `[reject]` (blind) One timeout covers connect and read. The story specifies one `ml_timeout_s`, and a down sidecar on the compose network refuses quickly.
  - `[low]` `[reject]` (blind) 408/429 are treated as terminal. The sidecar never emits them.
  - `[medium]` `[patch]` (blind) Smoke default image name. Same as intent g.
  - `[low]` `[patch]` (blind) `ML_MEM_LIMIT` is undocumented. Added to `.env.example`.
  - `[low]` `[reject]` (blind) The compose acceptance criterion has no automated test. `docker compose config` in desktop verification covers it; a YAML test adds structure for a two-line invariant.
  - `[low]` `[defer]` (blind) CI never tests the shipped stack. Same as the deferred image row.
  - `[low]` `[reject]` (blind) Dev compose builds the heavy image. The story requires the service in docker-compose.yml.
  - `[low]` `[reject]` (blind) `test_importing_app_loads_no_models` depends on test order. The AST test beside it already proves there is no module-level heavy import.
  - `[low]` `[reject]` (blind) The healthcheck is repeated in the Dockerfile and compose. Harmless duplication; the compose values are explicit.
  - `[low]` `[patch]` (blind) The python image register note lists apt installs the ml image lacks. Note reworded.
  - `[low]` `[reject]` (blind) Only model.safetensors is hashed. The revision pin fixes the small config files; the weights are what the register records.
  - `[false]` `[reject]` (blind) The `_clients` cache leaks stale clients. It is keyed by (url, timeout), so different settings get a different client.
  - `[low]` `[patch]` (edge) httpx DecodingError / TooManyRedirects escape the typed contract. `_request` now maps any other `httpx.HTTPError` to `ModelServiceError`; test added.
  - `[medium]` `[patch]` (edge) More than 256 texts. Same as the blind batching row.
  - `[low]` `[reject]` (edge) Non-numeric vector elements. The sidecar's pydantic `list[list[float]]` response model rules them out.
  - `[medium]` `[patch]` (edge) Deterministic 500s retried forever. The reachable case (spaCy max_length) is now a 422 through the NER cap; other model exceptions were not shown reachable.
  - `[medium]` `[patch]` (edge) Unbounded NER text. Same as the blind row.
  - `[medium]` `[defer]` (edge) The lock queue has no bound. Deferred (unverified) to E0-Platform.4's 503 policy.
  - `[low]` `[reject]` (edge) A bad `ML_EMBED_BATCH_SIZE` crashes at import. Failing loudly on a bad operator setting is correct.
  - `[low]` `[defer]` (edge) Nothing sets ENVIRONMENT=test. The story gives that to E0-QA's conftest. Deferred.
  - `[false]` `[reject]` (edge) A stop word followed by a newline in the fake. The span keeps correct offsets; the fake makes no claim to match spaCy on such input.
  - `[low]` `[patch]` (edge) The single-definition test misses annotated assignments. `_module_assignments` now matches `ast.AnnAssign` too.
  - `[medium]` `[patch]` (edge) Smoke default image name. Same as intent g.
  - `[low]` `[reject]` (edge) A non-integer `SMOKE_TIMEOUT_S`. `set -e` aborts on bash's arithmetic error; nothing passes silently.
  - `[medium]` `[patch]` (edge) Deleted backend test_nlp. Same as the verification-gap row.
  - `[low]` `[patch]` (edge) The "moved" claim vs the changed de-dup property. Restoring the backend test keeps the name de-dup covered.
  - `[false]` `[reject]` (edge) The matrix claims the fake under ENVIRONMENT=test. `get_ml_client` does select it under that setting (tested); who sets it is the deferred E0-QA row.

## Design Notes

The sidecar suite runs inside backend CI through a subprocess wrapper because workflows belong to E0-QA; a dedicated `ml` job (and path filter on `src/services/ml/**`) is deferred to E0-QA. Image build and `--network none` smoke in CI belong to E0-QA.8's image list. spaCy 3.8 (not the backend's 3.7.6) because 3.7.6 has no linux-aarch64 wheels (architecture tech-currency review D6); tag parity with 3.7.3 is a desktop check.

## Verification

**Commands:**
- `uv run --python 3.11 --with fastapi==0.115.0 --with httpx==0.27.2 --with pytest python -m pytest -q src/services/ml/tests` -- expected: pass (real-model tests skip)
- `python -m py_compile` on changed backend files; `docker compose -f docker-compose.prod.yml config -q` if docker available -- expected: success
- GitHub CI on the draft PR -- expected: green

## Auto Run Result

Status: done

**Summary:** A new `src/services/ml/` sidecar:
- **Stack:** FastAPI on Python 3.11. Torch 2.15.0+cpu comes from the PyTorch CPU index. spaCy 3.8.18 and `en_core_web_trf` 3.8.0 install as a hash-pinned wheel. MiniLM is baked at revision `1110a243…` and its sha256 is checked.
- **Routes:**
  - `/healthz`
  - `/v1/status`: models and RSS.
  - `/v1/embed`: up to 256 texts, returns unit-norm 384-d vectors.
  - `/v1/ner`: up to 100k chars, returns spaCy ents followed by the Matcher's ITEM/QUEST spans.
- **Container:** runs offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) with one worker, as non-root, with a HEALTHCHECK. A CUDA/NVIDIA guard runs after every install.

On the backend side:
- `app/clients/{errors,ml,fakes}.py`: `ModelServiceUnavailable` and `ModelServiceError`, a client that batches requests, and a deterministic fake that is chosen under `ENVIRONMENT=test`.
- `app/domain/embedding.py` is the single embedding contract.
- Settings `ml_url` and `ml_timeout_s`.

Compose adds `ml` on an `internal: true` `models` network, with no ports and no nginx route. Callers are not switched over; that is E0-Platform.6.

**Files changed:**
- **`src/services/ml/` (new):**
  - `ml_service/{app,config,models}.py`, `bake_models.py`
  - `Dockerfile`, `.dockerignore`
  - `requirements.txt` (a 74-package lock), `requirements-dev.txt`, `pytest.ini`
  - `tests/`: fake HTTP tests, a Dockerfile static guard, the moved NER cases plus a Borin Stonebeard / Karak Dun / ring of shadows case, and an opt-in parity test.
- **`src/backend/app/clients/` (new):** client, errors and fake.
- **`src/backend/app/domain/embedding.py` (new):** the embedding contract.
- **`src/backend/app/core/config.py`, `services/embedding_service.py`, `db/models/journal.py`, `db/models/source.py`:** the new settings, and imports of the contract.
- **Backend tests:**
  - `test_ml_client.py` (new).
  - `test_ml_sidecar_suite.py` (new): runs the sidecar suite in a subprocess as a stopgap CI hook.
  - `tests/test_nlp.py` is kept (see the review). The story says "move", but the cases now live in both places until E0-Platform.6 removes `nlp_service`.
- **Compose, scripts and env:** `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`, and `scripts/sidecar_smoke.sh` (new).
- **`licenses/register.yaml`:** `ml` added to 65 reused rows, 10 new package rows, and an `en_core_web_trf` 3.8.0 model row.

**Review:** 47 findings. Several layers reported the same root causes, so the grouped entries are what was patched or deferred. Every row is in the triage log.
- **Patched, 8 entries:**
  - medium: backend NER coverage restored, the ml Dockerfile guard test, the smoke image name, client batching, the NER length cap
  - low: the status contract test, the pattern drift test, a typed fallback for other httpx errors, AnnAssign in the single-definition test, `ML_MEM_LIMIT` documentation, the register note
- **Deferred:** 6, listed in the frontmatter.
- **Rejected:** each has its reason in the triage log.
- **Sprint-sync:** skipped, because the orchestrator owns sprint-status.yaml.

**Follow-up review recommended: true.** Five medium entries were patched. The unverified risk is that the ml image has never been built. Installing the lock, running `bake_models.py` against the image's huggingface-hub, the guard RUNs, and the HEALTHCHECK under `--network none` have only been checked statically.

**Verification:**
- Sidecar suite, locally: 19 passed, 5 skipped. The real-model tests skip when no models are installed.
- `tests/test_ml_client.py` with `--noconftest`: 43 passed.
- The implementation subagent also ran:
  - the real-model tests on both spaCy 3.7.6/trf 3.7.3 and spaCy 3.8.18/trf 3.8.0;
  - a real bake, with a matching sha256;
  - the server offline;
  - `check-licenses.py --artifact ml` on an env installed from the lock: 0 violations in both editions.
- GitHub CI on draft PR #27: everything passed on the first push (backend tests, licence backend/frontend/register, frontend build).

### Needs desktop verification
- **Build:**
  - Run `docker build -t lorekeeper-ml:latest src/services/ml` and `docker buildx build --platform linux/arm64 src/services/ml`. The guard RUNs and `bake_models.py` should pass.
  - Run `docker run --rm lorekeeper-ml pip list | grep -iE 'nvidia|cuda'`. It should print nothing.
- **Offline health:** `scripts/sidecar_smoke.sh ml` prints `ml: healthy`.
- **Compose:**
  - `docker compose -f docker-compose.prod.yml config -q` passes.
  - After `docker compose -f docker-compose.prod.yml up -d ml`, `docker compose -f docker-compose.prod.yml ps ml` shows `healthy`.
  - `docker port` shows nothing for ml.
  - From the backend container, `python -c "import httpx;print(httpx.get('http://ml:8000/v1/status').json())"` works.
- **Embedding parity:**
  - For each of the 9 demo-seed narratives, sidecar `POST /v1/embed` and in-process `embedding_service.embed` in the backend container should have a cosine of at least 0.9999.
  - Also run `ML_REAL_MODELS=1 pytest src/services/ml/tests` inside the ml image.
- **NER/tag parity:** for the same narratives, `nlp_service.extract_tags` in the backend (3.7.3) and the sidecar's `/v1/ner` ents mapped with the same TagType rules (3.8.0) should give the same tags.
- **Memory:** use `docker stats` and `/v1/status` `rss_bytes` to compare the RSS of the backend's 4 workers against the `ml` container. Record per-worker and sidecar numbers for E0-Platform.6 and .7.
- **In-image licence scan:**
  - Run `docker run --rm -v $PWD:/repo -w /repo -e LOREKEEPER_EDITION=commercial lorekeeper-ml sh -c "pip install -q pyyaml && python scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact ml"`, then the same with `agpl`. Both should report 0 violations.
  - Add the ml image to E0-QA.8's list of shipped images.

**Residual risks:**
- spaCy 3.8 with trf 3.8.0 may tag some narratives differently from today's 3.7.3. The desktop parity check settles this.
- The sidecar suite runs in CI only when `src/backend/**` changes as well. The fix is deferred to E0-QA.
