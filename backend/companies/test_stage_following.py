from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture
from companies.models import PickupStage
from companies.routing import plan_line

User = get_user_model()
STRONG = 'Tr4velSafe-2026'
START = (-1.30, 36.80)
END = (-1.30, 36.90)
FAR = (-1.28, 36.85)        # about 2.2 km north of the plain road


def linear(points):
    coords = [[lng, lat] for lat, lng in points]
    return {'type': 'LineString', 'coordinates': coords}, 11000.0


class PlanLineTests(APITestCase):
    def test_a_stage_the_road_misses_is_pulled_in(self):
        with patch('companies.routing.road_line', side_effect=linear):
            geometry, _d, followed, skipped = plan_line(START, END, [], [(7, 'Far', *FAR)])
        self.assertEqual(followed, [7])
        self.assertEqual(skipped, [])
        self.assertIn([FAR[1], FAR[0]], geometry['coordinates'])

    def test_a_stage_that_makes_the_line_double_back_is_left_out(self):
        stub = {'type': 'LineString', 'coordinates': [
            [36.80, -1.30], [36.85, -1.30], [36.85, -1.2973],
            [36.85, -1.30], [36.90, -1.30]]}

        def fake(points):
            return linear(points) if len(points) == 2 else (stub, 1.0)

        side = (-1.2973, 36.85)      # about 300 m off the plain road
        with patch('companies.routing.road_line', side_effect=fake):
            geometry, _d, followed, skipped = plan_line(START, END, [], [(8, 'Side', *side)])
        self.assertEqual(followed, [])
        self.assertEqual(skipped, [8])
        self.assertEqual(geometry['coordinates'], [[36.80, -1.30], [36.90, -1.30]])

    def test_a_stage_already_on_the_road_causes_no_extra_call(self):
        near = (-1.2995, 36.85)      # about 55 m off
        with patch('companies.routing.road_line', side_effect=linear) as rl:
            _g, _d, followed, skipped = plan_line(START, END, [], [(9, 'On road', *near)])
        self.assertEqual((followed, skipped), ([], []))
        self.assertEqual(rl.call_count, 1)


class RoutePlanFollowStagesTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('2901')
        self.route = self.trip.route
        self.stage = PickupStage.objects.create(
            route=self.route, name='R29 Far', order=1,
            latitude=Decimal('-1.280000'), longitude=Decimal('36.850000'))
        manager = User.objects.create_user(
            username='r29_mgr', password=STRONG, phone_number='+254733002901',
            role='company_manager', company=self.route.company)
        self.client.force_authenticate(user=manager)
        self.url = f'/api/companies/routes/{self.route.id}/plan/'
        self.body = {
            'start': {'name': 'A', 'latitude': -1.30, 'longitude': 36.80},
            'end': {'name': 'B', 'latitude': -1.30, 'longitude': 36.90},
        }

    def _plan(self, **extra):
        with patch('companies.routing.road_line', side_effect=linear) as rl:
            response = self.client.post(self.url, {**self.body, **extra}, format='json')
        return response, rl

    def test_by_default_stages_do_not_steer_the_line(self):
        response, rl = self._plan()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(rl.call_count, 1)
        self.assertEqual([s['id'] for s in response.data['off_route_stages']], [self.stage.id])

    def test_follow_stages_pulls_the_line_through_the_missed_stage(self):
        response, _rl = self._plan(follow_stages=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['followed_stages'], [self.stage.id])
        self.assertEqual(response.data['off_route_stages'], [])
