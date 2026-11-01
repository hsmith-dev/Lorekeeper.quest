---
title: 'E0-Platform.1: Dev compose ports bind to localhost by default'
type: 'chore'
created: '2026-10-31'
status: 'done'
baseline_revision: '9de94d26304535c94e756f510784a3381a617944'
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred:
  - summary: >-
      No CI check asserts that the dev compose files publish every port on 127.0.0.1 when BIND_IP is unset.
    evidence: |-
      No workflow renders docker-compose.yml or docker-compose.dev.yml (backend-tests.yml uses a service container), so a later edit that drops the ${BIND_IP:-127.0.0.1}: prefix or adds an unprefixed port would pass CI. CI gates belong to E0-QA's harness (CI-1..CI-15) and .github/workflows is outside this story's owned files. Suggested gate: `docker compose -f <file> config --format json` with BIND_IP unset, fail if any services[].ports[].host_ip != 127.0.0.1, and assert that prod publishes only 80/443.
    location: >-
      .github/workflows/ (new step); docker-compose.yml, docker-compose.dev.yml
    severity: medium
---

<intent-contract>

## Intent

**Problem:** `docker-compose.yml` and `docker-compose.dev.yml` publish Postgres (5432), Redis (6379), the backend (8000) and Vite (5173) on every host interface. Docker-published ports bypass ufw, so a fresh `docker compose up` exposes an unauthenticated Redis and a `changeme` Postgres to the LAN.

**Approach:** Prefix every dev `ports:` entry with `${BIND_IP:-127.0.0.1}:` so the default is loopback-only and a self-hoster can opt in to one specific interface (e.g. a Tailscale IP) via `BIND_IP` in `.env`. Document `BIND_IP` in `.env.example` (with a warning against `0.0.0.0`) and add a short "Remote dev over Tailscale" note to `README.md`.

## Boundaries & Constraints

**Always:** Default (unset or empty `BIND_IP`) renders every dev port as `host_ip: 127.0.0.1`. Container-side ports and host ports stay the same numbers. Use the `:-` form so an empty `BIND_IP=` also falls back to loopback.

**Never:** Change `docker-compose.prod.yml` port publishing (only nginx publishes 80/443). Touch `tests/conftest.py` / `TEST_DATABASE_URL` (E0-QA). Add new services, profiles or env files. Recommend `0.0.0.0`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Default | no `BIND_IP` | `docker compose config` shows `host_ip: 127.0.0.1` for 5432, 6379 (dev file) and 5432, 6379, 8000, 5173 (main file) | No error expected |
| Empty | `BIND_IP=` | same as default | No error expected |
| Opt-in | `BIND_IP=100.x.y.z` | every dev port has `host_ip: 100.x.y.z`; not reachable on LAN address | No error expected |
| Prod | `docker-compose.prod.yml` | unchanged: only nginx `80:80`, `443:443` | No error expected |

</intent-contract>

## Code Map

- `docker-compose.dev.yml` -- lines 11-12 (`"5432:5432"`), 23-24 (`"6379:6379"`); header comment uses legacy `docker-compose`.
- `docker-compose.yml` -- lines 10, 22, 36, 52: postgres, redis, backend, frontend `ports:`. Backend uses `env_file: .env` (BIND_IP leaking into the container env is harmless).
- `docker-compose.prod.yml` -- lines 205-207: nginx only; read-only for this story.
- `.env.example` -- sectioned with `# ── Name ───` headers; add a "Dev compose port binding" section (commented `# BIND_IP=`, default unset).
- `README.md` -- Setup is prod-focused; add a short "Remote dev over Tailscale" subsection after "GPU (optional, big speedup)" and before "## Access modes".

## Tasks & Acceptance

