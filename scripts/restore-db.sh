#!/usr/bin/env bash
# =============================================================================
# Lorekeeper — restore the database (and stored files) from a backup
#
# Two kinds of backup:
#   - a nightly dump from backup-db.sh on the host, backups/lorekeeper_<stamp>.dump,
#     with its stored-files archive backups/lorekeeper_files_<stamp>.tar.gz;
#   - a pre-upgrade dump the web service wrote to the `backups` volume before
#     a migration (scripts/boot_migrate.py, E0-Platform.9),
#     pre-upgrade_<stamp>_<revision>.dump. Name it by its file name.
#
# DESTRUCTIVE: resets the database's public schema and loads the dump into it
# in one transaction, and (nightly backups only) replaces everything on the
# `files_data` volume (stored files, E0-Jobs.8) with the matching files
# archive. Stops the web and worker services first (so nothing writes
# mid-restore), asks for explicit confirmation, then restarts them after.
#
# The restore runs in a one-off web container: its pg_restore 17 reads both
# the pg16 nightly dumps and the pg17-made pre-upgrade dumps (the postgres
# container's pg16 client can't read the latter).
#
# Usage:
#   scripts/restore-db.sh [--no-restart] <dump> [files-archive]
#   scripts/restore-db.sh backups/lorekeeper_2026-08-12_030000.dump
#   scripts/restore-db.sh --no-restart pre-upgrade_20261121T101500Z_0f1c3b194a4b.dump
#
# --no-restart leaves web and worker stopped afterwards. Use it for a
# rollback: starting the newer image again would upgrade the restored
# database straight back. Deploy the previous tag next
# (docs/OCI_DEPLOYMENT.md, "Rolling back").
#
# The files archive defaults to the one with a nightly dump's timestamp. With
# no archive (a pre-upgrade dump, or a backup from before stored files
# existed), only the database is restored and the volume is left as it is.
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

RESTART=1
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--no-restart" ]]; then RESTART=0; else ARGS+=("$arg"); fi
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

# The one-off containers below use the image the deployed web runs
# (lorekeeper-web:<LOREKEEPER_TAG>): taken from the environment, else .env,
# else the existing web container, else latest.
if [[ -z "${LOREKEEPER_TAG:-}" ]]; then
  LOREKEEPER_TAG="$(grep -E '^[[:space:]]*LOREKEEPER_TAG=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
  # The same reading as deploy-oci.sh's env_file_value: surrounding quotes dropped.
  LOREKEEPER_TAG="${LOREKEEPER_TAG%\"}"; LOREKEEPER_TAG="${LOREKEEPER_TAG#\"}"
  LOREKEEPER_TAG="${LOREKEEPER_TAG%\'}"; LOREKEEPER_TAG="${LOREKEEPER_TAG#\'}"
fi
if [[ -z "${LOREKEEPER_TAG:-}" ]]; then
  WEB_CID="$(docker compose -f docker-compose.prod.yml ps -aq web 2>/dev/null | head -n 1 || true)"
  if [[ -n "$WEB_CID" ]]; then
    WEB_IMAGE="$(docker inspect --format '{{.Config.Image}}' "$WEB_CID" 2>/dev/null || true)"
    [[ "$WEB_IMAGE" == lorekeeper-web:* ]] && LOREKEEPER_TAG="${WEB_IMAGE#lorekeeper-web:}"
  fi
fi
# Sanitised exactly as deploy-oci.sh's resolve_tag does, so both name the same image.
LOREKEEPER_TAG="$(printf '%s' "${LOREKEEPER_TAG:-latest}" | tr -c 'A-Za-z0-9_.-' '-' | cut -c1-128)"
LOREKEEPER_TAG="${LOREKEEPER_TAG#[.-]}"
export LOREKEEPER_TAG="${LOREKEEPER_TAG:-latest}"

list_backups() {
  echo "Available backups:"
  echo "  nightly (host, backups/):"
  ls -1 backups/lorekeeper_*.dump backups/lorekeeper_files_*.tar.gz 2>/dev/null | sed 's/^/    /' || echo "    (none found)"
  echo "  pre-upgrade (the backups volume):"
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T web sh -c 'ls -1 /backups/pre-upgrade_*.dump 2>/dev/null | sed "s|^/backups/|    |" || echo "    (none found)"' || true
}

