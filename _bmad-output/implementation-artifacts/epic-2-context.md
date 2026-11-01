# Epic 2 Context: Trustworthy tests, CI gates and evaluation harness

<!-- Generated from planning artifacts. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Make every merge trustworthy for the owner and capstone reviewers. Tests build the schema from Alembic migrations against the dev pgvector Postgres. CI runs on `main` and on every PR with no path filters. A licence gate covers everything shipped (packages, images, apt libraries, models, voices, fonts) and protects the commercial edition. The EV-4 spoiler-leak suite is a zero-leak hard gate, and benchmarks plus the demo seed can be reproduced offline. This is Phase 0 substrate: other epics append probes, register entries, gate steps and benchmark rows to what this epic builds.

## Stories

- Story 2.1 (E0-QA.1): Backend CI runs on `main` (Done)
- Story 2.2 (E0-QA.2): Dependency licence gate for Python and npm packages (Done)
- Story 2.3 (E0-QA.3): One GitHub Pages deployer (Done)
- Story 2.4 (E0-QA.4): The test database URL can be overridden from the environment
- Story 2.5 (E0-QA.5): Tests build the schema from Alembic migrations
- Story 2.6 (E0-QA.6): Migration-chain gates, and CI with no path filters
- Story 2.7 (E0-QA.7): Licence register and strict commercial mode
- Story 2.8 (E0-QA.8): The licence check scans the Docker images we actually ship
- Story 2.9 (E0-QA.9): Owner confirms or replaces the three licence exceptions
- Story 2.10 (E0-QA.10): Structural CI gates: layers, model packages, table owners, enum sync, memory sum
- Story 2.11 (E0-QA.11): EV-4 harness scaffolding: route enumeration, actors and probe families
- Story 2.12 (E0-QA.12): Demo seed and the shared eval-script scaffold
- Story 2.13 (E0-QA.13): EV-4 probes for every existing route
- Story 2.14 (E0-QA.14): EV-4 is a zero-leak hard gate, with chat and captured-context probes
- Story 2.15 (E0-QA.15): EV-5 benchmark suite and the x86 spike re-run

## Requirements & Constraints

**Licensing (most relevant to E0-QA.7 to E0-QA.9):**
- Every dependency, base image, apt package, model weight, voice and font must be distributable under both AGPL and the commercial licence. A single licence register lists all of them, and any PR that adds one must update the register in the same PR.
- CI runs the licence gate on every PR and on `main`, with no path filter. It fails the commercial build on GPL, AGPL, statically linked or other LGPL, non-commercial, Hippocratic (ethical-use) or unknown licences.
- Only dynamically linked LGPL system libraries are allowed: libvips from apt, Pango, HarfBuzz and GLib (cairo is also listed as LGPL/MIT, dynamically linked, for WeasyPrint). `pyvips[binary]` is denied.
- A register-vs-artifact check covers weights, voices, fonts and system packages: each needs an artifact path or download source and a `sha256`, and a baked artifact with no entry fails.
- espeak-ng (GPL-3.0+, bundled by `espeakng-loader` and pulled in by `kokoro`/kokoro-onnx/misaki) is excluded from the commercial build. It exists only in the optional `tts` container of the AGPL build. Without it, fantasy proper nouns are silently dropped. A non-GPL pronunciation path (Entity-name lexicon as Kokoro phoneme overrides) is a deferred spike. Legal review is an owner action.
- Known licence seed: OK for commercial: Ollama/llama.cpp (MIT), RapidFuzz (MIT), nli-deberta-v3 (Apache-2.0), faster-whisper (MIT), Kokoro-82M weights (Apache-2.0), WeasyPrint (BSD), Leaflet (BSD-2), Sigma.js/graphology/@react-sigma (MIT), pgvector (PostgreSQL), book fonts under SIL OFL 1.1, pyannote community-1 (code MIT, weights CC-BY-4.0, attribution). Still to verify: Silero VAD, kokoro-onnx/Kokoro-FastAPI/misaki code, arq/RQ.
- Rejected, and to be recorded with reasons: Piper (GPL-3.0), XTTS-v2 (CPML), F5-TTS (non-commercial), MiniCheck-7B (non-commercial), GLiNER v0/v1 (non-commercial), EbookLib (AGPL), Pandoc (GPL), react-leaflet (Hippocratic-2.1).
- Three current exceptions (fpdf2 LGPL-3.0, python-bidi LGPL via easyocr, caniuse-lite CC-BY-4.0) are marked `OWNER TO CONFIRM`. Commercial mode must eventually fail on unconfirmed exceptions (E0-QA.9).
- Known gap: CUDA torch in the backend image pulls in about 15 NVIDIA-proprietary wheels plus `triton`. The CPU-only CI install never sees them. They are tracked as pending until the AD-1 refactor removes torch from web and worker. GPU-image redistribution under the NVIDIA EULA is an open owner decision.

