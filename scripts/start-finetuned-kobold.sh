#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — Start KoboldCpp serving the fine-tuned Lorekeeper LoRA model
#
# Usage: ./scripts/start-finetuned-kobold.sh
#
# Runs alongside the base-model KoboldCpp instance (port 5001) on port 5002,
# so base and fine-tuned narrative quality can be compared side by side.
# In Settings → AI Provider, select "KoboldCpp / Local" and click
# "Use Fine-Tuned Lorekeeper Model" to point Lorekeeper at this instance.
#
# Requires: src/ml/models/lorekeeper-7b-q4.gguf (produced by src/ml/scripts/train.py)
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_ROOT/scripts/.pids"
LOG_DIR="$PROJECT_ROOT/scripts/.logs"
GGUF_PATH="$PROJECT_ROOT/src/ml/models/lorekeeper-7b-q4.gguf"

mkdir -p "$PID_DIR" "$LOG_DIR"

G='\033[0;32m'; R='\033[0;31m'; B='\033[0;34m'; NC='\033[0m'
ok()  { echo -e "${G}  ✓${NC}  $*"; }
step(){ echo -e "\n${B}▶${NC}  $*"; }
die() { echo -e "${R}  ✗${NC}  $*" >&2; exit 1; }

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

[ -f "$GGUF_PATH" ] || die "Fine-tuned GGUF not found at $GGUF_PATH — run src/ml/scripts/train.py first."

step "KoboldCpp  (Fine-tuned Lorekeeper · port 5002)"
if is_running kobold-finetuned; then
  ok "Already running (PID $(cat "$PID_DIR/kobold-finetuned.pid"))"
else
  cd "$PROJECT_ROOT/koboldcpp"
  nohup python koboldcpp.py \
    --model "$GGUF_PATH" \
    --port 5002 \
    --contextsize 4096 \
    --gpulayers 32 \
    --threads 8 \
    --blasbatchsize 512 \
    > "$LOG_DIR/kobold-finetuned.log" 2>&1 &
  echo $! > "$PID_DIR/kobold-finetuned.pid"
  ok "Started (PID $!) — model loading in background, takes ~15s"
  ok "Log: $LOG_DIR/kobold-finetuned.log"
fi

echo -e "\n  Fine-tuned KoboldCpp → http://localhost:5002\n"
