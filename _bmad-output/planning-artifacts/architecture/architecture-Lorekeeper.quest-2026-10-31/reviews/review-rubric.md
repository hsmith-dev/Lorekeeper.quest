---
title: Rubric review of ARCHITECTURE-SPINE.md
reviewed: _bmad-output/planning-artifacts/architecture/architecture-Lorekeeper.quest-2026-10-31/ARCHITECTURE-SPINE.md
against: prd.md, addendum.md, brownfield-context.md, src/ (commit 0c35e21), live package registries (2026-10-31)
date: 2026-10-31
verdict: revise-before-epics
---

# Rubric review: Lorekeeper architecture spine

## Verdict

This is a strong initiative-level spine. The job system, visibility model, single Canon write path, file serving, the Live transport and the licence gate are all decided at the right level, and almost every named version checks out. It is **not ready to fan out to 17 parallel epics yet**, for four reasons:

- Ownership of the shared schema contradicts itself (AD-19 against the boundary map).
- Two ADs have Rules that the brownfield code cannot satisfy, or that do not prevent the divergence they name (AD-13's CI check and AD-20's per-user limiting).
- Offline model provisioning is never decided, although NFR-1 and every demo scenario depend on it.
- Several job-runtime details that each epic would otherwise invent are missing: the DB session in handlers, the RQ timeout, the heartbeat owner and the drainer owner.

Each fix is small. None of them reopens the paradigm.

## Rubric scorecard

| Criterion | Result | Notes |
| --- | --- | --- |
| Fixes the real divergence points, misses none | Partial | Strong coverage. Missed: the DB session and timeout in job handlers, the build-edition mechanism, model provisioning, the E1/E2 proposal↔flag link, entity-panel extension points, legacy status mapping, the KoboldCpp structured path. |
| Every Rule is enforceable and prevents its divergence | Partial | AD-13's CI rule fails on the existing code. AD-20 leaves per-IP throttling in place. AD-4's heartbeat can't be met by a handler. AD-1's layering has no check. AD-11's fingerprint blocks re-proposal after an edit. |
| Nothing Deferred lets two units diverge | Mostly | The files_data backup owner is "whichever epic lands first" (three candidates). The rest is safe. |
| Named tech is verified-current | Pass, with notes | All versions exist. Ollama v0.40.13, Kokoro-FastAPI v0.9.2 and rq 3.0.0 are 1–3 days old. rq is pinned to 2.9.1 although 3.0.0 is out. arm64 availability is unstated. |
| Ratifies rather than contradicts the brownfield | Mostly | It contradicts the brownfield in the AD-13 CI rule (99 route `select()` calls and 6 services), the AD-1 layer table (`get_user_llm_config` lives in `api/deps.py`), and by staying silent on the arm64 OCI production host. |
| Covers the spec's capabilities | Pass, with gaps | Missing: FR-22 marking (no data link), FR-6 delete effects on Canon, FR-44 stream close for share-link revocation, FR-24 "appears without refresh" for the graph. |
| Altitude dimensions decided, deferred or open | Fail on the operational envelope | Model install offline, observability, upgrade/rollback and the hosted OCI environment are not addressed. Backups are deferred with an ambiguous owner. |
| Terse (decisions, not rationale) | Pass | Mostly decision-shaped. A few rationale clauses could go (see Low). |
| Seed/obvious ADs to cut | Minor | AD-20 and AD-21 are largely ratified seed. Keep them, slimmer. Nothing should be cut outright. |
| Internal contradictions | Fail | Container limits sum to more than the 7.5 GB bound. The stored_files owner is given three different ways. The Foundation migration owner is unclear. `core` imports layers above it. AD-10 and AD-17 disagree on when hooks fire. |

---

## Critical

### C-1. Offline model provisioning is undecided (NFR-1, every DS scenario)

**Finding.** NFR-1 requires that every model "can be downloaded ahead of time and installed offline" and that there are "no new outbound calls". The spine says `stt` loads faster-whisper "on first use" and `ml` loads NLI/OCR "lazily", but it never says where the weights come from. By default faster-whisper and sentence-transformers/cross-encoders pull from the Hugging Face Hub on first load. EasyOCR also downloads on first use, and that is today's behaviour, which is being moved. The profile swaps (`en_core_web_sm`↔`trf`, NLI xsmall↔base, whisper base↔small) mean that the model for the other profile is also absent. The result is that each sidecar epic will pick its own provisioning, either baked in, a volume or a runtime pull, and DS-1 to DS-5 (internet disconnected) will fail on first use.

