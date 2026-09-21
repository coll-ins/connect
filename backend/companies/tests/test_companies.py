from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking
from companies.models import Company, Route, Trip
from drivers.models import Driver  # Ensure driver model is imported
from wallets.models import Wallet

User = get_user_model()


class CompanyFunctionViewsTests(APITestCase):

  def setUp(self):
      self.company = Company.objects.create(
          name="Test Corp",
          description="A test company",
          areas_served="Nairobi",
      )
      self.other_company = Company.objects.create(
          name="Other Corp",
          description="Another company",
          areas_served="Mombasa",
      )

      self.route = Route.objects.create(
          company=self.company,
          name="Nairobi-Mombasa",
          start_point="Nairobi",
          end_point="Mombasa",
          price=Decimal("1000.00"),
      )

      # Create the driver instance matching the Driver model definition
      self.driver = Driver.objects.create(
          name="John Doe",
          phone_number="0700000000",
          bus_number="KBZ 123A",
          company=self.company,
      )

      self.trip = Trip.objects.create(
          route=self.route,
          driver=self.driver,
          departure_at=timezone.now(),
          capacity=50,
          status="scheduled",
      )

      self.user = User.objects.create_user(
          username="testuser", password="password123", phone_number="0711111111"
      )
      self.admin_user = User.objects.create_superuser(
          username="adminuser", password="password123", phone_number="0722222222"
      )
      self.company_user = User.objects.create_user(
          username="compuser",
          password="password123",
          phone_number="0733333333",
          company=self.company,
      )

      self.list_url = reverse("get_companies")
      self.routes_url = reverse("get_routes")
      self.trips_url = reverse("get_trips")


  def test_get_companies(self):
    self.client.force_authenticate(user=self.user)
    response = self.client.get(self.list_url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

  def test_get_routes_all_and_filtered(self):
    self.client.force_authenticate(user=self.user)
    # Get all routes
    response = self.client.get(self.routes_url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Get routes filtered by query param company_id
    response_filtered = self.client.get(
        f"{self.routes_url}?company_id={self.company.pk}"
    )
    self.assertEqual(response_filtered.status_code, status.HTTP_200_OK)

  def test_get_company_routes_url(self):
    self.client.force_authenticate(user=self.user)
    url = reverse("get_company_routes", kwargs={"company_id": self.company.pk})
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

  def test_get_trips_all_and_filtered(self):
    self.client.force_authenticate(user=self.user)
    # All trips
    response = self.client.get(self.trips_url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Filtered by company query param
    response_comp = self.client.get(
        f"{self.trips_url}?company_id={self.company.pk}"
    )
    self.assertEqual(response_comp.status_code, status.HTTP_200_OK)

    # Filtered by route query param
    response_route = self.client.get(
        f"{self.trips_url}?route_id={self.route.pk}"
    )
    self.assertEqual(response_route.status_code, status.HTTP_200_OK)

  def test_get_company_trips_url(self):
    self.client.force_authenticate(user=self.user)
    url = reverse("get_company_trips", kwargs={"company_id": self.company.pk})
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

  def test_get_trip_details(self):
    self.client.force_authenticate(user=self.user)
    url = reverse("get_trip_details", kwargs={"trip_id": self.trip.pk})
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    # Non-existent trip 404
    bad_url = reverse("get_trip_details", kwargs={"trip_id": 9999})
    response_404 = self.client.get(bad_url)
    self.assertEqual(response_404.status_code, status.HTTP_404_NOT_FOUND)

  def test_company_analytics_views(self):
    url = reverse("company_analytics", kwargs={"company_id": self.company.pk})

    # 1. Regular user unauthorized for other companies
    self.client.force_authenticate(user=self.user)
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # 2. Company-associated user authorized for their own company
    self.client.force_authenticate(user=self.company_user)
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

    # 3. Superuser/Staff authorized
    self.client.force_authenticate(user=self.admin_user)
    response = self.client.get(url)
    self.assertEqual(response.status_code, status.HTTP_200_OK)

  def test_update_trip_status(self):
    self.client.force_authenticate(user=self.admin_user)
    url = reverse("update_trip_status", kwargs={"trip_id": self.trip.pk})

    # Missing status field
    response_missing = self.client.post(url, {})
    self.assertEqual(response_missing.status_code, status.HTTP_400_BAD_REQUEST)

    # Invalid status choice
    response_invalid = self.client.post(url, {"status": "INVALID_STATUS"})
    self.assertEqual(response_invalid.status_code, status.HTTP_400_BAD_REQUEST)

    # Valid status update (PATCH/POST) using lowercase valid model choice
    response_valid = self.client.patch(url, {"status": "boarding"})
    self.assertEqual(response_valid.status_code, status.HTTP_200_OK)

    # Non-existent trip 404
    bad_url = reverse("update_trip_status", kwargs={"trip_id": 9999})
    response_404 = self.client.post(bad_url, {"status": "completed"})
    self.assertEqual(response_404.status_code, status.HTTP_404_NOT_FOUND)