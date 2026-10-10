import datetime as dt
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
STAGE_LAT, STAGE_LNG = -1.286400, 36.817200
FAR_LNG = STAGE_LNG + 0.004   # roughly 440 m east
FAR_LNG_2 = STAGE_LNG + 0.006


def _company_url(name, **kwargs):
    for prefix in ('companies:', ''):
        try:
            return reverse(prefix + name, kwargs=kwargs)
        except NoReverseMatch:
            continue
    raise NoReverseMatch(name)


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.company = Company.objects.create(name='Test SACCO r25')
        self.manager = User.objects.create_user(
            username='mgr_r25', password='password123',
            phone_number='+254700000901', company=self.company,
            role='company_manager',
        )
        self.passenger = User.objects.create_user(
            username='pax_r25', password='password123',
            phone_number='+254700000902',
        )
        self.driver = Driver.objects.create(
            name='Driver R25', phone_number='+254700000903',
            bus_number='KDB-025A', company=self.company,
        )
        self.route = Route.objects.create(
            company=self.company, name='CBD to Test', start_point='CBD',
            end_point='Test', price=Decimal('100.00'),
        )
        self.stage1 = PickupStage.objects.create(
            route=self.route, name='CBD', latitude=STAGE_LAT,
            longitude=STAGE_LNG, order=0,
        )
        self.stage2 = PickupStage.objects.create(
            route=self.route, name='Mid', latitude=-1.27,
            longitude=36.80, order=1,
        )
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() + dt.timedelta(hours=1),
            capacity=10, status='scheduled',
        )
        self.client = APIClient()

    def _booking(self, seats, status='confirmed', user=None):
        return Booking.objects.create(
            user=user or self.passenger, route=self.route,
            driver=self.driver, trip=self.trip, pickup_location='CBD',
            pickup_stage=self.stage1, seats=seats,
            total_amount=Decimal('100.00') * seats, status=status,
        )


class TripCapacityEditTests(Base):
    def _patch(self, value, user=None):
        self.client.force_authenticate(user=user or self.manager)
        url = _company_url('update_trip_capacity', trip_id=self.trip.id)
        return self.client.patch(url, {'capacity': value}, format='json')

    def test_manager_can_raise_capacity(self):
        self.assertEqual(self._patch(14).status_code, 200)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.capacity, 14)

    def test_cannot_drop_below_taken_seats(self):
        self._booking(4)
        self.assertEqual(self._patch(3).status_code, 409)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.capacity, 10)
        self.assertEqual(self._patch(4).status_code, 200)

    def test_cancelled_bookings_do_not_block(self):
        self._booking(8, status='cancelled')
        self._booking(2)
        self.assertEqual(self._patch(2).status_code, 200)

    def test_other_company_manager_forbidden(self):
        other = Company.objects.create(name='Other SACCO r25')
        stranger = User.objects.create_user(
            username='mgr_other_r25', password='password123',
            phone_number='+254700000904', company=other,
            role='company_manager',
        )
        self.assertEqual(self._patch(12, user=stranger).status_code, 403)

    def test_rejects_finished_trip_and_bad_values(self):
        for bad in (0, -1, 101, 'abc', 2.5, None):
            self.assertEqual(self._patch(bad).status_code, 400, bad)
        self.trip.status = 'completed'
        self.trip.save(update_fields=['status'])
        self.assertEqual(self._patch(12).status_code, 409)


class BoardingStageBookingTests(Base):
    def _book(self, stage=None, **extra):
        self.client.force_authenticate(user=self.passenger)
        body = {'trip_id': self.trip.id, 'seats': 1}
        if stage is not None:
            body['pickup_stage_id'] = stage.id
        body.update(extra)
        return self.client.post(
            reverse('bookings:create-booking'), body, format='json'
        )

    def test_boarding_trip_accepts_first_stage_only(self):
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - dt.timedelta(minutes=10)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.assertEqual(self._book(self.stage1).status_code, 201)
        self.assertEqual(self._book(self.stage2).status_code, 400)
        self.assertEqual(
            self._book(pickup_location='Somewhere').status_code, 400
        )

    def test_scheduled_trip_still_accepts_any_stage(self):
        self.assertEqual(self._book(self.stage2).status_code, 201)

    def test_departed_trip_rejected(self):
        self.trip.status = 'departed'
        self.trip.save(update_fields=['status'])
        self.assertEqual(self._book(self.stage1).status_code, 400)

    def test_boarding_trip_cannot_oversell(self):
        self.trip.status = 'boarding'
        self.trip.capacity = 1
        self.trip.save(update_fields=['status', 'capacity'])
        self.assertEqual(self._book(self.stage1).status_code, 201)
        self.assertEqual(self._book(self.stage1).status_code, 400)


