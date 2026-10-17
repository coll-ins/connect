from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
PIN = "482913"


class RedTeamQrBoardingTests(APITestCase):
    def setUp(self):
        cache.clear()
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        stage = PickupStage.objects.create(
            route=route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        driver = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=co)
        trip = Trip.objects.create(
            route=route, driver=driver,
            departure_at=timezone.now() - timedelta(minutes=5),
            capacity=10, status="boarding")
        owner = User.objects.create_user(
            username="own", password="x", phone_number="+254711000001")
        self.booking = Booking.objects.create(
            user=owner, route=route, trip=trip, driver=driver,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="confirmed",
            verification_pin=PIN)
        Payment.objects.create(
            booking=self.booking, amount=Decimal("800.00"),
            method="cash", status="confirmed")
        driver_user = User.objects.create_user(
            username="drv", password="x", phone_number="+254700000001")
        self.client.force_authenticate(user=driver_user)
        patcher = patch("bookings.views.is_driver_account_for", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        throttle = patch(
            "bookings.views.BoardingVerifyThrottle.allow_request", return_value=True)
        throttle.start()
        self.addCleanup(throttle.stop)
        self.url = reverse("bookings:verify-boarding", args=[self.booking.id])
        self.number = self.booking.booking_number

    def _post(self, **data):
        return self.client.post(self.url, data, format="json")

    def _boarded(self):
        return BoardingEvent.objects.filter(booking=self.booking).exists()

    def test_bare_booking_number_is_refused(self):
        self.assertEqual(self._post(qr_data=self.number).status_code, 400)
        self.assertFalse(self._boarded())

    def test_number_with_correct_pin_boards(self):
        self.assertEqual(self._post(qr_data=f"{self.number}:{PIN}").status_code, 200)
        self.assertEqual(BoardingEvent.objects.get(booking=self.booking).method, "qr")

    def test_number_with_wrong_pin_is_refused(self):
        self.assertEqual(self._post(qr_data=f"{self.number}:000000").status_code, 400)
        self.assertFalse(self._boarded())

    def test_wrong_scans_lock_both_paths(self):
        for i in range(5):
            self.assertEqual(
                self._post(qr_data=f"{self.number}:00000{i}").status_code, 400)
        self.assertEqual(self._post(qr_data=f"{self.number}:{PIN}").status_code, 429)
        self.assertEqual(self._post(boarding_pin=PIN).status_code, 429)
        self.assertFalse(self._boarded())

    def test_wrong_pins_lock_both_paths(self):
        for i in range(5):
            self.assertEqual(self._post(boarding_pin=f"00000{i}").status_code, 400)
        self.assertEqual(self._post(boarding_pin=PIN).status_code, 429)
        self.assertEqual(self._post(qr_data=f"{self.number}:{PIN}").status_code, 429)
        self.assertFalse(self._boarded())

    def test_four_wrong_pins_do_not_lock(self):
        for i in range(4):
            self.assertEqual(self._post(boarding_pin=f"00000{i}").status_code, 400)
        self.assertEqual(self._post(boarding_pin=PIN).status_code, 200)
        self.assertTrue(self._boarded())
