from datetime import timedelta
from unittest.mock import patch
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from companies.geo import locate_on_line
from companies.routing import RoutingError
from companies.simulation import DIVERT_LEAD
from companies.models import Company, PickupStage, Route, Trip, TripSimulation
from drivers.models import Driver

User = get_user_model()
LINE = {
    'type': 'LineString',
    'coordinates': [[36.8219, -1.2864], [36.8330, -1.2900], [36.8450, -1.2990]],
}


class TripSimulationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Metro Shuttle', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=self.company, name='CBD to Westlands', start_point='CBD',
            end_point='Westlands', price=Decimal('100.00'), geometry=LINE,
        )
        PickupStage.objects.create(
            route=self.route, name='CBD', latitude=-1.2864, longitude=36.8219, order=0
        )
        self.driver = Driver.objects.create(
            name='Peter Otieno', phone_number='+254700000555',
            bus_number='KDA 123A', company=self.company,
        )
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=30,
            departure_at=timezone.now() + timedelta(hours=2), status='boarding',
        )
        self.admin = User.objects.create_superuser(
            username='root_admin', password='test-only-password',
            phone_number='+254700000111', email='a@example.test',
        )
        self.client.force_authenticate(user=self.admin)

    def start(self, trip=None):
        return self.client.post(f'/api/system/trips/{(trip or self.trip).id}/simulate/')

    def test_start_advance_moves_driver_until_completed(self):
        resp = self.start()
        self.assertEqual(resp.status_code, 201, resp.content)
        sim = resp.json()['simulation']
        self.assertEqual(sim['status'], 'running')
        advance = f"/api/system/trip-simulations/{sim['id']}/advance/"
        body = self.client.post(advance).json()['simulation']
        self.assertEqual(body['position_index'], 1)
        self.driver.refresh_from_db()
        self.assertAlmostEqual(self.driver.latitude, body['position'][0], places=5)
        self.assertIsNotNone(self.driver.location_updated_at)
        for _ in range(body['total_points']):
            last = self.client.post(advance)
            if last.status_code != 200:
                break
        self.assertEqual(TripSimulation.objects.get(pk=sim['id']).status, 'completed')
        self.assertEqual(self.client.post(advance).status_code, 409)

    def test_stop_and_active(self):
        sim_id = self.start().json()['simulation']['id']
        active = self.client.get('/api/system/trip-simulations/active/').json()
        self.assertEqual(active['simulation']['id'], sim_id)
        self.assertEqual(
            self.client.post(f'/api/system/trip-simulations/{sim_id}/stop/').status_code, 200
        )
        self.assertIsNone(
            self.client.get('/api/system/trip-simulations/active/').json()['simulation']
        )
        self.assertEqual(
            self.client.post(f'/api/system/trip-simulations/{sim_id}/stop/').status_code, 409
        )

    def test_permissions(self):
        manager = User.objects.create_user(
            username='mgr', password='test-only-password',
            phone_number='+254700000112', role='company_manager', company=self.company,
        )
        self.client.force_authenticate(user=manager)
        self.assertEqual(self.start().status_code, 403)
        self.assertEqual(self.client.get('/api/system/trip-simulations/active/').status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.start().status_code, 403)
        self.assertEqual(TripSimulation.objects.count(), 0)

    def test_starting_a_scheduled_trip_makes_it_trackable(self):
        self.trip.status = 'scheduled'
        self.trip.save(update_fields=['status'])

        resp = self.start()

        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['simulation']['trip_status'], 'boarding')
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')

    def test_divert_puts_the_bus_on_a_real_road_and_back(self):
        sim_id = self.start().json()['simulation']['id']
        before = TripSimulation.objects.get(pk=sim_id).path

        def side_road(points, timeout=20):
            # The road service's answer: straight to the via point and on.
            return {'type': 'LineString',
                    'coordinates': [[lng, lat] for lat, lng in points]}, 1.0

        with patch('companies.routing.road_alternatives', side_effect=RoutingError('down')), \
                patch('companies.routing.road_line', side_effect=side_road) as road:
            resp = self.client.post(f'/api/system/trip-simulations/{sim_id}/divert/')

        self.assertEqual(resp.status_code, 200, resp.content)
        after = TripSimulation.objects.get(pk=sim_id).path
        self.assertEqual(after[:DIVERT_LEAD + 1], before[:DIVERT_LEAD + 1])
        self.assertEqual(after[-1], before[-1])
        # Every detour point lies on the line the road service returned.
        a, via, b = road.call_args_list[0].args[0]
        road_geo = {'type': 'LineString', 'coordinates': [[p[1], p[0]] for p in (a, via, b)]}
        detour = [p for p in after if p not in before]
        self.assertTrue(detour)
        for lat, lng in detour:
            self.assertLess(locate_on_line(road_geo, lat, lng)[0], 1)
        planned = {'type': 'LineString', 'coordinates': [[p[1], p[0]] for p in before]}
        self.assertGreater(max(locate_on_line(planned, *p)[0] for p in detour), 120)

    def test_divert_refuses_without_a_different_road(self):
        sim_id = self.start().json()['simulation']['id']
        before = TripSimulation.objects.get(pk=sim_id).path
        same_road = ({'type': 'LineString', 'coordinates': LINE['coordinates']}, 1.0)

        with patch('companies.routing.road_alternatives', return_value=[same_road]), \
                patch('companies.routing.road_line', side_effect=RoutingError('down')):
            resp = self.client.post(f'/api/system/trip-simulations/{sim_id}/divert/')

        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(TripSimulation.objects.get(pk=sim_id).path, before)

    def test_finish_ends_the_trip_and_stops_the_bus(self):
        sim_id = self.start().json()['simulation']['id']

        resp = self.client.post(f'/api/system/trips/{self.trip.id}/finish/')

        self.assertEqual(resp.status_code, 200, resp.content)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'completed')
        self.assertEqual(TripSimulation.objects.get(pk=sim_id).status, 'stopped')
        self.assertEqual(
            self.client.post(f'/api/system/trips/{self.trip.id}/finish/').status_code, 409,
        )

    def test_journey_controls_are_superuser_only(self):
        sim_id = self.start().json()['simulation']['id']
        staff = User.objects.create_user(
            username='plain', password='x', phone_number='+254700000222',
        )
        self.client.force_authenticate(user=staff)
        self.assertEqual(
            self.client.post(f'/api/system/trip-simulations/{sim_id}/divert/').status_code, 403,
        )
        self.assertEqual(
            self.client.post(f'/api/system/trips/{self.trip.id}/finish/').status_code, 403,
        )
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')

    def test_refusals(self):
        self.trip.status = 'completed'
        self.trip.save(update_fields=['status'])
        self.assertEqual(self.start().status_code, 400)
        self.trip.status = 'boarding'
        self.trip.save(update_fields=['status'])

        self.route.geometry = None
        self.route.save(update_fields=['geometry'])
        resp = self.start()
        self.assertEqual(resp.status_code, 400)
        self.assertIn('needs a map line or at least two pickup stages', resp.json()['error'])
        self.route.geometry = LINE
        self.route.save(update_fields=['geometry'])

        self.assertEqual(self.start().status_code, 201)
        other = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=30,
            departure_at=timezone.now() + timedelta(hours=3), status='scheduled',
        )
        self.assertEqual(self.start(other).status_code, 409)

    def test_recent_real_gps_blocks_start_and_real_gps_stops_simulation(self):
        Driver.objects.filter(pk=self.driver.pk).update(
            latitude=-1.2, longitude=36.8, location_updated_at=timezone.now()
        )
        resp = self.start()
        self.assertEqual(resp.status_code, 409)
        self.assertIn('GPS', resp.json()['error'])

        Driver.objects.filter(pk=self.driver.pk).update(
            location_updated_at=timezone.now() - timedelta(minutes=5)
        )
        sim_id = self.start().json()['simulation']['id']
        self.client.post(
            f'/api/drivers/{self.driver.id}/location/',
            {'latitude': -1.29, 'longitude': 36.83, 'accuracy': 10}, format='json',
        )
        self.assertEqual(TripSimulation.objects.get(pk=sim_id).status, 'stopped')


class StageFallbackTests(TripSimulationApiTests):
    def test_route_without_line_drives_stop_to_stop(self):
        self.route.geometry = None
        self.route.save(update_fields=['geometry'])
        PickupStage.objects.create(
            route=self.route, name='Westlands', latitude=-1.2676, longitude=36.8108, order=1
        )
        resp = self.start()
        self.assertEqual(resp.status_code, 201, resp.content)
        path = TripSimulation.objects.get().path
        self.assertEqual(path[0], [-1.2864, 36.8219])
        self.assertEqual(path[-1], [-1.2676, 36.8108])
