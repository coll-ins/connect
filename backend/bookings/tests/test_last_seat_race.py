"""Real concurrency: several passengers hit the last seat at the same instant.

Runs only on PostgreSQL (CI and production): SQLite serialises every write,
so it cannot prove anything about row locks.
"""
import datetime as dt
import threading
import unittest
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models import Sum
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings import services
from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class LastSeatRaceTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name='Race Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        self.trip = Trip.objects.create(
            route=self.route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))

    def _fill(self, seats):
        filler = User.objects.create_user(
            username='filler', password='pw-123456', phone_number='+254711999999')
        Booking.objects.create(
            user=filler, trip=self.trip, route=self.route, driver=self.trip.driver,
            seats=seats, total_amount=Decimal('100') * seats, status='confirmed',
            pickup_location='Kencom')

    def _race(self, racers, seats_each):
        users = [
            User.objects.create_user(
                username=f'racer{i}', password='pw-123456',
                phone_number=f'+2547120000{i:02d}')
            for i in range(racers)
        ]
        barrier = threading.Barrier(racers)
        codes = []

        def book(user):
            client = APIClient()
            client.force_authenticate(user)
            barrier.wait()
            try:
                r = client.post('/api/bookings/create/', {
                    'trip_id': self.trip.id, 'seats': seats_each,
                    'pickup_stage_id': self.stage.id}, format='json')
                codes.append(r.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=book, args=(u,)) for u in users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        taken = (self.trip.bookings.exclude(status='cancelled')
                 .aggregate(s=Sum('seats'))['s'])
        return codes, taken

    def test_ten_passengers_one_last_seat(self):
        self._fill(13)
        codes, taken = self._race(10, 1)
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(taken, 14)

    def test_two_people_ask_for_two_of_the_last_two_seats(self):
        self._fill(12)
        codes, taken = self._race(2, 2)
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(taken, 14)


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class BoardingTripLastSeatRaceTests(LastSeatRaceTests):
    """The same races on a trip that is already boarding."""

    def setUp(self):
        super().setUp()
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        self.trip.refresh_from_db()


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class MoveAndWalkInRaceTests(LastSeatRaceTests):
    def _staff(self):
        return User.objects.create_user(
            username='staff', password='pw-123456',
            phone_number='+254711777777', is_superuser=True, is_staff=True)

    def _run(self, jobs):
        barrier = threading.Barrier(len(jobs))
        codes = []

        def go(job):
            barrier.wait()
            try:
                codes.append(job())
            finally:
                connection.close()

        threads = [threading.Thread(target=go, args=(j,)) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return codes

    def _seats(self):
        return (self.trip.bookings.filter(services.active_seat_q())
                .aggregate(s=Sum('seats'))['s'] or 0)

    def test_ten_moves_onto_a_trip_with_one_seat_left(self):
        self._fill(13)
        other = Trip.objects.create(
            route=self.route, driver=self.trip.driver, capacity=40,
            status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        staff = self._staff()
        ids = []
        for i in range(10):
            u = User.objects.create_user(
                username=f'mv{i}', password='pw-123456',
                phone_number=f'+2547140000{i:02d}')
            ids.append(Booking.objects.create(
                user=u, trip=other, route=self.route, driver=other.driver,
                seats=1, total_amount=Decimal('100'), status='confirmed',
                pickup_location='Kencom').id)

        def mover(booking_id):
            def job():
                c = APIClient()
                c.force_authenticate(staff)
                return c.post(f'/api/bookings/{booking_id}/move-trip/',
                              {'trip_id': self.trip.id}, format='json').status_code
            return job

        codes = self._run([mover(i) for i in ids])
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(self._seats(), 14)

    def test_walkin_and_online_never_exceed_capacity(self):
        """40 threads, online and walk-up, on the last 3 seats: exactly 3 sold."""
        self._fill(11)
        Trip.objects.filter(pk=self.trip.pk).update(
            status='boarding',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        staff = self._staff()
        online_users = [
            User.objects.create_user(
                username=f'on{i}', password='pw-123456',
                phone_number=f'+2547150000{i:02d}')
            for i in range(20)
        ]

        def online(user):
            def job():
                c = APIClient()
                c.force_authenticate(user)
                return c.post('/api/bookings/create/', {
                    'trip_id': self.trip.id, 'seats': 1,
                    'pickup_stage_id': self.stage.id}, format='json').status_code
            return job

        def walk(i):
            def job():
                c = APIClient()
                c.force_authenticate(staff)
                return c.post(f'/api/bookings/walk-in/{self.trip.id}/', {
                    'phone_number': f'07330000{i:02d}', 'seats': 1},
                    format='json').status_code
            return job

        jobs = [online(u) for u in online_users] + [walk(i) for i in range(20)]
        with mock.patch('notifications.sms.send_booking_sms'):
            codes = self._run(jobs)
        sold = codes.count(201)
        self.assertEqual(sold, 3, codes)
        self.assertEqual(self._seats(), 14)


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class SeatNumberRaceTests(TransactionTestCase):
    """Seat numbers and seat capacity stay in step when writers race."""

    def setUp(self):
        from bookings.tests.review_base import run_together
        self.run_together = run_together
        company = Company.objects.create(name='Num Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        self.driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=company)
        self.trip = self._trip(14)
        self.n = 0

    def _trip(self, capacity, status='scheduled'):
        return Trip.objects.create(
            route=self.route, driver=self.driver, capacity=capacity, status=status,
            departure_at=timezone.now() + dt.timedelta(hours=2))

    def _user(self):
        self.n += 1
        return User.objects.create_user(
            username=f'num{self.n}', password='pw-123456',
            phone_number=f'+2547160{self.n:05d}')

    def _book(self, user, numbers=None, seats=1, trip=None):
        def job():
            c = APIClient()
            c.force_authenticate(user)
            body = {'trip_id': (trip or self.trip).id, 'seats': seats,
                    'pickup_stage_id': self.stage.id}
            if numbers is not None:
                body['seat_numbers'] = numbers
            return c.post('/api/bookings/create/', body, format='json').status_code
        return job

    def _invariants(self, trip):
        from bookings.models import SeatAssignment
        from bookings.seats import seat_row_active_q
        trip.refresh_from_db()
        self.assertLessEqual(services.seats_taken(trip), trip.capacity)
        active = list(
            SeatAssignment.objects.filter(seat_row_active_q(), trip=trip)
            .values_list('seat_no', flat=True))
        self.assertEqual(len(active), len(set(active)))
        for b in trip.bookings.filter(services.active_seat_q()):
            self.assertLessEqual(b.seat_assignments.count(), b.seats)

    def test_same_number_requested_together_exactly_one_201(self):
        codes, errs = self.run_together([self._book(self._user(), [5]) for _ in range(6)])
        self.assertEqual(errs, [])
        self.assertEqual(codes.count(201), 1, codes)
        self.assertEqual(codes.count(409), 5, codes)
        self.assertEqual(Booking.objects.filter(trip=self.trip).count(), 1)
        self._invariants(self.trip)

    def test_expired_hold_resold_against_late_payment(self):
        from bookings.models import Payment
        trip = self._trip(1)
        late = Booking.objects.create(
            user=self._user(), trip=trip, route=self.route, driver=self.driver,
            seats=1, total_amount=Decimal('100'), status='pending',
            held_until=timezone.now() - dt.timedelta(seconds=20),
            pickup_location='Kencom')
        pay = Payment.objects.create(
            booking=late, amount=Decimal('100'), method='digital', status='pending',
            provider_reference='CONNECT-late-1', idempotency_key='CONNECT-late-1')
        buyer = self._user()

        def pay_late():
            return services.confirm_booking_payment(
                paid_amount=10000, currency='KES',
                reference=pay.provider_reference).result

        out, errs = self.run_together([pay_late, self._book(buyer, [1], trip=trip)])
        self.assertEqual(errs, [])
        late.refresh_from_db()
        bought = Booking.objects.filter(user=buyer, trip=trip).exists()
        self.assertEqual((late.status == 'confirmed') + bought, 1, out)
        self._invariants(trip)

    def test_move_and_create_race_for_the_last_seat(self):
        target = self._trip(1)
        staff = User.objects.create_user(
            username='stf', password='pw-123456', phone_number='+254711777771',
            is_superuser=True, is_staff=True)
        mover = Booking.objects.create(
            user=self._user(), trip=self.trip, route=self.route, driver=self.driver,
            seats=1, total_amount=Decimal('100'), status='confirmed',
            pickup_location='Kencom')

        def move():
            c = APIClient()
            c.force_authenticate(staff)
            return c.post(f'/api/bookings/{mover.id}/move-trip/',
                          {'trip_id': target.id}, format='json').status_code

        out, errs = self.run_together([move, self._book(self._user(), [1], trip=target)])
        self.assertEqual(errs, [])
        self.assertEqual(sum(1 for c in out if c in (200, 201)), 1, out)
        self.assertEqual(target.bookings.filter(services.active_seat_q()).count(), 1)
        self._invariants(target)
        self._invariants(self.trip)

    def test_walk_in_and_online_race_for_the_last_seat(self):
        trip = self._trip(1, status='boarding')
        staff = User.objects.create_user(
            username='stf2', password='pw-123456', phone_number='+254711777772',
            is_superuser=True, is_staff=True)

        def walk():
            c = APIClient()
            c.force_authenticate(staff)
            return c.post(f'/api/bookings/walk-in/{trip.id}/', {
                'phone_number': '0733000999', 'seats': 1, 'seat_numbers': [1]},
                format='json').status_code

        with mock.patch('notifications.sms.send_booking_sms'):
            out, errs = self.run_together([walk, self._book(self._user(), [1], trip=trip)])
        self.assertEqual(errs, [])
        self.assertEqual(sum(1 for c in out if c in (200, 201)), 1, out)
        self.assertEqual(trip.bookings.filter(services.active_seat_q()).count(), 1)
        self._invariants(trip)
