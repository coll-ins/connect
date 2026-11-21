"""A route-restricted operator sees only the parcels of routes they handle."""
from decimal import Decimal

from django.test import TestCase

from bookings.tests.review_base import WorldMixin
from companies.models import PickupStage
from deliveries.models import Parcel


class ParcelRouteScopeTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        drop = PickupStage.objects.create(
            route=self.r1, name='S1b', order=2, latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
        self.parcel = Parcel.objects.create(
            sender=self.pax, trip=self.trip1, pickup_stage=self.s1, dropoff_stage=drop,
            size='small', description='Box', receiver_name='Recv',
            receiver_phone='+254712345678', price=Decimal('150.00'), status='paid')

    def test_restricted_operator_cannot_open_a_parcel_of_an_unassigned_route(self):
        r = self.api(self.op_r2).get(f'/api/deliveries/{self.parcel.id}/')
        self.assertEqual(r.status_code, 404, r.content[:200])

    def test_restricted_operator_company_list_omits_the_unassigned_route(self):
        r = self.api(self.op_r2).get('/api/deliveries/company/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_unrestricted_operator_and_manager_still_see_the_parcel(self):
        for user in (self.op_all, self.mgr):
            self.assertEqual(
                self.api(user).get(f'/api/deliveries/{self.parcel.id}/').status_code, 200, user.username)
            listed = self.api(user).get('/api/deliveries/company/').json()
            self.assertEqual([p['id'] for p in listed], [self.parcel.id], user.username)

    def test_restricted_operator_sees_the_parcel_once_the_route_is_assigned(self):
        self.op_r2.assigned_routes.add(self.r1)
        self.assertEqual(self.api(self.op_r2).get(f'/api/deliveries/{self.parcel.id}/').status_code, 200)
        listed = self.api(self.op_r2).get('/api/deliveries/company/').json()
        self.assertEqual([p['id'] for p in listed], [self.parcel.id])
