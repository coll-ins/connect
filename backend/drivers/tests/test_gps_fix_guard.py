"""Driver GPS fixes carry the device's own fix time and accuracy (plan A-5)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from companies.models import Company
from drivers.models import Driver

User = get_user_model()


class GpsFixGuardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Gps Co', areas_served='Nairobi')
        self.driver = Driver.objects.create(
            name='D', phone_number='+254711000111', bus_number='KDA 111A',
            company=self.company)
        self.user = User.objects.create_user(
            username='drv', password='pw-123456', phone_number='+254711000111',
            company=self.company, role='driver')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('drivers:driver-location', kwargs={'driver_id': self.driver.id})
        self.now = timezone.now()

    def post(self, lat=-1.2864, fix_ago=None, accuracy=None, **extra):
        body = {'latitude': lat, 'longitude': 36.82, **extra}
        if fix_ago is not None:
            body['fix_at'] = (self.now - timedelta(seconds=fix_ago)).isoformat()
        if accuracy is not None:
            body['accuracy_m'] = accuracy
        return self.client.post(self.url, body, format='json')

    def stored(self):
        self.driver.refresh_from_db()
        return self.driver.latitude, self.driver.location_updated_at

    def test_fresh_fix_is_stored_with_its_own_time(self):
        resp = self.post(fix_ago=5, accuracy=12.5)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['ignored'])
        lat, at = self.stored()
        self.assertEqual(lat, -1.2864)
        self.assertAlmostEqual((self.now - at).total_seconds(), 5, delta=1)

    def test_fix_without_the_new_fields_still_works(self):
        resp = self.post()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['ignored'])
        self.assertEqual(self.stored()[0], -1.2864)

    def test_stale_fix_is_ignored(self):
        resp = self.post(fix_ago=300)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.data['ignored'], resp.data['reason']), (True, 'stale'))
        self.assertIsNone(self.stored()[0])

    def test_inaccurate_fix_is_ignored(self):
        resp = self.post(fix_ago=1, accuracy=450)
        self.assertEqual((resp.data['ignored'], resp.data['reason']), (True, 'inaccurate'))
        self.assertIsNone(self.stored()[0])

    def test_out_of_order_fix_is_ignored_and_keeps_the_newer_one(self):
        self.assertFalse(self.post(lat=-1.30, fix_ago=2).data['ignored'])
        resp = self.post(lat=-1.40, fix_ago=20)
        self.assertEqual((resp.data['ignored'], resp.data['reason']), (True, 'out_of_order'))
        self.assertEqual(self.stored()[0], -1.30)

    def test_in_order_fix_after_a_delayed_one_is_accepted(self):
        # The first request was delayed on the network: received late, fix time old.
        self.assertFalse(self.post(lat=-1.30, fix_ago=60).data['ignored'])
        self.assertFalse(self.post(lat=-1.31, fix_ago=55).data['ignored'])
        self.assertEqual(self.stored()[0], -1.31)

    def test_fix_time_in_the_future_is_clamped_to_now(self):
        resp = self.post(fix_ago=-3600)
        self.assertFalse(resp.data['ignored'])
        self.assertLessEqual(self.stored()[1], timezone.now())

    def test_bad_fix_at_or_accuracy_is_400(self):
        for body in ({'fix_at': 'yesterday'}, {'fix_at': '2026-01-01T10:00:00'},
                     {'accuracy_m': 'high'}, {'accuracy_m': -4}):
            with self.subTest(body=body):
                resp = self.client.post(
                    self.url, {'latitude': -1.2, 'longitude': 36.8, **body}, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIsNone(self.stored()[0])

    def test_ignored_fix_does_not_stop_a_simulation(self):
        from companies.models import TripSimulation
        from companies.models import Route, Trip
        from decimal import Decimal
        route = Route.objects.create(
            company=self.company, name='R', start_point='A', end_point='B', price=Decimal('100'))
        trip = Trip.objects.create(
            route=route, driver=self.driver, capacity=5, status='departed',
            departure_at=timezone.now())
        sim = TripSimulation.objects.create(
            trip=trip, status='running', path=[], expires_at=timezone.now() + timedelta(hours=1))
        self.post(fix_ago=300)
        sim.refresh_from_db()
        self.assertEqual(sim.status, 'running')
