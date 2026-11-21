---
title: 'E0-Platform.7: One 16 GB profile with container limits, GPU override and sum check'
type: 'feature'
created: '2026-11-21'
status: 'done'
baseline_revision: '90c8ea18b688baa1306717a61e03e6f3b2007475'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/BENCHMARKS.md'
warnings: [oversized]
deferred:
  - summary: >-
      The shipped default (OLLAMA_CPUS=0, one thread per host core) is the configuration E0-QA.15 saw OOM-killed at the 5.25g ollama limit.
    evidence: |-
      docs/BENCHMARKS.md: the 12-thread uncapped run was OOM-killed at 5.25 GB on extraction_300; the 4-thread Reference Box run peaked at 5.08 GB. AD-7 fixes the limit at 5.25g and E0-Platform.10 owns the Ollama memory re-check (brief carry-over). Settle with the desktop RSS run under "Needs desktop verification".
    location: >-
      docker-compose.prod.yml (ollama deploy.resources)
    severity: high
  - summary: >-
      Valkey's RDB fork (--save 60 1) can push copy-on-write pages past the 128m limit while maxmemory is 96mb.
    evidence: |-
      Unmeasured. A BGSAVE fork's dirtied pages count against the same cgroup; under steady writes during a save, usage could exceed 128m. Settle by watching memory.peak during a save under queue load on the desktop.
    location: >-
      docker-compose.prod.yml (valkey command)
    severity: medium (unverified)
  - summary: >-
      Postgres is bounded only by shared_buffers=192MB; max_connections (100) and work_mem are left at defaults under the 768m limit.
    evidence: |-
      Each of 4 gunicorn workers and the RQ pool has a SQLAlchemy pool (pool_size=10, src/backend/app/db/session.py:10). Whether connection + sort memory can pass 768m is unmeasured; settle with memory.peak under a concurrent load test.
    location: >-
      docker-compose.prod.yml (postgres command)
    severity: medium (unverified)
  - summary: >-
      Host RAM of the GPU stt build (CUDA context, cuBLAS, cuDNN) has not been measured against the unchanged 1.25g limit.
    evidence: |-
      Only the CPU build was measured (base int8 0.5 GB cgroup). Settle by running the gpu target under the override and reading memory.peak.
    location: >-
      docker-compose.gpu.yml (stt)
    severity: medium (unverified)
  - summary: >-
      The runtime ACs (merged prod + gpu config, host-gateway reachability, Ollama env at start) are checked only by reading the YAML; no docker compose config/up ran.
    evidence: |-
      No Docker on the Mac and the desktop was unreachable from this run. Settle with `docker compose -f docker-compose.prod.yml -f docker-compose.gpu.yml config` and an `up` on the desktop.
    location: >-
      docker-compose.prod.yml, docker-compose.gpu.yml
    severity: medium (unverified)
---

<intent-contract>

## Intent

**Problem:** `docker-compose.prod.yml` hard-codes memory limits that sum to about 34 GiB (ollama 14g, backend 14g, postgres 3g, ...), so the "16 GB box" promise is untrue and CI-14 only checks a partial `.env.example` list; there is no GPU override file and no way to point the stack at a host Ollama.

**Approach:** Move every prod limit to an AD-7 `*_MEM_LIMIT` variable declared in `.env.example` (sum exactly 14.5 GiB, worker and tts reserved), tune ollama/postgres/valkey to fit, rename the prod `backend` service to `web`, add `docker-compose.gpu.yml`, and extend the existing CI-14 script (`scripts/check_memory_budget.py`, already wired in `gates.yml`) so a prod service without a limit variable, or an override that touches a limit, fails CI.

## Boundaries & Constraints

**Always:** limits are binary units (14.5 GiB ceiling, inclusive); compose references use `${X_MEM_LIMIT:-<same default as .env.example>}`; the diarize profile is outside the sum; `VALKEY_MEM_LIMIT` (not `REDIS_MEM_LIMIT`, owner rename round 3); OLLAMA_CPUS stays uncapped by default (v1.1: 585 s -> 76 s) and any cap is documented as needing a matching `num_thread`.

