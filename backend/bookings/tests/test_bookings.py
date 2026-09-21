import hashlib
import hmac
import json
import threading
import unittest
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.urls import reverse
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, Payment, BoardingEvent
from companies.models import Company, Route, Trip
from drivers.models import Driver
from wallets.models import Wallet

User = get_user_model()


class BookingsAppTests(APITestCase):

    def setUp(self):
        self.company = Company.objects.create(name="Express Line")
        self.passenger = User.objects.create_user(
            username="passenger_user",
            password="password123",
            phone_number="+254700000001",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="John Doe",
            phone_number="+254711111111",
            bus_number="KAA 000A",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Nairobi - Nakuru",
            price=Decimal("800.00"),
        )
        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=1,
        )
        self.wallet = Wallet.objects.create(
            user=self.passenger,
            available_balance=Decimal("2000.00"),
            held_balance=Decimal("0.00"),
        )
        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            booking_number="BK9999",
            total_amount=Decimal("800.00"),
            status="confirmed",
        )

    def _resolve_url(self, primary_name, fallback_name, kwargs=None):
        try:
            return reverse(primary_name, kwargs=kwargs)
        except Exception:
            return reverse(fallback_name, kwargs=kwargs)

    def test_list_user_bookings(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:get-my-bookings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_booking_insufficient_balance(self):
        self.client.force_authenticate(user=self.passenger)
        self.wallet.available_balance = Decimal("100.00")
        self.wallet.save()

        url = reverse("bookings:create-booking")
        payload = {"trip_id": self.trip.id, "route_id": self.route.id, "seats": 1}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_all_bookings_admin_or_passenger(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:get-all-bookings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_specific_booking(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:get-booking-detail", kwargs={"booking_id": self.booking.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["booking_number"], "BK9999")

    def test_cancel_booking(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:cancel-booking", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    @patch("bookings.views.requests.post")
    def test_initialize_paystack_payment_success(self, mock_post):
        self.client.force_authenticate(user=self.passenger)

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "reference": "REF123456789",
            },
        }

        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["reference"], "REF123456789")

    def test_paystack_webhook_valid_charge_success(self):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="REF999999",
            amount=self.booking.total_amount,
            method="digital",
            status="pending",
        )

        payload = {
            "event": "charge.success",
            "data": {
                "reference": "REF999999",
                "amount": int(self.booking.total_amount * Decimal("100")),
            },
        }
        body = json.dumps(payload).encode("utf-8")

        computed_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()

        url = "/api/bookings/webhooks/paystack/"
        response = self.client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=computed_signature,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "confirmed")

    def test_confirm_cash_payment_by_staff(self):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH123",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        admin_user = User.objects.create_superuser(username="admin", password="password")
        self.client.force_authenticate(user=admin_user)

        url = reverse("bookings:confirm-cash-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "confirmed")

    def test_assign_driver_by_staff(self):
        admin_user = User.objects.create_superuser(username="admin_driver", password="password")
        self.client.force_authenticate(user=admin_user)

        url = reverse("bookings:assign-driver", kwargs={"booking_id": self.booking.id})
        payload = {"driver_id": self.driver.id}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.booking.trip.refresh_from_db()
        self.assertEqual(self.booking.trip.driver, self.driver)

    def test_verify_boarding_by_staff(self):
        operator_user = User.objects.create_user(
            username="operator_user",
            password="password123"
        )

        self.company.user = operator_user
        self.company.save()

        self.booking.status = "confirmed"
        self.booking.verification_pin = "1234"
        self.booking.save()

        Payment.objects.create(
            booking=self.booking,
            provider_reference="PAY123456",
            amount=self.booking.total_amount,
            method="digital",
            status="confirmed",
        )

        admin_user = User.objects.create_superuser(
            username="admin_board",
            password="password"
        )

        self.client.force_authenticate(user=admin_user)

        url = reverse(
            "bookings:verify-boarding",
            kwargs={"booking_id": self.booking.id}
        )

        response = self.client.post(
            url,
            {"boarding_pin": "1234"}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.booking.refresh_from_db()
        payment = Payment.objects.get(booking=self.booking)

        self.assertEqual(self.booking.status, "completed")
        self.assertEqual(payment.status, "confirmed")
        self.assertEqual(payment.settlement_status, "eligible")

        self.assertTrue(
            BoardingEvent.objects.filter(
                booking=self.booking
            ).exists()
        )

        self.booking.user.refresh_from_db()
        self.assertEqual(self.booking.user.boarded_count, 1)

    def test_update_passenger_location(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:update-passenger-location", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url, {"latitude": -1.2921, "longitude": 36.8219}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_set_stage_departure_staff(self):
        admin_user = User.objects.create_superuser(username="admin_stage", password="password")
        self.client.force_authenticate(user=admin_user)
        url = reverse("bookings:set-stage-departure", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url, {"minutes": 15}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cancel_booking_company_fault(self):
        staff_user = User.objects.create_user(
            username="admin_staff",
            password="password123",
            is_staff=True,
        )
        self.client.force_authenticate(user=staff_user)

        wallet, _ = Wallet.objects.get_or_create(user=self.booking.user)
        wallet.held_balance = self.booking.total_amount
        wallet.save(update_fields=["held_balance"])

        Payment.objects.create(
            booking=self.booking,
            provider_reference="REF_CANCEL",
            amount=self.booking.total_amount,
            method="cash",
            status="confirmed",
        )

        url = reverse("bookings:cancel-booking", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url, {"fault_party": "company"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_resolve_url_fallback(self):
        resolved = self._resolve_url("bookings:non-existent-url", "bookings:get-my-bookings")
        self.assertTrue(resolved)

    def test_booking_model_str_and_methods(self):
        self.assertIn("BK9999", str(self.booking))
        self.assertTrue(self.route.__str__())
        self.assertTrue(self.trip.__str__())

    def test_booking_serializer_edge_cases(self):
        from bookings.serializers import BookingCreateSerializer
        serializer = BookingCreateSerializer(data={})
        self.assertFalse(serializer.is_valid())

        valid_serializer = BookingCreateSerializer(data={
            "trip_id": self.trip.id,
            "seats": 1,
            "pickup_location": "Nairobi",
        })
        self.assertTrue(valid_serializer.is_valid())

    def test_initialize_paystack_payment_booking_not_found(self):
        self.client.force_authenticate(user=self.passenger)
        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": 99999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_initialize_paystack_payment_invalid_status_or_paid(self):
        self.client.force_authenticate(user=self.passenger)
        self.booking.status = "cancelled"
        self.booking.save()
        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("bookings.views.requests.post")
    def test_initialize_paystack_payment_request_exception(self, mock_post):
        import requests
        self.client.force_authenticate(user=self.passenger)
        mock_post.side_effect = requests.RequestException("Network down")
        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch("bookings.views.requests.post")
    def test_initialize_paystack_payment_bad_status_code(self, mock_post):
        self.client.force_authenticate(user=self.passenger)
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Internal Server Error"
        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch("bookings.views.requests.post")
    def test_initialize_paystack_payment_paystack_api_false_status(self, mock_post):
        self.client.force_authenticate(user=self.passenger)
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"status": False, "message": "Invalid key"}
        url = reverse("bookings:initialize-paystack-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paystack_webhook_amount_mismatch(self):
        Payment.objects.create(
            booking=self.booking,
            provider_reference="REF_MISMATCH",
            amount=self.booking.total_amount,
            method="digital",
            status="pending",
        )
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "REF_MISMATCH",
                "amount": 100000,
            },
        }
        body = json.dumps(payload).encode("utf-8")
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), body, hashlib.sha512).hexdigest()

        url = "/api/bookings/webhooks/paystack/"
        response = self.client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_confirm_cash_payment_unauthorized_driver_or_user(self):
        other_user = User.objects.create_user(
            username="random_guy",
            password="password123",
            phone_number="+254799999999",
        )
        self.client.force_authenticate(user=other_user)

        Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_UNAUTH",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        url = reverse("bookings:confirm-cash-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_confirm_cash_payment_not_found_or_non_cash(self):
        admin_user = User.objects.create_superuser(username="admin_cash", password="password")
        self.client.force_authenticate(user=admin_user)

        url = reverse("bookings:confirm-cash-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_booking_trip_not_scheduled_or_full(self):
        self.client.force_authenticate(user=self.passenger)
        self.trip.capacity = 0
        self.trip.save()
        url = reverse("bookings:create-booking")
        payload = {"trip_id": self.trip.id, "route_id": self.route.id, "seats": 1}
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_boarding_invalid_payload_or_pin(self):
        admin_user = User.objects.create_superuser(username="admin_verify_err", password="password")
        self.client.force_authenticate(user=admin_user)
        self.booking.verification_pin = "5678"
        self.booking.status = "confirmed"
        self.booking.save()

        url = reverse("bookings:verify-boarding", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url, {"boarding_pin": "0000"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_booking_already_cancelled_or_invalid_fault(self):
        self.client.force_authenticate(user=self.passenger)
        self.booking.status = "cancelled"
        self.booking.save()
        url = reverse("bookings:cancel-booking", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paystack_webhook_missing_signature(self):
        url = reverse("bookings:paystack-webhook")
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paystack_webhook_invalid_signature(self):
        url = reverse("bookings:paystack-webhook")
        payload = {"event": "charge.success", "data": {"reference": "REF123"}}
        response = self.client.post(
            url,
            payload,
            format="json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid_sig",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paystack_webhook_ignored_event(self):
        url = reverse("bookings:paystack-webhook")
        body = json.dumps({"event": "other.event", "data": {}}).encode("utf-8")
        computed_sig = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()

        response = self.client.post(
            url,
            body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=computed_sig,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_confirm_cash_payment_wrong_method(self):
        staff_user = User.objects.create_user(
            username="cash_staff",
            password="password123",
            is_staff=True,
        )
        self.client.force_authenticate(user=staff_user)

        Payment.objects.create(
            booking=self.booking,
            provider_reference="DIGITAL_REF",
            amount=self.booking.total_amount,
            method="digital",
            status="pending",
        )
        url = reverse("bookings:confirm-cash-payment", kwargs={"booking_id": self.booking.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("bookings.services.requests.post")
    def test_passenger_fault_requests_50_percent_paystack_refund(
        self,
        mock_post,
    ):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="PAYSTACK_REF_800",
            amount=Decimal("800.00"),
            method="digital",
            status="confirmed",
        )

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "status": True,
            "data": {
                "id": 12345,
                "status": "pending",
            },
        }

        from bookings.services import settle_booking_fault

        refund_amount = settle_booking_fault(
            self.booking,
            "passenger",
        )

        self.assertEqual(
            refund_amount,
            Decimal("400.00"),
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.refund_amount,
            Decimal("400.00"),
        )

        self.assertEqual(
            payment.refund_status,
            "pending",
        )

        self.assertEqual(
            payment.refund_reference,
            "12345",
        )

        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args.kwargs

        self.assertEqual(
            call_kwargs["json"]["transaction"],
            "PAYSTACK_REF_800",
        )

        self.assertEqual(
            call_kwargs["json"]["amount"],
            40000,
        )


class LastSeatBookingTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Last Seat Co")
        self.driver = Driver.objects.create(
            company=self.company,
            name="Race Driver",
            phone_number="+254700000200",
            bus_number="KAA 111B",
        )
        self.route = Route.objects.create(
            company=self.company,
            name="Nairobi - Nakuru",
            price=Decimal("500.00"),
        )
        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=1,
        )
        self.user_a = User.objects.create_user(
            username="seat_a",
            password="password123",
            phone_number="+254700000201",
        )
        self.user_b = User.objects.create_user(
            username="seat_b",
            password="password123",
            phone_number="+254700000202",
        )
        Wallet.objects.create(
            user=self.user_a,
            available_balance=Decimal("2000.00"),
            held_balance=Decimal("0.00"),
        )
        Wallet.objects.create(
            user=self.user_b,
            available_balance=Decimal("2000.00"),
            held_balance=Decimal("0.00"),
        )

    def test_second_user_cannot_take_last_seat(self):
        url = reverse("bookings:create-booking")
        payload = {
            "trip_id": self.trip.id,
            "route_id": self.route.id,
            "seats": 1,
            "pickup_location": "CBD",
        }
        self.client.force_authenticate(user=self.user_a)
        first = self.client.post(url, payload, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.user_b)
        second = self.client.post(url, payload, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

        created = Booking.objects.filter(trip=self.trip).exclude(status="cancelled").count()
        self.assertEqual(created, 1)


class ConcurrentLastSeatTests(TransactionTestCase):

    def setUp(self):
        self.company = Company.objects.create(
            name="Concurrent Race Co"
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Concurrent Driver",
            phone_number="+254700000300",
            bus_number="KAA 222C",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Nairobi - Mombasa",
            price=Decimal("500.00"),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=1,
            status="scheduled",
        )

        self.user_a = User.objects.create_user(
            username="concurrent_a",
            password="password123",
            phone_number="+254700000301",
        )

        self.user_b = User.objects.create_user(
            username="concurrent_b",
            password="password123",
            phone_number="+254700000302",
        )

        Wallet.objects.create(
            user=self.user_a,
            available_balance=Decimal("2000.00"),
            held_balance=Decimal("0.00"),
        )

        Wallet.objects.create(
            user=self.user_b,
            available_balance=Decimal("2000.00"),
            held_balance=Decimal("0.00"),
        )

    def tearDown(self):
        connections.close_all()

    def _book(self, user, results):
        from rest_framework.test import APIClient

        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            response = client.post(
                reverse("bookings:create-booking"),
                {
                    "trip_id": self.trip.id,
                    "route_id": self.route.id,
                    "seats": 1,
                    "pickup_location": "CBD",
                },
                format="json",
            )
            results.append(response.status_code)
        finally:
            connections.close_all()

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "True row-level locking only exists on PostgreSQL.",
    )
    def test_only_one_user_gets_the_last_seat_concurrently(self):
        results = []

        thread_a = threading.Thread(
            target=self._book,
            args=(self.user_a, results),
        )
        thread_b = threading.Thread(
            target=self._book,
            args=(self.user_b, results),
        )

        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()
        connections.close_all()

        self.assertEqual(
            sorted(results),
            [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST],
        )

        successful_bookings = (
            Booking.objects.filter(trip=self.trip)
            .exclude(status="cancelled")
            .count()
        )
        self.assertEqual(successful_bookings, 1)