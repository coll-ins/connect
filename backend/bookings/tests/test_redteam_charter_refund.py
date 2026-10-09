from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from bookings.models import UnappliedPayment
from charters.models import CharterRequest
from companies.models import Company

User = get_user_model()
REF = "CHT-1-TESTREF"


class RefundCharterCommandTests(TestCase):
    def setUp(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        self.passenger = User.objects.create_user(
            username="pax", password="x", phone_number="+254711000002")
        self.charter = CharterRequest.objects.create(
            passenger=self.passenger, company=co, purpose="Wedding",
            pickup_location="A", destination="B",
            depart_at=timezone.now() + timedelta(days=3), passenger_count=40,
            contact_name="N", contact_phone="0700000000", status="confirmed",
            quote_price=Decimal("50000.00"), provider_reference=REF,
            paid_at=timezone.now())

    def _run(self, *extra):
        call_command("refund_charter", self.charter.reference,
                     "--reason", "customer asked", *extra, stdout=StringIO())

    def test_queues_full_refund_and_cancels(self):
        with patch("requests.post") as post:
            self._run()
        post.assert_not_called()
        self.charter.refresh_from_db()
        self.assertEqual(self.charter.status, "cancelled")
        self.assertIsNotNone(self.charter.cancelled_at)
        row = UnappliedPayment.objects.get(reference=REF)
        self.assertEqual((row.kind, row.status, row.amount, row.currency),
                         ("charter", "refund_due", Decimal("50000.00"), "KES"))

    def test_second_run_is_refused(self):
        self._run()
        with self.assertRaises(CommandError):
            self._run()
        self.assertEqual(UnappliedPayment.objects.count(), 1)

    def test_only_confirmed_hires(self):
        for st in ("requested", "quoted", "completed", "declined", "cancelled"):
            CharterRequest.objects.filter(pk=self.charter.pk).update(status=st)
            with self.assertRaises(CommandError):
                self._run()
        self.assertFalse(UnappliedPayment.objects.exists())

    def test_after_departure_needs_force(self):
        CharterRequest.objects.filter(pk=self.charter.pk).update(
            depart_at=timezone.now() - timedelta(hours=1))
        with self.assertRaises(CommandError):
            self._run()
        self.assertFalse(UnappliedPayment.objects.exists())
        self._run("--force")
        self.assertTrue(UnappliedPayment.objects.filter(reference=REF).exists())

    def test_refuses_without_payment_reference(self):
        CharterRequest.objects.filter(pk=self.charter.pk).update(provider_reference=None)
        with self.assertRaises(CommandError):
            self._run()

    def test_refuses_when_refund_row_exists(self):
        UnappliedPayment.objects.create(
            reference=REF, kind="charter", amount=Decimal("50000.00"), status="refunded")
        with self.assertRaises(CommandError):
            self._run()
        self.charter.refresh_from_db()
        self.assertEqual(self.charter.status, "confirmed")

    def test_unknown_reference(self):
        with self.assertRaises(CommandError):
            call_command("refund_charter", "NOPE", "--reason", "x", stdout=StringIO())
