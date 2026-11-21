# Connect — Matatu Booking App

> Book your matatu. Know when it arrives.

Connect is a seat-booking platform for Nairobi's organised bus SACCOs. Passengers book a seat from anywhere, get a booking number, and receive their driver's details via SMS. Operators manage bookings and assign drivers from a dedicated dashboard. Drivers share their live GPS location so passengers can track their ride in real time.

---

## Features

**Passenger app**
- Sign up with name, phone number and location
- Browse bus companies and routes serving your area
- Book a seat and get a unique booking number instantly
- Pick each seat on a drawing of the real bus, or let the app choose free seats at random
- See the bus fleet number, number plate, vehicle and driver's name before booking
- Track your driver's live location on a map
- Receive driver name, phone number and bus number via SMS
- Trip auto-completes when you arrive at your pickup point

**Operator dashboard**
- View all incoming bookings in real time
- Assign a driver to a booking with one tap
- Set stage departure time so passengers know when the bus is leaving
- Add and manage drivers for your company
- Add buses by type; every trip runs on one bus and sells exactly its seats (more demand: add a second bus at the same time)

**Seat plans** (`backend/bookings/seats.py`): 14-seater matatu from Toyota's HiAce Commuter plan; Isuzu NMR85 (27), FTR90 (51) and FVR34S (67) from ACMG's numbered drawings. The Isuzu NQR81M 33-seater's count and front row are from Isuzu East Africa's brochure, but no drawing is published, so its seat positions are marked approximate. Any other bus is entered with its seat count and gets a plain 2+2 plan, marked unverified.

**Driver app**
- Select your driver profile
- View an automatically refreshed timetable of assigned trips
- Share your live GPS location with assigned passengers
- See all your assigned passengers on a map with distance to nearest pickup

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, Django, Django REST Framework |
| Frontend | React, Vite |
| Database | SQLite (development), PostgreSQL (production) |
| Maps | Leaflet, MapLibre, OpenStreetMap |
| SMS | Africa's Talking |
| Payments | Paystack |

---

## Project structure

```
connect/
├── backend/                  ← Django project
│   ├── connect/              ← Project settings and URLs
│   ├── users/                ← Signup, login, admin accounts
│   ├── companies/            ← Bus companies and routes
│   ├── bookings/             ← Booking creation, payments, refunds and settlement
│   ├── buses/                ← Buses
│   ├── charters/             ← Bus hire
│   ├── deliveries/           ← Parcels
│   ├── drivers/              ← Driver profiles and live location
│   ├── wallets/              ← Passenger wallet: top-up, spend, withdrawals
│   ├── notifications/        ← SMS via Africa's Talking
│   └── manage.py
│
├── frontend-react/           ← React passenger, driver and staff apps
├── deploy/                   ← Server, nginx and operations files
├── .github/workflows/        ← CI checks on pushes and pull requests
├── .gitignore
└── README.md
```

---

## Getting started locally

```bash
git clone https://github.com/coll-ins/connect.git
cd connect
make setup
```

`make setup` installs the backend and frontend dependencies, installs Chrome for
Playwright, and creates `backend/.env` from the safe local template if it does not
exist. The template uses SQLite and test-mode integrations; do not put production
credentials in it.

Apply database migrations once for a fresh local database:

```bash
make migrate
```

Open two terminals in the repository. Start the backend in the first:

```bash
make backend
```

Start the frontend in the second:

```bash
make frontend
```

Open the URL printed by Vite (normally `http://localhost:5173`).

Run the automated checks with `make test`. `make lint` and `make build` are
available for quick local checks. GitHub Actions runs the backend checks,
frontend lint/build, and Playwright browser tests on every push and pull request.

---

## Deployment

The live setup is Render (Django backend, PostgreSQL, Redis) with Vercel for the
React frontend. Follow [deploy/RENDER-VERCEL.md](./deploy/RENDER-VERCEL.md): it lists
the start command, every environment variable, the production database checks to run
first, and the known limitations. The single-VPS kit (nginx, Daphne, PostgreSQL,
Redis) in [deploy/RUNBOOK.md](./deploy/RUNBOOK.md) is an alternative that is not
the live target. Production requires real Paystack and Africa's Talking credentials.
Never copy local `.env` values to the server.

## Automation and operations

- GitHub Actions runs backend checks, production configuration checks, frontend
  lint/build, and browser tests on pushes and pull requests.
- On Render, GitHub Actions (`scheduled-jobs`) calls the protected cron endpoint every
  10 minutes for booking expiry, late payments, no-shows, refund retries, wallet
  sweeps and trip generation. Set the `CONNECT_API_URL` repository variable and the
  `CRON_SECRET` repository secret (the same value as on Render), or nothing runs.
- On the single-VPS kit the server's own cron schedules the same jobs and backups;
  see the deployment runbook.
