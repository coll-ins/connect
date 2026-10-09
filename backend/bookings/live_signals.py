import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from math import asin, cos, radians, sin, sqrt

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _f(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _distance_km(a_lat, a_lng, b_lat, b_lng):
    if None in (a_lat, a_lng, b_lat, b_lng):
        return None
    dlat = radians(b_lat - a_lat)
    dlng = radians(b_lng - a_lng)
    h = (
        sin(dlat / 2) ** 2
        + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    )
    return round(6371.0 * 2 * asin(sqrt(h)), 2)


def location_freshness(driver, now=None):
    """Return server-authoritative GPS freshness; missing fixes are always stale."""
    now = now or timezone.now()
    try:
        threshold = max(1, int(getattr(settings, "LOCATION_STALE_SECONDS", 120)))
    except (TypeError, ValueError):
        threshold = 120

    if (
        driver is None
        or getattr(driver, "latitude", None) is None
        or getattr(driver, "longitude", None) is None
    ):
        return {"is_stale": True, "location_age_seconds": None}

    updated = getattr(driver, "location_updated_at", None)
    if updated is None:
        return {"is_stale": True, "location_age_seconds": None}
    try:
        age = max(0, int((now - updated).total_seconds()))
    except (TypeError, AttributeError):
        return {"is_stale": True, "location_age_seconds": None}
    return {"is_stale": age > threshold, "location_age_seconds": age}


def trip_is_live(trip, now=None):
    """A booking is trackable only while boarding/departed and within 12 hours."""
    now = now or timezone.now()
    if trip is None or str(getattr(trip, "status", "")).lower() not in {"boarding", "departed"}:
        return False
    departure = getattr(trip, "departure_at", None)
    if departure is None:
        return False
    try:
        return departure >= now - timedelta(hours=12)
    except TypeError:
        return False


def location_freshness_for_booking(booking_id):
    """Freshness and trip-live state for the passenger live-location response."""
    from bookings.models import Booking

    booking = (
        Booking.objects.select_related("driver", "trip")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        return {
            "is_stale": True,
            "location_age_seconds": None,
            "is_trip_live": False,
        }
    driver = booking.driver if getattr(booking, "driver_id", None) else None
    trip = getattr(booking, "trip", None)
    return {
        **location_freshness(driver),
        "is_trip_live": trip_is_live(trip),
    }


def _payload(booking, driver):
    p_lat = _f(booking.passenger_latitude)
    p_lng = _f(booking.passenger_longitude)
    d_lat = _f(driver.latitude) if driver else None
    d_lng = _f(driver.longitude) if driver else None
    updated = getattr(driver, "location_updated_at", None) if driver else None
    freshness = location_freshness(driver)
    trip = getattr(booking, "trip", None)

    return {
        "type": "location",
        "booking_id": booking.id,
        **freshness,
        "is_trip_live": trip_is_live(trip),
        "driver": {
            "latitude": d_lat,
            "longitude": d_lng,
            "location_updated_at": updated.isoformat() if updated else None,
            **freshness,
        },
        "passenger": {"latitude": p_lat, "longitude": p_lng},
        "distance_km": _distance_km(p_lat, p_lng, d_lat, d_lng),
    }


def _push(booking_id, payload):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            f"booking_live_{booking_id}",
            {"type": "live.update", "payload": payload},
        )
    except Exception:
        # A failed push must never break saving a location.
        logger.warning("Live push failed for booking %s", booking_id, exc_info=True)


def driver_saved(sender, instance, update_fields=None, **kwargs):
    if update_fields is not None and not ({"latitude", "longitude"} & set(update_fields)):
        return
    if instance.latitude is None or instance.longitude is None:
        return

    from .models import Booking

    for booking in Booking.objects.filter(
        driver_id=instance.id, status__in=["pending", "confirmed"]
    ):
        _push(booking.id, _payload(booking, instance))


def booking_saved(sender, instance, update_fields=None, **kwargs):
    if update_fields is None or not (
        {"passenger_latitude", "passenger_longitude"} & set(update_fields)
    ):
        return
    _push(instance.id, _payload(instance, instance.driver))