**Never:** new script name (`check_mem_limits.py` in epics = the existing `check_memory_budget.py`; renaming would break gates.yml, owned by E0-QA and touched by a sibling); edits to `gates.yml`, sprint-status, epics.md; adding a `tts` or `diarize` service (E5/E4); changing the dev compose files' service names; raising a limit above AD-7 (Kokoro's 3.1 GB peak is E0-Platform.10's).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Repo as shipped | AD-7 nine vars = 14.5 GiB | check exits 0 | — |
| Over budget | any var raised by 1m | exit 1, names the overshoot | — |
| Profile service without limit | prod service with no `memory:` or a literal | exit 1 naming the service | — |
| Limit var not declared | prod uses `${FOO_MEM_LIMIT:-1g}` absent from env | exit 1 | — |
| diarize service | service with `profiles: [diarize]` using `DIARIZE_MEM_LIMIT` | its var is reported but excluded from the sum | — |
| GPU override touches a limit | `memory:` key in docker-compose.gpu.yml | exit 1 | — |
| Literal baseline entry left | baseline line matching nothing | exit 1 (existing rule) | — |

</intent-contract>

## Code Map

- `scripts/check_memory_budget.py` -- CI-14; already sums `.env.example` vars, checks compose defaults, ratchets literals. Extend: `compose_services()` (indent parser: per-service memory value + profiles), profile-file coverage, diarize exclusion, override-file rule.
- `scripts/memory_literal_limits_baseline.txt` -- five prod literals; empty after this story.
- `scripts/test_check_memory_budget.py` -- `FROZEN_LITERALS` becomes empty; add tests for the new rules.
- `docker-compose.prod.yml` -- every service; `backend` -> `web` (alias `backend` on default network); worker `depends_on: web`; extra_hosts on web+worker.
- `nginx/nginx.conf:80` -- `server backend:8000;` -> `web:8000`.
- `.env.example` -- declare nine limits uncommented; GPU and host-Ollama notes; OLLAMA_CPUS/num_thread note.
- `docker-compose.gpu.yml` (new) -- ollama + stt device reservations, stt `build.target: gpu`, image `lorekeeper-stt:gpu`.
- `src/services/stt/Dockerfile` -- `gpu` target exists (sets `STT_DEVICE=cuda`); read-only.
- `README.md:17-19,92,118-161` -- 16 GB rationale, GPU section, host Ollama.
- `scripts/backup-db.sh:68`, `scripts/restore-db.sh`, `scripts/deploy-oci.sh:93,137`, `docs/*.md`, `src/backend/scripts/*.py` docstrings -- `exec backend` on prod -> `exec web`.

## Tasks & Acceptance

**Execution:**
- `scripts/check_memory_budget.py` -- add profile coverage (PROFILE_FILE=docker-compose.prod.yml), diarize exclusion, override rule (docker-compose.gpu.yml) -- AC 2, 5, 6.
- `scripts/test_check_memory_budget.py` -- cover each I/O row; empty FROZEN_LITERALS.
- `scripts/memory_literal_limits_baseline.txt` -- drop all entries.
- `.env.example` -- nine AD-7 vars, comments -- AC 1.
- `docker-compose.prod.yml` -- limits, ollama env, postgres `shared_buffers=192MB`, valkey `--maxmemory 96mb --maxmemory-policy noeviction`, web rename, extra_hosts, updated comments -- AC 1, 3, 5.
- `docker-compose.gpu.yml` -- new -- AC 4.
- `nginx/nginx.conf`, scripts, docs -- `web` rename; README 16 GB / GPU / host-Ollama text -- AC 3, 5.

**Acceptance Criteria:**
- Given `.env.example`, then it declares OLLAMA 5.25g, ML 2.5g, TTS 2.5g, STT 1.25g, WEB 1g, WORKER 1g, POSTGRES 768m, VALKEY 128m, NGINX 128m and each prod service uses its var as `deploy.resources.limits.memory`.
- Given `python scripts/check_memory_budget.py`, then it passes at exactly 14.5 GiB and fails above it or when a prod service lacks a limit variable.
- Given prod compose, then ollama has MAX_LOADED_MODELS=1, NUM_PARALLEL=1, CONTEXT_LENGTH=4096, KEEP_ALIVE=30m; the API runs as `web` with gunicorn -w 4 and 1g; the old 14g / memory.peak comment is replaced.
- Given `-f docker-compose.prod.yml -f docker-compose.gpu.yml config`, then only ollama and stt differ (GPU reservations, stt gpu target), and no limit changes.
- Given `KOBOLD_URL=http://host.docker.internal:11434` and `--scale ollama=0`, then web/worker reach the host via `host-gateway`, and docs say the 5.25g reserve still counts.

