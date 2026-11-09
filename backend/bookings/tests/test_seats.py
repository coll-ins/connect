import random
from datetime import timedelta
from unittest import mock
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, SeatAssignment
from bookings.seats import VEHICLES, layout_for
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


def _nums(rows):
    return sorted(x for row in rows for x in row if isinstance(x, int))


class LayoutTests(APITestCase):
    def test_every_plan_numbers_each_seat_once_in_even_rows(self):
        for key, v in VEHICLES.items():
            self.assertEqual(_nums(v['layout']), list(range(1, v['seats'] + 1)), key)
            self.assertEqual(len({len(r) for r in v['layout']}), 1, key)
            self.assertEqual(sum(r.count('D') for r in v['layout']), 1, key)
        for cap in (10, 3, 36, 62):
            self.assertEqual(_nums(layout_for(cap)), list(range(1, cap + 1)), cap)

    def test_published_plans(self):
        # Toyota HiAce Commuter No. 6, mirrored for right-hand drive.
        hiace = layout_for(14, 'matatu_14')
        self.assertEqual(hiace[0], [1, 2, None, 'D'])
        self.assertEqual(hiace[1], ['door', 3, 4, 5])
        self.assertEqual(hiace[2:], [[6, None, 7, 8], [9, None, 10, 11], [12, None, 13, 14]])
        # ACMG drawings: seat numbers exactly as printed.
        nmr = layout_for(27, 'minibus_27')
        self.assertEqual((nmr[0], nmr[2], nmr[-1]),
                         ([2, 1, None, None, 'D'], ['door', 'door', None, 8, 7], [27, 26, 25, 24, 23]))
        ftr = layout_for(51, 'bus_51')
        self.assertEqual((ftr[1], ftr[3], ftr[-1]),
                         ([4, 3, None, 7, 6, 5], [15, 14, None, 13, 12, 11], [51, 50, 49, 48, 47, 46]))
        fvr = layout_for(67, 'bus_67')
        self.assertEqual((fvr[0], fvr[2], fvr[4], fvr[-2], fvr[-1]),
                         ([1, None, None, None, None, 'D'], [4, 5, None, 8, 7, 6],
                          [12, 13, None, 14, 15, 16], [57, 58, None, 59, 60, 61], [62, 63, 64, 65, 66, 67]))

    def test_seat_count_picks_only_an_exact_plan(self):
        self.assertIs(layout_for(51), VEHICLES['bus_51']['layout'])
        # 33 has only an approximate plan: a bare count must not claim it.
        self.assertIsNot(layout_for(33), VEHICLES['minibus_33']['layout'])
        self.assertIs(layout_for(33, 'minibus_33'), VEHICLES['minibus_33']['layout'])
        self.assertIsNot(layout_for(51, 'other'), VEHICLES['bus_51']['layout'])


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

    def test_without_numbers_random_free_seats_are_given(self):
        self._book(self.pax, 10, list(range(1, 11)))
        Booking.objects.filter(user=self.pax).update(status="confirmed")  # paid, so off the unpaid-seat cap
        self._book(self.pax, 3, [11, 12, 13])
        with mock.patch("bookings.seats.random.sample", wraps=random.sample) as pick:
            r = self._book(self.other, 1)
        self.assertEqual(r.json()["seat_numbers"], [14])  # the only free seat
        pick.assert_called_once_with([14], 1)

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
