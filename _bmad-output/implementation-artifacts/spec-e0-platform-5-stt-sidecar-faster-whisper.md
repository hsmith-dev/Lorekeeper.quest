---
title: 'E0-Platform.5: `stt` sidecar with faster-whisper, and voice upload switched to it'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'fc1e1c56bab6e0e805fdde4ff4ad87260eb9d39c'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred:
  - summary: >-
      Decoded audio length has no cap: a 25 MB low-bitrate upload decodes to hours of float32 and may pass the 1280m limit.
    evidence: |-
      decode_container materialises the whole clip before any check (faster_whisper.decode_audio also
      concatenates frames). Measure peak RSS for a 25 MB opus upload on the desktop, then add STT_MAX_AUDIO_S
      or stream-decode it.
    location: >-
      src/services/stt/stt_service/models.py (decode_container)
    severity: medium (unverified)
  - summary: >-
      The single model lock has no queue bound, and work the client abandoned after its timeout keeps running.
    evidence: |-
      This is the same as ml's deferred lock-queue item. Concurrent RecordSessionPage users share one queue,
      and each queued request holds its decoded array. Needs a measured 503-on-busy policy (E4 live load).
    location: >-
      src/services/stt/stt_service/models.py (LazyModelSlot.run); app.py transcribe
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** Voice upload (`/api/ingest/voice`) runs openai-whisper `base` inside each gunicorn worker through a per-process `ThreadPoolExecutor`. That costs about 1.5 GB per loaded worker, and it is about 1.6–3.7× slower than faster-whisper at the same accuracy (SPIKE-2). There is no `stt` service for E4's Live Session to use.

**Approach:** Add `src/services/stt/`, a standalone FastAPI sidecar built the way E0-Platform.3 built `ml`. It runs faster-whisper 1.2.1 / ctranslate2 4.8.4 with the Systran `faster-whisper-base` weights baked in at a pinned revision, sha256-checked. The model loads lazily, unloads when idle, and `STT_COMPUTE_TYPE` (default `int8`, `float32` override) is configurable. It serves `/healthz`, `/v1/status` and `/v1/transcribe` (multipart audio, or PCM16 with `?format=pcm16`). Add the backend client `app/clients/stt.py` with a deterministic fake, make `transcription_service.transcribe` an async wrapper over it, switch the route, and remove openai-whisper. Add the compose services on the internal network with `STT_MEM_LIMIT`, the licence-scan matrix leg and the register entries.

## Boundaries & Constraints

**Always:**
- **Separation:** The sidecar package (`stt_service`) never imports the backend `app`. `faster_whisper`, `ctranslate2` and `av` are imported only inside the real model and decoder functions, so the HTTP app is testable with fakes.
- **Network:** `stt` has no `ports:` and no nginx route. It joins only the existing `internal: true` `models` network.
- **Offline weights:** Weights are baked at build and checked with sha256. The container runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
- **No GPU stack in the CPU image:** The default (last) Dockerfile stage installs no torch and no `nvidia-*`/`cuda-*` wheels, and a guard RUN after every pip install proves it.
- **Route contract:** The voice route keeps its 25 MB cap, its 415, its 422 on an empty transcript and its `10/minute` `user_or_ip` limit. Its response shape `{transcribed_text}` does not change, so `RecordSessionPage` / `JournalInput` work unchanged.
- **Licence register:** Every package, image and weight in the `stt` image is in `licenses/register.yaml`, and each entry records the truth. If a shipped component's licence fails the policy, the register says so and the PR reports it. The policy is never bypassed.

**Never:**
- **Files owned elsewhere:** Do not edit `.github/license-policy.toml`, `.github/workflows/backend-tests.yml`, `tests/conftest.py`, `docker-compose.dev.yml`, frontend files, `llm_provider*`, `sprint-status.yaml` or `epics.md`.
- **Other stories' work:** Do not add `docker-compose.gpu.yml` or GPU device reservations (E0-Platform.7). Do not touch `ml`, nlp/embedding/vision callers, or `main.py` lifespan (E0-Platform.6). Do not build E4 live/WebSocket work, and do not add diarization or VAD.
- **Licence workaround:** Do not build FFmpeg or PyAV from source. That is an owner decision (see Design Notes).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| health, fresh container | the baked `model.bin` is present and the model is not loaded | `GET /healthz` 200 `{"status":"ok"}`; `GET /v1/status` → `{models:[{name:"faster-whisper-base",kind:"stt",state:"not_loaded"}], compute_type, device, rss_bytes}` | — |
| health, broken bake | the model file is missing | `/healthz` 503 `{"status":"model_missing"}` | — |
| transcribe container audio | multipart `file` (webm/ogg/wav/mp3/mp4), optional form `initial_prompt` | 200 `{text, language, segments:[{start_ms,end_ms,text}], rtf}`; decoded to 16 kHz float32 and passed to the model with the prompt; state becomes `loaded` | — |
| transcribe PCM16 | `?format=pcm16`, multipart `file` = raw s16le 16 kHz mono bytes, plus `initial_prompt` | same shape; the model receives `np.frombuffer(b, "<i2").astype(float32)/32768`, and the container decoder is not called | — |
| bad input | empty file; odd-length PCM16; undecodable bytes; `format` other than `pcm16`; prompt over 2000 chars | — | 422 `{"detail": ...}` |
| too large | file over `STT_MAX_UPLOAD_BYTES` (default 32 MiB) | — | 413 |
| model fails to load | the loader raises | state `failed`; the next request tries to load again | 503 `{"detail":"speech model unavailable"}` |
| compute type | `STT_COMPUTE_TYPE` unset / `float32` / `bogus` | `int8` / `float32` is passed to the loader | `bogus` → config `ValueError` at startup |
| idle unload | loaded, unused for `STT_IDLE_UNLOAD_S` (default 600; 0 = never) | the model is dropped and the state goes back to `not_loaded`; the next request reloads it | — |
| client errors | connect error, timeout, 5xx / 4xx / malformed body | — | `ModelServiceUnavailable` / `ModelServiceError(status_code=4xx)` / `ModelServiceError` |
| client in tests | `ENVIRONMENT=test` | `get_stt_client()` returns `FakeSTTClient`: `b""` or odd PCM16 → `ModelServiceError(422)`; all-zero bytes → text `""`; otherwise deterministic non-empty text | — |
| voice route | an upload that passes the 415/413 checks | 200 `{transcribed_text}`. Errors: empty file or empty text → 422 (existing message); sidecar 4xx → 422 (same message); `ModelServiceUnavailable` or any other `ModelServiceError` → 503 `{"detail":"Speech model unavailable"}` | — |

