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
