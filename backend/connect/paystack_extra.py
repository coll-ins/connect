"""Paystack helpers for parcels and bus hire (references PCL-… and CHT-…)."""
import logging
import re
import secrets
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PARCEL_REF = re.compile(r'^PCL-(\d+)-[A-Z0-9]{10}$')
CHARTER_REF = re.compile(r'^CHT-(\d+)-[A-Z0-9]{10}$')
_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
API = 'https://api.paystack.co'


class GatewayError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def new_reference(prefix, object_id):
    return f'{prefix}-{object_id}-' + ''.join(secrets.choice(_ALPHABET) for _ in range(10))


def to_kes(subunits):
    try:
        return (Decimal(int(subunits)) / Decimal(100)).quantize(Decimal('0.01'))
    except (TypeError, ValueError):
        raise GatewayError('Invalid amount from payment gateway.', 409)


def _headers():
    return {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def initialize(*, email, amount, reference, callback_url, metadata):
    try:
        response = requests.post(
            f'{API}/transaction/initialize',
            json={
                'email': email,
                'amount': int(Decimal(amount) * 100),
                'currency': 'KES',
                'reference': reference,
                'callback_url': callback_url,
                'metadata': metadata,
            },
            headers=_headers(), timeout=30,
        )
    except requests.RequestException:
        raise GatewayError('Unable to connect to payment gateway.')
    if response.status_code != 200:
        raise GatewayError('Failed to start payment.')
    try:
        body = response.json()
    except ValueError:
        raise GatewayError('Invalid response from payment gateway.')
    url = (body.get('data') or {}).get('authorization_url')
    if not body.get('status') or not url:
        raise GatewayError(body.get('message') or 'Payment could not be started.', 400)
    return url


def verify(reference):
    try:
        response = requests.get(
            f'{API}/transaction/verify/{reference}', headers=_headers(), timeout=30)
    except requests.RequestException:
        raise GatewayError('Unable to connect to payment gateway.')
    if response.status_code != 200:
        raise GatewayError('Could not verify the payment yet.')
    try:
        return response.json().get('data') or {}
    except ValueError:
        raise GatewayError('Invalid response from payment gateway.')


def apply_charge(reference, data):
    """Mark the parcel or hire behind a successful charge as paid. Raises on any problem."""
    from charters.services import mark_charter_paid
    from deliveries.services import mark_parcel_paid

    if data.get('currency') != 'KES':
        raise GatewayError('Unexpected currency.', 409)
    amount = to_kes(data.get('amount'))

    match = PARCEL_REF.match(reference or '')
    if match:
        return mark_parcel_paid(parcel_id=int(match.group(1)), amount=amount, reference=reference)
    match = CHARTER_REF.match(reference or '')
    if match:
        return mark_charter_paid(charter_id=int(match.group(1)), amount=amount, reference=reference)
    raise GatewayError('Unknown reference.', 400)


def handle_extra_charge(reference, data):
    """Webhook hook. True if the reference is ours (parcel/hire); never raises.
    A payment that cannot be applied alerts the admin numbers for a manual refund."""
    if not (PARCEL_REF.match(reference or '') or CHARTER_REF.match(reference or '')):
        return False
    try:
        apply_charge(reference, data)
    except Exception as exc:
        message = getattr(exc, 'message', None) or str(exc) or exc.__class__.__name__
        logger.exception('Paystack payment %s could not be applied', reference)
        try:
            from notifications.sms import send_admin_alert_sms
            send_admin_alert_sms(
                f'Payment {reference} received but NOT applied: {message[:90]}. Refund manually.')
        except Exception:
            logger.exception('Admin alert for %s failed', reference)
    return True
