"""Seat holds, lazy expiry, one seat count, one confirm path, cut-off (BE-1a)."""
import datetime as dt
import hashlib
import hmac
import json
import pathlib
import re
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings import services
from bookings.models import Booking, BookingHold, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
MIN = dt.timedelta(minutes=1)
BACKEND = pathlib.Path(__file__).resolve().parents[2]


class SeatBase(TestCase):
    capacity = 4

    def setUp(self):
        # Cash on board is gated to proven riders upstream; these tests are
        # about seats and money, so the gate is open.
        patcher = mock.patch('users.models.CustomUser.can_pay_cash', new=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.company = Company.objects.create(name='Hold Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=self.company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        self.driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=self.company)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=self.capacity,
            status='scheduled', departure_at=timezone.now() + dt.timedelta(hours=3))
        self.n = 0
        self.passenger = self.user()
        self.staff = User.objects.create_user(
            username='root', password='pw-123456', phone_number='+254711888888',
            is_superuser=True, is_staff=True)
        self.client = APIClient()

    def user(self):
        self.n += 1
        return User.objects.create_user(
            username=f'pax{self.n}', password='pw-123456',
            phone_number=f'+2547119{self.n:05d}')

    def booking(self, seats=1, status='pending', held_until=None, user=None,
                trip=None):
        trip = trip or self.trip
        return Booking.objects.create(
            user=user or self.user(), trip=trip, route=trip.route,
            driver=trip.driver, seats=seats, total_amount=Decimal('100') * seats,
            status=status, held_until=held_until, pickup_location='Kencom',
            pickup_stage=self.stage)

    def digital_payment(self, booking, status='pending', ref=None):
        return Payment.objects.create(
            booking=booking, amount=booking.total_amount, method='digital',
            status=status, provider_reference=ref or f'CONNECT-{booking.id}-abc',
            idempotency_key=ref or f'CONNECT-{booking.id}-abc')

    def webhook(self, payment, amount=None, currency='KES'):
        amount = int(payment.amount * 100) if amount is None else amount
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': payment.provider_reference, 'amount': amount,
            'currency': currency}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return self.client.post(
            '/api/bookings/webhooks/paystack/', data=body,
            content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)

    def create_via_api(self, user=None, seats=1, trip=None):
        self.client.force_authenticate(user or self.passenger)
        return self.client.post('/api/bookings/create/', {
            'trip_id': (trip or self.trip).id, 'seats': seats,
            'pickup_stage_id': self.stage.id}, format='json')


class SeatsTakenTests(SeatBase):
    def test_seats_taken_lazy_expiry(self):
        now = timezone.now()
        self.booking(3, 'confirmed')
        self.booking(2, 'pending', now + 5 * MIN)
        self.booking(4, 'pending', now - 1 * MIN)
        self.booking(1, 'pending', None)  # legacy/unstamped row stays counted
        self.booking(5, 'cancelled')
        self.assertEqual(services.seats_taken(self.trip, now), 6)
        self.assertEqual(services.seats_taken(self.trip, now + 10 * MIN), 4)

    def test_completed_and_no_show_count(self):
        self.booking(1, 'completed')
        self.booking(2, 'no_show')
        self.assertEqual(services.seats_taken(self.trip), 3)

    def test_exclude_booking(self):
        mine = self.booking(2, 'pending', timezone.now() - MIN)
        self.booking(1, 'confirmed')
        self.assertEqual(
            services.seats_taken(self.trip, exclude_booking_id=mine.id), 1)

    def test_active_seat_q_matches_seats_taken(self):
        now = timezone.now()
        self.booking(2, 'confirmed')
        self.booking(3, 'pending', now - MIN)
        from django.db.models import Sum
        total = Booking.objects.filter(
            services.active_seat_q(now), trip=self.trip
        ).aggregate(t=Sum('seats'))['t']
        self.assertEqual(total, services.seats_taken(self.trip, now))

    def test_reserve_seats_raises_with_available_count(self):
        self.booking(3, 'confirmed')
        self.assertEqual(services.reserve_seats(self.trip, 1), 0)
        with self.assertRaises(services.NotEnoughSeats) as ctx:
            services.reserve_seats(self.trip, 2)
        self.assertEqual(ctx.exception.available, 1)

    def test_no_sum_seats_outside_services(self):
        pattern = re.compile(r"Sum\(\s*['\"]seats['\"]|bookings__seats|\.seats\s+for\s")
        files = sorted(BACKEND.glob('*/views.py')) + sorted(BACKEND.glob('*/serializers.py'))
        bad = []
        for path in files:
            for no, line in enumerate(path.read_text().splitlines(), 1):
                if not pattern.search(line):
                    continue
                # The operator manifest totals passengers on one trip's
                # active bookings (not a capacity check); the annotate in
                # get_trips is the sanctioned use of active_seat_q.
                if 'passenger_count' in line or 'active_seat_q' in line:
                    continue
                bad.append(f'{path.parent.name}/{path.name}:{no}: {line.strip()}')
        self.assertEqual(bad, [])


