from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from bookings.tests.test_round5 import _Fixture
from drivers.models import Driver

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


class DriverPhoneChangeTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('1601')
        self.manager = User.objects.create_user(
            username='r16_mgr', password=STRONG, phone_number='+254733001601',
            role='company_manager', company=self.company)
        self.login = User.objects.create_user(
            username='r16_driver', password=STRONG,
            phone_number=self.driver.phone_number,
            role='driver', company=self.company)
        self.old_phone = self.driver.phone_number
        self.url = reverse('drivers:driver-detail', kwargs={'driver_id': self.driver.id})
        self.client.force_authenticate(user=self.manager)

    def _phones(self):
        return (
            Driver.objects.get(pk=self.driver.pk).phone_number,
            User.objects.get(pk=self.login.pk).phone_number,
        )

    def test_login_account_follows_the_driver_phone(self):
        response = self.client.patch(self.url, {'phone_number': '0799000001'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._phones(), ('+254799000001', '+254799000001'))

    def test_number_used_by_another_account_is_rejected(self):
        User.objects.create_user(
            username='r16_other', password=STRONG, phone_number='+254799000002')
        response = self.client.patch(self.url, {'phone_number': '0799000002'}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self._phones(), (self.old_phone, self.old_phone))

    def test_driver_phone_cannot_be_cleared(self):
        response = self.client.patch(self.url, {'phone_number': ''}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self._phones(), (self.old_phone, self.old_phone))

    def test_patch_without_a_phone_leaves_both_alone(self):
        response = self.client.patch(self.url, {'name': 'Renamed'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._phones(), (self.old_phone, self.old_phone))


class StaffCreationDuplicateTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('1602')
        self.manager = User.objects.create_user(
            username='r16_mgr2', password=STRONG, phone_number='+254733001602',
            role='company_manager', company=self.company)
        User.objects.create_user(
            username='r16_existing', password=STRONG, phone_number='+254799000010')
        self.client.force_authenticate(user=self.manager)
        self.url = reverse('users:company-staff')

    def _create(self, username, phone):
        return self.client.post(self.url, {
            'username': username, 'phone_number': phone,
            'password': STRONG, 'role': 'company_operator',
        }, format='json')

    def test_control_a_fresh_number_is_accepted(self):
        # Proves the payload is valid, so the next test cannot pass for the wrong reason.
        response = self._create('r16_new_staff', '0799000011')
        self.assertEqual(response.status_code, 201, response.data)

    def test_same_number_in_another_format_is_a_clean_400(self):
        response = self._create('r16_dup_staff', '0799000010')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('phone number already exists', str(response.data))
        self.assertFalse(User.objects.filter(username='r16_dup_staff').exists())
