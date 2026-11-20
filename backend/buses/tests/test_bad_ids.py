"""A garbage company id on the bus list/create is a 400, never a 500."""
from django.test import TestCase

from bookings.tests.review_base import WorldMixin, User


class BusBadIdTests(WorldMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.root = User.objects.create_superuser(
            username='root', password='pw-123456', phone_number='+254722009999')

    def test_list_with_a_garbage_company_id_is_400(self):
        for bad in ('abc', '1e3', '99999999999999999999999', '-1'):
            r = self.api(self.root).get('/api/buses/', {'company_id': bad})
            self.assertEqual(r.status_code, 400, (bad, r.status_code, r.content[:200]))

    def test_create_with_a_garbage_company_is_400(self):
        for bad in ('abc', [1], 10 ** 30, -1):
            r = self.api(self.root).post('/api/buses/', {
                'company': bad, 'bus_number': 'KZZ 999Z', 'capacity': 14}, format='json')
            self.assertEqual(r.status_code, 400, (bad, r.status_code, r.content[:200]))

    def test_list_with_a_valid_company_id_still_works(self):
        r = self.api(self.root).get('/api/buses/', {'company_id': self.co.id})
        self.assertEqual(r.status_code, 200)
