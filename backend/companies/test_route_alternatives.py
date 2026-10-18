from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route
from companies.routing import RoutingError

User = get_user_model()
LINE = {'type': 'LineString', 'coordinates': [[36.80, -1.30], [36.80, -1.20]]}
START = {'latitude': -1.30, 'longitude': 36.80}
END = {'latitude': -1.20, 'longitude': 36.80}


class RouteAlternativesTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role, company=None):
            return User.objects.create_user(
                username=username, password='x', phone_number=phone, role=role, company=company)

        self.mgr = mk('am', '+254700006001', 'company_manager', self.a)
        self.mgr_b = mk('amb', '+254700006002', 'company_manager', self.b)
        self.pax = mk('ap', '+254700006003', 'passenger')
        self.route = Route.objects.create(
            company=self.a, name='R', start_point='A', end_point='B', price=Decimal('100'))
        self.on = PickupStage.objects.create(
            route=self.route, name='On', order=1,
            latitude=Decimal('-1.25'), longitude=Decimal('36.80'))
        self.url = f'/api/companies/routes/{self.route.id}/alternatives/'

    def post(self, body=None, user=None):
        self.client.force_authenticate(user or self.mgr)
        return self.client.post(
            self.url, {'start': START, 'end': END} if body is None else body, format='json')

    @patch('companies.routing.road_alternatives', return_value=[(LINE, 12000.0), (LINE, 15500.0)])
    def test_returns_options_and_saves_nothing(self, ra):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        opts = r.data['options']
        self.assertEqual(len(opts), 2)
        self.assertEqual(opts[0]['distance_km'], 12.0)
        self.assertEqual(opts[1]['distance_km'], 15.5)
        for o in opts:
            for key in ('geometry', 'distance_km', 'spurs', 'off_route_stages', 'via'):
                self.assertIn(key, o)
            self.assertIsInstance(o['via'], list)
        self.route.refresh_from_db()
        self.assertIsNone(self.route.geometry)
        self.assertEqual(ra.call_args.kwargs.get('count'), 3)

    @patch('companies.routing.road_alternatives', return_value=[(LINE, 12000.0)])
    def test_flags_only_active_stages_far_from_the_line(self, ra):
        far = PickupStage.objects.create(
            route=self.route, name='Far', order=2,
            latitude=Decimal('-1.25'), longitude=Decimal('36.90'))
        PickupStage.objects.create(
            route=self.route, name='Hidden', order=3, is_active=False,
            latitude=Decimal('-1.25'), longitude=Decimal('36.95'))
        off = self.post().data['options'][0]['off_route_stages']
        self.assertEqual([s['id'] for s in off], [far.id])
        self.assertGreater(off[0]['offset_m'], 1000)

    @patch('companies.routing.road_alternatives')
    def test_other_company_manager_and_passenger_forbidden(self, ra):
        self.assertEqual(self.post(user=self.mgr_b).status_code, 403)
        self.assertEqual(self.post(user=self.pax).status_code, 403)
        ra.assert_not_called()

    @patch('companies.routing.road_alternatives', side_effect=RoutingError('down'))
    def test_routing_failure_is_502(self, ra):
        r = self.post()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.data['error'], 'down')

    @patch('companies.routing.road_alternatives')
    def test_missing_or_invalid_points_are_400(self, ra):
        self.assertEqual(self.post(body={}).status_code, 400)
        bad = {'start': {'latitude': 95, 'longitude': 36.8}, 'end': END}
        self.assertEqual(self.post(body=bad).status_code, 400)
        ra.assert_not_called()

    @patch('companies.routing.road_alternatives')
    def test_multi_point_line_returns_via_points(self, ra):
        line = {'type': 'LineString', 'coordinates': [
            [36.80, -1.30], [36.80, -1.28], [36.80, -1.26],
            [36.80, -1.24], [36.80, -1.22], [36.80, -1.20]]}
        ra.return_value = [(line, 12000.0)]
        via = self.post().data['options'][0]['via']
        self.assertEqual(len(via), 4)
        self.assertEqual(via[0], {'latitude': -1.28, 'longitude': 36.8})
        self.assertEqual(via[-1], {'latitude': -1.22, 'longitude': 36.8})
