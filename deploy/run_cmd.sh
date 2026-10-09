#!/usr/bin/env bash
# Usage: run_cmd.sh <management_command> [args]. Loads env, never overlaps itself, logs.
set -euo pipefail
set -a; . /etc/connect/connect.env; set +a
cd /srv/connect/backend
exec flock -n "/tmp/connect-$1.lock" /srv/connect/venv/bin/python manage.py "$@" >> /var/log/connect/cron.log 2>&1
