"""Seat numbers (rows) and seat capacity (count) agree: one definition of "active"."""
import datetime as dt
from unittest import mock

from django.utils import timezone
from rest_framework.test import APIClient

from bookings import seats, services
from bookings.models import Booking, SeatAssignment
from bookings.tests.review_base import fund
from bookings.tests.test_seat_holds import MIN, SeatBase
from companies.models import Trip


class IntegrationBase(SeatBase):
    capacity = 14

    def numbered(self, booking, numbers, trip=None):
        trip = trip or self.trip
        for n in numbers:
            SeatAssignment.objects.create(trip=trip, seat_no=n, booking=booking)
        return booking

    def rows(self, booking):
        return sorted(booking.seat_assignments.values_list('seat_no', flat=True))

    def book(self, user=None, seats_=1, numbers=None, trip=None, key=None):
        self.client.force_authenticate(user or self.passenger)
        body = {'trip_id': (trip or self.trip).id, 'seats': seats_,
                'pickup_stage_id': self.stage.id}
        if numbers is not None:
            body['seat_numbers'] = numbers
        if key:
            body['idempotency_key'] = key
        return self.client.post('/api/bookings/create/', body, format='json')

    def seat_state(self, no):
        data = seats.seat_map(self.trip)
        return next(s for s in data['seats'] if s['no'] == no)['state']


class ExpiredHoldTests(IntegrationBase):
    def test_expired_hold_frees_numbers_and_capacity(self):
        old = self.numbered(self.booking(1, 'pending', timezone.now() - MIN), [5])
        self.assertEqual(self.seat_state(5), 'free')
        self.assertEqual(services.seats_taken(self.trip), 0)
        resp = self.book(self.user(), 1, [5])
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['seat_numbers'], [5])
        self.assertEqual(self.rows(old), [])

    def test_live_hold_keeps_its_number(self):
        self.numbered(self.booking(1, 'pending', timezone.now() + 5 * MIN), [5])
        self.assertEqual(self.seat_state(5), 'held')
        self.assertEqual(self.book(self.user(), 1, [5]).status_code, 409)

    def test_purge_dead_rows_removes_cancelled_and_expired_only(self):
        now = timezone.now()
        self.numbered(self.booking(1, 'cancelled'), [1])
        self.numbered(self.booking(1, 'pending', now - MIN), [2])
        live = self.numbered(self.booking(1, 'pending', now + 5 * MIN), [3])
        paid = self.numbered(self.booking(1, 'confirmed'), [4])
        SeatAssignment.objects.create(trip=self.trip, seat_no=5, blocked=True)
        seats.purge_dead_rows(self.trip, now)
        self.assertEqual(
            sorted(self.trip.seat_assignments.values_list('seat_no', flat=True)),
            [3, 4, 5])
        self.assertEqual((self.rows(live), self.rows(paid)), ([3], [4]))

    def test_expired_hold_does_not_hide_its_seats_in_the_map_count(self):
        self.numbered(self.booking(2, 'pending', timezone.now() - MIN), [1, 2])
        self.assertEqual(seats.seat_map(self.trip)['unassigned'], 0)
        self.booking(2, 'confirmed')  # legacy, no numbers
        self.assertEqual(seats.seat_map(self.trip)['unassigned'], 2)


class LatePaymentNumbersTests(IntegrationBase):
    def _pay(self, booking):
        pay = self.digital_payment(booking)
        return pay, services.confirm_booking_payment(
            paid_amount=int(pay.amount * 100), currency='KES',
            reference=pay.provider_reference)

    def test_late_payment_after_purge_gets_numbers_back(self):
        b = self.numbered(self.booking(2, 'pending', timezone.now() - 30 * dt.timedelta(seconds=1)), [3, 4])
        seats.purge_dead_rows(self.trip)
        self.assertEqual(self.rows(b), [])
        _, outcome = self._pay(b)
        self.assertEqual(outcome.result, 'confirmed')
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        self.assertEqual(len(self.rows(b)), 2)

    def test_late_payment_seat_resold_refunds_once(self):
        Trip.objects.filter(pk=self.trip.pk).update(capacity=2)
        b = self.booking(2, 'pending', timezone.now() - 30 * dt.timedelta(seconds=1))
        self.booking(2, 'confirmed')
        pay, outcome = self._pay(b)
        self.assertEqual(outcome.result, 'refund')
        b.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual((b.status, pay.refund_reason), ('cancelled', 'late_payment'))
        self.assertEqual(self.rows(b), [])
        again = services.confirm_booking_payment(
            paid_amount=int(pay.amount * 100), currency='KES',
            reference=pay.provider_reference)
        self.assertEqual(again.result, 'ignored')

    def test_late_payment_with_old_number_resold_gets_another(self):
        b = self.booking(1, 'pending', timezone.now() - 30 * dt.timedelta(seconds=1))
        other = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=self.user())
        seats.assign_seats(self.trip, other, [3])
        _, outcome = self._pay(b)
        self.assertEqual(outcome.result, 'confirmed')
        got = self.rows(b)
        self.assertEqual(len(got), 1)
        self.assertNotIn(3, got)

    def test_every_confirm_edge_leaves_exactly_seats_rows(self):
        # webhook / status path (service)
        a = self.booking(2, 'pending', timezone.now() + 5 * MIN)
        self._pay(a)
        # cash confirm
        c = self.booking(2, 'pending', timezone.now() + 5 * MIN)
        from bookings.models import Payment
        Payment.objects.create(booking=c, amount=c.total_amount, method='cash', status='pending')
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(f'/api/bookings/payments/{c.id}/cash/confirm/').status_code, 200)
        # wallet
        owner = self.user()
        w = self.booking(2, 'pending', timezone.now() + 5 * MIN, user=owner)
        fund(owner, 1000, 'seed-int')
        self.client.force_authenticate(owner)
        self.assertEqual(
            self.client.post(f'/api/bookings/payments/{w.id}/wallet/').status_code, 200)
        for b in (a, c, w):
            b.refresh_from_db()
            self.assertEqual(b.status, 'confirmed')
            self.assertEqual(len(self.rows(b)), 2, b.id)
        numbers = [n for b in (a, c, w) for n in self.rows(b)]
        self.assertEqual(len(numbers), len(set(numbers)))