**Fix.** Add an AD, "Model provisioning":
- Every sidecar image bakes the baseline models at build time and sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at runtime.
- Full-profile models live on a named volume `models_data` mounted read-only, and are populated by `scripts/fetch-models.sh` (online) or by `scripts/import-models.sh <bundle.tar>` (offline).
- `GET /v1/status` reports each missing model, and the admin model-install SSE flow (`ollama_service.install_model_events` pattern) is extended to cover sidecar models.
- CI runs each sidecar with `--network none` and asserts that `/v1/status` reports the baseline models loaded.
- Add the Ollama 7B import (`deploy-oci.sh` already does this) to the same procedure.

### C-2. Schema and file ownership contradicts itself across AD-19 and the boundary map

**Finding.** AD-19 says the Foundation migration creates `jobs`, `stored_files`, `data_backfills`, `entities` and every satellite table. The boundary map says:
- `jobs` and `data_backfills` are owned by E0-Jobs;
- the entity tables are owned by E0-WorldCore;
- the Foundation migration is owned by E0-Access;
- `stored_files` and `files.py` are "created by whichever of E5, E8 or E10 lands first";
- the E10 row says `file_service.py` is "owned by E0-Jobs if it lands first".

That is three or four owners for the same objects. With parallel epics, two teams will each write `CREATE TABLE stored_files`, or each wait for the other.

**Fix.** Pick one owner per object, and give the order:
- **(a)** E0-Access owns *only* the enums, role and visibility columns, and party columns (migration `foundation_access`).
- **(b)** E0-Jobs owns `jobs` and `data_backfills`.
- **(c)** E0-WorldCore owns `entities` and its satellites.
- **(d)** Move `stored_files`, `file_service.py`, `api/routes/files.py`, the nginx `/_files/` internal location and the `files_data` volume into **E0-Platform**, since it is a Phase 0 foundation that three feature epics consume.

Then rewrite AD-19's first bullet as "Foundation migrations (one per owning E0 epic, in the order Access → Jobs → Platform(files) → WorldCore) create every shared enum and table", and delete the "whichever lands first" lines.

---

## High

### H-1. AD-13's CI check cannot pass on the brownfield code and has no escape for system contexts

**Finding.** `check_scoped_queries.py` fails on `select(<registered model>)` outside `core/access.py` and `services/*_repo.py`. The existing code has 99 `select(` calls in `api/routes/*.py`, plus selects in `journal_service`, `retrieval_service`, `source_service`, `shorthand_service` and others. No `*_repo.py` files exist or appear in the new source tree, and the naming convention is `<domain>_service.py`. Job handlers, backfills and the worker's boot requeue also have to read rows without a user ctx. As written, the rule either blocks every PR or gets disabled. Either way it stops preventing R-9.

**Fix.**
- Make the check a **ratchet**: a committed baseline file `scripts/scoped_queries_baseline.txt` lists today's call sites, CI fails on any *new* unscoped select of a registered model, and E0-Access burns the list down for FR-8 routes.
- Allow `scoped_select` *or* a `select()` whose enclosing function takes `ctx: CampaignContext` in `services/*_service.py`.
- Add `access.system_ctx(campaign_id, reason)` for jobs and backfills, and have the check accept it.
- Drop the `_repo.py` wording.

### H-2. AD-20 does not stop a table that shares one IP being throttled together

**Finding.** AD-20 "Prevents: a table sharing one IP being throttled together", but its Rule puts every new AI or streaming route into the nginx `ai_gen` zone. That zone is `limit_req_zone $binary_remote_addr … rate=10r/m` (`nginx/nginx.conf:52`). Five players behind one NAT asking the Chronicler share 10 r/m at nginx before slowapi's per-user key is ever reached. That violates NFR-8. "Streaming route" also collides with "Job routes stay in the api zone" for `GET /api/jobs/stream`, and the same is true of a 30 r/s burst-20 zone for a Leaflet viewport fetching 20–40 tiles at once.

