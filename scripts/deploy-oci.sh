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
#   - Applies the edition rule to COMPOSE_PROFILES (AD-16): the AGPL edition
#     (LOREKEEPER_EDITION=agpl, the default) gets the `tts` profile; the
#     commercial edition never does, and the script refuses if one is asked for.
#   - Builds Lorekeeper's own images (web, ml, stt, nginx) natively from this
#     source with `docker buildx bake --load` (docker-bake.hcl), tagged
#     lorekeeper-<svc>:<TAG>. TAG is LOREKEEPER_TAG (environment, else .env),
#     else `git describe`, else `latest`. A clean release tag already built
#     here is reused, not rebuilt: that is how a rollback runs the previous
#     code (docs/OCI_DEPLOYMENT.md, "Rolling back").
#   - Pulls the upstream multi-arch images (postgres, valkey, ollama) with
#     `docker compose pull --ignore-buildable`. Nothing is ever pushed and no
#     registry login happens: Lorekeeper is distributed as source.
#   - Brings up the stack from docker-compose.prod.yml and .env only. On boot
#     the web service dumps the database to the `backups` volume before any
#     migration (scripts/boot_migrate.py).
#   - Waits for Ollama to be healthy, then imports the fine-tuned model
#     (idempotent — skips if already imported).
#   - Prints the final status.
#
# Rollback: scripts/restore-db.sh --no-restart <pre-upgrade dump>, then
#   LOREKEEPER_TAG=<previous tag> scripts/deploy-oci.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${G}  ✓${NC}  $*"; }
warn() { echo -e "${Y}  !${NC}  $*"; }
step() { echo -e "\n${B}▶${NC}  $*"; }
die()  { echo -e "${R}  ✗${NC}  $*" >&2; exit 1; }

# The value of KEY in .env (last assignment wins, quotes stripped); empty if unset.
env_file_value() {
  local key="$1" file="${2:-$REPO_ROOT/.env}" line=""
  [ -f "$file" ] || return 0
  line="$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# AD-16: the commercial edition ships no AGPL-only `tts` container, so it
# never runs with the tts profile; the AGPL edition always gets it. Reads
# LOREKEEPER_EDITION and COMPOSE_PROFILES from the environment, else .env, and
# exports the resolved values. Returns 1 (and says why) on a commercial
# request for tts or an unknown edition.
apply_edition_rule() {
  local edition profiles p out="" has_tts=0
  edition="${LOREKEEPER_EDITION:-$(env_file_value LOREKEEPER_EDITION)}"
  edition="$(printf '%s' "${edition:-agpl}" | tr '[:upper:]' '[:lower:]')"
  if [ -n "${COMPOSE_PROFILES+set}" ]; then
    profiles="$COMPOSE_PROFILES"
  else
    profiles="$(env_file_value COMPOSE_PROFILES)"
  fi
  for p in ${profiles//,/ }; do
    [ "$p" = "tts" ] && has_tts=1
    out="${out:+$out,}$p"
  done
  case "$edition" in
    agpl)
      [ "$has_tts" = 1 ] || out="${out:+$out,}tts"
      ;;
    commercial)
      if [ "$has_tts" = 1 ]; then
        echo "deploy-oci: refusing COMPOSE_PROFILES=${profiles}: LOREKEEPER_EDITION=commercial never runs the tts profile (AD-16: the commercial edition uses browser speech, TTS_PROVIDER=none; Kokoro ships only in the AGPL build). Remove tts from COMPOSE_PROFILES." >&2
        return 1
      fi
      ;;
    *)
      echo "deploy-oci: LOREKEEPER_EDITION must be agpl or commercial, got '${edition}'" >&2
      return 1
      ;;
  esac
  export LOREKEEPER_EDITION="$edition"
  export COMPOSE_PROFILES="$out"
}

# The image tag: LOREKEEPER_TAG (environment, else .env), else `git describe`,
# else `latest`. Characters a docker tag can't hold become '-'.
resolve_tag() {
  local tag
  tag="${LOREKEEPER_TAG:-$(env_file_value LOREKEEPER_TAG)}"
  if [ -z "$tag" ]; then
    tag="$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null || true)"
  fi
  tag="${tag:-latest}"
  printf '%s' "$tag" | tr -c 'A-Za-z0-9_.-' '-' | cut -c1-128
}

BUILT_IMAGES=(lorekeeper-web lorekeeper-ml lorekeeper-stt lorekeeper-nginx)

all_images_present() {
  local tag="$1" img
  for img in "${BUILT_IMAGES[@]}"; do
    docker image inspect "$img:$tag" >/dev/null 2>&1 || return 1
  done
}

# Build web, ml, stt (cpu) and nginx for this host's own platform. `latest`
# and a dirty tree always rebuild; a clean release tag already built here is
# reused (a rollback, or a re-run).
build_images() {
  local tag="$1"
  if [ "$tag" != "latest" ] && [[ "$tag" != *-dirty ]] && all_images_present "$tag"; then
    ok "Images for $tag already built here; reusing them"
    return 0
  fi
  if docker buildx version >/dev/null 2>&1; then
    LOREKEEPER_TAG="$tag" docker buildx bake --load -f "$REPO_ROOT/docker-bake.hcl"
  else
    warn "docker buildx not available; building with docker compose build instead"
    LOREKEEPER_TAG="$tag" docker compose -f docker-compose.prod.yml build
  fi
  ok "Built ${BUILT_IMAGES[*]} at :$tag ($(uname -m))"
}

