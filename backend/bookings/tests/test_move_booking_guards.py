"""move_booking_to_trip: the target must be open by the clock, and the old trip must still be the booking's."""
import datetime as dt
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from bookings.models import Booking
from bookings.tests.review_base import WorldMixin
from companies.models import Trip


class MoveBookingGuardTests(WorldMixin, TestCase):
    def test_move_onto_a_trip_that_already_left_by_the_clock_is_refused(self):
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        gone = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                   departure_at=timezone.now() - dt.timedelta(minutes=30))
        r = self.api(self.mgr).post(f'/api/bookings/{b.id}/move-trip/', {'trip_id': gone.id}, format='json')
        self.assertEqual(r.status_code, 409, r.content[:200])
        b.refresh_from_db()
        self.assertEqual(b.trip_id, self.trip1.id)

    def test_move_onto_an_open_trip_still_works(self):
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        ok = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                 departure_at=timezone.now() + dt.timedelta(hours=3))
        r = self.api(self.mgr).post(f'/api/bookings/{b.id}/move-trip/', {'trip_id': ok.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        b.refresh_from_db()
        self.assertEqual(b.trip_id, ok.id)

    def test_a_booking_that_changed_trips_after_the_unlocked_read_is_not_moved(self):
        b = self.booking(self.pax, self.trip1, 1, 'confirmed')
        elsewhere = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                        departure_at=timezone.now() + dt.timedelta(hours=2))
        target = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                     departure_at=timezone.now() + dt.timedelta(hours=4))
        real_lock = Booking.objects.select_for_update

        def lock_after_a_competing_move(*args, **kwargs):
            # Another request moved the booking between the read and the lock.
            Booking.objects.filter(pk=b.pk).update(trip=elsewhere)
            return real_lock(*args, **kwargs)

        with mock.patch.object(Booking.objects, 'select_for_update', lock_after_a_competing_move):
            r = self.api(self.mgr).post(f'/api/bookings/{b.id}/move-trip/', {'trip_id': target.id}, format='json')
        self.assertEqual(r.status_code, 409, r.content[:200])
        b.refresh_from_db()
        self.assertEqual(b.trip_id, elsewhere.id)

    def test_move_with_a_huge_or_negative_trip_id_is_a_client_error(self):
        b = self.booking(self.pax, self.trip1)
        for tid in (10 ** 30, -1, '9' * 40):
            r = self.api(self.mgr).post(f'/api/bookings/{b.id}/move-trip/', {'trip_id': tid}, format='json')
            self.assertEqual(r.status_code, 400, (tid, r.status_code))
