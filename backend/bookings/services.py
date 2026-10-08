from decimal import Decimal, ROUND_HALF_UP

import requests
from django.db import transaction
from django.utils import timezone

from rest_framework.throttling import SimpleRateThrottle
from .models import BookingHold


class BoardingVerifyThrottle(SimpleRateThrottle):
    """
    Custom throttle instead of ScopedRateThrottle + throttle_scope:
    DRF's @api_view decorator does not forward a .throttle_scope
    attribute to the generated view (verified — it silently does
    nothing), so ScopedRateThrottle never actually saw a scope and
    never throttled anything. This works because 'scope' is a
    hardcoded class attribute here, with nothing depending on
    per-view attribute forwarding.
    """
    scope = 'boarding_verify'

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}



def trip_has_departed(trip):
    """
    True if this trip is gone: either already flagged 'departed' by
    process_noshows, or its departure time has passed but the sweep
    hasn't run yet. Payment should never be accepted on a booking
    whose trip is in this state — otherwise money gets confirmed and
    held with no way for process_noshows to ever find it again (it
    only scans trips still 'scheduled'/'boarding').
    """
    if not trip:
        return True
    return trip.status not in ['scheduled', 'boarding'] or trip.departure_at <= timezone.now()


import logging

logger = logging.getLogger(__name__)


class RefundRejected(ValueError):
    """Paystack definitively refused the refund: nothing was refunded."""


class RefundClaim:
    """A refund reserved in the database but not yet sent to Paystack."""

    __slots__ = (
        'payment_id',
        'booking_id',
        'booking_number',
        'provider_reference',
        'refund_amount',
    )

    def __init__(self, payment_id, booking_id, booking_number,
                 provider_reference, refund_amount):
        self.payment_id = payment_id
        self.booking_id = booking_id
        self.booking_number = booking_number
        self.provider_reference = provider_reference
        self.refund_amount = refund_amount


def _alert_admin(message):
    try:
        from notifications.sms import send_admin_alert_sms
        send_admin_alert_sms(message)
    except Exception:
        logger.exception('Admin alert failed: %s', message)


def claim_booking_refund(booking, fault_party):
    """
    DATABASE ONLY - never talks to Paystack.

    Reserves the refund by moving the payment to "processing" so no other
    request can refund it too. Call it inside the caller's transaction, then
    call execute_booking_refund(claim) AFTER that transaction has committed.

    Passenger fault: 50% refund. Company fault: 100% refund.

    Returns (refund_amount, claim). claim is None when nothing has to be sent
    to Paystack (no confirmed payment, cash, below the gateway minimum, or a
    refund that is already pending/processing/processed).
    """
    from .models import Payment

    with transaction.atomic():
        try:
            payment = (
                Payment.objects
                .select_for_update()
                .get(booking_id=booking.pk)
            )
        except Payment.DoesNotExist:
            return Decimal('0.00'), None

        if payment.status != 'confirmed':
            return Decimal('0.00'), None

        if fault_party not in ('passenger', 'company'):
            raise ValueError('Invalid fault party.')

        # Another request already owns this refund. Never send a second one.
        if payment.refund_status in ('pending', 'processing', 'processed'):
            return payment.refund_amount or Decimal('0.00'), None

        fare = payment.amount

        if fault_party == 'company':
            refund_amount = fare
        else:
            refund_amount = (
                fare / Decimal('2')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Cash does not go through Paystack.
        if payment.method == 'cash':
            payment.refund_amount = refund_amount
            payment.refund_status = 'not_requested'
            payment.save(update_fields=['refund_amount', 'refund_status'])
            return refund_amount, None

        if payment.method != 'digital':
            raise ValueError('Unsupported payment method.')

        if not payment.provider_reference:
            raise ValueError('Digital payment has no provider reference.')

        # Paystack rejects refunds below KES 5.
        if refund_amount < Decimal('5.00'):
            payment.refund_amount = refund_amount
            payment.refund_status = 'not_requested'
            payment.save(update_fields=['refund_amount', 'refund_status'])
            return refund_amount, None

        # Refuse impossible refunds BEFORE any money moves.
        hold = (
            BookingHold.objects
            .select_for_update()
            .filter(booking_id=booking.pk)
            .first()
        )
        if hold is not None and refund_amount > hold.amount:
            raise ValueError('Refund amount exceeds the booking hold amount.')

        payment.refund_amount = refund_amount
        payment.refund_status = 'processing'
        payment.refund_claimed_at = timezone.now()
        payment.save(
            update_fields=['refund_amount', 'refund_status', 'refund_claimed_at']
        )

        return refund_amount, RefundClaim(
            payment.pk,
            booking.pk,
            booking.booking_number,
            payment.provider_reference,
            refund_amount,
        )


def release_refund_claim(claim):
    """Paystack definitely refused: free the reservation so a retry is clean."""
    from .models import Payment

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=claim.payment_id)
        if payment.refund_status == 'processing':
            payment.refund_status = 'not_requested'
            payment.refund_amount = None
            payment.save(update_fields=['refund_status', 'refund_amount'])


