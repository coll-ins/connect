"""Hostile ids and amounts in booking endpoints are client errors, never a 500."""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Incident, Payment
from bookings.tests.review_base import WorldMixin, fund
from companies.models import Route


class BadIdTests(WorldMixin, TestCase):
    def test_resolve_incident_list_replacement_trip_is_a_400(self):
        b = self.booking(self.pax, self.trip1)
        Incident.objects.create(trip=self.trip1, reported_by=self.mgr, incident_type='breakdown',
                                description='x', status='reported')
        for bad in ([1], {'a': 1}, 'abc', 10 ** 30, -4, True):
            r = self.api(self.pax).post(
                f'/api/bookings/{b.id}/resolve-incident/',
                {'resolution': 'reschedule', 'replacement_trip_id': bad}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content[:200]))

    def test_report_incident_with_a_garbage_trip_id_is_a_400(self):
        for bad in ('abc', [1], {'a': 1}, 10 ** 30, -1):
            r = self.api(self.mgr).post('/api/bookings/incidents/report/', {
                'trip_id': bad, 'incident_type': 'breakdown', 'description': 'x'}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.content[:200]))

    def test_login_with_a_non_string_phone_is_a_plain_401(self):
        for phone in (['a'], {'a': 1}, 12345, 1.5):
            r = APIClient().post('/api/users/login/', {'phone_number': phone, 'password': 'x'}, format='json')
            self.assertEqual(r.status_code, 401, (phone, r.status_code))

    def test_walk_in_and_wallet_huge_values_are_client_errors(self):
        cache.clear()
        with override_settings(WALLET_TOPUP_ENABLED=True, WALLET_PAYOUTS_ENABLED=True,
                               CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
                mock.patch('wallets.throttles.TopUpThrottle.allow_request', return_value=True), \
                mock.patch('wallets.throttles.WithdrawThrottle.allow_request', return_value=True):
            for seats in (10 ** 30, -3, '1e3'):
                r = self.api(self.op_all).post(f'/api/bookings/walk-in/{self.trip1.id}/',
                                               {'seats': seats, 'phone_number': '0755000222'}, format='json')
                self.assertEqual(r.status_code, 400, (seats, r.status_code))
            for amt in ('1e3', '99999999999', '-5', 'NaN', '50.555', 10 ** 30):
                r = self.api(self.pax).post('/api/wallet/topup/', {'amount': amt}, format='json')
                self.assertEqual(r.status_code, 400, ('topup', amt, r.status_code))
                r = self.api(self.pax).post('/api/wallet/withdraw/', {
                    'amount': amt, 'idempotency_key': 'k' * 10, 'password': 'pw-123456'}, format='json')
                self.assertEqual(r.status_code, 400, ('withdraw', amt, r.status_code))
            # Non-ASCII digits are read as numbers by Python; the point is they never crash.
            r = self.api(self.op_all).post(f'/api/bookings/walk-in/{self.trip1.id}/',
                                           {'seats': '\u0663', 'phone_number': '0755000222'}, format='json')
            self.assertIn(r.status_code, (201, 400))
            r = self.api(self.pax).post('/api/wallet/withdraw/', {
                'amount': '\u0665\u0660\u0660', 'idempotency_key': 'k' * 10, 'password': 'pw-123456'}, format='json')
            self.assertEqual(r.status_code, 400)


class ZeroPriceWalletPayTests(WorldMixin, TestCase):
    def test_zero_price_route_does_not_500_the_wallet_payment(self):
        Route.objects.filter(pk=self.r1.pk).update(price=Decimal('0.00'))
        self.r1.refresh_from_db()
        b = self.booking(self.pax, self.trip1, 1, 'pending', held_until=timezone.now() + dt.timedelta(minutes=5))
        fund(self.pax, 100, 'topup:zero')
        r = self.api(self.pax).post(f'/api/bookings/payments/{b.id}/wallet/', {}, format='json')
        self.assertEqual(r.status_code, 400, r.content[:200])
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')
        self.assertFalse(Payment.objects.filter(booking=b, status='confirmed').exists())
