from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from bookings.models import Booking, BoardingEvent
from bookings.tests.test_round5 import _Fixture
from companies.models import Company, Trip

User = get_user_model()
STRONG = 'Tr4velSafe-2026'


class VerifyBoardingIdentityTests(_Fixture, APITestCase):
    def setUp(self):
        self.build('1801')
        self.booking_obj, _ = self.booking(
            'confirmed', 'BRD-R18', payment_status='confirmed')
        Booking.objects.filter(pk=self.booking_obj.pk).update(verification_pin='1234')
        Trip.objects.filter(pk=self.trip.pk).update(status='boarding')
        self.url = reverse(
            'bookings:verify-boarding', kwargs={'booking_id': self.booking_obj.id})

    def _user(self, username, **extra):
        return User.objects.create_user(
            username=username, password=STRONG,
            phone_number=self.driver.phone_number, **extra)

    def _verify(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(self.url, {'boarding_pin': '1234'}, format='json')

    def _untouched(self):
        self.booking_obj.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'confirmed')
        self.assertFalse(BoardingEvent.objects.filter(booking=self.booking_obj).exists())

    def test_control_the_real_driver_account_can_verify(self):
        # Proves the setup is boardable, so the refusals below mean something.
        user = self._user('r18_driver', role='driver', company=self.company)
        response = self._verify(user)
        self.assertEqual(response.status_code, 200, response.data)
        self.booking_obj.refresh_from_db()
        self.assertEqual(self.booking_obj.status, 'completed')

    def test_passenger_with_the_drivers_number_is_refused(self):
        response = self._verify(self._user('r18_borrower'))
        self.assertEqual(response.status_code, 403, response.data)
        self._untouched()

    def test_driver_account_of_another_company_is_refused(self):
        other = Company.objects.create(name='R18 Other Co')
        user = self._user('r18_foreign_driver', role='driver', company=other)
        response = self._verify(user)
        self.assertEqual(response.status_code, 403, response.data)
        self._untouched()
