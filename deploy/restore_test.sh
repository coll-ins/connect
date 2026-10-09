#!/usr/bin/env bash
# Proves the latest backup restores. Run monthly. Needs a Postgres user that can CREATE DATABASE.
set -euo pipefail
DIR="${BACKUP_DIR:-/var/backups/connect}"
LATEST="$(ls -t "$DIR"/connect-*.dump | head -1)"
T="connect_restore_test"
dropdb --if-exists "$T"; createdb "$T"
pg_restore --no-owner -d "$T" "$LATEST"
psql -d "$T" -tAc "select 'bookings', count(*) from bookings_booking"
dropdb "$T"; echo "restore OK from $LATEST"