class CreateBookingHoldTests(SeatBase):
    def test_create_sets_held_until_ten_minutes_and_pay_before(self):
        resp = self.create_via_api()
        self.assertEqual(resp.status_code, 201, resp.content)
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.assertAlmostEqual(
            (b.held_until - b.created_at).total_seconds(), 600, delta=5)
        self.assertEqual(resp.data['pay_before'], b.held_until)

    def test_held_until_never_outlives_departure(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() + 8 * MIN)
        self.company.booking_cutoff_minutes = 0
        self.company.save()
        resp = self.create_via_api()
        self.assertEqual(resp.status_code, 201, resp.content)
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.trip.refresh_from_db()
        self.assertEqual(b.held_until, self.trip.departure_at)

    def test_expired_hold_frees_the_seat_without_the_cron(self):
        self.booking(4, 'pending', timezone.now() - MIN)
        resp = self.create_via_api(seats=4)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_live_hold_blocks(self):
        self.booking(4, 'pending', timezone.now() + 5 * MIN)
        resp = self.create_via_api(seats=1)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Only 0 remaining', resp.data['error'])

    def test_detail_shows_pay_before_for_pending(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=self.passenger)
        self.client.force_authenticate(self.passenger)
        resp = self.client.get(f'/api/bookings/{b.id}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('pay_before', resp.data)
        self.assertIsNotNone(resp.data['pay_before'])

    def test_hold_is_never_extended(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=self.passenger)
        before = Booking.objects.get(pk=b.pk).held_until
        self.client.force_authenticate(self.passenger)
        for _ in range(10):
            with mock.patch('bookings.views.requests.post') as post:
                post.return_value.status_code = 400
                post.return_value.json.return_value = {'status': False, 'message': 'no'}
                self.client.post(f'/api/bookings/payments/{b.id}/paystack/', {})
            Payment.objects.filter(booking=b).update(status='failed')
        self.assertEqual(Booking.objects.get(pk=b.pk).held_until, before)


class CutoffTests(SeatBase):
    def setUp(self):
        super().setUp()
        self.company.booking_cutoff_minutes = 15
        self.company.save()

    def _depart_in(self, minutes):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() + minutes * MIN)
        self.trip.refresh_from_db()

    def test_create_rejected_inside_cutoff(self):
        self._depart_in(14)
        resp = self.create_via_api()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['code'], 'booking_closed')
        self.assertEqual(resp.data['closes_at'], self.trip.departure_at - 15 * MIN)
        self.assertFalse(Booking.objects.filter(trip=self.trip).exists())

    def test_create_allowed_just_outside_cutoff(self):
        self._depart_in(16)
        self.assertEqual(self.create_via_api().status_code, 201)

    def test_cutoff_is_per_company(self):
        other = Company.objects.create(name='Other', areas_served='x',
                                       booking_cutoff_minutes=0)
        route = Route.objects.create(company=other, name='R2', start_point='a',
                                     end_point='b', price=Decimal('100'))
        PickupStage.objects.create(route=route, name='S', order=1,
                                   latitude=Decimal('-1.28'), longitude=Decimal('36.8'))
        driver = Driver.objects.create(name='D2', phone_number='+254711000002',
                                       bus_number='K2', company=other)
        trip2 = Trip.objects.create(
            route=route, driver=driver, capacity=4, status='scheduled',
            departure_at=timezone.now() + 5 * MIN)
        stage2 = PickupStage.objects.get(route=route)
        self.client.force_authenticate(self.passenger)
        resp = self.client.post('/api/bookings/create/', {
            'trip_id': trip2.id, 'seats': 1, 'pickup_stage_id': stage2.id},
            format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self._depart_in(5)
        self.assertEqual(self.create_via_api().status_code, 400)

    def test_boarding_trip_after_departure_no_longer_bookable_online(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding', departure_at=timezone.now() - 5 * MIN)
        resp = self.create_via_api()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'booking_closed')

    def test_dispatcher_move_allowed_inside_cutoff(self):
        # Staff moves are exempt from the cut-off (decision of BE-W2).
        b = self.booking(1, 'confirmed')
        target = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=4, status='scheduled',
            departure_at=timezone.now() + 10 * MIN)
        self.client.force_authenticate(self.staff)
        resp = self.client.post(f'/api/bookings/{b.id}/move-trip/',
                                {'trip_id': target.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, target.id)

    def test_walkin_allowed_on_scheduled_inside_cutoff(self):
        self._depart_in(10)
        self.client.force_authenticate(self.staff)
        with mock.patch('notifications.sms.send_booking_sms'):
            resp = self.client.post(
                f'/api/bookings/walk-in/{self.trip.id}/',
                {'phone_number': '0733000111', 'seats': 1}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_walkin_refused_on_scheduled_before_cutoff(self):
        self._depart_in(60)
        self.client.force_authenticate(self.staff)
        resp = self.client.post(
            f'/api/bookings/walk-in/{self.trip.id}/',
            {'phone_number': '0733000111', 'seats': 1}, format='json')
        self.assertEqual(resp.status_code, 409, resp.content)

    def test_walkin_blocked_by_live_hold_and_not_by_expired(self):
        self._depart_in(10)
        self.booking(4, 'pending', timezone.now() + 5 * MIN)
        self.client.force_authenticate(self.staff)
        url = f'/api/bookings/walk-in/{self.trip.id}/'
        body = {'phone_number': '0733000111', 'seats': 1}
        self.assertEqual(self.client.post(url, body, format='json').status_code, 400)
        Booking.objects.filter(status='pending').update(
            held_until=timezone.now() - MIN)
        with mock.patch('notifications.sms.send_booking_sms'):
            self.assertEqual(self.client.post(url, body, format='json').status_code, 201)

    def test_closes_at_helper(self):
        self.assertEqual(services.booking_closes_at(self.trip),
                         self.trip.departure_at - 15 * MIN)


class ConfirmPathTests(SeatBase):
    capacity = 2

    def test_confirm_rechecks_capacity_after_hold_expiry(self):
        late = self.booking(2, 'pending', timezone.now() - MIN)
        pay = self.digital_payment(late)
        self.booking(2, 'confirmed')  # the seat was resold
        with mock.patch('bookings.views.settle_booking_fault') as refund:
            resp = self.webhook(pay)
        self.assertEqual(resp.status_code, 200)
        late.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(late.status, 'cancelled')
        self.assertEqual(pay.status, 'confirmed')
        refund.assert_called_once()
        self.assertFalse(BookingHold.objects.filter(booking=late).exists())

    def test_expired_hold_within_the_arrival_tolerance_still_confirms(self):
        late = self.booking(1, 'pending', timezone.now() - 30 * dt.timedelta(seconds=1))
        pay = self.digital_payment(late)
        with mock.patch('bookings.views.settle_booking_fault') as refund:
            self.assertEqual(self.webhook(pay).status_code, 200)
        late.refresh_from_db()
        self.assertEqual(late.status, 'confirmed')
        refund.assert_not_called()
        self.assertTrue(BookingHold.objects.filter(booking=late).exists())

    def test_on_time_payment_confirms_and_holds_money(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        pay = self.digital_payment(b)
        self.assertEqual(self.webhook(pay).status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        self.assertTrue(BookingHold.objects.filter(booking=b).exists())

    def test_amount_mismatch_fails_payment_and_alerts(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        pay = self.digital_payment(b)
        with mock.patch('bookings.views.send_admin_alert_sms') as alert:
            with self.captureOnCommitCallbacks(execute=True):
                self.webhook(pay, amount=5)
        pay.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((pay.status, b.status), ('failed', 'pending'))
        self.assertEqual(alert.call_count, 1)

    def test_status_and_verify_use_the_same_path(self):
        late = self.booking(2, 'pending', timezone.now() - MIN, user=self.passenger)
        pay = self.digital_payment(late)
        self.booking(2, 'confirmed')
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {'status': True, 'data': {
            'status': 'success', 'amount': 20000, 'currency': 'KES'}}
        self.client.force_authenticate(self.passenger)
        with mock.patch('bookings.views.requests.get', return_value=ok), \
                mock.patch('bookings.views.settle_booking_fault') as refund:
            resp = self.client.get(f'/api/bookings/payments/{late.id}/status/')
        self.assertEqual(resp.status_code, 200, resp.content)
        late.refresh_from_db()
        self.assertEqual(late.status, 'cancelled')
        # A GET decides the booking but leaves the refund to the sweep.
        refund.assert_not_called()
        Payment.objects.filter(pk=pay.pk).update(status='pending', refund_reason='')
        Booking.objects.filter(pk=late.pk).update(status='pending')
        with mock.patch('bookings.views.requests.get', return_value=ok), \
                mock.patch('bookings.views.settle_booking_fault') as refund:
            self.client.post(f'/api/bookings/payments/{late.id}/verify/')
        refund.assert_called_once()

    def test_trip_changed_under_us_asks_for_retry(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        pay = self.digital_payment(b)
        other = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=2, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=4))
        real = services._lock_payment_chain

        def move_then_lock(payment_id, booking_id, trip_id):
            Booking.objects.filter(pk=booking_id).update(trip=other)
            return real(payment_id, booking_id, trip_id)

        with mock.patch.object(services, '_lock_payment_chain', move_then_lock):
            self.client.raise_request_exception = False
            resp = self.webhook(pay)
        self.assertEqual(resp.status_code, 500)
        pay.refresh_from_db()
        self.assertEqual(pay.status, 'pending')

    def test_cash_confirm_rechecks_capacity_after_expiry(self):
        late = self.booking(2, 'pending', timezone.now() - MIN)
        Payment.objects.create(booking=late, amount=late.total_amount,
                               method='cash', status='pending')
        self.booking(2, 'confirmed')
        self.client.force_authenticate(self.staff)
        resp = self.client.post(f'/api/bookings/payments/{late.id}/cash/confirm/')
        self.assertEqual(resp.status_code, 409, resp.content)
        late.refresh_from_db()
        self.assertEqual(late.status, 'pending')

    def test_cash_confirm_of_expired_hold_with_free_seat_works(self):
        late = self.booking(1, 'pending', timezone.now() - MIN)
        Payment.objects.create(booking=late, amount=late.total_amount,
                               method='cash', status='pending')
        self.client.force_authenticate(self.staff)
        resp = self.client.post(f'/api/bookings/payments/{late.id}/cash/confirm/')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_cash_select_on_dead_hold_with_resold_seat_is_refused(self):
        late = self.booking(2, 'pending', timezone.now() - MIN, user=self.passenger)
        self.booking(2, 'confirmed')
        self.client.force_authenticate(self.passenger)
        resp = self.client.post(f'/api/bookings/payments/{late.id}/cash/')
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.data['code'], 'hold_expired')
        self.assertLessEqual(services.seats_taken(self.trip), 2)

    def test_cash_revival_of_a_lapsed_hold_gets_seat_numbers_again(self):
        from bookings.models import SeatAssignment
        from bookings.seats import purge_dead_rows
        b = self.booking(2, 'pending', timezone.now() - MIN, user=self.passenger)
        SeatAssignment.objects.create(trip=self.trip, seat_no=1, booking=b)
        SeatAssignment.objects.create(trip=self.trip, seat_no=2, booking=b)
        purge_dead_rows(self.trip)  # another writer clears the lapsed hold's rows
        self.assertEqual(SeatAssignment.objects.filter(booking=b).count(), 0)
        self.client.force_authenticate(self.passenger)
        resp = self.client.post(f'/api/bookings/payments/{b.id}/cash/')
        self.assertIn(resp.status_code, (200, 201), resp.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')
        self.assertGreater(b.held_until, timezone.now())
        numbers = sorted(SeatAssignment.objects.filter(booking=b).values_list('seat_no', flat=True))
        self.assertEqual(len(numbers), 2)
        self.assertEqual(len(set(numbers)), 2)

    def test_cash_holds_until_the_trip_is_over_digital_ttl_10(self):
        resp = self.create_via_api()
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.assertAlmostEqual(
            (b.held_until - b.created_at).total_seconds(), 600, delta=5)
        self.client.post(f'/api/bookings/payments/{b.id}/cash/')
        b.refresh_from_db()
        self.trip.refresh_from_db()
        # Cash is paid on board, possibly at a later stage: the seat is held
        # until the trip is over.
        self.assertEqual(
            b.held_until,
            self.trip.departure_at + dt.timedelta(hours=settings.TRIP_AUTO_CLOSE_AFTER_HOURS))
        first = b.held_until
        self.client.post(f'/api/bookings/payments/{b.id}/cash/')
        b.refresh_from_db()
        self.assertEqual(b.held_until, first)

    def test_cash_hold_is_not_capped_at_departure(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() + 16 * MIN)
        self.company.booking_cutoff_minutes = 0
        self.company.save()
        resp = self.create_via_api()
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.client.post(f'/api/bookings/payments/{b.id}/cash/')
        b.refresh_from_db()
        self.trip.refresh_from_db()
        self.assertEqual(
            b.held_until,
            self.trip.departure_at + dt.timedelta(hours=settings.TRIP_AUTO_CLOSE_AFTER_HOURS))


class ExpirySweepTests(SeatBase):
    def _run(self, *args):
        out = StringIO()
        call_command('expire_pending_bookings', *args, stdout=out)
        return out.getvalue()

    def test_expire_sweep_covers_boarding_trips(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding', departure_at=timezone.now() + dt.timedelta(minutes=30))
        b = self.booking(1, 'pending', timezone.now() - MIN)
        self._run()
        b.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')

    def test_sweep_leaves_live_holds_and_paid_rows(self):
        live = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        paid = self.booking(1, 'pending', timezone.now() - MIN)
        self.digital_payment(paid, status='confirmed')
        self._run()
        live.refresh_from_db()
        paid.refresh_from_db()
        self.assertEqual(live.status, 'pending')
        self.assertEqual(paid.status, 'pending')

    def test_cash_booking_is_not_swept(self):
        b = self.booking(1, 'pending', timezone.now() + 8 * MIN)
        Payment.objects.create(booking=b, amount=b.total_amount, method='cash',
                               status='pending')
        Booking.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - 12 * MIN)
        self._run()
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')

    def test_ttl_flag_overrides_by_created_at(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        Booking.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - 30 * MIN)
        self._run('--ttl-minutes', '25')
        b.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')

    def test_unstamped_legacy_row_expires_by_created_at(self):
        b = self.booking(1, 'pending', None)
        Booking.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - 30 * MIN)
        self._run()
        b.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')

    def test_default_ttl_setting_is_ten(self):
        self.assertEqual(settings.PAYMENT_HOLD_MINUTES, 10)


class CancelAndRestoreTests(SeatBase):
    def test_non_owner_gets_404_not_403(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        self.client.force_authenticate(self.passenger)
        resp = self.client.post(f'/api/bookings/{b.id}/cancel/')
        self.assertEqual(resp.status_code, 404, resp.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')

    def test_failed_refund_restore_of_pending_booking_keeps_its_seat(self):
        from bookings.services import RefundRejected
        b = self.booking(2, 'pending', timezone.now() - MIN, user=self.passenger)
        self.digital_payment(b, status='confirmed')
        self.client.force_authenticate(self.passenger)
        with mock.patch('bookings.services.execute_booking_refund',
                        side_effect=RefundRejected('no')):
            resp = self.client.post(f'/api/bookings/{b.id}/cancel/')
        self.assertEqual(resp.status_code, 409, resp.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'pending')
        self.assertGreater(b.held_until, timezone.now())
        self.assertEqual(services.seats_taken(self.trip), 2)


class SeatCountConsumersTests(SeatBase):
    def test_trip_list_booked_seats_ignores_expired_holds(self):
        self.booking(1, 'confirmed')
        self.booking(2, 'pending', timezone.now() - MIN)
        self.booking(1, 'pending', timezone.now() + 5 * MIN)
        resp = APIClient().get('/api/companies/trips/')
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        row = next(r for r in rows if r['id'] == self.trip.id)
        self.assertEqual(row['booked_seats'], 2)

    def test_trip_serializer_without_annotation_ignores_expired(self):
        from companies.serializers import TripSerializer
        self.booking(1, 'confirmed')
        self.booking(2, 'pending', timezone.now() - MIN)
        self.assertEqual(TripSerializer(self.trip).data['booked_seats'], 1)

    def test_bus_swap_ignores_expired_holds(self):
        self.booking(1, 'confirmed')
        self.booking(3, 'pending', timezone.now() - MIN)
        from buses.models import Bus
        bus = Bus.objects.create(
            company=self.company, bus_number='B1', registration_number='KDA 111A',
            capacity=1, vehicle_type='other')
        self.client.force_authenticate(self.staff)
        resp = self.client.patch(
            f'/api/companies/trips/{self.trip.id}/bus/', {'bus_id': bus.id},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['seats_taken'], 1)
