from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from buses.models import Bus
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
            bus = None
            if sch.bus_id:
                bus = Bus.objects.select_for_update().get(pk=sch.bus_id)
                if not bus.is_active or bus.maintenance_status != 'operational':
                    return 'bus_unavailable'
                if bus.trips.filter(departure_at=dep, status__in=ACTIVE).exists():
                    return 'bus_conflict'
            if trip is None:
                Trip.objects.create(route=sch.route, driver=driver, bus=bus, departure_at=dep,
                                    capacity=sch.capacity, status='scheduled', schedule=sch)
                return 'created'
            trip.route, trip.driver, trip.bus, trip.capacity, trip.status = (
                sch.route, driver, bus, sch.capacity, 'scheduled')
            trip.save(update_fields=['route', 'driver', 'bus', 'capacity', 'status'])
            return 'revived'
    except IntegrityError:
        return 'existing'


def regenerate_for_schedule(sch, days=HORIZON_DAYS, revive=True):
    """Create or revive future trips for ONE schedule. Safe to re-run. Returns counts."""
    counts = {k: 0 for k in (
        'created', 'revived', 'existing', 'past', 'driver_unavailable', 'driver_conflict',
        'bus_unavailable', 'bus_conflict', 'invalid')}
    if not sch.is_active:
        counts['driver_unavailable'] = 0
        counts['driver_conflict'] = 0
        _save_generation_summary(sch, counts)
        return counts
    try:
        weekdays = sch.weekdays()
    except ValueError:
        weekdays = None
    if (not weekdays or any(w < 0 or w > 6 for w in weekdays)
            or not 1 <= sch.capacity <= 100
            or sch.route.company_id != sch.driver.company_id
            or sch.normal_interval_minutes < 15
            or sch.rush_interval_minutes < 15
            or sch.rush_interval_minutes > sch.normal_interval_minutes
            or ((sch.rush_start_time is None) != (sch.rush_end_time is None))
            or (sch.service_end_time is not None
                and sch.service_end_time <= sch.departure_time)
            or (sch.rush_start_time is not None
                and (sch.service_end_time is None
                     or sch.rush_start_time < sch.departure_time
                     or sch.rush_end_time <= sch.rush_start_time
                     or sch.rush_end_time > sch.service_end_time))
            or (not sch.auto_renew and
                (sch.start_date is None or sch.end_date is None
                 or (sch.end_date - sch.start_date).days > 6))):
        counts['invalid'] += 1
        _save_generation_summary(sch, counts)
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
        times = [sch.departure_time]
        if sch.service_end_time is not None:
            times = []

            def add_segment(start, end, interval, inclusive_end):
                current = datetime.combine(d, start)
                limit = datetime.combine(d, end)
                while current < limit or (inclusive_end and current == limit):
                    times.append(current.time())
                    current += timedelta(minutes=interval)

            if sch.rush_start_time is None:
                add_segment(
                    sch.departure_time, sch.service_end_time,
                    sch.normal_interval_minutes, True,
                )
            else:
                add_segment(
                    sch.departure_time, sch.rush_start_time,
                    sch.normal_interval_minutes, False,
                )
                add_segment(
                    sch.rush_start_time, sch.rush_end_time,
                    sch.rush_interval_minutes, False,
                )
                add_segment(
                    sch.rush_end_time, sch.service_end_time,
                    sch.normal_interval_minutes, True,
                )

        for departure_time in times:
            dep = timezone.make_aware(datetime.combine(d, departure_time), tz)
            if dep <= now:
                counts['past'] += 1
                continue
            counts[_slot(sch, dep, revive)] += 1
    _save_generation_summary(sch, counts)
    return counts


def _save_generation_summary(sch, counts):
    """Persist the latest skipped-departure counts for manager/operator review."""
    from .models import TripSchedule

    TripSchedule.objects.filter(pk=sch.pk).update(
        generation_checked_at=timezone.now(),
        driver_unavailable_count=counts['driver_unavailable'],
        driver_conflict_count=counts['driver_conflict'],
    )
