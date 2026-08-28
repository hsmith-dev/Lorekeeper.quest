#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — Service status
#
# Usage: ./scripts/status.sh
# =============================================================================
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_ROOT/scripts/.pids"
LOG_DIR="$PROJECT_ROOT/scripts/.logs"

# ── Colours ──────────────────────────────────────────────────────────────────
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; NC='\033[0m'; DIM='\033[2m'

check() {
  local label="$1" pid_name="$2" port="$3"
  local pid_file="$PID_DIR/$pid_name.pid"
  local pid=""
  local running=false

  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    kill -0 "$pid" 2>/dev/null && running=true
  fi

  # Also accept the service as running if the port is listening (e.g. started externally)
  if ! $running && command -v ss &>/dev/null; then
    ss -tlnp 2>/dev/null | grep -q ":$port " && running=true && pid="(external)"
  fi

  if $running; then
    printf "  ${G}●${NC}  %-22s ${G}running${NC}  pid=%-8s  port=%s\n" "$label" "$pid" "$port"
  else
    printf "  ${R}○${NC}  %-22s ${R}stopped${NC}\n" "$label"
  fi
}

check_http() {
  local label="$1" url="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$url" 2>/dev/null || echo "000")
  if [[ "$code" == "200" || "$code" == "401" || "$code" == "404" ]]; then
    printf "    ${G}↳${NC} ${DIM}%s${NC}  ${G}HTTP %s${NC}\n" "$url" "$code"
  else
    printf "    ${R}↳${NC} ${DIM}%s${NC}  ${R}unreachable${NC}\n" "$url"
  fi
}

echo ""
echo -e "  Lorekeeper — Service Status"
echo -e "  $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Database (check port directly) ───────────────────────────────────────────
if pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  printf "  ${G}●${NC}  %-22s ${G}running${NC}  port=5432\n" "PostgreSQL"
else
  printf "  ${R}○${NC}  %-22s ${R}stopped${NC}\n" "PostgreSQL"
fi

if (echo -e '*1\r\n$4\r\nPING\r\n' > /dev/tcp/localhost/6379) 2>/dev/null; then
  printf "  ${G}●${NC}  %-22s ${G}running${NC}  port=6379\n" "Redis"
else
  printf "  ${R}○${NC}  %-22s ${R}stopped${NC}\n" "Redis"
fi

echo ""

# ── App services ──────────────────────────────────────────────────────────────
check "KoboldCpp (Mistral 7B)" "kobold"   "5001"
check_http "  KoboldCpp" "http://localhost:5001/api/v1/model"

check "KoboldCpp (fine-tuned)" "kobold-finetuned" "5002"
check_http "  KoboldCpp (fine-tuned)" "http://localhost:5002/api/v1/model"

check "FastAPI backend"         "backend"  "8000"
check_http "  Backend docs" "http://localhost:8000/docs"

check "Vite frontend"           "frontend" "5173"
check_http "  App" "http://localhost:5173"

# ── Log tail hints ────────────────────────────────────────────────────────────
echo ""
if [ -d "$LOG_DIR" ]; then
  echo -e "  ${DIM}Logs (last 5 lines each):${NC}"
  for svc in kobold kobold-finetuned backend frontend; do
    local_log="$LOG_DIR/$svc.log"
    if [ -f "$local_log" ]; then
      echo -e "  ${DIM}── $svc ──${NC}"
      tail -n 5 "$local_log" | sed 's/^/    /'
    fi
  done
fi

echo ""
echo "  start:  ./scripts/start.sh"
echo "  stop:   ./scripts/stop.sh          (keeps DB running)"
echo "  stop:   ./scripts/stop.sh --all    (stops DB too)"
echo ""
