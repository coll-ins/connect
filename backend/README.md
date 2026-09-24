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
- `/company-admin`
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