class RestoreTests(IntegrationBase):
    def _cancel_refused(self, booking, during=None):
        from bookings.services import RefundRejected

        def refuse(claim):
            if during:
                during()
            raise RefundRejected('no')

        self.client.force_authenticate(booking.user)
        with mock.patch('bookings.services.execute_booking_refund', side_effect=refuse), \
                mock.patch('bookings.views._alert_payment_problem') as alert:
            resp = self.client.post(f'/api/bookings/{booking.id}/cancel/')
        return resp, alert

    def test_cancel_refund_refused_restore_keeps_numbers_when_free(self):
        b = self.numbered(self.booking(2, 'confirmed', user=self.passenger), [3, 4])
        self.digital_payment(b, status='confirmed')
        resp, _ = self._cancel_refused(b)
        self.assertEqual(resp.status_code, 409, resp.content)
        b.refresh_from_db()
        self.assertEqual((b.status, self.rows(b)), ('confirmed', [3, 4]))

    def test_restore_gets_other_numbers_when_resold(self):
        b = self.numbered(self.booking(1, 'confirmed', user=self.passenger), [3])
        self.digital_payment(b, status='confirmed')
        buyer = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=self.user())

        def resale():
            seats.assign_seats(self.trip, buyer, [3])

        resp, _ = self._cancel_refused(b, during=resale)
        self.assertEqual(resp.status_code, 409, resp.content)
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        self.assertEqual(len(self.rows(b)), 1)
        self.assertNotIn(3, self.rows(b))
        self.assertEqual(self.rows(buyer), [3])

    def test_restore_fails_cleanly_when_capacity_gone(self):
        Trip.objects.filter(pk=self.trip.pk).update(capacity=1)
        b = self.numbered(self.booking(1, 'confirmed', user=self.passenger), [1])
        pay = self.digital_payment(b, status='confirmed')
        buyer = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=self.user())

        def resale():
            seats.assign_seats(self.trip, buyer, [1])

        resp, alert = self._cancel_refused(b, during=resale)
        self.assertEqual(resp.status_code, 409, resp.content)
        b.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(b.status, 'cancelled')
        self.assertEqual(pay.refund_reason, 'seat_lost_early')
        alert.assert_called_once()
        self.assertEqual(self.rows(buyer), [1])
        self.assertEqual(services.seats_taken(self.trip), 1)


class MoveTests(IntegrationBase):
    def _target(self, capacity):
        return Trip.objects.create(
            route=self.route, driver=self.driver, capacity=capacity,
            status='scheduled', departure_at=timezone.now() + dt.timedelta(hours=4))

    def _move(self, booking, target):
        self.client.force_authenticate(self.staff)
        return self.client.post(f'/api/bookings/{booking.id}/move-trip/',
                                {'trip_id': target.id}, format='json')

    def test_move_to_full_trip_409_no_rows_moved(self):
        b = self.numbered(self.booking(1, 'confirmed'), [2])
        target = self._target(1)
        self.booking(1, 'confirmed', trip=target)
        self.assertEqual(self._move(b, target).status_code, 409)
        b.refresh_from_db()
        self.assertEqual((b.trip_id, self.rows(b)), (self.trip.id, [2]))

    def test_move_onto_expired_hold_reuses_its_number(self):
        target = self._target(1)
        self.numbered(self.booking(1, 'pending', timezone.now() - MIN, trip=target), [1], trip=target)
        b = self.numbered(self.booking(1, 'confirmed'), [2])
        self.assertEqual(self._move(b, target).status_code, 200)
        b.refresh_from_db()
        self.assertEqual((b.trip_id, self.rows(b)), (target.id, [1]))

    def test_move_expired_pending_excludes_self(self):
        target = self._target(1)
        b = self.numbered(self.booking(1, 'pending', timezone.now() - MIN), [2])
        self.assertEqual(self._move(b, target).status_code, 200)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, target.id)