def execute_booking_refund(claim):
    """
    Send a claimed refund to Paystack and record the outcome.

    MUST run with no database transaction open: a rollback after Paystack has
    accepted the refund would erase the claim and allow a second refund.

    Raises RefundRejected when Paystack definitely refused (nothing refunded;
    the caller should release_refund_claim) and a plain ValueError when the
    outcome is uncertain (the payment stays "processing" for reconciliation).
    """
    from django.conf import settings

    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }

    payload = {
        'transaction': claim.provider_reference,
        'amount': int(claim.refund_amount * Decimal('100')),
        'currency': 'KES',
        'customer_note': f'Refund for CONNECT booking {claim.booking_number}',
        'merchant_note': f'CONNECT booking refund {claim.booking_number}',
    }

    try:
        response = requests.post(
            'https://api.paystack.co/refund',
            json=payload,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        # A timeout is ambiguous: Paystack may have received the request.
        raise ValueError(
            'Unable to confirm the refund gateway request. '
            'Refund remains processing and must be reconciled.'
        ) from exc

    if response.status_code != 200:
        try:
            detail = response.json().get('message')
        except ValueError:
            detail = None

        message = (
            'Payment provider did not confirm the refund request'
            + (f': {detail}' if detail else '.')
        )

        # A 4xx means the request was refused, so nothing was refunded.
        if 400 <= response.status_code < 500 and response.status_code != 408:
            raise RefundRejected(message)

        raise ValueError(message)

    try:
        response_data = response.json()
    except ValueError as exc:
        raise ValueError(
            'Invalid response from payment gateway. '
            'Refund remains processing and must be reconciled.'
        ) from exc

    if not response_data.get('status'):
        raise RefundRejected(
            response_data.get(
                'message',
                'Refund request was not confirmed by the payment provider.'
            )
        )

    refund_data = response_data.get('data') or {}

    return record_refund_result(
        claim,
        refund_data.get('status', 'pending'),
        refund_data.get('id'),
    )


def record_refund_result(claim, provider_refund_status, refund_id):
    """
    Record what Paystack says about a claimed refund. Database only.
    Used by execute_booking_refund and by the reconcile_refunds command.
    """
    from .models import Payment

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=claim.payment_id)

        hold = (
            BookingHold.objects
            .select_for_update()
            .filter(booking_id=claim.booking_id)
            .first()
        )

        # A webhook may have finished the refund first. Never downgrade a
        # final state.
        if payment.refund_status != 'processed':
            payment.refund_status = provider_refund_status
            update_fields = ['refund_status']

            if refund_id is not None:
                payment.refund_reference = str(refund_id)
                update_fields.append('refund_reference')

            payment.save(update_fields=update_fields)

        refund_to_record = payment.refund_amount or claim.refund_amount

        if hold is not None:
            new_refunded_amount = max(
                hold.refunded_amount or Decimal('0.00'),
                refund_to_record,
            )

            # The money has already moved: never roll back over this.
            if new_refunded_amount > hold.amount:
                logger.error(
                    'Refund for %s exceeds its hold; capping the record.',
                    claim.booking_number,
                )
                new_refunded_amount = hold.amount

            hold.refunded_amount = new_refunded_amount

            if (
                payment.refund_status == 'processed'
                and new_refunded_amount >= hold.amount
            ):
                hold.status = 'refunded'
                hold.refunded_at = timezone.now()
                hold.save(
                    update_fields=[
                        'refunded_amount',
                        'status',
                        'refunded_at',
                        'updated_at',
                    ]
                )
            else:
                hold.save(update_fields=['refunded_amount', 'updated_at'])

        return payment.refund_amount or claim.refund_amount