</intent-contract>

## Code Map

- **Copy these from the ml sidecar:**
  - `src/services/ml/` provides the layout: `ml_service/{__init__,config,models,app}.py`, `bake_models.py`, `Dockerfile`, `.dockerignore`, `pytest.ini`, `requirements{,-dev}.txt`, `tests/{conftest,test_app,test_dockerfile}.py`.
  - Copy from it: `rss_bytes()`, the `ModelSlot` lock pattern, the `create_app(config, factories)` injection, the AST "no heavy imports at module level" test, and the Dockerfile static-guard test helpers (`_instructions`, `_runs`, `_is_guard`).
- `src/backend/app/clients/ml.py` -- the client pattern to mirror: the `_request` error mapping (Timeout/Transport → Unavailable, other `httpx.HTTPError` → Error, 5xx → Unavailable, 4xx → Error with `status_code`, non-JSON → Error), the `_clients` cache keyed by (url, timeout), and `get_ml_client` with the `environment == "test"` fake. Do not change ml.py.
- `src/backend/app/clients/errors.py` -- reuse `ModelServiceError` / `ModelServiceUnavailable` as they are. You may widen the module docstring to cover `stt`.
- `src/backend/app/clients/fakes.py` -- shared append point: add `FakeSTTClient` here.
- `src/backend/app/services/transcription_service.py` -- whole file replaced: the openai-whisper `_load_model`, `_executor` and `transcribe_audio` go.
- `src/backend/app/api/routes/ingest.py:67-86` -- `ingest_voice`. Drop the `ext_map`, because the sidecar sniffs the container. Keep the content-type check, the 25 MB check, the decorator and the response model.
- `src/backend/app/core/config.py` -- add after the `ml_url` block: `stt_url = "http://stt:8000"`, `stt_timeout_s: float = 300.0` (it is the read timeout for a 30 s segment on a slow CPU), and `stt_compute_type: Literal["int8","float32"] = "int8"`. The comment says it mirrors `STT_COMPUTE_TYPE`, which compose passes to the sidecar from the same `.env`.
- `src/backend/requirements.txt:20` -- remove `openai-whisper`. That drops llvmlite, more-itertools, numba, tiktoken and (on x86) triton from the backend resolve (checked with `uv pip compile` on both arches).
- `src/backend/tests/test_rate_limit.py:94` -- already asserts `ingest_voice` at `10/minute` on `user_or_ip`. It must stay green. Its `_register` helper shows how to get an auth header (needs the `promo_code` fixture).
- `src/backend/tests/test_ml_sidecar_suite.py` -- copy as `test_stt_sidecar_suite.py` pointed at `src/services/stt`. Backend CI's interpreter has fastapi 0.115, httpx, python-multipart 0.0.12, numpy<2 and pytest, which is all the sidecar's fake-model tests need.
- `docker-compose.yml`, `docker-compose.prod.yml` -- copy the `ml` service blocks for `stt`:
  - `image: lorekeeper-stt:latest`, build `./src/services/stt`, `networks: [models]`, and the same healthcheck with a `start_period` of 30s.
  - `environment`: `STT_COMPUTE_TYPE: ${STT_COMPUTE_TYPE:-int8}`, `STT_IDLE_UNLOAD_S: ${STT_IDLE_UNLOAD_S:-600}`, `STT_CPU_THREADS: ${STT_CPU_THREADS:-2}`.
  - Prod only: `restart: unless-stopped`, `deploy.resources.limits` `cpus: "2.0"`, `memory: ${STT_MEM_LIMIT:-1280m}` (AD-7 stt = 1.25g).
- `.env.example:54-62` -- add an stt block after the ml block: `STT_URL`, `STT_TIMEOUT_S`, `STT_COMPUTE_TYPE`, `STT_IDLE_UNLOAD_S`, `STT_CPU_THREADS`, `STT_MEM_LIMIT=1280m`, each commented out with its default.
- `.github/workflows/license-check.yml` (image-licenses matrix) -- add one line after `ml`: `- { image: stt, context: src/services/stt, dockerfile: src/services/stt/Dockerfile, python: true, editions: "agpl commercial" }`.
- `licenses/register.yaml`:
  - **Format:** flow-style python rows, alphabetical. A model row needs `download` + `sha256`. Rows with the same name are allowed when the versions differ.
  - **Reused rows:** add `stt` to `images` of every reused python row and of the `python` image row, then update that row's note.
  - **Remove** the rows that only openai-whisper used: `openai-whisper`, `llvmlite`, `more-itertools`, `numba`, `tiktoken`, `triton` (all `images: [backend]` only), plus the `whisper-base` model row.
