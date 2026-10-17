import hashlib
import hmac
import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import BookingHold, Payment, Payout
from bookings.tests.test_round5 import _Fixture, _paystack_ok


class LatePaymentOutsideTransactionTests(_Fixture, TransactionTestCase):
    """The late-payment refund paths must not call Paystack inside a transaction."""

    def _spy(self):
        seen = []

        def fake_post(*args, **kwargs):
            seen.append(connection.in_atomic_block)
            return _paystack_ok(777)

        return seen, fake_post

    def test_webhook_late_payment(self):
        self.build('401')
        booking, payment = self.booking('cancelled', 'REF_LATE')
        body = json.dumps({
            'event': 'charge.success',
            'data': {'reference': 'REF_LATE', 'amount': 80000, 'currency': 'KES'},
        }).encode()
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512
        ).hexdigest()
        seen, fake_post = self._spy()
        with patch('bookings.services.requests.post', side_effect=fake_post):
            response = APIClient().post(
                reverse('bookings:paystack-webhook'),
                data=body,
                content_type='application/json',
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, [False])
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'pending')

    @patch('bookings.views.requests.get')
    def test_verify_late_payment(self, mock_get):
        self.build('402', departure_hours=-1)
        booking, payment = self.booking('pending', 'REF_VER')
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'status': True,
            'data': {'status': 'success', 'amount': 80000},
        }
        seen, fake_post = self._spy()
        client = APIClient()
        client.force_authenticate(user=self.passenger)
        url = reverse('bookings:verify-paystack-payment', kwargs={'booking_id': booking.id})
        with patch('bookings.services.requests.post', side_effect=fake_post):
            response = client.post(url)
            if response.status_code == 405:
                response = client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(seen, [False])
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'pending')


class ReconcileRefundsTests(_Fixture, TestCase):
    def setUp(self):
        self.build('501')
        self.booking_obj, self.payment = self.booking(
            'cancelled', 'REF_REC', payment_status='confirmed', hold=True
        )
        self._claim(minutes_ago=120)

    def _claim(self, minutes_ago, status='processing', reference=None):
        values = {
            'refund_status': status,
            'refund_amount': Decimal('400.00'),
            'refund_claimed_at': timezone.now() - timedelta(minutes=minutes_ago),
        }
        if reference is not None:
            values['refund_reference'] = reference
        Payment.objects.filter(pk=self.payment.pk).update(**values)

    def _run(self, listing=None, exc=None, resend=False):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'status': True, 'data': listing or []}
        target = 'bookings.management.commands.reconcile_refunds.requests.get'
        with patch(target, side_effect=exc, return_value=response) as mock_get, \
                patch('notifications.sms.send_admin_alert_sms') as alert:
            call_command(
                'reconcile_refunds',
                resend=resend,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        return mock_get, alert

    def test_no_refund_at_paystack_is_flagged_not_resent(self):
        with patch('bookings.services.requests.post') as post:
            _, alert = self._run(listing=[])
        post.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processing')
        alert.assert_called_once()

    def test_resend_sends_a_refund_that_never_reached_paystack(self):
        with patch('bookings.services.requests.post', return_value=_paystack_ok(42)) as post:
            self._run(listing=[], resend=True)
        post.assert_called_once()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'pending')
        self.assertEqual(self.payment.refund_reference, '42')

    def test_resend_never_applies_once_paystack_acknowledged(self):
        self._claim(minutes_ago=120, status='pending', reference='7')
        with patch('bookings.services.requests.post') as post:
            _, alert = self._run(listing=[], resend=True)
        post.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'pending')
        alert.assert_called_once()

    def test_processed_refund_is_recorded(self):
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': 40000}])
        self.payment.refresh_from_db()
        hold = BookingHold.objects.get(booking=self.booking_obj)
        self.assertEqual(self.payment.refund_status, 'processed')
        self.assertEqual(self.payment.refund_reference, '9')
        self.assertEqual(hold.refunded_amount, Decimal('400.00'))
        self.assertEqual(hold.status, 'held')

    def test_partial_refund_keeps_payment_confirmed_for_settlement(self):
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': 40000}])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processed')
        self.assertEqual(self.payment.status, 'confirmed')

    def test_full_refund_marks_payment_refunded(self):
        full = self.payment.amount
        Payment.objects.filter(pk=self.payment.pk).update(refund_amount=full)
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': int(full * 100)}])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'refunded')
        self.assertIsNotNone(self.payment.refunded_at)

    def _settle(self, apply=False):
        out = io.StringIO()
        kwargs = {'apply': True, 'reference': 'TESTPAY1'} if apply else {}
        call_command('settle_company', self.company.pk, stdout=out, **kwargs)
        return out.getvalue()

    def test_partial_refund_then_settlement_pays_only_the_remainder(self):
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': 40000}])
        self._settle(apply=True)
        payout = Payout.objects.get(company=self.company)
        fee = settings.PLATFORM_FEE_PER_SEAT * self.booking_obj.seats
        self.assertEqual(payout.gross_amount, Decimal('400.00'))
        self.assertEqual(payout.fee_amount, fee)
        self.assertEqual(payout.net_amount, Decimal('400.00') - fee)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.settlement_status, 'settled')
        self._settle(apply=True)
        self.assertEqual(Payout.objects.filter(company=self.company).count(), 1)

    def test_full_refund_is_never_paid_out(self):
        Payment.objects.filter(pk=self.payment.pk).update(refund_amount=Decimal('800.00'))
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': 80000}])
        self._settle(apply=True)
        self.assertFalse(Payout.objects.filter(company=self.company).exists())

    def test_processed_refund_without_amount_is_held_not_paid(self):
        Payment.objects.filter(pk=self.payment.pk).update(
            refund_status='processed', refund_amount=None,
            settlement_status='not_ready')
        self.assertIn('HELD BACK', self._settle())
        self._settle(apply=True)
        self.assertFalse(Payout.objects.filter(company=self.company).exists())

    def test_missed_webhook_pending_becomes_processed(self):
        self._claim(minutes_ago=120, status='pending', reference='9')
        self._run(listing=[{'id': 9, 'status': 'processed', 'amount': 40000}])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processed')

    def test_fresh_claim_is_left_alone(self):
        self._claim(minutes_ago=1)
        mock_get, _ = self._run(listing=[])
        mock_get.assert_not_called()
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processing')

    def test_paystack_unreachable_changes_nothing(self):
        self._run(exc=requests.ConnectionError('down'))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processing')

    def test_failed_refund_alerts_and_stays(self):
        _, alert = self._run(listing=[{'id': 9, 'status': 'failed', 'amount': 40000}])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.refund_status, 'processing')
        alert.assert_called_once()
