"""A signed charge.success redelivered after the parcel moved on stays a no-op.

Before the fix the replay was classed as a business conflict and queued a
full refund of a parcel that was already delivered.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from bookings.models import UnappliedPayment
from bookings.tests.review_base import WorldMixin
from bookings.tests.sim import fake_gateway as fg
from companies.models import PickupStage
from deliveries.models import Parcel
from rest_framework.test import APIClient


def charge(reference, subunits, currency='KES'):
    return {'event': 'charge.success', 'data': {
        'reference': reference, 'amount': subunits, 'currency': currency, 'status': 'success'}}


class ParcelReplayAfterProgressTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        drop = PickupStage.objects.create(
            route=self.r1, name='S1b', order=2, latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
        self.parcel = Parcel.objects.create(
            sender=self.pax, trip=self.trip1, pickup_stage=self.s1, dropoff_stage=drop,
            size='small', description='Box', receiver_name='R',
            receiver_phone='+254712345678', price=Decimal('150.00'))
        self.ref = f'PCL-{self.parcel.id}-ABCDEFGHJK'
        self.client = APIClient()

    def post(self, subunits=15000, ref=None):
        return fg.post_event(self.client, charge(ref or self.ref, subunits))

    def test_replayed_charge_after_each_later_status_is_not_refunded(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(Parcel.objects.get(pk=self.parcel.pk).status, 'paid')
        for later in ('picked_up', 'delivered', 'failed_delivery'):
            Parcel.objects.filter(pk=self.parcel.pk).update(status=later)
            self.assertEqual(self.post().status_code, 200, later)
            self.assertEqual(Parcel.objects.get(pk=self.parcel.pk).status, later)
            self.assertEqual(
                UnappliedPayment.objects.filter(reference=self.ref).count(), 0,
                (later, list(UnappliedPayment.objects.values('status', 'reason'))))
        # and the sweep must not send money back for a parcel that went through
        self.fake.customer_pays(self.ref, 150)
        call_command('process_unapplied', stdout=StringIO())
        self.assertEqual(self.fake.accepted_refunds(self.ref), [])

    def test_a_different_reference_on_a_progressed_parcel_is_still_refunded(self):
        self.assertEqual(self.post().status_code, 200)
        Parcel.objects.filter(pk=self.parcel.pk).update(status='delivered')
        other = f'PCL-{self.parcel.id}-ZZZZZZZZZZ'
        self.fake.customer_pays(other, 150)
        self.assertEqual(self.post(ref=other).status_code, 200)
        row = UnappliedPayment.objects.get(reference=other)
        self.assertEqual((row.status, row.amount), ('refund_due', Decimal('150.00')))
        call_command('process_unapplied', stdout=StringIO())
        self.assertEqual(self.fake.refunded_subunits(other), 15000)

    def test_a_charge_on_a_parcel_cancelled_while_unpaid_is_still_refunded(self):
        # The checkout reference is stored before payment; it is not proof of payment.
        Parcel.objects.filter(pk=self.parcel.pk).update(
            status='cancelled', provider_reference=self.ref)
        self.fake.customer_pays(self.ref, 150)
        self.assertEqual(self.post().status_code, 200)
        row = UnappliedPayment.objects.get(reference=self.ref)
        self.assertEqual(row.status, 'refund_due')
