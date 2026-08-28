#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — Deploy to an Oracle Cloud Always Free instance
#
# This script automates everything that CAN be automated once you're SSH'd
# into the instance. It cannot create the instance itself — that needs your
# own OCI account and the console/CLI, done manually first:
#
#   1. In the OCI Console: Compute → Instances → Create Instance.
#      - Shape: VM.Standard.A1.Flex (Ampere, Always Free) — 4 OCPUs, 24 GB RAM.
#      - Image: Ubuntu (22.04 or newer), ARM64/aarch64.
#      - Region: pick one with good Ampere capacity — Frankfurt (eu-frankfurt-1)
#        or Singapore (ap-singapore-1) tend to have more available than US
#        regions when Always Free capacity is tight.
#      - Add your SSH public key during creation (or upload one).
#   2. Networking → the instance's VCN's Default Security List: add ingress
#      rules for TCP 80 and 443 from 0.0.0.0/0. Do NOT open 11434 (Ollama) —
#      it's only reachable internally between containers on this deployment,
#      never from the internet.
#   3. Note the instance's public IP, then:
#        ssh ubuntu@<public-ip>
#   4. Copy this repo to the instance (from your dev machine):
#        rsync -avz --exclude node_modules --exclude .git \
#          /home/smith/Documents/Capstone/ ubuntu@<public-ip>:~/lorekeeper/
#   5. The fine-tuned model isn't in git (models/ is gitignored) — copy it
#      separately, it's the one large file this whole deployment actually
#      needs:
#        rsync -avz --progress \
#          /home/smith/Documents/Capstone/src/ml/models/lorekeeper-7b-q4.gguf \
#          /home/smith/Documents/Capstone/src/ml/models/lorekeeper-Modelfile \
#          ubuntu@<public-ip>:~/lorekeeper/src/ml/models/
#   6. SSH in and run this script from the repo root: ~/lorekeeper/scripts/deploy-oci.sh
#
# What this script does from there:
#   - Installs Docker + the Compose plugin if missing (apt, needs sudo).
#   - Checks .env exists (copies from .env.example + generates SECRET_KEY if not,
#     but you still need to fill in CORS_ORIGINS with your actual domain/IP).
#   - Brings up the full stack via docker-compose.prod.yml.
#   - Waits for Ollama to be healthy, then imports the fine-tuned model
#     (idempotent — skips if already imported).
#   - Prints the final status.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${G}  ✓${NC}  $*"; }
warn() { echo -e "${Y}  !${NC}  $*"; }
step() { echo -e "\n${B}▶${NC}  $*"; }
die()  { echo -e "${R}  ✗${NC}  $*" >&2; exit 1; }

# ── 1. Docker ──────────────────────────────────────────────────────────────
step "Docker"
if command -v docker &>/dev/null; then
  ok "Already installed ($(docker --version))"
else
  warn "Installing Docker (needs sudo)…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  die "Docker installed — log out and back in (group membership), then re-run this script."
fi

# ── 2. Fine-tuned model present? ──────────────────────────────────────────
step "Fine-tuned model"
GGUF="$REPO_ROOT/src/ml/models/lorekeeper-7b-q4.gguf"
MODELFILE="$REPO_ROOT/src/ml/models/lorekeeper-Modelfile"
if [ ! -f "$GGUF" ] || [ ! -f "$MODELFILE" ]; then
  die "Missing $GGUF or $MODELFILE — copy them from your dev machine first (see this script's header comment for the rsync command). Not in git; models/ is gitignored."
fi
ok "Found lorekeeper-7b-q4.gguf ($(du -h "$GGUF" | cut -f1)) and Modelfile"

# ── 3. .env ────────────────────────────────────────────────────────────────
step ".env"
if [ -f "$REPO_ROOT/.env" ]; then
  ok "Already exists"
