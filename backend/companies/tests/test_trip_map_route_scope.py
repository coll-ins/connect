"""The trip-specific route map hides passengers from a route-restricted operator."""
from decimal import Decimal

from django.test import TestCase

from bookings.models import Booking
from bookings.tests.review_base import WorldMixin


class TripMapRouteScopeTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        Booking.objects.filter(pk=b.pk).update(
            passenger_latitude=Decimal('-1.123456'), passenger_longitude=Decimal('36.654321'))
        self.url = f'/api/companies/routes/{self.r1.id}/map/?trip_id={self.trip1.id}'

    def test_restricted_operator_gets_no_passenger_data_from_trip_map(self):
        r = self.api(self.op_r2).get(self.url)
        body = r.content.decode()
        self.assertEqual(r.status_code, 403, body[:300])
        self.assertNotIn('+254733000001', body)
        self.assertNotIn('36.654321', body)

    def test_unrestricted_operator_and_manager_still_see_passengers(self):
        for user in (self.op_all, self.mgr):
            r = self.api(user).get(self.url)
            self.assertEqual(r.status_code, 200, (user.username, r.content[:200]))
            self.assertIn('+254733000001', r.content.decode(), user.username)

    def test_restricted_operator_sees_passengers_on_an_assigned_route(self):
        self.op_r2.assigned_routes.add(self.r1)
        r = self.api(self.op_r2).get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn('+254733000001', r.content.decode())
