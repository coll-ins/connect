"""A listed refund that names another transaction is never taken as ours."""
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from bookings.models import Payment
from bookings.tests.review_base import WorldMixin
from connect.paystack_extra import route_refund

OURS = 'CONNECT-1-' + 'a' * 32
OTHER = 'CONNECT-2-' + 'b' * 32


class RouteRefundTransactionTests(TestCase):
    def test_a_refund_naming_another_transaction_is_not_matched_by_id_or_amount(self):
        listed = [{'id': 7, 'amount': 5000, 'transaction_reference': OTHER}]
        self.assertEqual(route_refund(listed, 7, 5000, reference=OURS), ('none', None))
        self.assertEqual(route_refund(listed, None, 5000, reference=OURS), ('none', None))

    def test_a_refund_naming_our_transaction_is_matched(self):
        listed = [{'id': 7, 'amount': 5000, 'transaction_reference': OURS}]
        self.assertEqual(route_refund(listed, 7, 5000, reference=OURS), ('match', listed[0]))

    def test_a_refund_with_no_transaction_reference_keeps_the_old_behaviour(self):
        listed = [{'id': 7, 'amount': 5000}]
        self.assertEqual(route_refund(listed, 7, 5000, reference=OURS), ('match', listed[0]))
        self.assertEqual(route_refund(listed, None, 5000, reference=OURS), ('match', listed[0]))

    def test_the_foreign_refund_is_dropped_but_ours_still_wins_among_several(self):
        listed = [{'id': 7, 'amount': 5000, 'transaction_reference': OTHER},
                  {'id': 8, 'amount': 5000, 'transaction_reference': OURS}]
        self.assertEqual(route_refund(listed, None, 5000, reference=OURS), ('match', listed[1]))


class ReconcileRefundsTransactionTests(WorldMixin, TestCase):
    def run_reconcile(self, listed):
        b = self.booking(self.pax, self.trip1, 1, 'cancelled')
        pay = Payment.objects.create(
            booking=b, amount=Decimal('100'), method='digital', status='confirmed',
            provider_reference=OURS, refund_status='processing', refund_amount=Decimal('50.00'),
            refund_claimed_at=None)
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': True, 'data': listed}
        err = StringIO()
        with mock.patch('bookings.management.commands.reconcile_refunds.requests.get',
                        return_value=response):
            call_command('reconcile_refunds', '--min-age-minutes', '0', stdout=StringIO(), stderr=err)
        pay.refresh_from_db()
        return pay, err.getvalue()

    def test_a_foreign_refund_is_not_recorded_against_our_payment(self):
        pay, err = self.run_reconcile([{'id': 77, 'amount': 5000, 'status': 'processed',
                                        'transaction_reference': OTHER}])
        self.assertEqual(pay.refund_reference, None)
        self.assertEqual(pay.refund_status, 'processing')

    def test_our_refund_is_recorded(self):
        pay, err = self.run_reconcile([{'id': 78, 'amount': 5000, 'status': 'processed',
                                        'transaction_reference': OURS}])
        self.assertEqual(pay.refund_reference, '78')