- **Resolved stt lock** (`uv pip compile` with an input of fastapi==0.115.0, uvicorn==0.30.0, pydantic==2.9.0, python-multipart==0.0.12, faster-whisper==1.2.1, ctranslate2==4.8.4; `--python-version 3.11`; identical for `--python-platform x86_64-manylinux_2_28` and `aarch64-manylinux_2_28`):
  - **31 packages:** annotated-types 0.8.0, anyio 4.15.1, av 18.1.0, click 8.5.0, ctranslate2 4.8.4, fastapi, faster-whisper, filelock 4.2.6, flatbuffers 25.12.19, fsspec 2026.9.0, h11 0.16.0, hf-xet 1.8.0, httpcore2 2.16.0, httpx2 2.16.0, huggingface-hub 2.4.0, idna 3.20, numpy 2.4.6, onnxruntime 1.31.1, packaging 26.3, protobuf 7.36.2, pydantic 2.9.0, pydantic-core 2.23.2, python-multipart 0.0.12, pyyaml 6.0.3, starlette 0.38.6, tokenizers 0.23.3, tqdm 4.70.1, truststore 0.10.5, typing-extensions 4.16.0, tzdata 2026.6, uvicorn 0.30.0.
  - **Likely new to the register:** av (metadata `BSD-3-Clause`), ctranslate2 (`MIT`; the wheel bundles libgomp, GCC runtime exception), faster-whisper (`MIT`; the wheel carries the Silero VAD onnx asset, MIT), onnxruntime (`MIT License`), flatbuffers, protobuf, huggingface-hub 2.4.0 if absent.
  - **Check the rows:** `python scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact stt --emit-missing` in a venv installed from the lock. It must report 0 violations in both editions apart from the PyAV row below.
- **Weights:** `Systran/faster-whisper-base` at revision `ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66`, licence MIT. Files: `config.json`, `model.bin` (sha256 `d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9`, 145217532 bytes), `tokenizer.json`, `vocabulary.txt`. The register row's download is `https://huggingface.co/Systran/faster-whisper-base/resolve/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66/model.bin`.
- **faster-whisper API (1.2.1):**
  - `WhisperModel(path, device="cpu", compute_type=..., cpu_threads=N)`; a directory path is used as is.
  - `model.transcribe(ndarray_float32_16k, language=None, beam_size=5, initial_prompt=..., vad_filter=False)` returns `(segments_generator, info)`. Segments carry `.start`/`.end` in seconds and `.text`; `info` carries `.language`.
  - `faster_whisper.audio.decode_audio(BinaryIO, sampling_rate=16000)` decodes through PyAV. `faster_whisper/__init__` imports `av` at the top.

## Tasks & Acceptance

**Execution:**
- `src/services/stt/stt_service/config.py`:
  - **Constants:** `MODEL_NAME="faster-whisper-base"`, `MODEL_REPO`, `MODEL_REVISION`, `MODEL_SHA256`, `DEFAULT_MODEL_PATH="/models/faster-whisper-base"`, `SAMPLE_RATE=16000`, `MAX_PROMPT_CHARS=2000`, `COMPUTE_TYPES=("int8","float32","float16","int8_float16")` (the last two exist for the gpu target).
  - **`load_config(environ)` reads:** `STT_MODEL_PATH`, `STT_COMPUTE_TYPE` (default `int8`; an unknown value raises `ValueError`), `STT_DEVICE` (default `cpu`), `STT_CPU_THREADS` (default 0), `STT_IDLE_UNLOAD_S` (default 600), `STT_MAX_UPLOAD_BYTES` (default 32 MiB), `STT_LANGUAGE` (default unset = auto-detect, as today) and `STT_BEAM_SIZE` (default 5).
- `src/services/stt/stt_service/models.py`:
  - **Data types:** `Segment(start_ms,end_ms,text)` and `Transcription(text, language, segments)`.
  - **Protocols:** `SpeechModel` with `transcribe(audio: np.ndarray, initial_prompt) -> Transcription`, and `Decoder` with `(bytes) -> np.ndarray`.
  - **`FasterWhisperModel`:**
    - Builds the WhisperModel from the config.
    - Each segment's ms values come from `round(s*1000)`, and segment text is stripped.
    - `text = "".join(raw segment texts).strip()`, which matches openai-whisper's `result["text"].strip()`.
  - **`decode_container(bytes)`:** runs `decode_audio(io.BytesIO(...))` and raises `AudioDecodeError` on any decoder exception.
  - **`pcm16_to_float32(bytes)`:** raises `AudioDecodeError` on empty or odd-length input.
  - **`LazyModelSlot`:** a lock, `state` in not_loaded|loading|loaded|failed, `last_used`, `run(fn, now)`, and `unload_if_idle(now, idle_s) -> bool`. After `failed`, the next `run` tries to load again.
