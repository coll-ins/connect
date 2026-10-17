# CONNECT Frontend

Responsive React/Vite frontend for the CONNECT matatu booking platform.

## Local URLs

- Passenger: `http://localhost:5173/passenger`
- Driver: `http://localhost:5173/driver`
- Company admin: `http://localhost:5173/company-admin`
- Platform admin: `http://localhost:5173/platform-admin`
- Login: `http://localhost:5173/login`
- Signup: `http://localhost:5173/signup`

All protected pages redirect based on the role returned by the Django API.

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

## Payment flow

1. Passenger creates a booking.
2. CONNECT opens a payment-choice window.
3. Cash uses the existing cash-payment API.
4. Online payment offers M-PESA or Card.
5. M-PESA calls the backend Paystack Charge API using the passenger's saved phone number and `provider: mpesa`; Paystack sends the authorization prompt to the phone.
6. Card redirects to Paystack's secure hosted checkout.
7. Paystack's webhook is the authoritative payment confirmation; the frontend polls payment status while waiting.
