---
title: 'E0-Platform.2: CPU-only torch in the backend image (closes the NVIDIA wheel licence gap)'
type: 'chore'
created: '2026-10-31'
status: 'done'
baseline_revision: 'fc1806a9a15f2da98765b946e20d733d46fb2114'
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred:
  - summary: >-
      No CI job builds the backend images and runs the licence checker inside them.
    evidence: |-
      The only checks in this change are a static Dockerfile test and a build-time guard RUN. Neither scans
      the image with check-licenses.py and license-policy.toml. E0-QA.8 owns the in-image `image-licenses`
      job in license-check.yml, and this story must not edit workflows.
    location: >-
      .github/workflows/license-check.yml (new image-licenses job, E0-QA.8)
    severity: medium
  - summary: >-
      A PR that only touches licenses/register.yaml does not run the Dockerfile-vs-register pin test.
    evidence: |-
      backend-tests.yml filters on src/backend/** only. license-check.yml triggers on licenses/** but does
      not run the backend pytest suite. A register-only torch bump could drift from the Dockerfile pins
      until the next backend PR. The fix is a path-filter change in an E0-QA-owned workflow.
    location: >-
      .github/workflows/backend-tests.yml:8-17
    severity: low
  - summary: >-
      CI's licence job installs unpinned torch, so a new torch release changes what CI scans while the images stay pinned.
    evidence: |-
      license-check.yml:63-65 installs requirements.txt with the CPU extra index but no torch pin. The
      register matches exact versions, so a new torch release already breaks CI's scan (an existing
      problem). The Dockerfiles stay at 2.15.0+cpu. The fix is a shared constraints file or a
      requirements.txt pin used by CI too, which needs workflow or requirements changes outside this story.
    location: >-
      .github/workflows/license-check.yml:63-65; src/backend/requirements.txt
    severity: medium
  - summary: >-
      backend-tests.yml still installs CUDA torch from PyPI, so the test environment differs from the shipped images.
    evidence: |-
      backend-tests.yml runs a plain `pip install -r requirements.txt`. This existed before this story and the workflow is owned by E0-QA.
    location: >-
      .github/workflows/backend-tests.yml (Install dependencies)
    severity: low
---

<intent-contract>

## Intent

**Problem:** `src/backend/Dockerfile` and `Dockerfile.prod` run a plain `pip install -r requirements.txt`, which on x86-64 resolves CUDA torch from PyPI and pulls about 15 NVIDIA-proprietary `nvidia-*` wheels plus `cuda-toolkit`, `cuda-bindings` and `cuda-pathfinder` (18 licence violations in an in-image scan). CI's licence job installs CPU torch, so it never sees them, and the image is several GB larger than it needs to be.

**Approach:** In both Dockerfiles, install pinned `torch==2.15.0+cpu` and `torchvision==0.29.2+cpu` from `--index-url https://download.pytorch.org/whl/cpu` in a layer before `requirements.txt`, then install `requirements.txt` with the same `--extra-index-url` CI uses, so the image and the CI licence scan resolve the same package set. Record in `licenses/register.yaml` that the shipped torch/torchvision are the CPU builds, and add a static backend test that keeps the Dockerfiles honest.

## Boundaries & Constraints

**Always:** Pins equal the versions in `licenses/register.yaml` (and CI's resolution). The torch layer precedes the `requirements.txt` layer. Same wheels on `linux/amd64` and `linux/arm64` (the CPU index publishes `+cpu` manylinux_2_28 wheels for both, verified on download.pytorch.org). Keep the `build-essential` comment and apt line in `Dockerfile.prod` unchanged.

**Never:** Edit `.github/workflows/*` (E0-QA owns them; the in-image `image-licenses` job is E0-QA.8, `images.yml` is E0-Platform.9). Add a GPU/CUDA variant as default (OD-2 NVIDIA EULA decision is open; none is added here). Remove torch from the image (E0-Platform.6). Touch `tests/conftest.py`, alembic `env.py`, `docker-compose.dev.yml`, `llm_gate.py`, `pubsub.py` (wave siblings). Change `requirements.txt` contents.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| amd64 build | `docker build -f Dockerfile.prod .` | `torch 2.15.0+cpu`, no `nvidia-*`/`cuda-*` in `pip list`; `torch.cuda.is_available()` is False | No error expected |
| arm64 build | `docker buildx build --platform linux/arm64` | same `+cpu` wheels (aarch64), build succeeds | spaCy source build still needs build-essential (prod) |
| requirements step | torch already installed | pip keeps the pinned `+cpu` torch (`torch==2.15.0` specifiers accept the local label) | A future requirement needing a different torch would visibly re-resolve; the static test and E0-QA.8 catch drift |

</intent-contract>

## Code Map

- `src/backend/Dockerfile` -- dev image (docker-compose.yml backend + worker, lines 34/50). Line 4: plain `pip install -r requirements.txt`.
- `src/backend/Dockerfile.prod` -- prod image (docker-compose.prod.yml:122). Line 16: plain `pip install`; lines 4-14 build-essential note (keep).
- `src/backend/requirements.txt` -- read-only; torch arrives transitively via sentence-transformers, easyocr (also torchvision), openai-whisper (also triton on x86_64, MIT, registered).
- `.github/workflows/license-check.yml:63-65` -- read-only; CI pattern `pip install --extra-index-url https://download.pytorch.org/whl/cpu -r src/backend/requirements.txt`.
- `licenses/register.yaml:19-20` -- header comment saying CUDA wheels are deliberately unregistered; `:395` torch `2.15.0+cpu`, `:396` torchvision `0.29.2+cpu`, `:399` triton notes referencing E0-Platform.2.
- `scripts/check-licenses.py:266-280` -- register lookup is exact version (comma lists allowed), so image pins must equal register versions.
- `src/backend/tests/` -- pytest suite run by backend-tests.yml from `src/backend`; repo root is present in CI checkout but not in a bare `src/backend` rsync.

## Tasks & Acceptance

**Execution:**
- `src/backend/Dockerfile` -- add a `RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.15.0+cpu torchvision==0.29.2+cpu` layer after `COPY requirements.txt` and before the requirements install; add `--extra-index-url https://download.pytorch.org/whl/cpu` to the requirements install; short comment why -- removes NVIDIA wheels.
- `src/backend/Dockerfile.prod` -- same change, keep the build-essential block -- same.
- `licenses/register.yaml` -- update header comment and torch/torchvision/triton notes: shipped backend image installs the CPU wheels (E0-Platform.2); CUDA wheels remain unregistered so any regression fails -- AC register record.
- `src/backend/tests/test_dockerfile_cpu_torch.py` -- static test: for each Dockerfile, a torch install from the CPU index with `torch==X+cpu` pinned appears before the `-r requirements.txt` install, the requirements install carries the CPU extra index, and (when `licenses/register.yaml` is reachable) pins equal the register's torch/torchvision versions -- regression guard runnable in CI without Docker.

**Acceptance Criteria:**
- Given both Dockerfiles, when built for linux/amd64, then `pip list | grep -i nvidia` is empty and `python -c "import torch; assert not torch.cuda.is_available()"` succeeds.
- Given the built image, when `scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact backend` runs inside it, then it passes in both editions.
- Given the existing suite, when run, then the 99-test baseline still passes plus the new static test.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 24 findings — high 0, medium 8, low 12, false 4, maybe-false 0
- findings:
  - `[medium]` `[patch]` (verification-gap) No check proves the built image has no CUDA torch or NVIDIA wheels, and later layers (requirements, spaCy download) could re-resolve torch. Added a guard RUN after the spaCy download in both Dockerfiles that exits non-zero if `torch.version.cuda` is set, CUDA is available, or any `nvidia-*`/`cuda-*` package is installed. Added a static test that the guard comes last. The full in-image licence scan is deferred to E0-QA.8 (group: image-unverified).
  - `[low]` `[defer]` (verification-gap) A register-only PR does not run the pin test. Fixing it means a workflow path filter, which E0-QA owns. Deferred.
  - `[medium]` `[patch]` (intent-alignment) The runtime ACs (pip list, cuda False, in-image licence check) are not exercised by the diff. Same root cause as image-unverified: the build guard covers the first two at build time. The in-image licence scan is deferred, and the item is listed under Needs desktop verification.
  - `[false]` `[reject]` (intent-alignment) The register should literally read "BSD-3-Clause" for torch. check-licenses.py compares the register string with the wheel's real metadata (`register says X, scan says Y`, check-licenses.py:367), and torch's metadata is the compound expression, which includes BSD-3-Clause. Writing a bare BSD-3-Clause would fail the AC's own check.
  - `[low]` `[patch]` (intent-alignment) The image-size drop is not in a PR description. It will be recorded in the PR description as needing desktop measurement, because no image can be built here.
  - `[low]` `[reject]` (intent-alignment) torchvision is pinned although the story only names torch. This is necessary: PyPI's x86_64 torchvision is built against CUDA torch, and easyocr requires torchvision. Keeping it is less work than unpinning it.
  - `[low]` `[defer]` (intent-alignment) backend-tests.yml installs CUDA torch, so the test environment differs from the images. This was already the case, the workflow is owned by E0-QA, and it is deferred.
  - `[false]` `[reject]` (intent-alignment) The arm64 `+cpu` wheel existence was not checked. Confirmed on download.pytorch.org/whl/cpu: `torch-2.15.0+cpu-cp311-cp311-manylinux_2_28_aarch64.whl` and `torchvision-0.29.2+cpu-py3-none-manylinux_2_28_aarch64.whl` both exist.
  - `[medium]` `[defer]` (blind) CI and the images do not resolve the same set after a new torch release. Real, but CI's unpinned torch already breaks the exact-version register on any release (an existing problem). The fix needs a workflow change or a requirements.txt pin, both outside this story, so it is deferred. The misleading "same package set" comment was reworded (patch).
  - `[low]` `[reject]` (blind) `--extra-index-url` on the requirements install widens the supply-chain surface. The caller asked to mirror CI's index setup so the image and CI match. The torch layer is already pinned from `--index-url` only, and the PyTorch stable CPU index serves pinned mirrors. Diverging from CI would bring back exactly the scan mismatch this story closes.
  - `[medium]` `[patch]` (blind) Nothing fails the build on a CUDA regression. Same group as image-unverified: the guard RUN was added.
  - `[false]` `[reject]` (blind) The arm64 `+cpu` pins may not resolve. Refuted: the aarch64 `+cpu` wheels for both pins are listed on the CPU index (see above). The dev Dockerfile comment gap was patched, and the note was added there too.
  - `[low]` `[reject]` (blind) The docstring says "Runs without Docker", but conftest's autouse DB fixture needs Postgres. The docstring is accurate (no Docker), the test runs in backend-tests.yml with Postgres, and moving it adds structure for no user-facing gain.
  - `[low]` `[reject]` (blind) The parser does not handle exec form, heredocs, pip3 or `--requirement`. It fails closed, with a loud assertion, on forms the current files do not use. Supporting them adds branches for layouts nobody writes here.
  - `[medium]` `[patch]` (blind) Only the first torch layer is checked, so a later reinstall is unnoticed. Same group as image-unverified: the build guard catches any later re-resolve.
  - `[low]` `[reject]` (blind) `DOCKERFILES` is a hard-coded list. A new backend Dockerfile (for example the E0-Platform.6 worker image) will arrive with its own story and its own guard. A glob assertion is extra machinery for a rare event.
  - `[low]` `[reject]` (blind) The triton note does not cover arm64 images lacking triton. The register is per-package, and a registered package that is absent from an arm64 image does not fail the scan, so no harm follows.
  - `[medium]` `[patch]` (edge) `BACKEND.parents[1]` raises IndexError when src/backend is mounted at /app. Fixed: REGISTER now falls back to a missing path when there is no grandparent, so the skipif applies.
  - `[medium]` `[patch]` (edge) A later RUN can reinstall CUDA torch. Same group as image-unverified: the guard RUN was added.
  - `[low]` `[patch]` (edge) Comment lines inside a backslash continuation are kept as tokens. Fixed: `_run_instructions` now drops `#` lines inside a continuation, as Docker does.
  - `[low]` `[reject]` (edge) Exec-form or heredoc RUN gives junk tokens. Same reasoning as the parser-forms reject above.
  - `[medium]` `[patch]` (edge) A requirement whose torch range excludes 2.15.0 would let pip replace torch. Same group as image-unverified: the guard RUN fails the build. A constraint flag was not added, so that the requirements install stays identical to CI's.
  - `[low]` `[patch]` (edge) The "resolve the same package set" claim is false. The comment was reworded to "same CPU extra index as CI's licence job" (the CI drift itself is deferred above).
  - `[false]` `[reject]` (edge) The CPU index may lack aarch64 `+cpu` wheels. Refuted: verified on download.pytorch.org (see above).

## Design Notes

Both arches use the identical `+cpu` pin because the CPU index carries `manylinux_2_28_aarch64` `+cpu` wheels for torch 2.15.0 and torchvision 0.29.2, so no `uname`/`TARGETARCH` branch is needed. torchvision is pinned in the same layer because PyPI's x86_64 torchvision is built against CUDA torch.

## Verification

**Commands:**
- `uv run --python 3.11 --with pytest python -m pytest -q src/backend/tests/test_dockerfile_cpu_torch.py --noconftest` -- expected: pass
- GitHub CI (backend-tests, license-check) on the draft PR -- expected: green

**Manual checks (if no CLI):**
- Needs desktop verification: build both images, `pip list | grep -iE 'nvidia|cuda'` empty, CUDA assert, in-image licence check, arm64 buildx, image size before/after.

## Auto Run Result

Status: done

**Summary:** Both backend Dockerfiles now install pinned `torch==2.15.0+cpu` and `torchvision==0.29.2+cpu` from `--index-url https://download.pytorch.org/whl/cpu` in their own layer, before `requirements.txt`. The requirements install uses the same CPU `--extra-index-url` as CI's licence job. A guard RUN after the spaCy model download fails the build if torch is a CUDA build or any `nvidia-*`/`cuda-*` package is present. The register notes record that the shipped backend images use the CPU builds, and the CUDA wheels stay unregistered on purpose. A static backend test keeps the Dockerfiles honest.

**Files changed:**
- `src/backend/Dockerfile`: CPU torch layer, CPU extra index on the requirements install, CUDA/NVIDIA build guard.
- `src/backend/Dockerfile.prod`: the same changes. The build-essential note and apt line are untouched.
- `licenses/register.yaml`: header comment and torch, torchvision and triton notes say the shipped images use the CPU builds. Versions and licences are unchanged.
- `src/backend/tests/test_dockerfile_cpu_torch.py` (new): 8 static checks. CPU-index `+cpu` pins come before requirements, the requirements install has the extra index, the pins match the register, and the guard RUN comes last.

**Review:** 24 findings (0 high, 8 medium, 12 low, 4 false). Patched entries: 2 medium (the image-unverified group, fixed with the build guard and its test; the `/app` IndexError) and 3 low (the comment wording, the comment lines inside a continuation, and the dev Dockerfile arm64 note). The size-drop note is to go in the PR description. Deferred: 4 items (see frontmatter `deferred`). Rejected: 4 false and 8 low, each with its reason in the triage log. Sprint-sync was skipped: the orchestrator owns sprint-status.yaml.

**Follow-up review recommended: true.** Two medium entries were patched. The specific unverified risk is that the new guard RUN has never run in a real `docker build`: the `! pip list | grep` negation in the image's /bin/sh, and `torch.cuda.is_available()` on a CPU wheel. A desktop or CI image build settles it.

**Verification:** `uv run --python 3.11 --with pytest python -m pytest -q src/backend/tests/test_dockerfile_cpu_torch.py --noconftest` gives 8 passed. Against the original HEAD Dockerfiles, the ordering and extra-index checks fail, as they should. I confirmed on download.pytorch.org/whl/cpu that the aarch64 and x86_64 `+cpu` cp311 wheels exist for both pins. The full backend suite and the licence workflow run in GitHub CI on the draft PR.

### Needs desktop verification
- amd64 build plus checks: `docker build -f src/backend/Dockerfile.prod -t lk-backend-cpu src/backend && docker run --rm lk-backend-cpu pip list | grep -iE 'nvidia|cuda'` should print nothing, and `docker run --rm lk-backend-cpu python -c "import torch; assert not torch.cuda.is_available(); print(torch.__version__)"` should print `2.15.0+cpu`. Do the same with `-f src/backend/Dockerfile`.
- In-image licence check, both editions: `docker run --rm -v $PWD:/repo -w /repo -e LOREKEEPER_EDITION=commercial lk-backend-cpu sh -c "pip install -q pyyaml && python scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact backend"`. Repeat with `LOREKEEPER_EDITION=agpl`. Both should report 0 violations. (A permanent CI version of this check is E0-QA.8.)
- arm64: `docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod src/backend` should succeed.
- Size: `docker image ls` for an image built from `main` against `lk-backend-cpu`. Record the drop in the PR description.
- Suite against the image: run the builder-brief backend test command with `lk-backend-cpu` in place of `lorekeeper-backend-test`. The 99-test baseline plus 8 new tests should pass, along with `/api/health`, journal save, retrieval and `test_nlp.py`.

**Residual risks:** CI's licence job installs unpinned torch, so a new torch release makes CI's scan diverge (deferred, E0-QA). Torch is removed from the web/worker image entirely in E0-Platform.6.
