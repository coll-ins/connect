from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
PAY = "bookings:initialize-paystack-payment"
MPESA = "bookings:initialize-mpesa-payment"


class RedTeamPayInitTests(APITestCase):
    def setUp(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        stage = PickupStage.objects.create(
            route=route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=co)
        trip = Trip.objects.create(
            route=route, driver=d1,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        self.owner = User.objects.create_user(
            username="own", password="x", phone_number="+254711000001")
        self.stranger = User.objects.create_user(
            username="str", password="x", phone_number="+254711000002")
        self.booking = Booking.objects.create(
            user=self.owner, route=route, trip=trip, driver=d1,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="pending")

    def _post(self, name, user, body=None):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse(name, args=[self.booking.id]), body or {}, format="json")

    def test_other_users_cannot_start_payment(self):
        for name in (PAY, MPESA):
            for label, u in (("stranger", self.stranger), ("anon", None)):
                with self.subTest(endpoint=name, attacker=label), \
                     patch("bookings.views.requests.post") as post:
                    self.assertIn(self._post(name, u).status_code, (401, 403, 404))
                    post.assert_not_called()

    def test_closed_bookings_cannot_start_payment(self):
        for st in ("cancelled", "completed", "no_show"):
            Booking.objects.filter(pk=self.booking.pk).update(status=st)
            for name in (PAY, MPESA):
                with self.subTest(status=st, endpoint=name), \
                     patch("bookings.views.requests.post") as post:
                    self.assertEqual(self._post(name, self.owner).status_code, 400)
                    post.assert_not_called()

    def test_mpesa_rejects_malformed_numbers(self):
        for phone in ("0712345678", "+25471234567", "+2547123456789",
                      "+254abc4567890", "254712345678", "+1 555 0100"):
            with self.subTest(phone=phone), \
                 patch("bookings.views.requests.post") as post:
                r = self._post(MPESA, self.owner, {"phone_number": phone})
                self.assertEqual(r.status_code, 400)
                post.assert_not_called()