## Spec Change Log

## Review Triage Log

### 2026-11-21 — Review pass
- verdicts: 35 findings — high 3, medium 12, low 10, false 6, maybe-false 4
- findings:
  - `[high]` `[defer]` (blind) Default uncapped Ollama is the config seen OOM at 5.25g — real per BENCHMARKS.md; the limit is AD-7's and the re-check is E0-Platform.10's; deferred high + desktop verification.
  - `[maybe-false]` `[defer]` (blind) Valkey BGSAVE fork CoW can pass 128m — plausible, unmeasured; settle with memory.peak during a save under load.
  - `[maybe-false]` `[defer]` (blind) Postgres max_connections/work_mem unbounded under 768m — pools are 10/process; unmeasured; settle with a load test.
  - `[medium]` `[patch]` (blind) "always agree" gate claim false with LLM_GATE_CAPACITY — Ollama NUM_PARALLEL now fixed "1", comment rewritten to name LLM_GATE_CAPACITY, `.env.example` note added.
  - `[medium]` `[patch]` (blind) README:56 still lists `backend (healthy)` — now web/ml/stt, plus a `--remove-orphans` pointer.
  - `[low]` `[patch]` (blind) Rename stops at prod: docstrings above `exec web` still say "backend container" — fixed in 3 scripts and OCI_DEPLOYMENT.md:208; status.sh/stop.sh are false (they manage native dev processes, not the compose service); dev compose keeps `backend` by spec.
  - `[medium]` `[patch]` (blind) `--scale ollama=0` not persistent — README/.env.example/compose header now document an override with `deploy.replicas: 0` used on every `up`.
  - `[medium]` `[patch]` (blind) "5.25 GB still counts" unenforced for host Ollama — docs now tell the user to run the host Ollama with 4096 / 1 / 1 and say nothing caps it.
  - `[maybe-false]` `[defer]` (blind) GPU stt host RAM unmeasured vs 1.25g — deferred, desktop.
  - `[low]` `[patch]` (blind) VRAM figure ignores stt on GPU — README now says 6–8 GB and what partial offload does.
  - `[low]` `[patch]` (blind) README mixes GB and GiB — one-line binary-units note added.
  - `[medium]` `[patch]` (blind) Repo test pinned exact values and sum == ceiling, blocking a lower limit — now pins the variable set and compose wiring, sum `<=`; the exact-ceiling edge moved to a test on the AD-7 table.
  - `[medium]` `[patch]` (blind) same-indent block `profiles:` list misread — parser uses `>=`; parametrized test case added.
  - `[low]` `[patch]` (blind) override.yml limits outside the check — README sentence warns a `memory:` there is outside the budget.
  - `[low]` `[patch]` (blind) Two-model OCI regression + KEEP_ALIVE 60m→30m unexplained — compose comment and docs/UPGRADING.md now state both and the reload cost; values are AD-7's.
  - `[false]` `[reject]` (blind) Missing tests: nginx upstream / dev-prod name parity / gpu target compute type / skip-not-fail — upstream resolves via the `backend` alias either way; names differ by design; stt Dockerfile gpu stage is covered by src/services/stt/tests/test_dockerfile.py; the gpu file is read unguarded by test_gpu_override_touches_only_ollama_and_stt.
  - `[high]` `[patch]` (edge) Orphaned `backend` container keeps 14g beside `web` after upgrade — deploy-oci.sh uses `--remove-orphans`; README + docs/UPGRADING.md tell upgraders to do the same.
  - `[medium]` `[patch]` (edge) Orphan writes mid-restore — same root cause as above; covered by the upgrade instruction.
  - `[medium]` `[patch]` (edge) Host-Ollama opt-out lost on next `up` — grouped with the blind finding; same docs fix.
  - `[medium]` `[patch]` (edge) OLLAMA_NUM_PARALLEL=0 reaches Ollama and multiplies KV cache — compose now hard-codes "1"; test asserts it.
  - `[low]` `[patch]` (edge) Host Ollama context/parallel mismatch vs prompt budget — grouped with the "5.25 still counts" docs fix.
  - `[low]` `[reject]` (edge) noeviction makes cache writes raise 500s — access/cache.py already catches write failures and degrades; only dedup store_hash could raise, at a full Valkey; unlikely and the fix adds guards.
  - `[medium]` `[patch]` (edge) same-indent profiles list — grouped with the blind finding; fixed.
  - `[low]` `[reject]` (edge) quoted service keys / YAML merge keys mis-parsed — not used in any compose file here; supporting them adds parser complexity.
  - `[low]` `[reject]` (edge) `--compose` list without the prod file passes the profile rule vacuously — CI runs the default glob, which always includes it; a guard would break fixture-based runs.
  - `[medium]` `[patch]` (verification-gap) ops scripts name prod services with no test — added test_ops_scripts_name_real_prod_services (mutation-checked: stale `backend` in stop/run/start is caught).
  - `[medium]` `[patch]` (verification-gap other) README:56 / OCI_DEPLOYMENT.md:208 still say backend — fixed (same as blind row).
  - `[high]` `[defer]` (verification-gap other) default ollama config OOM risk — same as the blind row; deferred.
  - `[low]` `[reject]` (verification-gap other) web 1g unmeasured — already listed under "Needs desktop verification"; nothing to change in code.
  - `[false]` `[reject]` (intent) script not named check_mem_limits.py — the CI-14 gate already exists as check_memory_budget.py wired in gates.yml; renaming would break E0-QA's workflow.
  - `[false]` `[reject]` (intent) VALKEY_MEM_LIMIT instead of REDIS_MEM_LIMIT — owner round-3 rename plus the brief's carry-over note ("use VALKEY_MEM_LIMIT").
  - `[false]` `[reject]` (intent) README did not say "about 8 GB" — true; it already said 16 GB, the rationale paragraph was the stale part and is rewritten.
  - `[maybe-false]` `[defer]` (intent) runtime ACs exercised only by YAML reads — deferred, desktop `config`/`up`.
  - `[false]` `[reject]` (intent) "every service needs a limit" scoped to prod only — the profile is docker-compose.prod.yml (AD-7 "one profile"); dev files are not the 16 GB profile.
  - `[false]` `[reject]` (intent) diarize exclusion tested only by fixtures — no diarize service exists until E4; the fixture covers the rule E4 will rely on.

