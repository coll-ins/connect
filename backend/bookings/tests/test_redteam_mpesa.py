from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
MPESA = "bookings:initialize-mpesa-payment"


class RedTeamMpesaTests(APITestCase):
    def setUp(self):
        cache.clear()
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
        self.booking = Booking.objects.create(
            user=self.owner, route=route, trip=trip, driver=d1,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="pending")
        self.client.force_authenticate(user=self.owner)

    def _post(self, phone):
        return self.client.post(
            reverse(MPESA, args=[self.booking.id]),
            {"phone_number": phone}, format="json")

    def test_push_requests_are_rate_limited(self):
        from bookings.views import MpesaPushThrottle
        with patch.dict(MpesaPushThrottle.THROTTLE_RATES, {"mpesa_push": "3/hour"}), \
             patch("bookings.views.requests.post") as post:
            codes = [self._post("0712345678").status_code for _ in range(5)]
        self.assertEqual(codes, [400, 400, 400, 429, 429])
        post.assert_not_called()

    def test_refused_charge_does_not_block_a_retry(self):
        refused = MagicMock(status_code=400)
        refused.json.return_value = {"status": False, "message": "Invalid phone"}
        ok = MagicMock(status_code=200)
        ok.json.return_value = {
            "status": True, "data": {"reference": "x", "status": "pay_offline"}}
        with patch("bookings.views.requests.post", side_effect=[refused, ok]):
            first = self._post("+254712345678")
            second = self._post("+254712345679")
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 200)

    def test_unknown_outcome_keeps_the_payment_in_progress(self):
        with patch("bookings.views.requests.post",
                   side_effect=requests.RequestException("timeout")):
            self.assertEqual(self._post("+254712345678").status_code, 502)
        with patch("bookings.views.requests.post") as post:
            self.assertEqual(self._post("+254712345678").status_code, 409)
            post.assert_not_called()
