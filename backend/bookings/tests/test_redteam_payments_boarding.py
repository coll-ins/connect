from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
DENIED = (401, 403)
LEAKS = ("RT_REF_1", "payment_id", "confirmed_at")


class RedTeamPaymentBoardingTests(APITestCase):
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
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal("100.00"), method="digital",
            status="confirmed", provider_reference="RT_REF_1")

    def _pay_status(self, user):
        self.client.force_authenticate(user=user)
        url = reverse("bookings:payment-status", args=[self.booking.id])
        r = self.client.get(url)
        if r.status_code == 405:
            r = self.client.post(url, {}, format="json")
        return r

    def _board(self, user, pin="0000"):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse("bookings:verify-boarding", args=[self.booking.id]),
            {"boarding_pin": pin}, format="json")

    # ---- payment status ----
    def test_anonymous_denied_payment_status(self):
        self.assertIn(self._pay_status(None).status_code, DENIED)

    def test_non_owners_get_no_payment_data(self):
        for label, user in (("stranger", self.stranger), ("other manager", self.mgr_b),
                            ("own manager", self.mgr), ("driver", self.drv1)):
            with self.subTest(attacker=label):
                r = self._pay_status(user)
                self.assertIn(r.status_code, (200, 403, 404))
                for leak in LEAKS:
                    self.assertNotIn(leak, r.content.decode())

    def test_owner_sees_own_payment(self):
        r = self._pay_status(self.owner)
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r.json()["reference"], "RT_REF_1")

    def test_paystack_timeout_does_not_500(self):
        Payment.objects.filter(pk=self.payment.pk).update(status="pending")
        with patch("bookings.views.requests.get",
                   side_effect=requests.ConnectionError("down")):
            r = self._pay_status(self.owner)
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r.json()["payment_status"], "pending")

    # ---- boarding ----
    def test_unauthorized_cannot_board(self):
        for label, user in (("anonymous", None), ("owner passenger", self.owner),
                            ("stranger", self.stranger), ("other manager", self.mgr_b),
                            ("other driver", self.drv2)):
            with self.subTest(attacker=label):
                self.assertIn(self._board(user).status_code, DENIED)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "confirmed")
        self.assertFalse(BoardingEvent.objects.filter(booking=self.booking).exists())

    def test_authorized_users_pass_the_gate(self):
        for user in (self.drv1, self.mgr):
            r = self._board(user)
            self.assertNotIn(r.status_code, (401, 403, 404, 405), (user.username, r.content[:200]))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "confirmed")
