from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
PIN = "739204"


def mk(username, phone, **extra):
    return User.objects.create_user(
        username=username, password="x", phone_number=phone, **extra)


class PinNeverLeaksTests(APITestCase):
    def setUp(self):
        cache.clear()
        co = Company.objects.create(name="A", description="d", areas_served="N")
        other = Company.objects.create(name="B", description="d", areas_served="N")
        route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        stage = PickupStage.objects.create(
            route=route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        self.driver = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=co)
        trip = Trip.objects.create(
            route=route, driver=self.driver,
            departure_at=timezone.now() - timedelta(minutes=5),
            capacity=10, status="boarding")
        self.owner = mk("own", "+254711000001")
        self.booking = Booking.objects.create(
            user=self.owner, route=route, trip=trip, driver=self.driver,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="confirmed",
            verification_pin=PIN)
        Payment.objects.create(
            booking=self.booking, amount=Decimal("800.00"),
            method="cash", status="confirmed")
        self.drv_user = mk("drv", "+254711000002", role="driver", company=co)
        self.manager = mk("mgr", "+254711000003", role="company_manager", company=co)
        self.operator = mk("opr", "+254711000004", role="company_operator", company=co)
        self.auditor = mk("aud", "+254711000005", role="company_auditor", company=co)
        self.other_mgr = mk("omg", "+254711000006", role="company_manager", company=other)
        self.stranger = mk("str", "+254711000007")

    def _get(self, user, url):
        self.client.force_authenticate(user=user)
        with patch("bookings.views.is_driver_account_for",
                   return_value=(user.pk == self.drv_user.pk)):
            return self.client.get(url)

    def test_pin_never_reaches_anyone_but_the_owner(self):
        bid = self.booking.id
        number = self.booking.booking_number
        detail = reverse("bookings:get-booking-detail", args=[bid])
        cases = [
            (self.drv_user, "driver list", reverse("bookings:get-driver-bookings", args=[self.driver.id])),
            (self.manager, "manager all", reverse("bookings:get-all-bookings")),
            (self.manager, "manager detail", detail),
            (self.operator, "operator all", reverse("bookings:get-all-bookings")),
            (self.operator, "operator detail", detail),
            (self.auditor, "auditor receipts", reverse("bookings:auditor-receipt-search") + f"?search={number}"),
            (self.auditor, "auditor detail", detail),
            (self.other_mgr, "other-company all", reverse("bookings:get-all-bookings")),
            (self.other_mgr, "other-company detail", detail),
            (self.stranger, "stranger my", reverse("bookings:get-my-bookings")),
            (self.stranger, "stranger records", reverse("bookings:passenger-records")),
            (self.stranger, "stranger detail", detail),
        ]
        reached = []
        for user, label, url in cases:
            resp = self._get(user, url)
            body = resp.content.decode()
            self.assertNotIn(PIN, body, f"{label} leaked the PIN")
            if resp.status_code == 200 and number in body:
                reached.append(label)
        self.assertGreaterEqual(len(reached), 2, f"too few endpoints exercised: {reached}")

    def test_owner_sees_pin_only_while_confirmed(self):
        url = reverse("bookings:passenger-records")
        self.client.force_authenticate(user=self.owner)
        self.assertIn(PIN, self.client.get(url).content.decode())
        Booking.objects.filter(pk=self.booking.pk).update(status="cancelled")
        self.assertNotIn(PIN, self.client.get(url).content.decode())


    def test_my_bookings_shows_pin_to_owner_only_while_confirmed(self):
        url = reverse("bookings:get-my-bookings")
        self.client.force_authenticate(user=self.owner)
        self.assertIn(PIN, self.client.get(url).content.decode())
        Booking.objects.filter(pk=self.booking.pk).update(status="cancelled")
        self.assertNotIn(PIN, self.client.get(url).content.decode())

    def test_auditor_receipt_search_works_and_hides_pin(self):
        url = reverse("bookings:auditor-receipt-search") + f"?search={self.booking.booking_number}"
        resp = self._get(self.auditor, url)
        self.assertEqual(resp.status_code, 200, resp.content.decode()[:300])
        self.assertIn(self.booking.booking_number, resp.content.decode())
        self.assertNotIn(PIN, resp.content.decode())
