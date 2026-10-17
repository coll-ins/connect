#!/usr/bin/env bash
# Fails if any deploy-kit file is incomplete (guards against truncated pastes).
cd "$(dirname "$0")"; fail=0
need() { if grep -qF -- "$2" "$1" 2>/dev/null; then echo "ok   $1: $2"; else echo "MISSING in $1: $2"; fail=1; fi; }
need nginx-connect.conf 'listen 443 ssl http2;'
need nginx-connect.conf 'proxy_set_header X-Forwarded-For $remote_addr;'
need nginx-connect.conf 'location /ws/'
need nginx-connect.conf 'location /api/'
need nginx-connect.conf 'location /static/'
need nginx-connect.conf 'try_files $uri /index.html;'
need connect-daphne@.service 'ExecStart=/srv/connect/venv/bin/daphne'
need connect-daphne@.service '[Install]'
need connect.env.example 'REDIS_URL='
need connect.env.example 'AT_API_KEY='
need connect.cron 'process_noshows'
need connect.cron 'reconcile_refunds'
need connect.cron 'backup.sh'
grep -q '^\*/5 .*process_unapplied' connect.cron && echo "ok   connect.cron: process_unapplied scheduled" || { echo "MISSING in connect.cron: scheduled process_unapplied"; fail=1; }
need run_cmd.sh 'flock'
need smoke_test.sh 'ALL PASS'
need smoke_test.sh 'unsigned refund webhook refused'
need RUNBOOK.md 'Update procedure'
need RUNBOOK.md 'smoke_test.sh'
[ "$(tr -cd '{' < nginx-connect.conf | wc -c)" = "$(tr -cd '}' < nginx-connect.conf | wc -c)" ] || { echo "UNBALANCED BRACES in nginx-connect.conf"; fail=1; }
[ $fail -eq 0 ] && echo "KIT COMPLETE" || { echo "KIT INCOMPLETE"; exit 1; }
