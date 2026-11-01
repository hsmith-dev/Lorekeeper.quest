---
title: 'E0-QA.8 The licence check scans the Docker images we actually ship'
type: 'feature'
created: '2026-11-01'
status: 'done'
baseline_revision: 'a099a75fe69cea03dd65f0175a153d96f1a4d0f2'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-e0-qa-7-licence-register-strict-mode.md'
warnings: ['oversized']
deferred:
  - summary: >-
      An aggregate-listed OS package whose DEP-5 union holds a GPL term plus an unrecognised term (noderivs, POWERDOG) is classified gpl and passes; the unrecognised term is never judged.
    evidence: |-
      classify() returns gpl once any GPL pattern matches; bad_patterns still catch NC/proprietary/UNKNOWN/Custom/NVIDIA anywhere. Per-atom judgement would need aliases for ~100 Debian short names. The register row is the human review.
    location: >-
      scripts/check-licenses.py classify / os_rule_ok
    severity: medium
  - summary: >-
      The new permissive ids and public-domain aliases (X11, TCL, GD, Beerware, LicenseRef-Public-Domain) are global, so a pip/npm package saying "Public Domain" now passes.
    evidence: |-
      [allow] and [aliases] have no per-kind scope; every pip/npm package still needs a register entry, which is where it would be reviewed.
    location: >-
      .github/license-policy.toml [allow]/[aliases]
    severity: low
  - summary: >-
      The register records binary package names and versions, not dpkg `Source:`, so GPL source retrieval for binNMUs or renamed binaries needs a lookup.
    evidence: |-
      load_dpkg ignores Source; only matters once built images are distributed (LICENSING.md owner action).
    location: >-
      scripts/check-licenses.py load_dpkg
    severity: low
  - summary: >-
      os_aggregate_allowlist is one list for apt and apk, so a Debian-named pattern (^bash$, ^make$) would also admit a GPL apk package of that name.
    evidence: |-
      Patterns are only grouped by comment; keying by kind is a schema change.
    location: >-
      .github/license-policy.toml os_aggregate_allowlist
    severity: low
  - summary: >-
      The bare --os-packages default (ROOT=/) has no unit test; only the image-licenses (backend) CI leg exercises it.
    evidence: |-
      Verification-gap mutation const=None passed the unit suite. A unit test needs a host with a dpkg/apk database.
    location: >-
      scripts/check-licenses.py main (argparse)
    severity: low
  - summary: >-
      arm64 images are never scanned (CI builds linux/amd64 only), and their package set differs (spaCy source build).
    evidence: |-
      docker/build-push-action platforms: linux/amd64. Needs desktop verification.
    location: >-
      .github/workflows/license-check.yml image-licenses
    severity: medium
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

