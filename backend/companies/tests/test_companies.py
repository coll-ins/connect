import threading
import unittest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
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
          role="company_auditor",
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


    def test_create_trip_platform_admin(self):
      self.client.force_authenticate(user=self.admin_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 40,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_201_CREATED
      )
      self.assertEqual(
          response.data["capacity"],
          40
      )
      self.assertEqual(
          response.data["status"],
          "scheduled"
      )


  def test_create_trip_company_manager_own_company(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_201_CREATED
      )


  def test_create_trip_company_manager_cannot_manage_other_company(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.other_company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_trip_regular_user_forbidden(self):
      self.client.force_authenticate(user=self.user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_trip_wrong_route_company_rejected(self):
      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="Nairobi",
          end_point="Kisumu",
          price=Decimal("500.00"),
      )

      self.client.force_authenticate(user=self.admin_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": other_route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_404_NOT_FOUND
      )


  def test_create_trip_invalid_capacity_rejected(self):
      self.client.force_authenticate(user=self.admin_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 0,
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_400_BAD_REQUEST
      )

  def test_create_route_manager_own_company_allowed(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "name": "CBD-Rongai",
              "start_point": "CBD",
              "end_point": "Rongai",
              "price": "150.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_201_CREATED
      )
      self.assertEqual(
          response.data["company"],
          self.company.pk
      )
      self.assertEqual(
          response.data["name"],
          "CBD-Rongai"
      )


  def test_create_route_manager_other_company_forbidden(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.other_company.pk,
              "name": "Other Route",
              "start_point": "Nairobi",
              "end_point": "Kisumu",
              "price": "500.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_route_auditor_forbidden(self):
      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "name": "Auditor Route",
              "start_point": "CBD",
              "end_point": "Westlands",
              "price": "100.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_route_operator_forbidden(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "name": "Operator Route",
              "start_point": "CBD",
              "end_point": "Kasarani",
              "price": "120.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_route_passenger_forbidden(self):
      self.client.force_authenticate(user=self.user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "name": "Passenger Route",
              "start_point": "CBD",
              "end_point": "Karen",
              "price": "200.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_create_route_superuser_any_company_allowed(self):
      self.client.force_authenticate(user=self.admin_user)

      url = reverse("create_route")

      response = self.client.post(
          url,
          {
              "company_id": self.other_company.pk,
              "name": "Global Route",
              "start_point": "Nairobi",
              "end_point": "Mombasa",
              "price": "1000.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_201_CREATED
      )
      self.assertEqual(
          response.data["company"],
          self.other_company.pk
      )


  def test_edit_route_manager_own_company_allowed(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "name": "Nairobi-Kisumu",
              "price": "1200.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_200_OK
      )

      self.route.refresh_from_db()

      self.assertEqual(
          self.route.name,
          "Nairobi-Kisumu"
      )
      self.assertEqual(
          self.route.price,
          Decimal("1200.00")
      )
      self.assertEqual(
          self.route.company_id,
          self.company.pk
      )


  def test_edit_route_manager_cannot_change_company(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "company": self.other_company.pk,
              "name": "Attempted Transfer",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_200_OK
      )

      self.route.refresh_from_db()

      self.assertEqual(
          self.route.company_id,
          self.company.pk
      )
      self.assertEqual(
          self.route.name,
          "Attempted Transfer"
      )


  def test_edit_route_other_company_manager_forbidden(self):
      other_manager = User.objects.create_user(
          username="othermanager",
          password="password123",
          phone_number="0744444444",
          company=self.other_company,
          role="company_manager",
      )

      self.client.force_authenticate(user=other_manager)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "name": "Unauthorized Edit",
              "price": "999.00",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_edit_route_auditor_forbidden(self):
      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "name": "Auditor Edit",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_edit_route_operator_forbidden(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "name": "Operator Edit",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_edit_route_passenger_forbidden(self):
      self.client.force_authenticate(user=self.user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.patch(
          url,
          {
              "name": "Passenger Edit",
          },
          format="json",
      )

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_delete_route_manager_own_company_allowed(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      route = Route.objects.create(
          company=self.company,
          name="Delete Me",
          start_point="CBD",
          end_point="Embakasi",
          price=Decimal("100.00"),
      )

      url = reverse(
          "manage_route",
          kwargs={"route_id": route.pk}
      )

      response = self.client.delete(url)

      self.assertEqual(
          response.status_code,
          status.HTTP_200_OK
      )

      self.assertFalse(
          Route.objects.filter(pk=route.pk).exists()
      )


  def test_delete_route_auditor_forbidden(self):
      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.delete(url)

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_delete_route_operator_forbidden(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.delete(url)

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_delete_route_other_company_manager_forbidden(self):
      other_manager = User.objects.create_user(
          username="otherdeletemanager",
          password="password123",
          phone_number="0755555555",
          company=self.other_company,
          role="company_manager",
      )

      self.client.force_authenticate(user=other_manager)

      url = reverse(
          "manage_route",
          kwargs={"route_id": self.route.pk}
      )

      response = self.client.delete(url)

      self.assertEqual(
          response.status_code,
          status.HTTP_403_FORBIDDEN
      )


  def test_delete_route_superuser_any_company_allowed(self):
      self.client.force_authenticate(user=self.admin_user)

      route = Route.objects.create(
          company=self.other_company,
          name="Superuser Delete",
          start_point="CBD",
          end_point="Thika",
          price=Decimal("80.00"),
      )

      url = reverse(
          "manage_route",
          kwargs={"route_id": route.pk}
      )

      response = self.client.delete(url)

      self.assertEqual(
          response.status_code,
          status.HTTP_200_OK
      )

      self.assertFalse(
          Route.objects.filter(pk=route.pk).exists()
      )

  def test_create_trip_company_auditor_forbidden(self):
      self.company_user.role = "company_auditor"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_create_trip_company_operator_forbidden(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse("create_trip")

      response = self.client.post(
          url,
          {
              "company_id": self.company.pk,
              "route_id": self.route.pk,
              "driver_id": self.driver.pk,
              "departure_at": (
                  timezone.now() + timezone.timedelta(hours=2)
              ).isoformat(),
              "capacity": 30,
          },
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_update_trip_status_company_manager_own_company_allowed(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": self.trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_200_OK)

      self.trip.refresh_from_db()
      self.assertEqual(self.trip.status, "boarding")


  def test_update_trip_status_company_operator_own_company_allowed(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": self.trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_200_OK)

      self.trip.refresh_from_db()
      self.assertEqual(self.trip.status, "boarding")


  def test_update_trip_status_company_auditor_forbidden(self):
      self.company_user.role = "company_auditor"
      self.company_user.save(update_fields=["role"])

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": self.trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_update_trip_status_passenger_forbidden(self):
      self.client.force_authenticate(user=self.user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": self.trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_update_trip_status_manager_other_company_forbidden(self):
      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])

      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0799999999",
          bus_number="KXX 999X",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Kisumu",
          price=Decimal("500.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": other_trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_update_trip_status_operator_other_company_forbidden(self):
      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])

      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0788888888",
          bus_number="KYY 888Y",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Nakuru",
          price=Decimal("600.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "update_trip_status",
          kwargs={"trip_id": other_trip.pk}
      )

      response = self.client.patch(
          url,
          {"status": "boarding"},
          format="json",
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_get_trips_company_staff_cannot_access_other_company(self):
      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0777777777",
          bus_number="KZZ 777Z",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Nakuru",
          price=Decimal("600.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.company_user.role = "company_manager"
      self.company_user.save(update_fields=["role"])
      self.client.force_authenticate(user=self.company_user)

      response = self.client.get(
          f"{self.trips_url}?company_id={self.other_company.pk}"
      )

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
      self.assertEqual(
          response.data["error"],
          "You cannot access trips from another company."
      )


  def test_get_trips_company_staff_only_sees_own_company(self):
      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0776666666",
          bus_number="KYY 666Y",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Thika",
          price=Decimal("400.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.company_user.role = "company_auditor"
      self.company_user.save(update_fields=["role"])
      self.client.force_authenticate(user=self.company_user)

      response = self.client.get(self.trips_url)

      self.assertEqual(response.status_code, status.HTTP_200_OK)

      returned_ids = [trip["id"] for trip in response.data]

      self.assertIn(self.trip.pk, returned_ids)
      self.assertNotIn(other_trip.pk, returned_ids)


  def test_get_trip_details_company_staff_cannot_access_other_company(self):
      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0775555555",
          bus_number="KXX 555X",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Machakos",
          price=Decimal("700.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.company_user.role = "company_operator"
      self.company_user.save(update_fields=["role"])
      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "get_trip_details",
          kwargs={"trip_id": other_trip.pk}
      )

      response = self.client.get(url)

      self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


  def test_get_trip_details_company_staff_can_access_own_company(self):
      self.company_user.role = "company_auditor"
      self.company_user.save(update_fields=["role"])
      self.client.force_authenticate(user=self.company_user)

      url = reverse(
          "get_trip_details",
          kwargs={"trip_id": self.trip.pk}
      )

      response = self.client.get(url)

      self.assertEqual(response.status_code, status.HTTP_200_OK)


  def test_get_trips_superuser_can_access_any_company(self):
      other_driver = Driver.objects.create(
          name="Other Driver",
          phone_number="0774444444",
          bus_number="KWW 444W",
          company=self.other_company,
      )

      other_route = Route.objects.create(
          company=self.other_company,
          name="Other Route",
          start_point="CBD",
          end_point="Kitengela",
          price=Decimal("350.00"),
      )

      other_trip = Trip.objects.create(
          route=other_route,
          driver=other_driver,
          departure_at=timezone.now(),
          capacity=40,
          status="scheduled",
      )

      self.client.force_authenticate(user=self.admin_user)

      response = self.client.get(
          f"{self.trips_url}?company_id={self.other_company.pk}"
      )

      self.assertEqual(response.status_code, status.HTTP_200_OK)

      returned_ids = [trip["id"] for trip in response.data]
      self.assertIn(other_trip.pk, returned_ids)


class TripStatusConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Trip Status Race Co",
        )

        self.manager = User.objects.create_user(
            username="trip_status_race_manager",
            password="password123",
            role="company_manager",
            company=self.company,
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Status Race Route",
            start_point="CBD",
            end_point="Ngong",
            price=Decimal("300.00"),
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Trip Status Race Driver",
            phone_number="+254711111114",
            bus_number="KAA 114D",
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=10,
            status="scheduled",
        )

    def tearDown(self):
        connections.close_all()

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "True row-level locking test requires PostgreSQL.",
    )
    def test_invalid_transition_is_rejected_after_locked_state_changes(self):
        """
        Prove the endpoint does not rely only on the stale state read
        performed before entering transaction.atomic().

        The trip is changed to cancelled while another request is
        already attempting to move it to boarding. The request must
        re-check the locked current state and return 409.
        """
        from rest_framework.test import APIClient

        ready = threading.Event()
        results = []

        def attempt_boarding():
            close_old_connections()

            try:
                client = APIClient()
                client.force_authenticate(user=self.manager)

                ready.set()

                response = client.patch(
                    reverse(
                        "update_trip_status",
                        kwargs={"trip_id": self.trip.pk},
                    ),
                    {"status": "boarding"},
                    format="json",
                )

                results.append(response.status_code)
            except Exception as exc:
                results.append(f"error: {exc}")
            finally:
                connections.close_all()

        close_old_connections()

        with transaction.atomic():
            locked_trip = (
                Trip.objects
                .select_for_update()
                .get(pk=self.trip.pk)
            )

            locked_trip.status = "cancelled"
            locked_trip.save(update_fields=["status"])

            worker = threading.Thread(
                target=attempt_boarding,
            )
            worker.start()

            ready.wait(timeout=5)

            # Keep the row locked until the worker has had a chance
            # to enter the endpoint and wait on select_for_update().
            import time
            time.sleep(0.15)

        worker.join(timeout=5)

        connections.close_all()

        self.assertEqual(
            results,
            [409],
            results,
        )

        self.trip.refresh_from_db()

        self.assertEqual(
            self.trip.status,
            "cancelled",
        )


class RouteHistoryDeletionTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Route History Test Co",
        )

        self.manager = User.objects.create_user(
            username="route_history_manager",
            password="password123",
            phone_number="+254711111119",
            company=self.company,
            role="company_manager",
        )

        self.passenger = User.objects.create_user(
            username="route_history_passenger",
            password="password123",
            phone_number="+254700000030",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Route History Driver",
            phone_number="+254711111120",
            bus_number="KAA 120J",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Protected History Route",
            start_point="CBD",
            end_point="Ngong",
            price=Decimal("500.00"),
        )

    def test_route_with_trip_history_cannot_be_deleted(self):
        Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=10,
            status="completed",
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            reverse(
                "manage_route",
                kwargs={"route_id": self.route.id},
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.assertTrue(
            Route.objects.filter(pk=self.route.pk).exists()
        )

    def test_route_with_booking_history_cannot_be_deleted(self):
        Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=None,
            total_amount=Decimal("500.00"),
            status="cancelled",
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            reverse(
                "manage_route",
                kwargs={"route_id": self.route.id},
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.assertTrue(
            Route.objects.filter(pk=self.route.pk).exists()
        )


