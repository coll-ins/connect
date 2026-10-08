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


class RefundUncertain(Exception):
    """The refund request may or may not have reached Paystack."""


def _alert(message):
    try:
        from notifications.sms import send_admin_alert_sms
        send_admin_alert_sms(message)
    except Exception:
        logger.exception('Admin alert failed: %s', message)


def classify_failure(exc, data):
    """Return (action, reason, amount). action is 'refund', 'review' or 'retry'."""
    from django.core.exceptions import ObjectDoesNotExist

    reason = getattr(exc, 'message', None) or str(exc) or exc.__class__.__name__
    try:
        amount = to_kes(data.get('amount'))
    except GatewayError:
        amount = None

    if isinstance(exc, ObjectDoesNotExist):
        return 'review', 'no matching parcel or hire exists', amount
    if data.get('currency') != 'KES' or amount is None or amount <= 0:
        return 'review', reason, amount
    code = getattr(exc, 'status_code', None)
    if type(exc).__name__ in ('ParcelError', 'CharterError') and code in (None, 409):
        return 'refund', reason, amount
    return 'retry', reason, amount


_STATUS_FOR_ACTION = {'refund': 'refund_due', 'review': 'review', 'retry': 'retry'}
_TAIL = {
    'refund': 'Automatic refund queued; no action needed.',
    'review': 'Needs a human: check Paystack and refund manually if appropriate.',
    'retry': 'Will retry automatically.',
}


def record_failure(reference, data, exc):
    """Durably record a charge that could not be applied, and alert once."""
    try:
        from bookings.models import UnappliedPayment

        action, reason, amount = classify_failure(exc, data)
        kind = 'parcel' if PARCEL_REF.match(reference or '') else 'charter'
        row, created = UnappliedPayment.objects.get_or_create(
            reference=reference,
            defaults={
                'kind': kind,
                'amount': amount,
                'currency': str(data.get('currency') or '')[:10],
                'reason': reason[:255],
                'payload': data,
                'status': _STATUS_FOR_ACTION[action],
            },
        )
        if created:
            _alert(f'Payment {reference} received but NOT applied: {reason[:90]}. {_TAIL[action]}')
    except Exception:
        logger.exception('Could not record unapplied payment %s', reference)
        _alert(f'Payment {reference} received but NOT applied and NOT recorded. Refund manually.')


def _finish(row, **fields):
    from django.utils import timezone
    from bookings.models import UnappliedPayment

    UnappliedPayment.objects.filter(pk=row.pk).update(updated_at=timezone.now(), **fields)


def claim_refund(row):
    """Atomically take a refund_due row. True only for the caller that got it."""
    from django.utils import timezone
    from bookings.models import UnappliedPayment

    return UnappliedPayment.objects.filter(pk=row.pk, status='refund_due').update(
        status='refunding', updated_at=timezone.now()
    ) == 1


def refund_charge(reference, amount):
    """
    Full refund of a charge. Returns (status, refund_id).
    GatewayError = Paystack definitely refused. RefundUncertain = outcome unknown.
    """
    try:
        response = requests.post(
            f'{API}/refund',
            json={
                'transaction': reference,
                'amount': int(Decimal(amount) * 100),
                'currency': 'KES',
                'customer_note': f'Refund for CONNECT payment {reference}',
                'merchant_note': f'CONNECT unapplied payment {reference}',
            },
            headers=_headers(), timeout=30,
        )
    except requests.RequestException as exc:
        raise RefundUncertain('Could not confirm the refund request.') from exc

    if response.status_code != 200:
        try:
            detail = response.json().get('message')
        except ValueError:
            detail = None
        message = 'Refund not confirmed' + (f': {detail}' if detail else '.')
        if 400 <= response.status_code < 500 and response.status_code != 408:
            raise GatewayError(message, 409)
        raise RefundUncertain(message)

    try:
        body = response.json()
    except ValueError as exc:
        raise RefundUncertain('Unreadable refund response.') from exc
    if not body.get('status'):
        raise GatewayError(body.get('message') or 'Refund refused.', 409)

    data = body.get('data') or {}
    return data.get('status', 'pending'), data.get('id')


def send_refund(row):
    """Send a claimed refund. The row must already be 'refunding'; no transaction may be open."""
    try:
        refund_status, refund_id = refund_charge(row.reference, row.amount)
    except GatewayError as exc:
        _finish(row, status='review', reason=f'refund refused: {exc.message}'[:255])
        _alert(
            f'Charge {row.reference} (KES {row.amount}) not applied and the automatic '
            f'refund was refused ({exc.message[:60]}). Refund manually.'
        )
        return False
    except RefundUncertain:
        _alert(
            f'Charge {row.reference} (KES {row.amount}): refund outcome unknown. '
            f'Check Paystack before retrying.'
        )
        return False
    _finish(
        row, status='refunded',
        refund_status=str(refund_status)[:20],
        refund_reference=str(refund_id or '')[:100],
    )
    return True


def reconcile_refund(row):
    """Ask Paystack about a 'refunding' row. Returns 'refunded', 'none', 'odd' or 'error'."""
    try:
        response = requests.get(
            f'{API}/refund', params={'reference': row.reference},
            headers=_headers(), timeout=30,
        )
        body = response.json()
    except (requests.RequestException, ValueError):
        return 'error'
    if response.status_code != 200 or not body.get('status'):
        return 'error'
    refunds = body.get('data') or []
    if not refunds:
        return 'none'
    if len(refunds) == 1 and refunds[0].get('status') in ('pending', 'processing', 'processed'):
        _finish(
            row, status='refunded',
            refund_status=refunds[0]['status'],
            refund_reference=str(refunds[0].get('id') or '')[:100],
        )
        return 'refunded'
    return 'odd'


def handle_extra_charge(reference, data):
    """
    Webhook hook. True if the reference is ours (parcel/hire).

    A charge that cannot be applied is recorded durably (UnappliedPayment) and
    the admins are alerted once; the process_unapplied command retries or
    refunds it. This never calls Paystack itself, so the webhook stays fast.
    """
    if not (PARCEL_REF.match(reference or '') or CHARTER_REF.match(reference or '')):
        return False

    from django.utils import timezone
    from bookings.models import UnappliedPayment

    existing = UnappliedPayment.objects.filter(reference=reference).first()
    # Already handled, being refunded, or waiting for a human: never re-apply
    # (a replay must not mark a refunded parcel as paid).
    if existing is not None and existing.status != 'retry':
        return True

    try:
        apply_charge(reference, data)
    except Exception as exc:
        logger.exception('Paystack payment %s could not be applied', reference)
        if existing is None:
            record_failure(reference, data, exc)
    else:
        if existing is not None:
            UnappliedPayment.objects.filter(pk=existing.pk, status='retry').update(
                status='applied', updated_at=timezone.now()
            )
    return True
