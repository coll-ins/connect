import hmac
import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from companies.models import PickupStage, Trip
from users.views import normalize_phone_number

from .models import Parcel

MAX_UNPAID_PARCELS = 5
LIVE_TRIP_STATES = ('scheduled', 'boarding', 'departed')


class ParcelError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def create_parcel(*, sender, trip_id, pickup_stage_id, dropoff_stage_id, size,
                  description, receiver_name, receiver_phone):
    try:
        trip = Trip.objects.select_related('route__company', 'driver').get(id=trip_id)
    except Trip.DoesNotExist:
        raise ParcelError('Trip not found.', 404)

    if trip.status != 'scheduled' or trip.departure_at <= timezone.now():
        raise ParcelError('Parcels can only be booked on upcoming scheduled trips.')

    route = trip.route
    if trip.driver.company_id != route.company_id:
        raise ParcelError('This trip is not available for parcels.', 409)
    price = route.parcel_rate(size)
    if price is None or price <= 0:
        raise ParcelError('This route does not carry parcels of that size.')

    stages = {
        s.id: s
        for s in PickupStage.objects.filter(
            route=route, is_active=True,
            id__in=[pickup_stage_id, dropoff_stage_id],
        )
    }
    pickup = stages.get(pickup_stage_id)
    dropoff = stages.get(dropoff_stage_id)
    if pickup is None or dropoff is None:
        raise ParcelError('Pickup and drop-off must be active stages on this trip\'s route.')
    if pickup.order >= dropoff.order:
        raise ParcelError('Drop-off must come after pickup along the route.')

    phone = normalize_phone_number(receiver_phone)
    if not re.fullmatch(r'\+254\d{9}', phone or ''):
        raise ParcelError('Enter a valid Kenyan receiver phone number.')

    unpaid = Parcel.objects.filter(sender=sender, status='pending_payment').count()
    if unpaid >= MAX_UNPAID_PARCELS:
        raise ParcelError('Too many unpaid parcels. Pay or cancel existing ones first.', 429)

    return Parcel.objects.create(
        sender=sender,
        trip=trip,
        pickup_stage=pickup,
        dropoff_stage=dropoff,
        size=size,
        description=description.strip(),
        receiver_name=receiver_name.strip(),
        receiver_phone=phone,
        price=price,
    )


def mark_parcel_paid(*, parcel_id, amount, reference):
    """Called ONLY by the payment-confirmation path. Returns (parcel, changed)."""
    with transaction.atomic():
        parcel = Parcel.objects.select_for_update().get(id=parcel_id)
        if parcel.status == 'paid' and parcel.provider_reference == reference:
            return parcel, False
        if parcel.status != 'pending_payment':
            raise ParcelError('Parcel is not awaiting payment.', 409)
        if Decimal(str(amount)) != parcel.price:
            raise ParcelError('Paid amount does not match the parcel price.', 409)
        parcel.status = 'paid'
        parcel.provider_reference = reference
        parcel.paid_at = timezone.now()
        parcel.save(update_fields=['status', 'provider_reference', 'paid_at', 'updated_at'])
        return parcel, True


def cancel_parcel(*, parcel_id, user):
    with transaction.atomic():
        parcel = Parcel.objects.select_for_update().get(id=parcel_id)
        if parcel.sender_id != user.id:
            raise Parcel.DoesNotExist
        if parcel.status == 'pending_payment':
            parcel.status = 'cancelled'
            parcel.cancelled_at = timezone.now()
            parcel.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            return parcel
        if parcel.status == 'paid':
            # Nothing has been picked up yet: refund the full price. The refund
            # is queued in this transaction and sent by process_unapplied
            # (never from inside a transaction).
            if not parcel.provider_reference:
                raise ParcelError(
                    'This parcel has no payment reference; contact support for a refund.', 409
                )
            parcel.status = 'cancelled'
            parcel.cancelled_at = timezone.now()
            parcel.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            _queue_parcel_refund(parcel, 'Customer cancelled before pickup; full refund.')
            return parcel
        raise ParcelError('This parcel can no longer be cancelled.', 409)


def _queue_parcel_refund(parcel, reason):
    """Queue a full refund for process_unapplied. Call inside the transaction
    that changed the parcel's status, with the parcel row locked."""
    from bookings.models import UnappliedPayment

    row, created = UnappliedPayment.objects.select_for_update().get_or_create(
        reference=parcel.provider_reference,
        defaults={
            'kind': 'parcel',
            'amount': parcel.price,
            'currency': 'KES',
            'reason': reason,
            'payload': {},
            'status': 'refund_due',
        },
    )
    # A row left by an earlier failed-then-applied charge must not
    # swallow this refund; one already refunding/refunded is final.
    if not created and row.status in ('retry', 'review', 'applied'):
        row.status = 'refund_due'
        row.amount = parcel.price
        row.reason = reason
        row.save(update_fields=['status', 'amount', 'reason'])