**Tests and evals:**
- Brownfield migrations are forward-only and safe at boot. They are tested on an empty DB and on a seeded copy of the current schema (head `a3e7c1f9d258`).
- Players never see GM-only content. EV-4 runs in CI and must have 0 leaks before release, and a route with no probe or exemption fails.
- NFR-6 latency targets stay provisional until the x86 re-run. Any reset needs owner sign-off in `.memlog.md`.
- Every eval runs offline on the committed demo seed, with no model download.
- The frontend has no test runner, so `tsc` strict stays its gate and EV-4 runs against the API.

## Technical Decisions

- **Editions:** `LOREKEEPER_EDITION ∈ {agpl, commercial}` is both a build arg and a setting. `commercial` forces `TTS_PROVIDER=none` (browser speech), leaves out the `tts` compose profile, and runs the licence gate in strict mode. The `tts` image is permitted only when the edition is `agpl`. No backend image may install `kokoro`, `kokoro-onnx`, `misaki`, `phonemizer` or `espeakng-loader`.
- **Licence files:** `licenses/register.yaml` is the inventory. Each entry has `name`, `kind ∈ {python, npm, image, apt, model, voice, font}`, `version`, `license` (SPDX), `source_url`, `editions ⊆ {agpl, commercial}` and `notes`, plus `artifact`/`sha256` for models, voices and fonts. `.github/license-policy.toml` stays the scanner's allowlist, aliases, exceptions and (from E0-QA.8) `[[pending]]` file. The checker is `scripts/check-licenses.py` (`--python-env`, `--npm`, adding `--register`), with `pyyaml` as a dev-only checker dependency. `license-check.yml` runs both editions as matrix legs.
- **Scans:** `pip-licenses`/PEP 639 metadata on the web, worker, ml and stt images. `license-checker-rseidelsohn` on the frontend. An apt scan via `dpkg-query` plus `/usr/share/doc/*/copyright`. The checker is mounted into the image, never installed in it. Adding an image is one matrix line.
- **Test substrate:** `TEST_DATABASE_URL` (default `postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test`, and the DB name must end in `_test`). The schema comes from `alembic upgrade head`, and `create_all` is removed. `ENVIRONMENT=test` and `JOBS_EAGER=1` turn on the fakes. `migrations/env.py` imports the whole `app.db.models` package.
- **Gates:** `.github/workflows/gates.yml` is the one place every structural gate is listed (import-linter layers, model-package ratchet, table-owner parser, StrEnum↔CHECK sync, memory sum ≤ 14.5 GB, EV-4). Baselines can only shrink.
- **EV-4:** `tests/ev4/` enumerates `app.routes` and nginx locations using nginx's real matching order. It provides the canary seed, the actors (`gm_owner`, `anon_share`, `player`, `cross_gm_player`) and the probe families. Each feature appends `tests/ev4/probes/<feature>.py`.
- **Evals:** `scripts/eval_<name>.py` on `scripts/eval_common.py` produce `docs/<NAME>_EVAL.md` in the RETRIEVAL_EVAL format, run on `seeds/demo_campaign.json` loaded by `scripts/seed_demo.py` (idempotent on `seed_id`, writes through the ORM).
- **Ownership:** this epic owns `tests/conftest.py`, `tests/ev4/`, the CI workflows, the import-linter config, `licenses/`, `seeds/`, `scripts/seed_demo.py`, `docs/BENCHMARKS.md` and `docs/SPOILER_EVAL.md`. It owns no tables.

## Cross-Story Dependencies

- Licence chain: E0-QA.2 (done) → E0-QA.7 → E0-QA.8 and E0-QA.9. E0-QA.10 also needs E0-QA.7, because import-linter must be registered.
- E0-QA.7 and E0-QA.6 both edit `license-check.yml`: E0-QA.7 adds the edition matrix and E0-QA.6 removes the `paths:` filter. They are in different build waves, so expect a rebase.
- Test chain: E0-QA.4 → E0-QA.5 → E0-QA.6 / E0-QA.11 / E0-QA.12 → E0-QA.15. E0-QA.11 also needs `gates.yml` from E0-QA.10.
- EV-4 probes (E0-QA.13/14) need E0-Access.4–8, .12 and .13, plus E0-LLM.5 (fake provider and context-capture hook).
- E0-Platform (AD-1 and the CPU-only torch story) clears the CUDA wheel pending entries and moves python-bidi into the `ml` image. E8 replaces fpdf2 with WeasyPrint. E5 adds the AGPL-only `tts` image to the agpl leg. Every later epic adds its register entries in the same PR.
