#!/usr/bin/env bash
# Release gate: throwaway production-shaped env; any new `check --deploy` warning fails.
set -uo pipefail
cd "$(dirname "$0")/../backend"
if [[ -x .venv/bin/python ]]; then
  PYTHON=.venv/bin/python
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  echo "MISSING PYTHON"
  exit 1
fi

export DEBUG=False SECRET_KEY="$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  PAYSTACK_SECRET_KEY=sk_test_x BEHIND_TLS_PROXY=True NUM_PROXIES=1 \
  ALLOWED_HOSTS=connect.example.com CORS_ALLOWED_ORIGINS=https://connect.example.com \
  FRONTEND_URL=https://connect.example.com DATABASE_URL=postgres://u:p@127.0.0.1:5432/connect \
  ADMIN_ALERT_PHONE_NUMBERS=+254700000000 \
  ADMIN_SIGNUP_CODE="$("$PYTHON" -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  REDIS_URL="${REDIS_URL-redis://127.0.0.1:6379/0}" REDIS_CACHE_URL=redis://127.0.0.1:6379/1 \
  AT_API_KEY="${AT_API_KEY-test_key_x}" AT_USERNAME="${AT_USERNAME-connect}"
"$PYTHON" -c "import channels_redis, redis, daphne, whitenoise, psycopg2" || { echo "MISSING PROD DEPENDENCY"; exit 1; }
"$PYTHON" manage.py check --deploy --fail-level WARNING
