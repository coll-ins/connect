"""The withdrawals list is gated by the same switch as the withdraw POST."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()


class WithdrawalsListGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='wl1', password='pw-123456', phone_number='+254712345678')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @override_settings(WALLET_PAYOUTS_ENABLED=False)
    def test_list_is_503_feature_disabled_when_payouts_are_off(self):
        r = self.client.get(reverse('wallet-withdrawals'))
        self.assertEqual(r.status_code, 503, r.content)
        self.assertEqual(r.data['code'], 'feature_disabled')

    @override_settings(WALLET_PAYOUTS_ENABLED=True)
    def test_list_is_200_when_payouts_are_on(self):
        r = self.client.get(reverse('wallet-withdrawals'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'], [])
