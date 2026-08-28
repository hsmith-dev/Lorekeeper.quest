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
git clone <this-repo> lorekeeper && cd lorekeeper
cp .env.example .env
# edit .env: set SECRET_KEY (openssl rand -hex 32) and POSTGRES_PASSWORD.
# Registration is open by default — no billing anywhere (see Access modes below).

docker compose -f docker-compose.prod.yml up -d --build
```

### Add a model

The stack serves models through [Ollama](https://ollama.com). The recommended model is **[Lorekeeper-Mistral-7B](https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF)** — the LoRA fine-tune of Mistral 7B this app was built around, trained on RPG session-journal data across 12 game systems:

```bash
# download into the models dir (mounted into the ollama container), ~4.4 GB
curl -L -o src/ml/models/lorekeeper-7b-q4.gguf \
  https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF/resolve/main/lorekeeper-7b-q4.gguf
curl -L -o src/ml/models/lorekeeper-Modelfile \
  https://huggingface.co/harrisonsmith/Lorekeeper-Mistral-7B-GGUF/resolve/main/lorekeeper-Modelfile

docker compose -f docker-compose.prod.yml exec ollama ollama create lorekeeper -f /import-models/lorekeeper-Modelfile
```

Optionally add the base model too (enables the in-app fine-tuned-vs-base comparison in Settings):

```bash
docker compose -f docker-compose.prod.yml exec ollama ollama pull mistral:7b-instruct-q4_0
docker compose -f docker-compose.prod.yml exec ollama ollama cp mistral:7b-instruct-q4_0 lorekeeper-base
```

Prefer a different model? Any instruct GGUF works — drop it in `src/ml/models/` with a Modelfile and `ollama create lorekeeper -f /import-models/your-Modelfile`, or `ollama cp` any pulled Ollama model to the name `lorekeeper`. The training pipeline that produced the fine-tune lives in `src/ml/`.

Then open **http://localhost** and register an account.

### TLS

`nginx/nginx.conf` expects Let's Encrypt certs at `/etc/letsencrypt/live/<your-domain>/`. For local use, mount a self-signed cert over `/etc/letsencrypt` via a compose override; for a real deployment see the TLS section of `docs/OCI_DEPLOYMENT.md`.

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
