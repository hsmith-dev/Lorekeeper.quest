#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — restore the database from a backup produced by backup-db.sh
#
# DESTRUCTIVE: drops and replaces every table in the target database with
# whatever's in the dump file. Stops the backend first (so nothing writes
# mid-restore), asks for explicit confirmation, then restarts it after.
#
# Usage:
#   scripts/restore-db.sh backups/lorekeeper_2026-08-12_030000.dump
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP_FILE="${1:-}"
if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Usage: $0 <path-to-dump-file>"
  echo
  echo "Available backups:"
  ls -1 backups/lorekeeper_*.dump 2>/dev/null || echo "  (none found)"
  exit 1
fi

POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)

echo "This will DROP and REPLACE every table in '$POSTGRES_DB' with the contents of:"
echo "  $DUMP_FILE"
echo "The backend will be stopped for the duration and restarted afterward."
read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted — nothing was touched."
  exit 1
fi

echo "Stopping backend..."
docker compose -f docker-compose.prod.yml stop backend

echo "Restoring..."
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < "$DUMP_FILE"

echo "Restarting backend..."
docker compose -f docker-compose.prod.yml start backend

echo
echo "Done. Verify with:"
echo "  docker compose -f docker-compose.prod.yml logs backend --tail 30"
