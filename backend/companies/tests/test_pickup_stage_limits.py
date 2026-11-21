"""Pickup stage coordinates are range checked; a stage a parcel uses cannot be deleted."""
from decimal import Decimal

from django.test import TestCase

from bookings.tests.review_base import WorldMixin
from companies.models import PickupStage
from deliveries.models import Parcel


class StageCoordinateTests(WorldMixin, TestCase):
    def create(self, lat, lng):
        return self.api(self.mgr).post(
            f'/api/companies/routes/{self.r1.id}/pickup-stages/create/',
            {'name': 'Range stage', 'latitude': lat, 'longitude': lng, 'order': 7}, format='json')

    def test_latitude_outside_90_is_400(self):
        for lat in ('91', '-91', '181'):
            r = self.create(lat, '36.8')
            self.assertEqual(r.status_code, 400, (lat, r.content[:160]))
            self.assertIn('latitude', r.json())

    def test_longitude_outside_180_is_400(self):
        for lng in ('181', '-181'):
            r = self.create('-1.1', lng)
            self.assertEqual(r.status_code, 400, (lng, r.content[:160]))
            self.assertIn('longitude', r.json())

    def test_the_limits_themselves_and_normal_values_are_accepted(self):
        self.assertEqual(self.create('-1.1', '36.8').status_code, 201)
        self.assertEqual(self.create('90', '180').status_code, 201)

    def test_updating_a_stage_to_a_bad_latitude_is_400(self):
        r = self.api(self.mgr).patch(f'/api/companies/pickup-stages/{self.s1.id}/', {'latitude': '95'}, format='json')
        self.assertEqual(r.status_code, 400, r.content[:160])


class StageDeleteTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.s1b = PickupStage.objects.create(
            route=self.r1, name='S1b', order=2, latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
        self.parcel = Parcel.objects.create(
            sender=self.pax, trip=self.trip1, pickup_stage=self.s1, dropoff_stage=self.s1b, description='box',
            size='small', receiver_name='Rec Eiver', receiver_phone='+254711900009', price=Decimal('300'))

    def test_deleting_a_stage_a_parcel_uses_is_409_and_keeps_it(self):
        for stage in (self.s1, self.s1b):
            r = self.api(self.mgr).delete(f'/api/companies/pickup-stages/{stage.id}/')
            self.assertEqual(r.status_code, 409, r.content[:160])
            self.assertTrue(PickupStage.objects.filter(pk=stage.pk).exists())

    def test_deleting_an_unused_stage_still_works(self):
        free = PickupStage.objects.create(
            route=self.r1, name='Free', order=3, latitude=Decimal('-1.4'), longitude=Decimal('36.9'))
        r = self.api(self.mgr).delete(f'/api/companies/pickup-stages/{free.id}/')
        self.assertEqual(r.status_code, 200, r.content[:160])
        self.assertFalse(PickupStage.objects.filter(pk=free.pk).exists())
