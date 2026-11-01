#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — nightly database backup (local tier)
#
# Dumps the production Postgres database to a timestamped, compressed file
# under ~/lorekeeper/backups/, then archives the stored files (the
# `files_data` volume, E0-Jobs.8) next to it under the same timestamp, then
# prunes anything past the retention window. This is Tier 1 of the backup strategy — see
# docs/DATABASE_BACKUPS.md for the full plan, including Tier 2 (an offsite
# copy), which this script deliberately does NOT do: it needs cloud storage
# credentials that have to be set up once by hand, not guessed at here.
#
# Local-only backups still protect against the most common real failure
# modes — a bad migration, an application bug that corrupts data, someone
# (a user or an admin) deleting something they didn't mean to. They do NOT
# protect against losing the instance itself (disk failure, accidental
# termination) — that's exactly what Tier 2 is for.
#
# Install (on the instance, one-time):
#   crontab -e
#   # add this line (03:00 server time, daily):
#   0 3 * * * /home/ubuntu/lorekeeper/scripts/backup-db.sh >> /home/ubuntu/lorekeeper/backups/backup.log 2>&1
#
# Restore with scripts/restore-db.sh.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="$(pwd)/backups"
RETENTION_DAYS=14
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
OUT_FILE="$BACKUP_DIR/lorekeeper_${TIMESTAMP}.dump"
FILES_OUT="$BACKUP_DIR/lorekeeper_files_${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

POSTGRES_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)

echo "[$(date)] Starting backup: $OUT_FILE"

# -Fc: pg_dump's custom format — compressed, and restorable selectively
# (pg_restore -t <table> ...) or wholesale, unlike a plain SQL dump. Piped
# through `docker compose exec -T` (no TTY) so stdout is exactly the dump
# bytes, nothing else.
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUT_FILE"

if [[ ! -s "$OUT_FILE" ]]; then
  echo "[$(date)] ERROR: backup file is empty — pg_dump likely failed. Not pruning old backups." >&2
  rm -f "$OUT_FILE"
  exit 1
fi

SIZE=$(du -h "$OUT_FILE" | cut -f1)
echo "[$(date)] Database backup complete: $OUT_FILE ($SIZE)"

# Stored files (files_data, mounted at /data/files in the backend), AFTER
# the dump: every row in the dump existed before the archive started, so
# the only file a restore can lack is one deleted in between (it answers 404
# for everyone, like any missing file); stray bytes are swept by files.gc.
# Kept raw Live audio (`<campaign>/live_audio/`) is excluded unless the GM
# opted in, which leaves a `.backup-live-audio` marker in that Campaign's
# directory. In-flight temporary names (`.tmp-*`) are skipped. Run inside the
# container so tar sees the volume as the app does.
echo "[$(date)] Archiving stored files: $FILES_OUT"
if ! docker compose -f docker-compose.prod.yml exec -T backend sh -c '
  set -e
  cd /data/files
  set --
  for d in */live_audio; do
    [ -d "$d" ] || continue
    [ -e "${d%/live_audio}/.backup-live-audio" ] || set -- "$@" "--exclude=./$d"
  done
  # GNU tar exits 1 when a file changed or vanished while it was read (a put
  # or a delete during the backup): the archive is still good.
  tar -czf - --warning=no-file-changed --warning=no-file-removed --exclude="./*/*/.tmp-*" "$@" . || [ "$?" -eq 1 ]
' > "$FILES_OUT"; then
  echo "[$(date)] ERROR: the stored-files archive failed. Not pruning old backups." >&2
  rm -f "$FILES_OUT"
  exit 1
fi
FILES_SIZE=$(du -h "$FILES_OUT" | cut -f1)
echo "[$(date)] Stored-files backup complete: $FILES_OUT ($FILES_SIZE)"

# Prune anything older than RETENTION_DAYS — only runs if the new backup
# above actually succeeded (see the empty-file check), so a broken backup
# job can't silently delete good history along with itself.
find "$BACKUP_DIR" -name "lorekeeper_*.dump" -mtime "+$RETENTION_DAYS" -print -delete
find "$BACKUP_DIR" -name "lorekeeper_files_*.tar.gz" -mtime "+$RETENTION_DAYS" -print -delete

echo "[$(date)] Retained backups:"
ls -lh "$BACKUP_DIR"/lorekeeper_*.dump "$BACKUP_DIR"/lorekeeper_files_*.tar.gz 2>/dev/null || echo "  (none)"
