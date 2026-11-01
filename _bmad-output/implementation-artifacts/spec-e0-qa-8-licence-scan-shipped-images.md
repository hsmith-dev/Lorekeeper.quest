---
title: 'E0-QA.8 The licence check scans the Docker images we actually ship'
type: 'feature'
created: '2026-11-01'
status: 'in-progress'
baseline_revision: 'a099a75fe69cea03dd65f0175a153d96f1a4d0f2'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-qa-7-licence-register-strict-mode.md'
warnings: ['oversized']
deferred: []
---

<intent-contract>

## Intent

**Problem:** The licence gate scans what CI installs on the runner (CPU torch, the npm lockfile), not the images we ship. The backend image's real pip set and the OS packages of the backend (Debian) and nginx (Alpine) images have never been checked. E0-QA.7 also left base-OS GPL/LGPL packages (glibc, bash, busybox) without a rule.

**Approach:** Add an `image-licenses` job that builds each shipped image with buildx (GHA cache) and runs `check-licenses.py --register` inside it in both editions. The checker gains `--os-packages` (dpkg + `/usr/share/doc/*/copyright` as kind `apt`, the apk DB as kind `apk`), an OS-base-layer (mere-aggregation) allowlist rule, and `[[pending]]` known gaps. Register entries are added for every OS package found, and `docs/LICENSING.md` explains it all.

## Boundaries & Constraints

**Always:**
- Shipped images = what we build: `backend` (`src/backend/Dockerfile.prod`) and `nginx` (`nginx/Dockerfile`). Each image is one `include` matrix line (`image, context, dockerfile, python, editions`). A `tts` line would use `editions: "agpl"`.
- The checker, register and policy are mounted read-only (`/chk`, `/lic`, `/pol`), never installed into the image. A no-Python image (nginx) is exported and its OS DB scanned on the runner.
- Every OS package needs a register entry whose licence matches the scan, or (only for LGPL/permissive packages) a match on `system_lib_allowlist`. An unknown package fails.
- GPL-family OS packages pass in both editions only when they are registered and on `[strict] os_aggregate_allowlist`. Non-commercial, proprietary and unknown licences never pass. The rule never applies to pip or npm.
- `[[pending]]` (ecosystem, package glob, tracking, reason, optional images): an unregistered match is a warning. Any other unregistered package still fails.
- When an entry pins `scanned_license`, the edition rules classify the register's reviewed `license`.

**Never:**
- No pending entry that covers the `backend` image. E0-Platform.2 removed the CUDA wheels, and a regression must fail. The CUDA pending entries are scoped to the planned `ml-gpu` override image.
- Don't touch the redis exception (owner Redis-vs-Valkey decision), `desktop-verification-queue.md`, `sprint-status.yaml` or `epics.md`.
- No multi-stage rewrite of `Dockerfile.prod` (out of scope; noted in LICENSING.md).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Shipped images, both editions | built backend + nginx | 0 violations, exit 0 | — |
| New OS package | unregistered apt/apk package | FAIL + `--emit-missing` stub with `images: [<artifact>]` | exit 1 |
| GPL OS package off the list | registered, not on aggregate list | FAIL GPL | exit 1 |
| Aggregate package, unknown licence | `UNKNOWN (no copyright file)` | FAIL unknown | exit 1 |
| LGPL system lib, unregistered | `libglib2.0-0t64` LGPL | pass via allowlist | — |
| CUDA wheel in backend | `nvidia-*` | FAIL (pending does not apply) | exit 1 |
| CUDA wheel in ml-gpu | `nvidia-*` | PENDING warning, exit 0 | `::warning` |
| No package DB | `--os-packages` on an empty dir | error naming dpkg/apk | exit 1 |
| SPDX precedence | `(MIT OR GPL-3.0) AND GPL-3.0` | not allowed | — |

</intent-contract>

## Code Map

- `scripts/check-licenses.py` -- `Policy` (adds `os_aggregate`, `pending`); `split_top`/`strip_outer_parens` (parenthesis-aware `term_ok`); OS loaders `parse_deb822`, `debian_copyright_license`, `load_dpkg`, `load_apk`, `load_os_packages`; rules `is_os_aggregate`, `os_rule_ok`, `pending_for`; `check_register_scan` (now returns `pending`) and `check_register_entries`; `emit_stub` (apt/apk URLs, `images`); `report` (PENDING lines and `::warning`); CLI `--os-packages [ROOT]`.
- `.github/license-policy.toml` -- `[strict] os_aggregate_allowlist`, `[[pending]]` CUDA entries (`images = ["ml-gpu"]`), OS-licence allow ids and aliases.
- `.github/workflows/license-check.yml` -- `image-licenses` job: free disk, buildx `type=gha` cache, `--load`, in-image or exported scan, both editions in one job (one build per image). Paths gain Dockerfiles and `nginx/**`; weekly schedule for base-tag drift.
- `licenses/register.yaml` -- new `apk` and `apt` sections, generated from the CI `--emit-missing` output and hand-reviewed.
- `scripts/test_check_licenses.py` -- tests for the matrix rows above.
- `docs/LICENSING.md` (new) -- how it works, the aggregate rule and its obligations, the CUDA gap and interim CPU-index rule, OD-2.
- Read-only: `src/backend/Dockerfile.prod` (PR #20 CPU torch pins and build guard; first real build happens here), `nginx/Dockerfile`, `docker-compose.prod.yml`.

## Tasks & Acceptance

**Execution:**
- `scripts/check-licenses.py` -- OS scan, aggregate rule, pending, precedence fix -- the gate.
- `.github/license-policy.toml` -- rules above -- the policy stays the rule file.
- `licenses/register.yaml` -- an entry for every scanned OS package -- the inventory.
- `.github/workflows/license-check.yml` -- `image-licenses` job -- CI-4.
- `scripts/test_check_licenses.py` -- unit tests for the I/O matrix -- regression guard.
- `docs/LICENSING.md` -- documentation -- AC 3.

**Acceptance Criteria:**
- Given the PR, when `image-licenses` runs, then both images build on ubuntu-latest and pass in both editions.
- Given a CUDA regression in the backend image, when it is scanned, then each `nvidia-*`/`cuda-*` wheel fails with its real licence string (unit test; the Dockerfile guard also fails the build).
- Given a new image, when it is added, then it is one matrix line with no code change.

## Spec Change Log

## Review Triage Log

## Design Notes

PR #20 changed the premise of AC 1 and AC 3: the shipped backend image no longer carries CUDA wheels. So the `[[pending]]` mechanism is implemented and the CUDA wheels are listed under it with the required `tracking`, but scoped to the future `ml-gpu` image. In `backend` they remain hard failures, rather than being silenced. The OS-base-layer rule follows E0-QA.7's deferral. It uses a reviewed name allowlist in the policy, like `system_lib_allowlist`, instead of trusting every distro package, so a GPL library brought in by a new `apt-get install` still needs review.

## Verification

**Commands:**
- `uv run --python 3.11 --with pytest --with pyyaml python -m pytest -q scripts/test_check_licenses.py` -- all pass
- `actionlint .github/workflows/license-check.yml` -- clean
- GitHub CI on the draft PR (`license-check.yml`, all jobs, including `image-licenses (backend)` and `(nginx)`) -- green