- `src/services/stt/stt_service/app.py`:
  - **Injection:** `create_app(config=None, model_factory=None, decoder=None, clock=time.monotonic)`.
  - **Routes:**
    - `/healthz` checks that `<model_path>/model.bin` exists.
    - `/v1/status` returns the model state, `compute_type`, `device` and `rss_bytes`.
    - `POST /v1/transcribe` is a plain `def` taking `file: UploadFile`, `initial_prompt: str | None = Form(None)` and `format: Literal["pcm16"] | None = Query(None)`. It reads at most max+1 bytes and returns 413 above the limit. It measures `rtf = elapsed / (len(samples)/16000)`, rounded to 4 places, and 0 for zero samples.
  - **Failures:** a loader failure returns 503 `speech model unavailable`, and an `AudioDecodeError` returns 422.
  - **Idle unloader:** the lifespan starts a daemon thread or asyncio task that calls `unload_if_idle` every `min(30, idle_s/4)` seconds when `idle_s > 0`, and stops it on shutdown.
  - **Module attribute:** `app = create_app()`.
- `src/services/stt/bake_models.py`:
  - **Download and check:** run `snapshot_download` at the pinned revision with `allow_patterns` set to the 4 files, into `STT_MODEL_PATH`, then verify the `model.bin` sha256 (exit 1 on a mismatch).
  - **Load check:** load `FasterWhisperModel` with the configured compute type and transcribe 1 s of zeros.
