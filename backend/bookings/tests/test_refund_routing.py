"""One charge, two refunds: webhook and reconcilers route by refund id first (BE-1b)."""
import datetime as dt
import hashlib
import hmac
import json
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone

from bookings.models import Payment, UnappliedPayment
from bookings.tests.test_late_payments import MoneyBase

LIST = 'bookings.management.commands.reconcile_refunds.requests.get'
PX_LIST = 'connect.paystack_extra.requests.get'


def listing(*items):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {'status': True, 'data': list(items)}
    return resp


class RoutingBase(MoneyBase):
    """A 100 KES charge with a booking refund and an overpayment refund open."""

    def setUp(self):
        super().setUp()
        # A shared (Redis) cache keeps the once-a-day alert key from an earlier test that used the same payment id.
        cache.clear()
        self.b = self.booking(1, 'cancelled')
        self.pay = Payment.objects.create(
            booking=self.b, amount=Decimal('100'), method='digital',
            status='confirmed', provider_reference='CONNECT-9-' + 'a' * 32,
            refund_status='processing', refund_amount=Decimal('100'),
            refund_claimed_at=timezone.now() - dt.timedelta(hours=2),
            paid_amount=Decimal('150'))
        self.row = UnappliedPayment.objects.create(
            reference=self.pay.provider_reference, kind='booking',
            amount=Decimal('50'), currency='KES', reason='overpayment',
            status='refunding')
        UnappliedPayment.objects.filter(pk=self.row.pk).update(
            updated_at=timezone.now() - dt.timedelta(hours=2))

    def event(self, kind, rid=None, amount=None, extra=None):
        data = {'transaction_reference': self.pay.provider_reference}
        if rid is not None:
            data['refund_reference'] = rid
        if amount is not None:
            data['amount'] = amount
        data.update(extra or {})
        body = json.dumps({'event': f'refund.{kind}', 'data': data}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return self.client.post(
            '/api/bookings/webhooks/paystack/refund/', data=body,
            content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)

    def reload(self):
        self.pay.refresh_from_db()
        self.row.refresh_from_db()


class RefundWebhookRoutingTests(RoutingBase):
    def test_refund_webhook_routes_by_refund_id_first(self):
        Payment.objects.filter(pk=self.pay.pk).update(refund_reference='11')
        UnappliedPayment.objects.filter(pk=self.row.pk).update(refund_reference='12')
        # The amount is the booking refund's, but the id says it is the row's.
        self.assertEqual(self.event('processed', '12', 10000).status_code, 200)
        self.reload()
        self.assertEqual(self.row.refund_status, 'processed')
        self.assertEqual(self.pay.refund_status, 'processing')

    def test_refund_webhook_for_the_booking_refund_leaves_the_row_alone(self):
        Payment.objects.filter(pk=self.pay.pk).update(refund_reference='11')
        UnappliedPayment.objects.filter(pk=self.row.pk).update(refund_reference='12')
        self.event('processed', '11', 5000)
        self.reload()
        self.assertEqual(self.pay.refund_status, 'processed')
        self.assertEqual(self.row.refund_status, '')

    def test_refund_webhook_falls_back_to_amount_when_ids_are_unknown(self):
        self.event('processed', 'new-id', 5000)
        self.reload()
        self.assertEqual((self.row.refund_status, self.row.refund_reference),
                         ('processed', 'new-id'))
        self.assertEqual(self.pay.refund_status, 'processing')
        self.event('processed', 'other-id', 10000)
        self.reload()
        self.assertEqual((self.pay.refund_status, self.pay.refund_reference),
                         ('processed', 'other-id'))

    def test_ambiguous_event_touches_nothing_and_alerts_once(self):
        Payment.objects.filter(pk=self.pay.pk).update(refund_amount=Decimal('50'))
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                self.assertEqual(self.event('processed', 'x', 5000).status_code, 200)
        self.reload()
        self.assertEqual(self.pay.refund_status, 'processing')
        self.assertEqual(self.row.refund_status, '')
        self.assertEqual(self.alert.call_count, 1)

    def test_failed_refund_on_the_row_goes_to_review_and_alerts(self):
        UnappliedPayment.objects.filter(pk=self.row.pk).update(refund_reference='12')
        with self.captureOnCommitCallbacks(execute=True):
            self.event('failed', '12', 5000)
        self.reload()
        self.assertEqual((self.row.status, self.row.refund_status), ('review', 'failed'))
        self.assertEqual(self.pay.refund_status, 'processing')
        self.assertEqual(self.alert.call_count, 1)

    def test_a_processed_row_is_never_downgraded(self):
        UnappliedPayment.objects.filter(pk=self.row.pk).update(
            refund_reference='12', refund_status='processed', status='refunded')
        self.event('pending', '12', 5000)
        self.row.refresh_from_db()
        self.assertEqual(self.row.refund_status, 'processed')

    def test_without_an_unapplied_row_the_payment_is_updated_as_before(self):
        UnappliedPayment.objects.all().delete()
        self.event('processed', 'r-1', 10000)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.refund_status, 'processed')


class ReconcileRoutingTests(RoutingBase):
    def reconcile(self, *items):
        with mock.patch(LIST, return_value=listing(*items)):
            call_command('reconcile_refunds', stdout=StringIO(), stderr=StringIO())

    def test_reconcile_two_refunds_one_transaction_not_odd(self):
        self.reconcile(
            {'id': 12, 'status': 'pending', 'amount': 5000},
            {'id': 11, 'status': 'processed', 'amount': 10000})
        self.pay.refresh_from_db()
        self.assertEqual(
            (self.pay.refund_status, self.pay.refund_reference), ('processed', '11'))
        self.assertEqual(self.alert.call_count, 0)

    def test_reconcile_picks_the_stored_refund_id_even_when_amounts_tie(self):
        Payment.objects.filter(pk=self.pay.pk).update(
            refund_amount=Decimal('50'), refund_reference='11')
        UnappliedPayment.objects.filter(pk=self.row.pk).update(refund_reference='12')
        self.reconcile(
            {'id': 12, 'status': 'pending', 'amount': 5000},
            {'id': 11, 'status': 'processed', 'amount': 5000})
        self.pay.refresh_from_db()
        self.assertEqual((self.pay.refund_status, self.pay.refund_reference),
                         ('processed', '11'))

    def test_reconcile_flags_a_tie_it_cannot_resolve(self):
        Payment.objects.filter(pk=self.pay.pk).update(refund_amount=Decimal('50'))
        self.reconcile(
            {'id': 12, 'status': 'pending', 'amount': 5000},
            {'id': 11, 'status': 'processed', 'amount': 5000})
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.refund_status, 'processing')
        self.assertEqual(self.alert.call_count, 1)

    def test_unapplied_reconcile_ignores_the_booking_refund(self):
        with mock.patch(PX_LIST, return_value=listing(
                {'id': 11, 'status': 'processed', 'amount': 10000},
                {'id': 12, 'status': 'pending', 'amount': 5000})):
            call_command('process_unapplied', stdout=StringIO(), stderr=StringIO())
        self.row.refresh_from_db()
        self.assertEqual(
            (self.row.status, self.row.refund_status, self.row.refund_reference),
            ('refunded', 'pending', '12'))

    def test_unapplied_reconcile_does_not_claim_the_booking_refund_as_its_own(self):
        with mock.patch(PX_LIST, return_value=listing(
                {'id': 11, 'status': 'processed', 'amount': 10000})):
            call_command('process_unapplied', stdout=StringIO(), stderr=StringIO())
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'review')