**Execution:**
- `docker-compose.dev.yml` -- change both ports to `"${BIND_IP:-127.0.0.1}:5432:5432"` / `"${BIND_IP:-127.0.0.1}:6379:6379"`; note BIND_IP in the header comment -- loopback by default.
- `docker-compose.yml` -- same prefix on 5432, 6379, 8000, 5173 -- loopback by default.
- `.env.example` -- document `BIND_IP` (default 127.0.0.1, set to a Tailscale IP for remote dev, never `0.0.0.0` because Docker bypasses ufw; prod ignores it) -- discoverability.
- `README.md` -- "Remote dev over Tailscale" note: set `BIND_IP=<tailscale ip>` in `.env`, start the dev stack, connect from the laptop at that IP -- self-run remote access.

**Acceptance Criteria:**
- Given no `BIND_IP`, when `docker compose -f docker-compose.dev.yml config` and `docker compose config` are rendered (and the dev stack brought up), then every published port has host IP `127.0.0.1` only.
- Given `BIND_IP=<tailscale ip>`, when the dev stack starts, then Postgres and Redis listen on that IP only (not the LAN address).
- Given `docker-compose.prod.yml`, when this story lands, then its rendered ports are identical to `main`.

## Spec Change Log

## Review Triage Log

### 2026-10-31 — Review pass
- verdicts: 18 findings — high 0, medium 5, low 10, false 3, maybe-false 0
- findings:
  - `[low]` `[patch]` (edge) IPv6 BIND_IP unbracketed breaks the port spec — README and .env.example now say BIND_IP must be IPv4 (`tailscale ip -4`).
  - `[medium]` `[patch]` (edge) With BIND_IP set, loopback is no longer bound, so local clients on localhost fail — documented in README and .env.example (group: loopback-replaced).
  - `[low]` `[patch]` (edge) Bind fails with "cannot assign requested address" if Tailscale isn't up — README says to start Tailscale first and re-run `up -d` (group: tailscale-not-up).
  - `[low]` `[reject]` (edge) Nothing enforces against BIND_IP=0.0.0.0 — the intent asks only for a documented warning; a preflight guard adds new surface for a case users meet only by ignoring two warnings.
  - `[false]` `[reject]` (edge) Backend may reject unknown BIND_IP from env_file — src/backend/app/core/config.py:128 sets `extra = "ignore"`.
  - `[medium]` `[defer]` (verification-gap) No CI check renders the dev compose files and asserts host_ip 127.0.0.1 — CI gates belong to E0-QA and .github/workflows is outside this story's files; logged in frontmatter `deferred`.
  - `[medium]` `[patch]` (verification-gap) scripts/start.sh's `pg_isready -h localhost` fails when BIND_IP is set — same root cause as loopback-replaced; README names start.sh explicitly. start.sh does not read .env, so it only breaks when the user opts in.
  - `[medium]` `[patch]` (blind) BIND_IP replaces loopback, undocumented — group loopback-replaced; documented.
  - `[medium]` `[patch]` (blind) README URL lacks `+asyncpg` and gives no DATABASE_URL/REDIS_URL guidance — replaced with full laptop-side DATABASE_URL and REDIS_URL lines.
  - `[low]` `[patch]` (blind) No warning that BIND_IP exposes the services to every tailnet device — README sentence on Tailscale ACLs and a non-default Postgres password added.
  - `[low]` `[patch]` (blind) Docker fails if the Tailscale IP isn't up — group tailscale-not-up; documented.
  - `[false]` `[reject]` (blind) IPv6 localhost regression for the Vite proxy — in docker-compose.yml Vite runs in a container and its proxy never uses the published host port; browsers on the host use happy-eyeballs fallback to 127.0.0.1; the frontend image is node:20.
  - `[low]` `[patch]` (blind) README shows only docker-compose.dev.yml — added `docker compose up -d` for the full stack (8000/5173).
  - `[low]` `[patch]` (blind) 0.0.0.0 warning names only Redis/Postgres — now lists Postgres, Redis, backend API and Vite.
  - `[low]` `[patch]` (blind) No user-facing way to check the binding — added a `docker compose ... ps` check.
  - `[low]` `[patch]` (blind) Firewall wording is ufw-only — now "host firewalls such as ufw/firewalld on Linux".
  - `[low]` `[patch]` (blind) Section sits inside the prod Setup flow — the first sentence now says it is dev-only and doesn't affect prod.
  - `[false]` `[reject]` (intent-alignment) Runtime ACs are unproven: there is no bring-up or cross-host evidence — a real bring-up was run on the remote desktop (see Auto Run Result): loopback-only listeners, refused from another host over both Tailscale and LAN, then BIND_IP=Tailscale reachable over Tailscale and refused on LAN. It used high host ports because the owner's stack holds 5432/6379; binding semantics don't depend on the port number.

