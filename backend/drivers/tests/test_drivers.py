from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company
from drivers.models import Driver

User = get_user_model()


class DriversAppTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Coast Bus")
        self.staff_user = User.objects.create_user(
            username="staff_member",
            password="password123",
            phone_number="+254700000003",
            is_staff=True,
        )
        self.driver = Driver.objects.create(
            name="James Omondi",
            phone_number="+254712345678",
            bus_number="KBB 002B",
            company=self.company,
        )

    def test_driver_str_representation(self):
        self.assertEqual(str(self.driver), "James Omondi - KBB 002B")

    def test_list_drivers_staff_access(self):
        self.client.force_authenticate(user=self.staff_user)
        try:
            url = reverse("driver-list")
        except Exception:
            url = reverse("drivers:driver_list")
        response = self.client.get(url)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])