from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from bookings.models import Payment, UnappliedPayment
from bookings.tests.test_round5 import _Fixture
from bookings.tests.test_round11 import _ParcelFixture
from companies.models import Company

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


def _url_name(func_name):
    """Find the URL name of a bookings view by its function name."""
    from bookings import urls
    for pattern in urls.urlpatterns:
        callback = getattr(pattern, 'callback', None)
        view_cls = getattr(callback, 'cls', None)
        name = getattr(view_cls, '__name__', None) or getattr(callback, '__name__', '')
        if name == func_name:
            return pattern.name
    raise AssertionError(f'No URL pattern found for {func_name}')


class CashConfirmationRoleTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('1201')
        self.booking_obj, self.payment = self.booking(
            'confirmed', 'CASH-R12', payment_status='pending')
        Payment.objects.filter(pk=self.payment.pk).update(method='cash')
        self.url = reverse(
            f"bookings:{_url_name('confirm_cash_payment')}",
            kwargs={'booking_id': self.booking_obj.id},
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

    def test_passenger_with_the_drivers_phone_is_refused(self):
        impostor = self._user('r12_impostor', self.driver.phone_number)
        response = self._post(impostor)
        self.assertEqual(response.status_code, 403, getattr(response, 'data', None))
        self._still_unpaid()

    def test_driver_account_of_another_company_is_refused(self):
        other = Company.objects.create(name='R12 Other Co')
        stranger = self._user(
            'r12_stranger', self.driver.phone_number, role='driver', company=other)
        self.assertEqual(self._post(stranger).status_code, 403)
        self._still_unpaid()

    def test_manager_of_another_company_is_refused(self):
        other = Company.objects.create(name='R12 Other Co 2')
        manager = self._user(
            'r12_other_manager', '+254733001201', role='company_manager', company=other)
        self.assertEqual(self._post(manager).status_code, 403)
        self._still_unpaid()

    def test_assigned_driver_is_still_allowed(self):
        driver_user = self._user(
            'r12_driver', self.driver.phone_number, role='driver', company=self.company)
        response = self._post(driver_user)
        self.assertNotEqual(response.status_code, 403, getattr(response, 'data', None))

    def test_own_company_manager_is_still_allowed(self):
        manager = self._user(
            'r12_manager', '+254733001202', role='company_manager', company=self.company)
        response = self._post(manager)
        self.assertNotEqual(response.status_code, 403, getattr(response, 'data', None))


class ParcelAccessControlTests(_ParcelFixture, APITestCase):
    """Another user (or an anonymous one) must not read, cancel, pay for or drive a parcel."""

    BASE = '/api/deliveries/'

    def setUp(self):
        self.build('1202')
        self.pending_parcel = self.parcel(status='pending_payment')
        self.paid_parcel = self.parcel(status='paid')
        self.intruder = User.objects.create_user(
            username='r12_thief', password=STRONG, phone_number='+254744001202')
        self.client.force_authenticate(user=self.intruder)

    def _call(self, method, path):
        with patch('connect.paystack_extra.requests.post') as post, \
                patch('connect.paystack_extra.requests.get') as get:
            if method == 'get':
                response = self.client.get(f'{self.BASE}{path}')
            else:
                response = self.client.post(f'{self.BASE}{path}', {}, format='json')
        post.assert_not_called()
        get.assert_not_called()
        return response

    def _unchanged(self):
        self.pending_parcel.refresh_from_db()
        self.paid_parcel.refresh_from_db()
        self.assertEqual(self.pending_parcel.status, 'pending_payment')
        self.assertEqual(self.paid_parcel.status, 'paid')
        self.assertEqual(UnappliedPayment.objects.count(), 0)

    def test_cannot_read_someone_elses_parcel(self):
        response = self._call('get', f'{self.paid_parcel.id}/')
        self.assertGreaterEqual(response.status_code, 400)
        self._unchanged()

    def test_cannot_cancel_someone_elses_paid_parcel_or_trigger_a_refund(self):
        response = self._call('post', f'{self.paid_parcel.id}/cancel/')
        self.assertGreaterEqual(response.status_code, 400)
        self._unchanged()

    def test_cannot_start_payment_for_someone_elses_parcel(self):
        response = self._call('post', f'{self.pending_parcel.id}/pay/')
        self.assertGreaterEqual(response.status_code, 400)
        self._unchanged()

    def test_cannot_verify_someone_elses_parcel_payment(self):
        response = self._call('post', f'{self.pending_parcel.id}/verify/')
        if response.status_code == 405:
            response = self._call('get', f'{self.pending_parcel.id}/verify/')
        self.assertGreaterEqual(response.status_code, 400)
        self._unchanged()

    def test_passenger_cannot_pick_up_or_deliver(self):
        for action in ('pickup', 'deliver'):
            response = self._call('post', f'{self.paid_parcel.id}/{action}/')
            self.assertGreaterEqual(response.status_code, 400, action)
        self._unchanged()

    def test_anonymous_users_are_rejected(self):
        self.client.force_authenticate(user=None)
        for method, path in (
            ('get', f'{self.paid_parcel.id}/'),
            ('post', f'{self.paid_parcel.id}/cancel/'),
            ('post', f'{self.pending_parcel.id}/pay/'),
            ('post', f'{self.pending_parcel.id}/verify/'),
            ('post', f'{self.paid_parcel.id}/pickup/'),
            ('post', f'{self.paid_parcel.id}/deliver/'),
        ):
            response = self._call(method, path)
            self.assertIn(response.status_code, (401, 403, 405), path)
        self._unchanged()