STALE_DEPARTED = timedelta(hours=12)
UNDELIVERED_ALERT_AFTER = timedelta(hours=48)


def settle_stale_parcels(now=None):
    """
    Sweep parcels whose trip is over, whatever ended it (cancel, close,
    simulation). Idempotent; run by process_unapplied every 5 minutes.
    - paid, trip cancelled: cancelled + full refund.
    - paid, never picked up, trip completed (or departed 12h+ ago): expired +
      full refund (the parcel never left the sender).
    - unpaid, trip gone: expired (no money involved).
    - picked up, trip over 48h+ ago, not delivered: failed_delivery + admin
      alert. No automatic refund: the goods are with the driver, and the
      driver can still complete the hand-over with the PIN.
    Returns (refunded, failed_deliveries).
    """
    from django.db.models import Q

    now = now or timezone.now()
    trip_over = Q(trip__status__in=('completed', 'cancelled')) | Q(
        trip__status='departed', trip__departure_at__lte=now - STALE_DEPARTED)

    # Unpaid parcels whose trip can no longer take them: expire, so they stop
    # counting towards MAX_UNPAID_PARCELS. A payment that still lands is
    # refunded automatically (mark_parcel_paid refuses it with a 409).
    Parcel.objects.filter(status='pending_payment').filter(
        Q(trip__status__in=('departed', 'completed', 'cancelled'))
        | Q(trip__departure_at__lte=now)
    ).update(status='expired', updated_at=now)

    refunded = 0
    for pk in Parcel.objects.filter(trip_over, status='paid').values_list('pk', flat=True):
        with transaction.atomic():
            parcel = Parcel.objects.select_for_update().select_related('trip').get(pk=pk)
            if parcel.status != 'paid':
                continue
            if parcel.trip.status == 'cancelled':
                parcel.status, reason = 'cancelled', 'Trip cancelled; full refund.'
                parcel.cancelled_at = now
            else:
                parcel.status, reason = 'expired', 'Parcel never picked up; full refund.'
            parcel.save(update_fields=['status', 'cancelled_at', 'updated_at'])
            if parcel.provider_reference:
                _queue_parcel_refund(parcel, reason)
            else:
                transaction.on_commit(lambda c=parcel.tracking_code: _alert(
                    f'Parcel {c} was paid but has no payment reference: refund manually.'))
            refunded += 1

    failed = 0
    stuck = Parcel.objects.filter(
        trip_over, status='picked_up', picked_up_at__lte=now - UNDELIVERED_ALERT_AFTER,
    ).values_list('pk', flat=True)
    for pk in stuck:
        if Parcel.objects.filter(pk=pk, status='picked_up').update(
                status='failed_delivery', updated_at=now):
            code = Parcel.objects.values_list('tracking_code', flat=True).get(pk=pk)
            _alert(f'Parcel {code} was picked up 48h+ ago and never delivered. Follow up with the driver.')
            failed += 1
    return refunded, failed


def _alert(message):
    try:
        from notifications.sms import send_admin_alert_sms
        send_admin_alert_sms(message)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Admin alert failed: %s', message)


def pick_up(*, parcel_id, driver):
    with transaction.atomic():
        parcel = Parcel.objects.select_for_update().get(id=parcel_id)
        if parcel.trip.driver_id != driver.id:
            raise ParcelError('Parcel not found.', 404)
        if parcel.status != 'paid':
            raise ParcelError('Only paid parcels can be picked up.', 409)
        if parcel.trip.status not in LIVE_TRIP_STATES:
            raise ParcelError('This trip is no longer active.', 409)
        parcel.status = 'picked_up'
        parcel.picked_up_at = timezone.now()
        parcel.save(update_fields=['status', 'picked_up_at', 'updated_at'])
        return parcel


def deliver(*, parcel_id, driver, pin):
    with transaction.atomic():
        parcel = Parcel.objects.select_for_update().get(id=parcel_id)
        if parcel.trip.driver_id != driver.id:
            raise ParcelError('Parcel not found.', 404)
        # failed_delivery: flagged late, but the driver may still hand it over.
        if parcel.status not in ('picked_up', 'failed_delivery'):
            raise ParcelError('Only picked-up parcels can be delivered.', 409)
        if parcel.pin_attempts >= Parcel.MAX_PIN_ATTEMPTS:
            raise ParcelError('Too many wrong PIN attempts. Contact support.', 423)

        if hmac.compare_digest(str(pin), parcel.handover_pin):
            parcel.status = 'delivered'
            parcel.delivered_at = timezone.now()
            parcel.save(update_fields=['status', 'delivered_at', 'updated_at'])
            return parcel

        parcel.pin_attempts += 1
        parcel.save(update_fields=['pin_attempts', 'updated_at'])
        remaining = Parcel.MAX_PIN_ATTEMPTS - parcel.pin_attempts

    raise ParcelError(f'Incorrect PIN. {remaining} attempt(s) left.', 400)
