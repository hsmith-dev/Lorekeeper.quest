# Licensing of what we ship

Lorekeeper is AGPL-3.0 **and** sold under a commercial licence
([COMMERCIAL-LICENSE.md](../COMMERCIAL-LICENSE.md)). Everything we distribute
(Python and npm packages, Docker images and their OS packages, models, voices
and fonts) therefore has to be distributable under both. This page explains how
that is checked, which rules apply to the Docker images, and which gaps are
still open.

## The pieces

| File | Role |
| --- | --- |
| `licenses/register.yaml` | The inventory: one entry per shipped package, image, OS package, model, voice and font. |
| `.github/license-policy.toml` | The rules: allowlist, aliases, deny lists, `[strict]` edition rules, owner-approved `[[exception]]`s and `[[pending]]` known gaps. |
| `scripts/check-licenses.py` | The checker. `--python-env`, `--npm`, `--os-packages`, `--register`, `--check-artifacts`. |
| `.github/workflows/license-check.yml` | Runs everything in both editions (`LOREKEEPER_EDITION=agpl` and `commercial`). |

Any PR that adds a dependency, an apt/apk package, an image, a model, a voice or
a font updates `licenses/register.yaml` in the same PR. The checker prints a
ready-made register line for anything unregistered (`--emit-missing`).

## The image scan (`image-licenses`)

The `backend` and `frontend` jobs scan what CI installs on the runner. That is
not necessarily what the images contain: before E0-Platform.2, the backend
image installed CUDA torch and about 15 NVIDIA-proprietary wheels that the CPU
install in CI never saw. So the `image-licenses` job builds every image we ship
and scans it **from the inside**:

