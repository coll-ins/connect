from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company
from drivers.models import Driver

User = get_user_model()


class DriverAccessTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='x', phone_number=phone, role=role, company=company)

        self.pax = mk('pax', '+254700003001')
        self.mgr_a = mk('ma', '+254700003002', 'company_manager', self.a)
        self.op_a = mk('oa', '+254700003003', 'company_operator', self.a)
        self.da = Driver.objects.create(company=self.a, name='DA', phone_number='+254712100001', bus_number='KA 1')
        self.db = Driver.objects.create(company=self.b, name='DB', phone_number='+254712100002', bus_number='KB 1')
        self.drv_user = mk('da', '+254712100001', 'driver', self.a)

    def test_anonymous_blocked(self):
        self.assertEqual(self.client.get('/api/drivers/').status_code, 401)
        self.assertIn(self.client.get(f'/api/drivers/{self.da.id}/').status_code, (401, 403))

    def test_passenger_sees_no_driver_data(self):
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.get('/api/drivers/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/drivers/{self.da.id}/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/drivers/{self.da.id}/location/').status_code, 403)

    def test_driver_cannot_list_or_view_others(self):
        self.client.force_authenticate(self.drv_user)
        self.assertEqual(self.client.get('/api/drivers/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/drivers/{self.da.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/drivers/{self.db.id}/').status_code, 403)

    def test_manager_scoped_to_own_company(self):
        self.client.force_authenticate(self.mgr_a)
        names = {d['name'] for d in self.client.get('/api/drivers/').data}
        self.assertEqual(names, {'DA'})
        self.assertEqual(self.client.get(f'/api/drivers/?company_id={self.b.id}').status_code, 403)
        self.assertEqual(self.client.get(f'/api/drivers/{self.db.id}/').status_code, 403)

    def test_operator_is_read_only(self):
        self.client.force_authenticate(self.op_a)
        self.assertEqual(self.client.get('/api/drivers/').status_code, 200)
        self.assertEqual(
            self.client.patch(f'/api/drivers/{self.da.id}/', {'name': 'X'}, format='json').status_code, 403)
