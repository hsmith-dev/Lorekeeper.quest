# Lorekeeper

**An AI campaign companion for tabletop RPGs that remembers your world.** Self-hosted, no external AI APIs required — a local LLM plus retrieval over your own campaign journal, so answers come from what actually happened at your table instead of hallucinated lore.

## What it does

- **Shorthand → story** — jot terse session notes; get a full narrative journal entry in your campaign's genre voice (fantasy, sci-fi, horror, and more). You review and edit before anything is saved.
- **Ask your campaign anything** — chat that retrieves your real journal entries (vector search over pgvector embeddings) before answering, cites its sources, and — when nothing relevant exists — *says so* and labels the reply "not from your journal" instead of inventing canon.
- **Session co-planner** — next-session outlines drafted from your actual journal, open quests, and NPC roster.
- **A grounded co-writing suite** — NPC bios, quest hooks, recaps, campaign concepts, and note autocomplete, all built from the campaign record.
- Plus: campaigns with shared membership, NPC & quest tracking, character sheets, tagging, timelines, source-document ingestion (PDF/text → canon retrieval), voice session recording with transcription, and shorthand glossaries.

Everything runs on your own machine. No OpenAI/Anthropic key needed (though bring-your-own-key is supported per-user in Settings if you want a cloud model instead).

## Quickstart (Docker)

Requirements: Docker with Compose. ~8 GB free RAM (or an NVIDIA GPU — see below).

```bash
# 1 · get the app
git clone <this-repo> lorekeeper && cd lorekeeper
cp .env.example .env

# 2 · edit .env — two values (the file walks you through it):
#     SECRET_KEY (openssl rand -hex 32) and POSTGRES_PASSWORD

# 3 · launch
docker compose -f docker-compose.prod.yml up -d --build
```

Then:

1. Open **https://localhost** — accept the browser's one-time warning about the self-signed certificate (the stack generates one automatically; see TLS below for real certs).
2. **Register** — the first account created on a fresh deployment automatically becomes the admin, so register yourself before sharing the URL. Registration is open by default — no billing anywhere (see Access modes below).
3. Go to **Admin → System → Model Library** and click **Download & install** on the fine-tuned model. It pulls **[Lorekeeper-Mistral-7B](https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF)** (~4.4 GB) straight from Hugging Face into the stack's Ollama, with live progress — no shell needed. Optionally install the base model too (enables the in-app fine-tuned-vs-base comparison in Settings).

That's the whole setup. Verify with **Settings → AI Provider → Test Connection**.

<details>
<summary>Prefer to install models from the CLI instead?</summary>

```bash
# fine-tuned model, straight from Hugging Face
docker compose -f docker-compose.prod.yml exec ollama ollama pull hf.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF
docker compose -f docker-compose.prod.yml exec ollama ollama cp hf.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF lorekeeper

# optional base model
docker compose -f docker-compose.prod.yml exec ollama ollama pull mistral:7b-instruct-q4_0
docker compose -f docker-compose.prod.yml exec ollama ollama cp mistral:7b-instruct-q4_0 lorekeeper-base
```

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

Running it as a paid service instead is a checkbox, not a redeploy: the **admin portal → Platform tab** has an "Open access" toggle. Untick it and new accounts need a promo code (mintable from the same portal) or a Stripe subscription (`docs/PAYMENT_PROCESSOR_SETUP.md`) — the full billing integration ships in the codebase, dormant until you turn gating on. The `OPEN_ACCESS_MODE` env var only seeds the initial value; the portal setting is authoritative after that.

## Architecture

FastAPI backend · React frontend · PostgreSQL + pgvector (embeddings & retrieval) · Redis (caching) · Ollama (LLM serving) · nginx — one Docker Compose stack. See `docs/` for deployment, backups, and email setup.

## License

**AGPL-3.0, dual-licensed.** Free to use, modify, and self-host — but if you modify Lorekeeper and make it available to others (including as a network service), the AGPL requires you to publish your complete modified source under the same license. For commercial use without those obligations — a paid hosted service, a proprietary product, unreleased modifications — a separate commercial license is required: see [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md).

Copyright © 2026 Harrison Smith.
