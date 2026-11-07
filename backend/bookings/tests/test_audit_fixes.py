import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking
from bookings.services import RefundRejected
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class AuditFixTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name='A', areas_served='x')
        self.route = Route.objects.create(
            company=self.company, name='R', start_point='a', end_point='b',
            price=Decimal('100'))
        driver = Driver.objects.create(
            name='D', phone_number='+254700000005', bus_number='KAA1',
            company=self.company)
        self.trip = Trip.objects.create(
            route=self.route, driver=driver, capacity=1, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        self.pax = User.objects.create_user(
            username='p', password='pw-123456', phone_number='+254700000004')
        self.booking = Booking.objects.create(
            user=self.pax, trip=self.trip, route=self.route, driver=driver,
            seats=1, total_amount=Decimal('100'), status='confirmed',
            pickup_location='x')

    def _url(self):
        return f'/api/bookings/{self.booking.id}/'

    def test_route_restricted_operator_cannot_cancel_or_view_other_routes(self):
        op = User.objects.create_user(
            username='o', password='pw-123456', phone_number='+254700000003',
            company=self.company, role='company_operator', all_routes=False)
        self.client.force_authenticate(op)
        r = self.client.post(self._url() + 'cancel/', {'fault_party': 'company'},
                             format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_rejected_refund_does_not_restore_a_resold_seat(self):
        other = User.objects.create_user(
            username='q', password='pw-123456', phone_number='+254700000006')

        def resell_then_reject(claim):
            # Another passenger takes the freed seat while Paystack is called.
            Booking.objects.create(
                user=other, trip=self.trip, route=self.route,
                driver=self.trip.driver, seats=1, total_amount=Decimal('100'),
                status='confirmed', pickup_location='x')
            raise RefundRejected('Paystack refused the refund.')

        claim = SimpleNamespace(provider_reference='REF', booking_number='BK1')
        self.client.force_authenticate(self.pax)
        with mock.patch('bookings.services.claim_booking_refund',
                        return_value=(Decimal('50'), claim)), \
             mock.patch('bookings.services.execute_booking_refund',
                        side_effect=resell_then_reject), \
             mock.patch('bookings.services.release_refund_claim'), \
             mock.patch('bookings.views._alert_payment_problem') as alert:
            r = self.client.post(self._url() + 'cancel/', {}, format='json')

        self.assertEqual(r.status_code, 409)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
        alert.assert_called_once()
        taken = sum(b.seats for b in self.trip.bookings.exclude(status='cancelled'))
        self.assertLessEqual(taken, self.trip.capacity)

    def test_rejected_refund_restores_booking_when_seat_still_free(self):
        claim = SimpleNamespace(provider_reference='REF', booking_number='BK1')
        self.client.force_authenticate(self.pax)
        with mock.patch('bookings.services.claim_booking_refund',
                        return_value=(Decimal('50'), claim)), \
             mock.patch('bookings.services.execute_booking_refund',
                        side_effect=RefundRejected('no')), \
             mock.patch('bookings.services.release_refund_claim'):
            r = self.client.post(self._url() + 'cancel/', {}, format='json')
        self.assertEqual(r.status_code, 409)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')

    def test_all_bookings_rejects_non_numeric_company_id(self):
        admin = User.objects.create_superuser(
            username='a', password='pw-123456', phone_number='+254700000007',
            email='a@example.com')
        self.client.force_authenticate(admin)
        r = self.client.get('/api/bookings/all/?company_id=abc')
        self.assertEqual(r.status_code, 400)
        r = self.client.get(f'/api/bookings/all/?company_id={self.company.id}')
        self.assertEqual(r.status_code, 200)

    def test_currency_check_normalises_and_tolerates_missing_field(self):
        from bookings.views import _currency_ok
        self.assertTrue(_currency_ok('KES'))
        self.assertTrue(_currency_ok(' kes '))
        self.assertTrue(_currency_ok(None))
        self.assertFalse(_currency_ok('USD'))
        self.assertFalse(_currency_ok('NGN'))
