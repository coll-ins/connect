from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from wallets.models import Wallet

User = get_user_model()


class WalletsAppTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="wallet_user",
            password="password123",
            phone_number="+254700000002",
        )
        self.wallet = Wallet.objects.create(
            user=self.user,
            available_balance=Decimal("1500.00"),
            held_balance=Decimal("0.00"),
        )

    def _resolve_url(self, primary_name, fallback_name=None, kwargs=None):
        try:
            return reverse(primary_name, kwargs=kwargs)
        except Exception:
            return reverse(fallback_name, kwargs=kwargs)

    def test_wallet_detail_authenticated(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("my-wallet")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_wallet_detail_unauthenticated(self):
        url = reverse("my-wallet")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        