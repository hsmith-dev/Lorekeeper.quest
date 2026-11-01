# Lorekeeper

**An AI campaign companion for tabletop RPGs that remembers your world.** Self-hosted, no external AI APIs required — a local LLM plus retrieval over your own campaign journal, so answers come from what actually happened at your table instead of hallucinated lore.

## What it does

- **Shorthand → story** — jot terse session notes; get a full narrative journal entry in your campaign's genre voice (fantasy, sci-fi, horror, and more). You review and edit before anything is saved.
- **Ask your campaign anything** — chat that retrieves your real journal entries (vector search over pgvector embeddings) before answering, cites its sources, and — when nothing relevant exists — *says so* and labels the reply "not from your journal" instead of inventing canon.
- **Session co-planner** — next-session outlines drafted from your actual journal, open quests, and NPC roster.
- **A grounded co-writing suite** — NPC bios, quest hooks, recaps, campaign concepts, and note autocomplete, all built from the campaign record.
- Plus: campaigns with shared membership, NPC & quest tracking, character sheets, tagging, timelines, source-document ingestion (PDF/text → canon retrieval), voice session recording with transcription, and shorthand glossaries.

Everything runs on your own machine. No OpenAI/Anthropic key needed (though bring-your-own-key is supported per-user in Settings if you want a cloud model instead).

## Setup (Docker)

