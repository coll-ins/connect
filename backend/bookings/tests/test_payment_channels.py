from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Payment
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class PaymentChannelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Payment Test Line')
        self.passenger = User.objects.create_user(
            username='payment_passenger',
            password='password123',
            phone_number='+254700000001',
        )
        self.driver = Driver.objects.create(
            company=self.company,
            name='Payment Driver',
            phone_number='+254711111111',
            bus_number='KAA 000P',
        )
        self.route = Route.objects.create(
            company=self.company,
            name='CBD - Payment Test',
            start_point='CBD',
            end_point='Test',
            price=Decimal('200.00'),
        )
        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=14,
        )
        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            total_amount=Decimal('200.00'),
            status='pending',
        )
        self.client.force_authenticate(user=self.passenger)

    @patch('bookings.views.requests.post')
    def test_initialize_mpesa_payment_success(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'message': 'Charge attempted',
            'data': {
                'reference': 'MPESA-REF-001',
                'status': 'pay_offline',
                'display_text': 'Please complete authorization process on your mobile phone',
            },
        }

        response = self.client.post(
            reverse('bookings:initialize-mpesa-payment', kwargs={'booking_id': self.booking.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reference'], 'MPESA-REF-001')
        self.assertEqual(response.data['phone'], self.passenger.phone_number)
        payment = Payment.objects.get(booking=self.booking)
        self.assertEqual(payment.provider_reference, 'MPESA-REF-001')
        self.assertEqual(payment.status, 'pending')
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['mobile_money']['provider'], 'mpesa')
        self.assertEqual(payload['mobile_money']['phone'], self.passenger.phone_number)

    def test_payment_status_unpaid(self):
        response = self.client.get(
            reverse('bookings:payment-status', kwargs={'booking_id': self.booking.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['payment_status'], 'unpaid')

    def test_driver_can_read_assigned_bookings(self):
        driver_user = User.objects.create_user(
            username='driver_login',
            password='password123',
            phone_number=self.driver.phone_number,
            role='driver',
        )
        self.booking.status = 'confirmed'
        self.booking.driver = self.driver
        self.booking.save(update_fields=['status', 'driver'])
        self.trip.status = 'boarding'
        self.trip.save(update_fields=['status'])
        self.client.force_authenticate(user=driver_user)
        response = self.client.get(
            reverse('bookings:get-driver-bookings', kwargs={'driver_id': self.driver.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['bookings']), 1)
