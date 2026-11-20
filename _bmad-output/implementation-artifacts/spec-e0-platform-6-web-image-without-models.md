---
title: 'E0-Platform.6: Web and worker image without models: async client wrappers and lifespan cleanup'
type: 'refactor'
created: '2026-11-20'
status: 'in-progress'
baseline_revision: '9b73f0bcdec1f75aec6b389349b9e1fdf893bba1'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** Every gunicorn worker (and every RQ worker) loads spaCy `en_core_web_trf` and MiniLM in-process at boot (`app/main.py` lifespan), about 6.4 GB idle and 11.9 GB peak for the web tier, and the CPU inference blocks the event loop. The backend image still carries CPU torch, spaCy, sentence-transformers and the spaCy model, although the `ml` sidecar (E0-Platform.3/4) already serves embeddings, NER and OCR and `stt` (E0-Platform.5) serves speech.

**Approach:** `embedding_service` and `nlp_service` become `async def` wrappers over `app/clients/ml.py` (vision and transcription already are). Every caller awaits them. Lifespan loads no model. torch, torchvision, spaCy, sentence-transformers, the spaCy model and `build-essential`/`libpq-dev` leave `requirements.txt`, both Dockerfiles, backend CI and the CI-3 baseline (which becomes empty). The admin System tab shows the sidecars' `/v1/status`.

## Boundaries & Constraints

**Always:**
- Journal save never blocks on AI. If `ml` is down, the entry saves with no tags, `embedding`/`party_embedding` NULL, and a WARNING is logged.
- Tag mapping is unchanged: PERSON → character; GPE/LOC/FAC → location; ORG → faction; ITEM → item; QUEST → quest; dedupe on (lower(name), type); `name.title()`; in sidecar order (spaCy ents, then Matcher).
- Embedding parity comes from the same MiniLM in `ml` (E0-Platform.3 measured cosine ≥ 0.9999). No re-embed and no change to `app/domain/embedding.py`.
- Request paths that cannot do their job without `ml` return `503 {"detail": "<Model> unavailable"}`: source upload, journal reindex, NPC extract. Retrieval and canon context degrade to lexical-only or no canon, as they do today.
- Scripts (`seed_demo`, `eval_common`, `eval_retrieval`, `backfill_party_embeddings`) embed through the same `embedding_service`. `--embeddings require` fails clearly when `ml` is unreachable.
- Every removed package also leaves `licenses/register.yaml` for the `backend` image (rows only the backend used are deleted, shared rows lose `backend`).

**Never:**
- No new model package or `import` of one in `app/`. No baseline line is added anywhere (CI-3, CI-2 ratchet, CI-8).
- No pooled httpx client bound to an event loop. The clients stay per-call, because the RQ worker runs `asyncio.run` once per Job.
- No memory-limit changes (E0-Platform.7 owns `WEB_MEM_LIMIT`). No `journal.reembed` Job (E0-Journal). No edits to `lib/sse.ts`, the entities API or the members/analytics code (sibling stories).
- Do not change the published RETRIEVAL_EVAL numbers without a real re-run.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Save, ml up | POST journal | Tags from `/v1/ner`, both vectors from `/v1/embed` | none |
| Save, ml down | `ModelServiceUnavailable` | 201; no tags; both vectors NULL | WARNING log, caught in service |
| Chat retrieval, ml down | query | lexical-only hits | caught (existing) |
| Source upload, ml down | PDF/text | 503 "Embedding model unavailable"; nothing committed | `ModelServiceError` → 503 |
| Reindex, ml down | POST /reindex | 503; nothing committed | same |
| NPC extract, ml down | POST extract | 503 "NER model unavailable" | same |
| Admin sidecars | GET /api/admin/sidecars | `{ml:{reachable, error, models, rss_bytes,…}, stt:{…}}`; an unreachable one is `reachable:false` + error | never 5xx |
| Boot, sidecars absent | app start | healthy, no model load | none |

</intent-contract>

## Code Map