main() {
  cd "$REPO_ROOT"

  # ── 1. Docker ────────────────────────────────────────────────────────────
  step "Docker"
  if command -v docker &>/dev/null; then
    ok "Already installed ($(docker --version))"
  else
    warn "Installing Docker (needs sudo)…"
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    die "Docker installed — log out and back in (group membership), then re-run this script."
  fi

  # ── 2. Fine-tuned model present? ────────────────────────────────────────
  step "Fine-tuned model"
  local GGUF="$REPO_ROOT/src/ml/models/lorekeeper-7b-q4.gguf"
  local MODELFILE="$REPO_ROOT/src/ml/models/lorekeeper-Modelfile"
  if [ ! -f "$GGUF" ] || [ ! -f "$MODELFILE" ]; then
    die "Missing $GGUF or $MODELFILE — copy them from your dev machine first (see this script's header comment for the rsync command). Not in git; models/ is gitignored."
  fi
  ok "Found lorekeeper-7b-q4.gguf ($(du -h "$GGUF" | cut -f1)) and Modelfile"

  # ── 3. .env ──────────────────────────────────────────────────────────────
  step ".env"
  if [ -f "$REPO_ROOT/.env" ]; then
    ok "Already exists"
  else
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    local SECRET
    SECRET=$(openssl rand -hex 32)
    sed -i "s/SECRET_KEY=REPLACE_WITH_SECURE_RANDOM_KEY/SECRET_KEY=$SECRET/" "$REPO_ROOT/.env"
    sed -i "s|KOBOLD_URL=http://localhost:5001|KOBOLD_URL=http://ollama:11434|" "$REPO_ROOT/.env"
    echo "ENVIRONMENT=production" >> "$REPO_ROOT/.env"
    warn "Created .env with a generated SECRET_KEY and KOBOLD_URL pointed at the ollama service."
    warn "Still need to set CORS_ORIGINS and FRONTEND_URL in .env to your actual domain or IP before this is safe to expose — edit it now."
    warn "Billing (STRIPE_SECRET_KEY/STRIPE_WEBHOOK_SECRET/STRIPE_PRICE_ID_BYOK/STRIPE_PRICE_ID_HOSTED) is optional at first —"
    warn "the app runs fine in promo-code-only mode until you set those. See docs/PAYMENT_PROCESSOR_SETUP.md."
  fi

  # ── 4. Edition, tag, images ─────────────────────────────────────────────
  step "Edition and profiles"
  apply_edition_rule || die "Edition check failed (see above); nothing was built or started."
  ok "LOREKEEPER_EDITION=$LOREKEEPER_EDITION, COMPOSE_PROFILES=${COMPOSE_PROFILES:-(none)}"

  step "Images (built here from source; nothing is pushed)"
  local TAG
  TAG="$(resolve_tag)"
  export LOREKEEPER_TAG="$TAG"
  build_images "$TAG"
  # Upstream images only (postgres, valkey, ollama: multi-arch tags). The
  # buildable services are skipped, so nothing of ours is pulled or pushed.
  docker compose -f docker-compose.prod.yml pull --ignore-buildable
  ok "Pulled the upstream images for $(uname -m)"

  # ── 5. Bring up the stack ────────────────────────────────────────────────
  step "Docker Compose stack"
  # --no-build: the images above are the ones that run. --remove-orphans: a
  # stack from before E0-Platform.7 has a `backend` container (now `web`) that
  # would otherwise keep running beside it, outside the budget. web dumps the
  # database to the backups volume before any migration (boot_migrate.py).
  docker compose -f docker-compose.prod.yml up -d --no-build --remove-orphans
  ok "Stack starting at :$TAG — postgres, valkey, ollama, web, worker, ml, stt, nginx"

  # ── 6. Wait for Ollama, then import the fine-tuned model ─────────────────
  step "Ollama model import"
  echo -n "  Waiting for ollama to be healthy"
  local i
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

  # ── 7. Status ────────────────────────────────────────────────────────────
  step "Status"
  docker compose -f docker-compose.prod.yml ps
  echo ""
  ok "Deployed $TAG. Visit http://<this-instance's-public-ip>/ once nginx reports healthy."
  warn "Pre-upgrade database dumps land in the backups volume. Roll back with scripts/restore-db.sh --no-restart <dump>, then LOREKEEPER_TAG=<previous tag> scripts/deploy-oci.sh (docs/OCI_DEPLOYMENT.md)."
  warn "Set up a domain + TLS (certbot) before treating this as more than a demo — see docker-compose.prod.yml's HTTPS comments."
  warn "No promo codes exist yet — account registration is gated (needs a promo code or a subscription)."
  warn "Mint one: docker compose -f docker-compose.prod.yml exec web python scripts/create_promo_code.py create YOURCODE"
  warn "Full deployment walkthrough + scaling path: docs/OCI_DEPLOYMENT.md. Payment processor setup: docs/PAYMENT_PROCESSOR_SETUP.md."
}

# Sourcing the script (the tests) defines the functions without deploying.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
