from django.core.management.base import BaseCommand

from companies.models import TripSchedule
from companies.trip_generation import regenerate_for_schedule

KEYS = ('created', 'existing', 'past', 'driver_unavailable', 'driver_conflict', 'invalid')


class Command(BaseCommand):
    help = 'Create Trips from active TripSchedules for the next N days. Safe to re-run.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)

    def handle(self, *args, **opts):
        days = max(1, min(opts['days'], 31))
        counts = {k: 0 for k in KEYS}
        schedules = TripSchedule.objects.filter(is_active=True).select_related('route', 'driver')
        for sch in schedules:
            # revive=False: a trip a manager cancelled is never recreated by the nightly run.
            g = regenerate_for_schedule(sch, days=days, revive=False)
            if g['invalid']:
                self.stderr.write(f'schedule {sch.pk} is invalid, skipped')
            for k in KEYS:
                counts[k] += g[k]
        self.stdout.write('generate_scheduled_trips: ' + ', '.join(f'{k} {v}' for k, v in counts.items()))
