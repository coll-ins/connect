from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class OptionsAndRatesTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='x', phone_number=phone, role=role, company=company)

        self.pax = mk('pax', '+254700001001')
        self.mgr_a = mk('ma', '+254700001002', 'company_manager', self.a)
        self.mgr_b = mk('mb', '+254700001003', 'company_manager', self.b)
        self.op_a = mk('oa', '+254700001004', 'company_operator', self.a)

        self.drv_a = Driver.objects.create(company=self.a, name='DA', phone_number='+254712001001', bus_number='KA 1')
        when = timezone.now() + timedelta(hours=6)

        def route(company, name, rate=None, stages=2, trip_driver=None):
            r = Route.objects.create(company=company, name=name, price=Decimal('500'),
                                     parcel_price_small=rate)
            for i in range(stages):
                PickupStage.objects.create(route=r, name=f'{name}{i}', order=i + 1,
                                           latitude=Decimal('-1.2'), longitude=Decimal('36.8'))
            if trip_driver:
                Trip.objects.create(route=r, driver=trip_driver, departure_at=when, capacity=5)
            return r

        self.good = route(self.a, 'Good', Decimal('100'), trip_driver=self.drv_a)
        self.plain = route(self.a, 'Plain', None, trip_driver=self.drv_a)
        self.one_stage = route(self.a, 'OneStage', Decimal('100'), stages=1, trip_driver=self.drv_a)
        self.foreign_driver = route(self.b, 'Foreign', Decimal('100'), trip_driver=self.drv_a)

    def test_options_lists_only_carrying_routes(self):
        self.client.force_authenticate(self.pax)
        data = self.client.get('/api/deliveries/options/').data
        self.assertEqual([c['id'] for c in data], [self.a.id])
        self.assertEqual([r['id'] for r in data[0]['routes']], [self.good.id])
        self.assertEqual(len(data[0]['routes'][0]['trips']), 1)

    def test_options_anonymous_blocked(self):
        self.assertIn(self.client.get('/api/deliveries/options/').status_code, (401, 403))

    def test_rates_are_scoped_to_own_company(self):
        self.client.force_authenticate(self.mgr_a)
        names = {r['name'] for r in self.client.get('/api/deliveries/rates/').data}
        self.assertEqual(names, {'Good', 'Plain', 'OneStage'})
        self.client.force_authenticate(self.mgr_b)
        self.assertEqual({r['name'] for r in self.client.get('/api/deliveries/rates/').data}, {'Foreign'})

    def test_manager_can_set_and_clear_rates(self):
        self.client.force_authenticate(self.mgr_a)
        url = f'/api/deliveries/rates/{self.plain.id}/'
        self.assertEqual(self.client.patch(url, {'small': '120', 'large': '400'}, format='json').status_code, 200)
        self.plain.refresh_from_db()
        self.assertEqual(self.plain.parcel_price_small, Decimal('120.00'))
        self.assertEqual(self.plain.parcel_price_large, Decimal('400.00'))
        self.assertEqual(self.client.patch(
            f'/api/deliveries/rates/{self.good.id}/', {'small': None}, format='json').status_code, 200)
        self.client.force_authenticate(self.pax)
        ids = [r['id'] for c in self.client.get('/api/deliveries/options/').data for r in c['routes']]
        self.assertNotIn(self.good.id, ids)
        self.assertIn(self.plain.id, ids)

    def test_rates_access_rules(self):
        url = f'/api/deliveries/rates/{self.good.id}/'
        self.client.force_authenticate(self.mgr_b)
        self.assertEqual(self.client.patch(url, {'small': '1'}, format='json').status_code, 404)
        for user in (self.op_a, self.pax):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.patch(url, {'small': '1'}, format='json').status_code, 403)
            self.assertEqual(self.client.get('/api/deliveries/rates/').status_code, 403)
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual(self.client.patch(url, {'small': '0'}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'small': '99999999'}, format='json').status_code, 400)
