from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class RouteMapPrivacyTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Own Co", description="d", areas_served="Nairobi")
        self.other_company = Company.objects.create(
            name="Other Co", description="d", areas_served="Nairobi")
        self.route = Route.objects.create(
            company=self.company, name="R", start_point="A",
            end_point="B", price=Decimal("100.00"))
        self.stage = PickupStage.objects.create(
            route=self.route, name="Stage1", latitude=Decimal("-1.285000"),
            longitude=Decimal("36.820000"), order=1)
        self.driver = Driver.objects.create(
            name="D", phone_number="0700000001", bus_number="KAA 1A",
            company=self.company)
        self.other_driver = Driver.objects.create(
            name="D2", phone_number="0700000002", bus_number="KAA 2A",
            company=self.company)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(days=1),
            capacity=10, status="scheduled")

        self.passenger = User.objects.create_user(
            username="p1", password="x", phone_number="0711000001")
        self.stranger = User.objects.create_user(
            username="p2", password="x", phone_number="0711000002")
        self.manager = User.objects.create_user(
            username="m1", password="x", phone_number="0711000003",
            company=self.company, role="company_manager")
        self.other_manager = User.objects.create_user(
            username="m2", password="x", phone_number="0711000004",
            company=self.other_company, role="company_manager")
        self.driver_user = User.objects.create_user(
            username="d1", password="x", phone_number="0700000001",
            company=self.company, role="driver")
        self.other_driver_user = User.objects.create_user(
            username="d2", password="x", phone_number="0700000002",
            company=self.company, role="driver")

        Booking.objects.create(
            user=self.passenger, route=self.route, trip=self.trip,
            driver=self.driver, pickup_stage=self.stage,
            pickup_location="Stage1", seats=1,
            total_amount=Decimal("100.00"), status="confirmed")

        self.url = reverse("route-map-data", args=[self.route.id])

    def _passengers(self, user=None):
        self.client.force_authenticate(user=user)
        r = self.client.get(self.url, {"trip_id": self.trip.id})
        self.assertEqual(r.status_code, 200)
        stage = next(s for s in r.json()["stages"] if s["name"] == "Stage1")
        return stage["passengers"], stage, r.content.decode()

    def test_anonymous_sees_counts_but_no_passengers(self):
        p, stage, raw = self._passengers(None)
        self.assertEqual(p, [])
        self.assertEqual(stage["booking_count"], 1)
        self.assertNotIn("passenger_phone", raw)
        self.assertNotIn("0711000001", raw)

    def test_other_passenger_sees_none(self):
        self.assertEqual(self._passengers(self.stranger)[0], [])

    def test_booking_owner_passenger_role_sees_none_here(self):
        self.assertEqual(self._passengers(self.passenger)[0], [])

    def test_other_company_manager_sees_none(self):
        self.assertEqual(self._passengers(self.other_manager)[0], [])

    def test_unassigned_driver_sees_none(self):
        self.assertEqual(self._passengers(self.other_driver_user)[0], [])

    def test_owning_manager_sees_passenger(self):
        self.assertEqual(len(self._passengers(self.manager)[0]), 1)

    def test_assigned_driver_sees_passenger(self):
        self.assertEqual(len(self._passengers(self.driver_user)[0]), 1)