**Fix.**
- Add an nginx zone `ai_user` keyed on `$http_authorization`, falling back to the IP for anonymous requests, at 10 r/m. Use it for authenticated AI routes, and keep `ai_gen` per-IP only as a coarse ceiling (for example 60 r/m).
- Say explicitly that `/api/jobs/stream` and other long-lived SSE subscriptions go in `api`, with `proxy_buffering off`.
- Give tiles their own `location ~ ^/api/maps/[^/]+/tiles/` with `burst=100`.

### H-3. The job runtime leaves the DB session, timeout and heartbeat to each epic

**Finding.** In AD-2 and AD-4:
- `handle(job: Job, ctx)` has no DB session, so every handler will invent its own.
- The RQ worker forks a work-horse per job by default, so an asyncpg engine created at import is shared across the fork.
- RQ's default `job_timeout` is 180 s, which is shorter than the CPU targets (extraction and export at ≤ 3 min, plus a 60 s Ollama cold load). Jobs will be killed and retried as "other exceptions".
- The handler is told to call `job_progress` every 10 s, but a handler that awaits a single multi-minute `complete_structured` call cannot do so. The heartbeat is unmeetable and the 60 s stale rule will requeue live jobs on a second worker's boot (full profile).
- An OOM-killed work-horse (likely under a 512 MB worker limit) leaves its row `running` until the next worker boot.
- It is not stated whether retries use RQ `Retry` (which needs `--with-scheduler`) or a self re-enqueue.

**Fix.** Amend AD-2/AD-4:
- The signature is `async def handle(job, ctx, db: AsyncSession)`. The wrapper creates the engine inside the work-horse with `NullPool` and disposes it afterwards.
- The wrapper runs a background heartbeat task every 10 s, independent of `job_progress`. `job_progress` only reports progress.
- `job_timeout` comes from `registry.py` per kind, defaulting to 15 min, and `JobTimeoutException` maps to the retryable `timeout` error_code.
- A reaper runs every 60 s in each worker (not only at boot) and fails or requeues rows whose heartbeat is stale.
- Retries are AD-4's own re-enqueue via `enqueue_at`, with workers started `--with-scheduler`, and RQ-level retry is disabled.
- State whether a backfill cursor re-enqueue reuses the same `jobs` row (recommended, so FR-18 shows "one Job with per-entry progress").

### H-4. The container limits contradict the 7.5 GB bound they are meant to enforce

**Finding.** The baseline limits sum to about 9.2 GB:

| Container | Limit |
| --- | --- |
| ollama | 5 GB |
| postgres | 0.5 GB |
| redis | 0.125 GB |
| web | 0.5 GB |
| worker | 0.5 GB |
| ml | 1 GB |
| stt | 1 GB |
| tts | 0.5 GB |
| nginx | 0.064 GB |
| **Total** | **≈ 9.2 GB** |

The stated Live Session peak (7.2 GB) is only reachable if several containers stay well under their limits. The limits therefore neither enforce NFR-2 nor match the peaks. Some individual limits are also implausible:
- `ollama 5g` for a ~4.4 GB Q4 7B plus a 4096-token KV cache leaves very little headroom.
- `ml 1g` holds spaCy, MiniLM, NLI and EasyOCR. EasyOCR is torch-based, and the `sentence-transformers` ONNX backend still pulls in torch.
- `worker 512m` runs WeasyPrint on a 100-entry book and pyvips on a 16,000 px map, and both of those are listed as unmeasured.
- `redis 128m` with `--save 60 1` (RDB fork, copy-on-write) holds RQ queues and raw PCM backlog (about 19 MB per session at the 10-minute cap) under `noeviction`. A full Redis rejects writes, which stops every enqueue.

**Fix.**
- State the invariant "Σ baseline limits of always-on containers ≤ 7.5 GB, and lazy containers (stt, tts, ml lazies) are counted inside the admission rule". Then either cut the limits to fit, or say explicitly that the limits are OOM guards and add a separate `docs/BENCHMARKS.md` peak budget per case that SPIKE-5 must hit.
- Store PCM backlog chunks on `files_data` (tmp kind) and keep only refs in Redis. Alternatively set Redis `appendonly no`, `save ""` in baseline (job authority is Postgres anyway).
- Mark the worker and ml limits **(provisional: SPIKE-5)**, matching the others.

