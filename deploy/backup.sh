#!/usr/bin/env bash
# Nightly Postgres backup. Needs DATABASE_URL. Optional: OFFSITE_REMOTE (rclone remote:path).
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL must be set}"
DIR="${BACKUP_DIR:-/var/backups/connect}"; mkdir -p "$DIR"
OUT="$DIR/connect-$(date +%F-%H%M).dump"
pg_dump --format=custom --no-owner "$DATABASE_URL" -f "$OUT"
[ -s "$OUT" ] || { echo "empty backup"; exit 1; }
if [ -n "${OFFSITE_REMOTE:-}" ]; then rclone copy "$OUT" "$OFFSITE_REMOTE"; fi
find "$DIR" -name 'connect-*.dump' -mtime +14 -delete
echo "ok $OUT $(du -h "$OUT" | cut -f1)"