class GpsAutoDepartTests(Base):
    def setUp(self):
        super().setUp()
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - dt.timedelta(minutes=2)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.booking = self._booking(1)
        self.client.force_authenticate(user=self.manager)

    def _set_prev(self, lng):
        Driver.objects.filter(pk=self.driver.pk).update(
            latitude=STAGE_LAT, longitude=lng
        )

    def _post(self, lng):
        url = reverse('drivers:driver-location',
                      kwargs={'driver_id': self.driver.id})
        resp = self.client.post(
            url, {'latitude': STAGE_LAT, 'longitude': lng}, format='json'
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_two_fixes_away_departs_and_notifies_once(self):
        self._set_prev(FAR_LNG)
        with mock.patch('notifications.sms.send_departure_sms') as sms, \
                self.captureOnCommitCallbacks(execute=True):
            self._post(FAR_LNG_2)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'departed')
        sms.assert_called_once_with(
            '+254700000902', self.booking.booking_number, self.route.name
        )
        with mock.patch('notifications.sms.send_departure_sms') as sms2, \
                self.captureOnCommitCallbacks(execute=True):
            self._post(FAR_LNG_2 + 0.001)
        sms2.assert_not_called()

    def test_at_stage_stays_boarding(self):
        self._set_prev(STAGE_LNG)
        with mock.patch('notifications.sms.send_departure_sms') as sms, \
                self.captureOnCommitCallbacks(execute=True):
            self._post(STAGE_LNG + 0.0003)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')
        sms.assert_not_called()

    def test_single_gps_spike_does_not_depart(self):
        self._set_prev(STAGE_LNG)
        with mock.patch('notifications.sms.send_departure_sms') as sms, \
                self.captureOnCommitCallbacks(execute=True):
            self._post(FAR_LNG)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')
        sms.assert_not_called()

    def test_far_future_departure_does_not_trigger(self):
        self.trip.departure_at = timezone.now() + dt.timedelta(hours=3)
        self.trip.save(update_fields=['departure_at'])
        self._set_prev(FAR_LNG)
        with mock.patch('notifications.sms.send_departure_sms') as sms, \
                self.captureOnCommitCallbacks(execute=True):
            self._post(FAR_LNG_2)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'boarding')
        sms.assert_not_called()