### H-5. The commercial and open-source "build" is referenced but never defined

**Finding.** AD-7 (tts off in the commercial build), AD-16 and AD-22 (CI "fails the commercial build"; tts is the exception "scoped to the open-source build") all depend on a build edition, but no AD says what it is: an env flag, a compose override, an image tag suffix or a CI matrix. E0-QA, E0-Platform and E5 will each invent one.

**Fix.** Add one row to AD-22 or AD-7:
- `LOREKEEPER_EDITION ∈ {oss, commercial}` is a compose-time variable, and `profiles/commercial.env` sets `COMPOSE_PROFILES` without `tts`.
- CI has a matrix job `edition=commercial` that builds images without the `tts` service and runs the licence check with the strict allowlist.
- `tts_client.available()` returns false whenever `tts_url` is unset.

### H-6. AD-11's fingerprint uniqueness contradicts AD-17's supersede-and-re-extract

**Finding.** Editing a GM entry supersedes its `pending` proposals and queues extraction again (AD-17, FR-6). AD-11's `UNIQUE(journal_id, fingerprint)` then makes the re-run "insert nothing for that pair whether pending or decided". A re-extracted proposal identical to a superseded one is therefore silently dropped, and after the edit the GM never sees it. That breaks FR-6 and FR-13.

**Fix.** Use a partial unique index `UNIQUE(journal_id, fingerprint) WHERE state <> 'superseded'`. Rejected and approved rows still block (FR-15, FR-18), and superseded rows don't.

### H-7. Layering is unenforced and contradicts itself

