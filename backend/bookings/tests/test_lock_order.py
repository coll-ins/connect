"""One lock order for every seat and money path: Trip -> Booking -> Payment.

Postgres only: SQLite ignores row locks, so green there proves nothing.
"""
import datetime as dt
import hashlib
import hmac
import json
import re
import threading
import unittest
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Payment
from bookings.services import settle_booking_fault
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
WEBHOOK = '/api/bookings/webhooks/paystack/'


def _locks(queries):
    """(first table, has a join) for every FOR UPDATE statement, in order."""
    found = []
    for q in queries:
        sql = q['sql']
        if 'FOR UPDATE' not in sql:
            continue
        table = re.search(r'FROM "(\w+)"', sql).group(1)
        found.append((table, ' JOIN ' in sql))
    return found


def _signed(payment):
    body = json.dumps({'event': 'charge.success', 'data': {
        'reference': payment.provider_reference,
        'amount': int(payment.amount * 100), 'currency': 'KES'}}).encode()
    sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                   hashlib.sha512).hexdigest()
    return body, sig


class LockOrderBase(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name='Lock Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        self.driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        self.n = 0

    def pending_with_payment(self):
        self.n += 1
        user = User.objects.create_user(
            username=f'u{self.n}', password='pw-123456',
            phone_number=f'+2547130{self.n:05d}')
        booking = Booking.objects.create(
            user=user, trip=self.trip, route=self.route, driver=self.driver,
            seats=1, total_amount=Decimal('100'), status='pending',
            held_until=timezone.now() + dt.timedelta(minutes=5),
            pickup_location='Kencom', pickup_stage=self.stage)
        payment = Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='pending', provider_reference=f'CONNECT-{booking.id}-x',
            idempotency_key=f'CONNECT-{booking.id}-x')
        return user, booking, payment


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class LockOrderTests(LockOrderBase):
    def test_webhook_locks_trip_then_booking_then_payment_without_joins(self):
        _, _, payment = self.pending_with_payment()
        body, sig = _signed(payment)
        with CaptureQueriesContext(connection) as ctx:
            resp = APIClient().post(
                WEBHOOK, data=body, content_type='application/json',
                HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 200)
        locks = _locks(ctx.captured_queries)
        self.assertEqual(
            [t for t, _ in locks][:3],
            ['companies_trip', 'bookings_booking', 'bookings_payment'])
        self.assertEqual([t for t, joined in locks if joined], [],
                         'a locking query joined another table')

    def test_cancel_locks_trip_then_booking_then_payment(self):
        user, booking, payment = self.pending_with_payment()
        client = APIClient()
        client.force_authenticate(user)
        with CaptureQueriesContext(connection) as ctx:
            resp = client.post(f'/api/bookings/{booking.id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content)
        tables = [t for t, _ in _locks(ctx.captured_queries)]
        # cancel locks the booking, then the refund claim re-locks it (a no-op
        # for the same transaction) before the payment.
        self.assertEqual(
            tables[:4],
            ['companies_trip', 'bookings_booking', 'bookings_booking', 'bookings_payment'])

    def test_standalone_refund_claim_locks_booking_before_payment(self):
        _, booking, payment = self.pending_with_payment()
        Payment.objects.filter(pk=payment.pk).update(status='confirmed')
        with CaptureQueriesContext(connection) as ctx, \
                mock.patch('bookings.services.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {
                'status': True, 'data': {'id': 5, 'status': 'pending'}}
            settle_booking_fault(Booking.objects.get(pk=booking.pk), 'company')
        tables = [t for t, _ in _locks(ctx.captured_queries)]
        self.assertEqual(tables[:2], ['bookings_booking', 'bookings_payment'])

    def test_cash_confirm_locks_trip_first(self):
        _, booking, _ = self.pending_with_payment()
        Payment.objects.filter(booking=booking).update(method='cash', provider_reference=None)
        staff = User.objects.create_user(
            username='root', password='pw-123456', phone_number='+254711888888',
            is_superuser=True, is_staff=True)
        client = APIClient()
        client.force_authenticate(staff)
        with CaptureQueriesContext(connection) as ctx:
            resp = client.post(f'/api/bookings/payments/{booking.id}/cash/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content)
        tables = [t for t, _ in _locks(ctx.captured_queries)]
        self.assertEqual(tables[:3], ['companies_trip', 'bookings_booking', 'bookings_payment'])

    def test_lock_order_webhook_vs_cancel(self):
        """Many simultaneous webhook + cancel pairs: no deadlock, no 500."""
        results = []
        lock = threading.Lock()
        ids = iter(range(1000, 2000))

        def refund_ok(*args, **kwargs):
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {
                'status': True, 'data': {'id': next(ids), 'status': 'pending'}}
            return resp

        def hit(fn):
            try:
                code = fn()
            except Exception as exc:  # a deadlock surfaces as OperationalError
                code = repr(exc)
            finally:
                connection.close()
            with lock:
                results.append(code)

        with mock.patch('bookings.services.requests.post', side_effect=refund_ok), \
                mock.patch('bookings.views.settle_booking_fault'):
            for _ in range(25):
                user, booking, payment = self.pending_with_payment()
                body, sig = _signed(payment)
                client = APIClient()
                client.force_authenticate(user)
                barrier = threading.Barrier(2)

                def webhook():
                    barrier.wait()
                    return APIClient().post(
                        WEBHOOK, data=body, content_type='application/json',
                        HTTP_X_PAYSTACK_SIGNATURE=sig).status_code

                def cancel():
                    barrier.wait()
                    return client.post(f'/api/bookings/{booking.id}/cancel/').status_code

                threads = [threading.Thread(target=hit, args=(f,)) for f in (webhook, cancel)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                booking.refresh_from_db()
                self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(set(results), {200}, results)


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class EndTripVsWebhookTests(LockOrderBase):
    """D-10: the bulk 'cancel unpaid bookings' on trip end against a webhook."""

    def test_end_trip_vs_confirming_webhook(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding', departure_at=timezone.now() - dt.timedelta(minutes=25))
        drv = User.objects.create_user(
            username='drv', password='pw-123456', phone_number='+254700000001')
        ids = iter(range(5000, 6000))
        codes, outcomes = [], set()
        lock = threading.Lock()

        def refund_ok(*args, **kwargs):
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {
                'status': True, 'data': {'id': next(ids), 'status': 'pending'}}
            return resp

        for i in range(15):
            Trip.objects.filter(pk=self.trip.pk).update(status='boarding')
            _, booking, payment = self.pending_with_payment()
            body, sig = _signed(payment)
            barrier = threading.Barrier(2)

            def webhook():
                barrier.wait()
                return APIClient().post(
                    WEBHOOK, data=body, content_type='application/json',
                    HTTP_X_PAYSTACK_SIGNATURE=sig).status_code

            def end_trip():
                barrier.wait()
                client = APIClient()
                client.force_authenticate(drv)
                return client.post(
                    f'/api/bookings/driver/{self.driver.id}/end-trip/').status_code

            def run(fn):
                try:
                    code = fn()
                except Exception as exc:
                    code = repr(exc)
                finally:
                    connection.close()
                with lock:
                    codes.append(code)

            with mock.patch('bookings.services.requests.post', side_effect=refund_ok), \
                    mock.patch('bookings.views.settle_booking_fault') as late_refund, \
                    mock.patch('bookings.views.is_driver_account_for', return_value=True):
                threads = [threading.Thread(target=run, args=(f,))
                           for f in (webhook, end_trip)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            booking.refresh_from_db()
            payment.refresh_from_db()
            self.assertEqual(payment.status, 'confirmed')
            if booking.status == 'no_show':
                outcomes.add('confirmed_then_no_show')
            else:
                self.assertEqual(booking.status, 'cancelled')
                late_refund.assert_called_once()
                outcomes.add('cancelled_and_refunded')
        self.assertEqual(set(codes), {200}, codes)
        self.assertTrue(outcomes <= {'confirmed_then_no_show', 'cancelled_and_refunded'})
