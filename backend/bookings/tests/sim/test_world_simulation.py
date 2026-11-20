"""World simulation, part 1: seats, cut-off, holds, boarding, GPS and trips.

Real seeded SACCOs and routes (see base.SimCase). Synthetic stages are added in
the test database only. Every test ends with the global invariants.
"""
import datetime as dt
import unittest

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bookings import services
from bookings.models import Booking, BoardingEvent
from companies.models import Company, Trip

from .base import POSTGRES, SimCase

User = get_user_model()


def fill(tc, trip, seats, status='confirmed'):
    """Seats taken by someone else, straight in the database (a booking made earlier)."""
    filler = tc.user()
    return Booking.objects.create(
        user=filler, trip=trip, route=trip.route, driver=trip.driver, seats=seats,
        total_amount=trip.route.price * seats, status=status, pickup_location='earlier')


@unittest.skipUnless(POSTGRES, 'needs real row locks')
class ConcurrentSeatRaceTests(SimCase):
    def test_last_seats_on_three_companies_at_once(self):
        trips = []
        for ci in range(3):
            company, route = self.ready_route(ci, 0, index=ci)
            trip = self.trip(route, minutes=90)
            fill(self, trip, 11)
            trips.append(trip)
        # A fourth trip where every racer wants two seats and five are left.
        company, route = self.ready_route(0, 1, index=7)
        pairs = self.trip(route, minutes=90)
        fill(self, pairs, 9)

        jobs, labels = [], []
        for trip in trips:
            stage = self.first_stage(trip.route)
            for _ in range(12):
                user = self.user()
                labels.append(('one', trip.pk))
                jobs.append(lambda u=user, t=trip, s=stage: self.api(u).post(
                    reverse('bookings:create-booking'),
                    {'trip_id': t.pk, 'seats': 1, 'pickup_stage_id': s.pk}, format='json').status_code)
        stage = self.first_stage(pairs.route)
        for _ in range(8):
            user = self.user()
            labels.append(('two', pairs.pk))
            jobs.append(lambda u=user: self.api(u).post(
                reverse('bookings:create-booking'),
                {'trip_id': pairs.pk, 'seats': 2, 'pickup_stage_id': stage.pk}, format='json').status_code)

        codes, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        won = {}
        for (kind, trip_id), code in zip(labels, codes):
            self.assertIn(code, (201, 400), code)
            won[trip_id] = won.get(trip_id, 0) + (code == 201)
        for trip in trips:
            self.assertEqual(won[trip.pk], 3, f'trip {trip.pk} sold {won[trip.pk]} of the last 3 seats')
            self.assertEqual(services.seats_taken(trip), 14)
        self.assertEqual(won[pairs.pk], 2)
        self.assertEqual(services.seats_taken(pairs), 13)

    def test_online_and_walkups_never_exceed_capacity_on_a_boarding_trip(self):
        company, route = self.ready_route(1, 0, index=3)
        trip = self.trip(route, minutes=25, status='boarding')
        fill(self, trip, 10)
        operator = self.staff(company, 'company_operator')
        stage = self.first_stage(route)
        online = [self.user() for _ in range(8)]
        jobs = [lambda u=u: ('online', self.api(u).post(
            reverse('bookings:create-booking'),
            {'trip_id': trip.pk, 'seats': 1, 'pickup_stage_id': stage.pk}, format='json').status_code)
            for u in online]
        for _ in range(8):
            phone = self.phone()
            jobs.append(lambda p=phone: ('walkin', self.api(operator).post(
                reverse('bookings:walk-in-booking', args=[trip.pk]),
                {'seats': 1, 'phone_number': p}, format='json').status_code))
        results, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        sold = sum(1 for _, code in results if code == 201)
        self.assertEqual(sold, 4, results)
        self.assertEqual(services.seats_taken(trip), 14)


