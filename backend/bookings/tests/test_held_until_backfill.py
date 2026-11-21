"""Migration 0027 stamps held_until on pending bookings that already exist."""
import datetime as dt

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from companies.models import Company, Route, Trip
from drivers.models import Driver
from users.models import CustomUser

BEFORE = [('bookings', '0029_booking_held_until')]
AFTER = [('bookings', '0030_backfill_held_until')]
MIN = dt.timedelta(minutes=1)


class BackfillHeldUntilTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the schema fully migrated for the tests that run after this.
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_pending_rows_get_a_hold(self):
        apps = self.migrate(BEFORE)
        # Only Booking and Payment change shape here; the rest are the real
        # models, so their later (unrelated) migrations do not matter.
        Booking = apps.get_model('bookings', 'Booking')
        Payment = apps.get_model('bookings', 'Payment')

        now = timezone.now()
        user = CustomUser.objects.create(username='old', phone_number='+254711000001')
        company = Company.objects.create(name='Old Co', areas_served='x')
        route = Route.objects.create(company=company, name='R', start_point='a',
                                     end_point='b', price=100)
        driver = Driver.objects.create(name='D', phone_number='+254711000002',
                                       bus_number='K1', company=company)
        far = Trip.objects.create(route=route, driver=driver, capacity=10,
                                  status='scheduled', departure_at=now + dt.timedelta(hours=5))
        soon = Trip.objects.create(route=route, driver=driver, capacity=10,
                                   status='scheduled', departure_at=now + 5 * MIN)

        def make(status, age_min, trip, cash=False):
            b = Booking.objects.create(
                user_id=user.pk, route_id=route.pk,
                trip_id=trip.pk if trip else None, status=status, seats=1,
                total_amount=100, pickup_location='x')
            Booking.objects.filter(pk=b.pk).update(created_at=now - age_min * MIN)
            if cash:
                Payment.objects.create(booking_id=b.pk, amount=100, method='cash',
                                       status='pending')
            return b.pk

        digital = make('pending', 3, far)
        cash = make('pending', 3, far, cash=True)
        stale = make('pending', 45, far)
        stale_cash = make('pending', 45, far, cash=True)
        capped = make('pending', 0, soon)
        no_trip = make('pending', 3, None)
        confirmed = make('confirmed', 3, far)

        apps = self.migrate(AFTER)
        Booking = apps.get_model('bookings', 'Booking')
        held = {k: Booking.objects.get(pk=pk).held_until for k, pk in dict(
            digital=digital, cash=cash, stale=stale, stale_cash=stale_cash,
            capped=capped, no_trip=no_trip, confirmed=confirmed).items()}
        created = {pk: Booking.objects.get(pk=pk).created_at
                   for pk in (digital, cash, no_trip)}

        self.assertEqual(held['digital'], created[digital] + 10 * MIN)
        self.assertEqual(held['cash'], created[cash] + 20 * MIN)
        self.assertEqual(held['no_trip'], created[no_trip] + 10 * MIN)
        self.assertEqual(
            held['capped'],
            Trip.objects.get(pk=soon.pk).departure_at)
        for key in ('stale', 'stale_cash'):
            self.assertAlmostEqual(
                (held[key] - timezone.now()).total_seconds(), 120, delta=10, msg=key)
        self.assertIsNone(held['confirmed'])

    def test_migration_reverses(self):
        self.migrate(AFTER)
        apps = self.migrate([('bookings', '0025_boardingevent_walkin_method')])
        self.assertNotIn(
            'held_until', [f.name for f in apps.get_model('bookings', 'Booking')._meta.fields])
