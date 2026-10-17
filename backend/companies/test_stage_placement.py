from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route

User = get_user_model()
LINE = {'type': 'LineString', 'coordinates': [[36.80, -1.30], [36.80, -1.20]]}


class StagePlacementTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')
        self.mgr = User.objects.create_user(
            username='m', password='x', phone_number='+254700004001', role='company_manager', company=self.a)
        self.mgr_b = User.objects.create_user(
            username='mb', password='x', phone_number='+254700004002', role='company_manager', company=self.b)
        self.route = Route.objects.create(
            company=self.a, name='R', start_point='A', end_point='B',
            price=Decimal('100'), geometry=LINE)
        for i, lat in enumerate(('-1.29', '-1.25', '-1.21'), start=1):
            PickupStage.objects.create(
                route=self.route, name=f'S{i}', order=i,
                latitude=Decimal(lat), longitude=Decimal('36.80'))
        self.url = f'/api/companies/routes/{self.route.id}/pickup-stages/create/'

    def add(self, name, lat, lng='36.80', user=None):
        self.client.force_authenticate(user or self.mgr)
        return self.client.post(
            self.url, {'name': name, 'latitude': lat, 'longitude': lng}, format='json')

    def stages(self):
        return list(PickupStage.objects.filter(route=self.route).order_by('order', 'id'))

    def test_middle_stage_is_inserted_in_line_order(self):
        self.assertEqual(self.add('Mid', '-1.27').status_code, 201)
        self.assertEqual([s.name for s in self.stages()], ['S1', 'Mid', 'S2', 'S3'])
        self.assertEqual([s.order for s in self.stages()], [1, 2, 3, 4])

    def test_stage_past_the_end_is_appended(self):
        self.assertEqual(self.add('End', '-1.205').status_code, 201)
        self.assertEqual([s.name for s in self.stages()][-1], 'End')

    def test_stage_before_the_first_goes_first(self):
        self.assertEqual(self.add('Start', '-1.299').status_code, 201)
        self.assertEqual([s.name for s in self.stages()][0], 'Start')

    def test_stage_far_from_the_route_is_rejected(self):
        r = self.add('Far', '-1.27', lng='36.90')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.stages()), 3)

    def test_other_company_manager_is_refused(self):
        self.assertEqual(self.add('X', '-1.27', user=self.mgr_b).status_code, 403)
        self.assertEqual(len(self.stages()), 3)

    def test_route_without_a_line_still_accepts_stages(self):
        Route.objects.filter(id=self.route.id).update(geometry=None)
        self.assertEqual(self.add('Free', '-1.27', lng='36.90').status_code, 201)
