# Deploy Connect: Render (backend) + Vercel (frontend)

Migrations run when the web process starts (`backend/procfile`). A failed migration stops the app from booting, so do step 1 first.

## 1. Before the first deploy of this release (read-only checks)
Run these in the Render Postgres shell (or any SQL client). All three must return **no rows**.

```sql
SELECT id, amount, refund_amount FROM bookings_payment WHERE refund_amount < 0 OR refund_amount > amount;
SELECT id, amount, refunded_amount FROM bookings_bookinghold WHERE refunded_amount < 0 OR refunded_amount > amount;
SELECT id, seats FROM bookings_booking WHERE seats < 1;
```

If any row comes back, do not deploy: fix or remove those rows first. The migrations also refuse to run on such rows and name them.

## 2. Render web service
- Root directory: `backend`
- Build command: `pip install -r requirements.txt`
- Start command: `python manage.py migrate --noinput && python manage.py createcachetable && python manage.py ensure_superuser && gunicorn connect.wsgi --log-file -`
- Health check path: `/api/health/`
- Attach a Postgres database (set `DATABASE_URL`) and a Redis instance (set `REDIS_URL`). Production refuses to start without Redis.

### Environment variables
Required (the app prints one error naming every missing one):

| Variable | Value |
|---|---|
| `DEBUG` | `False` |
| `APP_ENVIRONMENT` | `production` |
| `SECRET_KEY` | long random string: `python3 -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `ALLOWED_HOSTS` | your Render host and your Vercel host, comma separated, no `*` |
| `CORS_ALLOWED_ORIGINS` | your Vercel URL, `https://...`, comma separated if several |
| `FRONTEND_URL` | your Vercel URL |
| `DATABASE_URL` | from the Render Postgres |
| `REDIS_URL` | from your Redis (`redis://...` or `rediss://...`) |
| `REDIS_CACHE_URL` | same Redis, database 1 (optional but recommended) |
| `NUM_PROXIES` | `2` when the browser reaches Render through the Vercel rewrite, `1` if it calls Render directly. Check one request in the logs: the client IP must be the real one |
| `BEHIND_TLS_PROXY` | `True` |
| `PAYSTACK_SECRET_KEY` | your Paystack secret key (test key until you go live) |
| `AT_USERNAME`, `AT_API_KEY` | Africa's Talking credentials |
| `ADMIN_ALERT_PHONE_NUMBERS` | e.g. `+2547XXXXXXXX` (comma separated) |
| `CRON_SECRET` | 32+ random characters (the same value goes into GitHub, step 4) |
| `ADMIN_SIGNUP_CODE` | 24+ random characters |
| `ADMIN_PHONE`, `ADMIN_PASSWORD` | creates the platform admin at start; the password must pass the validators |

Leave these OFF until they are tested live: `WALLET_TOPUP_ENABLED=False`, `WALLET_PAYOUTS_ENABLED=False` (default). `ADMIN_SITE_ENABLED=False` (default).
Do not use placeholder values: the app refuses `REPLACE` or `changeme` in the secrets above.

## 3. Vercel
`vercel.json` proxies `/api/*` to the Render URL. Check the destination host in `vercel.json` matches your Render service. Cookies then stay first-party, so keep `CROSS_SITE_COOKIE_AUTH=False`.
The live map uses polling when no WebSocket is available (Vercel does not proxy WebSockets); leave `VITE_WS_HOST` unset.
Optional: `VITE_CARTO_KEY` for map tiles.

## 4. Scheduled jobs (GitHub Actions)
In the GitHub repo settings add the variable `CONNECT_API_URL` (your Render URL) and the secret `CRON_SECRET` (same value as on Render). Without them no sweep runs: late payments, refund retries, expired holds and trip generation all depend on them.

## 5. After deploy: smoke test
1. `GET /api/health/` returns 200.
2. Sign up, log in (a wrong password locks out after repeated tries), book a seat, pay with the Paystack test key, cancel and see the refund.
3. Trigger the jobs once: GitHub Actions, scheduled-jobs, Run workflow. Every job must print 200 or 202.
4. Pilot data: stages, route lines and schedules must exist for each route before passengers use it (see `docs/` handover).

## Known limitations

- `NUM_PROXIES=2` assumes traffic comes through the Vercel rewrite. A client that calls the Render `*.onrender.com` host directly can supply its own `X-Forwarded-For` entry, so the per-IP throttles can be bypassed; only the per-phone cap remains.
- The per-phone login lockout can be abused to lock a victim out for an hour. This is a design trade-off against password guessing.
- Signup claims a password-less walk-in account without SMS proof of the phone. This is an owner decision.
- The Paystack Transfers adapter and the refund-event `id` field are unverified until they are tested live. Wallet top-up and withdrawals stay off for the pilot.

## Rollback
Redeploy the previous Render commit. The new migrations only add columns, tables and constraints; the old code keeps working with them. If a constraint migration ever fails, fix the named rows and redeploy.