**Requirements:** [Docker](https://docs.docker.com/get-docker/) with Compose (Docker Desktop on Windows/macOS, docker engine + compose plugin on Linux) · **16 GB RAM recommended** · ~15 GB free disk (images + one model). An NVIDIA GPU is optional but makes generation much faster — see [CPU vs GPU speed](#cpu-vs-gpu-speed) below.

Why 16 GB: measured on a running stack, the backend (4 workers + embedding model) sits around 4 GB and the model server around 5 GB once the 7B model is loaded, so ~9 GB steady. Both spike during generation and at startup (backend ~8 GB, model server ~9 GB at peak), so the combined worst case is ~17 GB. The two peaks don't usually line up, so 16 GB (ideally with some swap) is the practical baseline; 8 GB is not enough.

### 1 · Clone and configure

```bash
git clone https://github.com/hsmith-dev/Lorekeeper.quest.git lorekeeper
cd lorekeeper
cp .env.example .env      # Windows (PowerShell): copy .env.example .env
```

Open `.env` in any editor. Only **two values** need changing (the file walks you through everything else):

| Variable | Set it to |
|---|---|
| `SECRET_KEY` | any long random string — generate one with `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | any strong password — **also replace `changeme` inside `DATABASE_URL`, two lines up, with the same password** |

### 2 · Launch

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The first build takes a few minutes (downloads base images, builds the frontend, installs Python deps). When it finishes, `docker compose -f docker-compose.prod.yml ps` should show every service `Up`, with postgres/redis/ollama/backend `(healthy)`.

### 3 · Create your admin account

Open **https://localhost** in a browser. You'll hit a one-time warning about a self-signed certificate — that's expected (the stack generates its own; see [TLS](#tls) for real certs), click through it.

Click **Register**. **The first account created on a fresh deployment automatically becomes the admin** — so register yourself before sharing the URL with anyone. Everyone after that is a regular user (registration is open by default, no billing anywhere — see [Access modes](#access-modes)).

### 4 · Install the AI model

The app will tell you itself — a banner on the dashboard says no model is installed yet. Follow its link (or go to **Admin → System → Model Library**) and click **Download & install** on **Lorekeeper (fine-tuned)**. That downloads [Lorekeeper-Mistral-7B](https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF) (~4.4 GB GGUF) from Hugging Face and imports it into the stack's Ollama with a live progress bar — no shell needed. Keep the tab open until it finishes. The backend stages the file in its temp folder while it imports it, so it needs ~5 GB free there (set `LLM_DOWNLOAD_DIR` to use a different folder); the file is deleted afterwards.

Optionally install the **base model** too — it enables the fine-tuned-vs-base comparison in Settings → Model Evaluation.

### 5 · Verify

**Settings → AI Provider → Test Connection** should reply with a model response within a few seconds (up to ~a minute on CPU for the very first request while the model loads). Then make a campaign and write your first journal entry.

That's the whole setup.

<details>
<summary>Prefer to install models from the CLI instead?</summary>

Don't use `ollama pull hf.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF`. That repo also holds the LoRA adapter, so Ollama rejects it with *"Repository is not GGUF or is not compatible with llama.cpp"*. Download the GGUF and its Modelfile instead, then build the model from them. Run this from the repo root (Linux/macOS):

```bash
# fine-tuned model: download the GGUF (~4.4 GB) + Modelfile into src/ml/models,
# which the ollama container sees as /import-models
HF=https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF/resolve/main
mkdir -p src/ml/models
curl -fL -C - -o src/ml/models/lorekeeper-7b-q4.gguf "$HF/lorekeeper-7b-q4.gguf"
curl -fL -o src/ml/models/lorekeeper-Modelfile "$HF/lorekeeper-Modelfile"
docker compose -f docker-compose.prod.yml exec ollama ollama create lorekeeper -f /import-models/lorekeeper-Modelfile

# optional base model
docker compose -f docker-compose.prod.yml exec ollama ollama pull mistral:7b-instruct-q4_0
docker compose -f docker-compose.prod.yml exec ollama ollama cp mistral:7b-instruct-q4_0 lorekeeper-base
```

Running Ollama directly instead of in the stack? Download both files into one folder, `cd` into it, and run `ollama create lorekeeper -f lorekeeper-Modelfile`.

**Windows (PowerShell):** use `curl.exe`, not `curl`. In PowerShell, `curl` is an alias for `Invoke-WebRequest`, which doesn't take these flags. Set the variable with `$HF = "https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF/resolve/main"`, create the folder with `mkdir -Force src\ml\models`, and use `curl.exe -fL -C - -o src\ml\models\lorekeeper-7b-q4.gguf "$HF/lorekeeper-7b-q4.gguf"` (and the same for the Modelfile). The `docker compose ... ollama create` line works unchanged.

Prefer a different model entirely? Any instruct GGUF works — `ollama cp` any pulled Ollama model to the name `lorekeeper`, or drop a GGUF in `src/ml/models/` with a Modelfile and `ollama create lorekeeper -f /import-models/your-Modelfile`. The training pipeline that produced the fine-tune lives in `src/ml/`.
</details>

### Troubleshooting

- **Admin → System** shows whether the model server is reachable and which models are installed, has a live view of recent backend logs, and a **Download support bundle** button — a zip of recent logs plus a sanitized snapshot of the deployment's state (no secrets). Send that zip to **hello@harrisonsmith.ai** or attach it when [opening an issue](../../issues).
- "AI model unavailable" or chat errors while Test Connection looks fine usually means no model is installed under the expected name — the Model Library shows this at a glance, and Test Connection will now tell you exactly that.
- Raw container logs: `docker compose -f docker-compose.prod.yml logs backend --tail 200` (also `nginx`, `ollama`, `postgres`).

### TLS

Out of the box the stack generates a **self-signed certificate** at startup (browsers warn once; fine for local/LAN use). For a real domain, get a Let's Encrypt cert onto the host (`certbot certonly --standalone`) — the nginx container mounts `/etc/letsencrypt` and automatically prefers a real cert found there. See the TLS section of `docs/OCI_DEPLOYMENT.md`.

### CPU vs GPU speed

**On CPU, expect minutes per answer, not seconds.** A 7B model on CPU generates roughly a few tokens per second depending on your cores and memory bandwidth, and a full chat answer or journal entry is several hundred tokens, so one reply typically takes one to several minutes. The bundled `ollama` container uses all your CPU cores by default. On a shared machine you can cap it with `OLLAMA_CPUS` in `.env` (e.g. `OLLAMA_CPUS=6`), at the cost of proportionally slower replies. Requests time out after `KOBOLD_TIMEOUT_SECONDS` (default 1200 s); raise it if slow hardware hits that.

### GPU (optional, big speedup)

With an NVIDIA GPU (and the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) on the host), add a compose override giving the `ollama` service a device reservation:

```yaml
# docker-compose.override.yml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

then start with both files: `docker compose -f docker-compose.prod.yml -f docker-compose.override.yml up -d`. Verify with `docker compose -f docker-compose.prod.yml exec ollama ollama ps` (should read `100% GPU`). A 7B Q4 model needs ~5 GB VRAM; generations drop from minutes (CPU) to seconds.

### Changing nginx's ports or bind address

`docker-compose.prod.yml` publishes nginx on `80` and `443` on all interfaces. Compose *appends* an override file's `ports` list to the base file's instead of replacing it, so a plain `ports:` entry in `docker-compose.override.yml` adds a binding and still leaves 80/443 open. Use `!override` to replace the list:

```yaml
# docker-compose.override.yml — e.g. serve only on a Tailscale IP, on 8443
services:
  nginx:
    ports: !override
      - "100.x.y.z:8080:80"
      - "100.x.y.z:8443:443"
```

`!override` needs Docker Compose v2.24 or newer. Check the result with `docker compose -f docker-compose.prod.yml -f docker-compose.override.yml config nginx` before `up -d`. The same file can hold the GPU section above.

### Known limitations

- **Per-user rate limits are counted per backend worker.** The app's own limits (e.g. 20 AI requests/minute per user) are kept in each of the 4 gunicorn workers' memory, so in practice a user can get up to 4× that before the app refuses. nginx's stricter per-user limit on AI endpoints (10/minute, short burst allowed) applies first, so that is the limit you'll actually hit.

### Remote dev over Tailscale

Dev-only: this applies to `docker-compose.yml` and `docker-compose.dev.yml`, which publish their ports on `127.0.0.1` by default, and does not affect `docker-compose.prod.yml`. To reach them from another machine (e.g. a laptop working against a desktop):

- Start Tailscale first, then set `BIND_IP` in `.env` to the desktop's Tailscale IPv4 address (`tailscale ip -4`; an unbracketed IPv6 address breaks the port spec). If Tailscale wasn't up, `up -d` fails with "cannot assign requested address": start it and re-run `up -d`.
- Run `docker compose -f docker-compose.dev.yml up -d` (Postgres + Redis), or `docker compose up -d` for the full dev stack (adds backend 8000 and Vite 5173). Check with `docker compose -f docker-compose.dev.yml ps`: it should show `127.0.0.1:5432->5432` (or your `BIND_IP`).
- On the laptop: `DATABASE_URL=postgresql+asyncpg://lorekeeper:changeme@100.x.y.z:5432/lorekeeper` and `REDIS_URL=redis://100.x.y.z:6379/0`.
- `BIND_IP` replaces loopback rather than adding to it, so clients on the desktop itself (psql, a natively run backend, `scripts/start.sh`'s `pg_isready -h localhost`) must also use the `BIND_IP` address.
- Every device on your tailnet can then reach these services: restrict them with Tailscale ACLs and use a non-default Postgres password.
- Never set `BIND_IP=0.0.0.0`: Docker-published ports bypass host firewalls such as ufw/firewalld on Linux, so Postgres, Redis, the backend API and Vite would be exposed to your whole LAN.

## Access modes

**Open access is the default**: anyone can register and use the app — including the self-hosted model — with no promo code, subscription, or billing. That covers self-hosting, a company provisioning accounts for its users, and free community servers.

Restricting who gets in is a checkbox, not a redeploy: the **admin portal → Platform tab** has an "Open access" toggle. Untick it and new accounts need a promo code, mintable from the same portal — handy for invite-only servers. The `OPEN_ACCESS_MODE` env var only seeds the initial value; the portal setting is authoritative after that.

Running Lorekeeper as a **paid service** (Stripe subscriptions — the integration ships in the codebase, dormant) requires a commercial license: contact **hello@harrisonsmith.ai** for the license and setup guide. See [License](#license).

## Architecture

FastAPI backend · React frontend · PostgreSQL + pgvector (embeddings & retrieval) · Redis (caching) · Ollama (LLM serving) · nginx — one Docker Compose stack. See `docs/` for deployment, backups, and email setup, and [docs/RELEASE_NOTES.md](./docs/RELEASE_NOTES.md) for what changed in each release.

## Running tests

The backend suite (`src/backend`) runs against a real pgvector Postgres. Install the dependencies and the spaCy model first:

```bash
cd src/backend
pip install -r requirements.txt -r requirements-dev.txt
python -m spacy download en_core_web_trf
```

By default the suite connects to:

```
postgresql+asyncpg://lorekeeper:changeme@localhost:5432/lorekeeper_test
```

Point it somewhere else with `TEST_DATABASE_URL` (unset or empty means the default). The app's own engine, used by the account gate and `/api/health`, still connects through `DATABASE_URL`, so set that to the same URL. The app's settings also require `POSTGRES_PASSWORD` and `SECRET_KEY`:

```bash
# Postgres on another machine, e.g. over Tailscale
URL=postgresql+asyncpg://lorekeeper:changeme@my-desktop.tailnet.ts.net:5432/lorekeeper_test
TEST_DATABASE_URL=$URL DATABASE_URL=$URL POSTGRES_PASSWORD=changeme SECRET_KEY=test-only \
  python -m pytest
```

The suite drops and recreates every table, so it refuses to start unless the database name ends in `_test` or `_test_<lane>` (lane = letters and digits). `lorekeeper` or `lorekeeper_testing` aborts the run before anything connects. The guard checks only the database name, not the host or credentials. When several worktrees share one Postgres, give each its own database, e.g. `lorekeeper_test_e0qa4`. Create it once as the `lorekeeper` role, for example with `psql` on the pgvector server: `CREATE DATABASE lorekeeper_test_e0qa4;`. The suite runs `CREATE EXTENSION IF NOT EXISTS vector` itself, so the `vector` extension must be available on that server (the `pgvector/pgvector` image has it).

## License

**AGPL-3.0, dual-licensed.** Free to use, modify, and self-host — but if you modify Lorekeeper and make it available to others (including as a network service), the AGPL requires you to publish your complete modified source under the same license. For commercial use without those obligations — a paid hosted service, a proprietary product, unreleased modifications — a separate commercial license is required: see [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md).

Copyright © 2026 Harrison Smith.
