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
        # Stages no longer steer the line: start, road point, end.
        self.assertEqual(len(points), 3)

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_existing_curved_route_controls_are_ordered_along_saved_geometry(self, rl):
        # Existing route bends away from the straight start -> end line.
        # Along the saved geometry the order is:
        # S1 -> B -> A -> S2
        #
        # Straight-line latitude ordering would incorrectly produce:
        # S1 -> A -> B -> S2
        curved = {
            'type': 'LineString',
            'coordinates': [
                [36.80, -1.30],  # start
                [36.80, -1.25],  # S1
                [36.78, -1.23],  # B
                [36.82, -1.24],  # A
                [36.80, -1.22],  # S2
                [36.80, -1.20],  # end
            ],
        }

        self.route.geometry = curved
        self.route.start_latitude = Decimal('-1.300000')
        self.route.start_longitude = Decimal('36.800000')
        self.route.end_latitude = Decimal('-1.200000')
        self.route.end_longitude = Decimal('36.800000')
        self.route.save()

        via = [
            {'latitude': -1.24, 'longitude': 36.82},  # A
            {'latitude': -1.23, 'longitude': 36.78},  # B
        ]

        r = self.post(self.body(via=via))

        self.assertEqual(r.status_code, 200)

        points = rl.call_args[0][0]

        self.assertEqual(
            points,
            [
                (-1.30, 36.80),  # start
                (-1.23, 36.78),  # B
                (-1.24, 36.82),  # A
                (-1.20, 36.80),  # end
            ],
        )

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

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_path_keeps_the_order_it_was_drawn_in(self, rl):
        # Not sorted by latitude: a re-sort would give -1.27, -1.25, -1.23.
        via = [
            {'latitude': -1.27, 'longitude': 36.80},
            {'latitude': -1.23, 'longitude': 36.80},
            {'latitude': -1.25, 'longitude': 36.80},
        ]
        r = self.post(self.body(via=via, ordered=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            rl.call_args[0][0],
            [(-1.30, 36.80), (-1.27, 36.80), (-1.23, 36.80),
             (-1.25, 36.80), (-1.20, 36.80)],
        )

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_overrides_saved_geometry_ordering(self, rl):
        # Same curved route as the unordered test above, where the saved line
        # forces B before A. A drawn path must stay A then B.
        self.route.geometry = {
            'type': 'LineString',
            'coordinates': [
                [36.80, -1.30], [36.80, -1.25], [36.78, -1.23],
                [36.82, -1.24], [36.80, -1.22], [36.80, -1.20],
            ],
        }
        self.route.start_latitude = Decimal('-1.300000')
        self.route.start_longitude = Decimal('36.800000')
        self.route.end_latitude = Decimal('-1.200000')
        self.route.end_longitude = Decimal('36.800000')
        self.route.save()
        via = [
            {'latitude': -1.24, 'longitude': 36.82},  # A
            {'latitude': -1.23, 'longitude': 36.78},  # B
        ]
        r = self.post(self.body(via=via, ordered=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            rl.call_args[0][0],
            [(-1.30, 36.80), (-1.24, 36.82), (-1.23, 36.78), (-1.20, 36.80)],
        )

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_path_drawn_backwards_is_rejected(self, rl):
        via = [
            {'latitude': -1.23, 'longitude': 36.80},
            {'latitude': -1.25, 'longitude': 36.80},
            {'latitude': -1.27, 'longitude': 36.80},
        ]
        r = self.post(self.body(via=via, ordered=True))
        self.assertEqual(r.status_code, 400)
        self.assertIn('towards the start', r.data['error'])
        rl.assert_not_called()

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_allows_more_road_points_than_the_default_cap(self, rl):
        # 12 road points exceeds the unordered cap of 10; ordered allows 25.
        via = [{'latitude': -1.29 + i * 0.005, 'longitude': 36.80} for i in range(12)]
        r = self.post(self.body(via=via, ordered=True))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(rl.call_args[0][0]), 14)


ALT_NEAR = {'type': 'LineString', 'coordinates': [
    [36.80, -1.30], [36.80, -1.275], [36.80, -1.25], [36.80, -1.225], [36.80, -1.20]]}
ALT_FAR = {'type': 'LineString', 'coordinates': [
    [36.80, -1.30], [36.90, -1.275], [36.90, -1.25], [36.90, -1.225], [36.80, -1.20]]}


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
        PickupStage.objects.create(route=self.route, name='S1', order=1,
                                   latitude=Decimal('-1.25'), longitude=Decimal('36.80'))
        PickupStage.objects.create(route=self.route, name='S2', order=2,
                                   latitude=Decimal('-1.22'), longitude=Decimal('36.80'))
        self.url = f'/api/companies/routes/{self.route.id}/alternatives/'

    def post(self, body=None, user=None):
        self.client.force_authenticate(user or self.mgr)
        return self.client.post(
            self.url, {'start': START, 'end': END} if body is None else body, format='json')

    @patch('companies.routing.road_alternatives',
           return_value=[(ALT_NEAR, 12000.0), (ALT_FAR, 15500.0)])
    def test_returns_each_alternative_with_distance_and_stage_report(self, ra):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        near, far = r.data['options']
        self.assertEqual(near['distance_km'], 12.0)
        self.assertEqual(far['distance_km'], 15.5)
        self.assertEqual(near['geometry'], ALT_NEAR)
        self.assertEqual(near['off_route_stages'], [])
        self.assertEqual(sorted(s['name'] for s in far['off_route_stages']), ['S1', 'S2'])
        for option in (near, far):
            self.assertIn('spurs', option)
            self.assertTrue(1 <= len(option['via']) <= 6)
            self.assertEqual(set(option['via'][0]), {'latitude', 'longitude'})

    @patch('companies.routing.road_alternatives', return_value=[(ALT_FAR, 15500.0)])
    def test_inactive_stages_are_not_reported(self, ra):
        PickupStage.objects.create(route=self.route, name='Closed', order=3, is_active=False,
                                   latitude=Decimal('-1.25'), longitude=Decimal('36.80'))
        r = self.post()
        names = [s['name'] for s in r.data['options'][0]['off_route_stages']]
        self.assertNotIn('Closed', names)

    @patch('companies.routing.road_alternatives', return_value=[(ALT_NEAR, 12000.0)])
    def test_nothing_is_saved(self, ra):
        self.post()
        self.route.refresh_from_db()
        self.assertIsNone(self.route.geometry)

    @patch('companies.routing.road_alternatives', return_value=[(ALT_NEAR, 12000.0)])
    def test_falls_back_to_the_routes_saved_start_and_end(self, ra):
        self.route.start_latitude = Decimal('-1.300000')
        self.route.start_longitude = Decimal('36.800000')
        self.route.end_latitude = Decimal('-1.200000')
        self.route.end_longitude = Decimal('36.800000')
        self.route.save()
        r = self.post(body={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ra.call_args[0][0], [(-1.30, 36.80), (-1.20, 36.80)])
        self.assertEqual(ra.call_args[1], {'count': 3})

    @patch('companies.routing.road_alternatives', return_value=[(ALT_NEAR, 1.0)])
    def test_other_company_and_passenger_refused(self, ra):
        self.assertEqual(self.post(user=self.mgr_b).status_code, 403)
        self.assertEqual(self.post(user=self.pax).status_code, 403)
        ra.assert_not_called()

    @patch('companies.routing.road_alternatives', return_value=[(ALT_NEAR, 1.0)])
    def test_missing_start_is_rejected(self, ra):
        r = self.post(body={})  # route has no saved coordinates either
        self.assertEqual(r.status_code, 400)
        self.assertIn('start', r.data['error'])
        ra.assert_not_called()

    @patch('companies.routing.road_alternatives', return_value=[(ALT_NEAR, 1.0)])
    def test_out_of_range_point_is_rejected(self, ra):
        r = self.post(body={'start': dict(START, latitude=95), 'end': END})
        self.assertEqual(r.status_code, 400)
        self.assertIn('not a valid place', r.data['error'])
        ra.assert_not_called()

    @patch('companies.routing.road_alternatives', side_effect=RoutingError('down'))
    def test_routing_failure_is_reported(self, ra):
        r = self.post()
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.data['error'], 'down')
