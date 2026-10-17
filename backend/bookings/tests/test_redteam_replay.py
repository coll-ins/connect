import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
REF = "ref-replay-1"


class ReplayAfterRefundTests(TestCase):
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
        owner = User.objects.create_user(
            username="own", password="x", phone_number="0711000001")
        self.booking = Booking.objects.create(
            user=owner, route=route, trip=trip, driver=d1,
            pickup_stage=stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="cancelled")
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal("800.00"), method="digital",
            status="refunded", provider_reference=REF,
            settlement_status="refunded", refund_status="processed",
            refund_amount=Decimal("800.00"))

    def test_duplicate_charge_success_does_not_revive_a_refunded_payment(self):
        body = json.dumps({"event": "charge.success", "data": {
            "reference": REF, "amount": 80000, "currency": "KES"}})
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body.encode(),
                       hashlib.sha512).hexdigest()
        with patch("bookings.views.settle_booking_fault") as refund:
            r = self.client.post(
                reverse("bookings:paystack-webhook"), data=body,
                content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(r.status_code, 200)
        self.payment.refresh_from_db(); self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, "refunded")
        self.assertEqual(self.booking.status, "cancelled")
        refund.assert_not_called()
