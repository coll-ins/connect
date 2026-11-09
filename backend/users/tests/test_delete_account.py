from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import CustomUser
from wallets.models import Wallet

URL = '/api/users/delete-account/'


class DeleteAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = CustomUser.objects.create_user(
            username='amina', password='Str0ng!Pass', phone_number='+254712345678',
            first_name='Amina', last_name='Wanjiru', role='passenger',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_wrong_password_keeps_account(self):
        res = self.client.post(URL, {'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_money_in_wallet_blocks_closing(self):
        Wallet.objects.update_or_create(user=self.user, defaults={'available_balance': Decimal('150')})
        res = self.client.post(URL, {'password': 'Str0ng!Pass'}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertIn('KES 150', res.data['error'])

    def test_closing_removes_personal_details_and_frees_phone(self):
        res = self.client.post(URL, {'password': 'Str0ng!Pass'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNone(self.user.phone_number)
        self.assertEqual(self.user.first_name, '')
        self.assertFalse(self.user.has_usable_password())

    def test_drivers_cannot_close_their_own_login(self):
        self.user.role = 'driver'
        self.user.save()
        res = self.client.post(URL, {'password': 'Str0ng!Pass'}, format='json')
        self.assertEqual(res.status_code, 403)
