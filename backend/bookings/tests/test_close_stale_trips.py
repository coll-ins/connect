from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from bookings.models import Booking, Incident
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class CloseStaleTripsCommandTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Stale Trip SACCO',
            description='Test company',
            areas_served='Nairobi',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='Test Route',
            start_point='CBD',
            end_point='Westlands',
            price=Decimal('800.00'),
        )
        self.driver = Driver.objects.create(
            company=self.company,
            name='Test Driver',
            phone_number='0700000011',
            bus_number='KAA 001A',
        )
        self.passenger = User.objects.create_user(
            username='stale_trip_passenger',
            password='Test-password-123',
            phone_number='+254700000011',
        )

    def make_trip(self, *, status='departed', hours_ago=13):
        return Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() - timedelta(hours=hours_ago),
            capacity=14,
            status=status,
        )

    def make_booking(self, trip, status):
        return Booking.objects.create(
            user=self.passenger,
            route=self.route,
            driver=self.driver,
            trip=trip,
            pickup_location='CBD',
            total_amount=Decimal('800.00'),
            status=status,
        )

    def run_command(self, *args):
        out = StringIO()
        call_command('close_stale_trips', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_splits_closable_from_review_without_changes(self):
        closable = self.make_trip()
        pending = self.make_booking(closable, 'pending')
        review = self.make_trip()
        confirmed = self.make_booking(review, 'confirmed')

        output = self.run_command('--dry-run')

        for obj in (closable, review, pending, confirmed):
            obj.refresh_from_db()
        self.assertEqual(closable.status, 'departed')
        self.assertEqual(review.status, 'departed')
        self.assertEqual(pending.status, 'pending')
        self.assertEqual(confirmed.status, 'confirmed')
        self.assertIn('1 trip(s) would close', output)
        self.assertIn('1 need manual review', output)
        self.assertIn(f'Would close: {closable.pk}', output)
        self.assertIn(f'Needs review: {review.pk}', output)
        self.assertIn('no changes made', output)

    def test_stale_trip_without_bookings_is_closed(self):
        trip = self.make_trip()

        output = self.run_command()

        trip.refresh_from_db()
        self.assertEqual(trip.status, 'completed')
        self.assertIn('closed 1 trip(s)', output)

    def test_pending_bookings_are_cancelled_and_counted(self):
        trip = self.make_trip()
        p1 = self.make_booking(trip, 'pending')
        p2 = self.make_booking(trip, 'pending')

        output = self.run_command()

        trip.refresh_from_db()
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(trip.status, 'completed')
        self.assertEqual(p1.status, 'cancelled')
        self.assertEqual(p2.status, 'cancelled')
        self.assertIn('cancelled 2 pending booking(s)', output)

    @patch('bookings.services.claim_booking_refund')
    def test_confirmed_booking_leaves_trip_open_with_no_penalty(self, claim):
        trip = self.make_trip()
        confirmed = self.make_booking(trip, 'confirmed')

        output = self.run_command()

        trip.refresh_from_db()
        confirmed.refresh_from_db()
        self.passenger.refresh_from_db()
        self.assertEqual(trip.status, 'departed')
        self.assertEqual(confirmed.status, 'confirmed')
        self.assertEqual(self.passenger.no_show_count, 0)
        claim.assert_not_called()
        self.assertIn('left 1 trip(s) for manual review', output)
        self.assertIn(str(trip.pk), output)

    @patch('bookings.services.claim_booking_refund')
    def test_mixed_trip_is_left_untouched(self, claim):
        trip = self.make_trip()
        confirmed = self.make_booking(trip, 'confirmed')
        pending = self.make_booking(trip, 'pending')

        self.run_command()

        trip.refresh_from_db()
        confirmed.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(trip.status, 'departed')
        self.assertEqual(confirmed.status, 'confirmed')
        self.assertEqual(pending.status, 'pending')
        claim.assert_not_called()

    def test_limit_caps_closed_trips_per_run(self):
        trips = [self.make_trip() for _ in range(3)]

        output = self.run_command('--limit', '2')

        statuses = []
        for t in trips:
            t.refresh_from_db()
            statuses.append(t.status)
        self.assertEqual(statuses, ['completed', 'completed', 'departed'])
        self.assertIn('closed 2 trip(s)', output)

    def test_review_trips_do_not_consume_the_limit(self):
        review = self.make_trip()
        self.make_booking(review, 'confirmed')
        empty = self.make_trip()

        self.run_command('--limit', '1')

        review.refresh_from_db()
        empty.refresh_from_db()
        self.assertEqual(review.status, 'departed')
        self.assertEqual(empty.status, 'completed')

    def test_repeated_runs_are_idempotent(self):
        trip = self.make_trip()
        pending = self.make_booking(trip, 'pending')

        self.run_command()
        second = self.run_command()

        trip.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(trip.status, 'completed')
        self.assertEqual(pending.status, 'cancelled')
        self.assertIn('closed 0 trip(s)', second)

    def test_active_incident_prevents_automatic_trip_closure(self):
        trip = self.make_trip()
        booking = self.make_booking(trip, 'confirmed')
        Incident.objects.create(
            trip=trip,
            incident_type='breakdown',
            description='Needs company review.',
            status='investigating',
        )

        self.run_command()

        trip.refresh_from_db()
        booking.refresh_from_db()
        self.passenger.refresh_from_db()
        self.assertEqual(trip.status, 'departed')
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(self.passenger.no_show_count, 0)

    def test_recent_or_non_departed_trips_are_not_closed(self):
        recent = self.make_trip(hours_ago=11)
        scheduled = self.make_trip(status='scheduled', hours_ago=20)

        self.run_command('--older-than-hours', '12')

        recent.refresh_from_db()
        scheduled.refresh_from_db()
        self.assertEqual(recent.status, 'departed')
        self.assertEqual(scheduled.status, 'scheduled')

    def test_non_positive_age_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError, '--older-than-hours must be at least 1.'
        ):
            call_command('close_stale_trips', '--older-than-hours', '0')

    def test_non_positive_limit_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError, '--limit must be at least 1.'
        ):
            call_command('close_stale_trips', '--limit', '0')
