from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from companies.models import Company

User = get_user_model()
URL = '/api/charters/settings/'


class CharterSettingsTests(APITestCase):

    def setUp(self):
        self.a = Company.objects.create(name='A Line', areas_served='X')
        self.b = Company.objects.create(name='B Line', areas_served='Y')

        def mk(username, phone, role='passenger', company=None):
            return User.objects.create_user(
                username=username, password='x', phone_number=phone, role=role, company=company)

        self.pax = mk('pax', '+254700002001')
        self.mgr_a = mk('ma', '+254700002002', 'company_manager', self.a)
        self.op_a = mk('oa', '+254700002003', 'company_operator', self.a)

    def test_manager_toggles_own_company_only(self):
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual(self.client.get(URL).data, {'accepts_charters': False})
        self.assertEqual(self.client.patch(URL, {'accepts_charters': True}, format='json').status_code, 200)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertTrue(self.a.accepts_charters)
        self.assertFalse(self.b.accepts_charters)
        self.client.force_authenticate(self.pax)
        self.assertEqual([c['name'] for c in self.client.get('/api/charters/companies/').data], ['A Line'])

    def test_only_managers_and_valid_values(self):
        for user in (self.op_a, self.pax):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.patch(URL, {'accepts_charters': True}, format='json').status_code, 403)
        self.client.force_authenticate(self.mgr_a)
        self.assertEqual(self.client.patch(URL, {'accepts_charters': 'yes'}, format='json').status_code, 400)
