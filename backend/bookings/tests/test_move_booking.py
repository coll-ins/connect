import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


def _url(name, **kwargs):
    for prefix in ('bookings:', ''):
        try:
            return reverse(prefix + name, kwargs=kwargs)
        except NoReverseMatch:
            continue
    raise NoReverseMatch(name)


class MoveBase(TestCase):
    def setUp(self):
        cache.clear()
        self.company = Company.objects.create(name='Move SACCO')
        self.other_company = Company.objects.create(name='Other Move SACCO')
        self.operator = User.objects.create_user(
            username='op_move', password='password123',
            phone_number='+254700000911', company=self.company,
            role='company_operator', all_routes=True,
        )
        self.stranger_operator = User.objects.create_user(
            username='op_other_move', password='password123',
            phone_number='+254700000912', company=self.other_company,
            role='company_operator', all_routes=True,
        )
        self.manager = User.objects.create_user(
            username='mgr_move', password='password123',
            phone_number='+254700000913', company=self.company,
            role='company_manager',
        )
        self.passenger = User.objects.create_user(
            username='pax_move', password='password123',
            phone_number='+254700000914',
        )
        self.driver_a = Driver.objects.create(
            name='Driver A', phone_number='+254700000915',
            bus_number='KMA-001A', company=self.company,
        )
        self.driver_b = Driver.objects.create(
            name='Driver B', phone_number='+254700000916',
            bus_number='KMB-002B', company=self.company,
        )
        self.route = Route.objects.create(
            company=self.company, name='CBD to Move', start_point='CBD',
            end_point='Move', price=Decimal('100.00'),
        )
        self.other_route = Route.objects.create(
            company=self.company, name='CBD to Elsewhere', start_point='CBD',
            end_point='Elsewhere', price=Decimal('100.00'),
        )
        self.stage = PickupStage.objects.create(
            route=self.route, name='CBD', latitude=-1.2864,
            longitude=36.8172, order=0,
        )
        soon = timezone.now() + dt.timedelta(hours=1)
        self.trip_a = Trip.objects.create(
            route=self.route, driver=self.driver_a, departure_at=soon,
            capacity=10, status='boarding',
        )
        self.trip_b = Trip.objects.create(
            route=self.route, driver=self.driver_b, departure_at=soon,
            capacity=10, status='scheduled',
        )
        self.client = APIClient()

    def _booking(self, trip, seats=1, status='confirmed'):
        return Booking.objects.create(
            user=self.passenger, route=trip.route, driver=trip.driver,
            trip=trip, pickup_location='CBD', pickup_stage=self.stage,
            seats=seats, total_amount=Decimal('100.00') * seats,
            status=status,
        )

    def _move(self, booking, trip_id, user=None):
        self.client.force_authenticate(user=user or self.operator)
        return self.client.post(
            _url('move-booking-to-trip', booking_id=booking.id),
            {'trip_id': trip_id}, format='json',
        )


class MoveBookingTests(MoveBase):
    def test_operator_moves_booking_and_driver_follows(self):
        b = self._booking(self.trip_a)
        resp = self._move(b, self.trip_b.id)
        self.assertEqual(resp.status_code, 200, resp.data)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, self.trip_b.id)
        self.assertEqual(b.driver_id, self.driver_b.id)
        self.assertEqual(b.status, 'confirmed')

    def test_manager_can_move(self):
        b = self._booking(self.trip_a)
        self.assertEqual(
            self._move(b, self.trip_b.id, user=self.manager).status_code, 200
        )

    def test_can_move_onto_a_boarding_trip(self):
        self.trip_b.status = 'boarding'
        self.trip_b.save(update_fields=['status'])
        b = self._booking(self.trip_a)
        self.assertEqual(self._move(b, self.trip_b.id).status_code, 200)

    def test_other_company_operator_forbidden(self):
        b = self._booking(self.trip_a)
        resp = self._move(b, self.trip_b.id, user=self.stranger_operator)
        self.assertEqual(resp.status_code, 403)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, self.trip_a.id)

    def test_passenger_forbidden(self):
        b = self._booking(self.trip_a)
        self.assertEqual(
            self._move(b, self.trip_b.id, user=self.passenger).status_code, 403
        )

    def test_full_target_refused(self):
        self.trip_b.capacity = 1
        self.trip_b.save(update_fields=['capacity'])
        self._booking(self.trip_b, seats=1)
        b = self._booking(self.trip_a)
        resp = self._move(b, self.trip_b.id)
        self.assertEqual(resp.status_code, 409)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, self.trip_a.id)

    def test_cancelled_bookings_do_not_fill_the_target(self):
        self.trip_b.capacity = 1
        self.trip_b.save(update_fields=['capacity'])
        self._booking(self.trip_b, seats=1, status='cancelled')
        b = self._booking(self.trip_a)
        self.assertEqual(self._move(b, self.trip_b.id).status_code, 200)

    def test_different_route_refused(self):
        other = Trip.objects.create(
            route=self.other_route, driver=self.driver_b,
            departure_at=timezone.now() + dt.timedelta(hours=1),
            capacity=10, status='scheduled',
        )
        b = self._booking(self.trip_a)
        self.assertEqual(self._move(b, other.id).status_code, 400)

    def test_departed_or_completed_target_refused(self):
        b = self._booking(self.trip_a)
        for st in ('departed', 'completed', 'cancelled'):
            self.trip_b.status = st
            self.trip_b.save(update_fields=['status'])
            self.assertEqual(self._move(b, self.trip_b.id).status_code, 409, st)

    def test_finished_booking_cannot_move(self):
        for st in ('completed', 'cancelled', 'no_show'):
            b = self._booking(self.trip_a, status=st)
            self.assertEqual(self._move(b, self.trip_b.id).status_code, 409, st)

    def test_same_trip_and_missing_trip_id_are_rejected(self):
        b = self._booking(self.trip_a)
        self.assertEqual(self._move(b, self.trip_a.id).status_code, 400)
        self.client.force_authenticate(user=self.operator)
        resp = self.client.post(
            _url('move-booking-to-trip', booking_id=b.id), {}, format='json'
        )
        self.assertEqual(resp.status_code, 400)


class CashGateTests(MoveBase):
    def _confirm(self, user):
        b = self._booking(self.trip_a)
        self.client.force_authenticate(user=user)
        return self.client.post(
            _url('confirm-cash-payment', booking_id=b.id), {}, format='json'
        )

    def test_operator_cannot_confirm_cash_by_default(self):
        self.assertEqual(self._confirm(self.operator).status_code, 403)

    @override_settings(OPERATORS_CAN_CONFIRM_CASH=True)
    def test_operator_allowed_when_switch_is_on(self):
        self.assertNotEqual(self._confirm(self.operator).status_code, 403)

    def test_manager_is_not_blocked(self):
        self.assertNotEqual(self._confirm(self.manager).status_code, 403)
