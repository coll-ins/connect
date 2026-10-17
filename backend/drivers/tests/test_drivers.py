from datetime import timedelta
from decimal import Decimal
from bookings.models import Booking
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class DriversAppTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(
            name="Coast Bus"
        )
        self.other_company = Company.objects.create(
            name="Nairobi Shuttle"
        )

        self.manager = User.objects.create_user(
            username="manager",
            password="password123",
            phone_number="+254700000001",
            role="company_manager",
            company=self.company,
        )

        self.auditor = User.objects.create_user(
            username="auditor",
            password="password123",
            phone_number="+254700000002",
            role="company_auditor",
            company=self.company,
        )

        self.operator = User.objects.create_user(
            username="operator",
            password="password123",
            phone_number="+254700000003",
            role="company_operator",
            company=self.company,
        )

        self.other_manager = User.objects.create_user(
            username="other_manager",
            password="password123",
            phone_number="+254700000004",
            role="company_manager",
            company=self.other_company,
        )

        self.passenger = User.objects.create_user(
            username="passenger",
            password="password123",
            phone_number="+254700000005",
            role="passenger",
        )

        self.driver_user = User.objects.create_user(
            username="driver_user",
            password="password123",
            phone_number="+254712345678",
            role="driver",
            company=self.company,
        )

        self.superuser = User.objects.create_superuser(
            username="superuser",
            password="password123",
            phone_number="+254700000006",
        )

        self.driver = Driver.objects.create(
            name="James Omondi",
            phone_number="+254712345678",
            bus_number="KBB 002B",
            company=self.company,
            latitude=-1.286389,
            longitude=36.817223,
        )

        self.other_driver = Driver.objects.create(
            name="Peter Mwangi",
            phone_number="+254722222222",
            bus_number="KCC 003C",
            company=self.other_company,
        )

    def test_driver_str_representation(self):
        self.assertEqual(
            str(self.driver),
            "James Omondi - KBB 002B"
        )

    def test_manager_can_list_own_company_drivers(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["id"],
            self.driver.id,
        )

    def test_auditor_can_list_own_company_drivers(self):
        self.client.force_authenticate(user=self.auditor)

        url = reverse("drivers:driver-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)

    def test_operator_can_list_own_company_drivers(self):
        self.client.force_authenticate(user=self.operator)

        url = reverse("drivers:driver-list")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(len(response.data), 1)

    def test_manager_cannot_list_another_company(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")
        response = self.client.get(
            url,
            {"company_id": self.other_company.id},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_auditor_cannot_list_another_company(self):
        self.client.force_authenticate(user=self.auditor)

        url = reverse("drivers:driver-list")
        response = self.client.get(
            url,
            {"company_id": self.other_company.id},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operator_cannot_list_another_company(self):
        self.client.force_authenticate(user=self.operator)

        url = reverse("drivers:driver-list")
        response = self.client.get(
            url,
            {"company_id": self.other_company.id},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_can_create_driver_with_login_account(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "New Driver",
                "phone_number": "+254733333333",
                "bus_number": "KDD 004D",
                "company": self.company.id,
                "password": "driverpass123",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        driver = Driver.objects.get(
            phone_number="+254733333333"
        )

        self.assertEqual(
            driver.company_id,
            self.company.id,
        )

        driver_user = User.objects.get(
            phone_number="+254733333333"
        )

        self.assertEqual(
            driver_user.role,
            "driver",
        )

        self.assertEqual(
            driver_user.company_id,
            self.company.id,
        )

        self.assertTrue(
            driver_user.check_password("driverpass123")
        )

        self.assertTrue(
            driver_user.username.startswith("driver_")
        )

    def test_manager_cannot_create_driver_without_password(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "No Password Driver",
                "phone_number": "+254744444444",
                "bus_number": "KFF 005F",
                "company": self.company.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Driver.objects.filter(
                phone_number="+254744444444"
            ).exists()
        )

    def test_manager_cannot_create_driver_with_existing_user_phone(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "Duplicate User Phone",
                "phone_number": self.manager.phone_number,
                "bus_number": "KFF 006F",
                "company": self.company.id,
                "password": "driverpass123",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.assertFalse(
            Driver.objects.filter(
                phone_number=self.manager.phone_number
            ).exists()
        )

    def test_manager_company_is_used_even_if_another_company_is_submitted(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "Other Driver",
                "phone_number": "+254744444444",
                "bus_number": "KEE 005E",
                "company": self.other_company.id,
                "password": "driverpass123",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        driver = Driver.objects.get(
            phone_number="+254744444444"
        )

        self.assertEqual(
            driver.company_id,
            self.manager.company_id,
        )

        self.assertNotEqual(
            driver.company_id,
            self.other_company.id,
        )

        created_user = User.objects.get(
            phone_number="+254744444444"
        )

        self.assertEqual(
            created_user.role,
            "driver",
        )

        self.assertEqual(
            created_user.company_id,
            self.manager.company_id,
        )

    def test_auditor_cannot_create_driver(self):
        self.client.force_authenticate(user=self.auditor)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "Auditor Driver",
                "phone_number": "+254755555555",
                "bus_number": "KFF 006F",
                "company": self.company.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operator_cannot_create_driver(self):
        self.client.force_authenticate(user=self.operator)

        url = reverse("drivers:driver-list")

        response = self.client.post(
            url,
            {
                "name": "Operator Driver",
                "phone_number": "+254766666666",
                "bus_number": "KGG 007G",
                "company": self.company.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_can_view_driver_detail(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_manager_can_update_own_driver(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "James Updated"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.driver.refresh_from_db()
        self.assertEqual(
            self.driver.name,
            "James Updated",
        )

    def test_manager_cannot_move_driver_to_another_company(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.patch(
            url,
            {"company": self.other_company.id},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.driver.refresh_from_db()

        self.assertEqual(
            self.driver.company_id,
            self.company.id,
        )

    def test_auditor_cannot_update_driver(self):
        self.client.force_authenticate(user=self.auditor)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "Hacked Driver"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operator_cannot_update_driver(self):
        self.client.force_authenticate(user=self.operator)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "Hacked Driver"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_cannot_access_another_company_driver(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.other_driver.id},
        )

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_cannot_update_another_company_driver(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.other_driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "Unauthorized Update"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_can_delete_own_driver(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertFalse(
            Driver.objects.filter(
                id=self.driver.id
            ).exists()
        )

    def test_manager_cannot_delete_another_company_driver(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.other_driver.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_passenger_cannot_modify_driver(self):
        self.client.force_authenticate(user=self.passenger)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "Passenger Update"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_driver_can_update_own_location(self):
        self.client.force_authenticate(user=self.driver_user)

        url = reverse(
            "drivers:driver-location",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.post(
            url,
            {
                "latitude": -1.2921,
                "longitude": 36.8219,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIsNotNone(response.data["location_updated_at"])

        self.driver.refresh_from_db()

        self.assertAlmostEqual(
            self.driver.latitude,
            -1.2921,
        )
        self.assertAlmostEqual(
            self.driver.longitude,
            36.8219,
        )
        self.assertIsNotNone(self.driver.location_updated_at)
        self.assertLess(
            (timezone.now() - self.driver.location_updated_at).total_seconds(),
            10,
        )
        self.assertEqual(
            response.data["location_updated_at"],
            self.driver.location_updated_at,
        )

    def test_driver_cannot_update_another_driver_location(self):
        self.client.force_authenticate(user=self.driver_user)

        url = reverse(
            "drivers:driver-location",
            kwargs={"driver_id": self.other_driver.id},
        )

        response = self.client.post(
            url,
            {
                "latitude": -1.2921,
                "longitude": 36.8219,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_superuser_can_manage_any_driver(self):
        self.client.force_authenticate(user=self.superuser)

        url = reverse(
            "drivers:driver-detail",
            kwargs={"driver_id": self.other_driver.id},
        )

        response = self.client.patch(
            url,
            {"name": "Superuser Updated"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.other_driver.refresh_from_db()

        self.assertEqual(
            self.other_driver.name,
            "Superuser Updated",
        )

    def test_invalid_coordinates_are_rejected_without_refreshing_timestamp(self):
        self.client.force_authenticate(user=self.driver_user)

        old_timestamp = timezone.now() - timedelta(hours=1)
        self.driver.location_updated_at = old_timestamp
        self.driver.save(update_fields=["location_updated_at"])

        url = reverse(
            "drivers:driver-location",
            kwargs={"driver_id": self.driver.id},
        )

        response = self.client.post(
            url,
            {
                "latitude": 200,
                "longitude": 36.8219,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.driver.refresh_from_db()
        self.assertEqual(self.driver.location_updated_at, old_timestamp)

    def test_my_driver_profile_returns_driver(self):
        self.client.force_authenticate(user=self.driver_user)

        url = reverse("drivers:my-driver-profile")
        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["id"],
            self.driver.id,
        )


class DriverHistoryDeletionTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Driver History Test Co",
        )

        self.manager = User.objects.create_user(
            username="driver_history_manager",
            password="password123",
            phone_number="+254700000031",
            role="company_manager",
            company=self.company,
        )

        self.passenger = User.objects.create_user(
            username="driver_history_passenger",
            password="password123",
            phone_number="+254700000032",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Protected History Driver",
            phone_number="+254711111121",
            bus_number="KAA 121K",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Driver History Route",
            start_point="CBD",
            end_point="Karen",
            price=Decimal("600.00"),
        )

    def test_driver_with_trip_history_cannot_be_deleted(self):
        Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=4),
            capacity=14,
            status="completed",
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            reverse(
                "drivers:driver-detail",
                kwargs={"driver_id": self.driver.id},
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.assertTrue(
            Driver.objects.filter(pk=self.driver.pk).exists()
        )

    def test_driver_with_booking_history_cannot_be_deleted(self):
        Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=None,
            driver=self.driver,
            total_amount=Decimal("600.00"),
            status="cancelled",
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            reverse(
                "drivers:driver-detail",
                kwargs={"driver_id": self.driver.id},
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.assertTrue(
            Driver.objects.filter(pk=self.driver.pk).exists()
        )


