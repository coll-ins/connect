from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company, Route

User = get_user_model()
LINE = {'type': 'LineString', 'coordinates': [[36.80, -1.30], [36.80, -1.20]]}
START = {'name': 'CBD Station', 'latitude': -1.30, 'longitude': 36.80}
END = {'name': 'Ngong Town', 'latitude': -1.20, 'longitude': 36.80}


class OrderedPlanTests(APITestCase):

    def setUp(self):
        co = Company.objects.create(name='O Line', areas_served='X')
        self.mgr = User.objects.create_user(
            username='om', password='x', phone_number='+254700007001',
            role='company_manager', company=co)
        self.route = Route.objects.create(
            company=co, name='R', start_point='A', end_point='B', price=Decimal('100'))
        self.url = f'/api/companies/routes/{self.route.id}/plan/'

    def post(self, via):
        self.client.force_authenticate(self.mgr)
        return self.client.post(self.url, {
            'start': START, 'end': END, 'via': via, 'apply': False, 'ordered': True,
        }, format='json')

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_path_drawn_backwards_is_rejected(self, rl):
        via = [{'latitude': -1.22, 'longitude': 36.80}, {'latitude': -1.28, 'longitude': 36.80}]
        r = self.post(via)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Reverse', r.data['error'])
        rl.assert_not_called()

    def vias(self, n):
        return [{'latitude': -1.29 + i * 0.001, 'longitude': 36.80} for i in range(n)]

    def post_mode(self, via, ordered):
        self.client.force_authenticate(self.mgr)
        return self.client.post(self.url, {
            'start': START, 'end': END, 'via': via, 'apply': False, 'ordered': ordered,
        }, format='json')

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_unordered_limit_is_10(self, rl):
        self.assertEqual(self.post_mode(self.vias(10), False).status_code, 200)
        r = self.post_mode(self.vias(11), False)
        self.assertEqual(r.status_code, 400)
        self.assertIn('at most 10', r.data['error'])

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_limit_is_25(self, rl):
        self.assertEqual(self.post_mode(self.vias(25), True).status_code, 200)
        r = self.post_mode(self.vias(26), True)
        self.assertEqual(r.status_code, 400)
        self.assertIn('at most 25', r.data['error'])

    @patch('companies.routing.road_line', return_value=(LINE, 12000.0))
    def test_ordered_forward_path_keeps_drawn_order(self, rl):
        via = [{'latitude': -1.28, 'longitude': 36.80}, {'latitude': -1.22, 'longitude': 36.80}]
        r = self.post_mode(via, True)
        self.assertEqual(r.status_code, 200)
        points = rl.call_args[0][0]
        self.assertEqual(points[0], (-1.30, 36.80))
        self.assertEqual(points[1], (-1.28, 36.80))
        self.assertEqual(points[2], (-1.22, 36.80))
        self.assertEqual(points[-1], (-1.20, 36.80))
