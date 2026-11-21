import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import BookingHold
from .seats import ensure_numbers

# How long past its departure time a boarding trip stays bookable/payable.
BOARDING_BOOKABLE_WINDOW = timedelta(hours=2)

# Statuses that always take a seat. A pending booking takes one only while
# its hold lasts (see active_seat_q).
_SEAT_STATUSES = ('confirmed', 'completed', 'no_show')


class NotEnoughSeats(Exception):
    def __init__(self, available):
        super().__init__(f'Only {available} seats remaining.')
        self.available = max(available, 0)


def active_seat_q(now=None, prefix=''):
    """
    The one definition of "this booking takes a seat", as a Q.

    prefix is the lookup path from the model being queried to Booking
    (for example 'bookings__' when annotating Trip).

    A pending booking with no held_until counts as held: such a row was
    written by code that predates the hold (or by an old process during a
    rolling deploy), and counting it can never oversell.
    """
    now = now or timezone.now()
    return (
        Q(**{f'{prefix}status__in': _SEAT_STATUSES})
        | (
            Q(**{f'{prefix}status': 'pending'})
            & (
                Q(**{f'{prefix}held_until__isnull': True})
                | Q(**{f'{prefix}held_until__gt': now})
            )
        )
    )


def seats_taken(trip, now=None, exclude_booking_id=None):
    """Seats on `trip` that count against its capacity right now: live
    bookings plus the seats an operator blocked."""
    qs = trip.bookings.filter(active_seat_q(now))
    if exclude_booking_id is not None:
        qs = qs.exclude(pk=exclude_booking_id)
    booked = qs.aggregate(total=Sum('seats'))['total'] or 0
    return booked + trip.seat_assignments.filter(blocked=True).count()


def reserve_seats(trip, seats, now=None, exclude_booking_id=None):
    """
    Check that `seats` more fit on `trip`. The caller must already hold the
    Trip row lock. Returns the seats left after this request, or raises
    NotEnoughSeats carrying how many were available.
    """
    available = trip.capacity - seats_taken(trip, now, exclude_booking_id)
    if seats > available:
        raise NotEnoughSeats(available)
    return available - seats


def booking_closes_at(trip):
    """When online booking and passenger moves onto `trip` stop."""
    minutes = trip.route.company.booking_cutoff_minutes
    return trip.departure_at - timedelta(minutes=minutes)


def hold_deadline(trip, now=None, minutes=None):
    """held_until for a booking that is pending as of `now`. Never past departure."""
    now = now or timezone.now()
    if minutes is None:
        minutes = getattr(settings, 'PAYMENT_HOLD_MINUTES', 10)
    deadline = now + timedelta(minutes=minutes)
    if trip is not None and trip.departure_at < deadline:
        return trip.departure_at
    return deadline


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
    now = timezone.now()
    if trip.status == 'scheduled':
        return trip.departure_at <= now
    if trip.status == 'boarding':
        return trip.departure_at <= now - BOARDING_BOOKABLE_WINDOW
    return True


def cash_due_on_board(booking, payment):
    """Cash passenger who pays the driver on boarding: seat held, PIN shown."""
    return (
        booking.status == 'pending'
        and payment is not None
        and payment.method == 'cash'
        and payment.status == 'pending'
    )


def before_change_cutoff(trip):
    """True while the passenger can still cancel for free or change bus."""
    from django.conf import settings
    return (
        trip is not None
        and trip.status == 'scheduled'
        and trip.departure_at - timezone.now()
        > timedelta(minutes=settings.BOOKING_CHANGE_CUTOFF_MINUTES)
    )


def cash_still_payable(trip):
    """Cash can be taken until the trip ends: passengers board at stages
    along the way, after the bus has left the first one."""
    if trip and trip.status in ('boarding', 'departed'):
        from django.conf import settings
        hours = getattr(settings, 'TRIP_AUTO_CLOSE_AFTER_HOURS', 12)
        # A trip nobody ended is not still running days later.
        return trip.departure_at > timezone.now() - timedelta(hours=hours)
    return not trip_has_departed(trip)


