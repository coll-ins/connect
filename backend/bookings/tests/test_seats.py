from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, SeatAssignment
from bookings.seats import layout_for
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class LayoutTests(APITestCase):
    def test_every_layout_numbers_each_seat_once(self):
        for cap in (14, 29, 33, 51, 62, 10, 3):
            nums = [x for row in layout_for(cap) for x in row if isinstance(x, int)]
            self.assertEqual(nums, list(range(1, cap + 1)), cap)

    def test_matatu_is_a_real_hiace(self):
        rows = layout_for(14)
        self.assertEqual(rows[0], [None, 1, 2, 'D'])      # 2 beside the driver, front right
        self.assertEqual(rows[1], ['door', 3, 4, 5])      # sliding door on the left by row 2
        self.assertEqual(rows[-1], [None, 12, 13, 14])    # back bench of 3

    def test_bus_has_front_left_door_and_back_bench_of_five(self):
        for cap in (29, 33, 51):
            rows = layout_for(cap)
            self.assertEqual(rows[0], ['door', None, None, None, 'D'])
            self.assertEqual(len(rows[-1]), 5)
            self.assertTrue(all(isinstance(x, int) for x in rows[-1]))
        self.assertEqual(layout_for(51)[1], ['door', None, None, 1, 2])  # 2 behind the driver


class SeatBookingTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(company=self.co, name="R", start_point="A", end_point="B", price=Decimal("100"))
        self.driver = Driver.objects.create(name="Peter K", phone_number="+254700000050", bus_number="K5", company=self.co)
        self.trip = self._trip()
        self.pax = User.objects.create_user(username="p1", password="x", phone_number="+254711000501", first_name="Amina")
        self.other = User.objects.create_user(username="p2", password="x", phone_number="+254711000502")
        self.op = User.objects.create_user(username="op", password="x", phone_number="+254711000503",
                                           role="company_operator", company=self.co)

    def _trip(self, capacity=14):
        return Trip.objects.create(route=self.route, driver=self.driver, capacity=capacity,
                                   departure_at=timezone.now() + timedelta(hours=2))

    def _book(self, user, seats=1, numbers=None, trip=None):
        self.client.force_authenticate(user=user)
        body = {"trip_id": (trip or self.trip).id, "seats": seats, "pickup_location": "CBD"}
        if numbers is not None:
            body["seat_numbers"] = numbers
        return self.client.post(reverse("bookings:create-booking"), body, format="json")

    def _map(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(reverse("bookings:trip-seat-map", args=[self.trip.id])).json()

    def test_picked_seats_are_given(self):
        r = self._book(self.pax, 2, [7, 8])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["seat_numbers"], [7, 8])

    def test_without_numbers_lowest_free_seats_are_given(self):
        self._book(self.pax, 1, [1])
        r = self._book(self.other, 2)
        self.assertEqual(r.json()["seat_numbers"], [2, 3])

    def test_same_seat_twice_is_refused_and_nothing_is_saved(self):
        self._book(self.pax, 1, [5])
        r = self._book(self.other, 1, [5])
        self.assertEqual(r.status_code, 409)
        self.assertFalse(Booking.objects.filter(user=self.other).exists())

    def test_wrong_count_or_bad_seat_refused(self):
        self.assertEqual(self._book(self.pax, 2, [3]).status_code, 409)
        self.assertEqual(self._book(self.pax, 1, [15]).status_code, 409)

    def test_cancelled_booking_frees_its_seat(self):
        b = Booking.objects.get(pk=self._book(self.pax, 1, [4]).json()["booking_id"])
        Booking.objects.filter(pk=b.pk).update(status="cancelled")
        self.assertEqual(self._book(self.other, 1, [4]).status_code, 201)

    def test_passenger_map_has_no_names_but_marks_own_seat(self):
        self._book(self.pax, 1, [3])
        self._book(self.other, 1, [6])
        seats = {s["no"]: s for s in self._map(self.pax)["seats"]}
        self.assertTrue(seats[3]["mine"])
        self.assertFalse(seats[6]["mine"])
        self.assertNotIn("passenger", seats[6])
        self.assertEqual(seats[1]["state"], "free")

    def test_operator_sees_names_and_can_block(self):
        self._book(self.pax, 1, [3])
        seats = {s["no"]: s for s in self._map(self.op)["seats"]}
        self.assertEqual(seats[3]["passenger"], "Amina")
        r = self.client.post(reverse("bookings:trip-seat-block", args=[self.trip.id, 9]), {"note": "walk-in"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._book(self.other, 1, [9]).status_code, 409)
        self.client.force_authenticate(user=self.op)
        self.client.delete(reverse("bookings:trip-seat-block", args=[self.trip.id, 9]))
        self.assertEqual(self._book(self.other, 1, [9]).status_code, 201)

    def test_blocked_seats_reduce_capacity(self):
        small = self._trip(capacity=2)
        self.client.force_authenticate(user=self.op)
        self.client.post(reverse("bookings:trip-seat-block", args=[small.id, 1]), {}, format="json")
        self.assertEqual(self._book(self.pax, 2, trip=small).status_code, 400)

    def test_passenger_cannot_block(self):
        self.client.force_authenticate(user=self.pax)
        r = self.client.post(reverse("bookings:trip-seat-block", args=[self.trip.id, 9]), {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertFalse(SeatAssignment.objects.filter(blocked=True).exists())

    def test_moving_bus_keeps_seat_number_when_free(self):
        bid = self._book(self.pax, 1, [6]).json()["booking_id"]
        later = self._trip()
        self.client.force_authenticate(user=self.pax)
        r = self.client.post(reverse("bookings:move-booking-to-trip", args=[bid]), {"trip_id": later.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(list(SeatAssignment.objects.filter(booking_id=bid).values_list("trip_id", "seat_no")),
                         [(later.id, 6)])

    def test_block_note_hidden_from_passengers(self):
        self.client.force_authenticate(user=self.op)
        self.client.post(reverse("bookings:trip-seat-block", args=[self.trip.id, 9]), {"note": "VIP mama"}, format="json")
        seats = {s["no"]: s for s in self._map(self.pax)["seats"]}
        self.assertEqual(seats[9]["state"], "blocked")
        self.assertNotIn("note", seats[9])

    def test_seat_numbers_must_be_a_list(self):
        from bookings.seats import SeatError, assign_seats
        b = Booking.objects.create(user=self.pax, route=self.route, trip=self.trip, seats=2,
                                   total_amount=Decimal("200"), status="pending")
        with self.assertRaises(SeatError):
            assign_seats(self.trip, b, "12")
