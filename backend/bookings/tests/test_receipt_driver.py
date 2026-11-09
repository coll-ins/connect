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


class ReceiptDriverTests(APITestCase):
    def setUp(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B", price=Decimal("100.00"))
        self.driver = Driver.objects.create(
            name="Peter Kamau", phone_number="+254700000009", bus_number="KDH 112E", company=co)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver,
            departure_at=timezone.now() + timedelta(hours=1), capacity=10, status="scheduled")
        self.user = User.objects.create_user(
            username="p", password="x", phone_number="+254711000111")
        self.client.force_authenticate(user=self.user)

    def _book(self, status, method="digital", pay_status="confirmed"):
        b = Booking.objects.create(
            user=self.user, route=self.route, trip=self.trip, seats=1,
            total_amount=Decimal("100.00"), status=status)
        Payment.objects.create(booking=b, amount=Decimal("100.00"), method=method, status=pay_status)
        return b

    def _driver_of(self, booking):
        rows = self.client.get(reverse("bookings:passenger-records")).json()
        return next(r for r in rows if r["booking_id"] == booking.id)["driver"]

    def test_paid_trip_shows_driver_name_bus_and_phone(self):
        d = self._driver_of(self._book("confirmed"))
        self.assertEqual(d, {"name": "Peter Kamau", "phone_number": "+254700000009", "bus_number": "KDH 112E"})

    def test_cancelled_trip_hides_driver_phone(self):
        d = self._driver_of(self._book("cancelled", pay_status="failed"))
        self.assertEqual(d["name"], "Peter Kamau")
        self.assertIsNone(d["phone_number"])