def cancel_dead_pending_bookings(bookings):
    """
    Cancel unpaid bookings whose trip is gone (see trip_has_departed), so they
    stop showing as waiting for a payment that can no longer be accepted.
    Each row is locked first, so a payment confirmed a moment earlier wins.
    Returns how many were cancelled.
    """
    from django.db import OperationalError
    from django.db.models import Q

    from .models import Booking, Payment

    now = timezone.now()
    dead_ids = list(
        bookings.filter(status='pending')
        .filter(
            Q(trip__isnull=True)
            | Q(trip__status__in=['departed', 'completed', 'cancelled'])
            | Q(trip__status='scheduled', trip__departure_at__lte=now)
            | Q(
                trip__status='boarding',
                trip__departure_at__lte=now - BOARDING_BOOKABLE_WINDOW,
            )
        )
        # A cash passenger waiting at a later stage is still coming.
        .exclude(
            payment__method='cash',
            payment__status='pending',
            trip__status__in=['boarding', 'departed'],
        )
        .values_list('pk', flat=True)
    )

    cancelled = 0
    for pk in dead_ids:
        try:
            with transaction.atomic():
                booking = Booking.objects.select_for_update().get(pk=pk)
                if booking.status != 'pending':
                    continue
                if Payment.objects.filter(booking=booking, status='confirmed').exists():
                    continue
                booking.status = 'cancelled'
                booking.save(update_fields=['status'])
                cancelled += 1
        except OperationalError:
            # Lock conflict with a payment in flight: leave it for the next run.
            continue
    return cancelled


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


def _refund_to_wallet(booking, payment, refund_amount):
    from wallets import services as wallet_services

    hold = (
        BookingHold.objects
        .select_for_update()
        .filter(booking_id=booking.pk)
        .first()
    )
    if hold is not None and refund_amount > hold.amount:
        raise ValueError('Refund amount exceeds the booking hold amount.')
    if refund_amount <= 0:
        payment.refund_amount = refund_amount
        payment.refund_status = 'not_requested'
        payment.save(update_fields=['refund_amount', 'refund_status'])
        return refund_amount

    # The payer gets the money, whoever (staff or sweep) triggered the refund.
    wallet_services.credit(
        booking.user, refund_amount, 'refund', f'refund:{payment.pk}',
        booking=booking,
    )
    payment.refund_amount = refund_amount
    payment.refund_claimed_at = timezone.now()
    payment.save(update_fields=['refund_amount', 'refund_claimed_at'])
    return record_refund_result(
        RefundClaim(payment.pk, booking.pk, booking.booking_number,
                    None, refund_amount),
        'processed', f'WALLET-{payment.pk}',
    )


def claim_booking_refund(booking, fault_party):
    """
    DATABASE ONLY - never talks to Paystack.

    Reserves the refund by moving the payment to "processing" so no other
    request can refund it too. Call it inside the caller's transaction, then
    call execute_booking_refund(claim) AFTER that transaction has committed.

    Passenger fault: 50% refund. Company fault: 100% refund.

    Returns (refund_amount, claim). claim is None when nothing has to be sent
    to Paystack (no confirmed payment, cash, wallet (credited here), below the
    gateway minimum, or a refund that is already pending/processing/processed).
    """
    from .models import Booking, Payment

    with transaction.atomic():
        # Booking before Payment, the order every other path uses. A caller
        # that already holds the lock (cancel_booking) is not blocked: row
        # locks are re-entrant within one transaction.
        Booking.objects.select_for_update(of=('self',)).filter(pk=booking.pk).first()
        try:
            payment = (
                Payment.objects
                .select_for_update(of=('self',))
                .get(booking_id=booking.pk)
            )
        except Payment.DoesNotExist:
            return Decimal('0.00'), None

        if payment.status != 'confirmed':
            return Decimal('0.00'), None

        # 'passenger_early': the passenger cancelled before the change
        # cut-off, so the seat can still be resold: full refund.
        if fault_party not in ('passenger', 'passenger_early', 'company'):
            raise ValueError('Invalid fault party.')

        # Another request already owns this refund. Never send a second one.
        if payment.refund_status in ('pending', 'processing', 'processed'):
            return payment.refund_amount or Decimal('0.00'), None

        fare = payment.amount

        if fault_party in ('company', 'passenger_early'):
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

        # Wallet money is ours to give back at once: no gateway step, and no
        # KES 5 floor (that is a Paystack limit). Booking, Payment and Hold are
        # locked above and below; the Wallet is locked last, inside credit().
        if payment.method == 'wallet':
            return _refund_to_wallet(booking, payment, refund_amount), None

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
        fields = ['refund_amount', 'refund_status', 'refund_claimed_at']
        # The id of a failed earlier refund must not match a redelivered
        # event for it once this retry is in flight.
        if payment.refund_reference:
            payment.refund_reference = None
            fields.append('refund_reference')
        # Remember who was at fault so a refund that later fails at the
        # gateway can be retried with the same rule (see process_noshows).
        # refund_reason is 20 characters: 'passenger_early' is stored as 'early'.
        if payment.refund_reason in ('', 'fault_passenger', 'fault_company', 'fault_early'):
            payment.refund_reason = f'fault_{fault_party.replace("passenger_", "")}'
            fields.append('refund_reason')
        payment.save(update_fields=fields)

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

            if provider_refund_status == 'processed':
                payment.refunded_at = timezone.now()
                update_fields.append('refunded_at')
                total_refunded = payment.refund_amount or claim.refund_amount
                if total_refunded >= payment.amount:
                    payment.status = 'refunded'
                    update_fields.append('status')

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
    separate cash workflow. Wallet: the refund is credited to the payer's
    wallet at once (no Paystack call). Paystack payments never touch wallets.
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


