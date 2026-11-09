from django.test import override_settings
from decimal import Decimal
import io
from django.core.management import call_command
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


def _paystack_offline(*args, **kwargs):
    import requests
    raise requests.RequestException('offline')


@override_settings(CASH_ENABLED=True, CASH_MIN_TRIPS=1, CASH_MIN_ACCOUNT_DAYS=0)
class PaymentChannelTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Payment Test Line')
        self.passenger = User.objects.create_user(
            username='payment_passenger',
            password='password123',
            phone_number='+254700000001',
            boarded_count=10,  # trusted: cash unlocked
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

    @patch('bookings.views.requests.get', new=_paystack_offline)
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

    def test_driver_list_exposes_payment_method(self):
        driver_user = User.objects.create_user(
            username='driver_login_pm',
            password='password123',
            phone_number=self.driver.phone_number,
            role='driver',
        )
        self.booking.status = 'confirmed'
        self.booking.driver = self.driver
        self.booking.save(update_fields=['status', 'driver'])
        self.trip.status = 'boarding'
        self.trip.save(update_fields=['status'])
        Payment.objects.create(
            booking=self.booking,
            amount=Decimal('200.00'),
            method='cash',
            status='pending',
            settlement_status='not_ready',
            provider_reference='CONNECT-CASH-PM-TEST',
            idempotency_key='CONNECT-CASH-PM-TEST',
        )
        self.client.force_authenticate(user=driver_user)
        response = self.client.get(
            reverse('bookings:get-driver-bookings', kwargs={'driver_id': self.driver.id})
        )
        self.assertEqual(response.status_code, 200)
        item = response.data['bookings'][0]
        self.assertEqual(item['payment_status'], 'pending')
        self.assertEqual(item['payment_method'], 'cash')

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

    @patch('bookings.views.requests.get', new=_paystack_offline)
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

    @patch('bookings.views.requests.get', new=_paystack_offline)
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


@override_settings(CASH_ENABLED=True, CASH_MIN_TRIPS=1, CASH_MIN_ACCOUNT_DAYS=0)
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
            boarded_count=10,  # trusted: cash unlocked
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



@override_settings(CASH_ENABLED=True, CASH_MIN_TRIPS=1, CASH_MIN_ACCOUNT_DAYS=0)
class DeadDigitalAttemptTests(TestCase):
    """A closed or failed Paystack checkout must not lock the booking."""

    def setUp(self):
        self.client = APIClient()
        company = Company.objects.create(name='Retry Line')
        self.passenger = User.objects.create_user(
            username='retry_passenger', password='password123',
            phone_number='+254700000077',
            boarded_count=10)  # trusted: cash unlocked
        route = Route.objects.create(
            company=company, name='CBD - Retry', start_point='CBD',
            end_point='Retry', price=Decimal('200.00'))
        driver = Driver.objects.create(
            company=company, name='Retry Driver', phone_number='+254711111177',
            bus_number='KAA 077R')
        trip = Trip.objects.create(
            route=route, driver=driver, departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=14)
        self.booking = Booking.objects.create(
            user=self.passenger, route=route, trip=trip,
            total_amount=Decimal('200.00'), status='pending')
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('200.00'), method='digital',
            status='pending', settlement_status='not_ready',
            provider_reference='CONNECT-OLD', idempotency_key='CONNECT-OLD')
        self.client.force_authenticate(user=self.passenger)

    def _verify_says(self, mock_get, http, body):
        mock_get.return_value.status_code = http
        mock_get.return_value.json.return_value = body

    @patch('bookings.views.requests.get')
    def test_abandoned_checkout_lets_passenger_switch_to_cash(self, mock_get):
        self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'abandoned'}})
        r = self.client.post(reverse('bookings:initialize-cash-payment',
                                     kwargs={'booking_id': self.booking.id}))
        self.assertEqual(r.status_code, 200, r.data)
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.method, self.payment.status), ('cash', 'pending'))

    @patch('bookings.views.requests.post')
    @patch('bookings.views.requests.get')
    def test_failed_card_payment_can_be_retried(self, mock_get, mock_post):
        self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'failed'}})
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'data': {'authorization_url': 'https://checkout.paystack.com/x',
                     'reference': 'CONNECT-NEW'}}
        r = self.client.post(reverse('bookings:initialize-paystack-payment',
                                     kwargs={'booking_id': self.booking.id}))
        self.assertEqual(r.status_code, 200, r.data)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.provider_reference, 'CONNECT-NEW')

    @patch('bookings.views.requests.get')
    def test_attempt_still_in_progress_stays_locked(self, mock_get):
        self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'ongoing'}})
        r = self.client.post(reverse('bookings:initialize-mpesa-payment',
                                     kwargs={'booking_id': self.booking.id}),
                             {'phone_number': '+254712345678'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')

    @patch('bookings.views.requests.get')
    def test_paid_attempt_is_not_replaced(self, mock_get):
        self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'success'}})
        r = self.client.post(reverse('bookings:initialize-cash-payment',
                                     kwargs={'booking_id': self.booking.id}))
        self.assertEqual(r.status_code, 400)
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.method, self.payment.provider_reference),
                         ('digital', 'CONNECT-OLD'))

    @patch('bookings.views.requests.post')
    def test_refused_checkout_init_does_not_lock(self, mock_post):
        Payment.objects.filter(pk=self.payment.pk).update(status='failed')
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {'status': False, 'message': 'Invalid key'}
        r = self.client.post(reverse('bookings:initialize-paystack-payment',
                                     kwargs={'booking_id': self.booking.id}))
        self.assertEqual(r.status_code, 502)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'failed')

    def _webhook(self, ref, currency='KES'):
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': ref, 'amount': 20000, 'currency': currency}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return self.client.post(reverse('bookings:paystack-webhook'), data=body,
                                content_type='application/json',
                                HTTP_X_PAYSTACK_SIGNATURE=sig)

    def _switch_to_cash(self):
        with patch('bookings.views.requests.get') as mock_get:
            self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'abandoned'}})
            r = self.client.post(reverse('bookings:initialize-cash-payment',
                                         kwargs={'booking_id': self.booking.id}))
        self.assertEqual(r.status_code, 200, r.data)

    @patch('bookings.views.send_admin_alert_sms')
    @patch('connect.paystack_extra.refund_charge', return_value=('pending', 77))
    def test_paying_the_old_checkout_after_switching_is_refunded(self, refund, sms):
        from bookings.models import UnappliedPayment
        self._switch_to_cash()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self._webhook('CONNECT-OLD').status_code, 200)
            self.assertEqual(self._webhook('CONNECT-OLD').status_code, 200)  # Paystack replay
        refund.assert_not_called()  # never inline: the webhook stays fast
        row = UnappliedPayment.objects.get(reference='CONNECT-OLD')
        self.assertEqual((row.kind, row.status, row.amount),
                         ('booking', 'refund_due', Decimal('200.00')))
        self.assertEqual(sms.call_count, 1)  # one alert, not one per replay

        call_command('process_unapplied', stdout=io.StringIO())
        call_command('process_unapplied', stdout=io.StringIO())
        refund.assert_called_once_with('CONNECT-OLD', Decimal('200.00'))
        row.refresh_from_db()
        self.assertEqual((row.status, row.refund_reference), ('refunded', '77'))
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.method, self.payment.status), ('cash', 'pending'))

    @patch('bookings.views.send_admin_alert_sms')
    @patch('connect.paystack_extra.refund_charge')
    def test_unmatched_charge_in_wrong_currency_goes_to_a_human(self, refund, sms):
        from bookings.models import UnappliedPayment
        self._switch_to_cash()
        self._webhook('CONNECT-OLD', currency='USD')
        call_command('process_unapplied', stdout=io.StringIO())
        refund.assert_not_called()
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-OLD').status, 'review')

    @patch('bookings.views.send_admin_alert_sms')
    def test_recording_failure_makes_paystack_resend(self, sms):
        from bookings.models import UnappliedPayment
        self._switch_to_cash()
        with patch.object(UnappliedPayment.objects, 'get_or_create', side_effect=RuntimeError('db down')):
            self.assertEqual(self._webhook('CONNECT-OLD').status_code, 500)
        self.assertEqual(self._webhook('CONNECT-OLD').status_code, 200)
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-OLD').status, 'refund_due')

    @patch('bookings.views.send_admin_alert_sms')
    def test_failed_queued_refund_goes_back_to_a_human(self, sms):
        from bookings.models import UnappliedPayment
        UnappliedPayment.objects.create(reference='CONNECT-GONE', kind='booking',
                                        amount=Decimal('200.00'), status='refunded')
        body = json.dumps({'event': 'refund.failed', 'data': {
            'transaction_reference': 'CONNECT-GONE'}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()
        r = self.client.post(reverse('bookings:paystack-webhook'), data=body,
                             content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-GONE').status, 'review')
        sms.assert_called_once()


class WrongAmountChargeTests(DeadDigitalAttemptTests):
    """A real charge that does not match the booking is refunded, never kept."""

    def _signed(self, payload):
        body = json.dumps(payload).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()
        return self.client.post(reverse('bookings:paystack-webhook'), data=body,
                                content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)

    @patch('bookings.views.send_admin_alert_sms')
    def test_webhook_underpayment_is_queued_for_refund(self, sms):
        from bookings.models import UnappliedPayment
        with self.captureOnCommitCallbacks(execute=True):
            self._signed({'event': 'charge.success', 'data': {
                'reference': 'CONNECT-OLD', 'amount': 5000, 'currency': 'KES'}})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'failed')
        row = UnappliedPayment.objects.get(reference='CONNECT-OLD')
        self.assertEqual((row.status, row.amount), ('refund_due', Decimal('50.00')))
        sms.assert_called_once()

    @patch('bookings.views.send_admin_alert_sms')
    def test_webhook_missing_amount_goes_to_a_human(self, sms):
        from bookings.models import UnappliedPayment
        self._signed({'event': 'charge.success', 'data': {'reference': 'CONNECT-OLD'}})
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-OLD').status, 'review')

    @patch('bookings.views.send_admin_alert_sms')
    @patch('bookings.views.requests.get')
    def test_verify_wrong_currency_is_queued_for_human_review(self, mock_get, sms):
        from bookings.models import UnappliedPayment
        self._verify_says(mock_get, 200, {'status': True, 'data': {
            'status': 'success', 'amount': 20000, 'currency': 'USD'}})
        self.client.post(reverse('bookings:verify-paystack-payment',
                                 kwargs={'booking_id': self.booking.id}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'failed')
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-OLD').status, 'review')

    @patch('bookings.views.send_admin_alert_sms')
    def test_failed_refund_on_a_tracked_reference_reopens_it(self, sms):
        from bookings.models import UnappliedPayment
        UnappliedPayment.objects.create(reference='CONNECT-OLD', kind='booking',
                                        amount=Decimal('50.00'), status='refunded')
        self._signed({'event': 'refund.failed', 'data': {'transaction_reference': 'CONNECT-OLD'}})
        self.assertEqual(UnappliedPayment.objects.get(reference='CONNECT-OLD').status, 'review')

    @patch('bookings.views.send_admin_alert_sms')
    @patch('bookings.views.requests.get')
    def test_verify_without_amount_leaves_it_to_the_webhook(self, mock_get, sms):
        from bookings.models import UnappliedPayment
        self._verify_says(mock_get, 200, {'status': True, 'data': {'status': 'success'}})
        self.client.post(reverse('bookings:verify-paystack-payment',
                                 kwargs={'booking_id': self.booking.id}))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')
        self.assertFalse(UnappliedPayment.objects.exists())
        self._signed({'event': 'charge.success', 'data': {
            'reference': 'CONNECT-OLD', 'amount': 20000, 'currency': 'KES'}})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'confirmed')
