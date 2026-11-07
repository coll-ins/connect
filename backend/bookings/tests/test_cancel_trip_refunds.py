from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, BookingHold, Payment
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()

PAYSTACK = 'bookings.services.requests.post'
SMS = 'notifications.sms.send_trip_cancelled_sms'


def paystack_ok(post):
    post.return_value.status_code = 200
    post.return_value.json.return_value = {
        'status': True,
        'data': {'id': 555, 'status': 'pending'},
    }


class CancelTripRefundTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Cancel SACCO', description='d', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=self.company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('800.00'))
        self.driver = Driver.objects.create(
            company=self.company, name='Driver', phone_number='0700000021',
            bus_number='KAA 002A')
        self.admin = User.objects.create_superuser(
            username='cancel_admin', password='Test-password-123',
            phone_number='+254700000020')
        self.passenger = User.objects.create_user(
            username='cancel_passenger', password='Test-password-123',
            phone_number='+254700000022')
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=14,
            departure_at=timezone.now() + timedelta(hours=3),
            status='scheduled')
        self.client.force_authenticate(user=self.admin)

    def booking(self, status='confirmed'):
        return Booking.objects.create(
            user=self.passenger, route=self.route, driver=self.driver,
            trip=self.trip, pickup_location='CBD',
            total_amount=Decimal('800.00'), status=status)

    def paid_booking(self, reference='REF_1', method='digital'):
        booking = self.booking()
        payment = Payment.objects.create(
            booking=booking, provider_reference=reference,
            amount=Decimal('800.00'), method=method, status='confirmed')
        BookingHold.objects.create(
            booking=booking, amount=Decimal('800.00'), status='held')
        return booking, payment

    def set_status(self, new_status):
        return self.client.post(
            reverse('update_trip_status', kwargs={'trip_id': self.trip.pk}),
            {'status': new_status}, format='json')

    @patch(SMS)
    @patch(PAYSTACK)
    def test_paid_booking_gets_a_full_refund_and_is_told(self, post, sms):
        paystack_ok(post)
        booking, payment = self.paid_booking()

        response = self.set_status('cancelled')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['cancelled_bookings'], 1)
        self.assertEqual(response.json()['refunds_started'], 1)
        self.assertEqual(response.json()['refunds_to_follow_up'], 0)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['amount'], 80000)
        booking.refresh_from_db()
        payment.refresh_from_db()
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'cancelled')
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(payment.refund_amount, Decimal('800.00'))
        self.assertEqual(payment.refund_status, 'pending')
        sms.assert_called_once()
        self.assertTrue(sms.call_args.kwargs['paid'])

    @patch(SMS)
    @patch(PAYSTACK)
    def test_unpaid_booking_is_cancelled_without_a_refund(self, post, sms):
        booking = self.booking(status='pending')

        response = self.set_status('cancelled')

        self.assertEqual(response.status_code, 200, response.content)
        post.assert_not_called()
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertFalse(sms.call_args.kwargs['paid'])

    @patch(SMS)
    @patch(PAYSTACK)
    def test_cash_is_recorded_and_flagged_not_sent_to_paystack(self, post, _):
        booking, payment = self.paid_booking(reference=None, method='cash')

        response = self.set_status('cancelled')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['refunds_to_follow_up'], 1)
        post.assert_not_called()
        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(payment.refund_amount, Decimal('800.00'))

    @patch(SMS)
    @patch(PAYSTACK)
    def test_refused_when_someone_has_boarded(self, post, sms):
        self.trip.status = 'boarding'
        self.trip.save(update_fields=['status'])
        boarded = self.booking(status='completed')
        waiting, _ = self.paid_booking()

        response = self.set_status('cancelled')

        self.assertEqual(response.status_code, 409, response.content)
        post.assert_not_called()
        sms.assert_not_called()
        self.trip.refresh_from_db()
        boarded.refresh_from_db()
        waiting.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')
        self.assertEqual(boarded.status, 'completed')
        self.assertEqual(waiting.status, 'confirmed')

    @patch(SMS)
    @patch(PAYSTACK)
    def test_setting_cancelled_twice_does_not_refund_twice(self, post, _):
        paystack_ok(post)
        self.paid_booking()

        self.assertEqual(self.set_status('cancelled').status_code, 200)
        self.assertEqual(self.set_status('cancelled').status_code, 200)

        post.assert_called_once()

    @patch(SMS)
    @patch(PAYSTACK)
    def test_other_status_changes_leave_bookings_alone(self, post, sms):
        booking, _ = self.paid_booking()

        response = self.set_status('boarding')

        self.assertEqual(response.status_code, 200, response.content)
        post.assert_not_called()
        sms.assert_not_called()
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')

    @patch(SMS)
    @patch(PAYSTACK)
    def test_refused_refund_stays_cancelled_and_the_sweep_retries(self, post, _):
        post.return_value.status_code = 400
        post.return_value.json.return_value = {'message': 'Refused'}
        booking, payment = self.paid_booking()

        self.assertEqual(self.set_status('cancelled').status_code, 200)

        booking.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(payment.refund_status, 'not_requested')

        paystack_ok(post)
        post.reset_mock()
        call_command('process_noshows', stdout=StringIO(), stderr=StringIO())

        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['amount'], 80000)
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'pending')
