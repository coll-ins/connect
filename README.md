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
| Frontend | HTML, CSS, Vanilla JavaScript |
| Database | SQLite (development), PostgreSQL (production) |
| Maps | Leaflet.js + OpenStreetMap |
| SMS | Africa's Talking |
| Deployment | Render (backend), Vercel (frontend) |

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
├── frontend/
│   ├── user/                 ← Passenger-facing pages
│   ├── admin/                ← Operator dashboard pages
│   ├── driver/               ← Driver location sharing page
│   └── static/
│       ├── css/              ← Stylesheets
│       └── js/               ← api.js, user.js, admin.js, driver.js
│
├── .env                      ← Environment variables (never commit this)
├── .gitignore
└── README.md
```

---

## Getting started locally

### 1. Clone the repo

```bash
git clone https://github.com/yourname/connect.git
cd connect
```

### 2. Set up the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set up environment variables

Create a `.env` file inside the `backend/` folder:

```
DJANGO_SECRET_KEY=your-long-random-secret-key
AFRICASTALKING_API_KEY=your-africastalking-api-key
ADMIN_SIGNUP_CODE=your-chosen-admin-code
DEBUG=True
```

### 4. Run migrations and create a superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start the server

```bash
python manage.py runserver
```

Backend runs at `http://localhost:8000`

### 6. Open the frontend

Open `frontend/user/index.html` in your browser using Live Server (VS Code extension) or any local server on port 5500.

---

## Deployment

### Backend — Render

1. Push repo to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Set build command: `pip install -r requirements.txt`
5. Set start command: `gunicorn connect.wsgi:application`
6. Add environment variables from your `.env`

### Frontend — Vercel

1. Go to [vercel.com](https://vercel.com) → Import repo
2. Set root directory to `frontend`
3. Deploy
4. Update `BASE_URL` in `frontend/static/js/api.js` to your Render URL

---

## Environment variables

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key — generate a long random string |
| `AFRICASTALKING_API_KEY` | Africa's Talking API key for SMS |
| `ADMIN_SIGNUP_CODE` | Secret code operators use to create admin accounts |
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
