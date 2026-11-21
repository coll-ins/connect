"""A signed charge.success redelivered after the hire completed stays a no-op."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import UnappliedPayment
from bookings.tests.review_base import WorldMixin
from bookings.tests.sim import fake_gateway as fg
from charters.models import CharterRequest


class CharterReplayAfterProgressTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.charter = CharterRequest.objects.create(
            passenger=self.pax, company=self.co, driver=self.drv, purpose='School trip',
            pickup_location='Karen', destination='Nakuru',
            depart_at=timezone.now() + timedelta(days=3), passenger_count=40,
            contact_name='T', contact_phone='+254712345678', status='quoted',
            quote_price=Decimal('20000.00'),
            quote_valid_until=timezone.now() + timedelta(hours=48))
        self.ref = f'CHT-{self.charter.id}-ABCDEFGHJK'
        self.client = APIClient()

    def post(self, ref=None):
        return fg.post_event(self.client, {'event': 'charge.success', 'data': {
            'reference': ref or self.ref, 'amount': 2000000, 'currency': 'KES', 'status': 'success'}})

    def test_replayed_charge_after_the_hire_completed_is_not_refunded(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(CharterRequest.objects.get(pk=self.charter.pk).status, 'confirmed')
        CharterRequest.objects.filter(pk=self.charter.pk).update(status='completed')
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(CharterRequest.objects.get(pk=self.charter.pk).status, 'completed')
        self.assertEqual(
            UnappliedPayment.objects.filter(reference=self.ref).count(), 0,
            list(UnappliedPayment.objects.values('status', 'reason')))
        self.fake.customer_pays(self.ref, 20000)
        call_command('process_unapplied', stdout=StringIO())
        self.assertEqual(self.fake.accepted_refunds(self.ref), [])

    def test_a_different_reference_on_a_completed_hire_is_still_refunded(self):
        self.assertEqual(self.post().status_code, 200)
        CharterRequest.objects.filter(pk=self.charter.pk).update(status='completed')
        other = f'CHT-{self.charter.id}-ZZZZZZZZZZ'
        self.fake.customer_pays(other, 20000)
        self.assertEqual(self.post(ref=other).status_code, 200)
        self.assertEqual(UnappliedPayment.objects.get(reference=other).status, 'refund_due')
