from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
DENIED = (401, 403)
HIDDEN = (401, 403, 404)


class RedTeamIDORTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.co2 = Company.objects.create(name="B", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=self.co, name="R", start_point="A", end_point="B",
            price=Decimal("100.00"))
        self.stage = PickupStage.objects.create(
            route=self.route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        self.d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=self.co)
        self.d2 = Driver.objects.create(
            name="D2", phone_number="0700000002", bus_number="K2", company=self.co)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.d1,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        mk = User.objects.create_user
        self.owner = mk(username="own", password="x", phone_number="0711000001")
        self.stranger = mk(username="str", password="x", phone_number="0711000002")
        self.mgr = mk(username="m1", password="x", phone_number="0711000003",
                      company=self.co, role="company_manager")
        self.mgr_b = mk(username="m2", password="x", phone_number="0711000004",
                        company=self.co2, role="company_manager")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")
        self.drv2 = mk(username="d2", password="x", phone_number="0700000002",
                       company=self.co, role="driver")
        self.booking = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("100.00"), status="confirmed")

    def _call(self, user, method, name, arg):
        self.client.force_authenticate(user=user)
        return getattr(self.client, method)(
            reverse(f"bookings:{name}", args=[arg]), {}, format="json")

    def _attacks(self):
        b, d = self.booking.id, self.d1.id
        return [
            ("get", "get-booking-detail", b),
            ("get", "booking-live-location", b),
            ("post", "update-passenger-location", b),
            ("get", "get-driver-bookings", d),
        ]

    def _assert_denied(self, user, label, skip=()):
        for method, name, arg in self._attacks():
            if name in skip:
                continue
            with self.subTest(attacker=label, endpoint=name):
                r = self._call(user, method, name, arg)
                self.assertIn(r.status_code, HIDDEN, r.content[:200])

    def test_anonymous_denied_everywhere(self):
        self._assert_denied(None, "anonymous")

    def test_stranger_passenger_denied_everywhere(self):
        self._assert_denied(self.stranger, "stranger")

    def test_other_company_manager_denied_everywhere(self):
        self._assert_denied(self.mgr_b, "other-company manager")

    def test_other_driver_same_company_denied_booking_endpoints(self):
        self._assert_denied(self.drv2, "other driver", skip=())

    def test_positive_controls(self):
        self.assertEqual(self._call(self.owner, "get", "get-booking-detail", self.booking.id).status_code, 200)
        self.assertEqual(self._call(self.mgr, "get", "get-booking-detail", self.booking.id).status_code, 200)
        for user in (self.owner, self.mgr, self.drv1):
            r = self._call(user, "get", "booking-live-location", self.booking.id)
            self.assertNotIn(r.status_code, HIDDEN, (user.username, r.content[:200]))
        for user in (self.mgr, self.drv1):
            r = self._call(user, "get", "get-driver-bookings", self.d1.id)
            self.assertNotIn(r.status_code, HIDDEN, (user.username, r.content[:200]))
