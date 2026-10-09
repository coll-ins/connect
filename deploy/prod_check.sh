#!/usr/bin/env bash
# Release gate: throwaway production-shaped env; any new `check --deploy` warning fails.
set -uo pipefail
cd "$(dirname "$0")/../backend"
export DEBUG=False SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  PAYSTACK_SECRET_KEY=sk_test_x BEHIND_TLS_PROXY=True NUM_PROXIES=1 \
  ALLOWED_HOSTS=connect.example.com CORS_ALLOWED_ORIGINS=https://connect.example.com \
  FRONTEND_URL=https://connect.example.com DATABASE_URL=postgres://u:p@127.0.0.1:5432/connect \
  ADMIN_ALERT_PHONE_NUMBERS=+254700000000 \
  ADMIN_SIGNUP_CODE="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')" \
  REDIS_URL="${REDIS_URL-redis://127.0.0.1:6379/0}" REDIS_CACHE_URL=redis://127.0.0.1:6379/1
python manage.py check --deploy --fail-level WARNING
