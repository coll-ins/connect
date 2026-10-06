from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from companies.models import Company
from drivers.models import Driver

User = get_user_model()

LIST_URL = "/api/drivers/"


def detail_url(driver_id):
    return f"/api/drivers/{driver_id}/"


class DriverReadAccessTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Coast Bus", areas_served="Mombasa")
        self.other_company = Company.objects.create(name="Nairobi Shuttle", areas_served="Nairobi")

        def mk(username, phone, role, company=None):
            return User.objects.create_user(
                username=username, password="password123",
                phone_number=phone, role=role, company=company,
            )

        self.manager = mk("manager", "+254700000001", "company_manager", self.company)
        self.auditor = mk("auditor", "+254700000002", "company_auditor", self.company)
        self.operator = mk("operator", "+254700000003", "company_operator", self.company)
        self.other_manager = mk("other_manager", "+254700000004", "company_manager", self.other_company)
        self.passenger = mk("passenger", "+254700000005", "passenger")
        self.driver_user = mk("driver_user", "+254712345678", "driver", self.company)
        self.other_driver_user = mk("other_driver_user", "+254712345699", "driver", self.company)
        self.superuser = User.objects.create_superuser(
            username="superuser", password="password123",
            phone_number="+254700000009", email="su@example.com",
        )

        self.driver = Driver.objects.create(
            name="Own Driver", phone_number="+254712345678",
            bus_number="KAA 001A", company=self.company,
            latitude=-1.29, longitude=36.82,
        )
        self.other_company_driver = Driver.objects.create(
            name="Other Driver", phone_number="+254722222222",
            bus_number="KBB 002B", company=self.other_company,
            latitude=-1.30, longitude=36.83,
        )

    # --- anonymous ---
    def test_anonymous_list_401(self):
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_detail_denied(self):
        r = self.client.get(detail_url(self.driver.id))
        self.assertIn(r.status_code, (401, 403))
        self.assertNotIn("phone_number", r.data)

    # --- passenger ---
    def test_passenger_list_403(self):
        self.client.force_authenticate(self.passenger)
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_passenger_list_with_company_id_403(self):
        self.client.force_authenticate(self.passenger)
        r = self.client.get(f"{LIST_URL}?company_id={self.company.id}")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_passenger_detail_403(self):
        self.client.force_authenticate(self.passenger)
        r = self.client.get(detail_url(self.driver.id))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    # --- staff of another company ---
    def test_other_company_staff_cannot_request_foreign_company(self):
        self.client.force_authenticate(self.other_manager)
        r = self.client.get(f"{LIST_URL}?company_id={self.company.id}")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_company_staff_list_only_own_drivers(self):
        self.client.force_authenticate(self.other_manager)
        r = self.client.get(LIST_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        ids = {d["id"] for d in r.data}
        self.assertEqual(ids, {self.other_company_driver.id})

    def test_other_company_staff_detail_403(self):
        self.client.force_authenticate(self.other_manager)
        r = self.client.get(detail_url(self.driver.id))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    # --- same-company staff ---
    def test_same_company_staff_can_read(self):
        for user in (self.manager, self.auditor, self.operator):
            with self.subTest(role=user.role):
                self.client.force_authenticate(user)
                lst = self.client.get(LIST_URL)
                self.assertEqual(lst.status_code, status.HTTP_200_OK)
                self.assertEqual({d["id"] for d in lst.data}, {self.driver.id})
                det = self.client.get(detail_url(self.driver.id))
                self.assertEqual(det.status_code, status.HTTP_200_OK)

    # --- driver role ---
    def test_driver_reads_only_own_record(self):
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(self.client.get(detail_url(self.driver.id)).status_code, 200)
        self.assertEqual(self.client.get(detail_url(self.other_company_driver.id)).status_code, 403)

    def test_driver_cannot_list(self):
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(self.client.get(LIST_URL).status_code, 403)

    def test_driver_cannot_read_coworker_record(self):
        coworker = Driver.objects.create(
            name="Coworker", phone_number="+254712345699",
            bus_number="KCC 003C", company=self.company,
        )
        self.client.force_authenticate(self.driver_user)
        self.assertEqual(self.client.get(detail_url(coworker.id)).status_code, 403)

    # --- superuser ---
    def test_superuser_reads_everything(self):
        self.client.force_authenticate(self.superuser)
        lst = self.client.get(LIST_URL)
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(len(lst.data), 2)
        for d in (self.driver, self.other_company_driver):
            self.assertEqual(self.client.get(detail_url(d.id)).status_code, 200)