class WalkInTests(IntegrationBase):
    def _walk(self, seats_=1, numbers=None, trip=None):
        self.client.force_authenticate(self.staff)
        body = {'phone_number': '0733000111', 'seats': seats_}
        if numbers is not None:
            body['seat_numbers'] = numbers
        with mock.patch('notifications.sms.send_booking_sms'):
            return self.client.post(
                f'/api/bookings/walk-in/{(trip or self.trip).id}/', body, format='json')

    def _after_cutoff(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() + 10 * MIN)

    def test_walk_in_assigns_numbers_after_cutoff_and_caps_at_6(self):
        self._after_cutoff()
        resp = self._walk(1, [3])
        self.assertEqual(resp.status_code, 201, resp.content)
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.assertEqual(self.rows(b), [3])
        too_many = self._walk(7)
        self.assertEqual(too_many.status_code, 400)
        self.assertEqual(too_many.data['code'], 'seat_limit')

    def test_walk_in_respects_blocked_seats(self):
        self._after_cutoff()
        Trip.objects.filter(pk=self.trip.pk).update(capacity=2)
        SeatAssignment.objects.create(trip=self.trip, seat_no=1, blocked=True)
        self.assertEqual(self._walk(2).status_code, 400)
        resp = self._walk(1)
        self.assertEqual(resp.status_code, 201, resp.content)
        b = Booking.objects.get(pk=resp.data['booking_id'])
        self.assertEqual(self.rows(b), [2])
        self.assertEqual(self._walk(1).status_code, 400)


class CapTests(IntegrationBase):
    def test_per_booking_cap_is_six(self):
        resp = self.book(self.passenger, 7)
        self.assertEqual((resp.status_code, resp.data['code']), (400, 'seat_limit'))
        self.assertEqual(self.book(self.passenger, 6).status_code, 201)

    def test_caps_count_live_holds_only(self):
        self.assertEqual(self.book(self.passenger, 6).status_code, 201)
        # per trip: 6 unpaid seats already held here
        resp = self.book(self.passenger, 1)
        self.assertEqual((resp.status_code, resp.data['code']), (400, 'seat_limit'))
        Booking.objects.filter(user=self.passenger).update(
            held_until=timezone.now() - MIN)
        self.assertEqual(self.book(self.passenger, 1).status_code, 201)

    def test_per_user_cap_of_ten_seats_counts_live_holds_only(self):
        other = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=5))
        first = self.book(self.passenger, 6)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(self.book(self.passenger, 5, trip=other).status_code, 400)
        Booking.objects.filter(pk=first.data['booking_id']).update(
            held_until=timezone.now() - MIN)
        self.assertEqual(self.book(self.passenger, 5, trip=other).status_code, 201)


class FingerprintTests(IntegrationBase):
    def test_seat_numbers_in_fingerprint(self):
        first = self.book(numbers=[1], key='key-1')
        self.assertEqual(first.status_code, 201, first.content)
        again = self.book(numbers=[1], key='key-1')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['seat_numbers'], [1])
        self.assertTrue(again.data['replayed'])
        other = self.book(numbers=[2], key='key-1')
        self.assertEqual((other.status_code, other.data['code']),
                         (409, 'idempotency_key_reused'))
        self.assertEqual(Booking.objects.count(), 1)


