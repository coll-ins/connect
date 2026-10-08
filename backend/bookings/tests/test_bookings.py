import hashlib
import hmac
import json
import threading
import unittest
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.urls import reverse
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from bookings.models import Booking, Payment, BoardingEvent, Incident, BookingHold, IncidentResolution
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

    def test_active_incident_does_not_create_passenger_no_show(self):
        from django.core.management import call_command

        Incident.objects.create(
            trip=self.trip,
            reported_by=self.driver.company.user
            if getattr(self.driver.company, "user", None)
            else None,
            incident_type="breakdown",
            description="Bus broke down before departure.",
            status="reported",
        )

        self.passenger.no_show_count = 0
        self.passenger.save(update_fields=["no_show_count"])

        self.trip.departure_at = timezone.now() - timezone.timedelta(minutes=20)
        self.trip.save(update_fields=["departure_at"])

        call_command("process_noshows")

        self.booking.refresh_from_db()
        self.passenger.refresh_from_db()

        self.assertEqual(
            self.booking.status,
            "confirmed",
        )

        self.assertEqual(
            self.passenger.no_show_count,
            0,
        )

    def test_departed_trip_without_incident_creates_passenger_no_show(self):
        from django.core.management import call_command

        self.passenger.no_show_count = 0
        self.passenger.save(update_fields=["no_show_count"])

        self.trip.departure_at = timezone.now() - timezone.timedelta(minutes=20)
        self.trip.save(update_fields=["departure_at"])

        call_command("process_noshows")

        self.booking.refresh_from_db()
        self.passenger.refresh_from_db()

        self.assertEqual(
            self.booking.status,
            "no_show",
        )

        self.assertEqual(
            self.passenger.no_show_count,
            1,
        )

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

    def test_booking_detail_company_staff_same_company(self):
        company_user = User.objects.create_user(
            username="company_auditor",
            password="password123",
            phone_number="+254700000010",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=company_user)

        url = reverse(
            "bookings:get-booking-detail",
            kwargs={"booking_id": self.booking.id},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_booking_detail_company_staff_other_company_forbidden(self):
        other_company = Company.objects.create(
            name="Other Company",
        )

        company_user = User.objects.create_user(
            username="other_company_auditor",
            password="password123",
            phone_number="+254700000011",
            company=other_company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=company_user)

        url = reverse(
            "bookings:get-booking-detail",
            kwargs={"booking_id": self.booking.id},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_booking_detail_other_passenger_forbidden(self):
        other_passenger = User.objects.create_user(
            username="other_passenger",
            password="password123",
            phone_number="+254700000012",
        )

        self.client.force_authenticate(user=other_passenger)

        url = reverse(
            "bookings:get-booking-detail",
            kwargs={"booking_id": self.booking.id},
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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

    def test_assign_driver_by_company_manager(self):
        manager = User.objects.create_user(
            username="assignment_manager",
            password="password123",
            phone_number="+254700000020",
            company=self.company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:assign-driver",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"driver_id": self.driver.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.driver, self.driver)

    def test_assign_driver_by_company_operator(self):
        operator = User.objects.create_user(
            username="assignment_operator",
            password="password123",
            phone_number="+254700000021",
            company=self.company,
            role="company_operator",
        )

        self.client.force_authenticate(user=operator)

        url = reverse(
            "bookings:assign-driver",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"driver_id": self.driver.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.booking.refresh_from_db()
        self.assertEqual(self.booking.driver, self.driver)

    def test_assign_driver_by_company_auditor_forbidden(self):
        auditor = User.objects.create_user(
            username="assignment_auditor",
            password="password123",
            phone_number="+254700000022",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=auditor)

        url = reverse(
            "bookings:assign-driver",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"driver_id": self.driver.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_driver_by_passenger_forbidden(self):
        passenger = User.objects.create_user(
            username="assignment_passenger",
            password="password123",
            phone_number="+254700000023",
        )

        self.client.force_authenticate(user=passenger)

        url = reverse(
            "bookings:assign-driver",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"driver_id": self.driver.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_assign_driver_by_manager_from_other_company_forbidden(self):
        other_company = Company.objects.create(
            name="Other Assignment Company",
            areas_served="Other Area",
        )

        manager = User.objects.create_user(
            username="other_company_manager",
            password="password123",
            phone_number="+254700000024",
            company=other_company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:assign-driver",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"driver_id": self.driver.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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

        self.trip.status = "boarding"
        self.trip.save(update_fields=["status"])

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

    def _prepare_boarding_test(self):
        self.booking.status = "confirmed"
        self.booking.verification_pin = "1234"
        self.booking.save()

        self.trip.status = "boarding"
        self.trip.save(update_fields=["status"])

        Payment.objects.create(
            booking=self.booking,
            provider_reference="BOARDING_ROLE_PAY",
            amount=self.booking.total_amount,
            method="digital",
            status="confirmed",
        )

        return reverse(
            "bookings:verify-boarding",
            kwargs={"booking_id": self.booking.id},
        )

    def test_verify_boarding_company_manager(self):
        url = self._prepare_boarding_test()

        manager = User.objects.create_user(
            username="boarding_manager",
            password="password123",
            phone_number="+254700000060",
            company=self.company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        response = self.client.post(
            url,
            {"boarding_pin": "1234"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_verify_boarding_company_operator(self):
        url = self._prepare_boarding_test()

        operator = User.objects.create_user(
            username="boarding_operator",
            password="password123",
            phone_number="+254700000061",
            company=self.company,
            role="company_operator",
        )

        self.client.force_authenticate(user=operator)

        response = self.client.post(
            url,
            {"boarding_pin": "1234"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_verify_boarding_company_auditor_forbidden(self):
        url = self._prepare_boarding_test()

        auditor = User.objects.create_user(
            username="boarding_auditor",
            password="password123",
            phone_number="+254700000062",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=auditor)

        response = self.client.post(
            url,
            {"boarding_pin": "1234"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_verify_boarding_other_company_manager_forbidden(self):
        url = self._prepare_boarding_test()

        other_company = Company.objects.create(
            name="Other Boarding Company",
            areas_served="Other Area",
        )

        manager = User.objects.create_user(
            username="other_boarding_manager",
            password="password123",
            phone_number="+254700000063",
            company=other_company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        response = self.client.post(
            url,
            {"boarding_pin": "1234"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_verify_boarding_random_staff_forbidden(self):
        url = self._prepare_boarding_test()

        staff_user = User.objects.create_user(
            username="random_boarding_staff",
            password="password123",
            phone_number="+254700000064",
            is_staff=True,
        )

        self.client.force_authenticate(user=staff_user)

        response = self.client.post(
            url,
            {"boarding_pin": "1234"},
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

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

    def test_set_stage_departure_company_manager(self):
        manager = User.objects.create_user(
            username="stage_manager",
            password="password123",
            phone_number="+254700000040",
            company=self.company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:set-stage-departure",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"minutes": 15},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_set_stage_departure_company_operator(self):
        operator = User.objects.create_user(
            username="stage_operator",
            password="password123",
            phone_number="+254700000041",
            company=self.company,
            role="company_operator",
        )

        self.client.force_authenticate(user=operator)

        url = reverse(
            "bookings:set-stage-departure",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"minutes": 20},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_set_stage_departure_company_auditor_forbidden(self):
        auditor = User.objects.create_user(
            username="stage_auditor",
            password="password123",
            phone_number="+254700000042",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=auditor)

        url = reverse(
            "bookings:set-stage-departure",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"minutes": 20},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_set_stage_departure_other_company_manager_forbidden(self):
        other_company = Company.objects.create(
            name="Other Stage Company",
            areas_served="Other Area",
        )

        manager = User.objects.create_user(
            username="other_stage_manager",
            password="password123",
            phone_number="+254700000043",
            company=other_company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:set-stage-departure",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"minutes": 20},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_set_stage_departure_random_staff_forbidden(self):
        staff_user = User.objects.create_user(
            username="random_stage_staff",
            password="password123",
            phone_number="+254700000044",
            is_staff=True,
        )

        self.client.force_authenticate(user=staff_user)

        url = reverse(
            "bookings:set-stage-departure",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"minutes": 20},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_cancel_booking_company_fault(self):
        manager = User.objects.create_user(
            username="company_cancel_manager",
            password="password123",
            phone_number="+254700000030",
            company=self.company,
            role="company_manager",
        )
        self.client.force_authenticate(user=manager)

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

    def test_cancel_booking_company_operator(self):
        operator = User.objects.create_user(
            username="company_cancel_operator",
            password="password123",
            phone_number="+254700000031",
            company=self.company,
            role="company_operator",
        )

        self.client.force_authenticate(user=operator)

        url = reverse(
            "bookings:cancel-booking",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"fault_party": "company"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cancel_booking_company_auditor_forbidden(self):
        auditor = User.objects.create_user(
            username="company_cancel_auditor",
            password="password123",
            phone_number="+254700000032",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=auditor)

        url = reverse(
            "bookings:cancel-booking",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"fault_party": "company"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_booking_other_company_manager_forbidden(self):
        other_company = Company.objects.create(
            name="Other Cancellation Company",
            areas_served="Other Area",
        )

        manager = User.objects.create_user(
            username="other_cancel_manager",
            password="password123",
            phone_number="+254700000033",
            company=other_company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:cancel-booking",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"fault_party": "company"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_booking_random_staff_forbidden(self):
        staff_user = User.objects.create_user(
            username="random_staff",
            password="password123",
            phone_number="+254700000034",
            is_staff=True,
        )

        self.client.force_authenticate(user=staff_user)

        url = reverse(
            "bookings:cancel-booking",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(
            url,
            {"fault_party": "company"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

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
        operator = User.objects.create_user(
            username="cash_operator",
            password="password123",
            phone_number="+254700000050",
            company=self.company,
            role="company_operator",
        )
        self.client.force_authenticate(user=operator)

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

    def test_confirm_cash_payment_company_manager(self):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_MANAGER",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        manager = User.objects.create_user(
            username="cash_manager",
            password="password123",
            phone_number="+254700000051",
            company=self.company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:confirm-cash-payment",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()
        self.assertEqual(payment.status, "confirmed")

    def test_confirm_cash_payment_company_operator(self):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_OPERATOR",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        operator = User.objects.create_user(
            username="cash_operator_valid",
            password="password123",
            phone_number="+254700000052",
            company=self.company,
            role="company_operator",
        )

        self.client.force_authenticate(user=operator)

        url = reverse(
            "bookings:confirm-cash-payment",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()
        self.assertEqual(payment.status, "confirmed")

    def test_confirm_cash_payment_company_auditor_forbidden(self):
        Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_AUDITOR",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        auditor = User.objects.create_user(
            username="cash_auditor",
            password="password123",
            phone_number="+254700000053",
            company=self.company,
            role="company_auditor",
        )

        self.client.force_authenticate(user=auditor)

        url = reverse(
            "bookings:confirm-cash-payment",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_confirm_cash_payment_other_company_manager_forbidden(self):
        Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_OTHER_COMPANY",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        other_company = Company.objects.create(
            name="Other Cash Company",
            areas_served="Other Area",
        )

        manager = User.objects.create_user(
            username="other_cash_manager",
            password="password123",
            phone_number="+254700000054",
            company=other_company,
            role="company_manager",
        )

        self.client.force_authenticate(user=manager)

        url = reverse(
            "bookings:confirm-cash-payment",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_confirm_cash_payment_random_staff_forbidden(self):
        Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH_RANDOM_STAFF",
            amount=self.booking.total_amount,
            method="cash",
            status="pending",
        )

        staff_user = User.objects.create_user(
            username="random_cash_staff",
            password="password123",
            phone_number="+254700000055",
            is_staff=True,
        )

        self.client.force_authenticate(user=staff_user)

        url = reverse(
            "bookings:confirm-cash-payment",
            kwargs={"booking_id": self.booking.id},
        )

        response = self.client.post(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

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

        BookingHold.objects.create(
            booking=self.booking,
            amount=Decimal("800.00"),
            status="held",
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

        hold = BookingHold.objects.get(
            booking=self.booking,
        )

        self.assertEqual(
            hold.amount,
            Decimal("800.00"),
        )

        self.assertEqual(
            hold.refunded_amount,
            Decimal("400.00"),
        )

        self.assertEqual(
            hold.status,
            "held",
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


    @patch("bookings.services.requests.post")
    def test_company_fault_requests_full_paystack_refund(
        self,
        mock_post,
    ):
        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="PAYSTACK_REF_FULL_800",
            amount=Decimal("800.00"),
            method="digital",
            status="confirmed",
        )

        BookingHold.objects.create(
            booking=self.booking,
            amount=Decimal("800.00"),
            status="held",
        )

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "status": True,
            "data": {
                "id": 67890,
                "status": "processed",
            },
        }

        from bookings.services import settle_booking_fault

        refund_amount = settle_booking_fault(
            self.booking,
            "company",
        )

        self.assertEqual(
            refund_amount,
            Decimal("800.00"),
        )

        payment.refresh_from_db()

        self.assertEqual(
            payment.refund_amount,
            Decimal("800.00"),
        )

        self.assertEqual(
            payment.refund_status,
            "processed",
        )

        self.assertEqual(
            payment.refund_reference,
            "67890",
        )

        hold = BookingHold.objects.get(
            booking=self.booking,
        )

        self.assertEqual(
            hold.amount,
            Decimal("800.00"),
        )

        self.assertEqual(
            hold.refunded_amount,
            Decimal("800.00"),
        )

        self.assertEqual(
            hold.status,
            "refunded",
        )

        self.assertIsNotNone(
            hold.refunded_at,
        )

        mock_post.assert_called_once()

        call_kwargs = mock_post.call_args.kwargs

        self.assertEqual(
            call_kwargs["json"]["transaction"],
            "PAYSTACK_REF_FULL_800",
        )

        self.assertEqual(
            call_kwargs["json"]["amount"],
            80000,
        )



class ConcurrentRefundTests(TransactionTestCase):

    def setUp(self):
        self.company = Company.objects.create(
            name="Concurrent Refund Co"
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Refund Driver",
            phone_number="+254700000400",
            bus_number="KAA 333D",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Nairobi - Kisumu",
            price=Decimal("800.00"),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=10,
            status="scheduled",
        )

        self.passenger = User.objects.create_user(
            username="concurrent_refund_user",
            password="password123",
            phone_number="+254700000401",
        )

        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            booking_number="REFUND-RACE-001",
            total_amount=Decimal("800.00"),
            status="confirmed",
        )

        self.payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="PAYSTACK_REFUND_RACE",
            amount=Decimal("800.00"),
            method="digital",
            status="confirmed",
        )

        BookingHold.objects.create(
            booking=self.booking,
            amount=Decimal("800.00"),
            status="held",
        )

    def tearDown(self):
        connections.close_all()

    def _refund(self, results):
        from bookings.services import settle_booking_fault
        import time

        close_old_connections()

        try:
            # Small delay makes it much more likely that a second
            # thread reaches the refund claim while the first request
            # is still waiting on the mocked external provider.
            time.sleep(0.02)

            amount = settle_booking_fault(
                self.booking,
                "passenger",
            )

            results.append(
                ("ok", amount)
            )

        except Exception as exc:
            results.append(
                ("error", str(exc))
            )

        finally:
            connections.close_all()

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "True row-level locking test requires PostgreSQL.",
    )
    @patch("bookings.services.requests.post")
    def test_concurrent_refund_only_calls_paystack_once(
        self,
        mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "status": True,
            "data": {
                "id": 987654,
                "status": "pending",
            },
        }

        results = []

        thread_a = threading.Thread(
            target=self._refund,
            args=(results,),
        )

        thread_b = threading.Thread(
            target=self._refund,
            args=(results,),
        )

        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        self.assertEqual(
            len(results),
            2,
        )

        self.assertTrue(
            all(
                result[0] == "ok"
                for result in results
            ),
            results,
        )

        self.assertEqual(
            mock_post.call_count,
            1,
        )

        payment = Payment.objects.get(
            pk=self.payment.pk
        )

        self.assertEqual(
            payment.refund_amount,
            Decimal("400.00"),
        )

        self.assertEqual(
            payment.refund_status,
            "pending",
        )

        hold = BookingHold.objects.get(
            booking=self.booking
        )

        self.assertEqual(
            hold.refunded_amount,
            Decimal("400.00"),
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


class IncidentManagementTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Incident Express",
        )

        self.other_company = Company.objects.create(
            name="Other Incident Company",
        )

        self.passenger = User.objects.create_user(
            username="incident_passenger",
            password="password123",
            phone_number="+254700001001",
        )

        self.manager = User.objects.create_user(
            username="incident_manager",
            password="password123",
            phone_number="+254700001002",
            role="company_manager",
            company=self.company,
        )

        self.operator = User.objects.create_user(
            username="incident_operator",
            password="password123",
            phone_number="+254700001003",
            role="company_operator",
            company=self.company,
        )

        self.auditor = User.objects.create_user(
            username="incident_auditor",
            password="password123",
            phone_number="+254700001004",
            role="company_auditor",
            company=self.company,
        )

        self.other_manager = User.objects.create_user(
            username="other_incident_manager",
            password="password123",
            phone_number="+254700001005",
            role="company_manager",
            company=self.other_company,
        )

        self.driver_user = User.objects.create_user(
            username="incident_driver",
            password="password123",
            phone_number="+254711001001",
            role="driver",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Incident Driver",
            phone_number="+254711001001",
            bus_number="KXX 001X",
        )

        self.other_driver = Driver.objects.create(
            company=self.other_company,
            name="Other Incident Driver",
            phone_number="+254711001002",
            bus_number="KYY 002Y",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Incident Route",
            start_point="CBD",
            end_point="Rongai",
            price=Decimal("500.00"),
        )

        self.other_route = Route.objects.create(
            company=self.other_company,
            name="Other Incident Route",
            start_point="CBD",
            end_point="Thika",
            price=Decimal("600.00"),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=14,
        )

        self.other_trip = Trip.objects.create(
            route=self.other_route,
            driver=self.other_driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=14,
        )

    def incident_list_url(self):
        return reverse("bookings:incident-list")

    def report_incident_url(self):
        return reverse("bookings:report-incident")

    def incident_detail_url(self, incident_id):
        return reverse(
            "bookings:incident-detail",
            kwargs={"incident_id": incident_id},
        )

    def report_payload(self, trip_id=None):
        return {
            "trip_id": trip_id or self.trip.id,
            "incident_type": "breakdown",
            "description": "Bus broke down before departure.",
        }

    def test_company_manager_can_report_incident(self):
        self.client.force_authenticate(user=self.manager)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            response.data["trip"],
            self.trip.id,
        )
        self.assertEqual(
            response.data["reported_by"],
            self.manager.id,
        )

        incident = Incident.objects.get(id=response.data["id"])
        self.assertEqual(
            incident.trip.route.company_id,
            self.company.id,
        )

    def test_company_operator_can_report_incident(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            response.data["reported_by"],
            self.operator.id,
        )

    def test_driver_can_report_incident_for_assigned_trip(self):
        self.client.force_authenticate(user=self.driver_user)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

    def test_driver_cannot_report_incident_for_other_driver_trip(self):
        self.client.force_authenticate(user=self.driver_user)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(self.other_trip.id),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_auditor_cannot_report_incident(self):
        self.client.force_authenticate(user=self.auditor)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_passenger_cannot_report_incident(self):
        self.client.force_authenticate(user=self.passenger)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_other_company_manager_cannot_report_incident(self):
        self.client.force_authenticate(user=self.other_manager)

        response = self.client.post(
            self.report_incident_url(),
            self.report_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_company_staff_can_list_own_company_incidents(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.operator,
            incident_type="road_blocked",
            description="Road blocked near stage.",
        )

        self.client.force_authenticate(user=self.auditor)

        response = self.client.get(
            self.incident_list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            len(response.data),
            1,
        )
        self.assertEqual(
            response.data[0]["id"],
            incident.id,
        )

    def test_company_staff_cannot_list_other_company_incidents(self):
        Incident.objects.create(
            trip=self.other_trip,
            reported_by=self.other_manager,
            incident_type="breakdown",
            description="Other company breakdown.",
        )

        self.client.force_authenticate(user=self.auditor)

        response = self.client.get(
            self.incident_list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data,
            [],
        )

    def test_other_company_manager_cannot_view_incident_detail(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.manager,
            incident_type="accident",
            description="Incident on company route.",
        )

        self.client.force_authenticate(user=self.other_manager)

        response = self.client.get(
            self.incident_detail_url(incident.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_driver_can_view_incident_for_assigned_trip(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.driver_user,
            incident_type="breakdown",
            description="Engine problem.",
        )

        self.client.force_authenticate(user=self.driver_user)

        response = self.client.get(
            self.incident_detail_url(incident.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["id"],
            incident.id,
        )

    def test_driver_cannot_view_incident_for_other_driver(self):
        incident = Incident.objects.create(
            trip=self.other_trip,
            reported_by=self.other_manager,
            incident_type="breakdown",
            description="Other company's breakdown.",
        )

        self.client.force_authenticate(user=self.driver_user)

        response = self.client.get(
            self.incident_detail_url(incident.id),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_company_manager_can_update_incident(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.operator,
            incident_type="breakdown",
            description="Initial report.",
        )

        self.client.force_authenticate(user=self.manager)

        response = self.client.patch(
            self.incident_detail_url(incident.id),
            {
                "status": "investigating",
                "description": "Manager is investigating the breakdown.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["status"],
            "investigating",
        )

        incident.refresh_from_db()

        self.assertEqual(
            incident.status,
            "investigating",
        )
        self.assertEqual(
            incident.description,
            "Manager is investigating the breakdown.",
        )

    def test_company_operator_cannot_update_incident(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.operator,
            incident_type="breakdown",
            description="Initial report.",
        )

        self.client.force_authenticate(user=self.operator)

        response = self.client.patch(
            self.incident_detail_url(incident.id),
            {"status": "resolved"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_company_auditor_cannot_update_incident(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.operator,
            incident_type="breakdown",
            description="Initial report.",
        )

        self.client.force_authenticate(user=self.auditor)

        response = self.client.patch(
            self.incident_detail_url(incident.id),
            {"status": "resolved"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_other_company_manager_cannot_update_incident(self):
        incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.manager,
            incident_type="breakdown",
            description="Initial report.",
        )

        self.client.force_authenticate(user=self.other_manager)

        response = self.client.patch(
            self.incident_detail_url(incident.id),
            {"status": "resolved"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        incident.refresh_from_db()

        self.assertEqual(
            incident.status,
            "reported",
        )

    def test_passenger_cannot_view_incident_list(self):
        self.client.force_authenticate(user=self.passenger)

        response = self.client.get(
            self.incident_list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_invalid_incident_type_rejected(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.post(
            self.report_incident_url(),
            {
                "trip_id": self.trip.id,
                "incident_type": "fake_incident",
                "description": "Invalid incident.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_missing_incident_description_rejected(self):
        self.client.force_authenticate(user=self.operator)

        response = self.client.post(
            self.report_incident_url(),
            {
                "trip_id": self.trip.id,
                "incident_type": "breakdown",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )


class IncidentResolutionTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Resolution Express",
        )

        self.other_company = Company.objects.create(
            name="Other Resolution Company",
        )

        self.passenger = User.objects.create_user(
            username="resolution_passenger",
            password="password123",
            phone_number="+254700002001",
        )

        self.other_passenger = User.objects.create_user(
            username="other_resolution_passenger",
            password="password123",
            phone_number="+254700002002",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Resolution Driver",
            phone_number="+254711002001",
            bus_number="KZZ 001Z",
        )

        self.other_driver = Driver.objects.create(
            company=self.company,
            name="Replacement Driver",
            phone_number="+254711002002",
            bus_number="KZZ 002Z",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="CBD - Rongai",
            start_point="CBD",
            end_point="Rongai",
            price=Decimal("500.00"),
        )

        self.other_route = Route.objects.create(
            company=self.company,
            name="CBD - Thika",
            start_point="CBD",
            end_point="Thika",
            price=Decimal("600.00"),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=2),
            capacity=14,
        )

        self.replacement_trip = Trip.objects.create(
            route=self.route,
            driver=self.other_driver,
            departure_at=timezone.now() + timezone.timedelta(hours=5),
            capacity=14,
        )

        self.other_route_trip = Trip.objects.create(
            route=self.other_route,
            driver=self.other_driver,
            departure_at=timezone.now() + timezone.timedelta(hours=5),
            capacity=14,
        )

        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            driver=self.driver,
            pickup_location="CBD",
            seats=2,
            total_amount=Decimal("1000.00"),
            status="confirmed",
        )

        self.incident = Incident.objects.create(
            trip=self.trip,
            reported_by=self.passenger,
            incident_type="breakdown",
            description="Vehicle broke down before departure.",
            status="reported",
        )

        self.payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="RESOLUTION-PAY-001",
            amount=Decimal("1000.00"),
            method="digital",
            status="confirmed",
        )

        self.hold = BookingHold.objects.create(
            booking=self.booking,
            amount=Decimal("1000.00"),
            status="held",
        )

    def resolve_url(self):
        return reverse(
            "bookings:resolve-incident-booking",
            kwargs={"booking_id": self.booking.id},
        )

    def test_passenger_can_reschedule_without_second_payment(self):
        self.client.force_authenticate(user=self.passenger)

        booking_id = self.booking.id
        booking_number = self.booking.booking_number
        payment_id = self.payment.id
        hold_id = self.hold.id

        response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "reschedule",
                "replacement_trip_id": self.replacement_trip.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.booking.refresh_from_db()
        self.payment.refresh_from_db()
        self.hold.refresh_from_db()

        self.assertEqual(self.booking.id, booking_id)
        self.assertEqual(self.booking.booking_number, booking_number)
        self.assertEqual(self.booking.trip_id, self.replacement_trip.id)
        self.assertEqual(self.booking.driver_id, self.other_driver.id)
        self.assertEqual(self.booking.status, "confirmed")

        self.assertEqual(self.payment.id, payment_id)
        self.assertEqual(self.payment.amount, Decimal("1000.00"))
        self.assertEqual(self.payment.status, "confirmed")

        self.assertEqual(self.hold.id, hold_id)
        self.assertEqual(self.hold.amount, Decimal("1000.00"))
        self.assertEqual(self.hold.status, "held")

        self.assertEqual(
            Booking.objects.filter(
                user=self.passenger
            ).count(),
            1,
        )

        self.assertEqual(
            Payment.objects.filter(
                booking=self.booking
            ).count(),
            1,
        )

        resolution = IncidentResolution.objects.get(
            booking=self.booking
        )

        self.assertEqual(resolution.resolution, "reschedule")
        self.assertEqual(resolution.status, "completed")
        self.assertEqual(
            resolution.replacement_trip_id,
            self.replacement_trip.id,
        )

        self.assertTrue(
            response.data["payment_unchanged"]
        )

    def test_reschedule_rejects_different_route(self):
        self.client.force_authenticate(user=self.passenger)

        response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "reschedule",
                "replacement_trip_id": self.other_route_trip.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.booking.refresh_from_db()

        self.assertEqual(
            self.booking.trip_id,
            self.trip.id,
        )

        self.assertFalse(
            IncidentResolution.objects.filter(
                booking=self.booking
            ).exists()
        )

    def test_passenger_can_request_full_incident_refund_for_cash_payment(self):
        self.payment.delete()

        payment = Payment.objects.create(
            booking=self.booking,
            provider_reference="CASH-RESOLUTION-001",
            amount=Decimal("1000.00"),
            method="cash",
            status="confirmed",
        )

        self.client.force_authenticate(user=self.passenger)

        response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "refund",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.booking.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(
            self.booking.status,
            "cancelled",
        )

        self.assertEqual(
            response.data["refund_amount"],
            "1000.00",
        )

        self.assertEqual(
            payment.refund_amount,
            Decimal("1000.00"),
        )

        resolution = IncidentResolution.objects.get(
            booking=self.booking
        )

        self.assertEqual(
            resolution.resolution,
            "refund",
        )
        self.assertEqual(
            resolution.status,
            "completed",
        )
        self.assertEqual(
            resolution.refund_amount,
            Decimal("1000.00"),
        )

    def test_passenger_cannot_resolve_someone_elses_booking(self):
        self.booking.user = self.other_passenger
        self.booking.save(update_fields=["user"])

        self.client.force_authenticate(user=self.passenger)

        response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "reschedule",
                "replacement_trip_id": self.replacement_trip.id,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertFalse(
            IncidentResolution.objects.filter(
                booking=self.booking
            ).exists()
        )

    def test_cannot_resolve_same_booking_twice(self):
        self.client.force_authenticate(user=self.passenger)

        first_response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "reschedule",
                "replacement_trip_id": self.replacement_trip.id,
            },
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_200_OK,
        )

        second_response = self.client.post(
            self.resolve_url(),
            {
                "resolution": "reschedule",
                "replacement_trip_id": self.trip.id,
            },
            format="json",
        )

        self.assertEqual(
            second_response.status_code,
            status.HTTP_409_CONFLICT,
        )

        self.assertEqual(
            IncidentResolution.objects.filter(
                booking=self.booking
            ).count(),
            1,
        )

class ConcurrentDriverAssignmentTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Concurrent Assignment Co",
        )

        self.manager = User.objects.create_user(
            username="concurrent_assignment_manager",
            password="password123",
            phone_number="+254700000025",
            company=self.company,
            role="company_manager",
        )

        self.target_driver = Driver.objects.create(
            company=self.company,
            name="Target Driver",
            phone_number="+254711111115",
            bus_number="KAA 115E",
            is_available=True,
        )

        self.other_driver_a = Driver.objects.create(
            company=self.company,
            name="Other Driver A",
            phone_number="+254711111116",
            bus_number="KAA 116F",
            is_available=True,
        )

        self.other_driver_b = Driver.objects.create(
            company=self.company,
            name="Other Driver B",
            phone_number="+254711111117",
            bus_number="KAA 117G",
            is_available=True,
        )

        self.route_a = Route.objects.create(
            company=self.company,
            name="Assignment Race A",
            start_point="CBD",
            end_point="Ngong",
            price=Decimal("300.00"),
        )

        self.route_b = Route.objects.create(
            company=self.company,
            name="Assignment Race B",
            start_point="CBD",
            end_point="Karen",
            price=Decimal("350.00"),
        )

        departure = timezone.now() + timezone.timedelta(hours=3)

        self.trip_a = Trip.objects.create(
            route=self.route_a,
            driver=self.other_driver_a,
            departure_at=departure,
            capacity=10,
            status="scheduled",
        )

        self.trip_b = Trip.objects.create(
            route=self.route_b,
            driver=self.other_driver_b,
            departure_at=departure,
            capacity=10,
            status="scheduled",
        )

        self.passenger_a = User.objects.create_user(
            username="assignment_passenger_a",
            password="password123",
            phone_number="+254700000026",
        )

        self.passenger_b = User.objects.create_user(
            username="assignment_passenger_b",
            password="password123",
            phone_number="+254700000027",
        )

        self.booking_a = Booking.objects.create(
            user=self.passenger_a,
            route=self.route_a,
            trip=self.trip_a,
            total_amount=Decimal("300.00"),
            status="pending",
        )

        self.booking_b = Booking.objects.create(
            user=self.passenger_b,
            route=self.route_b,
            trip=self.trip_b,
            total_amount=Decimal("350.00"),
            status="pending",
        )

    def tearDown(self):
        connections.close_all()

    def _assign(self, booking_id, results, barrier):
        close_old_connections()

        try:
            client = APIClient()
            client.force_authenticate(user=self.manager)

            barrier.wait()

            response = client.post(
                reverse(
                    "bookings:assign-driver",
                    kwargs={"booking_id": booking_id},
                ),
                {"driver_id": self.target_driver.id},
                format="json",
            )

            results.append(response.status_code)

        except Exception as exc:
            results.append(f"error: {exc}")

        finally:
            connections.close_all()

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "True row-level locking test requires PostgreSQL.",
    )
    def test_driver_cannot_be_assigned_to_two_same_time_trips_concurrently(self):
        results = []
        barrier = threading.Barrier(2)

        thread_a = threading.Thread(
            target=self._assign,
            args=(
                self.booking_a.id,
                results,
                barrier,
            ),
        )

        thread_b = threading.Thread(
            target=self._assign,
            args=(
                self.booking_b.id,
                results,
                barrier,
            ),
        )

        thread_a.start()
        thread_b.start()
        thread_a.join()
        thread_b.join()

        connections.close_all()

        self.assertEqual(
            sorted(results),
            [
                status.HTTP_200_OK,
                status.HTTP_409_CONFLICT,
            ],
            results,
        )

        self.trip_a.refresh_from_db()
        self.trip_b.refresh_from_db()

        assigned_count = sum(
            [
                self.trip_a.driver_id == self.target_driver.id,
                self.trip_b.driver_id == self.target_driver.id,
            ]
        )

        self.assertEqual(
            assigned_count,
            1,
        )

        self.assertEqual(
            Trip.objects.filter(
                driver=self.target_driver,
                departure_at=self.trip_a.departure_at,
                status__in={
                    "scheduled",
                    "boarding",
                    "departed",
                },
            ).count(),
            1,
        )


class CancellationTripStateRaceTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Cancellation Race Co",
        )

        self.driver = Driver.objects.create(
            company=self.company,
            name="Cancellation Race Driver",
            phone_number="+254711111118",
            bus_number="KAA 118H",
        )

        self.manager = User.objects.create_user(
            username="cancellation_race_manager",
            password="password123",
            phone_number="+254700000028",
            company=self.company,
            role="company_manager",
        )

        self.passenger = User.objects.create_user(
            username="cancellation_race_passenger",
            password="password123",
            phone_number="+254700000029",
        )

        self.route = Route.objects.create(
            company=self.company,
            name="Cancellation Race Route",
            start_point="CBD",
            end_point="Ngong",
            price=Decimal("800.00"),
        )

        self.trip = Trip.objects.create(
            route=self.route,
            driver=self.driver,
            departure_at=timezone.now() + timezone.timedelta(hours=3),
            capacity=10,
            status="scheduled",
        )

        self.booking = Booking.objects.create(
            user=self.passenger,
            route=self.route,
            trip=self.trip,
            total_amount=Decimal("800.00"),
            status="confirmed",
            verification_pin="1234",
        )

    def tearDown(self):
        connections.close_all()

    @unittest.skipUnless(
        connection.vendor == "postgresql",
        "True row-level locking test requires PostgreSQL.",
    )
    def test_cancellation_rechecks_trip_state_after_trip_lock(self):
        """
        Hold the Trip lock, change the trip to boarding, then let
        cancellation proceed. Cancellation must see the locked/current
        Trip state and reject the request.
        """
        results = []
        ready = threading.Event()

        def cancel():
            close_old_connections()

            try:
                client = APIClient()
                client.force_authenticate(user=self.passenger)

                ready.set()

                response = client.post(
                    reverse(
                        "bookings:cancel-booking",
                        kwargs={"booking_id": self.booking.id},
                    ),
                    {
                        "fault_party": "passenger",
                    },
                    format="json",
                )

                results.append(response.status_code)

            except Exception as exc:
                results.append(
                    f"error: {exc}"
                )

            finally:
                connections.close_all()

        close_old_connections()

        with transaction.atomic():
            locked_trip = (
                Trip.objects
                .select_for_update()
                .get(pk=self.trip.pk)
            )

            locked_trip.status = "boarding"
            locked_trip.save(update_fields=["status"])

            worker = threading.Thread(
                target=cancel,
            )
            worker.start()

            ready.wait(timeout=5)

            import time
            time.sleep(0.15)

        worker.join(timeout=5)

        connections.close_all()

        self.assertEqual(
            results,
            [409],
            results,
        )

        self.booking.refresh_from_db()
        self.trip.refresh_from_db()

        self.assertEqual(
            self.trip.status,
            "boarding",
        )

        self.assertEqual(
            self.booking.status,
            "confirmed",
        )

