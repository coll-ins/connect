"""Automatic departure detection from driver GPS movement."""
import logging
import math
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from notifications import push, sms

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
    """Drive the trip from the driver's real GPS, with no button to press:

    scheduled -> boarding when the bus reaches its first stage near departure time,
    boarding -> departed once two consecutive fixes are away from that stage,
    and riders hear when the bus passes the stage before theirs.

    Never raises: a failure here must not break saving the driver's location.
    """
    try:
        _auto_board(driver, new_lat, new_lng)
        _auto_depart(driver, prev_lat, prev_lng, new_lat, new_lng)
        _approach_alerts(driver, new_lat, new_lng)
    except Exception:
        logger.exception('auto-depart failed for driver %s', driver.pk)


def _riders(trip):
    from bookings.models import Booking

    return Booking.objects.filter(trip=trip, status='confirmed')


def _auto_board(driver, lat, lng):
    if None in (lat, lng):
        return
    from companies.models import Trip

    threshold = float(getattr(settings, 'AUTO_DEPART_DISTANCE_M', 150))
    lead = timedelta(minutes=int(getattr(settings, 'AUTO_DEPART_LEAD_MINUTES', 30)))
    now = timezone.now()
    with transaction.atomic():
        if Trip.objects.filter(driver=driver, status__in=('boarding', 'departed'),
                               departure_at__gte=now - timedelta(hours=12)).exists():
            return
        # Earliest trip in its window: up to `lead` early, or up to 2 h late.
        trip = (
            Trip.objects.select_for_update(of=('self',))
            .select_related('route')
            .filter(driver=driver, status='scheduled',
                    departure_at__lte=now + lead,
                    departure_at__gte=now - timedelta(hours=2))
            .order_by('departure_at', 'id')
            .first()
        )
        if trip is None:
            return
        point = _boarding_point(trip)
        if point is None or _metres(lat, lng, *point) > threshold:
            return
        trip.status = 'boarding'
        trip.save(update_fields=['status'])
        users = list(_riders(trip).values_list('user_id', flat=True))
        stage = _first_stage_name(trip)
        transaction.on_commit(lambda: push.notify_users(
            users, 'Your bus is boarding',
            f'{trip.route.name}: the bus is at {stage} and boarding now.',
            url='/passenger', tag=f'trip-{trip.id}-board'))


def _first_stage_name(trip):
    stage = trip.route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()
    return stage.name if stage else trip.route.start_point


def _auto_depart(driver, prev_lat, prev_lng, new_lat, new_lng):
    if None in (prev_lat, prev_lng, new_lat, new_lng):
        return
    from companies.models import Trip

    threshold = float(getattr(settings, 'AUTO_DEPART_DISTANCE_M', 150))
    lead = timedelta(
        minutes=int(getattr(settings, 'AUTO_DEPART_LEAD_MINUTES', 30))
    )

    with transaction.atomic():
        trip = (
            Trip.objects.select_for_update(of=('self',))
            .select_related('route')
            .filter(driver=driver, status='boarding',
                    departure_at__gte=timezone.now() - timedelta(hours=12))
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

        riders = list(_riders(trip).values_list('user_id', 'user__phone_number', 'booking_number'))
        route_name = trip.route.name
        stage = _first_stage_name(trip)

        def _notify():
            for _user, phone, number in riders:
                if phone:
                    sms.send_departure_sms(phone, number, route_name)
            push.notify_users(
                [r[0] for r in riders], 'Your bus has left',
                f'{route_name}: the bus left {stage}. Track it live in CONNECT.',
                url='/passenger', tag=f'trip-{trip.id}-depart')

        transaction.on_commit(_notify)


def _approach_alerts(driver, lat, lng):
    """Tell riders once, when the bus is at or past the stage before theirs."""
    if None in (lat, lng):
        return
    from companies.models import Trip

    radius = float(getattr(settings, 'APPROACH_STAGE_RADIUS_M', 150))
    trip = (
        Trip.objects.select_related('route')
        .filter(driver=driver, status='departed',
                departure_at__gte=timezone.now() - timedelta(hours=12))
        .order_by('-departure_at', '-id')
        .first()
    )
    if trip is None:
        return
    stages = list(trip.route.pickup_stages.filter(is_active=True).order_by('order', 'id'))
    if len(stages) < 3:
        return
    near = [s for s in stages[1:] if _metres(lat, lng, float(s.latitude), float(s.longitude)) <= radius]
    if not near:
        return
    passed = max(near, key=lambda s: (s.order, s.id))
    idx = stages.index(passed)
    upcoming = stages[idx + 1] if idx + 1 < len(stages) else None
    # Riders at this stage or the next one; earlier riders are on board or missed it.
    targets = [s.pk for s in stages[idx:idx + 2]]
    with transaction.atomic():
        due = list(
            _riders(trip).select_for_update()
            .filter(pickup_stage_id__in=targets, approach_alert_at__isnull=True)
            .values_list('id', 'user_id', 'pickup_stage_id')
        )
        if not due:
            return
        _riders(trip).filter(id__in=[d[0] for d in due]).update(approach_alert_at=timezone.now())

    for booking_id, user_id, stage_id in due:
        if upcoming is not None and stage_id == upcoming.pk:
            title = 'Get ready: your bus is next'
            body = f'The bus just passed {passed.name}. Your stage, {upcoming.name}, is next.'
        else:
            title = 'Your bus is at your stage'
            body = f'The bus is at {passed.name} now.'
        push.notify_users([user_id], title, body, url='/passenger', tag=f'booking-{booking_id}-near')