class BlockedSeatsAgreeTests(IntegrationBase):
    def test_blocked_seats_in_seats_available_and_summary(self):
        SeatAssignment.objects.create(trip=self.trip, seat_no=3, blocked=True)
        self.booking(2, 'confirmed')
        taken = services.seats_taken(self.trip)
        self.assertEqual(taken, 3)
        self.assertEqual(seats.seat_map(self.trip)['blocked_count'], 1)
        rows = APIClient().get('/api/companies/trips/').data
        rows = rows['results'] if isinstance(rows, dict) else rows
        row = next(r for r in rows if r['id'] == self.trip.id)
        self.assertEqual((row['booked_seats'], row['seats_available']), (3, 11))
        self.client.force_authenticate(self.staff)
        summary = self.client.get(f'/api/companies/trips/{self.trip.id}/seat-summary/').data
        self.assertEqual((summary['open_seats'], summary['blocked_seats']), (11, 1))
        free = [s for s in seats.seat_map(self.trip)['seats'] if s['state'] == 'free']
        self.assertEqual(len(free) - seats.seat_map(self.trip)['unassigned'], 11)

    def test_block_over_an_expired_hold_succeeds(self):
        self.numbered(self.booking(1, 'pending', timezone.now() - MIN), [3])
        self.client.force_authenticate(self.staff)
        resp = self.client.post(f'/api/bookings/trips/{self.trip.id}/seats/3/block/', {}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_trip_bus_swap_ignores_dead_rows(self):
        from buses.models import Bus
        self.numbered(self.booking(1, 'pending', timezone.now() - MIN), [12])
        bus = Bus.objects.create(
            company=self.company, bus_number='B1', registration_number='KDA 111A',
            capacity=4, vehicle_type='other')
        self.client.force_authenticate(self.staff)
        resp = self.client.patch(f'/api/companies/trips/{self.trip.id}/bus/',
                                 {'bus_id': bus.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)


class OneDefinitionTests(IntegrationBase):
    def test_one_seats_taken_definition(self):
        from bookings import views
        self.assertFalse(hasattr(seats, 'seats_taken'))
        self.assertIs(views.seats_taken, services.seats_taken)


class SeatBookedPushTests(IntegrationBase):
    def _count(self, send):
        with mock.patch('bookings.views.push.notify_users') as notify, \
                self.captureOnCommitCallbacks(execute=True):
            send()
        return notify.call_count

    def test_digital_confirm_pushes_once(self):
        b = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        pay = self.digital_payment(b)
        self.assertEqual(self._count(lambda: self.webhook(pay)), 1)
        self.assertEqual(self._count(lambda: self.webhook(pay)), 0)

    def test_late_refunded_payment_does_not_push(self):
        Trip.objects.filter(pk=self.trip.pk).update(capacity=1)
        b = self.booking(1, 'pending', timezone.now() - 30 * dt.timedelta(seconds=1))
        self.booking(1, 'confirmed')
        pay = self.digital_payment(b)
        with mock.patch('bookings.views.settle_booking_fault'):
            self.assertEqual(self._count(lambda: self.webhook(pay)), 0)

    def test_wallet_and_cash_push_once(self):
        owner = self.user()
        w = self.booking(1, 'pending', timezone.now() + 5 * MIN, user=owner)
        fund(owner, 500, 'seed-push')
        self.client.force_authenticate(owner)
        self.assertEqual(self._count(
            lambda: self.client.post(f'/api/bookings/payments/{w.id}/wallet/')), 1)
        c = self.booking(1, 'pending', timezone.now() + 5 * MIN)
        from bookings.models import Payment
        Payment.objects.create(booking=c, amount=c.total_amount, method='cash', status='pending')
        self.client.force_authenticate(self.staff)
        self.assertEqual(self._count(
            lambda: self.client.post(f'/api/bookings/payments/{c.id}/cash/confirm/')), 1)



class ScheduleRebusTests(IntegrationBase):
    """Re-busing a schedule moves only empty trips; a blocked seat that the
    smaller bus does not have keeps a trip where it is."""

    def _schedule_with_trip(self, bus):
        from companies.models import TripSchedule
        sched = TripSchedule.objects.create(
            route=self.route, driver=self.driver, bus=bus, capacity=bus.capacity,
            days_of_week='0,1,2,3,4,5,6', departure_time='06:00',
            auto_renew=True)
        Trip.objects.filter(pk=self.trip.pk).update(
            schedule=sched, bus=bus, capacity=bus.capacity)
        return sched

    def _rebus(self, sched, bus):
        self.client.force_authenticate(self.staff)
        return self.client.patch(f'/api/companies/schedules/{sched.id}/',
                                 {'bus_id': bus.id}, format='json')

    def _buses(self):
        from buses.models import Bus
        mk = lambda n, cap: Bus.objects.create(  # noqa: E731
            company=self.company, bus_number=n, registration_number=f'KDA {n}A',
            capacity=cap, vehicle_type='other')
        return mk('B14', 14), mk('B4', 4)

    def test_empty_trip_moves_to_the_smaller_bus(self):
        big, small = self._buses()
        sched = self._schedule_with_trip(big)
        r = self._rebus(sched, small)
        self.assertEqual(r.status_code, 200, r.content)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.bus_id, self.trip.capacity), (small.id, 4))

    def test_a_blocked_seat_the_smaller_bus_lacks_keeps_the_trip(self):
        big, small = self._buses()
        sched = self._schedule_with_trip(big)
        SeatAssignment.objects.create(trip=self.trip, seat_no=12, blocked=True)
        r = self._rebus(sched, small)
        self.assertEqual(r.status_code, 200, r.content)
        self.trip.refresh_from_db()
        self.assertEqual((self.trip.bus_id, self.trip.capacity), (big.id, 14))
