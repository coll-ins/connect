#!/usr/bin/env bash
# Proves the latest backup restores into a scratch DB. Run monthly.
# Needs DATABASE_URL (role must have CREATEDB) and BACKUP_DIR.
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL must be set}"
DIR="${BACKUP_DIR:-/var/backups/connect}"
LATEST="$(ls -t "$DIR"/connect-*.dump | head -1)"
U="${DATABASE_URL%%\?*}"; BASE="${U%/*}"; T="connect_restore_test"
psql "$BASE/postgres" -qc "DROP DATABASE IF EXISTS $T"
psql "$BASE/postgres" -qc "CREATE DATABASE $T"
pg_restore --no-owner -d "$BASE/$T" "$LATEST"
psql "$BASE/$T" -tAc "select 'bookings', count(*) from bookings_booking"
psql "$BASE/postgres" -qc "DROP DATABASE $T"
echo "restore OK from $LATEST"