def cancel_trip_bookings(trip, claims):
    """
    Called when the company cancels a trip. It is the company's fault, so each
    paid booking gets a 100% refund. Unpaid bookings are simply cancelled.

    Must be called inside transaction.atomic(). Refunds are only reserved
    here: the caller sends the claims with run_refund_claims() after commit.
    A booking whose refund cannot be reserved is still cancelled and the admin
    is alerted; the process_noshows sweep retries it.

    Returns (booking, was_paid) for every booking that was cancelled.
    """
    affected = []

    for booking in (
        trip.bookings
        .select_for_update(of=('self',))
        .select_related('user')
        .filter(status__in=('pending', 'confirmed'))
    ):
        was_paid = booking.status == 'confirmed'

        if was_paid:
            try:
                _, claim = claim_booking_refund(booking, 'company')
                if claim is not None:
                    claims.append(claim)
            except ValueError as exc:
                logger.warning(
                    'Refund failed for %s: %s', booking.booking_number, exc
                )
                # Sent after commit so no external call runs under row locks;
                # a rollback drops it with the cancellation it describes.
                alert = (
                    f'Trip {trip.pk} was cancelled but booking '
                    f'{booking.booking_number} could not be refunded: {exc}'
                )
                transaction.on_commit(lambda alert=alert: _alert_admin(alert))

        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        affected.append((booking, was_paid))

    return affected


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

    from django.db.models import F as _F

    from .models import Payment

    incident = trip.incidents.filter(
        status__in=['reported', 'investigating']
    ).exists()

    # A cash hold that never boarded is a no-show too: it held a seat for the
    # whole trip. Without this, cash could be reserved and skipped for free.
    if not incident:
        holds = trip.bookings.filter(
            status='pending',
            payment__method='cash',
            payment__status='pending',
        ).select_for_update()
        for booking in holds:
            booking.status = 'no_show'
            booking.save(update_fields=['status'])
            Payment.objects.filter(booking=booking, status='pending').update(
                status='failed'
            )
            type(booking.user).objects.filter(pk=booking.user_id).update(
                no_show_count=_F('no_show_count') + 1
            )

    trip.bookings.filter(status='pending').update(status='cancelled')

    confirmed = trip.bookings.filter(status='confirmed')

    if incident:
        return 0, confirmed.count()

    settled = 0
    for booking in confirmed.select_for_update(of=('self',)).select_related('user'):
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

        type(booking.user).objects.filter(pk=booking.user_id).update(
            no_show_count=_F('no_show_count') + 1
        )
        settled += 1

    return settled, 0


# ============================================================
# ONE CONFIRM PATH FOR A DIGITAL PAYMENT
# ============================================================

def currency_ok(currency):
    # Reject a currency Paystack reports as something other than KES. A
    # missing field is not rejected: the amount check still applies and the
    # payload shape is not verified against Paystack's docs.
    return currency is None or str(currency).strip().upper() == 'KES'