- `src/backend/app/main.py:23-24,46-47` -- drop the `load_nlp_model`/`load_embedding_model` imports and calls.
- `src/backend/app/services/embedding_service.py` -- rewrite: `async embed(text)`, `async embed_many(texts)` over `get_ml_client()`. Add `use_client(client | None)` so scripts can install an override (the eval's bag-of-words fake, or a disabled client for `--embeddings skip`). Keep the `EMBEDDING_DIM`/`EMBEDDING_MODEL` re-export.
- `src/backend/app/services/nlp_service.py` -- rewrite: keep `ExtractedTag` and the label mapping, plus `async extract_tags(text)` over `ml.ner`. ITEM/QUEST_PATTERNS now live only in the sidecar (`src/services/ml/ml_service/models.py:14`).
- Callers to await: `app/services/journal_service.py:98,134` (wrap NER and embed in `except ModelServiceError` + `logger.warning`), `app/services/retrieval_service.py:172,307`, `app/services/source_service.py:56`, `app/services/eval_service.py:39-42` (make `_score` async or precompute), `app/api/routes/journals.py:373` (reindex), `app/api/routes/sources.py:18,94` (`embed_many(chunks)`), `app/api/routes/npcs.py:22,204`. `/api/ingest/image` (vision_service) is already async (E0-QA.9).
- `src/backend/app/api/routes/admin.py` -- add `GET /sidecars` (router-level `require_admin`, `60/minute` on `user_or_ip`, like `/jobs/stats`), calling `get_ml_client().status()` and `get_stt_client().status()`. Schemas go in `app/schemas/admin.py`.
- `src/backend/tests/ev4/exemptions.yaml` -- add an exemption for `GET /api/admin/sidecars` (admin-only, no Campaign data).
- `src/frontend/src/{types/index.ts,services/api.ts,hooks/useAdmin.ts,pages/AdminPage.tsx}` -- a `SidecarStatusCard` in `SystemTab` beside `JobCountsCard`, styled the same way (semantic tokens only, `lint:tokens`).
- Scripts: `src/backend/scripts/seed_demo.py:61,230-260,347-365` (the Embedder becomes async; `load_embedder(mode)` probes ml: auto warns and returns None, require raises SeedError, skip returns None; `EMBEDDING_MODEL` imported from `app.domain.embedding`), `scripts/eval_common.py:128-158,414-420` (`FakeEmbeddingModel` gets `async embed(texts)`; `install_embedding_model` → `embedding_service.use_client`), `scripts/eval_retrieval.py:57,105,197-225`, `scripts/backfill_party_embeddings.py:84-86,155-180` (async embed, drop `_load_model`).
- Tests to update (a sync monkeypatched lambda breaks once the callee is awaited): `tests/test_party_retrieval.py:42,237,251-266,332`, `tests/access/test_projection.py:595-596`, `tests/access/test_campaign_permissions.py:399-400,430`, `tests/access/test_write_rules.py:247-248`, `tests/ev4/probes/retrieval.py:36-57`, `tests/test_eval_common.py:207-293`, `tests/seeds/test_demo_seed.py:150-190`, and any backfill test. Delete `tests/test_nlp.py` (its cases live in `src/services/ml/tests/test_nlp.py`). Replace `tests/test_ml_client.py:449-454` (the pattern-parity test) with a test of the label mapping. Conftest already sets `ENVIRONMENT=test`, so `FakeMLClient` serves every test.
- `src/backend/requirements.txt` -- remove `spacy`, `sentence-transformers`. Keep `numpy<2.0` (pgvector). `uv pip compile --only-binary :all:` resolves the rest on x86_64 and aarch64 alike (72 packages), so no compiler is needed.
- `src/backend/Dockerfile`, `Dockerfile.prod` -- drop the torch install, the spaCy download, the CUDA guard (there is no torch left to guard; CI-3 forbids its return) and `build-essential libpq-dev` (asyncpg needs no libpq). Use a plain `pip install -r requirements.txt`.
- `scripts/model_packages_baseline.txt` -> header only. `scripts/test_check_model_packages.py:22` `FROZEN_BASELINE = frozenset()`.
- `scripts/check_model_packages.py` -- add `--installed FILE` (a `pip list --format=freeze` / `pip freeze` dump, `-` for stdin) so the AC's "pip list in the image" check exists. Every forbidden package in it fails (no baseline). Add unit tests.
- `src/backend/.importlinter` -- drop both `ignore_imports` lines (and the key). `scripts/test_import_ratchet.py` -- `FROZEN_IGNORES` empty; `TODAY` nlp/embedding import `app.clients`; `test_stale_ignore_line_fails` plants its own stale line in the copied config.
- `.github/workflows/backend-tests.yml:69-104` -- plain install, delete the spaCy download step and the torch/CUDA guard (needed: spaCy is gone). `.github/workflows/license-check.yml` -- the backend job drops the CPU extra index. The image job prints the image size (`docker image inspect`) and, for `backend`, runs `pip list --format=freeze` in the image through `check_model_packages.py --installed -`. The comment about the several-GB backend image is refreshed.
- `licenses/register.yaml` -- packages leaving backend (resolve diff): annotated-doc blis catalogue cloudpathlib cloudpickle confection cymem filelock fsspec hf-xet httpcore2 httpx2 huggingface-hub joblib langcodes markdown-it-py mdurl mpmath murmurhash narwhals networkx preshed pygments regex rich safetensors scikit-learn scipy sentence-transformers shellingham smart-open spacy spacy-legacy spacy-loggers srsly sympy thinc threadpoolctl tokenizers torch torchvision tqdm transformers truststore typer typer-slim wasabi weasel, plus spacy-curated-transformers/curated-* and the `en_core_web_trf` 3.7.3 model row. MiniLM's `images` → `[ml]`. Apt: the build-essential/libpq-dev closure (gcc*, g++*, cpp*, binutils*, make, dpkg-dev, libc6-dev, linux-libc-dev, lib*-dev, libasan8…libubsan1, libisl23, libmpc3, libmpfr6, libjansson4, libsframe1, libgprofng0, libctf*, rpcsvc-proto, patch, perl and libperl/perl-modules, libdpkg-perl, libgdbm*, libpq5 and its krb5/ldap/sasl deps). The image scan's `--emit-missing` re-adds anything still present. The header comment on CPU torch is updated.
- `docker-compose.yml:103-104`, `docker-compose.prod.yml:193-212,257-262` -- refresh comments (nothing loads models in web/worker; the limit itself is E0-Platform.7's). README:197, docs/LICENSING.md:168 -- remove the spaCy download / "stays in the image" text.
- `docs/RETRIEVAL_EVAL.md` -- reproduce text: embeddings come from `ml` (`ML_URL`); `require` fails without it. Results still awaiting the desktop re-run (12-entry seed plus sidecar).
- `src/backend/tests/test_ml_sidecar_suite.py` docstring -- en_core_web_trf is no longer in backend CI, so the sidecar's `test_nlp.py` skips there.

## Tasks & Acceptance

**Execution:**
- `.github/workflows/license-check.yml` + `scripts/check_model_packages.py --installed` (+ tests) -- DONE in commit a571095 (pushed, draft PR #76; it measures the "before" size). Do not redo. Do not commit or push: the orchestrator does that. Remaining work in this file is only the CPU-index flag in the `backend` job and the stale several-GB comment.
- `app/services/{embedding,nlp}_service.py`, `app/main.py` -- async wrappers, lifespan.
- All callers (Code Map), with the 503 mapping on the three routes and the warning on journal save.
- Admin `/sidecars` route + schema + EV-4 exemption + frontend card.
- Scripts: seed/eval/backfill.
- Tests: update the monkeypatches, and add: journal save with ml down (no tags, NULL vectors, warning), the 503 for source upload/reindex/npc extract, the tag-mapping unit test over a stub client, the admin sidecars route (up via fake; down via a raising client), lifespan without model loading (`import app.main` pulls in no spacy/sentence_transformers), and check_model_packages `--installed`.
- Image/CI/register/docs per Code Map.

**Acceptance Criteria:**
- Given the app starts, then lifespan calls only `init_valkey()` (and teardown), and `sys.modules` has no `spacy`/`sentence_transformers`/`torch` after `import app.main`.
- Given `requirements.txt` and both Dockerfiles, `python scripts/check_model_packages.py` passes with an empty baseline, and the CI image job's `pip list` check of the built backend image passes.
- Given ml is down, journal save returns 201 with no tags and NULL vectors, and logs a warning.
- Given `GET /api/admin/sidecars` as admin, it returns both sidecars' status; non-admin gets 403.
- Given the full backend suite, the gates and frontend CI, all are green in GitHub CI.

## Spec Change Log

## Review Triage Log

## Design Notes

"Lifespan cleanup" is the removal of model loading. The `ml`/`stt` clients open one short-lived `httpx.AsyncClient` per call (E0-Platform.3's design), so they hold no pooled connection to close at shutdown. A process-wide pool would be bound to the first event loop and break in the RQ worker, which runs `asyncio.run` per Job. Batch work uses `embed_many` (one request per 256 texts), so the per-call connect is not a hot path.

Eval override example:
```python
embedding_service.use_client(FakeEmbeddingModel())  # has async embed(texts)
try: ... finally: embedding_service.use_client(None)
```

## Verification

Environment: there is no Postgres or Valkey on this Mac, and you must not start one. Tests that need the DB run only in GitHub CI. A ready Python 3.11 venv with the slim backend requirements plus requirements-dev (no spaCy or torch) is at `/private/tmp/claude-501/-Users-harrisonsmith-Documents-GitHub-Lorekeeper-quest/a5524f3a-4ba6-4d29-8233-79940950d6ae/scratchpad/venv/bin/python`. Use it for every local run. Do not install anything globally.

**Commands:**
- `cd src/backend && <venv python> -m pytest -q <the non-DB test files you touched>` (e.g. tests/test_ml_client.py, the new mapping/lifespan tests) -- pass
- `cd src/backend && PYTHONPATH=. <venv>/bin/lint-imports --no-cache` -- pass
- `<venv python> -m compileall -q src/backend/app src/backend/scripts` -- pass
- `python scripts/check_model_packages.py && python -m pytest -q scripts/test_check_model_packages.py scripts/test_import_ratchet.py` -- pass
- `cd src/frontend && npx tsc --noEmit && npm run build && npm run lint:tokens` -- pass
- GitHub CI: backend-tests, gates, frontend-ci, license-check (image-licenses backend prints the size) -- green
