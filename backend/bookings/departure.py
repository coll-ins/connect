"""Automatic departure detection from driver GPS movement."""
import logging
import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications import sms

logger = logging.getLogger(__name__)


def _metres(a_lat, a_lng, b_lat, b_lng):
    dlat = math.radians(b_lat - a_lat)
    dlng = math.radians(b_lng - a_lng)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(a_lat))
        * math.cos(math.radians(b_lat))
        * math.sin(dlng / 2) ** 2
    )
    return 6371000.0 * 2 * math.asin(math.sqrt(h))


def _boarding_point(trip):
    stage = (
        trip.route.pickup_stages.filter(is_active=True)
        .order_by('order', 'id').first()
    )
    if stage is not None:
        return float(stage.latitude), float(stage.longitude)
    route = trip.route
    if route.start_latitude is not None and route.start_longitude is not None:
        return float(route.start_latitude), float(route.start_longitude)
    return None


def auto_depart_on_movement(driver, prev_lat, prev_lng, new_lat, new_lng):
    """Boarding -> departed once two consecutive fixes are away from the stage.

    Never raises: a failure here must not break saving the driver's location.
    """
    try:
        _auto_depart(driver, prev_lat, prev_lng, new_lat, new_lng)
    except Exception:
        logger.exception('auto-depart failed for driver %s', driver.pk)


def _auto_depart(driver, prev_lat, prev_lng, new_lat, new_lng):
    if None in (prev_lat, prev_lng, new_lat, new_lng):
        return
    from bookings.models import Booking
    from companies.models import Trip

    threshold = float(getattr(settings, 'AUTO_DEPART_DISTANCE_M', 150))
    lead = timedelta(
        minutes=int(getattr(settings, 'AUTO_DEPART_LEAD_MINUTES', 30))
    )

    with transaction.atomic():
        trip = (
            Trip.objects.select_for_update(of=('self',))
            .select_related('route')
            .filter(driver=driver, status='boarding')
            .order_by('departure_at', 'id')
            .first()
        )
        if trip is None:
            return
        if trip.departure_at > timezone.now() + lead:
            return
        point = _boarding_point(trip)
        if point is None:
            return
        if min(
            _metres(prev_lat, prev_lng, *point),
            _metres(new_lat, new_lng, *point),
        ) <= threshold:
            return

        trip.status = 'departed'
        trip.save(update_fields=['status'])

        recipients = list(
            Booking.objects.filter(trip=trip, status='confirmed')
            .values_list('user__phone_number', 'booking_number')
        )
        route_name = trip.route.name

        def _notify():
            for phone, number in recipients:
                if phone:
                    sms.send_departure_sms(phone, number, route_name)

        transaction.on_commit(_notify)
