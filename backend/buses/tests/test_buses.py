from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from companies.models import Company

from buses.models import Bus


User = get_user_model()


class BusManagementTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(
            name="Test Bus Company",
            description="Test company",
            areas_served="Nairobi",
            phone_number="0700000010",
        )

        self.other_company = Company.objects.create(
            name="Other Bus Company",
            description="Other company",
            areas_served="Mombasa",
            phone_number="0700000011",
        )

        self.manager = User.objects.create_user(
            username="busmanager",
            password="Password123!",
            phone_number="+254700000201",
            role="company_manager",
            company=self.company,
        )

        self.auditor = User.objects.create_user(
            username="busauditor",
            password="Password123!",
            phone_number="+254700000202",
            role="company_auditor",
            company=self.company,
        )

        self.operator = User.objects.create_user(
            username="busoperator",
            password="Password123!",
            phone_number="+254700000203",
            role="company_operator",
            company=self.company,
        )

        self.passenger = User.objects.create_user(
            username="buspassenger",
            password="Password123!",
            phone_number="+254700000204",
            role="passenger",
        )

        self.other_manager = User.objects.create_user(
            username="othermanager",
            password="Password123!",
            phone_number="+254700000205",
            role="company_manager",
            company=self.other_company,
        )

        self.superuser = User.objects.create_superuser(
            username="bussuperadmin",
            password="Password123!",
            phone_number="+254700000206",
            email="bussuperadmin@example.com",
        )

        self.bus = Bus.objects.create(
            company=self.company,
            registration_number="KDA 100A",
            bus_number="BUS-001",
            capacity=33,
        )

        self.other_bus = Bus.objects.create(
            company=self.other_company,
            registration_number="KDB 200B",
            bus_number="BUS-001",
            capacity=25,
        )

        self.list_url = reverse("buses:bus-list")

    def detail_url(self, bus):
        return reverse(
            "buses:bus-detail",
            kwargs={"bus_id": bus.id},
        )

    def test_manager_can_view_own_company_buses(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.bus.id, returned_ids)
        self.assertNotIn(self.other_bus.id, returned_ids)

    def test_auditor_can_view_own_company_buses(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.bus.id, returned_ids)
        self.assertNotIn(self.other_bus.id, returned_ids)

    def test_operator_can_view_own_company_buses(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.bus.id, returned_ids)
        self.assertNotIn(self.other_bus.id, returned_ids)

    def test_passenger_cannot_view_buses(self):
        self.client.force_authenticate(user=self.passenger)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_can_create_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.list_url,
            {
                "registration_number": "KDC 300C",
                "bus_number": "BUS-003",
                "capacity": 40,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        bus = Bus.objects.get(
            registration_number="KDC 300C"
        )

        self.assertEqual(
            bus.company_id,
            self.company.id,
        )

    def test_manager_cannot_create_bus_for_other_company(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.list_url,
            {
                "company": self.other_company.id,
                "registration_number": "KDD 400D",
                "bus_number": "BUS-004",
                "capacity": 30,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            Bus.objects.filter(
                registration_number="KDD 400D"
            ).exists()
        )

    def test_auditor_cannot_create_bus(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.post(
            self.list_url,
            {
                "registration_number": "KDE 500E",
                "bus_number": "BUS-005",
                "capacity": 30,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operator_cannot_create_bus(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.post(
            self.list_url,
            {
                "registration_number": "KDF 600F",
                "bus_number": "BUS-006",
                "capacity": 30,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_can_update_own_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.patch(
            self.detail_url(self.bus),
            {
                "capacity": 45,
                "maintenance_status": "maintenance",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.bus.refresh_from_db()

        self.assertEqual(self.bus.capacity, 45)
        self.assertEqual(
            self.bus.maintenance_status,
            "maintenance",
        )

    def test_auditor_cannot_update_bus(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.patch(
            self.detail_url(self.bus),
            {"capacity": 45},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operator_cannot_update_bus(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.patch(
            self.detail_url(self.bus),
            {"capacity": 45},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_cannot_access_other_company_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.get(
            self.detail_url(self.other_bus)
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_manager_cannot_update_other_company_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.patch(
            self.detail_url(self.other_bus),
            {"capacity": 50},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.other_bus.refresh_from_db()

        self.assertEqual(
            self.other_bus.capacity,
            25,
        )

    def test_manager_cannot_delete_other_company_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            self.detail_url(self.other_bus)
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertTrue(
            Bus.objects.filter(
                id=self.other_bus.id
            ).exists()
        )

    def test_manager_can_delete_own_bus(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(
            self.detail_url(self.bus)
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.assertFalse(
            Bus.objects.filter(
                id=self.bus.id
            ).exists()
        )

    def test_superuser_can_view_all_buses(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.get(self.list_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.bus.id, returned_ids)
        self.assertIn(self.other_bus.id, returned_ids)

    def test_superuser_can_create_bus_for_any_company(self):
        self.client.force_authenticate(user=self.superuser)

        response = self.client.post(
            self.list_url,
            {
                "company": self.other_company.id,
                "registration_number": "KDG 700G",
                "bus_number": "BUS-007",
                "capacity": 35,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        bus = Bus.objects.get(
            registration_number="KDG 700G"
        )

        self.assertEqual(
            bus.company_id,
            self.other_company.id,
        )

    def test_company_manager_cannot_change_bus_company(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.patch(
            self.detail_url(self.bus),
            {
                "company": self.other_company.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.bus.refresh_from_db()

        self.assertEqual(
            self.bus.company_id,
            self.company.id,
        )

    def test_duplicate_registration_number_is_rejected(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.list_url,
            {
                "registration_number": self.bus.registration_number,
                "bus_number": "BUS-009",
                "capacity": 30,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_capacity_must_be_valid(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.list_url,
            {
                "registration_number": "KDH 800H",
                "bus_number": "BUS-008",
                "capacity": 101,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