## Design Notes

Profile coverage parses only `docker-compose.prod.yml`: the dev files are not the 16 GB profile (no limits there besides worker). A var counts toward the sum unless every service that references it is in the `diarize` profile; reserved vars with no service (TTS) still count. 12-thread Ollama was OOM-killed at 5.25g in E0-QA.15 (4 threads peaked 5.08 GB); the limit stays per AD-7 and is flagged for desktop verification.

## Verification

**Commands:**
- `python3 scripts/check_memory_budget.py` -- expected: OK, sum 14.50 GiB
- `python3 -m pytest -q scripts/test_check_memory_budget.py` -- expected: all pass
- `docker compose -f docker-compose.prod.yml -f docker-compose.gpu.yml config -q` (CI or desktop, needs a .env) -- expected: valid

## Auto Run Result

Status: done

**Summary.** `docker-compose.prod.yml` is the one 16 GB profile: every service takes its memory limit from an AD-7 `*_MEM_LIMIT` variable declared in `.env.example` (ollama 5.25g, ml 2.5g, tts 2.5g reserved, stt 1.25g, web 1g, worker 1g, postgres 768m, valkey 128m, nginx 128m = 14.5 GiB exactly). The old literals (sum about 34 GiB) and their baseline are gone. Ollama runs 1 loaded model, 1 parallel slot, a 4096 context and 30m keep-alive; Postgres `shared_buffers=192MB`; Valkey `--maxmemory 96mb --maxmemory-policy noeviction`. The API service is `web` (gunicorn -w 4, 1g, alias `backend`), and `web`/`worker` map `host.docker.internal` to the host gateway. New `docker-compose.gpu.yml` reserves a GPU for ollama and stt and builds stt's local `gpu` target; it changes no limit. CI-14 (`scripts/check_memory_budget.py`, already in gates.yml) now also fails when a prod service has no limit variable or the GPU override sets a limit, and leaves `diarize`-profile variables out of the sum.