class PaymentOutcome:
    """What confirm_booking_payment decided. `result` is one of:

    not_found  no payment has that reference
    retry      the booking moved trips while we waited for locks: try again
    ignored    already confirmed/refunded, or not a digital payment: nothing done
    rejected   amount/currency wrong: payment marked failed and the charge
               queued (refund_due for a KES underpayment, review when it
               cannot be trusted); `alert` says why (None when a replay)
    refund     payment confirmed but the booking cannot be used: caller must
               refund after commit (settle_booking_fault, company fault)
    confirmed  booking confirmed and the financial hold created

    `extra_refunds` holds the UnappliedPayment row of an overpayment's
    difference. The caller sends it after commit (or alerts, when the row is
    'review'); process_unapplied sends it if the caller dies first.
    """

    __slots__ = ('result', 'payment', 'booking', 'alert', 'extra_refunds')

    def __init__(self, result, payment=None, booking=None, alert=None,
                 extra_refunds=None):
        self.result = result
        self.payment = payment
        self.booking = booking
        self.alert = alert
        self.extra_refunds = extra_refunds or []


# Paystack refuses refunds below this, so a smaller difference needs a human.
MIN_GATEWAY_REFUND = Decimal('5.00')

# The column holds 100 characters: CONNECT- plus up to 92 more fits it on PostgreSQL.
CONNECT_REF = re.compile(r'^CONNECT-[A-Za-z0-9_.-]{1,92}$')


def _kes(subunits):
    return (Decimal(subunits) / Decimal(100)).quantize(Decimal('0.01'))


def charge_refund_totals(payment):
    """
    (paid, refunded) in KES for one charge: what Paystack took and what has
    been refunded or is owed back, counting the booking refund and any
    UnappliedPayment rows on the same reference. For a late payment the two
    are equal; they must never differ by a refund too many.
    """
    from .models import UnappliedPayment

    paid = payment.paid_amount if payment.paid_amount is not None else payment.amount
    refunded = Decimal('0.00')
    if payment.refund_status in ('pending', 'processing', 'processed'):
        refunded += payment.refund_amount or Decimal('0.00')
    extra = (
        UnappliedPayment.objects
        .filter(reference=payment.provider_reference,
                status__in=('refund_due', 'refunding', 'refunded'))
        .aggregate(total=Sum('amount'))['total']
    )
    return paid, refunded + (extra or Decimal('0.00'))


def record_unmatched_charge(reference, paid_amount, currency):
    """
    A signed charge.success for a CONNECT reference that matches no Payment
    (an old checkout paid after re-initiation, a duplicate charge). The money
    is ours to give back: one UnappliedPayment per reference, refund_due for
    a full refund, review when the amount or currency cannot be trusted.

    Returns (row, created), or (None, False) for a reference that is not ours.
    """
    from .models import UnappliedPayment

    if not CONNECT_REF.match(reference or ''):
        return None, False
    amount = None
    try:
        paid = int(paid_amount)
        # UnappliedPayment.amount holds 10 digits: a bigger figure is not a
        # real charge and goes to a human with no amount.
        if 0 < paid < 10 ** 10:
            amount = _kes(paid)
    except (TypeError, ValueError, OverflowError):
        pass
    refundable = (
        amount is not None
        and amount >= MIN_GATEWAY_REFUND
        and str(currency or '').strip().upper() == 'KES'
    )
    return UnappliedPayment.objects.get_or_create(
        reference=reference,
        defaults={
            'kind': 'booking',
            'amount': amount,
            'currency': str(currency or '')[:10],
            'reason': 'no booking payment matches this reference',
            'payload': {'amount': str(paid_amount)[:20], 'currency': str(currency or '')[:10]},
            'status': 'refund_due' if refundable else 'review',
        },
    )


def _lock_payment_chain(payment_id, booking_id, trip_id):
    """
    Lock Trip -> Booking -> Payment, the one order every money and seat path
    uses (create_booking, cancel_booking, cash confirm). of=('self',) keeps
    each lock to its own table: no joined User or Route rows are locked.
    """
    from companies.models import Trip
    from .models import Booking, Payment

    trip = (
        Trip.objects.select_for_update(of=('self',)).get(pk=trip_id)
        if trip_id is not None else None
    )
    booking = Booking.objects.select_for_update(of=('self',)).get(pk=booking_id)
    payment = Payment.objects.select_for_update(of=('self',)).get(pk=payment_id)
    return trip, booking, payment


