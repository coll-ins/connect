from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import BoardingEvent, Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class RedTeamTripStateTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=self.co, name="R", start_point="A", end_point="B",
            price=Decimal("100.00"))
        self.stage = PickupStage.objects.create(
            route=self.route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        self.d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=self.co)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.d1,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        mk = User.objects.create_user
        self.owner = mk(username="own", password="x", phone_number="0711000001")
        self.other = mk(username="oth", password="x", phone_number="0711000002")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")

    def _booking_for_boarding(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            status="boarding", departure_at=timezone.now() - timedelta(minutes=5))
        b = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("100.00"), status="confirmed")
        Booking.objects.filter(pk=b.pk).update(verification_pin="1234")
        Payment.objects.create(booking=b, amount=Decimal("100.00"), method="digital",
                               status="confirmed", provider_reference="RT_BOARD")
        return b

    def _board(self, booking):
        self.client.force_authenticate(user=self.drv1)
        return self.client.post(
            reverse("bookings:verify-boarding", args=[booking.id]),
            {"boarding_pin": "1234"}, format="json")

    def _create(self, user, seats=1):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse("bookings:create-booking"),
            {"trip_id": self.trip.id, "seats": seats,
             "pickup_stage_id": self.stage.id}, format="json")

    def test_retry_boarding_never_duplicates(self):
        b = self._booking_for_boarding()
        self.assertEqual(self._board(b).status_code, 200)
        self.assertEqual(self._board(b).status_code, 400)
        self.assertEqual(BoardingEvent.objects.filter(booking=b).count(), 1)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.boarded_count, 1)

    def test_cannot_book_completed_or_departed_trip(self):
        # "boarding" is bookable at the first stage only; that behaviour is
        # covered in test_boarding_stage_flow.py.
        for st in ("completed", "departed", "cancelled"):
            with self.subTest(trip_status=st):
                Trip.objects.filter(pk=self.trip.pk).update(status=st)
                self.assertEqual(self._create(self.other).status_code, 400)
        self.assertFalse(Booking.objects.filter(user=self.other).exists())

    def test_cannot_book_scheduled_trip_past_departure(self):
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self._create(self.other).status_code, 400)

    def test_cannot_overbook(self):
        self.assertEqual(self._create(self.other, seats=11).status_code, 400)

    def test_positive_control_booking_works(self):
        self.assertIn(self._create(self.other).status_code, (200, 201))
