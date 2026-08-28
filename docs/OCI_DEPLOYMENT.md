# Deploying to Oracle Cloud Infrastructure (OCI)

You have an OCI account with nothing provisioned yet. This is the concrete,
in-order path from that to a running Lorekeeper instance on the **Always
Free** tier, plus how to scale beyond it if demand grows. The automatable
parts are in `scripts/deploy-oci.sh`; everything below that script can't do
for you (it needs your account, not just SSH access) is spelled out step by
step.

## Why VM.Standard.A1.Flex

OCI's Always Free tier includes up to **4 OCPUs / 24 GB RAM** of Ampere
(ARM64) compute, split across up to 4 `VM.Standard.A1.Flex` instances, at
**$0/month for as long as the account exists** (not a 12-month trial like
most "free tier" cloud offers — this specific shape is permanently free).
That's enough to run Postgres + Redis + the backend + Ollama serving the
fine-tuned 7B model (quantized to Q4, ~4-5 GB) + nginx all on one box. The
tradeoff is ARM64 — every image in `docker-compose.prod.yml` was verified to
have a real `linux/arm64` build (not just an x86_64 image running under
emulation), including a from-scratch `docker buildx build --platform
linux/arm64` of the custom backend image, so this isn't a "should work"
claim.

## 1. Create the instance (OCI Console)