### 2026-11-01 — Review pass
- verdicts: 41 findings — high 0, medium 9, low 21, false 6, maybe-false 0 (5 duplicate rows of the trigger finding are folded into its group)
- findings:
  - (intent) `[medium]` `patch` The `on:` block had no Dockerfile/nginx paths and no schedule, although the spec and LICENSING.md said so (an earlier scripted edit had not applied). Added `src/backend/Dockerfile*` and `nginx/**` to both path lists and a weekly cron. Blind, edge-case and verification-gap all reported the same issue (same group).
  - (intent) `[low]` `reject` AC1/AC3 are exercised only by unit tests, not a real image. PR #20 removed the CUDA wheels from every shipped image, and the Dockerfile guard fails the build first. Real-image proof is the desktop run against the old CUDA image (Needs desktop verification).
  - (intent) `[low]` `reject` The aggregate rule adds a third pass route beyond the AC's two. It is required by E0-QA.7's deferral and the orchestrator note on glibc/busybox/bash; documented in LICENSING.md.
  - (intent) `[false]` `reject` "No evidence that the scan ran". CI runs 41279105798 and 41279803809 produced the rows, and run b2dabf3 is green on both images.
  - (intent) `[low]` `reject` Unrequested checker changes (precedence fix, pin classification, exception set). Each is needed by the DEP-5 strings: parenthesised OR groups, Custom-* pins. Each is now tested.
  - (blind) `[low]` `patch` pyyaml is only a transitive dependency in the backend image. Documented in LICENSING.md with the fallback.
  - (blind+edge) `[medium]` `patch` `_under` followed an absolute symlink onto the host when scanning an exported rootfs. It now checks `is_symlink()` first; `test_absolute_doc_symlink_never_reads_the_host` added.
  - (blind) `[medium]` `patch` libreadline/libgdbm (GPL-3) can load into the Python process. LICENSING.md caveat added and register notes record that Lorekeeper imports neither.
  - (blind) `[medium]` `patch` The GPLv2 §3(c) archive pointer is not enough for commercial distribution. LICENSING.md now requires shipped source or a written offer before any published image (owner action).
  - (blind) `[low]` `defer` Binary vs source package names (frontmatter).
  - (blind) `[low]` `defer` Global allow ids and aliases (frontmatter).
  - (blind+edge) `[low]` `patch` Pending typos and bad images went unvalidated. Policy now validates ecosystem ∈ KINDS and requires `images` to be a non-empty list of strings; tests added. A stale-entry warning was rejected (low, adds machinery).
  - (blind) `[low]` `reject` The OS stub writes the raw string into `license`. Intended: the register normalises the same way, and pins are a review step described in the register header.
  - (blind) `[medium]` `defer` arm64 is never scanned (frontmatter; Needs desktop verification). The local reproduce command now passes `--platform linux/amd64`.
  - (blind+vgap) `[low]` `patch` The test comment promised a pip assertion. Pip and MIT rows were added.
  - (blind) `[low]` `patch` The CUDA test did not check licence strings. It now asserts the real strings and the "proprietary" reason.
  - (blind+edge) `[low]` `patch` Export errors went to /dev/null. tar errors now show plus a `::warning`, and an empty package DB is now an error.
  - (blind) `[low]` `patch` The dependency direction was reversed in the policy comment. Fixed.
  - (blind) `[low]` `defer` One aggregate list for both distros (frontmatter).
  - (edge) `[medium]` `defer` A GPL plus unknown-term union passes via aggregate (frontmatter).
  - (edge) `[low]` `reject` A BOM before `Format:`, or inline text in free-text copyright files: not present in either image's 220 files (scan output reviewed); a guard adds branches.
  - (edge) `[medium]` `patch` `images = []` meant all images. Now rejected at policy load.
  - (edge) `[low]` `patch` An unknown pending ecosystem was silent. Now rejected.
  - (edge) `[low]` `patch` half-installed or unpacked dpkg states were skipped. Now only not-installed and config-files are skipped.
  - (edge) `[low]` `patch` An empty package DB passed. Now an error; test added.
  - (edge) `[low]` `patch` `--os-packages` without `--register` gave confusing plain-mode failures. Now an argparse error; test added.
  - (edge) `[low]` `reject` An OS entry's `images` is not enforced per artifact. apt and apk kinds already separate the two distros, and no second Debian image exists yet.
  - (edge) `[low]` `reject` (claim) A new image needing pyyaml or code changes: documented. python:false images need no code; the host-symlink case is fixed.
  - (edge) `[false]` `reject` (claim) "Debian no-Python image hits host-symlink resolution": fixed in this pass (see above), so false now.
  - (vgap) `[medium]` `patch` The precedence regression was untested. Added `(MIT OR GPL-3.0) AND (GPL-3.0)` → False.
  - (vgap) `[medium]` `patch` PENDING / `::warning` output was unverified. Added `test_cli_pending_warns_and_exits_zero`.
  - (vgap) `[low]` `patch` Pending with no images, and pending ecosystem scoping, were untested. Test added.
  - (vgap) `[low]` `defer` The bare `--os-packages` default (frontmatter; covered by the CI leg).
  - (vgap) `[medium]` `patch` An exception matching the reviewed licence of a pinned entry was untested. Test added.
  - (vgap) `[low]` `patch` The permissive system-lib branch was untested. MIT row added.
  - (blind) `[false]` `reject` "paths miss docker-compose.prod.yml": compose changes don't alter image contents; the Dockerfiles and nginx/** are now in.
  - (blind) `[false]` `reject` "nginx has no local recipe": the workflow step is the recipe, and LICENSING.md describes the export path.
  - (intent) `[false]` `reject` "No Needs-desktop-verification section": it lives in the Auto Run Result below, not in the diff of code.
  - (intent) `[false]` `reject` "dev Dockerfile not built": out of scope by the story (Dockerfile.prod is the shipped image). Listed for the desktop.
  - (blind) `[false]` `reject` The register header still says license is SPDX: it was updated in this diff to explain pins.

## Design Notes

PR #20 changed the premise of AC 1 and AC 3: the shipped backend image no longer carries CUDA wheels. So the `[[pending]]` mechanism is implemented and the CUDA wheels are listed under it with the required `tracking`, but scoped to the future `ml-gpu` image. In `backend` they remain hard failures, rather than being silenced. The OS-base-layer rule follows E0-QA.7's deferral. It uses a reviewed name allowlist in the policy, like `system_lib_allowlist`, instead of trusting every distro package, so a GPL library brought in by a new `apt-get install` still needs review.

## Verification

**Commands:**
- `uv run --python 3.11 --with pytest --with pyyaml python -m pytest -q scripts/test_check_licenses.py` -- all pass
- `actionlint .github/workflows/license-check.yml` -- clean
- GitHub CI on the draft PR (`license-check.yml`, all jobs, including `image-licenses (backend)` and `(nginx)`) -- green

## Auto Run Result

Status: done

