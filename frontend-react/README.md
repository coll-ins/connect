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

The repository-root `vercel.json` builds and serves this Vite frontend when the
Vercel project root is the repository. If the Vercel project root is set to
`frontend-react`, its `vercel.json` provides the SPA fallback so direct routes
such as `/login` resolve to the app. Both configs explicitly proxy `/api/*` to
the Render backend before checking static files and then applying the SPA
fallback. Django must remain deployed separately; Vercel hosts the static
frontend, not the Channels/Django backend.

Set `VITE_WS_HOST` to the backend hostname (`connect-lhqy.onrender.com`) in
Vercel to enable live-location WebSockets. The API proxy does not proxy
WebSockets.

On the backend, include the API hostname in `ALLOWED_HOSTS`, and set
`CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` to the exact Vercel frontend origin
(for example, `https://connect-zj9i-gamma.vercel.app`).
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
