from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()
HIDDEN = ("ZorbaDriverQ", "KZZ999Q", "0700000099")


class AnonymousTripPrivacyTests(APITestCase):
    def setUp(self):
        cache.clear()
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(
            company=co, name="RouteQ7", start_point="A", end_point="B",
            price=Decimal("800.00"))
        driver = Driver.objects.create(
            name="ZorbaDriverQ", phone_number="0700000099",
            bus_number="KZZ999Q", company=co)
        self.trip = Trip.objects.create(
            route=route, driver=driver,
            departure_at=timezone.now() + timedelta(hours=1),
            capacity=10, status="scheduled")
        self.url = f"/api/trips/{self.trip.id}/"

    def test_anonymous_detail_hides_driver_identity(self):
        resp = self.client.get(self.url)
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("RouteQ7", body)
        for secret in HIDDEN:
            self.assertNotIn(secret, body, f"anonymous trip detail leaked {secret}")

    def test_logged_in_passenger_still_sees_driver_bus(self):
        user = User.objects.create_user(
            username="pax", password="x", phone_number="+254711000091")
        self.client.force_authenticate(user=user)
        body = self.client.get(self.url).content.decode()
        self.assertIn("KZZ999Q", body)

    def _list(self, user=None):
        from companies.views import get_trips
        from rest_framework.test import APIRequestFactory, force_authenticate
        req = APIRequestFactory().get("/api/trips/")
        if user is not None:
            force_authenticate(req, user=user)
        resp = get_trips(req)
        resp.render()
        return resp

    def test_anonymous_list_hides_driver_identity(self):
        resp = self._list()
        body = resp.content.decode()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("RouteQ7", body)
        for secret in HIDDEN:
            self.assertNotIn(secret, body, f"anonymous trip list leaked {secret}")

    def test_logged_in_list_still_shows_driver_bus(self):
        user = User.objects.create_user(
            username="pax2", password="x", phone_number="+254711000092")
        self.assertIn("KZZ999Q", self._list(user).content.decode())