class BoardingTripVisibilityTests(Base):
    def _visible_ids(self):
        resp = APIClient().get(_company_url('get_trips'))
        self.assertEqual(resp.status_code, 200)
        return {t.get('id') for t in resp.data}

    def test_recent_boarding_trip_is_listed_for_passengers(self):
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - dt.timedelta(minutes=10)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.assertIn(self.trip.id, self._visible_ids())

    def test_stale_boarding_and_departed_trips_stay_hidden(self):
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - dt.timedelta(hours=5)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.assertNotIn(self.trip.id, self._visible_ids())
        self.trip.status = 'departed'
        self.trip.departure_at = timezone.now() - dt.timedelta(minutes=5)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.assertNotIn(self.trip.id, self._visible_ids())

    def test_stale_boarding_trip_cannot_be_booked(self):
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - dt.timedelta(hours=5)
        self.trip.save(update_fields=['status', 'departure_at'])
        self.client.force_authenticate(user=self.passenger)
        resp = self.client.post(
            reverse('bookings:create-booking'),
            {'trip_id': self.trip.id, 'seats': 1,
             'pickup_stage_id': self.stage1.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class BoardingPaymentTests(Base):
    def _set_trip(self, status, minutes_ago):
        Trip.objects.filter(pk=self.trip.pk).update(
            status=status,
            departure_at=timezone.now() - dt.timedelta(minutes=minutes_ago),
        )

    def _init_cash(self, booking):
        self.client.force_authenticate(user=self.passenger)
        return self.client.post(
            reverse('bookings:initialize-cash-payment',
                    kwargs={'booking_id': booking.id}),
            {}, format='json',
        )

    def test_recent_boarding_trip_accepts_cash_init(self):
        b = self._booking(1, status='pending')
        self._set_trip('boarding', 10)
        self.assertEqual(self._init_cash(b).status_code, 200)

    def test_manager_can_confirm_cash_on_boarding_trip(self):
        b = self._booking(1, status='pending')
        self._set_trip('boarding', 10)
        self.assertEqual(self._init_cash(b).status_code, 200)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(
            reverse('bookings:confirm-cash-payment',
                    kwargs={'booking_id': b.id}),
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_stale_boarding_trip_rejects_payment(self):
        b = self._booking(1, status='pending')
        self._set_trip('boarding', 300)
        self.assertEqual(self._init_cash(b).status_code, 400)

    def test_scheduled_trip_past_departure_rejects_payment(self):
        b = self._booking(1, status='pending')
        self._set_trip('scheduled', 5)
        self.assertEqual(self._init_cash(b).status_code, 400)

    def test_departed_trip_rejects_payment(self):
        b = self._booking(1, status='pending')
        self._set_trip('departed', 5)
        self.assertEqual(self._init_cash(b).status_code, 400)


from bookings.models import BoardingEvent, Payment
from users.phone import canonical_phone


class WalkInBookingTests(Base):
    def setUp(self):
        super().setUp()
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding',
            departure_at=timezone.now() - dt.timedelta(minutes=5),
        )
        self.operator = User.objects.create_user(
            username='op_r26', password='password123',
            phone_number='+254700000905', company=self.company,
            role='company_operator',
        )
        self.client.force_authenticate(user=self.operator)

    def _walk(self, phone='0733000111', seats=1, user=None):
        if user is not None:
            self.client.force_authenticate(user=user)
        return self.client.post(
            reverse('bookings:walk-in-booking',
                    kwargs={'trip_id': self.trip.id}),
            {'phone_number': phone, 'seats': seats}, format='json',
        )

    def test_walk_in_boards_and_leaves_full_audit_trail(self):
        with mock.patch('notifications.sms.send_booking_sms') as sms, \
                self.captureOnCommitCallbacks(execute=True):
            resp = self._walk(seats=2)
        self.assertEqual(resp.status_code, 201, resp.content)
        b = Booking.objects.get(booking_number=resp.data['booking_number'])
        self.assertEqual(b.status, 'completed')
        self.assertEqual(b.seats, 2)
        self.assertEqual(b.total_amount, Decimal('200.00'))
        self.assertEqual(b.pickup_stage_id, self.stage1.id)
        self.assertEqual(b.trip_id, self.trip.id)
        p = b.payment
        self.assertEqual(
            (p.method, p.status, p.settlement_status),
            ('cash', 'confirmed', 'eligible'),
        )
        ev = BoardingEvent.objects.get(booking=b)
        self.assertEqual(ev.method, 'walkin')
        self.assertEqual(ev.verified_by_id, self.operator.id)
        pax = b.user
        self.assertEqual(pax.phone_number, canonical_phone('0733000111'))
        self.assertEqual(pax.role, 'passenger')
        self.assertFalse(pax.has_usable_password())
        self.assertEqual(pax.boarded_count, 1)
        sms.assert_called_once_with(pax.phone_number, b.booking_number)

    def test_existing_passenger_is_reused(self):
        before = User.objects.count()
        resp = self._walk(phone='+254700000902')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(
            Booking.objects.get(
                booking_number=resp.data['booking_number']).user_id,
            self.passenger.id,
        )

    def test_staff_phone_is_rejected(self):
        self.assertEqual(self._walk(phone='+254700000901').status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_cannot_oversell(self):
        Trip.objects.filter(pk=self.trip.pk).update(capacity=2)
        self.assertEqual(self._walk(seats=2).status_code, 201)
        self.assertEqual(
            self._walk(phone='0733000222', seats=1).status_code, 400)
        self.assertEqual(Booking.objects.count(), 1)

    def test_only_boarding_trips(self):
        for st in ('scheduled', 'departed', 'completed', 'cancelled'):
            Trip.objects.filter(pk=self.trip.pk).update(status=st)
            self.assertEqual(self._walk().status_code, 409, st)
        self.assertFalse(Booking.objects.exists())

    def test_stale_boarding_trip_rejected(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() - dt.timedelta(minutes=300))
        self.assertEqual(self._walk().status_code, 409)

    def test_bad_input_rejected(self):
        for seats in (0, -1, 'abc', 25, True):
            self.assertEqual(self._walk(seats=seats).status_code, 400, seats)
        self.assertEqual(self._walk(phone='').status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_passenger_and_foreign_manager_forbidden(self):
        self.assertEqual(
            self._walk(user=self.passenger).status_code, 403)
        other = Company.objects.create(name='Other SACCO r26')
        stranger = User.objects.create_user(
            username='mgr_other_r26', password='password123',
            phone_number='+254700000906', company=other,
            role='company_manager',
        )
        self.assertEqual(self._walk(user=stranger).status_code, 403)
        self.assertFalse(Booking.objects.exists())

    def test_manager_and_own_driver_allowed(self):
        self.assertEqual(self._walk(user=self.manager).status_code, 201)
        drv = User.objects.create_user(
            username='drv_r26', password='password123',
            phone_number='+254700000903', company=self.company,
            role='driver',
        )
        self.assertEqual(
            self._walk(phone='0733000333', user=drv).status_code, 201)


class OperatorRouteScopeTests(Base):
    def setUp(self):
        super().setUp()
        self.route2 = Route.objects.create(
            company=self.company, name='CBD to Other', start_point='CBD',
            end_point='Other', price=Decimal('80.00'),
        )
        self.r2stage = PickupStage.objects.create(
            route=self.route2, name='CBD2', latitude=STAGE_LAT,
            longitude=STAGE_LNG, order=0,
        )
        self.driver2 = Driver.objects.create(
            name='Driver2', phone_number='+254700000907',
            bus_number='KDB-026B', company=self.company,
        )
        self.trip2 = Trip.objects.create(
            route=self.route2, driver=self.driver2,
            departure_at=timezone.now() + dt.timedelta(hours=2),
            capacity=10, status='scheduled',
        )
        self.operator = User.objects.create_user(
            username='op_r27', password='password123',
            phone_number='+254700000908', company=self.company,
            role='company_operator',
        )

    def _assign(self, all_routes, route_ids=(), user=None):
        self.client.force_authenticate(user=user or self.manager)
        return self.client.patch(
            _company_url('set_operator_routes', user_id=self.operator.id),
            {'all_routes': all_routes, 'route_ids': list(route_ids)},
            format='json',
        )

    def _as_operator(self):
        # Reload: the view must see the DB state, as in a real request.
        self.operator = User.objects.get(pk=self.operator.pk)
        self.client.force_authenticate(user=self.operator)

    def test_default_operator_handles_every_route(self):
        self._as_operator()
        resp = self.client.get(_company_url('get_trips'))
        ids = {t['id'] for t in resp.data}
        self.assertEqual(ids, {self.trip.id, self.trip2.id})

    def test_restricted_operator_only_sees_assigned_routes(self):
        self.assertEqual(self._assign(False, [self.route.id]).status_code, 200)
        self._as_operator()
        ids = {t['id'] for t in self.client.get(_company_url('get_trips')).data}
        self.assertEqual(ids, {self.trip.id})

    def test_restricted_operator_with_no_routes_sees_nothing(self):
        self.assertEqual(self._assign(False, []).status_code, 200)
        self._as_operator()
        self.assertEqual(self.client.get(_company_url('get_trips')).data, [])

    def test_status_and_capacity_blocked_on_other_routes(self):
        self._assign(False, [self.route.id])
        self._as_operator()
        s2 = _company_url('update_trip_status', trip_id=self.trip2.id)
        c2 = _company_url('update_trip_capacity', trip_id=self.trip2.id)
        self.assertEqual(
            self.client.post(s2, {'status': 'boarding'}, format='json').status_code, 403)
        self.assertEqual(
            self.client.patch(c2, {'capacity': 12}, format='json').status_code, 403)
        s1 = _company_url('update_trip_status', trip_id=self.trip.id)
        self.assertEqual(
            self.client.post(s1, {'status': 'boarding'}, format='json').status_code, 200)
        self.trip2.refresh_from_db()
        self.assertEqual((self.trip2.status, self.trip2.capacity), ('scheduled', 10))

    def test_walk_in_blocked_on_other_routes(self):
        for t in (self.trip, self.trip2):
            Trip.objects.filter(pk=t.pk).update(
                status='boarding',
                departure_at=timezone.now() - dt.timedelta(minutes=5))
        self._assign(False, [self.route.id])
        self._as_operator()
        def walk(trip):
            return self.client.post(
                reverse('bookings:walk-in-booking', kwargs={'trip_id': trip.id}),
                {'phone_number': '0733000444', 'seats': 1}, format='json')
        self.assertEqual(walk(self.trip2).status_code, 403)
        self.assertEqual(walk(self.trip).status_code, 201)

    def test_cash_confirm_and_boarding_blocked_on_other_routes(self):
        b = Booking.objects.create(
            user=self.passenger, route=self.route2, driver=self.driver2,
            trip=self.trip2, pickup_location='CBD2', pickup_stage=self.r2stage,
            seats=1, total_amount=Decimal('80.00'), status='pending')
        Payment.objects.create(
            booking=b, amount=Decimal('80.00'), method='cash',
            status='pending', settlement_status='not_ready',
            refund_status='not_requested')
        cash = reverse('bookings:confirm-cash-payment', kwargs={'booking_id': b.id})
        self._assign(False, [self.route.id])
        self._as_operator()
        self.assertEqual(self.client.post(cash, {}, format='json').status_code, 403)
        self._assign(True)
        self._as_operator()
        self.assertEqual(self.client.post(cash, {}, format='json').status_code, 200)

        Trip.objects.filter(pk=self.trip2.pk).update(
            status='boarding',
            departure_at=timezone.now() - dt.timedelta(minutes=5))
        b.refresh_from_db()
        board = reverse('bookings:verify-boarding', kwargs={'booking_id': b.id})
        body = {'boarding_pin': b.verification_pin}
        self._assign(False, [self.route.id])
        self._as_operator()
        self.assertEqual(self.client.post(board, body, format='json').status_code, 403)
        self._assign(False, [self.route.id, self.route2.id])
        self._as_operator()
        self.assertEqual(self.client.post(board, body, format='json').status_code, 200)

    def test_manager_api_rules(self):
        self.client.force_authenticate(user=self.manager)
        listing = self.client.get(_company_url('operator_route_assignments'))
        self.assertEqual(listing.status_code, 200)
        row = [o for o in listing.data['operators'] if o['id'] == self.operator.id][0]
        self.assertTrue(row['all_routes'])
        self.assertEqual(
            {r['id'] for r in listing.data['routes']},
            {self.route.id, self.route2.id})

        other = Company.objects.create(name='Other SACCO r27')
        foreign_route = Route.objects.create(
            company=other, name='X', start_point='A', end_point='B',
            price=Decimal('50.00'))
        self.assertEqual(self._assign(False, [foreign_route.id]).status_code, 400)
        self.assertEqual(
            self.client.patch(
                _company_url('set_operator_routes', user_id=self.operator.id),
                {'all_routes': 'yes', 'route_ids': []}, format='json').status_code, 400)
        self.assertEqual(
            self.client.patch(
                _company_url('set_operator_routes', user_id=self.passenger.id),
                {'all_routes': True}, format='json').status_code, 404)

        stranger = User.objects.create_user(
            username='mgr_other_r27', password='password123',
            phone_number='+254700000909', company=other,
            role='company_manager')
        self.assertEqual(self._assign(False, [self.route.id], user=stranger).status_code, 403)
        self.assertEqual(self._assign(False, [self.route.id], user=self.operator).status_code, 403)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.all_routes)


class OperatorBookingAlertTests(Base):
    def setUp(self):
        super().setUp()
        self.route2 = Route.objects.create(
            company=self.company, name='CBD to Other', start_point='CBD',
            end_point='Other', price=Decimal('80.00'),
        )
        self.r2stage = PickupStage.objects.create(
            route=self.route2, name='CBD2', latitude=STAGE_LAT,
            longitude=STAGE_LNG, order=0,
        )
        self.driver2 = Driver.objects.create(
            name='Driver2', phone_number='+254700000917',
            bus_number='KDB-027C', company=self.company,
        )
        self.trip2 = Trip.objects.create(
            route=self.route2, driver=self.driver2,
            departure_at=timezone.now() + dt.timedelta(hours=2),
            capacity=10, status='scheduled',
        )
        self.operator = User.objects.create_user(
            username='op_r28', password='password123',
            phone_number='+254700000918', company=self.company,
            role='company_operator',
        )
        self.b1 = self._booking(1, status='pending')
        self.b2 = Booking.objects.create(
            user=self.passenger, route=self.route2, driver=self.driver2,
            trip=self.trip2, pickup_location='CBD2',
            pickup_stage=self.r2stage, seats=1,
            total_amount=Decimal('80.00'), status='pending')
        for b in (self.b1, self.b2):
            Payment.objects.create(
                booking=b, amount=b.total_amount, method='cash',
                status='pending', settlement_status='not_ready',
                refund_status='not_requested')

    def _restrict(self, route_ids):
        op = self.operator
        op.all_routes = False
        op.save(update_fields=['all_routes'])
        op.assigned_routes.set(route_ids)

    def _login_op(self):
        # Reload: force_authenticate must see DB state, as in a real request.
        self.client.force_authenticate(user=User.objects.get(pk=self.operator.pk))

    def _numbers(self, resp):
        return {i['booking_number'] for i in resp.data['items']}

    def test_alerts_manager_and_default_operator_see_all(self):
        want = {self.b1.booking_number, self.b2.booking_number}
        url = reverse('bookings:staff-alerts')
        self.client.force_authenticate(user=self.manager)
        self.assertEqual(self._numbers(self.client.get(url)), want)
        self._login_op()
        self.assertEqual(self._numbers(self.client.get(url)), want)

    def test_alerts_restricted_operator_only_own_routes(self):
        url = reverse('bookings:staff-alerts')
        self._restrict([self.route.id])
        self._login_op()
        resp = self.client.get(url)
        self.assertEqual(self._numbers(resp), {self.b1.booking_number})
        self.assertEqual(resp.data['count'], 1)
        self._restrict([])
        self._login_op()
        self.assertEqual(self.client.get(url).data['count'], 0)

    def test_alerts_skip_departed_trips_and_reject_non_staff(self):
        url = reverse('bookings:staff-alerts')
        Trip.objects.filter(pk=self.trip.pk).update(status='departed')
        self.client.force_authenticate(user=self.manager)
        self.assertEqual(self._numbers(self.client.get(url)), {self.b2.booking_number})
        self.client.force_authenticate(user=self.passenger)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_bookings_all_is_route_scoped(self):
        url = reverse('bookings:get-all-bookings')

        def numbers():
            body = self.client.get(url).data
            rows = body if isinstance(body, list) else body.get('results', body)
            return {r['booking_number'] for r in rows}

        self._login_op()
        self.assertEqual(
            numbers(), {self.b1.booking_number, self.b2.booking_number})
        self._restrict([self.route.id])
        self._login_op()
        self.assertEqual(numbers(), {self.b1.booking_number})

    def test_assign_driver_and_stage_departure_blocked_on_other_routes(self):
        self._restrict([self.route.id])
        self._login_op()
        a2 = reverse('bookings:assign-driver', kwargs={'booking_id': self.b2.id})
        s2 = reverse('bookings:set-stage-departure', kwargs={'booking_id': self.b2.id})
        a1 = reverse('bookings:assign-driver', kwargs={'booking_id': self.b1.id})
        s1 = reverse('bookings:set-stage-departure', kwargs={'booking_id': self.b1.id})
        self.assertEqual(
            self.client.post(a2, {'driver_id': self.driver2.id}, format='json').status_code,
            403)
        self.assertEqual(
            self.client.post(s2, {'minutes': 15}, format='json').status_code,
            403)
        self.assertNotEqual(
            self.client.post(a1, {'driver_id': self.driver.id}, format='json').status_code,
            403)
        self.assertNotEqual(
            self.client.post(s1, {'minutes': 15}, format='json').status_code,
            403)


class TripBookedSeatsTests(Base):
    def test_trip_list_reports_booked_seats(self):
        self._booking(2)
        self._booking(3, status='cancelled')
        self._booking(1, status='pending')
        self.client.force_authenticate(user=self.manager)
        resp = self.client.get(_company_url('get_trips'))
        row = [t for t in resp.data if t['id'] == self.trip.id][0]
        self.assertEqual(row['booked_seats'], 3)
