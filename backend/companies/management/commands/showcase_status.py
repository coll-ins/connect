"""READ-ONLY: live view of the showcase trip, to compare with what the phone shows."""
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from companies.models import Trip


def mask(phone):
    phone = phone or ''
    return phone[:7] + '***' + phone[-2:] if len(phone) > 9 else '***'


class Command(BaseCommand):
    help = 'READ-ONLY: show the live state of the showcase trip.'

    def add_arguments(self, parser):
        parser.add_argument('--trip', type=int)
        parser.add_argument('--watch', action='store_true', help='Refresh every 3 seconds.')

    def handle(self, *args, **opts):
        while True:
            trips = Trip.objects.select_related('route', 'driver')
            demo = trips.filter(driver__bus_number__startswith='DEMO')
            trip = (
                trips.filter(pk=opts['trip']).first() if opts['trip']
                else (
                    demo.filter(status='boarding').order_by('-id').first()
                    or demo.filter(status='departed').order_by('-id').first()
                    or demo.order_by('-id').first()
                )
            )
            if trip is None:
                raise CommandError('No trip found. Run seed_demo, or pass --trip ID.')
            if opts['watch']:
                self.stdout.write('\033[2J\033[H', ending='')
            self._show(trip)
            if not opts['watch']:
                return
            try:
                time.sleep(3)
            except KeyboardInterrupt:
                return

    def _show(self, trip):
        from django.db.models import Sum
        from bookings.live_signals import location_freshness
        from bookings.models import Booking

        driver = trip.driver
        stage = trip.route.pickup_stages.filter(is_active=True).order_by('order', 'id').first()
        taken = (
            trip.bookings.exclude(status='cancelled').aggregate(t=Sum('seats'))['t'] or 0
        )
        fresh = location_freshness(driver)
        age = fresh['location_age_seconds']
        gps = (
            'no GPS yet' if driver.latitude is None else
            f'({driver.latitude:.5f}, {driver.longitude:.5f})'
        )
        self.stdout.write(
            f'TRIP {trip.id} | {trip.route.name} | status: {trip.status.upper()}\n'
            f'Boarding stage: {stage.name if stage else "NONE"} | seats {taken}/{trip.capacity}\n'
            f'BUS {driver.bus_number} | GPS {gps} | '
            f'{"STALE" if fresh["is_stale"] else "FRESH"}'
            f'{f" ({age}s old)" if age is not None else ""}\n'
            f'Time now: {timezone.localtime().strftime("%H:%M:%S")}\n'
            f'{"-" * 70}')
        rows = Booking.objects.filter(trip=trip).select_related('user', 'pickup_stage').order_by('id')
        if not rows:
            self.stdout.write('No bookings yet.')
        for b in rows:
            pay = (f'{b.payment.method}/{b.payment.status}' if hasattr(b, 'payment') else 'no payment')
            boarded = 'BOARDED' if hasattr(b, 'boarding_event') else 'not boarded'
            pickup = b.pickup_stage.name if b.pickup_stage else b.pickup_location
            self.stdout.write(
                f'{b.booking_number} | {mask(b.user.phone_number)} | {b.seats} seat(s) | '
                f'pickup: {pickup} | booking: {b.status} | pay: {pay} | {boarded}')