**Finding.**
- `core/*` "imports nothing above it", but `core/access.py` imports db models, and `core/hooks_registry.py` imports `app/<feature>_hooks.py`, which call services (the diagram's H→S edge).
- `app/domain/*` and `app/<feature>_hooks.py` are not in the layer table.
- `get_user_llm_config` lives in `api/deps.py` and raises `HTTPException(402)`, but jobs must "resolve with the get_user_llm_config order" and may not import `api`.
- AD-1 has no checker, so "Follow the layer table" is advisory.

**Fix.**
- Move access to `app/access.py` (or declare that `core/access.py` sits above persistence), and put hooks registration in `app/hooks_registry.py`.
- Add `domain` (pure data, imports nothing) and `<feature>_hooks` (may import services and jobs.enqueue) to the table.
- Extract `resolve_llm_config(db, user) -> LLMConfig` into `services/llm_config_service.py`, raising `LLMConfigError`. `deps.get_user_llm_config` becomes a thin wrapper that maps it to 402.
- Enforce the table with `import-linter` contracts in CI.

---

## Medium

### M-1. The Live drainer has no ownership rule across gunicorn workers (AD-15)

**Finding.** "A per-session drainer in the web process" runs with `-w 2` (and `-w 4` on full). A reconnect can land on the other worker, which gives either two drainers (duplicate stt calls and out-of-order segments) or none (when the original socket's worker no longer holds it). A phone sleeping also stops draining if the drainer is tied to the socket.

**Fix.** The drainer holds a Redis lease `live:{id}:drainer` (`SET NX PX 30000`, renewed every 10 s), independent of the socket. Whichever web process holds the lease drains, and the socket handler only pushes chunks and subscribes to `live:{id}:events`. Segments are written in `seq` order.

### M-2. The admission rule conflicts with NFR-6 for other Campaigns, and in-request LLM calls bypass it (AD-3, AD-7)

**Finding.**
- "While a Live Session is active in any Campaign, workers consume only `interactive`" holds every other Campaign's extraction for up to 4 hours, against NFR-6's ≤ 3 min. That is acceptable for one group per host (NFR-11) but must be stated as a baseline-only, accepted deviation.
- A job already running when the session starts is not pre-empted, so the first Rolling Recaps can wait up to about 3 minutes.
- NPC replies, Chronicler answers and quick-lookup free text stream inside the request and hit Ollama (`NUM_PARALLEL=1`) concurrently with the recap job. "One heavy job at a time per model" is only true for RQ.

**Fix.**
- Scope the rule to `PROFILE=baseline` and record the NFR-6 exception for Q4.
- On `live_session_started`, the running non-interactive job is allowed to finish, and that wait is shown in the Live UI's backlog notice.
- State that interactive in-request LLM calls queue at Ollama and are not admission-controlled, and have SPIKE-5 measure the recap-plus-NPC overlap.

### M-3. AD-8 breaks the real KoboldCpp provider and model thrash for multiple users

**Finding.**
- Provider `kobold` covers KoboldCpp as well as Ollama (brownfield §3.1, and the prod compose comment describes a GPU host running KoboldCpp). KoboldCpp has no `/api/chat` with `format`.
- "Every task resolves to the user's configured model" doesn't stop two users on one host from choosing `finetuned` and `base` with `OLLAMA_MAX_LOADED_MODELS=1`. Each switch costs about 60 s.

**Fix.**
- Probe `GET /api/version`. If it is Ollama, use native `format`. Otherwise use the OpenAI-compatible `response_format` json_schema with a prompted-JSON fallback (the same path as `custom`).
- In the baseline profile, `model_for` resolves platform-default configs to `settings.kobold_model` only and ignores `hosted_model_variant`. Model Evaluation's quick-compare is documented as full-profile.

### M-4. The observability dimension is missing

**Finding.** The admin System tab and support bundle read `LOG_FILE` on `backend_logs` from the web container only. The new worker, ml, stt and tts containers fall outside it, as does `/api/health` (db and kobold only). Each epic will add its own diagnostics.

**Fix.** Add a Conventions row:
- web and worker write JSON logs to the same `backend_logs` volume (`backend.log`, `worker.log`);
- `/api/health` aggregates each sidecar's `/healthz` and `/v1/status` (RSS, loaded models) and the queue depths;
- the admin System tab shows them;
- the support bundle includes `jobs` failures from the last 24 h;
- there is no external telemetry (NFR-5).

### M-5. The upgrade and rollback dimension is missing

**Finding.** Nothing states forward-only migrations or a downgrade policy (NFR-8 implies forward-only), what happens when a sidecar contract changes (`/v1` versioning), or how an existing install moves to the new compose (the old `backend` service is renamed to `web`, plus new volumes and the worker).

**Fix.** Add to AD-19 or the environments paragraph:
- migrations are forward-only, and `downgrade()` may `raise`;
- the restore point is a `pg_dump` taken by `scripts/backup-db.sh` before `up`;
- a sidecar breaking change bumps the `/v2` prefix while the old one is kept for one release;
- a documented `UPGRADE.md` step covers the `backend`→`web` rename (keeping the `backend` network alias so nginx's `upstream backend:8000` keeps working).

### M-6. The hosted, arm64 production environment is not addressed

**Finding.** Production today is OCI Ampere A1, **linux/arm64**, 24 GB (`docs/OCI_DEPLOYMENT.md`, `scripts/deploy-oci.sh`), with live Stripe billing. The spine names only the x86 8 GB Reference Box and the dev Mac. It doesn't say whether the OCI box runs the `full` profile, and it doesn't require arm64 images for `ml`, `stt` and `tts`. ctranslate2 and onnxruntime 1.31.1 ship aarch64 wheels (verified). The upstream Kokoro-FastAPI CPU image's arm64 manifest is unverified.

**Fix.**
- The environments paragraph should say "OCI A1 = `full` profile, CPU, arm64".
- Every built image is `linux/amd64,linux/arm64` (buildx in CI).
- The `tts` image tag must have an arm64 manifest, or a local build from source is the fallback, and LIC-1/SPIKE-3 verify this.
- `deploy-oci.sh` is updated by E0-Platform.

### M-7. The proposal↔flag link between E1 and E2 is undecided (FR-22)

**Finding.** FR-22 marks contradicting proposals in the checklist. E1 owns `change_proposals` and E2 owns `continuity_flags`, and neither side's link is specified. Both epics are parallel in Phase 2, or Phase 1 against Phase 2.

**Fix.** In AD-11, `continuity_flags.proposal_id` (nullable FK) is owned by E2. E1's checklist API returns `flags[]` per item through a join that E2 registers as a renderer. No column is added to `change_proposals`.

### M-8. Legacy status mapping and adapter round-trip are missing (AD-18)

**Finding.** AD-18 maps roles but not statuses. Legacy `NpcStatus.dead` must become FR-11's `deceased`, and the `/api/npcs/*` adapters must map back for the current frontend. E0-WorldCore, the adapter author and the frontend will each guess.

**Fix.** Add the table `dead→deceased, alive→alive, unknown→unknown`, keep Quest statuses as they are, and state that the adapters return legacy enums until the frontend moves.

### M-9. Shared hotspot files are missing from the "Touches" list

**Finding.** Several files are edited by more than one epic, but only the registries are listed as append points:
- `api/routes/journals.py`: E0-Journal, E0-Access, E7.
- `api/routes/campaigns.py`: E0-Access (FR-10), E7 (roles), and the analytics/export that E8 and E9 replace.
- `api/routes/entities.py`: E0-WorldCore, E3.
- `retrieval_service.py`: E0-Access, plus E6's filter argument.
- `components/entities/EntityDetailPanel`: E2 flags, E3 relationships, E6 "Talk to", E10 pins.
- `ChatPage.tsx`: E0-Access, E6.

**Fix.**
- Add an entity-panel section registry, `components/entities/panelSections.ts`, keyed by Entity Type, as the Review UI does.
- State that E8 and E9 add new routes and that the old `campaigns.py` export and analytics become thin redirects owned by E0-Access.
- E6 adds `entry_ids: set[UUID] | None` to `hybrid_search_journal` in a PR reviewed by E0-Access.

### M-10. Hook enqueue failure is silent (AD-17 vs NFR-9) and hook timing is inconsistent (AD-10)

**Finding.**
- "A handler failure is logged and never propagates", so a failed `enqueue` from an `entry_saved` handler leaves no Job row. NFR-9 says every failure appears in Job status.
- AD-10 fires `canon_changed` inside `apply_change`'s transaction, while AD-17 says hooks fire after commit.

**Fix.**
- Jobs triggered by a write are inserted as `jobs` rows **inside** the write transaction (an outbox). The after-commit hook only pushes `job_id` to RQ, and the worker's reaper re-pushes `queued` rows older than 30 s.
- AD-10 says "queues `canon_changed`, dispatched after commit".

### M-11. The files_data backup owner is ambiguous (Deferred)

**Finding.** "Ships with the first file-producing epic", but FR-52 makes "included in backups" a testable consequence. There is also the question of whether `stored_files` rows and files are consistent when they are dumped at different times.

**Fix.** The owner is E0-Platform (after C-2). `backup-db.sh` also tars `files_data` after `pg_dump`. A restore deletes orphan files and marks rows whose bytes are missing as `stale`. `ollama_data` and `models_data` are documented as re-importable from the offline bundle (C-1), not backed up.

---

## Low

- **L-1. Version freshness.** Every version was verified on PyPI, npm or GitHub on 2026-10-31 (rq, sse-starlette, onnxruntime 1.31.1, faster-whisper 1.2.1, ctranslate2 4.8.4, rapidfuzz 3.14.6, WeasyPrint 70.0, pyvips 3.2.0, sigma 4.0.4, graphology 0.26.0, @react-sigma/core 6.0.0, forceatlas2 0.10.1, leaflet 1.9.4, Ollama v0.40.13, Kokoro-FastAPI v0.9.2). Notes:
  - **rq 3.0.0 was released 2026-10-28.** The spine pins 2.9.1. Keep 2.9.1, but say so explicitly ("2.x until 3.0 soaks").
  - Ollama v0.40.13 (2026-10-28) and Kokoro-FastAPI v0.9.2 (2026-10-30) are days old. Pin the tag that SPIKE-2/3/5 actually measured, not "current".
  - sentence-transformers' latest is 6.2.0 against the existing pin of 5.5.1. That is fine, but the `ml` image is new, so either decide to keep 5.5.1 or decide to drop sentence-transformers there for plain onnxruntime and a tokenizer, which removes torch from `ml` (see H-4).
  - spaCy 3.7.6 is an old pin (3.8.18 is current). That is fine for `ml`, but the `en_core_web_sm` and `trf` model versions must match 3.7.x.
- **L-2. The embedding backend swap changes vectors.** Moving MiniLM from torch to ONNX, and especially to int8, alters stored vectors slightly. Treat "backend or quantization change" like a model-id change in AD-6: re-embed plus a `RETRIEVAL_EVAL` rerun.
- **L-3. The baseline NER swap changes existing tag behaviour.** `trf`→`sm` changes today's on-save tags and breaks `tests/test_nlp.py`, which expects trf. Note it, and pin the test to the `ml` fake.
- **L-4. `party_tsv` can be set-based.** `to_tsvector('english', narrative)` belongs in the Foundation migration, not a backfill. Only `party_embedding` needs the `ml` backfill, and until it runs, non-GM retrieval should fall back to lexical-only (state this).
- **L-5. Stream close on Share Link revocation.** AD-13 closes streams on a `role_version` change, but anon Share Link streams (revoked or expired) have no `role_version`. Re-check `revoked` and `expires_at` on the same ping.
- **L-6. Narrow the WS location.** `location /api/live/` with a 4-hour timeout also catches the REST start/pause/end routes. Use `location ~ ^/api/live/[^/]+/ws$`.
- **L-7. The Owner has no member row.** `role_version` lives on `campaign_members`, and the Owner isn't a row (brownfield §2). State that the Owner's ctx uses `role_version = 0` and is never closed.
- **L-8. Global `entry_hash` uniqueness.** FR-6 edits recompute `entry_hash`, which is globally unique, so an edit can 409 across Campaigns. Scope it to `(campaign_id, entry_hash)` in E0-Journal's migration, or keep the original hash on edit.
- **L-9. The CI requirements check is too shallow.** AD-1's check reads `requirements.txt`, but torch can arrive transitively. Check `pip freeze` inside the built web/worker image instead.
- **L-10. Terseness.** Mostly good. Trim the rationale in AD-1's "Prevents" ("today about 11.9 GB at peak"), AD-7's peak narrative (move it to BENCHMARKS), and the Deferred items' reasons. AD-20 and AD-21 are largely ratified brownfield seed. Keep them, but cut them to just the deltas (the per-user key, `ai_user` zone and internal `/_files/`; and alembic-built test schema, the fake provider and EV-4 route enumeration).
- **L-11. The E10 `apply_change` caller is ambiguous.** E10 is listed as calling `apply_change`, but `map_pins` is not in AD-10's table list. Either Pin→Location links are Canon (add `map_pins` to AD-10) or E10 is removed from that sentence.
- **L-12. Missing FR coverage notes.** FR-24's "approved Relationship appears without refresh" needs `useJobStream` or `canon_changed` invalidation of `[graph, campaignId]`, so state it in the Graph convention. FR-6's delete effect ("Canon fields whose only source was that entry are flagged") needs a named owner, which should be the E0-WorldCore `entry_deleted` handler.

---

## Contradictions index

| # | Between | Contradiction |
| --- | --- | --- |
| 1 | AD-19 ↔ boundary map ↔ E10 row | `stored_files`, `jobs` and the entity tables each have two or three owners (C-2). |
| 2 | AD-7 limits ↔ AD-7 peaks ↔ NFR-2 | Σ limits ≈ 9.2 GB > 7.5 GB bound (H-4). |
| 3 | AD-11 fingerprint ↔ AD-17 supersede | Superseded rows block re-proposal (H-6). |
| 4 | AD-20 Prevents ↔ AD-20 Rule | Per-IP nginx zone still throttles a shared IP (H-2). |
| 5 | Layer table ↔ `core/access.py`, `core/hooks_registry.py` | `core` imports layers above it (H-7). |
| 6 | AD-13 CI ↔ brownfield and Conventions | `_repo.py` files don't exist, and 99 route selects (H-1). |
| 7 | AD-10 ↔ AD-17 | Hook fired in-transaction vs after-commit (M-10). |
| 8 | AD-4 heartbeat ↔ single long LLM await | Handler cannot heartbeat (H-3). |
| 9 | AD-3/AD-7 admission ↔ NFR-6 | Other Campaigns' on-save jobs wait out a Live Session (M-2). |

## Suggested AD additions (summary)

1. **AD-23 Model provisioning and offline install** (C-1).
2. **Build edition** row in AD-22 (H-5).
3. **Job runtime** amendments to AD-2/AD-4: db session, timeout, wrapper heartbeat, reaper and outbox (H-3, M-10).
4. **Operations** conventions row: logs, health aggregation, upgrade/rollback, backups including files, arm64 (M-4, M-5, M-6, M-11).
