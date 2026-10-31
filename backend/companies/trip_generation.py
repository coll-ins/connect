from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from drivers.models import Driver

from .models import Trip

ACTIVE = ['scheduled', 'boarding', 'departed']
HORIZON_DAYS = 7


def _slot(sch, dep, revive=True):
    """Create the trip for one slot; with revive=True also revive an empty cancelled one."""
    if not revive and Trip.objects.filter(schedule=sch, departure_at=dep).exists():
        return 'existing'
    try:
        with transaction.atomic():
            driver = Driver.objects.select_for_update().get(pk=sch.driver_id)
            trip = Trip.objects.select_for_update().filter(schedule=sch, departure_at=dep).first()
            if trip is not None and (
                    trip.status != 'cancelled' or trip.bookings.exists() or trip.parcels.exists()):
                return 'existing'
            if not driver.is_available:
                return 'driver_unavailable'
            if Trip.objects.filter(driver=driver, departure_at=dep, status__in=ACTIVE).exists():
                return 'driver_conflict'
            if trip is None:
                Trip.objects.create(route=sch.route, driver=driver, departure_at=dep,
                                    capacity=sch.capacity, status='scheduled', schedule=sch)
                return 'created'
            trip.route, trip.driver, trip.capacity, trip.status = sch.route, driver, sch.capacity, 'scheduled'
            trip.save(update_fields=['route', 'driver', 'capacity', 'status'])
            return 'revived'
    except IntegrityError:
        return 'existing'


def regenerate_for_schedule(sch, days=HORIZON_DAYS, revive=True):
    """Create or revive future trips for ONE schedule. Safe to re-run. Returns counts."""
    counts = {k: 0 for k in (
        'created', 'revived', 'existing', 'past', 'driver_unavailable', 'driver_conflict', 'invalid')}
    if not sch.is_active:
        return counts
    try:
        weekdays = sch.weekdays()
    except ValueError:
        weekdays = None
    if (not weekdays or any(w < 0 or w > 6 for w in weekdays)
            or not 1 <= sch.capacity <= 100
            or sch.route.company_id != sch.driver.company_id):
        counts['invalid'] += 1
        return counts
    tz = timezone.get_current_timezone()
    now = timezone.now()
    today = now.astimezone(tz).date()
    for offset in range(days):
        d = today + timedelta(days=offset)
        if d.weekday() not in weekdays:
            continue
        if sch.start_date and d < sch.start_date:
            continue
        if sch.end_date and d > sch.end_date:
            continue
        dep = timezone.make_aware(datetime.combine(d, sch.departure_time), tz)
        if dep <= now:
            counts['past'] += 1
            continue
        counts[_slot(sch, dep, revive)] += 1
    return counts