- The `generate-trips` workflow is a manual recovery action only.
- After deployment, run the smoke test and periodically test database restores;
  automation cannot replace monitoring payment settlement, SMS delivery, and
  passenger/driver support.
- Routes, their road lines and stages ship in
  `backend/companies/data/route_network.json` and are installed by a migration.
  Every route has a way back, and the last stage is drop-off only. To change the
  network, edit the route list in `tools/build_route_network.py`, run it (it
  reads OpenStreetMap roads and stops), then add a migration that loads the file.

---

## Environment variables

Create local settings in `backend/.env` using `backend/.env.example` as a starting
point. Keep real credentials out of source control. Production deployment requires
additional provider and infrastructure settings; see [deploy/RUNBOOK.md](./deploy/RUNBOOK.md).

| Variable | Description |
|---|---|
| `SECRET_KEY` | Django secret key — use a long, random value in production |
| `PAYSTACK_SECRET_KEY` | Paystack test key locally; live key only in production environment |
| `AT_USERNAME`, `AT_API_KEY` | Africa's Talking username and API key |
| `ADMIN_SIGNUP_CODE` | Private code for admin signup; disable self-service admin signup in production |
| `DEBUG` | Set to `False` in production |
| `ALLOWED_HOSTS` | Comma-separated list of allowed domains in production (no `*`) |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed frontend origins |
| `FRONTEND_URL` | The frontend's public URL |
| `DATABASE_URL`, `REDIS_URL` | PostgreSQL and Redis in production (Redis is required) |
| `NUM_PROXIES` | Number of proxies in front of the app (1 or more in production) |
| `CRON_SECRET` | 32+ random characters; required in production for scheduled jobs |
| `ADMIN_SITE_ENABLED` | Django admin site; off in production unless `true` |
| `WALLET_TOPUP_ENABLED`, `WALLET_PAYOUTS_ENABLED` | Wallet top-up and withdrawals; both stay `false` until tested live |

The full production list is in [deploy/RENDER-VERCEL.md](./deploy/RENDER-VERCEL.md).

Frontend (`frontend-react/.env.example`, set the same names in Vercel):

| Variable | Description |
|---|---|
| `VITE_LEGAL_ENTITY` | Registered business name shown in the Terms and Privacy Policy |
| `VITE_LEGAL_ADDRESS` | Business address shown in the legal pages (default `Nairobi, Kenya`) |
| `VITE_SUPPORT_EMAIL`, `VITE_SUPPORT_PHONE` | Support contact shown in Help and the legal pages |

## Legal pages

Terms, Privacy, Refund, Parcel and Bus Hire terms live in
`frontend-react/src/legal/documents.js` and are served at `/legal/<slug>`. Signup
requires accepting them; the accepted version and time are stored on the user
(`terms_version`, `terms_accepted_at`). When the text changes materially, bump
`TERMS_VERSION` in `backend/connect/settings.py` and `LAST_UPDATED` in
`frontend-react/src/legal/business.js`. The refund rules in the documents mirror
the code; change both together.

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/users/signup/` | Passenger signup |
| POST | `/api/users/login/` | Login |
| POST | `/api/users/admin-signup/` | Platform admin account creation (when enabled) |
| GET | `/api/companies/` | List bus companies |
| GET | `/api/companies/:id/routes/` | List routes for a company |
| POST | `/api/bookings/create/` | Create a booking |
| GET | `/api/bookings/my/` | Get passenger's bookings |
| GET | `/api/bookings/all/` | List bookings visible to authorized staff |
| POST | `/api/bookings/:id/assign-driver/` | Assign driver to booking |
| POST | `/api/bookings/driver/:driver_id/end-trip/` | Complete a driver's trip |
| POST | `/api/bookings/:id/stage-departure/` | Set bus departure time |
| POST | `/api/bookings/:id/location/` | Update passenger GPS |
| POST | `/api/companies/trips/create/` | Create a trip |
| GET | `/api/drivers/` | List available drivers |
| POST | `/api/drivers/:id/location/` | Update driver GPS location |
| GET/PATCH | `/api/companies/booking-settings/` | Per-company booking cut-off (manager) |
| GET | `/api/companies/trips/:id/seat-summary/` | Booked and open seats for a trip (staff) |
| POST | `/api/bookings/walk-in/:trip_id/` | Book and board a walk-up passenger |
| POST | `/api/bookings/payments/:booking_id/wallet/` | Pay a booking from the wallet |
| GET | `/api/wallet/` | Wallet balance |
| POST | `/api/wallet/topup/` | Start a wallet top-up (off until enabled) |
| POST | `/api/wallet/withdraw/` | Withdraw to M-PESA (off until enabled) |

---

## Built by

Collins — Moringa School, Nairobi, Kenya

---

## License

MIT
