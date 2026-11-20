import datetime as dt

from django.utils import timezone

from bookings.tests.test_seat_holds import SeatBase
from connect.system_checks import run_system_checks


def capacity_check():
    return next(c for c in run_system_checks()['checks'] if c['name'] == 'Trip capacity')


class TripCapacityCheckTests(SeatBase):
    capacity = 3

    def test_an_expired_hold_does_not_count_as_over_capacity(self):
        self.booking(seats=2, status='confirmed')
        self.booking(seats=3, status='pending',
                     held_until=timezone.now() - dt.timedelta(minutes=1))
        check = capacity_check()
        self.assertEqual((check['status'], check['count']), ('passed', 0))

    def test_a_live_hold_and_a_completed_booking_count(self):
        self.booking(seats=2, status='completed')
        self.booking(seats=2, status='pending',
                     held_until=timezone.now() + dt.timedelta(minutes=5))
        check = capacity_check()
        self.assertEqual(check['status'], 'failed')
        self.assertEqual(check['records'], [
            {'trip_id': self.trip.id, 'booked_seats': 4, 'capacity': 3}])
