---
title: 'E0-QA.7 Licence register and strict commercial mode'
type: 'feature'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
warnings: []
deferred:
  - summary: >-
      Workflow paths filter does not trigger on new baked artifacts under site/, nginx/, models/, assets/, so an unregistered font or weight can merge green.
    evidence: |-
      license-check.yml paths lists only requirements, package files, policy, scripts and licenses/**. E0-QA.6 removes the paths filter entirely.
    location: >-
      .github/workflows/license-check.yml
    severity: medium
  - summary: >-
      Strict mode has no rule for base-OS packages (glibc LGPL, busybox/bash GPL) that every shipped image carries; the E0-QA.8 apt scan needs an OS-base-layer / mere-aggregation rule.
    evidence: |-
      [strict] fails GPL and non-allowlisted LGPL for kind apt; python:3.11-slim and the alpine images contain such packages. No apt scan exists yet (E0-QA.8).
    location: >-
      .github/license-policy.toml [strict]
    severity: medium
  - summary: >-
      redis:7-alpine resolves to Redis 7.4.x (RSALv2/SSPLv1); recorded as a fourth OWNER TO CONFIRM exception that E0-QA.9 (which names three) must also cover, or pin redis:7.2-alpine / valkey.
    evidence: |-
      Implementer checked the running container version; E0-QA.9 lists only fpdf2, python-bidi and caniuse-lite.
    location: >-
      .github/license-policy.toml
    severity: medium
  - summary: >-
      Download-only model and font sha256 values are recorded but never verified against what installers fetch.
    evidence: |-
      check_artifacts skips entries without `artifact`; sentence-transformers, whisper, easyocr, Ollama and Google Fonts fetch without reading the register. Natural owners: E0-QA.8 or the E0-Platform sidecars.
    location: >-
      scripts/check-licenses.py check_artifacts
    severity: low
  - summary: >-
      kokoro, kokoro-onnx, misaki, phonemizer and espeakng-loader are not in [deny.packages] for web/worker scans.
    evidence: |-
      AD-16 image rule; epics assign this gate to CI-3 in a separate E0-QA story.
    location: >-
      .github/license-policy.toml [deny.packages]
    severity: low
  - summary: >-
      cairo (WeasyPrint) is not on system_lib_allowlist; add it when E8 installs the WeasyPrint apt libraries.
    evidence: |-
      Story AC names libvips, Pango, HarfBuzz and GLib only; addendum F lists cairo next to Pango and HarfBuzz.
    location: >-
      .github/license-policy.toml system_lib_allowlist
    severity: low
  - summary: >-
      Register entries that no scan matches (removed or renamed packages) are never reported, so the inventory can collect stale rows.
    evidence: |-
      run_register reports version drift only as informational and never lists unmatched python/npm entries.
    location: >-
      scripts/check-licenses.py run_register
    severity: low
---

<intent-contract>

## Intent

**Problem:** The licence gate (E0-QA.2) checks only that each scanned package's licence is on an allowlist. There is no inventory of what Lorekeeper ships (packages, images, apt libraries, models, voices, fonts), no notion of the `agpl`/`commercial` editions (AD-16), and no check that baked weights and fonts are recorded.

**Approach:** Add `licenses/register.yaml` as the inventory and teach `scripts/check-licenses.py` a `--register` mode that (a) requires every scanned Python/npm package to have an entry whose licence matches the scan, (b) applies edition rules selected by `LOREKEEPER_EDITION` (or `--edition`), and (c) runs a register-vs-artifacts check for `model`/`voice`/`font` entries. `.github/license-policy.toml` stays the allowlist/aliases/exceptions file and gains the dynamic-LGPL system-library allowlist, denied packages and the AGPL-only image list. CI runs both editions as matrix legs.

## Boundaries & Constraints

**Always:**
- Register entry fields: `name`, `kind ∈ {python, npm, image, apt, model, voice, font}`, `version`, `license` (SPDX), `source_url`, `editions ⊆ {agpl, commercial}`, `notes`; `model`/`voice`/`font` also need `artifact` (repo path) or `download` (URL) plus `sha256`. Optional `images` (which shipped images carry it), `scanned_license` (raw metadata string pin when the metadata is not SPDX or is wrong), `pip_package` (model shipped as a pip package, e.g. spaCy).
- Register has one entry per package installed by the CI CPU-torch install of `src/backend/requirements.txt` and per `package-lock.json` package (shipped and build-time), the five base-image families, the five bundled models and the fonts; plus a `rejected:` list (PRD addendum F) with reasons, and the LIC-1 espeak-ng entry (`editions: [agpl]`, `images: [tts]`, deferred non-GPL pronunciation path in `notes`).
- Strict (`commercial`): fails on any entry in the commercial edition, or scan result, whose licence is GPL/AGPL/LGPL (unless an `apt` entry matching the dynamic system-library allowlist: libvips, Pango, HarfBuzz, GLib), non-commercial, Hippocratic or unknown; and on any entry whose `editions` excludes `commercial` but which is present in a commercial artifact (found in the scan, or `images` names an image other than the AGPL-only `tts`).
- `agpl`: GPL-family entries pass only when `editions == [agpl]` and `images == [tts]`; GPL-family scan results pass only when the scanned `--artifact` is `tts` and the entry is `[agpl]`.
- Owner-approved `[[exception]]` entries in the policy keep working in both editions (E0-QA.9 tightens this later). `pyvips-binary` (`pyvips[binary]`) is denied outright.
- Without `--register`, the script behaves exactly as today.
- `pyyaml` is a dev-only dependency of the checker (`requirements-dev.txt`, CI install step).

**Never:**
- No `[[exception]]` or register entry for the NVIDIA CUDA wheels / `triton` / CUDA torch (E0-QA.8 / E0-Platform.2 own that); they must fail when the CUDA image is scanned.
- No image building or apt scanning in CI (E0-QA.8). No removal of the `paths:` filter (E0-QA.6), beyond adding `licenses/**` to it.
- Don't edit `sprint-status.yaml` or `epics.md`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| CI CPU install, both editions | `--python-env --register` | 0 violations, exit 0 | — |
| npm, both editions | `--npm npm.json --register` | 0 violations, exit 0 | — |
| Unregistered package | package installed, no entry | FAIL "no register entry" | exit 1 |
| Licence drift | entry `MIT`, scan `GPL-3.0` | FAIL "register says X, scan says Y" | exit 1 |
| CUDA image | nvidia-* wheels installed | FAIL per wheel (unregistered, licence) | exit 1, reported not excepted |
| AGPL-only entry in commercial artifact | `[agpl]` entry found in scan | FAIL in commercial; OK in agpl only if tts artifact | exit 1 |
| GPL entry outside tts | `[agpl]` GPL entry with `images: [backend]` | FAIL in agpl mode | exit 1 |
| Baked artifact unregistered | `*.woff2/.gguf/...` tracked in git, no entry `artifact` | FAIL | exit 1 |
| sha256 mismatch / missing | artifact file hash ≠ register | FAIL | exit 1 |
| Bad edition value | `LOREKEEPER_EDITION=foo` | argparse-style error | exit 2 |

</intent-contract>

## Code Map

- `scripts/check-licenses.py` -- existing scanner: `Policy` (allow/aliases/deny/exceptions, `term_ok`, `license_ok`), `python_license`, `load_python_env`, `load_npm`, `check`, `main`. Extend; keep the non-register path unchanged.
- `.github/license-policy.toml` -- allowlist, aliases, deny patterns, `[ignore]`, 3 `[[exception]]`s (fpdf2, python-bidi, caniuse-lite). Add `[strict]` tables.
- `.github/workflows/license-check.yml` -- `backend` (CPU-index pip install, `--python-env`) and `frontend` (license-checker-rseidelsohn@4.4.2) jobs. Add edition matrix, `--register`, artifacts job, `licenses/**` path.
- `src/backend/requirements.txt` / `requirements-dev.txt` -- runtime set; add `pyyaml` to dev.
- `src/backend/Dockerfile.prod`, `docker-compose*.yml`, `nginx/Dockerfile`, `src/frontend/Dockerfile` -- base images: `python:3.11-slim`, `pgvector/pgvector:pg16`, `redis:7-alpine`, `nginx:1.27-alpine`, `ollama/ollama`, `node:20-alpine` (build stage).
- Models: `app/services/embedding_service.py` (all-MiniLM-L6-v2), `nlp_service.py` (en_core_web_trf, baked in Dockerfile), `transcription_service.py` (whisper base), `vision_service.py` (EasyOCR en), GGUF via `scripts/` Hub publish / install. Fonts: `site/fonts/*.woff2` (tracked), Google Fonts in `src/frontend/index.html`.
- Desktop image `lorekeeper-backend-test` -- CUDA torch + 15 nvidia wheels + triton (expected failures).

## Tasks & Acceptance

**Execution:**
- `.github/license-policy.toml` -- add `[strict]` with `gpl_patterns`, `bad_patterns`, `system_lib_allowlist` (apt name regexes), `agpl_only_images = ["tts"]`, `[deny] packages.python = ["pyvips-binary"]`, `[artifacts]` extensions + roots -- policy stays the rule file.
- `scripts/check-licenses.py` -- add `--register`, `--edition` (default `$LOREKEEPER_EDITION` or `commercial`), `--artifact`, `--check-artifacts`, `--emit-missing` (prints YAML stubs for unregistered scanned packages); implement register validation, licence-vs-scan comparison, edition rules, register-vs-artifacts -- the gate.
- `licenses/register.yaml` -- seed inventory (generated stubs, hand-corrected licences), images, models with sha256, fonts, espeak-ng, rejected list.
- `scripts/test_check_licenses.py` -- pytest unit tests for the matrix rows using temp registers/policies.
- `.github/workflows/license-check.yml` -- `edition: [agpl, commercial]` matrix on backend and frontend, `--register`, artifacts job, checker unit tests, pyyaml install.
- `src/backend/requirements-dev.txt` -- add `pyyaml`.

**Acceptance Criteria:**
- Given the CI CPU-torch install, when the checker runs with `--register` in each edition, then it passes.
- Given the `lorekeeper-backend-test` CUDA image, when the checker runs inside it, then the NVIDIA/triton wheels fail and are reported (no exceptions added).
- Given `--check-artifacts`, when run on the repo, then every model/voice/font entry has artifact-or-download plus sha256, tracked artifacts match their hash, and an untracked-in-register baked artifact fails.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 33 findings — high 0, medium 5, low 20, false 8, maybe-false 0
- findings:
  - `[low]` `reject` (intent) strict LGPL still honours owner [[exception]]s (reading R2', not literal R2) — deliberate: E0-QA.9 owns failing unconfirmed exceptions in commercial; stated in Boundaries.
  - `[false]` `reject` (intent) "commercial artifact" decided from declared `images` / `--artifact`, not by inspecting built images — image inspection is E0-QA.8 in the story chain; this story scans packages.
  - `[low]` `reject` (intent) the tts agpl rule is exercised only by unit tests — no tts image exists yet (E5); the rule is covered by tests.
  - `[false]` `reject` (intent) extra changes (paths `licenses/**`, epic-2-context.md, new policy tables) — the paths entry is needed for register edits to run the gate; the context file is a workflow artefact; the policy stays the rule file as the story says.
  - `[medium]` `patch` (verification-gap) checker tests not in the paths filter — added `scripts/test_check_licenses.py` to both paths lists.
  - `[medium]` `defer` (verification-gap) artifact roots not in the paths filter — E0-QA.6 removes the filter.
  - `[medium]` `patch` (verification-gap + other findings) greedy `[^;]*` LGPL patterns classify mixed LGPL+GPL strings as lgpl (reproduced) — patterns tightened; test_classify_mixed_lgpl_gpl added (9 cases).
  - `[low]` `defer` (blind) kokoro/espeak packages not denied — the CI-3 gate is owned by another story.
  - `[low]` `defer` (blind) cairo not on the allowlist — the story names four libraries; for E8.
  - `[medium]` `defer` (blind) base-OS GPL/LGPL apt packages unhandled — E0-QA.8 apt scan.
  - `[false]` `reject` (blind) apt/image entries lack sha256 — the story AC requires artifact+sha256 only for model/voice/font.
  - `[low]` `defer` (blind) download sha256 never verified — for E0-QA.8 / E0-Platform.
  - `[low]` `patch` (blind) three font hashes only in notes — split into their own font entries with download+sha256.
  - `[low]` `defer` (blind) stale/unmatched entries never reported.
  - `[low]` `patch` (blind) crash on an entry with no licence — invalid entries are reported as schema errors and left out of the index and checks; test added.
  - `[low]` `patch` (blind) unquoted YAML numbers coerced — non-string fields are now schema errors; test added.
  - `[medium]` `defer` (blind) redis is a fourth OWNER TO CONFIRM exception E0-QA.9 does not name — owner decision.
  - `[false]` `reject` (blind) build-time npm packages treated as distributed — intentional since E0-QA.2 (build tooling injects code into the bundle); the story says shipped and build-time.
  - `[false]` `reject` (blind) the backend matrix scans twice — the story explicitly requires two edition matrix legs.
  - `[low]` `patch` (blind) untested paths — added an image-kind exception test and a denied-in-register test; the rest (roots filter, os.walk fallback, first-candidate fallback) are rare.
  - `[low]` `reject` (blind) no contributor docs — docs/LICENSING.md belongs to E0-QA.8; the header comments and --help cover usage.
  - `[low]` `patch` (edge) label() KeyError on a missing name — label uses .get and invalid entries are skipped.
  - `[low]` `patch` (edge) license_matches KeyError on a missing licence — same fix.
  - `[low]` `patch` (edge) a list/mapping kind crashes — a non-string kind/name is a schema error.
  - `[low]` `patch` (edge) register licence not normalised (parentheses) — the register side is normalised too; test added.
  - `[low]` `reject` (edge) OR operand order — register rows are generated from scans, so the order matches; the fix adds complexity.
  - `[low]` `reject` (edge) stale-exception message less specific than plain mode — it still fails; message only.
  - `[false]` `reject` (edge) absolute or `..` artifact path — the register is reviewed in-repo; no reachable harm shown.
  - `[low]` `patch` (edge) unquoted float versions — covered by the schema-error fix.
  - `[false]` `reject` (edge) overlapping comma-listed versions — no such rows; find() still licence-checks.
  - `[false]` `reject` (edge) non-UTF-8 tracked filenames — none exist.
  - `[low]` `patch` (edge) a denied package in the register is not flagged — check_register_entries now fails it; test added.
  - `[low]` `reject` (edge) triton is registered although the spec's Never-list says it must fail — triton is MIT and openai-whisper installs it on linux x86_64 even in the CPU-only CI install, so without an entry CI can never pass. The NVIDIA and cuda-* wheels still fail. The fix would be to edit the spec; noted in Auto Run Result.

## Design Notes

Licence comparison: the scan string is normalised to SPDX (split pip's `; ` alternatives into ` OR `, map each term through `[aliases]`) and compared case-insensitively to `license`; if the entry has `scanned_license`, the raw scan string must equal it instead (lets the register hold the true SPDX id when metadata says e.g. "BSD License"). Version differences are informational only, so routine bumps don't fail; licence changes do.

## Verification

**Desktop:** `ssh harrison@100.119.62.5` (login shell is fish: wrap commands in `bash -lc '...'`). Use run dir `~/lorekeeper-dev/runs/e0qa7` (rsync `scripts/`, `licenses/`, `.github/`, `src/backend/requirements*.txt` there). Docker is available there; the `lorekeeper-backend-test` image is cached. Do not touch other run dirs, the Ollama model or databases. Node/npm work happens on the Mac (`cd src/frontend && npm ci`).

**Commands:**
- `python -m pytest -q scripts/test_check_licenses.py` -- all pass
- desktop: CPU-index install in `python:3.11-slim`, then `check-licenses.py --python-env --register licenses/register.yaml --edition {agpl,commercial}` -- exit 0
- desktop: same inside `lorekeeper-backend-test` -- exit 1, only nvidia-*/triton/torch(+cuda) related failures
- `npm ci` + license-checker, then `--npm ... --register` both editions -- exit 0
- `check-licenses.py --check-artifacts --register licenses/register.yaml` -- exit 0
- workflow YAML validates (action-validator/actionlint)