**Summary:** A new `image-licenses` job in `license-check.yml` builds the two images we ship and runs the licence checker inside them in both editions. It uses buildx on the GitHub `type=gha` cache. `backend` is built from `Dockerfile.prod` and scanned in-image for its pip set and Debian packages. `nginx` is exported, and its Alpine packages are scanned from the runner. Each image is one matrix line; a `tts` line would use `editions: "agpl"`.

The checker gains:
- `--os-packages [ROOT]`: dpkg plus DEP-5 copyright files as kind `apt`, the apk database as kind `apk`.
- An OS-base-layer (mere-aggregation) allowlist rule.
- `[[pending]]` known gaps.
- An SPDX precedence fix that splits on operators only outside parentheses.
- `scanned_license` pins now classify the register's reviewed licence.

The register gains 151 Debian rows and 69 Alpine rows, generated from the CI scan and reviewed. Seven needed pins: libpq5/-dev, libcrypt1/-dev, libbsd0, libmd0 and libpcre2-8-0. The CUDA wheels are listed under `[[pending]]` with `tracking: "E0-Platform AD-1 / ml CPU image"`, scoped to the future `ml-gpu` image, so in `backend` they still fail. `docs/LICENSING.md` (new) covers the scan, the aggregate rule and its source and licence-text obligations, the CUDA gap, the interim CPU-index rule and the OD-2 owner decision.

**PR #20 verdict:** `Dockerfile.prod` built on ubuntu-latest (linux/amd64) with no changes. torch 2.15.0+cpu and torchvision 0.29.2+cpu resolved from the CPU index, and the build guard step passed in 1.6 s. The in-image pip scan found 129 packages and 0 violations in both editions. No Dockerfile fix was needed.

**Files:**
- `scripts/check-licenses.py`: OS scan, aggregate and pending rules, precedence fix.
- `scripts/test_check_licenses.py`: 97 tests, 41 of them new.
- `.github/license-policy.toml`: aggregate allowlist, pending entries, OS-licence allow ids and aliases.
- `.github/workflows/license-check.yml`: the `image-licenses` job, Dockerfile and nginx path triggers, weekly cron.
- `licenses/register.yaml`: apt and apk sections, header.
- `docs/LICENSING.md`: new.
- This spec.

**Implementation note:** the implementation was done by the orchestrating agent, not a separate step-03 subagent. The register rows could only come from CI scan output, which needed push/observe iterations. The four review layers ran as independent subagents.

**Review:** 41 findings. 22 patched (7 medium, 15 low), 6 deferred (see frontmatter), 13 rejected (6 false, 7 low), each with a reason in the triage log. **followup_review_recommended: true**: seven medium patches landed, and the specific unverified risk is the `_under` symlink rebasing on a real exported Debian rootfs. Only `nginx` (Alpine, no doc symlinks) goes through that path in CI today.

**Verification:**
- Unit tests: 97/97 pass.
- actionlint: clean.
- CI on b2dabf3: all 9 checks green, including both `image-licenses` legs. The cached backend rebuild takes about 3.5 min; the cold build took about 25 min.
- A simulated scan of all 151 Debian and 69 Alpine rows against the register gives 0 failures in both editions.

### Needs desktop verification
- **arm64 build and scan:**
  ```bash
  docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod -t lk-backend-arm src/backend --load
  ```
  Then run the LICENSING.md scan command with `lk-backend-arm`. Expect a few new apt rows (`*-aarch64-linux-gnu` toolchain packages, which match the aggregate patterns) and no triton; add any `--emit-missing` stubs to the register.
- **The CUDA regression is caught in an image:**
  ```bash
  docker run --rm --entrypoint python -v $PWD/scripts:/chk:ro -v $PWD/licenses:/lic:ro -v $PWD/.github:/pol:ro lorekeeper-backend-test /chk/check-licenses.py --policy /pol/license-policy.toml --register /lic/register.yaml --python-env --artifact backend
  ```
  Expect exit 1, with each nvidia-*/cuda-* wheel reported with its real licence string. With `--artifact ml-gpu` they should print as PENDING instead.
- **Running the image:** `docker compose -f docker-compose.prod.yml up -d --build`. Check that `/api/health` responds, that spaCy loads `en_core_web_trf`, and that the licence texts are present (`docker run --rm <backend> ls /usr/share/doc | wc -l`).
- **Dev image:** `docker build -f src/backend/Dockerfile src/backend` (not shipped, so not in CI).

**Residual risks:**
- The images float on their base tags, so a base rebuild can add an unregistered package. The weekly run catches it, but it will turn main red until the stub is registered.
- The DEP-5 union is conservative, and unknown non-GPL atoms inside an aggregate package are not judged (deferred).
- Commercial distribution of built images needs the GPL source offer first (LICENSING.md, owner action).
- The redis exception is unchanged and still waits on the owner's Redis-vs-Valkey decision.
- Sprint-status sync was skipped; the orchestrator owns it.