- `src/services/stt/Dockerfile`:
  - **Stages:** `FROM python:3.11-slim AS base` → `FROM base AS gpu` → `FROM base AS cpu`. The `cpu` stage is last, so it is the default build.
  - **`base` stage, in order:**
    1. `pip install -r requirements.txt`.
    2. The guard `! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]|^torch=='`.
    3. Copy the app and `bake_models.py`, then `RUN python bake_models.py`.
    4. `ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.
    5. A non-root user, `HEALTHCHECK` (start-period 30s) and `uvicorn --workers 1`.
  - **`gpu` stage:** local only and never published. It installs `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` 9.x (pin the versions you resolve), sets `LD_LIBRARY_PATH` to their `lib` dirs and sets `STT_DEVICE=cuda`.
  - **Also:** `.dockerignore`, `requirements.txt` (the full lock above plus a header that names the reproduce command), `requirements-dev.txt` (pytest, httpx) and `pytest.ini`.
- `src/services/stt/tests/{__init__,conftest,test_app,test_config,test_dockerfile}.py`:
  - **conftest:** a fake model that records the array and prompt it received, a fake decoder, a `tmp_path` model dir holding a `model.bin`, and an injected clock.
  - **test_app:** every sidecar row of the I/O matrix, plus the no-backend / no-heavy-import AST test.
  - **test_dockerfile:**
    - the guard comes after every pip install in `base`;
    - offline env after the bake;
    - `HEALTHCHECK` present;
    - the last `FROM` is not `gpu`;
    - no `torch` in the lock;
    - `faster-whisper==1.2.1` and `ctranslate2==4.8.4` are in the lock;
    - `MODEL_SHA256` and the revision equal the register's `faster-whisper-base` row (regex over the yaml text).
- `src/backend/app/clients/stt.py`:
  - **Data types:** `TranscriptSegment`, `Transcript(text, language, segments, rtf)` and `STTStatus`.
  - **`STTClient`:**
    - `transcribe(audio, *, initial_prompt=None, format=None)` posts multipart `files={"file": ("audio", audio, "application/octet-stream")}`, adds `data={"initial_prompt"}` when one is given, and sends `params={"format": format}` when one is given.
    - `status()`.
  - **Validation:** both methods validate the response shape and raise `ModelServiceError` on a mismatch.
  - **`get_stt_client(settings=None)`** follows the ml pattern.
- `src/backend/app/clients/fakes.py` -- `FakeSTTClient` (per the matrix; `status()` returns not_loaded).
- `src/backend/app/services/transcription_service.py` -- `async def transcribe(audio, *, initial_prompt=None, format=None) -> str`, which returns `(await get_stt_client().transcribe(...)).text.strip()`.
- `src/backend/app/api/routes/ingest.py`:
  - **Empty upload:** an empty upload returns 422 before the sidecar is called.
  - **Error mapping:** call `transcribe`. A `ModelServiceError` whose `status_code` is a 4xx becomes 422 with the existing message. `ModelServiceUnavailable` or any other `ModelServiceError` becomes 503 `Speech model unavailable`. Log a warning without the audio.
- `src/backend/app/core/config.py`, `src/backend/requirements.txt` -- per the Code Map.
- `src/backend/tests/test_stt_client.py`:
  - client rows via `httpx.MockTransport`, asserting the multipart field names, the `format` query and the `initial_prompt` field;
  - the fake's behaviour;
  - `get_stt_client` selection;
  - `stt_compute_type` validation;
  - `openai-whisper` and `ThreadPoolExecutor` are gone from requirements / transcription_service.
- `src/backend/tests/test_ingest_voice.py`:
  - **Route rows through the real app:** 200 with the fake text, 422 on silence, 422 on an empty upload, 415 and 413.
  - **Error mapping:** monkeypatch `app.services.transcription_service.get_stt_client` to a stub that raises Unavailable (→ 503 with the exact detail), `ModelServiceError(422)` (→ 422), and `ModelServiceError()` with no status (→ 503).
- `src/backend/tests/test_stt_sidecar_suite.py` -- the subprocess wrapper.
- `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`, `.github/workflows/license-check.yml` -- per the Code Map.
- `licenses/register.yaml` -- per the Code Map, plus the new rows:
  - The `faster-whisper-base` model row: `images: [stt]`, `download`, `sha256`, and notes naming the revision.
  - A truthful row for PyAV's bundled native libraries: name `pyav-bundled-ffmpeg`, kind `apt` (the espeak-ng precedent for bundled libs), version `av 18.1.0`.
    - The licence expression includes `LGPL-3.0-or-later AND GPL-2.0-or-later` plus the permissive codec licences.
    - The notes list `av.libs`. The GPL parts are libx264 and libx265, which `libavcodec` links against; the LGPL parts are FFmpeg 8 built with `--enable-version3`, lame, gnutls, nettle, gmp, libunistring and alsa-lib.
    - The notes also say: "OWNER DECISION REQUIRED".

**Acceptance Criteria:**
- Given backend CI, when the suite runs, then the existing tests and the new client, route and wrapper tests pass, and the wrapper runs the stt sidecar suite green.
- Given both compose files, when parsed, then `stt` has no `ports`, is attached only to `models`, and in prod has `memory: ${STT_MEM_LIMIT:-1280m}`.
- Given the licence workflow, when it runs, then the `stt` image builds (lock install, guard, bake) and is scanned. Across all the licence jobs, the only failure is the PyAV bundled-library row: register entries are checked globally, so it fails in every job. The PR reports that finding.

## Spec Change Log

### 2026-11-01 — Owner licence decision (relayed by the coordinator)
- **Trigger:** the deferred `[high]` licence row. The owner's policy is that only permissive code may be linked into a shipped process, while a separate program run as a subprocess is mere aggregation. There is to be no exception and no AGPL-only stt.
- **Amended (outside the intent contract):**
  - PyAV is never installed.
  - faster-whisper 1.2.1 is installed with `--no-deps` (`requirements-nodeps.txt`), and its real dependencies are pinned in the lock.
  - `stt_service/whisper_loader.py` satisfies `faster_whisper/audio.py`'s bare `import av` with an inert placeholder. It does this only when av is absent and touches nothing in site-packages. Any use of the placeholder raises.
  - `decode_container` runs the Debian `ffmpeg` CLI in a subprocess and reads f32le 16 kHz mono from its stdout.
  - The Dockerfile apt-installs ffmpeg. Its guards check that `import av` fails, that there is no `av==` in pip, and that ffmpeg is present.
  - The bake's decode check encodes its tones with the ffmpeg CLI.
  - Register: the av and `pyav-bundled-ffmpeg` rows are removed, and 194 apt rows are added for ffmpeg's closure (24 + 35 of them reviewed by hand). The 110 GPL/LGPL ones go on `os_aggregate_allowlist` by exact name.
- **Known-bad state avoided:** GPL libx264/libx265 mapped into the stt Python process, and every licence job red.
- **KEEP:** everything else in the review-pass code, which is unchanged.

## Review Triage Log

### 2026-11-01 — Review pass
- verdicts: 41 findings — high 1, medium 9, low 17, false 3, maybe-false 0 (rows from the blind, edge, verification-gap and intent layers, in that order; intent observations a–i count as findings)
- findings:
  - `[medium]` `[defer]` (blind) No cap on decoded length, so a large upload risks OOM. Deferred: needs a desktop RSS measurement.
  - `[medium]` `[defer]` (blind) No backpressure on the single lock, and timed-out work keeps running. Deferred, the same as ml's lock-queue item.
  - `[high]` `[defer]` (blind) The licence checks go red on main. Deferred to the owner's PyAV decision; the PR is flagged not to merge before it.
  - `[medium]` `[patch]` (blind) A natively run backend loses voice and nothing documents it. `.env.example` now explains how to run the sidecar locally and set STT_URL.
  - `[low]` `[reject]` (blind) STT_LANGUAGE, STT_BEAM_SIZE and STT_MAX_UPLOAD_BYTES are not forwarded by compose. They are sidecar-tuning knobs with sane defaults; adding them later is a one-line compose change.
  - `[medium]` `[patch]` (blind) The backend's compute-type Literal was narrower than the sidecar's. It is widened to the sidecar's set, normalised, and an AST drift test was added.
  - `[false]` `[reject]` (blind) A sidecar 413 or prompt-length 422 is shown as "speak clearly". Unreachable from the route: the backend caps at 25 MB, below the sidecar's 32 MiB, and the route sends no prompt.
  - `[low]` `[reject]` (blind) The log can't tell a timeout from a refusal. Debug convenience only; the type and status are logged.
  - `[low]` `[reject]` (blind) status() is unused, there is no depends_on, and healthz only checks the file. The admin System tab uses status (E0-Platform.6); healthz is a file check by the spec's design, so it turns healthy while the model loads lazily.
  - `[medium]` `[patch]` (blind) The real speech path is never run on real audio. Same root cause as the verification-gap decode row (patched).
  - `[low]` `[reject]` (blind) The sidecar suite runs on the backend's deps (numpy<2). This is the same interim CI hook as ml; a dedicated job is E0-QA's.
  - `[false]` `[reject]` (blind) initial_prompt is plumbed but unused by the route. By story: E4 uses the prompt path; the voice route never had one.
  - `[low]` `[reject]` (blind) Download-only packages ship in the image. Small, all registered; a builder stage is an optimisation, not a defect.
  - `[low]` `[patch]` (blind) Register notes are stale: numpy, and the pyav kind. Both notes updated.
  - `[low]` `[patch]` (blind) The fake's `format` type differs from the protocol. Typed `Literal["pcm16"] | None`; ignoring other formats was rejected as a test-only nicety.
  - `[low]` `[reject]` (edge) An inference error after load is a 500. The client maps a 500 to Unavailable, so the route answers 503; the next request retries on the same model.
  - `[low]` `[patch]` (edge) A zero-sample decode reached the real model. The route now returns an empty transcript without calling the model; test added.
  - `[medium]` `[defer]` (edge) Decoded-length OOM. Same as the blind row (deferred).
  - `[medium]` `[defer]` (edge) An orphaned inference holds the lock. Same as the blind backpressure row (deferred).
  - `[low]` `[patch]` (edge) last_used was stamped before inference. The slot now takes a clock and stamps again after fn (in a finally); tests added.
  - `[medium]` `[patch]` (edge) The compute-type mismatch fails backend startup. Same as the blind row (patched).
  - `[low]` `[reject]` (edge) Non-positive STT_MAX_UPLOAD_BYTES or STT_BEAM_SIZE are not rejected. An operator misconfiguration that fails loudly at request time; adding guards adds branches for an unlikely case.
  - `[low]` `[patch]` (edge) The numpy register note is stale. Same as the blind notes row (patched).
  - `[medium]` `[patch]` (verification-gap) The real PyAV decode path is never exercised. bake_models.py now encodes a 1 s tone to webm/opus, ogg/opus, mp3 and wav and fails the build unless each decodes to about 16000 float32 samples; it runs in the image-licenses stt build. tests/test_bake.py was added.
  - `[medium]` `[patch]` (verification-gap) No test guards sidecar ports and networks. Added src/backend/tests/test_compose_sidecars.py (ml and stt, both files, plus the prod memory values).
  - `[high]` `[defer]` (verification-gap) The licence gate is permanently red, so new problems hide behind it. Same root cause as the blind licence row (deferred to the owner).
  - `[low]` `[reject]` (intent a) healthz only checks model.bin. By design for a lazy model; the bake proves the model loads and decodes.
  - `[medium]` `[patch]` (intent b) Real transcription and decoding are tested only with fakes. Same as the verification-gap decode row (patched); the WER comparison is a desktop check.
  - `[low]` `[reject]` (intent c) No 429 test and no frontend test. test_rate_limit.py asserts the 10/minute user_or_ip decorator on ingest_voice; the response shape is unchanged; the UI run is a desktop check.
  - `[false]` `[reject]` (intent d) The 4xx→422 mapping goes beyond the AC. It keeps the existing 422 message for audio the sidecar can't read; nothing in the AC conflicts.
  - `[low]` `[patch]` (intent e) The client was a method, not the module-level `transcribe` the AC names. Added `app/clients/stt.py: transcribe(...)`; transcription_service calls it.
  - `[low]` `[reject]` (intent f) STT_MEM_LIMIT is set only in prod compose. The dev compose has no limits for any service (the ml precedent); AD-7 limits are prod.
  - `[high]` `[defer]` (intent g) The licence leg is red. Same as the blind licence row.
  - `[low]` `[reject]` (intent h) Only model.bin is checksummed. The revision pin fixes the small files (the ml precedent).
  - `[low]` `[reject]` (intent i) Scope additions (gpu target, extra knobs, prompt cap). The story's technical notes call for the gpu target; the knobs are defaults-only.
  - `[low]` `[reject]` (intent) The tested environment is not the shipped one (numpy 2.4.6 vs <2). Same as the blind suite-deps row.
  - `[low]` `[reject]` (intent) The smoke script is not wired into CI. E0-QA's job, as for ml.
  - `[low]` `[reject]` (intent) The memory limit applies only in prod. Same as intent f.
  - `[low]` `[reject]` (intent) The 503 is tested with injected exceptions, not an unreachable sidecar. test_stt_client covers connect errors and timeouts mapping to Unavailable, and the route test covers Unavailable mapping to 503.
  - `[low]` `[reject]` (intent) Rate limits are asserted only via the decorator. Same as intent c.
  - `[low]` `[reject]` (intent) The checksum check is a text parse, not a build. The build itself (image-licenses stt) runs the bake's sha256 check.

## Design Notes

**Licence finding (needs an owner decision).** faster-whisper hard-depends on PyAV (`av>=11`), and `faster_whisper/__init__` imports it. The PyPI `av` 18.1.0 wheel bundles FFmpeg 8 in `av.libs/`, and `libavcodec` there links against `libx264` and `libx265`, both GPL-2.0-or-later. Its pip metadata says only BSD-3-Clause, so the pip scan alone would pass silently. The commercial edition cannot ship GPL code. The policy also forbids GPL outside `tts` in the AGPL edition.

These are the owner's options:
- (a) Build FFmpeg (LGPL, decoders only: opus, vorbis, aac, mp3, flac, pcm) and PyAV from source in a builder stage, plus an LGPL `[[exception]]` like fpdf2's.
- (b) Have the browser send PCM16 (AudioWorklet) so the server never decodes containers. faster-whisper would still need `av` importable.
- (c) Accept the risk for the AGPL edition only.

This story records the truth and does not choose.

**Multipart for PCM16 too.** The `pcm16` path also sends a multipart `file` part. Only the `format` query tells the sidecar that the bytes are raw. One request shape keeps `initial_prompt` a form field in both paths, so a long glossary prompt never goes in a URL.

**Sidecar decodes, model sees arrays.** Decoding in the sidecar (rather than handing BinaryIO to faster-whisper) gives the duration needed for `rtf`, and the fake-model tests can then check the exact array.

## Verification

**Commands:**
- `cd src/services/stt && uv run --python 3.11 --with fastapi==0.115.0 --with httpx==0.27.2 --with python-multipart==0.0.12 --with 'numpy<2' --with pytest==8.3.0 python -m pytest -q` -- expected: all pass
- `cd src/backend && uv run --python 3.11 --with-requirements requirements-dev.txt --with pydantic-settings==2.5.0 --with fastapi==0.115.0 python -m pytest -q --noconftest tests/test_stt_client.py` -- expected: pass (route tests need Postgres, so CI covers them)
- `python -m py_compile` on every changed Python file; YAML-parse both compose files and `license-check.yml` -- expected: success
- A venv from the stt lock with `check-licenses.py --python-env --artifact stt` in both editions -- expected: only the PyAV-bundled row fails
- GitHub CI on the draft PR -- expected: backend tests green; licence legs fail only on the PyAV bundled-library row

## Auto Run Result

Status: done (the build). Merge is blocked until the owner makes the licence decision below.

**Summary:** Adds the `src/services/stt/` sidecar.
- **Stack:** faster-whisper 1.2.1 with ctranslate2 4.8.4 and a 31-package lock that is identical on x86_64 and aarch64. Systran `faster-whisper-base` is baked at revision `ebe41f70…` and its `model.bin` sha256 is checked. The model loads lazily and unloads after `STT_IDLE_UNLOAD_S` (600 by default) of idle time. `STT_COMPUTE_TYPE` defaults to `int8` and accepts `float32`.
- **Routes:** `/healthz` (checks the baked file), `/v1/status`, and `/v1/transcribe` (multipart container audio, or `?format=pcm16`, plus a form field `initial_prompt`).
- **Container:** Dockerfile stages `base` → `gpu` (local only) → `cpu` (the default). It has a no-torch/no-nvidia guard. The bake checks real decoding of webm, ogg, mp3 and wav. It runs offline as a non-root user.
- **Backend:**
  - `app/clients/stt.py` provides a client and a module-level `transcribe`, plus `FakeSTTClient`.
  - `transcription_service.transcribe` is now an async wrapper over it.
  - The voice route keeps the 415, the 413, its rate limit and the response shape. It now also returns 422 for an empty upload or a sidecar 4xx, and 503 `Speech model unavailable` for any other sidecar failure.
  - Settings `stt_url`, `stt_timeout_s` and `stt_compute_type` are added. `openai-whisper` and the ThreadPoolExecutor are removed.
- **Compose:** `stt` runs on the internal `models` network with no ports; prod sets `memory: ${STT_MEM_LIMIT:-1280m}`.
- **CI:** an `stt` image-licenses leg.
- **Register:** the new packages, the model row, and a truthful `pyav-bundled-ffmpeg` row. The rows that only openai-whisper used are removed.

**Files changed:**
- **`src/services/stt/` (new):** the sidecar app, Dockerfile, lock, bake script and tests.
- **`src/backend/app/clients/{stt,fakes,errors}.py`:** the client, the fake, and an updated docstring.
- **`app/services/transcription_service.py`:** now the wrapper.
- **`app/api/routes/ingest.py`:** error mapping.
- **`app/core/config.py`:** the stt settings.
- **`requirements.txt`:** openai-whisper removed.
- **Backend tests:** `test_stt_client.py`, `test_ingest_voice.py`, `test_stt_sidecar_suite.py` and `test_compose_sidecars.py`.
- **Compose and config:** `docker-compose.yml`, `docker-compose.prod.yml` and `.env.example` gain the stt service and its settings.
- **`.github/workflows/license-check.yml`:** the stt matrix line.
- **`licenses/register.yaml`:** the rows above.
- **E0-QA.10 ratchets, shrunk as their failure messages instruct:** `src/backend/.importlinter` and `scripts/test_import_ratchet.py` no longer list the `transcription_service -> whisper` ignore. `scripts/model_packages_baseline.txt` and `scripts/test_check_model_packages.py` no longer list openai-whisper.

**Review:** 41 findings (see the triage log).
- **Patched (13 rows):**
  - medium: real decode check in the bake; compose isolation test; compute-type parity; documenting native dev.
  - low: zero-sample guard; `last_used` stamped after inference; module-level `transcribe`; fake typing; register notes.
- **Deferred (3):** the licence red, the decoded-length cap, and lock backpressure.
- **Rejected:** each one has its reason in the triage log.
- **Sprint-sync:** skipped, because the orchestrator owns sprint-status.yaml.

**Follow-up review recommended: true.** Four medium entries were patched. The unverified risk is the real stt image:
- the lock install;
- the bake, with its new PyAV encode/decode check, against the real faster-whisper;
- the guard.

These have run only in CI's image build, never locally.

**Verification:**
- Sidecar suite: 50 passed, 1 skipped (the real-audio decode test needs `av` and `faster_whisper`).
- `test_stt_client.py` and `test_compose_sidecars.py`: 65 passed.
- Voice-route tests: 15 passed with stubbed auth and no database. Backend CI runs them against Postgres.
- E0-QA.10 gate tests: 81 passed. `lint-imports`: 5 kept, 0 broken. `check_memory_budget.py` and `check_model_packages.py` are OK.
- `check-licenses --artifact stt` in a venv built from the lock: the PyAV row is the only failure.

### Needs desktop verification
- **Transcript parity:** transcribe the same clip with openai-whisper base in the old backend image and with the sidecar (`curl -F file=@clip.webm http://stt:8000/v1/transcribe` from the backend container), and diff the text or compute a WER. Also run it once with `STT_COMPUTE_TYPE=float32`.
- **Latency and memory:** chunk latency and peak RSS for 15 s and 30 s chunks on an x86 CPU (int8 vs float32) and with `docker build --target gpu`. Use `docker stats` and `/v1/status` `rss_bytes`. Also measure peak RSS on a 25 MB opus upload, which settles the deferred decoded-length cap.
- **Build and offline health:** `docker build -t lorekeeper-stt:latest src/services/stt`, then `scripts/sidecar_smoke.sh stt`, which should print `stt: healthy`.
- **Compose:** `docker compose -f docker-compose.prod.yml config -q`, then `up -d stt backend`. `docker port` shows nothing for stt.
- **Real voice upload:** record and upload on RecordSessionPage and through JournalInput's voice button. Stop stt and check that the UI shows the transcription error and the API returns 503 `Speech model unavailable`.
- **Idle unload:** with `STT_IDLE_UNLOAD_S=60`, check that `/v1/status` goes from `loaded` back to `not_loaded` and that RSS drops.

