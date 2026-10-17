from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture
from companies.geo import line_health
from companies.models import Company, Route

User = get_user_model()
STRONG = 'Tr4velSafe-2026'

STRAIGHT = {'type': 'LineString',
            'coordinates': [[36.800 + i * 0.005, -1.30] for i in range(5)]}
# A road along latitude -1.30 with a side-street stub at lng 36.810: the line
# goes up the stub and comes straight back.
STUB = {'type': 'LineString', 'coordinates': [
    [36.800, -1.30], [36.805, -1.30], [36.810, -1.30], [36.810, -1.298],
    [36.810, -1.30], [36.815, -1.30], [36.820, -1.30]]}


class LineHealthTests(APITestCase):
    def test_straight_line_is_clean(self):
        h = line_health(STRAIGHT, [(1, 'On road', -1.30, 36.81)])
        self.assertTrue(h['has_line'])
        self.assertEqual(h['spurs'], 0)
        self.assertEqual(h['stages_off'], [])
        self.assertAlmostEqual(h['detour_ratio'], 1.0, places=1)

    def test_stub_is_counted_as_a_spur(self):
        h = line_health(STUB, [])
        self.assertEqual(h['spurs'], 1)
        self.assertEqual(len(h['spur_points']), 1)

    def test_stage_off_the_line_is_flagged(self):
        h = line_health(STRAIGHT, [(1, 'On road', -1.30, 36.81), (2, 'Far', -1.29, 36.81)])
        self.assertEqual([s['id'] for s in h['stages_off']], [2])

    def test_missing_line(self):
        self.assertFalse(line_health(None, [])['has_line'])


class RouteHealthEndpointTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('2601')
        self.route = self.trip.route
        Route.objects.filter(pk=self.route.pk).update(geometry=STUB)

    def _manager(self, username, phone, company):
        return User.objects.create_user(
            username=username, password=STRONG, phone_number=phone,
            role='company_manager', company=company)

    def test_manager_sees_the_check_for_own_routes_only(self):
        self.client.force_authenticate(
            user=self._manager('r26_mgr', '+254733002601', self.route.company))
        response = self.client.get('/api/companies/routes/health/')
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row['id']: row for row in response.data}
        self.assertEqual(rows[self.route.id]['status'], 'check')
        self.assertEqual(len(rows[self.route.id]['spur_points']), 1)

        other = Company.objects.create(name='R26 Other Co')
        self.client.force_authenticate(
            user=self._manager('r26_other', '+254733002602', other))
        response = self.client.get('/api/companies/routes/health/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(self.route.id, [row['id'] for row in response.data])

    def test_route_list_exposes_via_points(self):
        self.client.force_authenticate(
            user=self._manager('r26_mgr2', '+254733002603', self.route.company))
        response = self.client.get(f'/api/companies/{self.route.company_id}/routes/')
        self.assertEqual(response.status_code, 200, response.data)
        rows = response.data if isinstance(response.data, list) else response.data.get('results', [])
        row = next(r for r in rows if r['id'] == self.route.id)
        self.assertIn('via_points', row)
