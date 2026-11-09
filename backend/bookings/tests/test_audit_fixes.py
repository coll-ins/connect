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


class PassengerCannotClaimCompanyFaultTests(AuditFixTests):
    """A passenger cannot cancel their own booking as company fault (100%)."""

    def test_passenger_sending_company_fault_is_refused(self):
        from bookings.models import Payment
        Payment.objects.create(booking=self.booking, amount=Decimal('100'), method='cash',
                               status='confirmed')
        self.client.force_authenticate(self.pax)
        r = self.client.post(self._url() + 'cancel/', {'fault_party': 'company'}, format='json')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertIsNone(Payment.objects.get(booking=self.booking).refund_amount)


class IncidentRefundRejectedSeatTests(APITestCase):
    """Rejected incident refund must not oversell or double-book a seat."""

    def setUp(self):
        from bookings.models import Incident
        from bookings.seats import assign_seats
        company = Company.objects.create(name='A', areas_served='x')
        self.route = Route.objects.create(
            company=company, name='R', start_point='a', end_point='b',
            price=Decimal('100'))
        driver = Driver.objects.create(
            name='D', phone_number='+254700000015', bus_number='KAA2',
            company=company)
        self.trip = Trip.objects.create(
            route=self.route, driver=driver, capacity=1, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        self.pax = User.objects.create_user(
            username='p2', password='pw-123456', phone_number='+254700000014')
        self.booking = Booking.objects.create(
            user=self.pax, trip=self.trip, route=self.route, driver=driver,
            seats=1, total_amount=Decimal('100'), status='confirmed',
            pickup_location='x')
        assign_seats(self.trip, self.booking, [1])
        Incident.objects.create(
            trip=self.trip, reported_by=self.pax, incident_type='breakdown',
            description='Broke down.', status='reported')

    def _resolve(self, during_paystack):
        claim = SimpleNamespace(provider_reference='REF', booking_number='BK2')

        def reject(_claim):
            during_paystack()
            raise RefundRejected('Paystack refused the refund.')

        self.client.force_authenticate(self.pax)
        with mock.patch('bookings.services.claim_booking_refund',
                        return_value=(Decimal('100'), claim)), \
             mock.patch('bookings.services.execute_booking_refund',
                        side_effect=reject), \
             mock.patch('bookings.services.release_refund_claim'), \
             mock.patch('bookings.views._alert_payment_problem') as alert:
            r = self.client.post(
                f'/api/bookings/{self.booking.id}/resolve-incident/',
                {'resolution': 'refund'}, format='json')
        return r, alert

    def test_resold_seat_is_not_restored(self):
        from bookings.models import SeatAssignment
        from bookings.seats import assign_seats
        other = User.objects.create_user(
            username='q2', password='pw-123456', phone_number='+254700000016')

        def resell_seat_1():
            b = Booking.objects.create(
                user=other, trip=self.trip, route=self.route,
                driver=self.trip.driver, seats=1, total_amount=Decimal('100'),
                status='confirmed', pickup_location='x')
            assign_seats(self.trip, b, [1])

        r, alert = self._resolve(resell_seat_1)

        self.assertEqual(r.status_code, 409)
        live = self.trip.bookings.exclude(status='cancelled')
        self.assertLessEqual(sum(b.seats for b in live), self.trip.capacity)
        holders = SeatAssignment.objects.filter(
            trip=self.trip, seat_no=1, booking__in=live)
        self.assertEqual(holders.count(), 1)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'cancelled')
        alert.assert_called_once()

    def test_free_seat_is_restored_with_its_number(self):
        r, _ = self._resolve(lambda: None)
        self.assertEqual(r.status_code, 409)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, 'confirmed')
        self.assertEqual(
            list(self.booking.seat_assignments.values_list('seat_no', flat=True)), [1])
