from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture
from companies.models import PickupStage

User = get_user_model()
STRONG = 'Tr4velSafe-2026'
LINE = {'type': 'LineString', 'coordinates': [[36.80, -1.28], [36.70, -1.25]]}


class RoutePlanViaTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('2401')
        self.route = self.trip.route
        PickupStage.objects.create(
            route=self.route, name='R24 Stage',
            latitude=Decimal('-1.265000'), longitude=Decimal('36.750000'), order=1)
        manager = User.objects.create_user(
            username='r24_mgr', password=STRONG, phone_number='+254733002401',
            role='company_manager', company=self.route.company)
        self.client.force_authenticate(user=manager)
        self.url = f'/api/companies/routes/{self.route.id}/plan/'
        self.start = {'name': 'CBD', 'latitude': -1.286, 'longitude': 36.817}
        self.end = {'name': 'Kikuyu', 'latitude': -1.246, 'longitude': 36.663}
        self.via = {'latitude': -1.262, 'longitude': 36.77}

    def _plan(self, **body):
        payload = {'start': self.start, 'end': self.end, **body}
        with patch('companies.routing.road_line', return_value=(LINE, 12000.0)) as mock:
            response = self.client.post(self.url, payload, format='json')
        return response, mock

    def test_stages_do_not_steer_the_line(self):
        response, mock = self._plan(via=[self.via])
        self.assertEqual(response.status_code, 200, response.data)
        points = mock.call_args[0][0]
        self.assertEqual(points, [(-1.286, 36.817), (-1.262, 36.77), (-1.246, 36.663)])

    def test_preview_does_not_save_road_points(self):
        self._plan(via=[self.via])
        self.route.refresh_from_db()
        self.assertFalse(self.route.via_points)

    def test_saved_road_points_survive_a_later_preview(self):
        response, _ = self._plan(via=[self.via], apply=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.route.refresh_from_db()
        self.assertEqual(len(self.route.via_points), 1)
        response, mock = self._plan()          # no 'via' sent
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(mock.call_args[0][0]), 3)

    def test_sending_an_empty_list_clears_the_road_points(self):
        self._plan(via=[self.via], apply=True)
        response, _ = self._plan(via=[], apply=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.route.refresh_from_db()
        self.assertEqual(self.route.via_points, [])
