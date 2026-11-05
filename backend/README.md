# CONNECT Backend

Django REST API for the CONNECT matatu booking platform.

## Core services

- Users and role-based sessions
- Companies, routes and trips
- Passenger bookings
- Driver assignments and location updates
- Boarding PIN verification
- Wallet and settlement ledger
- Paystack Card checkout
- Paystack M-PESA STK push
- Cash payments
- Payment/refund webhooks
- Company and platform administration
- Django admin

## Supported role URLs on the React frontend

- `/passenger`
- `/driver`
- `/company-manager`
- `/company-operator`
- `/company-auditor`
- `/platform-admin`

## Environment

Copy `.env.example` to `.env` and provide real credentials. Never commit `.env`.

For Paystack, use a real test secret key for sandbox testing. The M-PESA charge endpoint is implemented at:

`POST /api/bookings/payments/<booking_id>/mpesa/`

The card/hosted checkout endpoint is:

`POST /api/bookings/payments/<booking_id>/paystack/`

Payment status:

`GET /api/bookings/payments/<booking_id>/status/`

Post-checkout verification:

`POST /api/bookings/payments/<booking_id>/verify/`

Webhook:

`POST /api/bookings/webhooks/paystack/`

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py check
python manage.py test
python manage.py runserver
```

The API health endpoint is:

`GET /api/health/`

## Weekly service templates

Company managers can create and manage weekly service templates from the
company-manager workspace's **Service templates** page. Operators retain
trip oversight but cannot edit templates. Templates select a route,
driver, operating weekdays, daily first/last departure, and trip capacity.
Normal frequency defaults to 60 minutes and rush-hour frequency to 30 minutes;
the rush-hour start and end are optional and manager-configurable. The backend
generates trips in the existing rolling seven-day window.

Auto-renew is off by default for new templates. Manual templates require a
date range of no more than seven days and can be renewed for the next week in
the UI. Enabling auto-renew removes that date bound and lets the scheduled
generator keep the rolling window populated. Pausing a template cancels its
future unbooked trips while preserving trips with bookings. Existing templates
retain their prior auto-renew behavior after migration. The existing one-off
trip endpoint remains unchanged. The rolling generator records latest
per-template driver-unavailable and driver-conflict skip counts; managers and
route-scoped operators can review these in the operator intervention panel.
Operators should escalate schedule exceptions to a manager; drivers are not
automatically reassigned.

Drivers see their own assigned trips on the **My timetable** page, covering
today and the next six local calendar days. It reads generated trip records,
so departures appear even before anyone books a seat; cancelled trips remain
visible with their status. The existing hourly trip-generation job keeps the
rolling seven-day window populated. Opening the driver page fetches the latest
timetable and refreshes it periodically; it does not create duplicate trips.

## Weekly operations reports

The `send_weekly_operations_reports` management command runs daily at 06:00
Africa/Nairobi when the server uses UTC. It creates a previous-week report on
Monday before auto-renewal and a reminder the day before an active manual
template expires. Reports summarize trips, bookings, payments, incidents, and
schedule-generation conflicts. Managers can review retained reports from the
**Weekly reports** page in the company-manager workspace. A uniqueness
constraint makes report creation idempotent.

Email is optional. Configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, and
`DEFAULT_FROM_EMAIL` in the protected server environment. Reports remain in
the app if SMTP is not configured. Delivery failures are logged, shown in the
report inbox, and retried by later command runs; a failed delivery returns a
non-zero command result for operational monitoring.

## Platform-admin demo trip

The Platform Admin **Trips** page can run an isolated client-demo simulation.
It animates a demo bus along saved route map geometry and has explicit stop and
expiry behavior. It stores a short-lived demo session only; it does not create
or update real trips, drivers, passenger bookings, GPS records, payments, or
notifications. Only authenticated Django superusers can access its API.

The feature is enabled by default only for local `development` when `DEBUG` is
true. Staging demonstrations require `APP_ENVIRONMENT=staging` and
`DEMO_SIMULATION_ENABLED=True`. It is forcibly disabled in `production`, even
if the flag is mistakenly enabled. Routes without at least two valid map points
cannot be simulated. The demo endpoint is not a load test and does not send
simulated coordinates to passenger tracking.
