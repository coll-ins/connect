from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


def end_trip_url(driver_id):
    for name in ("bookings:driver-end-trip", "bookings:driver_end_trip",
                 "driver-end-trip", "driver_end_trip"):
        try:
            return reverse(name, args=[driver_id])
        except NoReverseMatch:
            continue
    raise AssertionError("Unknown URL name for driver_end_trip; send the urls.py grep")


class RedTeamEndTripTests(APITestCase):
    def setUp(self):
        cache.clear()
        co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        self.driver = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=co)
        self.user = User.objects.create_user(
            username="drv", password="x", phone_number="+254700000001")
        self.client.force_authenticate(user=self.user)

    def _trip(self, minutes_ago):
        return Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() - timedelta(minutes=minutes_ago),
            capacity=10, status="departed")

    def _end(self):
        with patch("bookings.views.is_driver_account_for", return_value=True):
            return self.client.post(end_trip_url(self.driver.id))

    def test_cannot_end_right_after_departure(self):
        trip = self._trip(minutes_ago=2)
        self.assertEqual(self._end().status_code, 409)
        trip.refresh_from_db()
        self.assertEqual(trip.status, "departed")

    def test_can_end_after_minimum_duration(self):
        trip = self._trip(minutes_ago=25)
        self.assertEqual(self._end().status_code, 200)
        trip.refresh_from_db()
        self.assertEqual(trip.status, "completed")
