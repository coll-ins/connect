from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Incident, IncidentResolution, Payment
from bookings.tests.test_round5 import _Fixture, _paystack_ok
from companies.models import Trip


class IncidentRefundTests(_Fixture, TransactionTestCase):
    """The incident path must never call Paystack inside a transaction."""

    def setUp(self):
        self.build('701')
        self.booking_obj, self.payment = self.booking(
            'confirmed', 'REF_INC', payment_status='confirmed', hold=True
        )
        Incident.objects.create(
            trip=self.trip, reported_by=self.passenger,
            incident_type='breakdown', description='Broke down.', status='reported',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.passenger)
        self.url = reverse(
            'bookings:resolve-incident-booking', kwargs={'booking_id': self.booking_obj.id}
        )

    def _refund(self):
        return self.client.post(self.url, {'resolution': 'refund'}, format='json')

    def test_refund_runs_outside_transaction(self):
        seen = []

        def fake_post(*args, **kwargs):
            seen.append(connection.in_atomic_block)
            return _paystack_ok(808)

        with patch('bookings.services.requests.post', side_effect=fake_post):
            response = self._refund()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(seen, [False])
        self.booking_obj.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'cancelled')
        self.assertEqual(self.payment.refund_status, 'pending')
        self.assertEqual(self.payment.refund_amount, Decimal('800.00'))
        self.assertTrue(IncidentResolution.objects.filter(
            booking=self.booking_obj, resolution='refund').exists())

    def test_rejection_restores_booking_and_allows_retry(self):
        rejected = MagicMock()
        rejected.status_code = 400
        rejected.json.return_value = {'status': False, 'message': 'Insufficient balance'}
        with patch('bookings.services.requests.post', return_value=rejected):
            response = self._refund()
        self.assertEqual(response.status_code, 409)
        self.booking_obj.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'confirmed')
        self.assertEqual(self.payment.refund_status, 'not_requested')
        self.assertEqual(IncidentResolution.objects.filter(booking=self.booking_obj).count(), 0)

        with patch('bookings.services.requests.post', return_value=_paystack_ok(809)):
            retry = self._refund()
        self.assertEqual(retry.status_code, 200, retry.data)

    def test_uncertain_outcome_stays_cancelled_and_never_resends(self):
        with patch('bookings.services.requests.post',
                   side_effect=requests.ConnectionError('timeout')) as post, \
                patch('bookings.views.send_admin_alert_sms'):
            response = self._refund()
            again = self._refund()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['refund_status'], 'processing')
        self.booking_obj.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'cancelled')
        self.assertEqual(self.payment.refund_status, 'processing')
        self.assertEqual(again.status_code, 400)
        post.assert_called_once()

    def test_unpaid_booking_cannot_be_rescheduled(self):
        Booking.objects.filter(pk=self.booking_obj.pk).update(status='pending')
        Payment.objects.filter(pk=self.payment.pk).update(status='pending')
        replacement = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=6), capacity=5,
        )
        response = self.client.post(
            self.url,
            {'resolution': 'reschedule', 'replacement_trip_id': replacement.id},
            format='json',
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.booking_obj.refresh_from_db()
        self.assertEqual(self.booking_obj.trip_id, self.trip.id)
        self.assertEqual(self.booking_obj.status, 'pending')
