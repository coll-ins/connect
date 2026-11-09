from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment
from companies.models import Company, Route, Trip
from drivers.models import Driver

User = get_user_model()


@override_settings(CASH_ENABLED=True)
class CashUnlockTests(APITestCase):
    """Cash is for proven riders: 30+ trips, 95%+ integrity, 60+ day account."""

    def setUp(self):
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(company=co, name="R", start_point="A", end_point="B", price=Decimal("100"))
        driver = Driver.objects.create(name="D", phone_number="+254700000030", bus_number="K0", company=co)
        trip = Trip.objects.create(route=route, driver=driver,
                                   departure_at=timezone.now() + timedelta(hours=2), capacity=10)
        self.user = User.objects.create_user(username="p", password="x", phone_number="+254711000222")
        User.objects.filter(pk=self.user.pk).update(date_joined=timezone.now() - timedelta(days=61))
        self.booking = Booking.objects.create(
            user=self.user, route=route, trip=trip, seats=1, total_amount=Decimal("100"), status="pending")
        self.client.force_authenticate(user=self.user)
        self.url = reverse("bookings:initialize-cash-payment", args=[self.booking.id])

    def _set(self, boarded, no_show, **extra):
        User.objects.filter(pk=self.user.pk).update(boarded_count=boarded, no_show_count=no_show, **extra)
        self.user.refresh_from_db()

    def test_new_passenger_must_pay_online(self):
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["code"], "cash_locked")
        self.assertFalse(Payment.objects.filter(booking=self.booking).exists())

    def test_proven_rider_unlocks_cash(self):
        self._set(29, 1)  # 96.7%
        self.assertEqual(self.client.post(self.url).status_code, 200)

    def test_two_no_shows_in_thirty_stays_locked(self):
        self._set(28, 2)  # 93.3%
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_too_few_trips_stays_locked(self):
        self._set(29, 0)
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_new_account_stays_locked_even_with_trips(self):
        self._set(40, 0, date_joined=timezone.now() - timedelta(days=10))
        self.assertEqual(self.client.post(self.url).status_code, 403)

    @override_settings(CASH_ENABLED=False)
    def test_cash_off_at_launch_even_for_proven_rider(self):
        self._set(40, 0)
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 403)
        self.assertIn("not available", r.json()["error"])


class CashPaidAtPinTests(APITestCase):
    """The driver's PIN check is the cash receipt: no separate confirm step."""

    def setUp(self):
        cache.clear()
        co = Company.objects.create(name="A", description="d", areas_served="N")
        route = Route.objects.create(company=co, name="R", start_point="A", end_point="B", price=Decimal("100"))
        driver = Driver.objects.create(name="D", phone_number="+254700000031", bus_number="K1", company=co)
        trip = Trip.objects.create(route=route, driver=driver, departure_at=timezone.now(),
                                   capacity=10, status="boarding")
        self.pax = User.objects.create_user(username="p", password="x", phone_number="+254711000333")
        self.booking = Booking.objects.create(
            user=self.pax, route=route, trip=trip, driver=driver, seats=1,
            total_amount=Decimal("100"), status="pending", verification_pin="482915")
        self.payment = Payment.objects.create(booking=self.booking, amount=Decimal("100"),
                                              method="cash", status="pending")
        self.manager = User.objects.create_user(username="m", password="x", phone_number="+254711000334",
                                                role="company_manager", company=co)
        self.client.force_authenticate(user=self.manager)
        self.url = reverse("bookings:verify-boarding", args=[self.booking.id])

    def test_correct_pin_boards_and_records_cash(self):
        r = self.client.post(self.url, {"boarding_pin": "482915"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["cash_collected"], "100.00")
        self.payment.refresh_from_db(); self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, "confirmed")
        self.assertIsNotNone(self.payment.confirmed_at)
        self.assertEqual(self.payment.settlement_status, "eligible")
        self.assertEqual(self.booking.status, "completed")

    def test_wrong_pin_records_nothing(self):
        r = self.client.post(self.url, {"boarding_pin": "000000"})
        self.assertEqual(r.status_code, 400)
        self.payment.refresh_from_db(); self.booking.refresh_from_db()
        self.assertEqual(self.payment.status, "pending")
        self.assertEqual(self.booking.status, "pending")

    def test_operator_cannot_take_cash(self):
        op = User.objects.create_user(username="o", password="x", phone_number="+254711000335",
                                      role="company_operator", company=self.manager.company)
        self.client.force_authenticate(user=op)
        r = self.client.post(self.url, {"boarding_pin": "482915"})
        self.assertEqual(r.status_code, 403)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "pending")

    def test_unboarded_cash_hold_counts_as_no_show(self):
        from django.db import transaction
        from bookings.services import settle_unboarded_no_shows
        with transaction.atomic():
            settle_unboarded_no_shows(self.booking.trip)
        self.booking.refresh_from_db(); self.payment.refresh_from_db(); self.pax.refresh_from_db()
        self.assertEqual(self.booking.status, "no_show")
        self.assertEqual(self.payment.status, "failed")
        self.assertEqual(self.pax.no_show_count, 1)
