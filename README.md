# Connect — Matatu Booking App

> Book your matatu. Know when it arrives.

Connect is a seat-booking platform for Nairobi's organised bus SACCOs. Passengers book a seat from anywhere, get a booking number, and receive their driver's details via SMS. Operators manage bookings and assign drivers from a dedicated dashboard. Drivers share their live GPS location so passengers can track their ride in real time.

---

## Features

**Passenger app**
- Sign up with name, phone number and location
- Browse bus companies and routes serving your area
- Book a seat and get a unique booking number instantly
- Track your driver's live location on a map
- Receive driver name, phone number and bus number via SMS
- Trip auto-completes when you arrive at your pickup point

**Operator dashboard**
- View all incoming bookings in real time
- Assign a driver to a booking with one tap
- Set stage departure time so passengers know when the bus is leaving
- Add and manage drivers for your company

**Driver app**
- Select your driver profile
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
│   ├── bookings/             ← Booking creation and management
│   ├── drivers/              ← Driver profiles and live location
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

The deployment kit targets a single Ubuntu VPS with nginx, Daphne, PostgreSQL and
Redis. Follow the step-by-step [deployment runbook](./deploy/RUNBOOK.md); do not
deploy the old `frontend/` app or use the retired Render/Vercel instructions.
Production requires a chosen VPS/domain and real Paystack and Africa's Talking
credentials. Never copy local `.env` values to the server.

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
| `ALLOWED_HOSTS` | Comma-separated list of allowed domains in production |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed frontend origins |

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/users/signup/` | Passenger signup |
| POST | `/api/users/login/` | Login |
| POST | `/api/users/admin-signup/` | Operator account creation |
| GET | `/api/companies/` | List bus companies |
| GET | `/api/companies/:id/routes/` | List routes for a company |
| POST | `/api/bookings/create/` | Create a booking |
| GET | `/api/bookings/mine/` | Get passenger's bookings |
| GET | `/api/bookings/all/` | Get all bookings (admin only) |
| POST | `/api/bookings/:id/assign-driver/` | Assign driver to booking |
| POST | `/api/bookings/:id/complete/` | Complete a trip |
| POST | `/api/bookings/:id/stage-departure/` | Set bus departure time |
| POST | `/api/bookings/:id/passenger-location/` | Update passenger GPS |
| GET | `/api/drivers/` | List available drivers |
| POST | `/api/drivers/create/` | Add a driver (admin only) |
| POST | `/api/drivers/:id/location/` | Update driver GPS location |

---

## Built by

Collins — Moringa School, Nairobi, Kenya

---

## License

MIT