def run_refund_claims(claims):
    """
    Send refunds that were claimed inside a transaction that has now
    committed. Never raises.
    """
    results = []

    for claim in claims:
        try:
            results.append(execute_booking_refund(claim))
        except RefundRejected as exc:
            release_refund_claim(claim)
            logger.warning(
                'Refund rejected for %s: %s (the sweep will retry it)',
                claim.booking_number,
                exc,
            )
        except Exception as exc:
            logger.error(
                'Refund for %s needs reconciliation: %s',
                claim.booking_number,
                exc,
            )
            _alert_admin(
                f'Refund for booking {claim.booking_number} '
                f'({claim.refund_amount}) is unconfirmed. '
                f'Check Paystack before retrying.'
            )

    return results


def settle_booking_fault(booking, fault_party):
    """
    Claim and send a refund in one call. Use it only OUTSIDE a database
    transaction. Inside one, call claim_booking_refund() and send the claim
    with run_refund_claims() after the transaction commits.

    Passenger fault: 50% refund. Company fault: 100% refund.
    Cash: nothing is sent to Paystack; the amount is recorded for the
    separate cash workflow. This does NOT modify Django wallet balances.
    """
    refund_amount, claim = claim_booking_refund(booking, fault_party)

    if claim is None:
        return refund_amount

    try:
        return execute_booking_refund(claim)
    except RefundRejected:
        release_refund_claim(claim)
        raise


def create_booking_hold(booking):
    """
    Create the financial hold for a successfully confirmed payment.

    Idempotent:
    - If a hold already exists, return it.
    - Never create two holds for the same booking.
    """
    with transaction.atomic():
        hold, created = BookingHold.objects.get_or_create(
            booking=booking,
            defaults={
                'amount': booking.total_amount,
                'status': 'held',
            },
        )

        if not created:
            if hold.status == 'held':
                return hold

            raise ValueError(
                f'Booking {booking.booking_number} already has '
                f'a financial hold in status "{hold.status}".'
            )

        return hold


def release_booking_hold(booking):
    """
    Mark a booking's held payment as released after boarding.

    Idempotent:
    - Already released → return the existing hold.
    """
    with transaction.atomic():
        hold = (
            BookingHold.objects
            .select_for_update()
            .get(booking=booking)
        )

        if hold.status == 'released':
            return hold

        if hold.status != 'held':
            raise ValueError(
                f'Cannot release hold in status "{hold.status}".'
            )

        hold.status = 'released'
        hold.released_at = timezone.now()
        hold.save(
            update_fields=[
                'status',
                'released_at',
                'updated_at',
            ]
        )

        return hold


def refund_booking_hold(booking):
    """
    Mark a booking's financial hold as refunded.

    The actual Paystack refund remains responsible for moving
    real money. This function records the internal hold state.

    Idempotent:
    - Already refunded → return the existing hold.
    """
    with transaction.atomic():
        hold = (
            BookingHold.objects
            .select_for_update()
            .get(booking=booking)
        )

        if hold.status == 'refunded':
            return hold

        if hold.status != 'held':
            raise ValueError(
                f'Cannot refund hold in status "{hold.status}".'
            )

        hold.status = 'refunded'
        hold.refunded_at = timezone.now()
        hold.save(
            update_fields=[
                'status',
                'refunded_at',
                'updated_at',
            ]
        )

        return hold


def settle_unboarded_no_shows(trip, claims=None):
    """
    Called when a trip ends. Confirmed bookings that never boarded become
    passenger no-shows (50% refund). If the trip has an active incident,
    those bookings are left for the passenger's refund/reschedule choice.
    Pending bookings are cancelled.

    Must be called inside transaction.atomic().
    Returns (settled_count, protected_count).
    """
    import logging

    log = logging.getLogger(__name__)

    trip.bookings.filter(status='pending').update(status='cancelled')

    confirmed = trip.bookings.filter(status='confirmed')

    if trip.incidents.filter(status__in=['reported', 'investigating']).exists():
        return 0, confirmed.count()

    settled = 0
    for booking in confirmed.select_for_update().select_related('user'):
        try:
            if claims is None:
                settle_booking_fault(booking, fault_party='passenger')
            else:
                # Reserve only. The caller sends the claims to Paystack
                # after its transaction commits (run_refund_claims).
                _, claim = claim_booking_refund(booking, 'passenger')
                if claim is not None:
                    claims.append(claim)
        except ValueError as exc:
            # Same behaviour as process_noshows: still mark the no-show;
            # a failed refund is retried by that command.
            log.warning(
                'Refund failed for %s: %s', booking.booking_number, exc
            )

        booking.status = 'no_show'
        booking.save(update_fields=['status'])

        booking.user.no_show_count += 1
        booking.user.save(update_fields=['no_show_count'])
        settled += 1

    return settled, 0
