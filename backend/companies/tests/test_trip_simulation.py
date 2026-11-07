from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

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
            {'latitude': -1.29, 'longitude': 36.83}, format='json',
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
