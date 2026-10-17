import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Payment, Payout
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
REF = "ref-partial-1"


class RefundThenSettleTests(TestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=self.co, name="R", start_point="A", end_point="B",
            price=Decimal("800.00"))
        self.stage = PickupStage.objects.create(
            route=self.route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        self.d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=self.co)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.d1,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        owner = User.objects.create_user(
            username="own", password="x", phone_number="0711000001")
        self.booking = Booking.objects.create(
            user=owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("800.00"), status="confirmed")
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal("800.00"), method="digital",
            status="confirmed", provider_reference=REF,
            settlement_status="not_ready", refund_status="processing",
            refund_amount=Decimal("400.00"))

    def _refund_webhook(self):
        body = json.dumps({
            "event": "refund.processed",
            "data": {"transaction_reference": REF, "refund_reference": "rf-1"},
        })
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body.encode(),
                       hashlib.sha512).hexdigest()
        return self.client.post(
            reverse("bookings:paystack-refund-webhook"), data=body,
            content_type="application/json", HTTP_X_PAYSTACK_SIGNATURE=sig)

    def _settle(self):
        call_command("settle_company", self.co.id, "--apply",
                     "--reference", "T1", stdout=StringIO())

    def test_partial_refund_still_pays_company_the_remainder(self):
        self.assertEqual(self._refund_webhook().status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "confirmed")
        self.assertEqual(self.payment.refund_status, "processed")

        self._settle()
        payout = Payout.objects.get()
        fee = settings.PLATFORM_FEE_PER_SEAT * 1
        self.assertEqual(payout.gross_amount, Decimal("400.00"))
        self.assertEqual(payout.net_amount, Decimal("400.00") - fee)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payout_id, payout.id)

        self._settle()                       # a second run must not pay again
        self.assertEqual(Payout.objects.count(), 1)

    def test_duplicate_webhook_changes_nothing(self):
        self._refund_webhook()
        self._refund_webhook()
        self.payment.refresh_from_db()
        self.assertEqual((self.payment.status, self.payment.refund_status),
                         ("confirmed", "processed"))

    def test_full_refund_closes_payment_and_pays_nothing(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            refund_amount=Decimal("800.00"))
        self._refund_webhook()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "refunded")
        self._settle()
        self.assertEqual(Payout.objects.count(), 0)
