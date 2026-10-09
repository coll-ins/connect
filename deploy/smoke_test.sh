#!/usr/bin/env bash
# Post-deploy gate. Usage: deploy/smoke_test.sh https://your.domain
set -uo pipefail
B="${1:?usage: smoke_test.sh https://domain}"; H="${B#https://}"; fail=0
chk() { if [[ "$2" =~ ^($3)$ ]]; then echo "PASS $1"; else echo "FAIL $1 (got '$2', want $3)"; fail=1; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
chk "http redirects to https"        "$(code "http://$H/")" 301
chk "frontend loads"                 "$(code "$B/")" 200
chk "HSTS header present"            "$(curl -sI "$B/" | grep -ci '^strict-transport-security')" 1
chk "admin login page reachable"     "$(code "$B/admin/login/")" 200
chk "static files served"            "$(code "$B/static/admin/css/base.css")" 200
chk "my bookings needs login"        "$(code "$B/api/bookings/my/")" "401|403"
chk "unsigned paystack webhook refused" "$(code -X POST -d '{}' "$B/api/bookings/webhooks/paystack/")" "400|401|403"
chk "unsigned refund webhook refused"   "$(code -X POST -d '{}' "$B/api/bookings/webhooks/paystack/refund/")" "400|401|403"
chk "spoofed XFF does not break API" "$(code -H 'X-Forwarded-For: 1.2.3.4' "$B/api/bookings/my/")" "401|403"
[ $fail -eq 0 ] && echo "ALL PASS" || { echo "SMOKE TEST FAILED"; exit 1; }
