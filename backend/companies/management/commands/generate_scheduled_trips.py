from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.utils import timezone

from companies.models import Trip, TripSchedule
from drivers.models import Driver

ACTIVE = ['scheduled', 'boarding', 'departed']


class Command(BaseCommand):
    help = 'Create Trips from active TripSchedules for the next N days. Safe to re-run.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)

    def handle(self, *args, **opts):
        days = max(1, min(opts['days'], 31))
        tz = timezone.get_current_timezone()
        now = timezone.now()
        today = now.astimezone(tz).date()
        counts = {k: 0 for k in (
            'created', 'existing', 'past', 'driver_unavailable', 'driver_conflict', 'invalid')}

        schedules = TripSchedule.objects.filter(is_active=True).select_related('route', 'driver')
        for sch in schedules:
            try:
                weekdays = sch.weekdays()
            except ValueError:
                weekdays = None
            if (not weekdays or any(w < 0 or w > 6 for w in weekdays)
                    or not 1 <= sch.capacity <= 100
                    or sch.route.company_id != sch.driver.company_id):
                counts['invalid'] += 1
                self.stderr.write(f'schedule {sch.pk} is invalid, skipped')
                continue
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
                counts[self._make(sch, dep)] += 1

        self.stdout.write('generate_scheduled_trips: ' + ', '.join(f'{k} {v}' for k, v in counts.items()))

    def _make(self, sch, dep):
        if Trip.objects.filter(schedule=sch, departure_at=dep).exists():
            return 'existing'
        try:
            with transaction.atomic():
                driver = Driver.objects.select_for_update().get(pk=sch.driver_id)
                if not driver.is_available:
                    return 'driver_unavailable'
                if Trip.objects.filter(driver=driver, departure_at=dep, status__in=ACTIVE).exists():
                    return 'driver_conflict'
                Trip.objects.create(
                    route=sch.route, driver=driver, departure_at=dep,
                    capacity=sch.capacity, status='scheduled', schedule=sch)
        except IntegrityError:
            return 'existing'
        return 'created'
