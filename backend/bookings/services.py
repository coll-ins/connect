from decimal import Decimal, ROUND_HALF_UP

import requests
from django.utils import timezone

from rest_framework.throttling import SimpleRateThrottle
from decimal import Decimal, ROUND_HALF_UP


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


def settle_booking_fault(booking, fault_party):
    """
    Calculate and initiate the appropriate refund for a confirmed
    booking that will not be boarded.

    Passenger fault:
        50% refund.

    Company fault:
        100% refund.

    Digital payments:
        A real Paystack refund is initiated.

    Cash payments:
        No Paystack refund is initiated. The booking is returned
        with the calculated refund amount so a separate cash
        reconciliation/refund workflow can handle it.

    This function does NOT modify Django wallet balances.
    """

    from django.conf import settings
    from .models import Payment
    

    try:
        payment = booking.payment
    except Payment.DoesNotExist:
        return Decimal('0.00')

    # No confirmed payment means there is no money to refund.
    if payment.status != 'confirmed':
        return Decimal('0.00')

    if fault_party not in ('passenger', 'company'):
        raise ValueError('Invalid fault party.')

    fare = payment.amount

    if fault_party == 'company':
        refund_amount = fare
    else:
        refund_amount = (
            fare / Decimal('2')
        ).quantize(
            Decimal('0.01'),
            rounding=ROUND_HALF_UP
        )

    # Prevent accidentally creating another refund request.
    if payment.refund_status in (
        'pending',
        'processing',
        'processed',
    ):
        return payment.refund_amount or Decimal('0.00')

    # Cash does not go through Paystack.
    # We calculate the amount but leave the actual cash
    # reconciliation for a separate workflow.
    if payment.method == 'cash':
        payment.refund_amount = refund_amount
        payment.refund_status = 'not_requested'
        payment.save(
            update_fields=[
                'refund_amount',
                'refund_status',
            ]
        )
        return refund_amount

    # Digital payment must have a Paystack reference.
    if payment.method != 'digital':
        raise ValueError('Unsupported payment method.')

    if not payment.provider_reference:
        raise ValueError(
            'Digital payment has no provider reference.'
        )

    amount_in_cents = int(refund_amount * Decimal('100'))

    headers = {
        'Authorization': (
            f'Bearer {settings.PAYSTACK_SECRET_KEY}'
        ),
        'Content-Type': 'application/json',
    }

    payload = {
        'transaction': payment.provider_reference,
        'amount': amount_in_cents,
        'currency': 'KES',
        'customer_note': (
            f'Refund for CONNECT booking '
            f'{booking.booking_number}'
        ),
        'merchant_note': (
            f'CONNECT booking refund '
            f'{booking.booking_number}'
        ),
    }

    try:
        response = requests.post(
            'https://api.paystack.co/refund',
            json=payload,
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ValueError(
            'Unable to connect to payment gateway.'
        ) from exc

    if response.status_code != 200:
        raise ValueError(
            'Payment provider rejected the refund request.'
        )

    try:
        response_data = response.json()
    except ValueError as exc:
        raise ValueError(
            'Invalid response from payment gateway.'
        ) from exc

    if not response_data.get('status'):
        raise ValueError(
            response_data.get(
                'message',
                'Refund request failed.'
            )
        )

    refund_data = response_data.get('data', {})

    payment.refund_amount = refund_amount
    payment.refund_status = refund_data.get(
        'status',
        'pending'
    )

    # Paystack's refund object has its own ID.
    refund_id = refund_data.get('id')

    if refund_id is not None:
        payment.refund_reference = str(refund_id)

    payment.save(
        update_fields=[
            'refund_amount',
            'refund_status',
            'refund_reference',
        ]
    )

    return refund_amount