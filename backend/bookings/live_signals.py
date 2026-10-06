import logging
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


def _payload(booking, driver):
    p_lat = _f(booking.passenger_latitude)
    p_lng = _f(booking.passenger_longitude)
    d_lat = _f(driver.latitude) if driver else None
    d_lng = _f(driver.longitude) if driver else None
    updated = getattr(driver, "location_updated_at", None) if driver else None

    return {
        "type": "location",
        "booking_id": booking.id,
        "driver": {
            "latitude": d_lat,
            "longitude": d_lng,
            "location_updated_at": updated.isoformat() if updated else None,
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