| Image | Built from | What is scanned |
| --- | --- | --- |
| `backend` | `src/backend/Dockerfile.prod` | the image's pip set (`--python-env`) and its Debian packages (`--os-packages`) |
| `nginx` | `nginx/Dockerfile` | its Alpine packages (the frontend bundle's npm set is the `frontend` job) |

The checker, register and policy are mounted read-only into the container,
never installed into the image. Register mode needs PyYAML, and the backend
image has it only as a runtime transitive dependency (registered as `PyYAML`).
If that ever goes away, the in-image scan stops with "register mode needs
pyyaml". The fix is then to scan the image's exported filesystem from the
runner, as the nginx line does. An image without Python (nginx) is exported to
the runner and its package database scanned from there. Adding an image (the
planned `ml`, `stt` and `tts` sidecars) is one matrix line; the AGPL-only `tts`
image gets `editions: "agpl"`. The job also runs weekly, because the images
float on their base tags and a base-image rebuild can add a package without any
change in this repo.

Upstream images that compose only references and we run unmodified
(`pgvector/pgvector`, `redis`, `ollama/ollama`) are not rebuilt here; each is an
`image` entry in the register.

Reproduce locally:

```bash
# CI scans linux/amd64; an arm64 build has a different package set
docker build --platform linux/amd64 -f src/backend/Dockerfile.prod -t lk-backend src/backend
docker run --rm --entrypoint python \
  -v "$PWD/scripts:/chk:ro" -v "$PWD/licenses:/lic:ro" -v "$PWD/.github:/pol:ro" \
  lk-backend /chk/check-licenses.py --policy /pol/license-policy.toml \
  --register /lic/register.yaml --python-env --os-packages --artifact backend \
  --edition commercial --emit-missing
```

## OS packages: how licences are read

- **Debian (`apt`)**: `dpkg`'s status database lists the installed packages.
  Each package's licence comes from `/usr/share/doc/<pkg>/copyright`. For
  machine-readable (DEP-5) files, that is every distinct `License:` short name,
  joined with `AND`. For free-text files, it is the
  `/usr/share/common-licenses/<X>` files they point at. If neither is present,
  the licence is `UNKNOWN`, which fails.
- **Alpine (`apk`)**: the `L:` field of `/lib/apk/db/installed`.

Every OS package needs a register entry whose licence matches the scan. The
one exception is a dynamically linked LGPL system library on
`system_lib_allowlist` (libvips, Pango, HarfBuzz, GLib), which may resolve to
the allowlist instead of an entry. An unknown package fails. When the scan
string is not SPDX, the entry pins it in `scanned_license` and records the
reviewed SPDX licence in `license`, which is what the edition rules then judge.

## The OS-base-layer rule (mere aggregation)

Every Linux image carries GPL and LGPL software: glibc (LGPL), bash, coreutils
and the compiler toolchain on Debian, busybox and apk-tools on Alpine. These
ship unmodified, as separate programs and libraries of the image's
distribution. Lorekeeper does not modify them, and no Lorekeeper code is a
derivative work of them. Putting them next to Lorekeeper in one image is
aggregation, which the GPL explicitly allows ("mere aggregation ... on a volume
of a storage or distribution medium"). This works for the commercial edition as
long as we meet the obligations below.

So the policy has an `os_aggregate_allowlist` (apt/apk package-name regexes,
grouped and commented). A GPL/LGPL OS package passes, in both editions, only
when:

1. it has a register entry whose licence matches the scan, and
2. its name is on `os_aggregate_allowlist`.

Non-commercial, proprietary and unknown licences never pass this way. A GPL
library that a new `apt-get install` pulls in fails until someone reviews it
and adds it to the list in the same PR. The rule covers OS packages only, never
a pip or npm package: those run inside Lorekeeper's own process.

One caveat: the Python interpreter can itself load a few GPL-3 OS libraries
into Lorekeeper's process. These are `libreadline8` (the `readline` module)
and `libgdbm` (`dbm.gnu`). They come with the python:3.11-slim base, and
Lorekeeper imports neither: gunicorn is non-interactive and there is no dbm
usage. Their register notes record this. Code that starts importing
`readline` or `dbm.gnu` needs a licence review first.

Obligations that come with shipping these packages:

- **Licence texts** ship inside the images (`/usr/share/doc/*/copyright` and
  `/usr/share/common-licenses` on Debian, `/usr/share/licenses` on Alpine). Do
  not strip them, for example with a `rm -rf /usr/share/doc` slimming step.
- **Corresponding source** for the GPL packages exists in the distribution
  archive at the exact version in the register (Debian: `apt-get source
  <pkg>=<version>` or snapshot.debian.org; Alpine: aports at the matching
  release). Today we publish Dockerfiles and users build the images
  themselves, so we don't distribute these binaries. **If we ever distribute
  built images** (a registry, a commercial download), pointing at someone
  else's archive is not enough for commercial distribution: GPLv2 §3(c) is
  for noncommercial distribution only. We must then ship the source alongside
  the image, or give a written offer valid for three years (§3(a)/(b)), for
  example by mirroring the source packages next to each published image tag.
  Owner action before the first published image.

Things to clean up later:

- `Dockerfile.prod` keeps `build-essential` (gcc, binutils, make, perl, about
  100 packages, mostly GPL) in the shipped image, because spaCy is compiled from
  source on arm64. A multi-stage build that compiles in a builder stage and
  copies only the venv would remove all of them, along with most of the
  aggregate list.
- The `en_core_web_trf` model and the CPU torch wheels stay in the image until
  E0-Platform.3 and .6 move them to the `ml` sidecar.

## Known gaps (`[[pending]]`)

A `[[pending]]` entry in the policy records a known licence gap with an owning
story (`tracking`). An unregistered scanned package that matches one prints a
warning and does not fail the job. Any other unregistered package still fails.
An entry can be limited to certain images (`images`).

**CUDA wheels.** CUDA torch from PyPI pulls in the NVIDIA runtime wheels
(`nvidia-*`: cuBLAS, cuDNN, NCCL, cuSPARSELt and others) plus `cuda-toolkit`,
`cuda-bindings` and `cuda-pathfinder`. These are under the NVIDIA EULA,
proprietary terms that the commercial and AGPL editions cannot pass on.

- **Shipped images today:** none of them. E0-Platform.2 installs CPU-only
  `torch==2.15.0+cpu` and `torchvision==0.29.2+cpu` from the PyTorch CPU index
  in both backend Dockerfiles, and a build step fails if any `nvidia-*` or
  `cuda-*` package appears. The backend image scan also fails on them: the
  pending entries do not apply to `backend`.
- **Interim rule until AD-1 lands:** any image that installs torch for the
  commercial build must install it from the CPU wheel index (pin
  `torch==<ver>+cpu` from `--index-url https://download.pytorch.org/whl/cpu`
  first, then install the requirements with
  `--extra-index-url https://download.pytorch.org/whl/cpu`). Never install
  plain PyPI torch on x86-64.
- **After AD-1:** the web and worker images never install torch. `ml` defaults
  to CPU wheels, with an optional GPU override image. The pending entries
  (`tracking: "E0-Platform AD-1 / ml CPU image"`) cover that override image
  only (`images = ["ml-gpu"]`).
- **Owner decision still needed (OD-2):** may we redistribute a GPU image that
  contains NVIDIA's CUDA runtime under the NVIDIA EULA, and in which editions?
  Options are to publish it under the EULA's redistribution terms, to publish
  only a Dockerfile that users build themselves, or to have no GPU image at
  all. Until the owner decides, no GPU image is built or published, and the
  pending entries stay warnings for an image that does not exist yet.

## Owner-approved exceptions

`[[exception]]` entries in the policy record packages the owner accepts despite
the rules: fpdf2 (LGPL-3.0), python-bidi (LGPL, via easyocr), caniuse-lite
(CC-BY-4.0) and the `redis:7-alpine` image (RSALv2 / SSPLv1). All four are
marked `OWNER TO CONFIRM`. E0-QA.9 records the decisions. For redis, the
choice is between pinning `redis:7.2-alpine` (the last BSD-3-Clause release)
and switching to Valkey.
