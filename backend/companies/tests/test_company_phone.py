"""A company's phone number must be a Kenyan mobile number (or left blank)."""
from django.test import TestCase

from bookings.tests.review_base import User, WorldMixin


class CompanyPhoneTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.su = User.objects.create_user(
            username='su', password='pw-123456', phone_number='+254700123456', is_superuser=True)

    def create(self, phone, name='Phone Co'):
        return self.api(self.su).post('/api/companies/create/', {
            'name': name, 'description': 'd', 'areas_served': 'Nairobi', 'phone_number': phone},
            format='json')

    def test_a_non_phone_value_is_400(self):
        for bad in ('not-a-phone', '123', '+1 202 555 0100', '٠٧١٢٣٤٥٦٧٨'):
            r = self.create(bad)
            self.assertEqual(r.status_code, 400, (bad, r.content[:200]))
            self.assertIn('phone_number', r.json())

    def test_a_kenyan_mobile_is_saved_in_canonical_form(self):
        r = self.create('0712 345 678')
        self.assertEqual(r.status_code, 201, r.content[:200])
        self.assertEqual(r.json()['phone_number'], '+254712345678')

    def test_a_blank_phone_is_still_allowed(self):
        self.assertEqual(self.create('').status_code, 201)

    def test_updating_to_a_bad_phone_is_400(self):
        r = self.api(self.su).patch(f'/api/companies/{self.co.id}/', {'phone_number': 'nope'}, format='json')
        self.assertEqual(r.status_code, 400, r.content[:200])
