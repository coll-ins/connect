from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from bookings.models import Payment
from bookings.tests.test_round5 import _Fixture
from bookings.tests.test_round12 import _url_name
from companies.models import Company
from drivers.models import Driver
from users.identity import drivers_for_user, is_driver_account_for

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


class IdentityTests(TestCase):
    def setUp(self):
        self.co = Company.objects.create(name='R14 Co')
        self.other = Company.objects.create(name='R14 Other Co')
        self.driver = Driver.objects.create(
            company=self.co, name='D', phone_number='+254712100001', bus_number='KAA 1')

    def _user(self, username, phone, **extra):
        return User.objects.create_user(
            username=username, password=STRONG, phone_number=phone, **extra)

    def test_driver_account_of_the_same_company_matches(self):
        user = self._user('r14_ok', '+254712100001', role='driver', company=self.co)
        self.assertTrue(is_driver_account_for(user, self.driver))

    def test_driver_account_without_a_company_still_matches(self):
        user = self._user('r14_nocompany', '+254712100001', role='driver')
        self.assertTrue(is_driver_account_for(user, self.driver))

    def test_other_company_never_matches(self):
        user = self._user('r14_other', '+254712100001', role='driver', company=self.other)
        self.assertFalse(is_driver_account_for(user, self.driver))

    def test_a_passenger_with_the_same_number_never_matches(self):
        user = self._user('r14_pass', '+254712100001')
        self.assertFalse(is_driver_account_for(user, self.driver))

    def test_blank_phones_never_match(self):
        blank_driver = Driver.objects.create(
            company=self.co, name='Blank', phone_number='', bus_number='KAA 9')
        user = User.objects.create_user(
            username='r14_nophone', password=STRONG, role='driver', company=self.co)
        self.assertFalse(is_driver_account_for(user, blank_driver))
        self.assertEqual(list(drivers_for_user(user)), [])

    def test_anonymous_and_missing_never_match(self):
        self.assertFalse(is_driver_account_for(AnonymousUser(), self.driver))
        self.assertFalse(is_driver_account_for(None, self.driver))
        user = self._user('r14_x', '+254712100001', role='driver', company=self.co)
        self.assertFalse(is_driver_account_for(user, None))

    def test_legacy_format_driver_row_still_matches(self):
        Driver.objects.filter(pk=self.driver.pk).update(phone_number='0712100001')
        self.driver.refresh_from_db()
        user = self._user('r14_legacy', '+254712100001', role='driver', company=self.co)
        self.assertTrue(is_driver_account_for(user, self.driver))
        self.assertEqual(list(drivers_for_user(user)), [self.driver])

    def test_drivers_for_user_is_scoped_to_the_users_company(self):
        user = self._user('r14_scoped', '+254712100001', role='driver', company=self.other)
        self.assertEqual(list(drivers_for_user(user)), [])


class CashConfirmationIdentityTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('141')
        booking, self.payment = self.booking('confirmed', 'CASH-R14', payment_status='pending')
        Payment.objects.filter(pk=self.payment.pk).update(method='cash')
        self.url = reverse(
            f"bookings:{_url_name('confirm_cash_payment')}",
            kwargs={'booking_id': booking.id},
        )

    def _post(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(self.url, {}, format='json')

    def _user(self, username, phone, **extra):
        return User.objects.create_user(
            username=username, password=STRONG, phone_number=phone, **extra)

    def _still_unpaid(self):
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')

    def test_driver_with_a_legacy_format_driver_record_is_allowed(self):
        legacy = '0' + self.driver.phone_number[4:]
        Driver.objects.filter(pk=self.driver.pk).update(phone_number=legacy)
        user = self._user('r14_legacy_driver', self.driver.phone_number,
                          role='driver', company=self.company)
        self.assertNotEqual(self._post(user).status_code, 403)

    def test_passenger_cannot_borrow_a_legacy_format_driver_number(self):
        legacy = '0' + self.driver.phone_number[4:]
        Driver.objects.filter(pk=self.driver.pk).update(phone_number=legacy)
        passenger = self._user('r14_borrower', self.driver.phone_number)
        self.assertEqual(self._post(passenger).status_code, 403)
        self._still_unpaid()

    def test_blank_phone_driver_record_authorises_nobody(self):
        Driver.objects.filter(pk=self.driver.pk).update(phone_number='')
        user = User.objects.create_user(
            username='r14_nophone_driver', password=STRONG,
            role='driver', company=self.company)
        self.assertEqual(self._post(user).status_code, 403)
        self._still_unpaid()