1. Log into [cloud.oracle.com](https://cloud.oracle.com) → hamburger menu →
   **Compute** → **Instances** → **Create Instance**.
2. **Name**: `lorekeeper` (or whatever).
3. **Placement**: leave default unless you have a reason to pick a specific
   availability domain.
4. **Image and shape**:
   - Click **Edit** next to "Image" → **Ubuntu** → pick the newest 22.04 or
     24.04 LTS **aarch64** build (the image list defaults to x86_64 —
     switch the architecture toggle).
   - Click **Edit** next to "Shape" → **Ampere** → `VM.Standard.A1.Flex` →
     set **4 OCPUs / 24 GB memory** (the max included in Always Free — no
     reason to provision less since it doesn't cost anything either way).
5. **Networking**: default VCN is fine. Leave "Assign a public IPv4 address"
   checked — you need it reachable.
6. **Add SSH keys**: either paste a public key you already have
   (`~/.ssh/id_ed25519.pub` or similar) or let the console generate a
   keypair and download the private key — you'll need it to SSH in.
7. **Boot volume**: default (50 GB) is enough; Always Free includes up to
   200 GB total boot volume storage if you want to bump it.
8. **Create**. Provisioning takes 1-3 minutes.

**If you get "Out of capacity" for A1.Flex**: this shape is popular and
some regions run out of free-tier Ampere capacity. Two fixes: (a) try a
different region when you first set up the OCI account (Frankfurt
`eu-frankfurt-1` and Singapore `ap-singapore-1` tend to have more headroom
than US regions), or (b) just retry — capacity frees up as other people's
instances terminate, and OCI's console will let you know immediately if the
shape's unavailable rather than half-provisioning something broken.

## 2. Open the firewall (Security List)

By default OCI blocks everything except SSH (port 22). You need 80/443 open
for the app itself — but **not** 11434 (Ollama), which should only ever be
reachable from the backend container on the same Docker network, never from
the internet (this is already enforced in `docker-compose.prod.yml` — the
`ollama` service has no `ports:` mapping to the host at all, so this step is
about the OCI-level firewall in front of that, not a redundant safeguard).

1. Console → **Networking** → **Virtual Cloud Networks** → click your VCN.
2. **Security Lists** → click the **Default Security List**.
3. **Add Ingress Rules**, twice:
   - Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `80`
   - Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `443`
   (port 22/SSH should already be there from instance creation — don't
   remove it or you'll lock yourself out)

Ubuntu's own `ufw` is inactive by default on the OCI marketplace image, so
you don't need a second firewall layer inside the instance — but if you've
enabled it, `sudo ufw allow 80,443/tcp` first.

## 3. Get the code and model onto the instance

From your dev machine, note the instance's public IP (Console → Instances →
your instance → shown at the top), then:

```bash
ssh ubuntu@<public-ip>   # first connection asks to confirm the host key — yes

# from a second terminal on your dev machine, copy the repo over:
rsync -avz --exclude node_modules --exclude .git \
  /home/smith/Documents/Capstone/ ubuntu@<public-ip>:~/lorekeeper/

# the fine-tuned model is gitignored (too large for git) — copy it separately,
# it's the one large file this whole deployment actually needs:
rsync -avz --progress \
  /home/smith/Documents/Capstone/src/ml/models/lorekeeper-7b-q4.gguf \
  /home/smith/Documents/Capstone/src/ml/models/lorekeeper-Modelfile \
  ubuntu@<public-ip>:~/lorekeeper/src/ml/models/
```

## 4. Run the deploy script

SSH into the instance and run:

```bash
cd ~/lorekeeper
./scripts/deploy-oci.sh
```

This installs Docker if missing, generates `.env` (with a random
`SECRET_KEY`), brings up the full stack (`docker-compose.prod.yml`), waits
for Ollama to report healthy, and imports the fine-tuned model. Full detail
in the script's own header comment.

**Before it's actually safe to expose**, edit `.env` on the instance and set:

```
CORS_ORIGINS=["http://<public-ip>"]        # or https://yourdomain.com once you have one
FRONTEND_URL=http://<public-ip>
```

then `docker compose -f docker-compose.prod.yml restart backend`.

At this point `http://<public-ip>/` should load the app.

## 5. Set up a domain + HTTPS (recommended before any real users)

Without this, login/register submit plaintext passwords over HTTP. Cheapest
path:

1. Point a domain (or subdomain) at the instance's public IP via an A
   record with whatever registrar/DNS provider you use.
2. On the instance: `sudo apt install certbot python3-certbot-nginx -y` —
   but note `nginx` is running **inside a Docker container**, not on the
   host, so `certbot --nginx` won't find it. Simplest fix for this setup:
   run certbot in standalone mode against port 80 with the app stopped
   briefly, or (easier long-term) add a
   [`nginx-proxy` + `acme-companion`](https://github.com/nginx-proxy/acme-companion)
   sidecar, or terminate TLS at an OCI Load Balancer instead (see below) and
   leave the origin on plain HTTP inside the private network.
3. Once you have `fullchain.pem`/`privkey.pem`, uncomment the HTTPS `server`
   block in `nginx/nginx.conf`, mount the certs (there's a commented volume
   line in `docker-compose.prod.yml` for exactly this), and restart nginx.

## 6. Payment processor

Separate doc: [`PAYMENT_PROCESSOR_SETUP.md`](./PAYMENT_PROCESSOR_SETUP.md) —
covers both tiers (Bring Your Own Key $5/mo, Hosted Model $15/mo). Do this
before announcing subscriptions are available — until `STRIPE_SECRET_KEY`/
`STRIPE_PRICE_ID_BYOK`/`STRIPE_PRICE_ID_HOSTED` are all set,
`/api/billing/checkout` returns a 503 and the frontend shows "Billing isn't
configured yet."

## 7. Promo codes

No admin UI yet — mint codes from the instance:

```bash
docker compose -f docker-compose.prod.yml exec backend python scripts/create_promo_code.py create BETA2026 --max-redemptions 50
```

Full usage in the script's own `--help` / header docstring.

---

## Scaling beyond one instance

**Default posture: one A1.Flex instance, $0/month, handles a meaningful
amount of traffic on its own** — 4 OCPU/24GB is genuinely a lot for a
FastAPI + Postgres + Redis + Ollama-serving-a-7B-model stack at low-to-moderate
concurrent usage. Don't provision more until you actually see it struggling
(`docker stats` on the instance, or response times climbing in nginx's
access log). When you do, here's the path, roughly in the order you'd reach
for it:

### Step 1 — Split Ollama onto its own instance

The LLM is almost always the bottleneck before Postgres/nginx/the API
process are (a 7B model generating tokens saturates CPU hard on a
GPU-less Ampere box). If `docker stats` shows the `ollama` container
consistently pegged while everything else is idle:

1. Provision a **second** `VM.Standard.A1.Flex` (still free — this is your
   2nd of the 4 free OCPUs' worth of instances) in the same VCN.
2. Run just the `ollama` service on it (copy the relevant service block out
   of `docker-compose.prod.yml` into its own compose file, or run
   `docker run -d --name ollama -v ollama_data:/root/.ollama ollama/ollama`
   directly).
3. On the *original* instance, change `KOBOLD_URL` in `.env` to point at the
   second instance's **private** IP (same VCN, so instance-to-instance
   traffic doesn't need to go through the public internet or the firewall
   rules from step 2): `KOBOLD_URL=http://<ollama-instance-private-ip>:11434`.
   Do **not** open 11434 in the Security List for this — VCN-internal traffic
   between instances in the same subnet doesn't need an ingress rule the way
   internet-facing traffic does, and 11434 should still never be
   internet-reachable.

This alone often buys a lot of headroom before you need anything fancier.

### Step 2 — Multiple app instances behind a Load Balancer

If the **backend/nginx** side (not Ollama) becomes the bottleneck — lots of
concurrent users doing non-LLM things (browsing journals, campaigns, chat
history) — horizontal-scale that tier:

1. **OCI Load Balancer**: Console → **Networking** → **Load Balancers** →
   Create. The "Flexible" shape has a free tier band (10 Mbps) that may
   suffice; above that it's a paid service (unlike compute, LB isn't part of
   Always Free) — factor that in once you're at this scale, since it's the
   first genuinely non-$0 piece of this path.
2. Provision N more A1.Flex instances (again, up to 4 total OCPUs
   free — beyond that, paid A1.Flex is billed per OCPU/GB-hour, which is
   still cheap relative to most cloud compute).
3. Each instance runs `backend` + `nginx` (from `docker-compose.prod.yml`,
   minus the `postgres`/`redis`/`ollama` services — those become shared,
   see Step 3) pointing at the shared Postgres/Redis/Ollama instances via
   private IP.
4. Point the Load Balancer at all the instances' nginx (port 80), health
   check `/api/health`.
5. Point your domain's DNS at the Load Balancer's public IP instead of an
   instance's IP directly.

### Step 3 — Externalize stateful services

Once there's more than one app instance, Postgres and Redis can't live
inside any single app instance's Docker Compose anymore — every app
instance needs to see the *same* database and cache.

- **Simplest**: dedicate one more A1.Flex instance to just `postgres` +
  `redis` (from `docker-compose.prod.yml`), open the VCN's internal
  security rules (not the internet-facing one) for 5432/6379 from the app
  instances' private IPs, point every app instance's `DATABASE_URL`/
  `REDIS_URL` at it.
- **Managed alternative**: OCI's Base Database Service / Autonomous
  Database can host Postgres-compatible storage with backups/HA handled for
  you — meaningfully more reliable than a single hand-managed instance, but
  it's a paid service and a bigger jump in complexity (connection setup,
  potentially different Postgres version/extension availability — confirm
  `pgvector` is supported on whatever tier you pick, since journal embeddings
  depend on it) than the sections above. Worth it once uptime actually
  matters to real users; overkill before that.

### What this buys you

Every step above keeps the **default single-instance deployment as the
common case** — nothing in the codebase assumes multi-node (no
in-memory session state that would break behind a load balancer; JWT auth is
already stateless; Redis is used for caching, not session affinity). Scaling
out is an infrastructure change, not an application rewrite, which is the
point of routing everything through `DATABASE_URL`/`REDIS_URL`/`KOBOLD_URL`
env vars in the first place rather than hardcoding `localhost`.
