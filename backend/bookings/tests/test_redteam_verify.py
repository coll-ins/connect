from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
REF = "ref-verify-1"


def _paystack_success():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "status": True,
        "data": {"status": "success", "amount": 80000, "currency": "KES"}}
    return resp


class RedTeamVerifyTests(APITestCase):
    def setUp(self):
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
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        self.owner = User.objects.create_user(
            username="own", password="x", phone_number="0711000001")
        self.booking = Booking.objects.create(
            user=self.owner, route=route, trip=trip, driver=d1,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="cancelled")
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal("800.00"), method="digital",
            status="pending", provider_reference=REF)
        self.client.force_authenticate(user=self.owner)

    def test_late_payment_found_by_status_poll_is_refunded(self):
        with patch("bookings.views.requests.get", return_value=_paystack_success()), \
             patch("bookings.views.settle_booking_fault") as refund:
            r = self.client.get(
                reverse("bookings:payment-status", args=[self.booking.id]))
        self.assertEqual(r.status_code, 200)
        refund.assert_called_once()
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "cancelled")

    def test_verify_cannot_revive_a_refunded_payment(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            status="refunded", settlement_status="refunded",
            refund_status="processed", refund_amount=Decimal("800.00"))
        with patch("bookings.views.requests.get", return_value=_paystack_success()), \
             patch("bookings.views.settle_booking_fault") as refund:
            self.client.post(
                reverse("bookings:verify-paystack-payment", args=[self.booking.id]))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "refunded")
        refund.assert_not_called()

    def test_create_booking_rejects_bad_seat_counts(self):
        trip = Trip.objects.get()
        url = reverse("bookings:create-booking")
        for seats in (0, -1, -5, 10 ** 6, "abc", None):
            with self.subTest(seats=seats):
                r = self.client.post(
                    url, {"trip_id": trip.id, "seats": seats}, format="json")
                self.assertEqual(r.status_code, 400)
