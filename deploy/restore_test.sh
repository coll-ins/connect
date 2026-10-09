#!/usr/bin/env bash
# Restore the latest valid backup into a unique scratch database.
# Needs DATABASE_URL, BACKUP_DIR (optional), and a DB role with CREATEDB.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"
DIR="${BACKUP_DIR:-/var/backups/connect}"

if [[ ! -d "$DIR" ]]; then
    echo "ERROR: backup directory does not exist: $DIR" >&2
    exit 1
fi

shopt -s nullglob
BACKUPS=("$DIR"/connect-*.dump)
shopt -u nullglob

if ((${#BACKUPS[@]} == 0)); then
    echo "ERROR: no connect-*.dump backup files found in $DIR" >&2
    exit 1
fi

LATEST=""
LATEST_MTIME=-1
for candidate in "${BACKUPS[@]}"; do
    candidate_mtime="$(stat -c '%Y' -- "$candidate")"
    if [[ -z "$LATEST" ]] || ((candidate_mtime >= LATEST_MTIME)); then
        LATEST="$candidate"
        LATEST_MTIME="$candidate_mtime"
    fi
done

if [[ ! -s "$LATEST" ]] || ! pg_restore --list "$LATEST" >/dev/null; then
    echo "ERROR: latest backup is empty or invalid: $LATEST" >&2
    exit 1
fi

# Unique name: never drop or overwrite a pre-existing database.
TEST_DB="connect_restore_test_$(date -u +%Y%m%d%H%M%S)_$$"

CONNECTION_INFO="$(python3 - "$DATABASE_URL" "$TEST_DB" <<'PY'
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

raw_url, test_db = sys.argv[1:3]
parts = urlsplit(raw_url)

if parts.scheme not in ("postgres", "postgresql") or not parts.netloc:
    raise SystemExit("ERROR: DATABASE_URL must be a PostgreSQL URI.")

if not parts.path or not parts.path.strip("/"):
    raise SystemExit("ERROR: DATABASE_URL must name a database.")

source_db = unquote(parts.path.lstrip("/"))
if "/" in source_db:
    raise SystemExit("ERROR: DATABASE_URL has an invalid database path.")

if source_db == test_db:
    raise SystemExit("ERROR: refusing to restore into the source database.")

# Preserve query parameters, including SSL connection settings.
admin_url = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, ""))
test_url = urlunsplit(
    (parts.scheme, parts.netloc, "/" + quote(test_db, safe=""), parts.query, "")
)

print(admin_url)
print(test_url)
print(source_db)
PY
)" || exit 1

mapfile -t CONNECTION_PARTS <<< "$CONNECTION_INFO"
if ((${#CONNECTION_PARTS[@]} != 3)); then
    echo "ERROR: could not safely prepare PostgreSQL connections." >&2
    exit 1
fi

ADMIN_URL="${CONNECTION_PARTS[0]}"
TEST_URL="${CONNECTION_PARTS[1]}"

# Confirm that the administrative URI connects to the intended maintenance DB.
ADMIN_DB="$(psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -qAtc 'SELECT current_database()')" || exit 1
if [[ "$ADMIN_DB" != "postgres" ]]; then
    echo "ERROR: administrative connection did not select the postgres database." >&2
    exit 1
fi

CREATED=0
cleanup() {
    local rc=$?
    trap - EXIT HUP INT TERM

    if ((CREATED)); then
        if psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q \
            -c "DROP DATABASE \"$TEST_DB\""; then
            echo "Removed temporary restore database: $TEST_DB"
        else
            echo "ERROR: could not remove scratch database $TEST_DB; investigate it manually." >&2
            if ((rc == 0)); then rc=1; fi
        fi
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# No DROP DATABASE IF EXISTS: a collision must fail safely.
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -q \
    -c "CREATE DATABASE \"$TEST_DB\""
CREATED=1

pg_restore --exit-on-error --no-owner --dbname="$TEST_URL" "$LATEST"

TABLE_COUNT="$(
    psql "$TEST_URL" -v ON_ERROR_STOP=1 -qAtc \
      "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
)"
if [[ ! "$TABLE_COUNT" =~ ^[0-9]+$ ]] || ((TABLE_COUNT < 1)); then
    echo "ERROR: restored database contains no public tables." >&2
    exit 1
fi

BOOKINGS_COUNT="$(
    psql "$TEST_URL" -v ON_ERROR_STOP=1 -qAtc \
      "SELECT count(*) FROM bookings_booking"
)"

echo "RESTORE PASS: archive=$LATEST public_tables=$TABLE_COUNT bookings=$BOOKINGS_COUNT"
