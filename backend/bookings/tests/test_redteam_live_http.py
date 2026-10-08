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


class RedTeamLiveHttpTests(APITestCase):
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
        self.aud = mk(username="aud", password="x", phone_number="0711000005",
                      company=self.co, role="company_auditor")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")
        self.booking = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("100.00"), status="confirmed")

    def _get(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(
            reverse("bookings:booking-live-location", args=[self.booking.id]))

    def test_outsiders_refused(self):
        for label, u in (("anonymous", None), ("stranger", self.stranger),
                         ("other manager", self.mgr_b)):
            with self.subTest(attacker=label):
                self.assertIn(self._get(u).status_code, (401, 403))

    def test_legitimate_viewers_allowed(self):
        for label, u in (("owner", self.owner), ("manager", self.mgr),
                         ("auditor", self.aud), ("driver", self.drv1)):
            with self.subTest(viewer=label):
                self.assertEqual(self._get(u).status_code, 200)

    def test_closed_booking_gives_no_location(self):
        for st in ("cancelled", "no_show", "completed"):
            Booking.objects.filter(pk=self.booking.pk).update(status=st)
            for label, u in (("owner", self.owner), ("driver", self.drv1)):
                with self.subTest(booking_status=st, viewer=label):
                    self.assertGreaterEqual(self._get(u).status_code, 400)
