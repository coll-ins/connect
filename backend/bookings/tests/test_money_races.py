"""Simultaneous webhooks and claims on one charge (BE-1b, PostgreSQL only).

SQLite serialises every write, so only real row locks prove these.
"""
import datetime as dt
import hashlib
import hmac
import json
import threading
import unittest
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking, Payment, UnappliedPayment
from companies.models import Company, PickupStage, Route, Trip
from connect import paystack_extra as px
from drivers.models import Driver

User = get_user_model()


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class MoneyRaceTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name='Money Co', areas_served='Nairobi')
        route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        stage = PickupStage.objects.create(
            route=route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        self.trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        user = User.objects.create_user(
            username='pax', password='pw-123456', phone_number='+254711222222')
        self.booking = Booking.objects.create(
            user=user, trip=self.trip, route=route, driver=driver, seats=1,
            total_amount=Decimal('100'), status='pending',
            held_until=timezone.now() + dt.timedelta(minutes=5),
            pickup_location='Kencom', pickup_stage=stage)
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal('100'), method='digital',
            status='pending', provider_reference='CONNECT-1-' + 'c' * 32)
        self.refunds = []
        self.lock = threading.Lock()

    def fake_post(self, url, json=None, **kwargs):
        resp = mock.Mock(status_code=200)
        with self.lock:
            self.refunds.append((json['transaction'], json['amount']))
            rid = len(self.refunds)
        resp.json.return_value = {'status': True, 'data': {'id': rid, 'status': 'pending'}}
        return resp

    def hit(self, n, target, *args):
        barrier = threading.Barrier(n)
        results = []

        def run():
            barrier.wait()
            try:
                results.append(target(*args))
            finally:
                connection.close()

        threads = [threading.Thread(target=run) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def webhook(self, amount):
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': self.payment.provider_reference, 'amount': amount,
            'currency': 'KES'}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return APIClient().post(
            '/api/bookings/webhooks/paystack/', data=body,
            content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig).status_code

    def test_eight_replays_of_an_overpayment_send_one_refund(self):
        with mock.patch('requests.post', self.fake_post), \
                mock.patch('bookings.views.send_admin_alert_sms'):
            codes = self.hit(8, self.webhook, 15000)
        self.assertEqual(codes, [200] * 8)
        self.assertEqual(self.refunds, [(self.payment.provider_reference, 5000)])
        self.assertEqual(UnappliedPayment.objects.count(), 1)
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, 'confirmed')

    def test_eight_replays_of_a_late_payment_send_one_refund(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            held_until=timezone.now() - dt.timedelta(minutes=5))
        with mock.patch('requests.post', self.fake_post), \
                mock.patch('bookings.views.send_admin_alert_sms'):
            codes = self.hit(8, self.webhook, 10000)
        self.assertEqual(codes, [200] * 8)
        self.assertEqual(self.refunds, [(self.payment.provider_reference, 10000)])
        self.assertEqual(Booking.objects.get(pk=self.booking.pk).status, 'cancelled')

    def test_unapplied_refund_single_claim(self):
        row = UnappliedPayment.objects.create(
            reference='CONNECT-2-' + 'd' * 32, kind='booking',
            amount=Decimal('50'), status='refund_due')
        wins = self.hit(8, px.claim_refund, row)
        self.assertEqual(wins.count(True), 1)
        self.assertEqual(UnappliedPayment.objects.get(pk=row.pk).status, 'refunding')

    def test_eight_replays_of_an_unmatched_charge_send_one_refund(self):
        ref = 'CONNECT-3-' + 'e' * 32
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': ref, 'amount': 12000, 'currency': 'KES'}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()

        def post():
            return APIClient().post(
                '/api/bookings/webhooks/paystack/', data=body,
                content_type='application/json',
                HTTP_X_PAYSTACK_SIGNATURE=sig).status_code

        with mock.patch('requests.post', self.fake_post), \
                mock.patch('bookings.views.send_admin_alert_sms'), \
                mock.patch('notifications.sms.send_admin_alert_sms'):
            codes = self.hit(8, post)
            from io import StringIO
            from django.core.management import call_command
            call_command('process_unapplied', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(codes, [200] * 8)
        self.assertEqual(self.refunds, [(ref, 12000)])
        self.assertEqual(UnappliedPayment.objects.filter(reference=ref).count(), 1)
