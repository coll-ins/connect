import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import UnappliedPayment
from bookings.tests.test_round5 import _paystack_ok
from charters.services import CharterError
from connect import paystack_extra as px
from deliveries.services import ParcelError

PARCEL = 'PCL-501-ABCDEFGHJK'
CHARTER = 'CHT-502-ABCDEFGHJK'
ALERT = 'notifications.sms.send_admin_alert_sms'


def _data(reference, **extra):
    return {'reference': reference, 'amount': 80000, 'currency': 'KES', **extra}


class WebhookRecordingTests(TestCase):
    def _handle(self, exc, reference=PARCEL, data=None):
        data = data or _data(reference)
        with patch('connect.paystack_extra.apply_charge', side_effect=exc), \
                patch(ALERT) as alert, \
                patch('connect.paystack_extra.requests.post') as post:
            result = px.handle_extra_charge(reference, data)
        post.assert_not_called()      # the webhook never calls Paystack to refund
        return result, alert

    def test_business_rejection_is_queued_for_refund(self):
        result, alert = self._handle(ParcelError('Parcel is not awaiting payment.', 409))
        self.assertTrue(result)
        row = UnappliedPayment.objects.get(reference=PARCEL)
        self.assertEqual(row.status, 'refund_due')
        self.assertEqual(row.kind, 'parcel')
        self.assertEqual(row.amount, Decimal('800.00'))
        alert.assert_called_once()
        self.assertIn('received but NOT applied', alert.call_args.args[0])

    def test_charter_rejection_is_queued_for_refund(self):
        self._handle(CharterError('That bus is already booked for those dates.', 409), reference=CHARTER)
        row = UnappliedPayment.objects.get(reference=CHARTER)
        self.assertEqual((row.status, row.kind), ('refund_due', 'charter'))

    def test_duplicate_delivery_records_and_alerts_once(self):
        exc = ParcelError('Paid amount does not match the parcel price.', 409)
        self._handle(exc)
        _, second_alert = self._handle(exc)
        self.assertEqual(UnappliedPayment.objects.filter(reference=PARCEL).count(), 1)
        second_alert.assert_not_called()

    def test_transient_error_is_queued_for_retry(self):
        self._handle(RuntimeError('lock timeout'))
        self.assertEqual(UnappliedPayment.objects.get(reference=PARCEL).status, 'retry')

    def test_wrong_currency_goes_to_a_human(self):
        self._handle(px.GatewayError('Unexpected currency.', 409), data=_data(PARCEL, currency='USD'))
        self.assertEqual(UnappliedPayment.objects.get(reference=PARCEL).status, 'review')

    def test_unknown_parcel_goes_to_a_human(self):
        reference = 'PCL-999999-ABCDEFGHJK'
        with patch(ALERT):
            px.handle_extra_charge(reference, _data(reference))
        self.assertEqual(UnappliedPayment.objects.get(reference=reference).status, 'review')

    def test_replay_after_refund_never_reapplies(self):
        UnappliedPayment.objects.create(
            reference=PARCEL, kind='parcel', amount=Decimal('800.00'),
            payload=_data(PARCEL), status='refunded',
        )
        with patch('connect.paystack_extra.apply_charge') as apply:
            self.assertTrue(px.handle_extra_charge(PARCEL, _data(PARCEL)))
        apply.assert_not_called()

    def test_replay_of_a_retry_row_that_now_succeeds_marks_applied(self):
        row = UnappliedPayment.objects.create(
            reference=PARCEL, kind='parcel', amount=Decimal('800.00'),
            payload=_data(PARCEL), status='retry',
        )
        with patch('connect.paystack_extra.apply_charge', return_value=(None, True)):
            px.handle_extra_charge(PARCEL, _data(PARCEL))
        row.refresh_from_db()
        self.assertEqual(row.status, 'applied')


