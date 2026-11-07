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
            "phone_number": "0700000000",
            "name": "Test User",
            "location": "Nairobi",
        }
        response = self.client.post(url, payload, format="json")
        self.assertIn(response.status_code, [status.HTTP_201_CREATED, status.HTTP_200_OK])
        self.assertEqual(response.data['user']['role'], 'passenger')
        self.assertEqual(response.data['user']['phone_number'], '+254700000000')
        profile = self.client.get(self._get_url('user_profile'))
        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.data['phone_number'], '+254700000000')

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


class KenyanPhoneLoginTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='phone_format_admin',
            password='StrongPassword123!',
            phone_number='+254700001234',
            email='phone-admin@example.test',
        )
        self.login_url = reverse('users:login')

    def test_superuser_can_login_with_local_or_international_number(self):
        for phone_number in ('0700001234', '+254700001234'):
            with self.subTest(phone_number=phone_number):
                response = self.client.post(
                    self.login_url,
                    {
                        'phone_number': phone_number,
                        'password': 'StrongPassword123!',
                    },
                    format='json',
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data['user']['role'], 'platform_admin')
                self.client.logout()

    def test_login_finds_legacy_local_number_stored_in_database(self):
        User.objects.filter(pk=self.admin.pk).update(
            phone_number='0700001234'
        )

        response = self.client.post(
            self.login_url,
            {
                'phone_number': '+254700001234',
                'password': 'StrongPassword123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['user']['role'], 'platform_admin')


class CompanyStaffManagementTests(APITestCase):

    def setUp(self):
        from companies.models import Company

        self.company = Company.objects.create(
            name="Test Company",
            description="Test company",
            areas_served="Nairobi",
            phone_number="0700000000",
        )

        self.other_company = Company.objects.create(
            name="Other Company",
            description="Other company",
            areas_served="Mombasa",
            phone_number="0711111111",
        )

        self.manager = User.objects.create_user(
            username="manager",
            password="Password123!",
            phone_number="+254700000101",
            role="company_manager",
            company=self.company,
        )

        self.auditor = User.objects.create_user(
            username="auditor",
            password="Password123!",
            phone_number="+254700000102",
            role="company_auditor",
            company=self.company,
        )

        self.operator = User.objects.create_user(
            username="operator",
            password="Password123!",
            phone_number="+254700000103",
            role="company_operator",
            company=self.company,
        )

        self.passenger = User.objects.create_user(
            username="passenger",
            password="Password123!",
            phone_number="+254700000104",
            role="passenger",
        )

        self.other_staff = User.objects.create_user(
            username="otherstaff",
            password="Password123!",
            phone_number="+254700000105",
            role="company_operator",
            company=self.other_company,
        )

        self.admin = User.objects.create_superuser(
            username="superadmin",
            password="Password123!",
            phone_number="+254700000106",
            email="admin@example.com",
        )

        self.staff_url = reverse("users:company-staff")

    def test_manager_can_view_own_company_staff(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.get(self.staff_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.manager.id, returned_ids)
        self.assertIn(self.auditor.id, returned_ids)
        self.assertIn(self.operator.id, returned_ids)
        self.assertNotIn(self.other_staff.id, returned_ids)

    def test_auditor_can_view_own_company_staff(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.get(self.staff_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.manager.id, returned_ids)
        self.assertIn(self.auditor.id, returned_ids)
        self.assertIn(self.operator.id, returned_ids)
        self.assertNotIn(self.other_staff.id, returned_ids)

    def test_operator_can_view_own_company_staff(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.get(self.staff_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.manager.id, returned_ids)
        self.assertIn(self.auditor.id, returned_ids)
        self.assertIn(self.operator.id, returned_ids)
        self.assertNotIn(self.other_staff.id, returned_ids)

    def test_passenger_cannot_view_company_staff(self):
        self.client.force_authenticate(user=self.passenger)

        response = self.client.get(self.staff_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_manager_can_create_company_operator(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.staff_url,
            {
                "username": "newoperator",
                "email": "newoperator@example.com",
                "phone_number": "+254700000107",
                "location": "Nairobi",
                "role": "company_operator",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED
        )

        created = User.objects.get(username="newoperator")

        self.assertEqual(created.role, "company_operator")
        self.assertEqual(created.company_id, self.company.id)
        self.assertFalse(created.is_superuser)

    def test_manager_cannot_create_staff_for_other_company(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.staff_url,
            {
                "username": "outsider",
                "email": "outsider@example.com",
                "phone_number": "+254700000108",
                "location": "Nairobi",
                "role": "company_operator",
                "company": self.other_company.id,
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertFalse(
            User.objects.filter(username="outsider").exists()
        )

    def test_manager_cannot_create_platform_admin(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.staff_url,
            {
                "username": "fakeadmin",
                "email": "fakeadmin@example.com",
                "phone_number": "+254700000109",
                "role": "platform_admin",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST
        )

        self.assertFalse(
            User.objects.filter(username="fakeadmin").exists()
        )

    def test_auditor_cannot_create_staff(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.post(
            self.staff_url,
            {
                "username": "auditorcreated",
                "email": "auditorcreated@example.com",
                "phone_number": "+254700000110",
                "role": "company_operator",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_operator_cannot_create_staff(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.post(
            self.staff_url,
            {
                "username": "operatorcreated",
                "email": "operatorcreated@example.com",
                "phone_number": "+254700000111",
                "role": "company_operator",
                "password": "Password123!",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_manager_can_update_staff_role(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.operator.id},
        )

        response = self.client.patch(
            url,
            {"role": "company_auditor"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.operator.refresh_from_db()
        self.assertEqual(
            self.operator.role,
            "company_auditor"
        )

    def test_auditor_cannot_update_staff(self):
        self.client.force_authenticate(user=self.auditor)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.operator.id},
        )

        response = self.client.patch(
            url,
            {"role": "company_manager"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_operator_cannot_update_staff(self):
        self.client.force_authenticate(user=self.operator)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.auditor.id},
        )

        response = self.client.patch(
            url,
            {"role": "company_manager"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_manager_cannot_update_other_company_staff(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.other_staff.id},
        )

        response = self.client.patch(
            url,
            {"role": "company_manager"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

    def test_manager_can_remove_own_company_staff(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.operator.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK
        )

        self.assertFalse(
            User.objects.filter(id=self.operator.id).exists()
        )

    def test_manager_cannot_remove_other_company_staff(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.other_staff.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertTrue(
            User.objects.filter(id=self.other_staff.id).exists()
        )

    def test_company_staff_cannot_manage_superuser(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.admin.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertTrue(
            User.objects.filter(id=self.admin.id).exists()
        )

    def test_manager_cannot_update_passenger_as_staff(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.passenger.id},
        )

        response = self.client.patch(
            url,
            {"role": "company_operator"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.passenger.refresh_from_db()

        self.assertEqual(
            self.passenger.role,
            "passenger"
        )

    def test_manager_cannot_remove_passenger_as_staff(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.passenger.id},
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertTrue(
            User.objects.filter(id=self.passenger.id).exists()
        )

    def test_manager_cannot_update_driver_as_staff(self):
        from drivers.models import Driver

        driver = Driver.objects.create(
            name="Test Driver",
            phone_number="+254700000120",
            bus_number="TEST-001",
            company=self.company,
        )

        driver_user = User.objects.create_user(
            username="driveruser",
            password="Password123!",
            phone_number="+254700000121",
            role="driver",
            company=self.company,
        )

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": driver_user.id},
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.patch(
            url,
            {"role": "company_operator"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        driver_user.refresh_from_db()

        self.assertEqual(
            driver_user.role,
            "driver"
        )

        driver.delete()

    def test_manager_cannot_remove_driver_as_staff(self):
        driver_user = User.objects.create_user(
            username="driveruser2",
            password="Password123!",
            phone_number="+254700000122",
            role="driver",
            company=self.company,
        )

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": driver_user.id},
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertTrue(
            User.objects.filter(id=driver_user.id).exists()
        )

    def test_superuser_can_view_all_company_staff(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.staff_url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(self.manager.id, returned_ids)
        self.assertIn(self.other_staff.id, returned_ids)

    def test_manager_cannot_change_staff_company(self):
        self.client.force_authenticate(user=self.manager)

        url = reverse(
            "users:company-staff-detail",
            kwargs={"staff_id": self.operator.id},
        )

        response = self.client.patch(
            url,
            {"company": self.other_company.id},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK
        )

        self.operator.refresh_from_db()

        self.assertEqual(
            self.operator.company_id,
            self.company.id
        )


class UserDirectoryTests(APITestCase):
    def test_only_superusers_get_the_user_directory(self):
        url = reverse("users:user-api-root")
        passenger = User.objects.create_user(
            username="p", password="pw-123456", phone_number="+254700000101",
        )
        admin = User.objects.create_superuser(
            username="a", password="pw-123456", phone_number="+254700000102",
            email="a@example.com",
        )

        self.assertIn("endpoints", self.client.get(url).data)
        self.client.force_authenticate(passenger)
        self.assertIn("endpoints", self.client.get(url).data)

        self.client.force_authenticate(admin)
        rows = self.client.get(url).data
        self.assertEqual({r["username"] for r in rows}, {"p", "a"})
        self.assertNotIn("password", rows[0])


class StaffManagementGuardTests(APITestCase):
    def setUp(self):
        from companies.models import Company
        self.company = Company.objects.create(name="C", areas_served="x")
        self.manager = User.objects.create_user(
            username="m", password="pw-123456", phone_number="+254700000201",
            role="company_manager", company=self.company,
        )
        self.staff = User.objects.create_user(
            username="s", password="pw-123456", phone_number="+254700000202",
            role="company_operator", company=self.company,
        )
        self.client.force_authenticate(self.manager)

    def _url(self, pk):
        return reverse("users:company-staff-detail", kwargs={"staff_id": pk})

    def test_staff_password_change_uses_password_validators(self):
        r = self.client.patch(self._url(self.staff.id), {"password": "abcdef"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(self._url(self.staff.id), {"password": "Matatu-Route-58"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_manager_cannot_delete_own_account(self):
        r = self.client.delete(self._url(self.manager.id))
        self.assertEqual(r.status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.manager.pk).exists())

    def test_manager_cannot_change_own_role_or_deactivate_self(self):
        for body in ({"role": "company_operator"}, {"is_active": False}):
            r = self.client.patch(self._url(self.manager.id), body, format="json")
            self.assertEqual(r.status_code, 400)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, "company_manager")
        self.assertTrue(self.manager.is_active)
