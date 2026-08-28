#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — Start all services
#
# Usage: ./scripts/start.sh
#
# Starts (in order):
#   1. PostgreSQL + Redis  (Docker via docker-compose.dev.yml — requires sudo)
#   2. Alembic migrations  (runs automatically, safe to re-run)
#   3. KoboldCpp           (Mistral 7B on port 5001)
#   4. FastAPI backend     (uvicorn --reload on port 8000)
#   5. Vite frontend       (dev server on port 5173)
#
# PIDs are written to scripts/.pids/ so stop.sh can clean up.
# Logs are written to scripts/.logs/.
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_ROOT/scripts/.pids"
LOG_DIR="$PROJECT_ROOT/scripts/.logs"
CONDA_PYTHON="/home/smith/miniforge3/envs/lorekeeper-spacy/bin/python"
CONDA_UVICORN="/home/smith/miniforge3/envs/lorekeeper-spacy/bin/uvicorn"

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── Colours ──────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${G}  ✓${NC}  $*"; }
step() { echo -e "\n${B}▶${NC}  $*"; }
warn() { echo -e "${Y}  !${NC}  $*"; }
die()  { echo -e "${R}  ✗${NC}  $*" >&2; exit 1; }

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# ── 1. PostgreSQL + Redis ─────────────────────────────────────────────────────
step "PostgreSQL + Redis"
if pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  ok "PostgreSQL already accepting connections"
else
  echo "    Starting via docker-compose.dev.yml (sudo required)..."
  sudo docker compose -f "$PROJECT_ROOT/docker-compose.dev.yml" up -d
  echo -n "    Waiting for PostgreSQL"
  for i in $(seq 1 30); do
    pg_isready -h localhost -p 5432 -q 2>/dev/null && break
    echo -n "."
    sleep 1
  done
  echo ""
  pg_isready -h localhost -p 5432 -q 2>/dev/null || die "PostgreSQL did not come up in time"
  ok "PostgreSQL ready"
fi

# ── 2. Alembic migrations ─────────────────────────────────────────────────────
step "Database migrations"
cd "$PROJECT_ROOT/src/backend"
"$CONDA_PYTHON" -m alembic upgrade head 2>&1 | sed 's/^/    /'
ok "Migrations up to date"

# ── 3. KoboldCpp ─────────────────────────────────────────────────────────────
step "KoboldCpp  (Mistral 7B · port 5001)"
if is_running kobold; then
  ok "Already running (PID $(cat "$PID_DIR/kobold.pid"))"
else
  cd "$PROJECT_ROOT/koboldcpp"
  nohup python koboldcpp.py \
    --model "$PROJECT_ROOT/src/ml/models/mistral-7b-instruct-v0.2.Q4_0.gguf" \
    --port 5001 \
    --contextsize 4096 \
    --gpulayers 32 \
    --threads 8 \
    --blasbatchsize 512 \
    > "$LOG_DIR/kobold.log" 2>&1 &
  echo $! > "$PID_DIR/kobold.pid"
  ok "Started (PID $!) — model loading in background, takes ~15s"
  ok "Log: $LOG_DIR/kobold.log"
fi

# ── 4. FastAPI backend ────────────────────────────────────────────────────────
step "FastAPI backend  (port 8000)"
if is_running backend; then
  ok "Already running (PID $(cat "$PID_DIR/backend.pid"))"
else
  cd "$PROJECT_ROOT/src/backend"
  # Free the port if something else is holding it
  fuser -k 8000/tcp &>/dev/null 2>&1 || true
  nohup "$CONDA_UVICORN" app.main:app --reload --port 8000 \
    > "$LOG_DIR/backend.log" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  sleep 2
  is_running backend || die "Backend exited immediately — check $LOG_DIR/backend.log"
  ok "Started (PID $(cat "$PID_DIR/backend.pid"))"
  ok "Log: $LOG_DIR/backend.log"
fi

# ── 5. Vite frontend ──────────────────────────────────────────────────────────
step "Vite frontend  (port 5173)"
if is_running frontend; then
  ok "Already running (PID $(cat "$PID_DIR/frontend.pid"))"
else
  fuser -k 5173/tcp &>/dev/null 2>&1 || true
  cd "$PROJECT_ROOT/src/frontend"
  nohup node ./node_modules/.bin/vite --host \
    > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  sleep 2
  is_running frontend || die "Frontend exited immediately — check $LOG_DIR/frontend.log"
  ok "Started (PID $(cat "$PID_DIR/frontend.pid"))"
  ok "Log: $LOG_DIR/frontend.log"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${G}  Lorekeeper is running${NC}"
echo -e "${G}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Frontend  →  http://localhost:5173"
echo "  Backend   →  http://localhost:8000/docs"
echo "  KoboldCpp →  http://localhost:5001"
echo ""
echo "  Logs:   $LOG_DIR/"
echo "  Status: ./scripts/status.sh"
echo "  Stop:   ./scripts/stop.sh"
echo ""