def confirm_booking_payment(*, paid_amount, currency, reference=None, payment_id=None):
    """
    The only place a digital payment turns a booking into a paid one. Used by
    the webhook, payment_status and verify_paystack_payment.

    The caller must NOT hold a transaction open (this opens its own) and must
    refund after it returns when the outcome is 'refund'.
    """
    from .models import Payment

    lookup = (
        {'provider_reference': reference} if reference is not None
        else {'pk': payment_id}
    )
    ids = (
        Payment.objects.filter(**lookup)
        .values('pk', 'booking_id', 'booking__trip_id').first()
    )
    if ids is None:
        return PaymentOutcome('not_found')

    with transaction.atomic():
        trip, booking, payment = _lock_payment_chain(
            ids['pk'], ids['booking_id'], ids['booking__trip_id'])

        if booking.trip_id != ids['booking__trip_id']:
            return PaymentOutcome('retry', payment, booking)

        # Wallet pay may have taken this Payment over (clearing its reference)
        # between the lookup above and our locks. The charge then belongs to
        # no payment: the webhook records it as unmatched and refunds it.
        if reference is not None and payment.provider_reference != reference:
            return PaymentOutcome('not_found')

        # Paystack may retry the same webhook; verify/status may race it.
        if payment.status in ('confirmed', 'refunded') or payment.method != 'digital':
            return PaymentOutcome('ignored', payment, booking)

        ref = payment.provider_reference
        problem = None
        paid = None
        if paid_amount is None:
            problem = 'amount missing in webhook'
        else:
            try:
                paid = int(paid_amount)
            except (TypeError, ValueError):
                problem = 'amount unreadable in webhook'
        expected = int(payment.amount * Decimal('100'))
        if problem is None:
            # Never trust the gateway response blindly: the amount must match
            # what CONNECT expected. Paying MORE in KES is accepted below.
            if paid >= 10 ** 10:
                # Over what the amount columns hold: a person looks at it.
                problem = f'amount too large: paid {paid} {currency}'
            elif paid < expected or not currency_ok(currency):
                problem = (
                    f'amount/currency mismatch: paid {paid} {currency}, '
                    f'expected {expected}'
                )
        if problem is not None:
            from .models import UnappliedPayment

            payment.status = 'failed'
            fields = ['status']
            # Whatever Paystack took is given back in full, nothing withheld:
            # an underpayment in KES is queued refund_due and process_unapplied
            # sends it. Only an amount or currency we cannot trust (or one under
            # the gateway minimum) waits for a person.
            refundable = (
                paid is not None
                and 0 < paid < 10 ** 10
                and _kes(paid) >= MIN_GATEWAY_REFUND
                and str(currency or '').strip().upper() == 'KES'
            )
            if refundable:
                payment.paid_amount = _kes(paid)
                fields.append('paid_amount')
            payment.save(update_fields=fields)
            _, created = UnappliedPayment.objects.get_or_create(
                reference=ref,
                defaults={
                    'kind': 'booking',
                    'amount': _kes(paid) if paid is not None and 0 < paid < 10 ** 10 else None,
                    'currency': str(currency or '')[:10],
                    'reason': problem[:255],
                    'payload': {'booking_id': booking.pk, 'expected': expected},
                    'status': 'refund_due' if refundable else 'review',
                },
            )
            return PaymentOutcome('rejected', payment, booking,
                                  alert=(ref, problem) if created else None)

        # -------------------------------------------------
        # PAYMENT CONFIRMED
        # -------------------------------------------------
        #
        # We deliberately do NOT add money to the user's
        # Django Wallet here.
        #
        # Paystack confirmation means the payment succeeded.
        # It does NOT mean CONNECT has released the money
        # to the transport company.
        #
        now = timezone.now()
        update_fields = ['status', 'settlement_status', 'confirmed_at']

        # The difference is recorded first and unconditionally, so it is owed
        # back whether the booking is then confirmed or refunded as late.
        extra_refunds = []
        if paid > expected:
            from .models import UnappliedPayment

            excess = _kes(paid - expected)
            payment.paid_amount = _kes(paid)
            update_fields.append('paid_amount')
            row, created = UnappliedPayment.objects.get_or_create(
                reference=ref,
                defaults={
                    'kind': 'booking',
                    'amount': excess,
                    'currency': 'KES',
                    'reason': 'overpayment',
                    'payload': {'booking_id': booking.pk, 'paid': paid,
                                'expected': expected},
                    # Under the gateway minimum nothing can be sent.
                    'status': ('refund_due' if excess >= MIN_GATEWAY_REFUND
                               else 'review'),
                },
            )
            if created:
                extra_refunds.append(row)

        payment.status = 'confirmed'
        payment.settlement_status = 'not_ready'
        payment.confirmed_at = now

        # A booking that cannot be used: closed, the trip is gone, the hold
        # ran out (past the arrival tolerance) or ran out a little earlier and
        # the seat has been resold. Money is never kept: the caller refunds
        # after commit and the sweep covers a crash. The booking is never
        # revived. An unstamped hold (held_until NULL) is never late.
        tolerance = timedelta(
            seconds=getattr(settings, 'PAYMENT_ARRIVAL_TOLERANCE_SECONDS', 60))
        unusable = (
            booking.status in ('cancelled', 'completed', 'no_show')
            or trip_has_departed(trip)
            or (
                booking.status == 'pending'
                and booking.held_until is not None
                and now > booking.held_until + tolerance
            )
        )
        if (
            not unusable
            and booking.status == 'pending'
            and booking.held_until is not None
            and booking.held_until <= now
        ):
            unusable = (
                seats_taken(trip, now, exclude_booking_id=booking.pk)
                + booking.seats > trip.capacity
            )

        if unusable:
            payment.refund_reason = 'late_payment'
            update_fields.append('refund_reason')
        payment.save(update_fields=update_fields)

        if unusable:
            if booking.status in ('pending', 'confirmed'):
                booking.status = 'cancelled'
                booking.save(update_fields=['status'])
            return PaymentOutcome('refund', payment, booking,
                                  extra_refunds=extra_refunds)

        booking.status = 'confirmed'
        booking.save(update_fields=['status'])
        ensure_numbers(trip, booking, now=now)
        create_booking_hold(booking)
        return PaymentOutcome('confirmed', payment, booking,
                              extra_refunds=extra_refunds)


