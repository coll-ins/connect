"""The 'Refund FAILED' admin SMS must leave only after the webhook's transaction commits."""
from decimal import Decimal
from unittest import mock

from bookings.models import Payment
from bookings.tests.test_refund_routing import RoutingBase


class RefundFailedAlertTests(RoutingBase):
    def setUp(self):
        super().setUp()
        # No open overpayment row, so the event is handled by the booking-refund branch.
        self.row.delete()

    def test_failed_refund_alert_is_deferred_to_commit_and_sent_once(self):
        with mock.patch('bookings.views.send_admin_alert_sms') as alert:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = self.event('failed')
            self.assertEqual(response.status_code, 200)
            alert.assert_not_called()
            for callback in callbacks:
                callback()
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.refund_status, 'failed')
        self.assertEqual(alert.call_count, 1)
        self.assertIn('Refund FAILED', alert.call_args.args[0])


class UnappliedRefundAlertTests(RoutingBase):
    def _deferred(self, send_event):
        with mock.patch('notifications.sms.send_admin_alert_sms') as alert:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                self.assertEqual(send_event().status_code, 200)
            alert.assert_not_called()
            for callback in callbacks:
                callback()
        self.assertEqual(alert.call_count, 1)
        return alert.call_args.args[0]

    def test_failed_unapplied_refund_alert_is_deferred_to_commit_and_sent_once(self):
        from bookings.models import UnappliedPayment
        UnappliedPayment.objects.filter(pk=self.row.pk).update(refund_reference='12')
        message = self._deferred(lambda: self.event('failed', '12', 5000))
        self.assertIn('FAILED at Paystack', message)

    def test_ambiguous_event_alert_is_deferred_to_commit_and_sent_once(self):
        Payment.objects.filter(pk=self.pay.pk).update(refund_amount=Decimal('50'))
        message = self._deferred(lambda: self.event('processed', 'x', 5000))
        self.assertIn('cannot be matched', message)
