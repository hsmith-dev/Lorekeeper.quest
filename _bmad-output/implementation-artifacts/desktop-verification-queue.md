---
title: Desktop verification queue
purpose: Checks that GitHub CI cannot run (real Docker host, live Ollama/GPU, nginx in front, benchmarks). Run these on the RTX test box when it is back, then tick them off.
---

# Desktop verification queue

Stories were merged on green GitHub CI while the desktop was offline (owner decision 2026-11-01: "keep building without testing, we will test later"). Each entry lists the exact checks; full detail is in the story's spec under `_bmad-output/implementation-artifacts/`.

## E0-Platform.2 — CPU-only torch in the backend image (PR #20)
- [ ] `docker build -f src/backend/Dockerfile.prod -t lk-backend-cpu src/backend` and the same with `-f src/backend/Dockerfile` (build guard must pass)
- [ ] `docker run --rm lk-backend-cpu pip list | grep -iE 'nvidia|cuda'` prints nothing; `python -c "import torch; assert not torch.cuda.is_available()"` passes
- [ ] In-image: `LOREKEEPER_EDITION=commercial` and `agpl` → `scripts/check-licenses.py --python-env --register licenses/register.yaml --artifact backend` = 0 violations
- [ ] `docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod src/backend` succeeds
- [ ] Image size vs a `main` build before this change (record in PR #20)
- [ ] Backend suite + `/api/health`, journal save, retrieval, `test_nlp.py` against the new image

## E0-QA.5 — Tests build the schema from Alembic migrations (PR #21)
- [ ] Run the suite on a lane DB that still has tables from the old `create_all` era (`-e TEST_DATABASE_URL=… -e DATABASE_URL=<same>`); expect green and `alembic_version` = `a3e7c1f9d258` afterwards
- [ ] Known drift to decide on (reported, not fixed): duplicate unique constraint+index on `password_reset_tokens.token_hash` and `promo_codes.code`; 12 migration-only server defaults; `app_config` seeds open-access ON while the app default is OFF

## E0-QA.8 — Licence scan of the shipped images (PR #24)
- [x] ~~E0-Platform.2 amd64 `Dockerfile.prod` build + in-image scan~~ — **verified in CI** by the new `image-licenses` job: CPU torch from the CPU index, nvidia/cuda guard passed, 129 pip packages / 0 violations in both editions
- [ ] arm64: `docker buildx build --platform linux/arm64 -f src/backend/Dockerfile.prod -t lk-backend-arm src/backend --load`, then the scan from `docs/LICENSING.md` (expect a few new Debian register entries)
- [ ] Regression check: in-image scan with `--artifact backend` against the old CUDA `lorekeeper-backend-test` image → exit 1 listing the NVIDIA wheels; with `--artifact ml-gpu` → pending warnings
- [ ] Stack: `docker compose -f docker-compose.prod.yml up -d --build`, `/api/health`, spaCy `en_core_web_trf` loads
- [ ] Dev image `docker build -f src/backend/Dockerfile src/backend` (not shipped, so not in CI)
- [ ] **Owner action before publishing any built image:** meet the GPL source obligation for OS packages (ship source or a written offer) — see `docs/LICENSING.md`
