"""Payment status is the owner's only: another passenger sees nothing of it."""
from decimal import Decimal

from django.test import TestCase

from bookings.models import Payment
from bookings.tests.review_base import WorldMixin


class PaymentStatusOwnerTests(WorldMixin, TestCase):
    def test_another_users_payment_status_looks_like_no_payment_and_leaks_nothing(self):
        booking = self.booking(self.pax, self.trip1, status='pending')
        Payment.objects.create(
            booking=booking, amount=Decimal('250'), method='digital', status='pending',
            settlement_status='not_ready', provider_reference='CONNECT-SECRET-REF',
            idempotency_key='CONNECT-SECRET-REF')
        r = self.api(self.pax2).get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(r.status_code, 200, r.content[:160])
        self.assertEqual(r.json(), {
            'booking_id': booking.id, 'payment_status': 'unpaid', 'payment_method': None})
        self.assertNotIn('CONNECT-SECRET-REF', r.content.decode())
        r = self.api(self.pax).get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(r.status_code, 200, r.content[:160])
        self.assertEqual(r.json()['payment_status'], 'pending')
