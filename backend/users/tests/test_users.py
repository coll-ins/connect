from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

User = get_user_model()


class UsersTestSuite(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="password123",
            phone_number="+254700000099",
        )

    def _get_url(self, name):
        url_map = {
            "register": "users:signup",
            "user_profile": "users:profile",
        }
        target = url_map.get(name, name)
        return reverse(target)

    def test_user_registration(self):
        url = self._get_url("register")
        payload = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "StrongPassword123!",
            "password2": "StrongPassword123!",
            "phone_number": "+254700000000",
            "first_name": "Test",
            "last_name": "User",
            "location": "Nairobi",
        }
        response = self.client.post(url, payload, format="json")
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])

    def test_get_user_profile(self):
        self.client.force_authenticate(user=self.user)
        url = self._get_url("user_profile")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class UserViewEdgeCaseTests(APITestCase):

    def test_register_user_invalid_data(self):
        url = reverse('users:register')
        response = self.client.post(url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_profile_unauthorized(self):
        url = reverse('users:profile')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)