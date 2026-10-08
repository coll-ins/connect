from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


class StaffPasswordTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('1901')
        self.manager = User.objects.create_user(
            username='r19_mgr', password=STRONG, phone_number='+254733001901',
            role='company_manager', company=self.company)
        self.client.force_authenticate(user=self.manager)
        self.url = reverse('users:company-staff')

    def _create(self, username, phone, password):
        return self.client.post(self.url, {
            'username': username, 'phone_number': phone,
            'password': password, 'role': 'company_operator',
        }, format='json')

    def test_control_a_strong_password_is_accepted(self):
        response = self._create('r19_ok', '0799001901', STRONG)
        self.assertEqual(response.status_code, 201, response.data)

    def test_weak_passwords_are_rejected_and_nothing_is_created(self):
        for index, weak in enumerate(('123456', 'password123', 'abcdefg')):
            response = self._create(f'r19_weak{index}', f'079900191{index}', weak)
            self.assertEqual(response.status_code, 400, (weak, response.data))
            self.assertFalse(User.objects.filter(username=f'r19_weak{index}').exists())
