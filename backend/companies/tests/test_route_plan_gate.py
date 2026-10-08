from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route

User = get_user_model()
LINE = {"type": "LineString", "coordinates": [[36.80, -1.28], [36.82, -1.28], [36.84, -1.28]]}
END = {"name": "B", "latitude": -1.28, "longitude": 36.84}
START = {"name": "A", "latitude": -1.28, "longitude": 36.80}
OLD = {"type": "LineString", "coordinates": [[36.80, -1.28], [36.84, -1.28]]}


class RoutePlanGateTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.co2 = Company.objects.create(name="B", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=self.co, name="R", start_point="A", end_point="B",
            price=Decimal("100.00"), geometry=OLD)
        self.mgr = User.objects.create_user(
            username="m1", password="x", phone_number="0711000003",
            company=self.co, role="company_manager")
        self.mgr_b = User.objects.create_user(
            username="m2", password="x", phone_number="0711000004",
            company=self.co2, role="company_manager")
        self.op = User.objects.create_user(
            username="op", password="x", phone_number="0711000005",
            company=self.co, role="company_operator")
        self.url = reverse("route_plan", args=[self.route.id])

    def _stage(self, lat, lng):
        return PickupStage.objects.create(
            route=self.route, name="S", latitude=Decimal(lat),
            longitude=Decimal(lng), order=1)

    def _post(self, user, **extra):
        self.client.force_authenticate(user=user)
        body = {"start": START, "end": END, **extra}
        with patch("companies.routing.road_line", return_value=(LINE, 4000.0)):
            return self.client.post(self.url, body, format="json")

    def test_save_refused_when_a_stage_would_be_off_the_line(self):
        self._stage("-1.300000", "36.820000")  # ~2.2 km south of the line
        r = self._post(self.mgr, apply=True)
        self.assertEqual(r.status_code, 422, r.content[:300])
        self.route.refresh_from_db()
        self.assertEqual(self.route.geometry, OLD)

    def test_preview_never_saves_and_reports_off_route(self):
        self._stage("-1.300000", "36.820000")
        r = self._post(self.mgr)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["applied"])
        self.assertEqual(len(r.json()["off_route_stages"]), 1)
        self.route.refresh_from_db()
        self.assertEqual(self.route.geometry, OLD)

    def test_save_succeeds_and_equals_preview_when_stages_on_line(self):
        self._stage("-1.280000", "36.820000")
        preview = self._post(self.mgr).json()["geometry"]
        r = self._post(self.mgr, apply=True)
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.route.refresh_from_db()
        self.assertEqual(self.route.geometry, preview)

    def test_other_company_and_non_manager_cannot_plan_or_save(self):
        for user in (self.mgr_b, self.op, None):
            r = self._post(user, apply=True)
            self.assertIn(r.status_code, (401, 403))
        self.route.refresh_from_db()
        self.assertEqual(self.route.geometry, OLD)
