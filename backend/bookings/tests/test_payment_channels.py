from decimal import Decimal
import json
import hmac
import hashlib
from unittest.mock import patch
import threading
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, BookingHold, Payment
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

    def test_initialize_cash_payment_success(self):
        response = self.client.post(
            reverse(
                'bookings:initialize-cash-payment',
                kwargs={'booking_id': self.booking.id},
            )
        )

        self.assertEqual(response.status_code, 200)

        payment = Payment.objects.get(
            booking=self.booking,
        )

        self.assertEqual(payment.method, 'cash')
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(
            payment.amount,
            Decimal('200.00'),
        )
        self.assertIsNone(payment.provider_reference)

    def test_initialize_cash_payment_rejects_confirmed_payment(self):
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal('200.00'),
            method='cash',
            status='confirmed',
            settlement_status='eligible',
        )

        response = self.client.post(
            reverse(
                'bookings:initialize-cash-payment',
                kwargs={'booking_id': self.booking.id},
            )
        )

        self.assertEqual(response.status_code, 400)

    def test_initialize_cash_payment_rejects_pending_digital_payment(self):
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal('200.00'),
            method='digital',
            status='pending',
            settlement_status='not_ready',
            provider_reference='CONNECT-DIGITAL-PENDING',
            idempotency_key='CONNECT-DIGITAL-PENDING',
        )

        response = self.client.post(
            reverse(
                'bookings:initialize-cash-payment',
                kwargs={'booking_id': self.booking.id},
            )
        )

        self.assertEqual(response.status_code, 400)


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
        self.assertNotIn(
            'verification_pin',
            response.data['bookings'][0],
        )

    def test_refund_processed_webhook_finalizes_hold_idempotently(self):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference='PAYSTACK-REF-WEBHOOK-001',
            amount=Decimal('800.00'),
            method='digital',
            status='confirmed',
            refund_amount=Decimal('800.00'),
            refund_status='pending',
        )

        hold = BookingHold.objects.create(
            booking=self.booking,
            amount=Decimal('800.00'),
            refunded_amount=Decimal('800.00'),
            status='held',
        )

        payload = {
            'event': 'refund.processed',
            'data': {
                'transaction_reference': 'PAYSTACK-REF-WEBHOOK-001',
                'refund_reference': 'REFUND-WEBHOOK-001',
            },
        }

        body = json.dumps(payload).encode('utf-8')

        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
            body,
            hashlib.sha512,
        ).hexdigest()

        url = reverse('bookings:paystack-refund-webhook')

        response = self.client.post(
            url,
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        payment.refresh_from_db()
        hold.refresh_from_db()

        self.assertEqual(
            payment.refund_status,
            'processed',
        )
        self.assertEqual(
            payment.status,
            'refunded',
        )
        self.assertEqual(
            payment.refund_reference,
            'REFUND-WEBHOOK-001',
        )
        self.assertEqual(
            hold.refunded_amount,
            Decimal('800.00'),
        )
        self.assertEqual(
            hold.status,
            'refunded',
        )
        self.assertIsNotNone(
            hold.refunded_at,
        )

        # Duplicate provider webhook must not change the amount
        # or create another internal refund allocation.
        response = self.client.post(
            url,
            data=body,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)

        hold.refresh_from_db()

        self.assertEqual(
            hold.refunded_amount,
            Decimal('800.00'),
        )
        self.assertEqual(
            hold.status,
            'refunded',
        )

    @patch('bookings.views.requests.post')
    def test_paystack_timeout_does_not_allow_duplicate_retry(
        self,
        mock_post,
    ):
        import requests

        mock_post.side_effect = requests.RequestException(
            "gateway timeout"
        )

        url = reverse(
            'bookings:initialize-paystack-payment',
            kwargs={'booking_id': self.booking.id},
        )

        first = self.client.post(url)

        self.assertEqual(first.status_code, 502)

        reference = first.data['reference']

        mock_post.reset_mock()

        second = self.client.post(url)

        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.data['reference'],
            reference,
        )
        mock_post.assert_not_called()

        payment = Payment.objects.get(
            booking=self.booking,
        )

        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.method, 'digital')
        self.assertEqual(
            payment.provider_reference,
            reference,
        )

    @patch('bookings.views.requests.post')
    def test_mpesa_timeout_does_not_allow_duplicate_retry(
        self,
        mock_post,
    ):
        import requests

        mock_post.side_effect = requests.RequestException(
            "gateway timeout"
        )

        url = reverse(
            'bookings:initialize-mpesa-payment',
            kwargs={'booking_id': self.booking.id},
        )

        first = self.client.post(url)

        self.assertEqual(first.status_code, 502)

        reference = first.data['reference']

        mock_post.reset_mock()

        second = self.client.post(url)

        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.data['reference'],
            reference,
        )
        mock_post.assert_not_called()

        payment = Payment.objects.get(
            booking=self.booking,
        )

        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.method, 'digital')
        self.assertEqual(
            payment.provider_reference,
            reference,
        )


class ConcurrentCashInitializationTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Concurrent Cash Co',
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name='Concurrent Cash Driver',
            phone_number='+254711111112',
            bus_number='KAA 111C',
        )

        self.route = Route.objects.create(
            company=self.company,
            name='CBD - Cash Race',
            start_point='CBD',
            end_point='Race',
            price=Decimal('200.00'),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=10,
            status='scheduled',
        )

        self.passenger = User.objects.create_user(
            username='concurrent_cash_user',
            password='password123',
            phone_number='+254700000002',
        )

        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            total_amount=Decimal('200.00'),
            status='pending',
        )

    def tearDown(self):
        connections.close_all()

    def _initialize_cash(self, results, barrier):
        close_old_connections()

        try:
            client = APIClient()
            client.force_authenticate(user=self.passenger)

            barrier.wait()

            response = client.post(
                reverse(
                    'bookings:initialize-cash-payment',
                    kwargs={'booking_id': self.booking.id},
                )
            )

            results.append(
                (
                    response.status_code,
                    response.data.get('payment_id'),
                )
            )
        except Exception as exc:
            results.append(
                ('error', str(exc))
            )
        finally:
            connections.close_all()

    @unittest.skipUnless(
        connection.vendor == 'postgresql',
        'True row-level locking test requires PostgreSQL.',
    )
    def test_concurrent_cash_initialization_creates_one_payment(self):
        results = []
        barrier = threading.Barrier(2)

        thread_a = threading.Thread(
            target=self._initialize_cash,
            args=(results, barrier),
        )

        thread_b = threading.Thread(
            target=self._initialize_cash,
            args=(results, barrier),
        )

        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        connections.close_all()

        self.assertEqual(len(results), 2, results)

        self.assertTrue(
            all(
                result[0] == 200
                for result in results
            ),
            results,
        )

        payment_ids = {
            result[1]
            for result in results
        }

        self.assertEqual(
            len(payment_ids),
            1,
            results,
        )

        self.assertEqual(
            Payment.objects.filter(
                booking=self.booking
            ).count(),
            1,
        )

        payment = Payment.objects.get(
            booking=self.booking
        )

        self.assertEqual(
            payment.method,
            'cash',
        )

        self.assertEqual(
            payment.status,
            'pending',
        )


class ConcurrentDigitalInitializationTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Concurrent Digital Co',
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name='Concurrent Digital Driver',
            phone_number='+254711111113',
            bus_number='KAA 112C',
        )

        self.route = Route.objects.create(
            company=self.company,
            name='CBD - Digital Race',
            start_point='CBD',
            end_point='Digital',
            price=Decimal('200.00'),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=10,
            status='scheduled',
        )

        self.passenger = User.objects.create_user(
            username='concurrent_digital_user',
            password='password123',
            phone_number='+254700000003',
        )

        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            total_amount=Decimal('200.00'),
            status='pending',
        )

    def tearDown(self):
        connections.close_all()

    def _initialize(
        self,
        endpoint_name,
        results,
        barrier,
    ):
        close_old_connections()

        try:
            client = APIClient()
            client.force_authenticate(user=self.passenger)

            barrier.wait()

            response = client.post(
                reverse(
                    endpoint_name,
                    kwargs={'booking_id': self.booking.id},
                ),
                format='json',
            )

            results.append(
                (
                    response.status_code,
                    response.data.get('reference'),
                )
            )
        except Exception as exc:
            results.append(
                ('error', str(exc))
            )
        finally:
            connections.close_all()

    @unittest.skipUnless(
        connection.vendor == 'postgresql',
        'True row-level locking test requires PostgreSQL.',
    )
    @patch('bookings.views.requests.post')
    def test_concurrent_paystack_initialization_creates_one_attempt(
        self,
        mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {
                'authorization_url':
                    'https://checkout.paystack.com/race',
                'reference': 'CONNECT-IGNORED',
            },
        }

        # Return exactly the reference CONNECT generated from the
        # booking, regardless of the random UUID.
        def initialize_response(*args, **kwargs):
            payload = kwargs['json']
            return type(
                'MockResponse',
                (),
                {
                    'status_code': 200,
                    'json': lambda self: {
                        'status': True,
                        'data': {
                            'authorization_url':
                                'https://checkout.paystack.com/race',
                            'reference': payload['reference'],
                        },
                    },
                },
            )()

        mock_post.side_effect = initialize_response

        results = []
        barrier = threading.Barrier(2)

        threads = [
            threading.Thread(
                target=self._initialize,
                args=(
                    'bookings:initialize-paystack-payment',
                    results,
                    barrier,
                ),
            )
            for _ in range(2)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        connections.close_all()

        self.assertEqual(len(results), 2, results)

        statuses = sorted(
            result[0]
            for result in results
        )

        self.assertEqual(
            statuses,
            [200, 409],
        )

        self.assertEqual(
            mock_post.call_count,
            1,
        )

        self.assertEqual(
            Payment.objects.filter(
                booking=self.booking,
            ).count(),
            1,
        )

        payment = Payment.objects.get(
            booking=self.booking,
        )

        self.assertEqual(
            payment.method,
            'digital',
        )

        self.assertEqual(
            payment.status,
            'pending',
        )

        self.assertTrue(
            payment.provider_reference.startswith(
                f'CONNECT-{self.booking.id}-'
            ),
        )

    @unittest.skipUnless(
        connection.vendor == 'postgresql',
        'True row-level locking test requires PostgreSQL.',
    )
    @patch('bookings.views.requests.post')
    def test_concurrent_mpesa_initialization_creates_one_attempt(
        self,
        mock_post,
    ):
        def charge_response(*args, **kwargs):
            payload = kwargs['json']

            return type(
                'MockResponse',
                (),
                {
                    'status_code': 200,
                    'json': lambda self: {
                        'status': True,
                        'data': {
                            'reference': payload['reference'],
                            'status': 'pay_offline',
                            'display_text':
                                'Complete M-PESA authorization.',
                        },
                    },
                },
            )()

        mock_post.side_effect = charge_response

        results = []
        barrier = threading.Barrier(2)

        threads = [
            threading.Thread(
                target=self._initialize,
                args=(
                    'bookings:initialize-mpesa-payment',
                    results,
                    barrier,
                ),
            )
            for _ in range(2)
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        connections.close_all()

        self.assertEqual(len(results), 2, results)

        statuses = sorted(
            result[0]
            for result in results
        )

        self.assertEqual(
            statuses,
            [200, 409],
        )

        self.assertEqual(
            mock_post.call_count,
            1,
        )

        self.assertEqual(
            Payment.objects.filter(
                booking=self.booking,
            ).count(),
            1,
        )

        payment = Payment.objects.get(
            booking=self.booking,
        )

        self.assertEqual(
            payment.method,
            'digital',
        )

        self.assertEqual(
            payment.status,
            'pending',
        )

        self.assertTrue(
            payment.provider_reference.startswith(
                f'CONNECT-{self.booking.id}-'
            ),
        )

