import hashlib
import hmac
import io
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from bookings.models import Booking, BookingHold, Payment
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


def _paystack_ok(refund_id=111, status='pending'):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        'status': True,
        'data': {'id': refund_id, 'status': status},
    }
    return response


class _Fixture:
    """One company, one 800.00 route, one trip, one passenger."""

    def build(self, suffix, departure_hours=3, trip_status='scheduled'):
        self.company = Company.objects.create(name=f'R5 Co {suffix}')
        self.driver = Driver.objects.create(
            company=self.company,
            name='R5 Driver',
            phone_number=f'+254711000{suffix}',
            bus_number='KAA 555R',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='R5 Route',
            price=Decimal('800.00'),
        )
        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=departure_hours),
            capacity=5,
            status=trip_status,
        )
        self.passenger = User.objects.create_user(
            username=f'r5_pass_{suffix}',
            password='password123',
            phone_number=f'+254722000{suffix}',
        )

    def booking(self, booking_status, ref, payment_status='pending', hold=False):
        booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            booking_number='BK' + uuid.uuid4().hex[:8],
            total_amount=Decimal('800.00'),
            status=booking_status,
        )
        payment = Payment.objects.create(
            booking=booking,
            provider_reference=ref,
            amount=Decimal('800.00'),
            method='digital',
            status=payment_status,
        )
        if hold:
            BookingHold.objects.create(
                booking=booking, amount=Decimal('800.00'), status='held'
            )
        return booking, payment


class LatePaymentTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('101')

    def _webhook(self, payload):
        body = json.dumps(payload).encode()
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512
        ).hexdigest()
        return self.client.post(
            reverse('bookings:paystack-webhook'),
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

    @staticmethod
    def _charge(ref, amount=80000, currency='KES'):
        return {
            'event': 'charge.success',
            'data': {'reference': ref, 'amount': amount, 'currency': currency},
        }

    def test_normal_payment_confirms_booking_and_creates_hold(self):
        booking, payment = self.booking('pending', 'REF_OK')
        self.assertEqual(self._webhook(self._charge('REF_OK')).status_code, 200)
        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(payment.status, 'confirmed')
        self.assertTrue(BookingHold.objects.filter(booking=booking).exists())

    @patch('bookings.services.requests.post')
    def test_payment_for_cancelled_booking_is_refunded_not_revived(self, mock_post):
        mock_post.return_value = _paystack_ok(321)
        booking, payment = self.booking('cancelled', 'REF_DEAD')

        self.assertEqual(self._webhook(self._charge('REF_DEAD')).status_code, 200)

        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertFalse(BookingHold.objects.filter(booking=booking).exists())
        self.assertEqual(payment.refund_status, 'pending')
        self.assertEqual(payment.refund_amount, Decimal('800.00'))
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs['json']['amount'], 80000)

    def test_amount_mismatch_fails_payment_and_alerts_admin(self):
        booking, payment = self.booking('pending', 'REF_BAD_AMT')
        with patch('bookings.views.send_admin_alert_sms') as alert, \
                self.captureOnCommitCallbacks(execute=True):
            response = self._webhook(self._charge('REF_BAD_AMT', amount=50000))
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'failed')
        alert.assert_called_once()

    def test_unknown_reference_alerts_admin(self):
        with patch('bookings.views.send_admin_alert_sms') as alert:
            response = self._webhook(self._charge('NO_SUCH_REF'))
        self.assertEqual(response.status_code, 200)
        alert.assert_called_once()

    @patch('bookings.services.requests.post')
    @patch('bookings.views.requests.get')
    def test_verify_after_departure_refunds_instead_of_confirming(self, mock_get, mock_post):
        self.trip.departure_at = timezone.now() - timezone.timedelta(hours=1)
        self.trip.save(update_fields=['departure_at'])
        booking, payment = self.booking('pending', 'REF_VERIFY')

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': True,
            'data': {'status': 'success', 'amount': 80000},
        }
        mock_post.return_value = _paystack_ok(555)

        self.client.force_authenticate(user=self.passenger)
        url = reverse('bookings:verify-paystack-payment', kwargs={'booking_id': booking.id})
        response = self.client.post(url)
        if response.status_code == 405:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)

        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertFalse(BookingHold.objects.filter(booking=booking).exists())
        self.assertEqual(payment.refund_status, 'pending')
        mock_post.assert_called_once()

    def test_mark_payment_confirmed_is_idempotent(self):
        from bookings.views import _mark_payment_confirmed

        booking, payment = self.booking('pending', 'REF_IDEM')
        for _ in range(2):
            with transaction.atomic():
                locked = (
                    Payment.objects.select_for_update()
                    .select_related('booking').get(pk=payment.pk)
                )
                self.assertTrue(_mark_payment_confirmed(locked, 80000))
        self.assertEqual(BookingHold.objects.filter(booking=booking).count(), 1)

    @patch('bookings.views.requests.post')
    def test_callback_url_must_stay_on_our_frontend(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://paystack.test/pay', 'reference': 'X'},
        }
        booking = Booking.objects.create(
            user=self.passenger, route=self.route, trip=self.trip,
            booking_number='BK' + uuid.uuid4().hex[:8],
            total_amount=Decimal('800.00'), status='pending',
        )
        self.client.force_authenticate(user=self.passenger)
        url = reverse('bookings:initialize-paystack-payment', kwargs={'booking_id': booking.id})

        self.client.post(url, {'callback_url': 'https://evil.example/phish'}, format='json')
        sent = mock_post.call_args.kwargs['json']['callback_url']
        self.assertTrue(sent.startswith(settings.FRONTEND_URL.rstrip('/')), sent)
        self.assertNotIn('evil.example', sent)


class RefundOutcomeTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('301')
        self.booking_obj, self.payment = self.booking(
            'confirmed', 'REF_OUT', payment_status='confirmed', hold=True
        )
        self.client.force_authenticate(user=self.passenger)
        self.url = reverse(
            'bookings:cancel-booking', kwargs={'booking_id': self.booking_obj.id}
        )

    def _cancel(self):
        return self.client.post(self.url, {'fault_party': 'passenger'}, format='json')

    def test_definitive_rejection_restores_booking_and_allows_retry(self):
        rejected = MagicMock()
        rejected.status_code = 400
        rejected.json.return_value = {'status': False, 'message': 'Insufficient balance'}

        with patch('bookings.services.requests.post', return_value=rejected):
            response = self._cancel()
        self.assertEqual(response.status_code, 409)
        self.booking_obj.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'confirmed')
        self.assertEqual(self.payment.refund_status, 'not_requested')

        with patch('bookings.services.requests.post', return_value=_paystack_ok()) as mock_post:
            response = self._cancel()
        self.assertEqual(response.status_code, 200, response.data)
        self.booking_obj.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'cancelled')
        self.assertEqual(self.payment.refund_status, 'pending')
        self.assertEqual(self.payment.refund_amount, Decimal('400.00'))
        self.assertEqual(
            BookingHold.objects.get(booking=self.booking_obj).refunded_amount,
            Decimal('400.00'),
        )
        mock_post.assert_called_once()

    def test_uncertain_outcome_keeps_refund_processing_and_never_resends(self):
        with patch(
            'bookings.services.requests.post',
            side_effect=requests.ConnectionError('timeout'),
        ) as mock_post, patch('bookings.views.send_admin_alert_sms'):
            response = self._cancel()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['refund_status'], 'processing')

            self.booking_obj.refresh_from_db()
            self.payment.refresh_from_db()
            self.assertEqual(self.booking_obj.status, 'cancelled')
            self.assertEqual(self.payment.refund_status, 'processing')
            self.assertEqual(self.payment.refund_amount, Decimal('400.00'))

            # Cancelling again must not reach Paystack a second time.
            again = self._cancel()
            self.assertEqual(again.status_code, 400)
            mock_post.assert_called_once()


class NoPaystackCallInsideTransactionTests(_Fixture, TransactionTestCase):
    """Paystack must never be called while a database transaction is open."""

    def _spy(self):
        seen = []

        def fake_post(*args, **kwargs):
            seen.append(connection.in_atomic_block)
            return _paystack_ok()

        return seen, fake_post

    def test_cancel(self):
        self.build('201')
        booking, payment = self.booking(
            'confirmed', 'REF_C', payment_status='confirmed', hold=True
        )
        seen, fake_post = self._spy()
        client = APIClient()
        client.force_authenticate(user=self.passenger)
        with patch('bookings.services.requests.post', side_effect=fake_post):
            response = client.post(
                reverse('bookings:cancel-booking', kwargs={'booking_id': booking.id}),
                {'fault_party': 'passenger'}, format='json',
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(seen, [False])
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'pending')

    def test_no_show_sweep(self):
        self.build('202', departure_hours=-1)
        booking, payment = self.booking(
            'confirmed', 'REF_S', payment_status='confirmed', hold=True
        )
        seen, fake_post = self._spy()
        with patch('bookings.services.requests.post', side_effect=fake_post):
            call_command('process_noshows', stdout=io.StringIO())
        self.assertEqual(seen, [False])
        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'no_show')
        self.assertEqual(payment.refund_status, 'pending')

    def test_driver_end_trip(self):
        self.build('203', departure_hours=-1, trip_status='boarding')
        booking, payment = self.booking(
            'confirmed', 'REF_E', payment_status='confirmed', hold=True
        )
        driver_user = User.objects.create_user(
            username='r5_driver_user',
            password='password123',
            phone_number=self.driver.phone_number,
            role='driver',
        )
        seen, fake_post = self._spy()
        client = APIClient()
        client.force_authenticate(user=driver_user)
        with patch('bookings.services.requests.post', side_effect=fake_post):
            response = client.post(
                reverse('bookings:driver-end-trip', kwargs={'driver_id': self.driver.id})
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(seen, [False])
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'pending')