**Files changed**
- `scripts/check_memory_budget.py` — profile coverage, diarize exclusion, override rule.
- `scripts/test_check_memory_budget.py` — tests for each new rule; empty literal ceiling.
- `scripts/memory_literal_limits_baseline.txt` — emptied.
- `.env.example` — Memory budget block; host-Ollama, OLLAMA_CPUS/num_thread and NUM_PARALLEL notes.
- `docker-compose.prod.yml` — limits, tuning, `web` rename, extra_hosts, comments.
- `docker-compose.gpu.yml` — new GPU override.
- `nginx/nginx.conf` — upstream `web:8000`.
- `src/backend/tests/test_compose_sidecars.py` — AD-7 sidecar limits, GPU override shape, prod web/tuning, ops-script service names.
- `README.md`, `docs/UPGRADING.md`, `docs/OCI_DEPLOYMENT.md`, `docs/DATABASE_BACKUPS.md`, `docs/EMAIL_SETUP.md`, `docs/RETRIEVAL_EVAL.md` — 16 GB table, GPU and host-Ollama sections, upgrade notes, `exec web`.
- `scripts/backup-db.sh`, `scripts/restore-db.sh`, `scripts/deploy-oci.sh` — `web` service name; `--remove-orphans`.
- `src/backend/scripts/{backfill_party_embeddings,eval_retrieval,seed_demo}.py` — usage docstrings.

**Review.** 35 findings: 21 patched (entry verdicts: high 1, medium 11 incl. grouped, low 9 — see the triage log), 5 deferred (frontmatter `deferred`), 9 rejected with reasons in the log. Follow-up review recommended: true — a `high` was patched (orphaned `backend` container after the rename); the unverified risk is whether `--remove-orphans` plus the docs fully cover existing installs, which only a real upgrade on the desktop shows.

**Verification.** `python3 scripts/check_memory_budget.py` → OK, 14.50 GiB. `pytest scripts/test_check_memory_budget.py src/backend/tests/test_compose_sidecars.py` → 63 passed. `bash -n` on the three edited shell scripts → ok. No `docker compose config` run (no Docker locally; desktop unreachable).

**Needs desktop verification**
```bash
# 1. Merged config renders, and the override only adds GPU devices:
docker compose -f docker-compose.prod.yml -f docker-compose.gpu.yml config > /tmp/gpu.yml
docker compose -f docker-compose.prod.yml config > /tmp/cpu.yml && diff /tmp/cpu.yml /tmp/gpu.yml
# 2. RSS against each limit, idle and under load (one heavy Job, a chat answer, an extraction_300 prompt):
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'
for c in $(docker compose -f docker-compose.prod.yml ps -q); do echo $(docker inspect -f '{{.Name}}' $c) $(docker exec $c cat /sys/fs/cgroup/memory.peak 2>/dev/null); done
# 3. Ollama 12-thread at 5.25g (E0-QA.15 OOM): watch `docker inspect -f '{{.State.OOMKilled}}'` on ollama after an extraction_300 call.
# 4. GPU: ollama `ollama ps` shows 100% GPU; stt /v1/status shows device cuda; stt memory.peak vs 1.25g.
# 5. Host Ollama: KOBOLD_URL=http://host.docker.internal:11434, ollama replicas 0; web reaches the host's lorekeeper model.
```

**Residual risks.** Ollama 5.25g with uncapped threads (deferred, high, E0-Platform.10); Valkey fork CoW, Postgres connection memory, GPU stt host RAM (deferred, unverified); Kokoro's 3.1 GB peak vs the reserved 2.5g tts limit stays E0-Platform.10's.
