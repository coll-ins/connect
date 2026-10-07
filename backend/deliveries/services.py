import hmac
import re
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
            raise ParcelError(
                'This parcel is already paid. Refunds are not automated yet; contact support.', 409
            )
        raise ParcelError('This parcel can no longer be cancelled.', 409)


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
        if parcel.status != 'picked_up':
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