DUMP_ARG="${1:-}"
if [[ -z "$DUMP_ARG" ]]; then
  echo "Usage: $0 [--no-restart] <dump-file | pre-upgrade_*.dump> [files-archive]"
  echo
  list_backups
  exit 1
fi

# Resolve the dump: a host file, else a pre-upgrade dump on the volume.
DUMP_FILE=""
VOLUME_DUMP=""
if [[ -f "$DUMP_ARG" ]]; then
  DUMP_FILE="$DUMP_ARG"
else
  NAME="$(basename "$DUMP_ARG")"
  if [[ "$NAME" =~ ^pre-upgrade_[A-Za-z0-9]+_[A-Za-z0-9+-]+\.dump$ ]] \
      && docker compose -f docker-compose.prod.yml run --rm --no-deps -T web test -s "/backups/$NAME"; then
    VOLUME_DUMP="$NAME"
  else
    echo "No such backup: $DUMP_ARG"
    echo
    list_backups
    exit 1
  fi
fi

FILES_ARCHIVE="${2:-}"
if [[ -z "$FILES_ARCHIVE" ]]; then
  if [[ -n "$DUMP_FILE" ]]; then
    STAMP="$(basename "$DUMP_FILE" .dump)"
    STAMP="${STAMP#lorekeeper_}"
    CANDIDATE="$(dirname "$DUMP_FILE")/lorekeeper_files_${STAMP}.tar.gz"
    [[ -f "$CANDIDATE" ]] && FILES_ARCHIVE="$CANDIDATE"
  fi
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

POSTGRES_DB=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2-)

echo "This will DROP every table in '$POSTGRES_DB' and replace them with the contents of:"
echo "  ${DUMP_FILE:-backups volume: $VOLUME_DUMP}"
if [[ -n "$FILES_ARCHIVE" ]]; then
  echo "and REPLACE every stored file on the files_data volume with the contents of:"
  echo "  $FILES_ARCHIVE"
else
  echo "No stored-files archive goes with this dump: the files_data volume is left untouched."
fi
if [[ "$RESTART" == 1 ]]; then
  echo "The web and worker services will be stopped for the duration and restarted afterward."
else
  echo "The web and worker services will be stopped and LEFT STOPPED (--no-restart)."
fi
read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted — nothing was touched."
  exit 1
fi

# Whatever happens from here (a failed restore under set -e included), the
# web and worker services are started again on exit, unless --no-restart.
restart_services() {
  if [[ "$RESTART" == 1 ]]; then
    echo "Restarting web and worker..."
    docker compose -f docker-compose.prod.yml start web worker
  else
    echo "web and worker left stopped (--no-restart). Next: check out the previous"
    echo "release's source and run ITS scripts/deploy-oci.sh (docs/OCI_DEPLOYMENT.md, Rolling back)."
  fi
}
trap restart_services EXIT

echo "Stopping web and worker..."
docker compose -f docker-compose.prod.yml stop web worker

# A one-off web container (same image, env and volumes, no gunicorn and no
# boot migration): boot_migrate.py restore resets `public` and loads the dump
# (pg_restore -f - | psql --single-transaction, ON_ERROR_STOP) in one
# transaction, so a failed restore leaves the database as it was. The
# password reaches the clients through PGPASSWORD, never argv.
echo "Restoring the database..."
if [[ -n "$DUMP_FILE" ]]; then
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T web python scripts/boot_migrate.py restore < "$DUMP_FILE"
else
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T web python scripts/boot_migrate.py restore "/backups/$VOLUME_DUMP"
fi

if [[ -n "$FILES_ARCHIVE" ]]; then
  # A one-off web container (same image, user and volume) while the
  # service is stopped: empty the volume, then unpack the archive into it.
  # Each Campaign's live_audio/ is kept: backup-db.sh leaves kept Live audio
  # out unless the GM opted in, so the archive cannot replace it (an opted-in
  # one in the archive still overwrites it on extract).
  echo "Restoring stored files..."
  docker compose -f docker-compose.prod.yml run --rm --no-deps -T web sh -c \
    'set -e
     find /data/files -mindepth 1 -path "/data/files/*/live_audio" -prune -o ! -type d -exec rm -f {} +
     find /data/files -mindepth 1 -depth -type d -empty -delete
     tar -xzf - -C /data/files' < "$FILES_ARCHIVE"
fi

echo
echo "Done. Verify with:"
echo "  docker compose -f docker-compose.prod.yml logs web --tail 30"