class BookingMoved(Exception):
    """The booking changed trips while we waited for its locks."""


def lock_trip_then_booking(booking_id, **filters):
    """
    Lock the booking's Trip, then the Booking: the order cancel_booking uses.
    Returns (trip, booking); trip is None for a booking with no trip.
    Raises Booking.DoesNotExist, or BookingMoved if it changed trips.
    """
    from companies.models import Trip
    from .models import Booking

    ref = Booking.objects.filter(pk=booking_id, **filters).values('trip_id').first()
    if ref is None:
        raise Booking.DoesNotExist
    trip = (
        Trip.objects.select_for_update(of=('self',)).get(pk=ref['trip_id'])
        if ref['trip_id'] is not None else None
    )
    # No select_related: Booking.trip is nullable and Postgres rejects
    # FOR UPDATE over the outer join it would produce.
    booking = Booking.objects.select_for_update(of=('self',)).get(
        pk=booking_id, **filters)
    if booking.trip_id != ref['trip_id']:
        raise BookingMoved
    return trip, booking


def hold_expired_and_seat_gone(booking, trip, now=None):
    """True for a pending booking whose hold ran out and whose seats are taken."""
    now = now or timezone.now()
    return (
        booking.status == 'pending'
        and booking.held_until is not None
        and booking.held_until <= now
        and trip is not None
        and seats_taken(trip, now, exclude_booking_id=booking.pk)
        + booking.seats > trip.capacity
    )


class WalletPayRefused(Exception):
    """A wallet payment that must not go ahead. Nothing was changed."""

    def __init__(self, code, message, http_status, **extra):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.extra = extra