## Verification

**Commands:**
- `docker compose -f docker-compose.dev.yml config` (with and without `BIND_IP`) on the remote desktop in `~/lorekeeper-dev/runs/e0plat1/` -- expected: `host_ip` 127.0.0.1 / the given IP.
- `docker compose -f docker-compose.yml config -q` and `-f docker-compose.prod.yml config -q` -- expected: valid.
- Real bring-up: `-p lk-e0plat1` with a high-port override, check `docker compose port` / `ss -ltn`, then `down -v` -- expected: loopback-only listeners.

## Auto Run Result

Status: done

**Summary:** Every dev compose port is now published on `${BIND_IP:-127.0.0.1}`, so it is loopback-only by default and opt-in on a single interface such as a Tailscale IP. `BIND_IP` is documented in `.env.example` and in a README "Remote dev over Tailscale" section. Prod is unchanged.

**Files changed:**
- `docker-compose.dev.yml`: postgres 5432 and redis 6379 bind to `${BIND_IP:-127.0.0.1}`; the header comment uses `docker compose` and mentions BIND_IP.
- `docker-compose.yml`: postgres 5432, redis 6379, backend 8000 and frontend 5173 bind to `${BIND_IP:-127.0.0.1}`.
- `.env.example`: new "Dev compose port binding" section (IPv4 only, replaces loopback, warning against 0.0.0.0, ignored by prod).
- `README.md`: new dev-only "Remote dev over Tailscale" subsection.
- `_bmad-output/implementation-artifacts/epic-3-context.md`: compiled epic context (workflow cache).

**Review:** 18 findings. 13 patched (all documentation; entry verdicts: 2 medium groups, 8 low). 1 deferred (medium: CI gate for loopback defaults, E0-QA). 4 rejected: 3 false (backend settings ignore extra env vars; Vite IPv6 proxy; runtime evidence exists) and 1 low (0.0.0.0 enforcement goes beyond the documented-warning intent).

**Follow-up review:** false. Two medium entries were patched, but both are documentation-only text that was re-read in the final diff. No unverified risk can be named.

**Verification** (remote desktop, `~/lorekeeper-dev/runs/e0plat1/v`, project `lk-e0plat1`):
- `docker compose config` for docker-compose.dev.yml and docker-compose.yml:
  - BIND_IP unset: every port `host_ip: 127.0.0.1`.
  - `BIND_IP=`: every port `host_ip: 127.0.0.1`.
  - `BIND_IP=100.119.62.5` (env or `.env`): every port `host_ip: 100.119.62.5`.
- docker-compose.prod.yml renders with only nginx 80/443 published and no host_ip.
- Real bring-up of the dev file with host ports moved to 25432/26379 (the owner's stack holds 5432/6379):
  - Default: `docker compose port` and `ss -ltn` show `127.0.0.1` only. From the Mac, both ports are refused on 100.119.62.5 (Tailscale) and 10.0.0.38 (LAN), while LAN sshd answers.
  - With `BIND_IP=100.119.62.5` in `.env`: listeners are on 100.119.62.5 only. From the Mac, both ports are open over Tailscale and refused on the LAN address.
  - Torn down with `down -v` (0 containers, 0 volumes left). The owner's stack was untouched.
- The doc patches changed no compose file, so the compose results above still hold.

**Residual risks:** the defer entry (no CI regression gate). With BIND_IP set, same-machine localhost clients must switch to the BIND_IP address (documented).