else
  cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
  SECRET=$(openssl rand -hex 32)
  sed -i "s/SECRET_KEY=REPLACE_WITH_SECURE_RANDOM_KEY/SECRET_KEY=$SECRET/" "$REPO_ROOT/.env"
  sed -i "s|KOBOLD_URL=http://localhost:5001|KOBOLD_URL=http://ollama:11434|" "$REPO_ROOT/.env"
  echo "ENVIRONMENT=production" >> "$REPO_ROOT/.env"
  warn "Created .env with a generated SECRET_KEY and KOBOLD_URL pointed at the ollama service."
  warn "Still need to set CORS_ORIGINS and FRONTEND_URL in .env to your actual domain or IP before this is safe to expose — edit it now."
  warn "Billing (STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET/STRIPE_PRICE_ID_BYOK/STRIPE_PRICE_ID_HOSTED) is optional at first —"
  warn "the app runs fine in promo-code-only mode until you set those. See docs/PAYMENT_PROCESSOR_SETUP.md."
fi

# ── 4. Bring up the stack ───────────────────────────────────────────────────
step "Docker Compose stack"
docker compose -f docker-compose.prod.yml up -d --build
ok "Stack starting — postgres, redis, ollama, backend, nginx"

# ── 5. Wait for Ollama, then import the fine-tuned model ───────────────────
step "Ollama model import"
echo -n "  Waiting for ollama to be healthy"
for i in $(seq 1 30); do
  if docker compose -f docker-compose.prod.yml exec -T ollama ollama list &>/dev/null; then
    echo ""; break
  fi
  echo -n "."; sleep 2
done

# Anchored (^lorekeeper:) so the fine-tuned check doesn't false-positive on
# "lorekeeper-base:..." also being present in the list.
if docker compose -f docker-compose.prod.yml exec -T ollama ollama list 2>/dev/null | grep -q "^lorekeeper:"; then
  ok "Model 'lorekeeper' (fine-tuned) already imported"
else
  docker compose -f docker-compose.prod.yml exec -T ollama ollama create lorekeeper -f /import-models/lorekeeper-Modelfile
  ok "Imported fine-tuned model into Ollama"
fi

# Base model — same architecture (Mistral 7B Instruct), no LoRA applied.
# Exists so Settings → AI Provider can offer "Base Model" alongside
# "Fine-Tuned" and Model Evaluation can actually compare the two live (the
# capstone proposal's stretch goal — previously only the fine-tuned model
# was reachable anywhere in production). Note: this is v0.2, while the LoRA
# was trained against v0.3 (see src/ml/configs/lora_config.yaml) — the exact
# pre-fine-tuning v0.3 checkpoint isn't retained as a separate artifact
# (Unsloth's merge step consumes it), so v0.2 is the closest already-on-hand
# stand-in. Same architecture/size class, not a byte-for-byte ablation.
if docker compose -f docker-compose.prod.yml exec -T ollama ollama list 2>/dev/null | grep -q "^lorekeeper-base:"; then
  ok "Model 'lorekeeper-base' already imported"
else
  docker compose -f docker-compose.prod.yml exec -T ollama ollama create lorekeeper-base -f /import-models/base-Modelfile
  ok "Imported base model into Ollama"
fi

# ── 6. Status ────────────────────────────────────────────────────────────────
step "Status"
docker compose -f docker-compose.prod.yml ps
echo ""
ok "Deployed. Visit http://<this-instance's-public-ip>/ once nginx reports healthy."
warn "Set up a domain + TLS (certbot) before treating this as more than a demo — see docker-compose.prod.yml's HTTPS comments."
warn "No promo codes exist yet — account registration is gated (needs a promo code or a subscription)."
warn "Mint one: docker compose -f docker-compose.prod.yml exec backend python scripts/create_promo_code.py create YOURCODE"
warn "Full deployment walkthrough + scaling path: docs/OCI_DEPLOYMENT.md. Payment processor setup: docs/PAYMENT_PROCESSOR_SETUP.md."