**Residual risks:**
- **Licence (owner decision):** every licence job fails on `pyav-bundled-ffmpeg`. Inside the av wheel, `libavcodec` links against libx264/libx265, which are GPL-2.0+.
- **Unbounded decode memory:** decoded length has no cap.
- **No queue bound:** requests wait on the single lock with no limit.

### Rework: licence fix and rebase (2026-11-01, coordinator request)

**Licence:**
- PyAV is gone. faster-whisper is installed `--no-deps`, and `stt_service/whisper_loader.py` makes its top-level `import av` resolve to an inert placeholder, but only when PyAV is genuinely absent. It edits nothing in site-packages, and any use of the placeholder raises `AvNotInstalled`.
- Uploads are decoded by the Debian `ffmpeg` CLI in a subprocess. The upload goes to a temp file, because MP4 needs seeking, and ffmpeg writes f32le 16 kHz mono to stdout. Errors map as follows: a non-zero exit or a timeout gives 422; a missing binary gives a 500, which the client sees as Unavailable and the route returns as 503.
- Dockerfile guards: `import av` fails, `pip list` has no `av==`, the ffmpeg CLI is present, and faster_whisper imports through the placeholder.
- Register and policy:
  - 194 apt rows for ffmpeg's closure, with `images: [stt]`. 35 of them had free-text copyright files and were reviewed as MIT/X11/HPND. 24 had non-SPDX Debian names and were reviewed with `scanned_license` pinned.
  - The 110 GPL/LGPL packages go on `os_aggregate_allowlist` by exact name, under a commented stt block.
  - Removed the `av` and `pyav-bundled-ffmpeg` rows.
