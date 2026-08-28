#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — Stop all services
#
# Usage:
#   ./scripts/stop.sh          — stop KoboldCpp, backend, frontend
#   ./scripts/stop.sh --all    — also stop PostgreSQL + Redis containers
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_ROOT/scripts/.pids"
STOP_ALL=false
[[ "${1:-}" == "--all" ]] && STOP_ALL=true

# ── Colours ──────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${G}  ✓${NC}  $*"; }
step() { echo -e "\n${B}▶${NC}  $*"; }
warn() { echo -e "${Y}  !${NC}  $*"; }

stop_service() {
  local name="$1"
  local port="${2:-}"
  local pid_file="$PID_DIR/$name.pid"
  local killed=false

  # Kill tracked PID
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null
      for i in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
      ok "$name stopped (was PID $pid)"
      killed=true
    else
      warn "$name PID $pid was not running"
    fi
    rm -f "$pid_file"
  fi

  # Also free the port in case the service was started outside the script
  if [ -n "$port" ] && command -v fuser &>/dev/null; then
    if fuser "$port/tcp" &>/dev/null 2>&1; then
      fuser -k "$port/tcp" &>/dev/null 2>&1 || true
      $killed || ok "$name — freed port $port"
    fi
  fi

  $killed || [ -z "$port" ] && return
  ! fuser "$port/tcp" &>/dev/null 2>&1 || warn "$name port $port still in use after stop"
}

# ── Stop user-managed services ────────────────────────────────────────────────
step "Vite frontend"
stop_service frontend 5173

step "FastAPI backend"
stop_service backend 8000

step "KoboldCpp"
stop_service kobold 5001

step "KoboldCpp (fine-tuned)"
stop_service kobold-finetuned 5002

# ── Optionally stop Docker services ──────────────────────────────────────────
if $STOP_ALL; then
  step "PostgreSQL + Redis  (Docker)"
  sudo docker compose -f "$PROJECT_ROOT/docker-compose.dev.yml" down
  ok "Containers stopped"
else
  echo ""
  echo -e "${Y}  Note:${NC} PostgreSQL and Redis are still running."
  echo "  To stop them too: ./scripts/stop.sh --all"
fi

echo ""
echo -e "${G}  All services stopped.${NC}"
echo ""
