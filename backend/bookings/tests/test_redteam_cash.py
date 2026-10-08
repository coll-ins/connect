from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()


class RedTeamCashTests(APITestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.co2 = Company.objects.create(name="B", description="d", areas_served="N")
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
        self.stranger = mk(username="str", password="x", phone_number="0711000002")
        self.mgr = mk(username="m1", password="x", phone_number="0711000003",
                      company=self.co, role="company_manager")
        self.mgr_b = mk(username="m2", password="x", phone_number="0711000004",
                        company=self.co2, role="company_manager")
        self.aud = mk(username="aud", password="x", phone_number="0711000005",
                      company=self.co, role="company_auditor")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")
        self.booking = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("100.00"), status="pending")
        self.payment = Payment.objects.create(
            booking=self.booking, amount=Decimal("100.00"), method="cash",
            status="pending")

    def _confirm(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(
            reverse("bookings:confirm-cash-payment", args=[self.booking.id]))

    def test_unauthorized_cannot_confirm(self):
        for label, u in (("anonymous", None), ("owner", self.owner),
                         ("stranger", self.stranger), ("other manager", self.mgr_b),
                         ("auditor", self.aud)):
            with self.subTest(attacker=label):
                self.assertIn(self._confirm(u).status_code, (401, 403))
        self.payment.refresh_from_db(); self.booking.refresh_from_db()
        self.assertEqual((self.payment.status, self.booking.status), ("pending", "pending"))

    def test_non_owner_cannot_initialize_cash(self):
        self.client.force_authenticate(user=self.stranger)
        r = self.client.post(reverse("bookings:initialize-cash-payment", args=[self.booking.id]))
        self.assertIn(r.status_code, (403, 404))

    def test_cancelled_booking_cannot_be_resurrected(self):
        for st in ("cancelled", "no_show", "completed"):
            with self.subTest(booking_status=st):
                Booking.objects.filter(pk=self.booking.pk).update(status=st)
                Payment.objects.filter(pk=self.payment.pk).update(status="pending")
                self.assertGreaterEqual(self._confirm(self.mgr).status_code, 400)
                self.booking.refresh_from_db()
                self.assertEqual(self.booking.status, st)

    def test_positive_and_idempotent(self):
        for u in (self.mgr, self.mgr):
            self.assertEqual(self._confirm(u).status_code, 200)
        self.booking.refresh_from_db(); self.payment.refresh_from_db()
        self.assertEqual((self.booking.status, self.payment.status), ("confirmed", "confirmed"))

    def test_driver_can_confirm(self):
        self.assertEqual(self._confirm(self.drv1).status_code, 200)