def pay_booking_from_wallet(booking_id, user, echoed_amounts=()):
    """
    Pay a pending booking from the passenger's wallet, in one transaction:
    Trip -> Booking -> Payment -> BookingHold -> Wallet -> ledger.

    Returns (booking, payment, replayed). Raises Booking.DoesNotExist (not the
    caller's booking), WalletPayRefused, or wallets InsufficientFunds (the
    transaction has then rolled back: nothing changed). The debit amount is
    always the server's total_amount; `echoed_amounts` are client-sent figures
    that are only compared with it.
    """
    from decimal import InvalidOperation
    from wallets import services as wallet_services
    from wallets.models import WalletTransaction
    from .models import Payment

    if user.role != 'passenger':
        raise WalletPayRefused(
            'passenger_only', 'The wallet is for passenger accounts.', 403)

    reference = f'spend:{booking_id}'
    with transaction.atomic():
        try:
            trip, booking = lock_trip_then_booking(booking_id, user=user)
        except BookingMoved:
            raise WalletPayRefused(
                'booking_moved', 'This booking changed trips. Please try again.', 409)
        payment = (
            Payment.objects.select_for_update(of=('self',))
            .filter(booking=booking).first()
        )

        # The ledger row is the proof that this booking was paid from the
        # wallet, so it is checked before any status: a replay returns the
        # same result and changes nothing, even after the booking moved on.
        if WalletTransaction.objects.filter(reference=reference).exists():
            if (
                payment is not None and payment.method == 'wallet'
                and payment.status == 'confirmed'
                and booking.status in ('confirmed', 'completed')
            ):
                return booking, payment, True
            raise WalletPayRefused(
                'already_paid', 'This booking has already been paid for.', 409)

        if payment is not None and payment.status in ('confirmed', 'refunded'):
            raise WalletPayRefused(
                'already_paid', 'This booking has already been paid for.', 409)
        if booking.status != 'pending':
            raise WalletPayRefused(
                'booking_not_payable',
                f'Cannot pay for booking with status: {booking.status}', 400)

        total = booking.total_amount
        # A zero-price booking (legacy row) has nothing to debit.
        if total <= 0:
            raise WalletPayRefused(
                'amount_invalid', 'This booking has no payable amount.', 400)
        for sent in echoed_amounts:
            try:
                same = Decimal(str(sent)) == total
            except (InvalidOperation, ValueError):
                same = False
            if not same:
                raise WalletPayRefused(
                    'amount_mismatch', 'The amount does not match this booking.',
                    400, expected=str(total))

        if trip_has_departed(trip):
            raise WalletPayRefused(
                'trip_departed',
                'This trip has already departed. Payment can no longer be made.', 400)
        # No capacity recheck: a live pending booking still holds its seat.
        # An unstamped hold (held_until NULL) is never late.
        now = timezone.now()
        # Same arrival tolerance as card and cash, and the same rule after it:
        # a lapsed hold pays only while its seat is still free.
        tolerance = timedelta(
            seconds=getattr(settings, 'PAYMENT_ARRIVAL_TOLERANCE_SECONDS', 60))
        if booking.held_until is not None and (
            now > booking.held_until + tolerance
            or (
                now > booking.held_until
                and seats_taken(trip, now, exclude_booking_id=booking.pk)
                + booking.seats > trip.capacity
            )
        ):
            raise WalletPayRefused(
                'hold_expired', 'The time to hold this booking has run out.', 409)

        fields = {
            'amount': total, 'method': 'wallet', 'status': 'confirmed',
            'settlement_status': 'not_ready',
            # Clearing the reference turns a later success on an abandoned
            # checkout into an unmatched charge, which is refunded in full.
            'provider_reference': None, 'idempotency_key': None,
            'confirmed_at': now, 'refunded_at': None, 'refund_reference': None,
            'refund_status': 'not_requested', 'refund_reason': '',
            'paid_amount': total, 'refund_amount': None,
        }
        if payment is None:
            payment = Payment.objects.create(booking=booking, **fields)
        else:
            for name, value in fields.items():
                setattr(payment, name, value)
            payment.save(update_fields=list(fields))

        booking.status = 'confirmed'
        booking.save(update_fields=['status'])
        ensure_numbers(trip, booking, now=now)
        try:
            create_booking_hold(booking)
        except ValueError as exc:
            raise WalletPayRefused('hold_conflict', str(exc), 409)
        wallet_services.debit(user, total, 'spend', reference, booking=booking)
    return booking, payment, False
