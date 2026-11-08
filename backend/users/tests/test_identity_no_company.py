from django.contrib.auth import get_user_model
from django.test import TestCase

from companies.models import Company
from drivers.models import Driver
from users.identity import drivers_for_user, is_driver_account_for


class DriverLoginWithoutCompanyTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name='Sacco A')
        self.b = Company.objects.create(name='Sacco B')
        self.driver_a = Driver.objects.create(
            name='A', phone_number='+254711000111', bus_number='KAA-1', company=self.a,
        )
        self.login = get_user_model().objects.create_user(
            username='old_driver', password='password123',
            phone_number='+254711000111', role='driver',
        )

    def test_unambiguous_phone_still_signs_in(self):
        self.assertTrue(is_driver_account_for(self.login, self.driver_a))

    def test_phone_shared_with_a_rival_company_matches_nobody(self):
        driver_b = Driver.objects.create(
            name='B', phone_number='+254711000111', bus_number='KBB-1', company=self.b,
        )
        self.assertFalse(is_driver_account_for(self.login, driver_b))
        self.assertFalse(is_driver_account_for(self.login, self.driver_a))
        self.assertFalse(drivers_for_user(self.login).exists())
