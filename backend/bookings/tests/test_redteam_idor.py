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
NO = (401, 403)


class RedTeamIdorTests(APITestCase):
    def _world(self, co, phone):
        route = Route.objects.create(
            company=co, name=f"R{co.id}", start_point="A", end_point="B",
            price=Decimal("100.00"))
        stage = PickupStage.objects.create(
            route=route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        drv = Driver.objects.create(
            name=f"D{co.id}", phone_number=phone, bus_number=f"K{co.id}", company=co)
        trip = Trip.objects.create(
            route=route, driver=drv,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        return route, stage, drv, trip

    def _booking(self, user, world):
        route, stage, drv, trip = world
        return Booking.objects.create(
            user=user, route=route, trip=trip, driver=drv, pickup_stage=stage,
            pickup_location="S1", seats=1, total_amount=Decimal("100.00"),
            status="confirmed")

    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.co2 = Company.objects.create(name="B", description="d", areas_served="N")
        self.wa = self._world(self.co, "0700000001")
        self.wb = self._world(self.co2, "0700000008")
        mk = User.objects.create_user
        self.owner = mk(username="own", password="x", phone_number="0711000001")
        self.stranger = mk(username="str", password="x", phone_number="0711000002")
        self.mgr = mk(username="m1", password="x", phone_number="0711000003",
                      company=self.co, role="company_manager")
        self.mgr_b = mk(username="m2", password="x", phone_number="0711000004",
                        company=self.co2, role="company_manager")
        self.aud = mk(username="aud", password="x", phone_number="0711000005",
                      company=self.co, role="company_auditor")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")
        self.drv_other = mk(username="d9", password="x", phone_number="0700000009",
                            company=self.co, role="driver")
        self.booking = self._booking(self.owner, self.wa)
        self.booking_b = self._booking(self.stranger, self.wb)

    def _as(self, user):
        self.client.force_authenticate(user=user)

    def test_booking_list_is_company_scoped(self):
        url = reverse("bookings:get-all-bookings")
        self._as(self.mgr)
        r = self.client.get(url)
        ids = {row["booking_id"] for row in r.data}
        self.assertEqual(r.status_code, 200)
        self.assertIn(self.booking.id, ids)
        self.assertNotIn(self.booking_b.id, ids)
        self.assertEqual(
            self.client.get(url, {"company_id": self.co2.id}).status_code, 403)
        for label, u in (("passenger", self.owner), ("driver", self.drv1), ("anon", None)):
            with self.subTest(who=label):
                self._as(u)
                self.assertIn(self.client.get(url).status_code, NO)

    def test_booking_detail_access(self):
        url = reverse("bookings:get-booking-detail", args=[self.booking.id])
        for label, u in (("anon", None), ("stranger", self.stranger),
                         ("other manager", self.mgr_b)):
            with self.subTest(attacker=label):
                self._as(u)
                self.assertIn(self.client.get(url).status_code, NO)
        for label, u in (("owner", self.owner), ("manager", self.mgr), ("auditor", self.aud)):
            with self.subTest(viewer=label):
                self._as(u)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_passenger_location_is_owner_only(self):
        url = reverse("bookings:update-passenger-location", args=[self.booking.id])
        body = {"latitude": -1.28, "longitude": 36.82}
        for label, u in (("stranger", self.stranger), ("manager", self.mgr),
                         ("driver", self.drv1)):
            with self.subTest(attacker=label):
                self._as(u)
                self.assertEqual(self.client.post(url, body, format="json").status_code, 404)
        self._as(self.owner)
        self.assertEqual(self.client.post(url, body, format="json").status_code, 200)

    def test_stage_departure_roles(self):
        url = reverse("bookings:set-stage-departure", args=[self.booking.id])
        for label, u in (("anon", None), ("passenger", self.owner),
                         ("stranger", self.stranger), ("other manager", self.mgr_b),
                         ("auditor", self.aud), ("driver", self.drv1)):
            with self.subTest(attacker=label):
                self._as(u)
                self.assertIn(self.client.post(url, {"minutes": 5}, format="json").status_code, NO)
        self._as(self.mgr)
        self.assertEqual(self.client.post(url, {"minutes": 5}, format="json").status_code, 200)

    def test_stage_departure_rejects_absurd_minutes(self):
        url = reverse("bookings:set-stage-departure", args=[self.booking.id])
        self._as(self.mgr)
        for m in (10 ** 15, -5, 100000):
            with self.subTest(minutes=m):
                self.assertEqual(self.client.post(url, {"minutes": m}, format="json").status_code, 400)

    def test_driver_bookings_access(self):
        url = reverse("bookings:get-driver-bookings", args=[self.wa[2].id])
        for label, u in (("anon", None), ("stranger", self.stranger), ("passenger", self.owner),
                         ("other manager", self.mgr_b), ("other driver", self.drv_other)):
            with self.subTest(attacker=label):
                self._as(u)
                self.assertIn(self.client.get(url).status_code, NO)
        for label, u in (("driver", self.drv1), ("manager", self.mgr)):
            with self.subTest(viewer=label):
                self._as(u)
                self.assertEqual(self.client.get(url).status_code, 200)
