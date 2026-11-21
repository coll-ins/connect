"""A refused incident refund puts the booking back only if its seat is still free."""
import unittest
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from bookings import services
from bookings.models import Incident, IncidentResolution
from bookings.services import RefundRejected
from bookings.tests.test_seat_holds import SeatBase


class IncidentRefundRestoreTests(SeatBase):
    capacity = 3

    def setUp(self):
        super().setUp()
        Incident.objects.create(
            trip=self.trip, incident_type='breakdown', description='engine',
            status='reported')
        self.mine = self.booking(2, 'confirmed', user=self.passenger)
        self.payment = self.digital_payment(self.mine, status='confirmed')
        self.client.force_authenticate(self.passenger)

    def resolve(self, side_effect):
        with mock.patch('bookings.services.execute_booking_refund',
                        side_effect=side_effect):
            return self.client.post(
                f'/api/bookings/{self.mine.id}/resolve-incident/',
                {'resolution': 'refund'}, format='json')

    def test_seat_still_free_restores_the_booking_and_reopens_the_choice(self):
        resp = self.resolve(RefundRejected('Paystack refused.'))
        self.assertEqual(resp.status_code, 409, resp.content)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, 'confirmed')
        self.assertFalse(IncidentResolution.objects.filter(booking=self.mine).exists())
        self.assertEqual(services.seats_taken(self.trip), 2)

    def test_seat_resold_during_the_refund_call_is_not_oversold(self):
        def refuse_after_seat_is_resold(claim):
            self.booking(2, 'confirmed')  # someone books the freed seats
            raise RefundRejected('Paystack refused.')

        with mock.patch('bookings.views._alert_payment_problem') as alert:
            resp = self.resolve(refuse_after_seat_is_resold)
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn('stays cancelled', resp.data['error'])
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, 'cancelled')
        self.assertLessEqual(services.seats_taken(self.trip), self.trip.capacity)
        self.assertEqual(services.seats_taken(self.trip), 2)
        resolution = IncidentResolution.objects.get(booking=self.mine)
        self.assertEqual(resolution.status, 'failed')
        alert.assert_called_once()

    @unittest.skipUnless(connection.vendor == 'postgresql', 'row locks need Postgres')
    def test_restore_locks_trip_before_booking(self):
        marks = []

        with CaptureQueriesContext(connection) as ctx:
            def refuse(claim):
                marks.append(len(ctx.captured_queries))  # the refund call splits the two transactions
                raise RefundRejected('Paystack refused.')

            self.resolve(refuse)
        after = [q['sql'] for q in ctx.captured_queries[marks[0]:] if 'FOR UPDATE' in q['sql']]
        tables = [
            'trip' if 'FROM "companies_trip"' in sql else 'booking'
            for sql in after if 'FROM "companies_trip"' in sql or 'FROM "bookings_booking"' in sql
        ]
        self.assertEqual(tables[:2], ['trip', 'booking'])
