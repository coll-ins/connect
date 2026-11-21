"""No gateway call may run inside an open database transaction.

A call made while a transaction is open holds row locks for the length of a
network request, and a rollback after the gateway said yes loses the record
of it. TransactionTestCase is required: under TestCase every test already
runs inside an atomic block, so the check would always fail.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Payment
from bookings.services import claim_booking_refund, settle_booking_fault
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class GatewayCallInvariantTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name='Gate Co', areas_served='Nairobi')
        route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        stage = PickupStage.objects.create(
            route=route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        self.user = User.objects.create_user(
            username='pax', password='pw-123456', phone_number='+254711222222')
        self.booking = Booking.objects.create(
            user=self.user, trip=trip, route=route, driver=driver, seats=1,
            total_amount=Decimal('100'), status='pending',
            held_until=timezone.now() + dt.timedelta(minutes=5),
            pickup_location='Kencom', pickup_stage=stage)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.in_atomic = []

    def fake(self, *args, **kwargs):
        self.in_atomic.append(connection.in_atomic_block)
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'status': True, 'data': {
            'id': 77, 'status': 'pending', 'reference': 'x',
            'authorization_url': 'https://paystack.test/pay'}}
        return resp

    def confirmed_payment(self):
        Booking.objects.filter(pk=self.booking.pk).update(status='confirmed')
        return Payment.objects.create(
            booking=self.booking, amount=Decimal('100'), method='digital',
            status='confirmed', provider_reference='CONNECT-ref-1',
            idempotency_key='CONNECT-ref-1')

    def test_atomic_requests_off(self):
        self.assertFalse(settings.DATABASES['default'].get('ATOMIC_REQUESTS'))

    def test_paystack_init_calls_gateway_outside_a_transaction(self):
        with mock.patch('requests.post', side_effect=self.fake):
            resp = self.client.post(
                f'/api/bookings/payments/{self.booking.id}/paystack/', {})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.in_atomic, [False])

    def test_mpesa_init_calls_gateway_outside_a_transaction(self):
        with mock.patch('requests.post', side_effect=self.fake):
            self.client.post(
                f'/api/bookings/payments/{self.booking.id}/mpesa/',
                {'phone_number': '+254711222222'}, format='json')
        self.assertEqual(self.in_atomic, [False])

    def test_refund_calls_gateway_outside_a_transaction(self):
        self.confirmed_payment()
        with mock.patch('requests.post', side_effect=self.fake):
            settle_booking_fault(Booking.objects.get(pk=self.booking.pk), 'company')
        self.assertEqual(self.in_atomic, [False])

    def test_cancel_refund_calls_gateway_outside_a_transaction(self):
        self.confirmed_payment()
        with mock.patch('requests.post', side_effect=self.fake):
            resp = self.client.post(f'/api/bookings/{self.booking.id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.in_atomic, [False])

    def test_late_payment_refund_calls_gateway_outside_a_transaction(self):
        import hashlib
        import hmac
        import json
        payment = self.confirmed_payment()
        Payment.objects.filter(pk=payment.pk).update(status='pending')
        Booking.objects.filter(pk=self.booking.pk).update(status='cancelled')
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': 'CONNECT-ref-1', 'amount': 10000,
            'currency': 'KES'}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        with mock.patch('requests.post', side_effect=self.fake):
            resp = APIClient().post(
                '/api/bookings/webhooks/paystack/', data=body,
                content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.in_atomic, [False])

    def test_claim_never_reaches_the_gateway(self):
        self.confirmed_payment()
        with mock.patch('requests.post') as post, mock.patch('requests.get') as get:
            with transaction.atomic():
                amount, claim = claim_booking_refund(
                    Booking.objects.get(pk=self.booking.pk), 'company')
        self.assertIsNotNone(claim)
        post.assert_not_called()
        get.assert_not_called()
