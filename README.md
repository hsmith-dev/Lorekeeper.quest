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

**Requirements:** [Docker](https://docs.docker.com/get-docker/) with Compose (Docker Desktop on Windows/macOS, docker engine + compose plugin on Linux) · ~8 GB free RAM · ~15 GB free disk (images + one model). An NVIDIA GPU is optional but makes generation much faster — see [GPU](#gpu-optional-big-speedup) below.

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

### GPU (optional, big speedup)

With an NVIDIA GPU, add a compose override giving the `ollama` service a device reservation:

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

then start with both files: `docker compose -f docker-compose.prod.yml -f docker-compose.override.yml up -d`. Verify with `ollama ps` (should read `100% GPU`). A 7B Q4 model needs ~5 GB VRAM; generations drop from minutes (CPU) to seconds.

## Access modes

**Open access is the default**: anyone can register and use the app — including the self-hosted model — with no promo code, subscription, or billing. That covers self-hosting, a company provisioning accounts for its users, and free community servers.

Restricting who gets in is a checkbox, not a redeploy: the **admin portal → Platform tab** has an "Open access" toggle. Untick it and new accounts need a promo code, mintable from the same portal — handy for invite-only servers. The `OPEN_ACCESS_MODE` env var only seeds the initial value; the portal setting is authoritative after that.

Running Lorekeeper as a **paid service** (Stripe subscriptions — the integration ships in the codebase, dormant) requires a commercial license: contact **hello@harrisonsmith.ai** for the license and setup guide. See [License](#license).

## Architecture

FastAPI backend · React frontend · PostgreSQL + pgvector (embeddings & retrieval) · Redis (caching) · Ollama (LLM serving) · nginx — one Docker Compose stack. See `docs/` for deployment, backups, and email setup.

## License

**AGPL-3.0, dual-licensed.** Free to use, modify, and self-host — but if you modify Lorekeeper and make it available to others (including as a network service), the AGPL requires you to publish your complete modified source under the same license. For commercial use without those obligations — a paid hosted service, a proprietary product, unreleased modifications — a separate commercial license is required: see [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md).

Copyright © 2026 Harrison Smith.