## Auto Run Result

Status: done

**Summary:** `licenses/register.yaml` has 621 entries: 128 Python packages, the npm lockfile packages (including the per-platform binaries), 6 images, espeak-ng (apt, `[agpl]`, `images: [tts]`, LIC-1 findings and the deferred non-GPL pronunciation path), 7 models and the fonts, with sha256 on every model and font entry, plus the 8 rejected items from addendum F. `scripts/check-licenses.py` gains a `--register` mode with `--edition` / `LOREKEEPER_EDITION` (default commercial), `--artifact`, `--check-artifacts` and `--emit-missing`. The policy gains `[strict]`, `[deny.packages]` (pyvips-binary), `[artifacts]`, PostgreSQL and OFL-1.1, and a redis image exception marked OWNER TO CONFIRM. The workflow runs agpl and commercial matrix legs for backend and frontend, plus a new `register` job (unit tests and the artifacts check).

**Files:** `scripts/check-licenses.py` (register mode), `scripts/test_check_licenses.py` (56 tests), `licenses/register.yaml` (inventory), `.github/license-policy.toml` (strict rules), `.github/workflows/license-check.yml` (matrix and register job), `src/backend/requirements-dev.txt` (pyyaml==6.0.3), `_bmad-output/implementation-artifacts/epic-2-context.md` (compiled epic context).

**Review:** 12 patches applied (2 medium, 10 low), 7 deferred (frontmatter), 14 rejected with reasons in the triage log. followup_review_recommended: false.

**Verification:**
- Unit tests: 56/56 pass.
- `--check-artifacts`: exit 0 in both editions.
- CPU-torch install (python:3.11-slim, the CI path): exit 0 in both editions, 125 packages, 0 violations.
- `lorekeeper-backend-test` CUDA image: exit 1 in both editions with 18 violations: 15 nvidia-* wheels plus cuda-bindings, cuda-pathfinder and cuda-toolkit. These are expected until E0-Platform.2; no exceptions were added.
- npm scan: exit 0 in both editions.
- actionlint: clean.
- The backend pytest suite was not run because no backend code changed.

**Spec deviation:** triton is registered (MIT) because openai-whisper installs it on linux x86_64 even in the CPU-only CI install. The intent-contract's Never-list wrongly assumed it was CUDA-only.

**Residual risks:** the redis licence needs an owner decision; the Google Fonts hashes may go stale; E0-QA.6 will conflict on the `license-check.yml` paths; apt and base-OS rules are left to E0-QA.8.
