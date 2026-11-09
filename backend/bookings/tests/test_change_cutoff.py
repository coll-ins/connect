from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


class ChangeCutoffTests(APITestCase):
    """15 minutes before departure: free cancel/move before, 50% and no move after."""

    def setUp(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(company=co, name="R", start_point="A", end_point="B", price=Decimal("200"))
        self.driver = Driver.objects.create(name="D", phone_number="+254700000040", bus_number="K4", company=co)
        self.pax = User.objects.create_user(username="p", password="x", phone_number="+254711000444")
        self.client.force_authenticate(user=self.pax)

    def _trip(self, minutes):
        return Trip.objects.create(route=self.route, driver=self.driver, capacity=14,
                                   departure_at=timezone.now() + timedelta(minutes=minutes))

    def _booking(self, trip):
        b = Booking.objects.create(user=self.pax, route=self.route, trip=trip, driver=self.driver,
                                   seats=1, total_amount=Decimal("200"), status="confirmed")
        # Cash needs no Paystack call, so the refund amount shows directly.
        Payment.objects.create(booking=b, amount=Decimal("200"), method="cash", status="confirmed")
        return b

    def _cancel(self, b):
        return self.client.post(reverse("bookings:cancel-booking", args=[b.id]), {}, format="json")

    def test_cancel_before_cutoff_is_full_refund(self):
        r = self._cancel(self._booking(self._trip(60)))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["refund_amount"], "200.00")
        self.assertTrue(r.json()["free_cancellation"])

    def test_cancel_inside_cutoff_is_half(self):
        r = self._cancel(self._booking(self._trip(10)))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["refund_amount"], "100.00")
        self.assertFalse(r.json()["free_cancellation"])

    def test_passenger_moves_own_booking_before_cutoff(self):
        b = self._booking(self._trip(60))
        later = self._trip(120)
        r = self.client.post(reverse("bookings:move-booking-to-trip", args=[b.id]), {"trip_id": later.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        b.refresh_from_db()
        self.assertEqual(b.trip_id, later.id)

    def test_passenger_cannot_move_inside_cutoff(self):
        b = self._booking(self._trip(10))
        later = self._trip(120)
        r = self.client.post(reverse("bookings:move-booking-to-trip", args=[b.id]), {"trip_id": later.id}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["code"], "change_cutoff")

    def test_stranger_cannot_move_someone_elses_booking(self):
        b = self._booking(self._trip(60))
        later = self._trip(120)
        other = User.objects.create_user(username="o", password="x", phone_number="+254711000445")
        self.client.force_authenticate(user=other)
        r = self.client.post(reverse("bookings:move-booking-to-trip", args=[b.id]), {"trip_id": later.id}, format="json")
        self.assertEqual(r.status_code, 403)