class ProcessUnappliedTests(TestCase):
    def _row(self, status='refund_due', reference=PARCEL, **extra):
        return UnappliedPayment.objects.create(
            reference=reference, kind='parcel', amount=Decimal('800.00'), currency='KES',
            reason='test', payload=_data(reference), status=status, **extra,
        )

    def _run(self):
        out = io.StringIO()
        call_command('process_unapplied', stdout=out, stderr=io.StringIO())
        return out.getvalue()

    def test_refund_due_is_sent_exactly_once(self):
        row = self._row()
        with patch('connect.paystack_extra.requests.post', return_value=_paystack_ok(55)) as post, patch(ALERT):
            self._run()
            self._run()
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['transaction'], PARCEL)
        self.assertEqual(post.call_args.kwargs['json']['amount'], 80000)
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunded')
        self.assertEqual(row.refund_status, 'pending')
        self.assertEqual(row.refund_reference, '55')

    def test_refused_refund_goes_to_a_human(self):
        row = self._row()
        refused = MagicMock()
        refused.status_code = 400
        refused.json.return_value = {'status': False, 'message': 'Transaction already reversed'}
        with patch('connect.paystack_extra.requests.post', return_value=refused), patch(ALERT) as alert:
            output = self._run()
        row.refresh_from_db()
        self.assertEqual(row.status, 'review')
        alert.assert_called_once()
        self.assertIn('NEEDS A HUMAN', output)

    def test_uncertain_refund_is_never_resent(self):
        row = self._row()
        with patch('connect.paystack_extra.requests.post',
                   side_effect=requests.ConnectionError('timeout')) as post, patch(ALERT) as alert:
            self._run()
            self._run()
        post.assert_called_once()
        alert.assert_called_once()
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunding')

    def test_retry_that_succeeds_is_applied(self):
        row = self._row(status='retry')
        with patch('connect.paystack_extra.apply_charge', return_value=(None, True)):
            self._run()
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts), ('applied', 1))

    def test_retry_that_hits_a_business_rejection_is_refunded_in_the_same_run(self):
        row = self._row(status='retry')
        with patch('connect.paystack_extra.apply_charge',
                   side_effect=ParcelError('Parcel is not awaiting payment.', 409)), \
                patch('connect.paystack_extra.requests.post', return_value=_paystack_ok(56)), \
                patch(ALERT):
            self._run()
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunded')

    def test_retry_gives_up_after_five_attempts(self):
        row = self._row(status='retry', attempts=4)
        with patch('connect.paystack_extra.apply_charge', side_effect=RuntimeError('still down')), \
                patch(ALERT) as alert:
            self._run()
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts), ('review', 5))
        alert.assert_called_once()

    def _stuck(self, minutes_ago=120):
        row = self._row(status='refunding')
        UnappliedPayment.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - timedelta(minutes=minutes_ago))
        return row

    def _listing(self, data):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {'status': True, 'data': data}
        return response

    def test_stuck_refund_found_at_paystack_is_recorded(self):
        row = self._stuck()
        with patch('connect.paystack_extra.requests.get',
                   return_value=self._listing([{'id': 9, 'status': 'processed'}])):
            self._run()
        row.refresh_from_db()
        self.assertEqual((row.status, row.refund_status, row.refund_reference), ('refunded', 'processed', '9'))

    def test_stuck_refund_missing_at_paystack_goes_to_a_human_not_resent(self):
        row = self._stuck()
        with patch('connect.paystack_extra.requests.get', return_value=self._listing([])), \
                patch('connect.paystack_extra.requests.post') as post, patch(ALERT) as alert:
            self._run()
        post.assert_not_called()
        alert.assert_called_once()
        row.refresh_from_db()
        self.assertEqual(row.status, 'review')

    def test_fresh_refunding_row_is_left_alone(self):
        row = self._stuck(minutes_ago=1)
        with patch('connect.paystack_extra.requests.get') as get:
            self._run()
        get.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunding')
