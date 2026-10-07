from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route, Trip
from companies.routing import RoutingError
from drivers.models import Driver

User = get_user_model()
LINE = {'type': 'LineString', 'coordinates': [[36.80, -1.30], [36.80, -1.20]]}
START = {'name': 'CBD Station', 'latitude': -1.30, 'longitude': 36.80}
END = {'name': 'Ngong Town', 'latitude': -1.20, 'longitude': 36.80}


class RoutePlanTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role, company=None):
            return User.objects.create_user(
                username=username, password='x', phone_number=phone, role=role, company=company)

        self.mgr = mk('m', '+254700005001', 'company_manager', self.a)
        self.mgr_b = mk('mb', '+254700005002', 'company_manager', self.b)
        self.pax = mk('p', '+254700005003', 'passenger')
        self.route = Route.objects.create(
            company=self.a, name='R', start_point='A', end_point='B', price=Decimal('100'))
        PickupStage.objects.create(route=self.route, name='S1', order=1,
                                   latitude=Decimal('-1.25'), longitude=Decimal('36.80'))
        PickupStage.objects.create(route=self.route, name='S2', order=2,
                                   latitude=Decimal('-1.22'), longitude=Decimal('36.80'))
        self.driver = Driver.objects.create(
            company=self.a, name='D', phone_number='+254712300001', bus_number='KA 1')
        self.url = f'/api/companies/routes/{self.route.id}/plan/'

    def post(self, body, user=None):
        self.client.force_authenticate(user or self.mgr)
        return self.client.post(self.url, body, format='json')

    def body(self, **over):
        b = {'start': START, 'end': END, 'via': [], 'apply': False}
        b.update(over)
        return b

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_preview_does_not_save_and_orders_waypoints(self, rl):
        via = [{'latitude': -1.26, 'longitude': 36.801}]
        r = self.post(self.body(via=via))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['applied'])
        self.assertEqual(r.data['distance_km'], 12.0)
        self.route.refresh_from_db()
        self.assertIsNone(self.route.geometry)
        points = rl.call_args[0][0]
        self.assertEqual(points[0], (-1.30, 36.80))
        self.assertEqual(points[1], (-1.26, 36.801))
        self.assertEqual(points[-1], (-1.20, 36.80))
        self.assertEqual(len(points), 5)

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_apply_saves_start_end_and_line(self, rl):
        r = self.post(self.body(apply=True))
        self.assertEqual(r.status_code, 200)
        self.route.refresh_from_db()
        self.assertEqual(self.route.geometry, LINE)
        self.assertEqual(self.route.start_point, 'CBD Station')
        self.assertEqual(self.route.end_point, 'Ngong Town')
        self.assertEqual(self.route.start_latitude, Decimal('-1.300000'))

    @patch('companies.routing.road_line', return_value=(LINE, 1.0))
    def test_other_company_and_passenger_refused(self, rl):
        self.assertEqual(self.post(self.body(apply=True), user=self.mgr_b).status_code, 403)
        self.assertEqual(self.post(self.body(apply=True), user=self.pax).status_code, 403)
        rl.assert_not_called()
        self.route.refresh_from_db()
        self.assertIsNone(self.route.geometry)

    @patch('companies.routing.road_line', return_value=(LINE, 1.0))
    def test_apply_blocked_while_a_trip_is_running(self, rl):
        Trip.objects.create(route=self.route, driver=self.driver, status='boarding',
                            capacity=5, departure_at=timezone.now())
        self.assertEqual(self.post(self.body(apply=True)).status_code, 409)
        self.route.refresh_from_db()
        self.assertIsNone(self.route.geometry)

    @patch('companies.routing.road_line', return_value=(LINE, 1.0))
    def test_old_departed_trips_do_not_block(self, rl):
        Trip.objects.create(route=self.route, driver=self.driver, status='departed',
                            capacity=5, departure_at=timezone.now() - timedelta(hours=30))
        self.assertEqual(self.post(self.body(apply=True)).status_code, 200)

    @patch('companies.routing.road_line', return_value=(LINE, 1.0))
    def test_stages_off_the_new_line_are_reported(self, rl):
        PickupStage.objects.create(route=self.route, name='Far', order=3,
                                   latitude=Decimal('-1.25'), longitude=Decimal('36.90'))
        r = self.post(self.body())
        self.assertEqual([s['name'] for s in r.data['off_route_stages']], ['Far'])

    @patch('companies.routing.road_line', side_effect=RoutingError('down'))
    def test_routing_failure_is_reported(self, rl):
        r = self.post(self.body())
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.data['error'], 'down')

    @patch('companies.routing.road_line', return_value=(LINE, 1.0))
    def test_bad_input_is_rejected(self, rl):
        bad = dict(START, latitude='abc')
        self.assertEqual(self.post(self.body(start=bad)).status_code, 400)
        nameless = dict(START, name='')
        self.assertEqual(self.post(self.body(start=nameless, apply=True)).status_code, 400)
        rl.assert_not_called()
