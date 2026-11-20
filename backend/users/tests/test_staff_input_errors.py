"""Staff create/update answers bad phone and company input with a 400, not a 500."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from companies.models import Company

User = get_user_model()


class StaffInputErrorTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='C', description='d', areas_served='Nairobi', phone_number='0700000000')
        self.manager = User.objects.create_user(
            username='mgr', password='Password123!', phone_number='+254700000101',
            role='company_manager', company=self.company)
        self.operator = User.objects.create_user(
            username='op', password='Password123!', phone_number='+254700000102',
            role='company_operator', company=self.company)
        self.other = User.objects.create_user(
            username='op2', password='Password123!', phone_number='+254700000103',
            role='company_operator', company=self.company)
        self.admin = User.objects.create_superuser(
            username='root', password='Password123!', phone_number='+254700000106',
            email='root@example.com')
        self.client = APIClient()

    def patch_phone(self, phone):
        self.client.force_authenticate(self.manager)
        return self.client.patch(
            reverse('users:company-staff-detail', args=[self.operator.pk]),
            {'phone_number': phone}, format='json')

    def test_patch_with_a_variant_of_an_existing_number_is_a_400(self):
        for variant in ('0700000103', '254700000103', '+254 700 000 103'):
            with self.subTest(variant=variant):
                response = self.patch_phone(variant)
                self.assertEqual(response.status_code, 400)
                self.assertIn('phone_number', response.json())
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.phone_number, '+254700000102')

    def test_patch_with_a_new_number_is_stored_canonical(self):
        response = self.patch_phone('0700000199')
        self.assertEqual(response.status_code, 200)
        self.operator.refresh_from_db()
        self.assertEqual(self.operator.phone_number, '+254700000199')

    def test_patch_with_the_staff_members_own_number_in_another_format_is_fine(self):
        response = self.patch_phone('0700000102')
        self.assertEqual(response.status_code, 200)

    def test_create_with_a_variant_of_an_existing_number_is_a_400(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(reverse('users:company-staff'), {
            'username': 'newop', 'phone_number': '0700000103', 'role': 'company_operator',
            'password': 'Password123!',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('phone_number', response.json())

    def test_non_numeric_company_is_a_400(self):
        self.client.force_authenticate(self.admin)
        for value in ('abc', '1; DROP', '1.5', [1], {'a': 1}):
            with self.subTest(value=value):
                response = self.client.post(reverse('users:company-staff'), {
                    'company': value, 'username': 'newop', 'phone_number': '0700000150',
                    'role': 'company_operator', 'password': 'Password123!',
                }, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('company', response.json())
