import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import (
    Booking, Incident, Payment, Payout, PayoutItem, UnappliedPayment,
)
from bookings.tests.test_round5 import _Fixture, _paystack_ok
from charters.models import CharterRequest
from companies.models import Company, PickupStage, Route, Trip
from connect import paystack_extra as px
from deliveries.models import Parcel
from deliveries.services import ParcelError, cancel_parcel

User = get_user_model()
ALERT = 'notifications.sms.send_admin_alert_sms'
FEES = dict(
    PLATFORM_FEE_PER_SEAT=Decimal('20.00'),
    PLATFORM_CHARTER_FEE_PERCENT=Decimal('10.00'),
    PLATFORM_PARCEL_FEE_PERCENT=Decimal('10.00'),
)


class _ParcelFixture(_Fixture):
    def parcel(self, status='delivered', price=Decimal('150.00'), trip=None, with_reference=True):
        if not hasattr(self, 'stage_a'):
            self.stage_a = PickupStage.objects.create(
                route=self.route, name='S1', order=1,
                latitude=Decimal('-1.2'), longitude=Decimal('36.8'))
            self.stage_b = PickupStage.objects.create(
                route=self.route, name='S2', order=2,
                latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
        parcel = Parcel.objects.create(
            sender=self.passenger, trip=trip or self.trip,
            pickup_stage=self.stage_a, dropoff_stage=self.stage_b, size='small',
            description='Box', receiver_name='R', receiver_phone='+254712345678',
            price=price, status=status,
        )
        reference = f'PCL-{parcel.id}-ABCDEFGHJK' if with_reference else None
        Parcel.objects.filter(pk=parcel.pk).update(provider_reference=reference)
        parcel.refresh_from_db()
        return parcel


@override_settings(**FEES)
class ParcelSettlementTests(_ParcelFixture, TestCase):
    def setUp(self):
        self.build('1001')

    def _settle(self, **kwargs):
        out = io.StringIO()
        call_command('settle_company', self.company.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_delivered_parcel_is_paid_with_percentage_fee(self):
        parcel = self.parcel()
        self.assertIn('NET TO PAY 135.00', self._settle())
        self.assertEqual(Payout.objects.count(), 0)

        self._settle(apply=True, reference='MPESA-P1')
        payout = Payout.objects.get(reference='MPESA-P1')
        self.assertEqual(payout.gross_amount, Decimal('150.00'))
        self.assertEqual(payout.fee_amount, Decimal('15.00'))
        self.assertEqual(payout.net_amount, Decimal('135.00'))
        self.assertEqual(payout.breakdown['parcels']['count'], 1)
        self.assertTrue(PayoutItem.objects.filter(kind='parcel', object_id=parcel.pk).exists())

    def test_only_delivered_paid_parcels_of_this_company(self):
        self.parcel(status='delivered')
        for status in ('pending_payment', 'paid', 'picked_up', 'cancelled',
                       'failed_delivery', 'expired'):
            self.parcel(status=status)
        self.parcel(status='delivered', with_reference=False)
        other = Company.objects.create(name='R11 Other Co')
        other_route = Route.objects.create(company=other, name='R11 Other', price=Decimal('800.00'))
        other_trip = Trip.objects.create(
            route=other_route, driver=self.driver,
            departure_at=timezone.now() + timedelta(hours=4), capacity=5)
        self.parcel(status='delivered', trip=other_trip)

        self._settle(apply=True, reference='MPESA-P2')
        self.assertEqual(PayoutItem.objects.count(), 1)

    def test_a_parcel_is_never_paid_twice(self):
        self.parcel()
        self._settle(apply=True, reference='MPESA-P3')
        self.assertIn('Nothing to pay out', self._settle(apply=True, reference='MPESA-P4'))
        self.assertEqual(PayoutItem.objects.count(), 1)

    def test_seats_charters_and_parcels_settle_in_one_payout(self):
        booking, payment = self.booking('confirmed', 'S11', payment_status='confirmed')
        Booking.objects.filter(pk=booking.pk).update(seats=1)
        Payment.objects.filter(pk=payment.pk).update(settlement_status='eligible')
        CharterRequest.objects.create(
            passenger=self.passenger, company=self.company, driver=self.driver,
            purpose='Wedding', pickup_location='CBD', destination='Nakuru',
            depart_at=timezone.now() + timedelta(days=5), passenger_count=14,
            contact_name='Test', contact_phone='+254700000000', status='completed',
            quote_price=Decimal('30000.00'), provider_reference='CHT-R11-1',
        )
        self.parcel()

        self._settle(apply=True, reference='MPESA-ALL')
        payout = Payout.objects.get(reference='MPESA-ALL')
        self.assertEqual(payout.gross_amount, Decimal('30950.00'))
        self.assertEqual(payout.fee_amount, Decimal('3035.00'))
        self.assertEqual(payout.net_amount, Decimal('27915.00'))
        self.assertEqual(payout.payments_count, 3)


class ParcelCancelRefundTests(_ParcelFixture, TestCase):
    def setUp(self):
        self.build('1002')

    def _cron(self):
        call_command('process_unapplied', stdout=io.StringIO(), stderr=io.StringIO())

    def test_paid_parcel_cancel_queues_a_full_refund_sent_once(self):
        parcel = self.parcel(status='paid')
        cancelled = cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        self.assertEqual(cancelled.status, 'cancelled')
        row = UnappliedPayment.objects.get(reference=parcel.provider_reference)
        self.assertEqual((row.status, row.kind, row.amount), ('refund_due', 'parcel', Decimal('150.00')))

        with patch('connect.paystack_extra.requests.post', return_value=_paystack_ok(61)) as post, \
                patch(ALERT):
            self._cron()
            self._cron()
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['transaction'], parcel.provider_reference)
        self.assertEqual(post.call_args.kwargs['json']['amount'], 15000)
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunded')

    def test_cancelling_twice_never_queues_a_second_refund(self):
        parcel = self.parcel(status='paid')
        cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        with self.assertRaises(ParcelError):
            cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        self.assertEqual(UnappliedPayment.objects.count(), 1)

    def test_another_user_cannot_cancel_or_trigger_a_refund(self):
        parcel = self.parcel(status='paid')
        intruder = User.objects.create_user(
            username='r11_thief', password='password123', phone_number='+254744001002')
        with self.assertRaises(Parcel.DoesNotExist):
            cancel_parcel(parcel_id=parcel.pk, user=intruder)
        parcel.refresh_from_db()
        self.assertEqual(parcel.status, 'paid')
        self.assertEqual(UnappliedPayment.objects.count(), 0)

    def test_picked_up_parcel_cannot_be_cancelled(self):
        parcel = self.parcel(status='picked_up')
        with self.assertRaises(ParcelError):
            cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        self.assertEqual(UnappliedPayment.objects.count(), 0)

    def test_paid_parcel_without_reference_is_not_cancelled(self):
        parcel = self.parcel(status='paid', with_reference=False)
        with self.assertRaises(ParcelError):
            cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        parcel.refresh_from_db()
        self.assertEqual(parcel.status, 'paid')

    def test_replayed_charge_webhook_does_not_reapply_a_cancelled_parcel(self):
        parcel = self.parcel(status='paid')
        cancel_parcel(parcel_id=parcel.pk, user=self.passenger)
        reference = parcel.provider_reference
        px.handle_extra_charge(
            reference, {'reference': reference, 'amount': 15000, 'currency': 'KES'})
        parcel.refresh_from_db()
        self.assertEqual(parcel.status, 'cancelled')
        self.assertEqual(UnappliedPayment.objects.count(), 1)


class PasswordPolicyTests(TestCase):
    def test_weak_passwords_are_rejected(self):
        for weak in ('12345678', 'password', 'abc'):
            with self.assertRaises(ValidationError):
                validate_password(weak)

    def test_reasonable_password_is_accepted(self):
        validate_password('Tr4velSafe-2026')

    def test_signup_serializer_enforces_the_policy(self):
        from users.serializers import UserSerializer
        field = UserSerializer().fields['password']
        self.assertIn(validate_password, field.validators)
        self.assertTrue(any(getattr(v, 'limit_value', None) == 8 for v in field.validators))


class BookingAccessControlTests(_Fixture, APITestCase):
    """Passenger B (and anonymous users) must not touch passenger A's booking."""

    def setUp(self):
        self.build('1003')
        self.confirmed, self.payment = self.booking(
            'confirmed', 'REF_ACL1', payment_status='confirmed', hold=True)
        self.pending, self.pending_payment = self.booking('pending', 'REF_ACL2')
        Incident.objects.create(
            trip=self.trip, reported_by=self.passenger, incident_type='breakdown',
            description='Broke down.', status='reported')
        self.intruder = User.objects.create_user(
            username='r11_intruder', password='password123', phone_number='+254744001003')
        self.client.force_authenticate(user=self.intruder)

    def _url(self, name, booking):
        return reverse(f'bookings:{name}', kwargs={'booking_id': booking.id})

    def _denied(self, response):
        self.assertIn(response.status_code, (403, 404), getattr(response, 'data', None))

    def _unchanged(self):
        self.confirmed.refresh_from_db()
        self.payment.refresh_from_db()
        self.pending.refresh_from_db()
        self.assertEqual(self.confirmed.status, 'confirmed')
        self.assertEqual(self.pending.status, 'pending')
        self.assertEqual(self.payment.refund_status, 'not_requested')
        self.assertFalse(Payment.objects.filter(refund_status__in=['processing', 'pending']).exists())

    def test_cannot_cancel_someone_elses_booking(self):
        with patch('bookings.services.requests.post') as post:
            response = self.client.post(
                self._url('cancel-booking', self.confirmed), {'fault_party': 'passenger'}, format='json')
        self._denied(response)
        post.assert_not_called()
        self._unchanged()

    def test_cannot_start_payment_for_someone_elses_booking(self):
        with patch('bookings.views.requests.post') as post:
            response = self.client.post(
                self._url('initialize-paystack-payment', self.pending), {}, format='json')
        self._denied(response)
        post.assert_not_called()
        self._unchanged()

    def test_cannot_verify_someone_elses_payment(self):
        url = self._url('verify-paystack-payment', self.pending)
        with patch('bookings.views.requests.get') as get, patch('bookings.services.requests.post') as post:
            response = self.client.post(url, {}, format='json')
            if response.status_code == 405:
                response = self.client.get(url)
        self._denied(response)
        get.assert_not_called()
        post.assert_not_called()
        self._unchanged()

    def test_cannot_resolve_someone_elses_incident_booking(self):
        with patch('bookings.services.requests.post') as post:
            response = self.client.post(
                self._url('resolve-incident-booking', self.confirmed),
                {'resolution': 'refund'}, format='json')
        self._denied(response)
        post.assert_not_called()
        self._unchanged()

    def test_anonymous_users_are_rejected_everywhere(self):
        self.client.force_authenticate(user=None)
        for name in ('cancel-booking', 'initialize-paystack-payment',
                     'verify-paystack-payment', 'resolve-incident-booking'):
            with patch('bookings.services.requests.post') as post, \
                    patch('bookings.views.requests.post'), patch('bookings.views.requests.get'):
                response = self.client.post(self._url(name, self.confirmed), {}, format='json')
                if response.status_code == 405:
                    response = self.client.get(self._url(name, self.confirmed))
            self.assertIn(response.status_code, (401, 403), name)
            post.assert_not_called()
        self._unchanged()
