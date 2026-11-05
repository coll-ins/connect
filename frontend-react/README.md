# CONNECT Frontend

Responsive React/Vite frontend for the CONNECT matatu booking platform.

## Local URLs

- Passenger: `http://localhost:5173/passenger`
- Driver: `http://localhost:5173/driver`
- Company manager: `http://localhost:5173/company-manager`
- Company operator: `http://localhost:5173/company-operator`
- Company auditor: `http://localhost:5173/company-auditor`
- Platform admin: `http://localhost:5173/platform-admin`
- Login: `http://localhost:5173/login`
- Signup: `http://localhost:5173/signup`

All protected pages redirect based on the role returned by the Django API.
Drivers see their assigned trips on the **My timetable** page for today and
the next six Nairobi calendar days; the overview also highlights today's
departures.

## Start

```bash
npm install
npm run dev
```

The Vite server listens on `0.0.0.0:5173`, so the same app can be opened from a phone on the same Wi-Fi network using the laptop's LAN IP.

## Build / lint

```bash
npm run lint
npm run build
```

## Vercel frontend

The repository-root `vercel.json` builds and serves this Vite frontend. Django
must remain deployed separately; Vercel hosts the static frontend, not the
Channels/Django backend.

Set these Vercel project environment variables for the production deployment:

- `VITE_API_URL`: HTTPS origin of the Django backend, for example
  `https://api.example.com` (no trailing slash or `/api`).
- `VITE_WS_HOST`: backend hostname for live-location WebSockets, for example
  `api.example.com` (no scheme or path).

On the backend, include the API hostname in `ALLOWED_HOSTS`, and set
`CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` to the exact Vercel frontend origin.
If frontend and backend are on different site domains, also set
`CROSS_SITE_COOKIE_AUTH=True`; this requires HTTPS and enables cross-site
session/CSRF cookies. For reliable session authentication, use a custom
frontend domain on the same site as the API (for example, `app.example.com`
and `api.example.com`); browsers may block third-party cookies when using the
default `*.vercel.app` domain. For the demo simulator, deploy a separate
staging backend with `DEBUG=False`, `APP_ENVIRONMENT=staging`, and
`DEMO_SIMULATION_ENABLED=True`. Production intentionally keeps the simulator
disabled.

## Payment flow

1. Passenger creates a booking.
2. CONNECT opens a payment-choice window.
3. Cash uses the existing cash-payment API.
4. Online payment offers M-PESA or Card.
5. M-PESA calls the backend Paystack Charge API using the passenger's saved phone number and `provider: mpesa`; Paystack sends the authorization prompt to the phone.
6. Card redirects to Paystack's secure hosted checkout.
7. Paystack's webhook is the authoritative payment confirmation; the frontend polls payment status while waiting.
