#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — restore the database and stored files from a backup produced
# by backup-db.sh
#
# DESTRUCTIVE: drops and replaces every table in the target database with
# whatever's in the dump file, and replaces everything on the `files_data`
# volume (stored files, E0-Jobs.8) with the matching files archive. Stops the
# backend and the worker first (so nothing writes mid-restore), asks for
# explicit confirmation, then restarts them after.
#
# Usage:
#   scripts/restore-db.sh backups/lorekeeper_2026-08-12_030000.dump [backups/lorekeeper_files_2026-08-12_030000.tar.gz]
#
# The files archive defaults to the one with the dump's timestamp. With no
# archive (a backup from before stored files existed), only the database is
# restored and the volume is left as it is.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP_FILE="${1:-}"
if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Usage: $0 <path-to-dump-file> [path-to-files-archive]"
  echo
  echo "Available backups:"
  ls -1 backups/lorekeeper_*.dump backups/lorekeeper_files_*.tar.gz 2>/dev/null || echo "  (none found)"
  exit 1
fi

FILES_ARCHIVE="${2:-}"
if [[ -z "$FILES_ARCHIVE" ]]; then
  STAMP="$(basename "$DUMP_FILE" .dump)"
  STAMP="${STAMP#lorekeeper_}"
  CANDIDATE="$(dirname "$DUMP_FILE")/lorekeeper_files_${STAMP}.tar.gz"
  [[ -f "$CANDIDATE" ]] && FILES_ARCHIVE="$CANDIDATE"
elif [[ ! -f "$FILES_ARCHIVE" ]]; then
  echo "No such files archive: $FILES_ARCHIVE"
  exit 1
fi

# Check the archive before anything is touched: a corrupt one must never
# cost the files already on the volume.
if [[ -n "$FILES_ARCHIVE" ]]; then
  if ! gzip -t "$FILES_ARCHIVE" || ! tar -tzf "$FILES_ARCHIVE" > /dev/null; then
    echo "The files archive $FILES_ARCHIVE is corrupt — nothing was touched."
    exit 1
  fi
fi

POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)

echo "This will DROP and REPLACE every table in '$POSTGRES_DB' with the contents of:"
echo "  $DUMP_FILE"
if [[ -n "$FILES_ARCHIVE" ]]; then
  echo "and REPLACE every stored file on the files_data volume with the contents of:"
  echo "  $FILES_ARCHIVE"
else
  echo "No stored-files archive matches this dump: the files_data volume is left untouched."
fi
echo "The backend and the worker will be stopped for the duration and restarted afterward."
read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted — nothing was touched."
  exit 1
fi

# Whatever happens from here (a failed restore under set -e included), the
# backend and the worker are started again on exit.
restart_services() {
  echo "Restarting backend and worker..."
  docker compose -f docker-compose.prod.yml start backend worker
}
trap restart_services EXIT

echo "Stopping backend and worker..."
docker compose -f docker-compose.prod.yml stop backend worker

echo "Restoring the database..."
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner < "$DUMP_FILE"

if [[ -n "$FILES_ARCHIVE" ]]; then
  # A one-off backend container (same image, user and volume) while the
  # service is stopped: empty the volume, then unpack the archive into it.
  # Each Campaign's live_audio/ is kept: backup-db.sh leaves kept Live audio
  # out unless the GM opted in, so the archive cannot replace it (an opted-in
  # one in the archive still overwrites it on extract).
  echo "Restoring stored files..."
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T backend sh -c \
    'set -e
     find /data/files -mindepth 1 -path "/data/files/*/live_audio" -prune -o ! -type d -exec rm -f {} +
     find /data/files -mindepth 1 -depth -type d -empty -delete
     tar -xzf - -C /data/files' < "$FILES_ARCHIVE"
fi

echo
echo "Done. Verify with:"
echo "  docker compose -f docker-compose.prod.yml logs backend --tail 30"