class CutoffAndWalkupTests(SimCase):
    def test_online_booking_closes_per_company_and_walkups_fill_the_stage(self):
        a, route_a = self.ready_route(0, 0, index=1)
        b, route_b = self.ready_route(1, 0, index=2)
        Company.objects.filter(pk=b.pk).update(booking_cutoff_minutes=30)
        passenger = self.user()

        inside = self.trip(route_a, minutes=14)
        outside = self.trip(route_a, minutes=16)
        r = self.api(passenger).post(reverse('bookings:create-booking'), {
            'trip_id': inside.pk, 'seats': 1, 'pickup_stage_id': self.first_stage(route_a).pk}, format='json')
        self.assertEqual((r.status_code, r.json()['code']), (400, 'booking_closed'))
        self.book(passenger, outside)

        # A second company with a 30 minute cut-off: +20 minutes is already closed, +31 open.
        self.book(passenger, self.trip(route_b, minutes=31))
        r = self.api(passenger).post(reverse('bookings:create-booking'), {
            'trip_id': self.trip(route_b, minutes=20).pk, 'seats': 1,
            'pickup_stage_id': self.first_stage(route_b).pk}, format='json')
        self.assertEqual(r.json()['code'], 'booking_closed')

        # The passenger trip list hides the trips that are closed online.
        listed = {t['id'] for t in self.api(None).get(reverse('get_trips')).json()}
        self.assertIn(outside.pk, listed)
        self.assertNotIn(inside.pk, listed)

        # The stage boards walk-ups on the closed trip until it is full, never beyond.
        operator = self.staff(a, 'company_operator')
        client = self.api(operator)
        url = reverse('bookings:walk-in-booking', args=[inside.pk])
        for n in range(7):
            r = client.post(url, {'seats': 2, 'phone_number': self.phone()}, format='json')
            self.assertEqual(r.status_code, 201, r.content)
            self.assertEqual(r.json()['seats_remaining'], 14 - 2 * (n + 1))
        r = client.post(url, {'seats': 1, 'phone_number': self.phone()}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(services.seats_taken(inside), 14)
        summary = client.get(reverse('trip-seat-summary', args=[inside.pk])).json()
        self.assertEqual((summary['open_seats'], summary['boarded_seats'], summary['online_open']), (0, 14, False))
        self.assertEqual(BoardingEvent.objects.filter(trip=inside, method='walkin').count(), 7)

        # Walk-up is not open yet on the trip that online booking still serves, and not for another SACCO.
        r = client.post(reverse('bookings:walk-in-booking', args=[outside.pk]),
                        {'seats': 1, 'phone_number': self.phone()}, format='json')
        self.assertEqual(r.status_code, 409)
        r = self.api(self.staff(b, 'company_operator')).post(
            url, {'seats': 1, 'phone_number': self.phone()}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.api(passenger).post(url, {'seats': 1, 'phone_number': self.phone()}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_boarding_trip_accepts_online_booking_at_the_first_stage_only(self):
        company, route = self.ready_route(2, 0, index=4)
        trip = self.trip(route, minutes=40, status='boarding')
        stages = list(route.pickup_stages.order_by('order'))
        passenger = self.user()
        self.book(passenger, trip, stage=stages[1], expect=400)
        self.book(passenger, trip, stage=stages[0])


class HoldTests(SimCase):
    def test_hold_lasts_ten_minutes_then_the_seat_is_resold(self):
        company, route = self.ready_route(0, 0, index=1)
        trip = self.trip(route, minutes=60)
        fill(self, trip, 13)
        a, b = self.user(), self.user()
        first = self.booking(a, trip)
        wait = (first.held_until - timezone.now()).total_seconds()
        self.assertTrue(9 * 60 <= wait <= 10 * 60 + 2, wait)
        self.book(b, trip, expect=400)          # the held seat is not for sale
        held_until = first.held_until
        self.init_digital(a, first, mpesa=True)
        first.refresh_from_db()
        self.assertEqual(first.held_until, held_until, 'starting a payment must not extend the hold')

        self.expire_hold(first)                 # ten minutes pass
        second = self.booking(b, trip)          # the seat is sold again
        self.assertEqual(services.seats_taken(trip), 14)
        self.run_command('expire_pending_bookings')
        first.refresh_from_db()
        self.assertEqual(first.status, 'cancelled')
        self.assertEqual(second.status, 'pending')

    def test_payment_one_second_before_expiry_confirms(self):
        company, route = self.ready_route(1, 1, index=5)
        trip = self.trip(route, minutes=60)
        booking = self.booking(self.user(), trip)
        reference = self.init_digital(booking.user, booking, mpesa=True)
        Booking.objects.filter(pk=booking.pk).update(held_until=timezone.now() + dt.timedelta(seconds=1))
        event = self.fake.customer_pays(reference, booking.total_amount)
        self.assertEqual(self.webhook(event).status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(self.fake.accepted_refunds(), [])

    def test_pending_cap_per_user(self):
        company, route = self.ready_route(0, 0, index=1)
        trip = self.trip(route, minutes=60)
        user = self.user()
        for _ in range(3):
            self.book(user, trip)
        self.book(user, trip, expect=400)


class NoShowAndTripLifecycleTests(SimCase):
    def _paid(self, trip, n):
        out = []
        for _ in range(n):
            user = self.user()
            booking, ref = self.confirmed_booking(user, trip)
            out.append((user, booking, ref))
        return out

    def test_no_shows_are_settled_at_half_once_and_boarded_passengers_are_left_alone(self):
        company, route = self.ready_route(0, 0, index=1)
        trip = self.trip(route, minutes=30)
        paid = self._paid(trip, 4)
        pending = self.booking(self.user(), trip)
        Trip.objects.filter(pk=trip.pk).update(status='boarding')
        operator = self.staff(company, 'company_operator')
        for _, booking, _ in paid[:2]:
            r = self.api(operator).post(reverse('bookings:verify-boarding', args=[booking.pk]),
                                        {'boarding_pin': booking.verification_pin}, format='json')
            self.assertEqual(r.status_code, 200, r.content)
        self.depart_in(trip, -20)               # past the 15 minute grace
        self.run_command('process_noshows')
        self.run_command('process_noshows')     # a second run must change nothing

        for _, booking, _ in paid[:2]:
            booking.refresh_from_db()
            self.assertEqual(booking.status, 'completed')
        fare = route.price
        for user, booking, ref in paid[2:]:
            booking.refresh_from_db()
            payment = self.payment(booking)
            self.assertEqual(booking.status, 'no_show')
            self.assertEqual(payment.refund_amount, fare / 2)
            self.assertEqual(self.fake.refunded_subunits(ref), int(fare / 2 * 100))
            user.refresh_from_db()
            self.assertEqual(user.no_show_count, 1)
        pending.refresh_from_db()
        self.assertEqual(pending.status, 'cancelled')
        trip.refresh_from_db()
        self.assertEqual(trip.status, 'departed')
        self.assertEqual(len(self.fake.accepted_refunds()), 2)

    def test_company_cancels_trip_every_paid_booking_refunded_in_full_once(self):
        company, route = self.ready_route(1, 0, index=2)
        trip = self.trip(route, minutes=120)
        paid = self._paid(trip, 3)
        unpaid = [self.booking(self.user(), trip) for _ in range(2)]
        manager = self.staff(company, 'company_manager')
        client = self.api(manager)
        url = reverse('update_trip_status', args=[trip.pk])
        r = client.post(url, {'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['cancelled_bookings'], 5)
        self.assertEqual(r.json()['refunds_started'], 3)
        for _, booking, ref in paid:
            self.assertEqual(self.fake.refunded_subunits(ref), int(route.price * 100))
        for booking in unpaid:
            booking.refresh_from_db()
            self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(len(self.fake.accepted_refunds()), 3)
        # Cancelling again, or sweeping, refunds nothing more.
        self.assertEqual(client.post(url, {'status': 'cancelled'}, format='json').status_code, 200)
        self.run_command('process_noshows')
        self.assertEqual(len(self.fake.accepted_refunds()), 3)
        self.assertEqual(len([m for m in self.fake.sms if 'cancelled' in m[0]]), 5)

    def test_trip_with_a_boarded_passenger_cannot_be_cancelled(self):
        company, route = self.ready_route(1, 0, index=2)
        trip = self.trip(route, minutes=30)
        (_, booking, _), = self._paid(trip, 1)
        Trip.objects.filter(pk=trip.pk).update(status='boarding')
        r = self.api(self.staff(company, 'company_operator')).post(
            reverse('bookings:verify-boarding', args=[booking.pk]),
            {'boarding_pin': booking.verification_pin}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.api(self.staff(company, 'company_manager')).post(
            reverse('update_trip_status', args=[trip.pk]), {'status': 'cancelled'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.fake.accepted_refunds(), [])

    def test_driver_ends_trip_and_unboarded_passengers_become_no_shows(self):
        company, route = self.ready_route(2, 0, index=4)
        driver = self.driver(company)
        trip = self.trip(route, driver=driver, minutes=20)
        (_, boarded, _), (_, absent, ref) = self._paid(trip, 2)
        Trip.objects.filter(pk=trip.pk).update(status='boarding')
        r = self.api(driver.account).post(reverse('bookings:verify-boarding', args=[boarded.pk]),
                                          {'boarding_pin': boarded.verification_pin}, format='json')
        self.assertEqual(r.status_code, 200)
        r = self.api(driver.account).post(reverse('bookings:driver-end-trip', args=[driver.pk]), {}, format='json')
        self.assertEqual(r.status_code, 409, 'ending before departure must be refused')
        self.depart_in(trip, -25)
        r = self.api(driver.account).post(reverse('bookings:driver-end-trip', args=[driver.pk]), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        absent.refresh_from_db()
        self.assertEqual(absent.status, 'no_show')
        self.assertEqual(self.fake.refunded_subunits(ref), int(route.price * 50))
        self.assertEqual(Booking.objects.get(pk=boarded.pk).status, 'completed')


class GpsTests(SimCase):
    def _setup(self):
        company, route = self.ready_route(0, 0, index=1)
        driver = self.driver(company)
        trip = self.trip(route, driver=driver, minutes=20)
        passenger = self.user()
        booking, _ = self.confirmed_booking(passenger, trip)
        Trip.objects.filter(pk=trip.pk).update(status='boarding')
        stages = list(route.pickup_stages.order_by('order'))
        return company, route, driver, trip, passenger, booking, stages

    def post_fix(self, driver, lat, lng, seconds_ago=None, accuracy=None, expect=200):
        body = {'latitude': lat, 'longitude': lng}
        if seconds_ago is not None:
            body['fix_at'] = (timezone.now() - dt.timedelta(seconds=seconds_ago)).isoformat()
        if accuracy is not None:
            body['accuracy_m'] = accuracy
        r = self.api(driver.account).post(reverse('drivers:driver-location', args=[driver.pk]), body, format='json')
        self.assertEqual(r.status_code, expect, r.content)
        return r.json()

    def live(self, passenger, booking):
        r = self.api(passenger).get(reverse('bookings:booking-live-location', args=[booking.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_drops_stale_out_of_order_and_inaccurate_fixes(self):
        company, route, driver, trip, passenger, booking, stages = self._setup()
        s1, s2 = float(stages[0].latitude), float(stages[0].longitude)
        # Two fixes at the stage: the bus is boarding, not leaving.
        self.assertFalse(self.post_fix(driver, s1, s2, 100)['ignored'])
        self.assertFalse(self.post_fix(driver, s1 + 0.0001, s2, 90)['ignored'])
        accepted = Driver_row(driver)

        # A fix older than the 120 s limit, one older than the last accepted, one too inaccurate.
        self.assertEqual(self.post_fix(driver, s1 + 0.05, s2, 200)['reason'], 'stale')
        self.assertEqual(self.post_fix(driver, s1 + 0.05, s2, 95)['reason'], 'out_of_order')
        self.assertEqual(self.post_fix(driver, s1 + 0.05, s2, 5, accuracy=500)['reason'], 'inaccurate')
        self.assertEqual(Driver_row(driver), accepted, 'an ignored fix moved the bus')
        trip.refresh_from_db()
        self.assertEqual(trip.status, 'boarding')

        # The driver goes quiet for three minutes: the passenger sees the last position, marked stale.
        from drivers.models import Driver
        Driver.objects.filter(pk=driver.pk).update(
            location_updated_at=timezone.now() - dt.timedelta(minutes=3))
        quiet = self.live(passenger, booking)
        self.assertTrue(quiet['is_stale'])
        self.assertGreaterEqual(quiet['location_age_seconds'], 180)
        self.assertAlmostEqual(quiet['driver']['latitude'], accepted[0], places=5)

        # The signal returns: two fixes away from the stage start the trip and clear the stale flag.
        self.assertFalse(self.post_fix(driver, s1 + 0.004, s2, 4)['ignored'])
        self.assertFalse(self.post_fix(driver, s1 + 0.008, s2, 1)['ignored'])
        back = self.live(passenger, booking)
        self.assertFalse(back['is_stale'])
        self.assertAlmostEqual(back['driver']['latitude'], s1 + 0.008, places=5)
        trip.refresh_from_db()
        self.assertEqual(trip.status, 'departed')

    def test_a_fix_without_a_device_time_is_accepted_and_bad_input_is_refused(self):
        company, route, driver, trip, passenger, booking, stages = self._setup()
        s1, s2 = float(stages[0].latitude), float(stages[0].longitude)
        self.assertFalse(self.post_fix(driver, s1, s2)['ignored'])
        self.post_fix(driver, 95.0, s2, expect=400)
        self.post_fix(driver, s1, 'abc', expect=400)
        r = self.api(driver.account).post(
            reverse('drivers:driver-location', args=[driver.pk]),
            {'latitude': s1, 'longitude': s2, 'fix_at': '2026-01-01T10:00:00'}, format='json')
        self.assertEqual(r.status_code, 400, 'a fix time without a timezone must be refused')

    def test_only_the_trips_own_driver_can_post_its_position(self):
        company, route, driver, trip, passenger, booking, stages = self._setup()
        other_company = next(c for c in self.companies() if c.pk != company.pk)
        for who in (passenger, self.driver(company).account, self.driver(other_company).account,
                    self.staff(other_company, 'company_manager')):
            r = self.api(who).post(reverse('drivers:driver-location', args=[driver.pk]),
                                   {'latitude': -1.28, 'longitude': 36.82}, format='json')
            self.assertEqual(r.status_code, 403, f'{who.role}: {r.content}')

    def test_many_drivers_move_in_order_along_their_routes(self):
        fleet = []
        for ci, company in enumerate(self.companies()):
            for ri, route in enumerate(self.routes_of(company)[:2]):
                if not route.pickup_stages.exists():
                    self.add_stages(route, index=ci * 2 + ri)
                fleet.append((self.driver(company), route))
        for step in range(10):
            for driver, route in fleet:
                stage = route.pickup_stages.order_by('order').first()
                lat = float(stage.latitude) + 0.001 * step
                self.post_fix(driver, lat, float(stage.longitude), seconds_ago=100 - 10 * step)
        for driver, route in fleet:
            stage = route.pickup_stages.order_by('order').first()
            self.assertEqual(Driver_row(driver)[0], float(stage.latitude) + 0.009)


def Driver_row(driver):
    from drivers.models import Driver
    row = Driver.objects.get(pk=driver.pk)
    return (row.latitude, row.longitude, row.location_updated_at)
