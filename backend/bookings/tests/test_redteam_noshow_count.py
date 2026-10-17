from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from bookings.models import Booking
from bookings.services import settle_unboarded_no_shows
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class NoShowCountTests(TestCase):
    def test_two_bookings_by_one_user_count_twice(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(
            company=co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        stage = PickupStage.objects.create(
            route=route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=co)
        trip = Trip.objects.create(
            route=route, driver=d1,
            departure_at=timezone.now() - timedelta(hours=1),
            capacity=10, status="departed")
        user = User.objects.create_user(
            username="own", password="x", phone_number="+254711000001")
        for _ in range(2):
            Booking.objects.create(
                user=user, route=route, trip=trip, driver=d1, pickup_stage=stage,
                pickup_location="S1", seats=1, total_amount=Decimal("800.00"),
                status="confirmed")
        with transaction.atomic(), patch(
                "bookings.services.claim_booking_refund", return_value=(None, None)):
            settled, protected = settle_unboarded_no_shows(trip, claims=[])
        self.assertEqual((settled, protected), (2, 0))
        user.refresh_from_db()
        self.assertEqual(user.no_show_count, 2)
