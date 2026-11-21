"""A route-restricted operator never reads passengers of a route they do not handle."""
from django.test import TestCase

from bookings.tests.review_base import WorldMixin


class DriverBookingsRouteScopeTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.booking(self.pax, self.trip1)

    def get(self, user):
        return self.api(user).get(f'/api/bookings/driver/{self.drv.id}/')

    def test_route_restricted_operator_cannot_read_passengers_of_unassigned_route(self):
        r = self.get(self.op_r2)
        self.assertEqual(r.status_code, 403, r.content[:300])
        self.assertNotIn('+254733000001', r.content.decode())

    def test_restricted_operator_reads_the_route_it_is_assigned(self):
        self.op_r2.assigned_routes.add(self.r1)
        r = self.get(self.op_r2)
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(len(r.json()['bookings']), 1)

    def test_unrestricted_operator_and_manager_still_read_passengers(self):
        for user in (self.op_all, self.mgr):
            r = self.get(user)
            self.assertEqual(r.status_code, 200, (user.username, r.content[:300]))
            self.assertEqual(len(r.json()['bookings']), 1, user.username)

    def test_restricted_operator_gets_no_driver_trip_payload_without_an_active_trip(self):
        # No trip means no passenger data, so the driver card is still shown.
        self.trip1.status = 'completed'
        self.trip1.save()
        r = self.get(self.op_r2)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['bookings'], [])