- **OWNER TO CONFIRM**, flagged in the row notes:
  - libgsm1: TU-Berlin-2.0, recorded as HPND.
  - libunibreak6: the Unicode data licence, recorded as HPND.
  - libmysofa1: ships two MIT KEMAR HRTF `.sofa` data files.

**Rebase onto main (#29–#45):**
- Valkey rename kept, and `stt` added to both compose files.
- Register merged by (name, version), with the images lists unioned.
- `fakes.py` keeps both sides.
- The E0-QA.10 ratchets shrink: the `transcription_service -> whisper` ignore and the openai-whisper baseline entry are gone.

**Verified on the desktop (x86, RTX box):**
- **Image build:** it builds, and the bake passes: sha256, the ffmpeg encode/decode check of webm, ogg, mp3, wav and mp4, and loading int8. `python -c "import av"` gives ModuleNotFoundError.
- **Sidecar suite in the image:** 59 passed, 0 skipped. That includes the real-ffmpeg decode, the bake's real-audio check, and the av-absent test.
- **End to end:** a 67 s TTRPG clip (macOS `say`) was converted to webm/opus, ogg, mp3, m4a and wav and sent to `/v1/transcribe`. All five returned the same transcript, with RTF about 0.034 unthrottled. PCM16 also worked, an undecodable upload got 422, and `/v1/status` went from not_loaded to loaded. RSS was about 350 MB, and `/proc/1/maps` shows no FFmpeg library in the uvicorn process.
- **Under the prod limits** (`--cpus 2 --memory 1280m`, `STT_CPU_THREADS=2`):
  - 15 s webm chunks took 0.93–1.29 s (RTF 0.06–0.08), with RSS around 325 MiB.
  - WER against the script was 0.121 without `initial_prompt` and 0.049 with the campaign names as the prompt.
- **In-image licence scan,** `check-licenses --python-env --os-packages --artifact stt`, in both editions: python 0, apt 0 (292 packages), register entries 0.
- **Locally:** the `scripts/` tests pass (247, including `test_real_register_is_valid`), and `--check-artifacts` is clean.

**Still needs desktop verification:**
- The openai-whisper side-by-side on the same clip.
- The GPU target (`docker build --target gpu`, plus E0-Platform.7's compose override).
- Compose bring-up with a real voice upload through the UI.

**Cost:** the image is 1.59 GB. Debian's ffmpeg pulls in Mesa, LLVM and X11 through libavdevice. A slimmer decoder-only ffmpeg would need an owner-reviewed policy rule for a source-built binary.
