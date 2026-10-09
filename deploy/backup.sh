#!/usr/bin/env bash
# Nightly PostgreSQL backup.
# Needs DATABASE_URL. Optional: OFFSITE_REMOTE (rclone remote:path).
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"

# Backups contain sensitive passenger and transaction information.
umask 077
DIR="${BACKUP_DIR:-/var/backups/connect}"
mkdir -p -- "$DIR"
chmod 700 -- "$DIR"

STAMP="$(date -u +%F-%H%M%S)-$$"
OUT="$DIR/connect-$STAMP.dump"
TMP="$DIR/.connect-$STAMP.dump.partial"

cleanup() {
    rm -f -- "$TMP"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Never expose a partial dump under the name used by restore_test.sh.
if ! pg_dump --format=custom --no-owner "$DATABASE_URL" --file="$TMP"; then
    echo "ERROR: pg_dump failed; incomplete backup will be discarded." >&2
    exit 1
fi

if [[ ! -s "$TMP" ]]; then
    echo "ERROR: backup is empty." >&2
    exit 1
fi

chmod 600 -- "$TMP"

if ! pg_restore --list "$TMP" >/dev/null; then
    echo "ERROR: backup archive validation failed." >&2
    exit 1
fi

if [[ -e "$OUT" ]]; then
    echo "ERROR: refusing to overwrite existing backup: $OUT" >&2
    exit 1
fi

# Same-directory rename makes the validated dump available atomically.
mv -- "$TMP" "$OUT"

if [[ -n "${OFFSITE_REMOTE:-}" ]]; then
    if ! command -v rclone >/dev/null 2>&1; then
        echo "ERROR: OFFSITE_REMOTE is set, but rclone is unavailable." >&2
        exit 1
    fi
    DEST="${OFFSITE_REMOTE%/}/$(basename -- "$OUT")"
    rclone copyto "$OUT" "$DEST"
else
    echo "WARNING: OFFSITE_REMOTE is unset; this backup is local only." >&2
fi

find "$DIR" -maxdepth 1 -type f -name 'connect-*.dump' -mtime +14 -delete
echo "OK: $OUT ($(du -h "$OUT" | cut -f1))"
