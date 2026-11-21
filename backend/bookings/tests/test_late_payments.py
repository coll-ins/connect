"""Late payments, overpayment, review rows and unmatched charges (BE-1b)."""
import datetime as dt
import hashlib
import hmac
import itertools
import json
import uuid
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from bookings import services
from bookings.models import Booking, BookingHold, Payment, UnappliedPayment
from bookings.tests.test_seat_holds import SeatBase

SEC = dt.timedelta(seconds=1)


class FakePaystack:
    """Stands in for requests.post/get on the refund endpoint."""

    def __init__(self):
        self.ids = itertools.count(900)
        self.refunds = []

    def post(self, url, json=None, **kwargs):
        resp = mock.Mock(status_code=200)
        if url.endswith('/refund'):
            rid = next(self.ids)
            self.refunds.append((json['transaction'], json['amount'], rid))
            resp.json.return_value = {
                'status': True, 'data': {'id': rid, 'status': 'pending'}}
        else:
            resp.json.return_value = {'status': True, 'data': {
                'authorization_url': 'https://paystack.test/pay',
                'reference': (json or {}).get('reference')}}
        return resp


class MoneyBase(SeatBase):
    def setUp(self):
        super().setUp()
        self.gateway = FakePaystack()
        self.alert = mock.Mock()
        for target in ('bookings.views.send_admin_alert_sms',
                       'notifications.sms.send_admin_alert_sms'):
            patcher = mock.patch(target, self.alert)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch('requests.post', self.gateway.post)
        patcher.start()
        self.addCleanup(patcher.stop)

    def hook(self, reference, amount, currency='KES', event='charge.success'):
        data = {'reference': reference, 'currency': currency}
        if amount is not None:
            data['amount'] = amount
        body = json.dumps({'event': event, 'data': data}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return self.client.post(
            '/api/bookings/webhooks/paystack/', data=body,
            content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=sig)

    def pending(self, held_for, seats=1, user=None):
        booking = self.booking(
            seats, 'pending', timezone.now() + held_for, user=user)
        return booking, self.digital_payment(booking)

    def sweep(self):
        call_command('process_noshows', stdout=StringIO(), stderr=StringIO())

    def unapplied(self):
        call_command('process_unapplied', stdout=StringIO(), stderr=StringIO())


class LateRuleTests(MoneyBase):
    def test_payment_inside_the_tolerance_confirms(self):
        booking, pay = self.pending(-30 * SEC)
        self.assertEqual(self.hook(pay.provider_reference, 10000).status_code, 200)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(pay.refund_reason, '')
        self.assertEqual(self.gateway.refunds, [])

    def test_late_after_tolerance_refunded_even_if_seat_free(self):
        booking, pay = self.pending(-90 * SEC)
        self.assertEqual(self.hook(pay.provider_reference, 10000).status_code, 200)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(pay.status, 'confirmed')
        self.assertEqual(pay.refund_reason, 'late_payment')
        self.assertEqual(self.gateway.refunds, [(pay.provider_reference, 10000, 900)])
        self.assertFalse(BookingHold.objects.filter(booking=booking).exists())

    def test_on_time_but_seat_resold_refunded(self):
        booking, pay = self.pending(-30 * SEC, seats=2)
        self.booking(3, 'confirmed')
        self.hook(pay.provider_reference, 20000)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(pay.refund_reason, 'late_payment')
        self.assertEqual(len(self.gateway.refunds), 1)

    def test_tolerance_is_a_named_setting(self):
        booking, pay = self.pending(-30 * SEC)
        with override_settings(PAYMENT_ARRIVAL_TOLERANCE_SECONDS=0):
            self.hook(pay.provider_reference, 10000)
        pay.refresh_from_db()
        self.assertEqual(pay.refund_reason, 'late_payment')

    def test_unstamped_hold_is_never_late(self):
        booking = self.booking(1, 'pending', None)
        pay = self.digital_payment(booking)
        self.hook(pay.provider_reference, 10000)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')

    def test_payment_for_a_cancelled_booking_is_marked_for_refund(self):
        booking, pay = self.pending(5 * 60 * SEC)
        Booking.objects.filter(pk=booking.pk).update(status='cancelled')
        self.hook(pay.provider_reference, 10000)
        pay.refresh_from_db()
        self.assertEqual(pay.refund_reason, 'late_payment')
        self.assertEqual(len(self.gateway.refunds), 1)


class LateSweepTests(MoneyBase):
    def crash_after_commit(self, pay_ref, amount=10000):
        """The webhook commits, then the process dies before the refund call."""
        with mock.patch('bookings.views.settle_booking_fault'):
            self.hook(pay_ref, amount)

    def test_late_payment_sweep_refunds_after_crash(self):
        booking, pay = self.pending(-90 * SEC)
        self.crash_after_commit(pay.provider_reference)
        pay.refresh_from_db()
        self.assertEqual(
            (pay.status, pay.refund_status, pay.refund_reason),
            ('confirmed', 'not_requested', 'late_payment'))
        self.assertEqual(self.gateway.refunds, [])
        self.sweep()
        pay.refresh_from_db()
        self.assertEqual(pay.refund_status, 'pending')
        self.assertEqual(pay.refund_amount, Decimal('100.00'))
        self.assertEqual(len(self.gateway.refunds), 1)
        self.sweep()
        self.assertEqual(len(self.gateway.refunds), 1)

    def test_sweep_covers_boarding_and_cancelled_trips(self):
        for trip_status in ('boarding', 'cancelled', 'departed'):
            self.gateway.refunds.clear()
            booking, pay = self.pending(-90 * SEC)
            self.crash_after_commit(pay.provider_reference)
            self.trip.status = trip_status
            self.trip.save(update_fields=['status'])
            self.sweep()
            pay.refresh_from_db()
            self.assertEqual(pay.refund_status, 'pending', trip_status)
            self.assertEqual(len(self.gateway.refunds), 1, trip_status)
            Payment.objects.filter(pk=pay.pk).delete()
            Booking.objects.filter(pk=booking.pk).delete()

    def test_sweep_retries_a_refund_paystack_refused(self):
        booking, pay = self.pending(-90 * SEC)
        refused = mock.Mock(status_code=400)
        refused.json.return_value = {'status': False, 'message': 'no'}
        with mock.patch('requests.post', return_value=refused):
            self.hook(pay.provider_reference, 10000)
        pay.refresh_from_db()
        self.assertEqual(pay.refund_status, 'not_requested')
        self.sweep()
        pay.refresh_from_db()
        self.assertEqual(pay.refund_status, 'pending')

    def test_sweep_leaves_a_deliberately_small_passenger_refund_alone(self):
        booking = self.booking(1, 'cancelled')
        Booking.objects.filter(pk=booking.pk).update(total_amount=Decimal('8'))
        Payment.objects.create(
            booking=booking, amount=Decimal('8'), method='digital',
            status='confirmed', provider_reference='CONNECT-x-1',
            refund_amount=Decimal('4.00'), refund_status='not_requested')
        self.sweep()
        self.assertEqual(self.gateway.refunds, [])

    def test_sweep_ignores_a_confirmed_booking_without_a_reason(self):
        booking = self.booking(1, 'cancelled')
        Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='confirmed', provider_reference='CONNECT-x-2')
        self.sweep()
        self.assertEqual(self.gateway.refunds, [])

    def test_sweep_alerts_once_when_it_cannot_refund(self):
        booking, pay = self.pending(-90 * SEC)
        self.crash_after_commit(pay.provider_reference)
        refused = mock.Mock(status_code=400)
        refused.json.return_value = {'status': False, 'message': 'no'}
        with mock.patch('requests.post', return_value=refused):
            self.sweep()
            self.sweep()
        self.assertEqual(self.alert.call_count, 1)


class GetStatusNeverRefundsTests(MoneyBase):
    def verify_ok(self, amount):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {'status': True, 'data': {
            'status': 'success', 'amount': amount, 'currency': 'KES'}}
        return ok

    def test_status_poll_confirms_a_late_payment_but_leaves_the_refund_to_the_sweep(self):
        booking, pay = self.pending(-90 * SEC, user=self.passenger)
        self.client.force_authenticate(self.passenger)
        with mock.patch('bookings.views.requests.get',
                        return_value=self.verify_ok(10000)):
            resp = self.client.get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(resp.status_code, 200, resp.content)
        pay.refresh_from_db()
        self.assertEqual((pay.status, pay.refund_reason), ('confirmed', 'late_payment'))
        self.assertEqual(self.gateway.refunds, [])
        self.sweep()
        self.assertEqual(len(self.gateway.refunds), 1)

    def test_status_poll_does_not_send_an_overpayment_refund(self):
        booking, pay = self.pending(5 * 60 * SEC, user=self.passenger)
        self.client.force_authenticate(self.passenger)
        with mock.patch('bookings.views.requests.get',
                        return_value=self.verify_ok(15000)):
            self.client.get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(self.gateway.refunds, [])
        self.unapplied()
        self.assertEqual(len(self.gateway.refunds), 1)

    def test_status_poll_uses_the_verify_timeout_setting(self):
        booking, pay = self.pending(5 * 60 * SEC, user=self.passenger)
        self.client.force_authenticate(self.passenger)
        with mock.patch('bookings.views.requests.get',
                        return_value=self.verify_ok(10000)) as get:
            self.client.get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(get.call_args.kwargs['timeout'], 10)
        with override_settings(PAYMENT_STATUS_VERIFY_TIMEOUT_SECONDS=4), \
                mock.patch('bookings.views.requests.get',
                           return_value=self.verify_ok(10000)) as get:
            Payment.objects.filter(pk=pay.pk).update(status='pending')
            self.client.get(f'/api/bookings/payments/{booking.id}/status/')
        self.assertEqual(get.call_args.kwargs['timeout'], 4)


class OverpaymentTests(MoneyBase):
    def test_overpayment_confirms_and_refunds_difference_once(self):
        booking, pay = self.pending(5 * 60 * SEC)
        self.assertEqual(self.hook(pay.provider_reference, 15000).status_code, 200)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual((pay.status, pay.amount, pay.paid_amount),
                         ('confirmed', Decimal('100.00'), Decimal('150.00')))
        row = UnappliedPayment.objects.get()
        self.assertEqual(
            (row.kind, row.reference, row.amount, row.reason, row.status),
            ('booking', pay.provider_reference, Decimal('50.00'),
             'overpayment', 'refunded'))
        self.assertEqual(self.gateway.refunds, [(pay.provider_reference, 5000, 900)])

    def test_overpayment_replay_one_refund(self):
        booking, pay = self.pending(5 * 60 * SEC)
        for _ in range(3):
            self.hook(pay.provider_reference, 15000)
        self.assertEqual(UnappliedPayment.objects.count(), 1)
        self.assertEqual(len(self.gateway.refunds), 1)
        self.unapplied()
        self.assertEqual(len(self.gateway.refunds), 1)

    def test_overpayment_refund_survives_a_crash(self):
        booking, pay = self.pending(5 * 60 * SEC)
        with mock.patch('connect.paystack_extra.claim_refund', return_value=False):
            self.hook(pay.provider_reference, 15000)
        self.assertEqual(UnappliedPayment.objects.get().status, 'refund_due')
        self.assertEqual(self.gateway.refunds, [])
        self.unapplied()
        self.assertEqual(self.gateway.refunds, [(pay.provider_reference, 5000, 900)])

    def test_overpaid_and_late_refunds_exactly_paid(self):
        booking, pay = self.pending(-90 * SEC)
        self.hook(pay.provider_reference, 15000)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual(booking.status, 'cancelled')
        paid, refunded = services.charge_refund_totals(pay)
        self.assertEqual((paid, refunded), (Decimal('150.00'), Decimal('150.00')))

    def test_overpaid_late_and_crashed_still_refunds_exactly_paid(self):
        booking, pay = self.pending(-90 * SEC)
        with mock.patch('bookings.views.settle_booking_fault'), \
                mock.patch('connect.paystack_extra.claim_refund', return_value=False):
            self.hook(pay.provider_reference, 15000)
        self.sweep()
        self.unapplied()
        pay.refresh_from_db()
        self.assertEqual(sorted(r[1] for r in self.gateway.refunds), [5000, 10000])
        self.assertEqual(services.charge_refund_totals(pay),
                         (Decimal('150.00'), Decimal('150.00')))

    def test_overpayment_below_the_refund_minimum_goes_to_review(self):
        booking, pay = self.pending(5 * 60 * SEC)
        self.hook(pay.provider_reference, 10300)
        row = UnappliedPayment.objects.get()
        self.assertEqual((row.status, row.amount), ('review', Decimal('3.00')))
        self.assertEqual(self.gateway.refunds, [])
        self.assertEqual(self.alert.call_count, 1)

    def test_duplicate_charge_with_a_new_reference_is_refunded_in_full(self):
        booking, pay = self.pending(5 * 60 * SEC)
        self.hook(pay.provider_reference, 10000)
        dup = f'CONNECT-{booking.id}-{uuid.uuid4().hex}'
        self.hook(dup, 10000)
        self.unapplied()  # queued by the webhook, sent by the sweep
        row = UnappliedPayment.objects.get(reference=dup)
        self.assertEqual((row.kind, row.amount, row.status),
                         ('booking', Decimal('100.00'), 'refunded'))
        self.assertEqual(self.gateway.refunds[-1][:2], (dup, 10000))
        pay.refresh_from_db()
        self.assertEqual(pay.refund_status, 'not_requested')


class ReviewRowTests(MoneyBase):
    def test_underpayment_is_queued_for_refund(self):
        booking, pay = self.pending(5 * 60 * SEC)
        self.hook(pay.provider_reference, 5000)
        booking.refresh_from_db()
        pay.refresh_from_db()
        self.assertEqual((pay.status, booking.status), ('failed', 'pending'))
        row = UnappliedPayment.objects.get()
        self.assertEqual(
            (row.kind, row.status, row.amount, row.reference),
            ('booking', 'refund_due', Decimal('50.00'), pay.provider_reference))
        self.assertIn('amount', row.reason)
        self.assertEqual(self.gateway.refunds, [])
        self.assertEqual(self.alert.call_count, 1)
        self.unapplied()
        row.refresh_from_db()
        self.assertEqual(row.status, 'refunded')
        self.assertEqual(self.gateway.refunds[-1][:2], (pay.provider_reference, 5000))

    def test_amount_mismatch_creates_review_row_for_every_bad_shape(self):
        cases = [
            ('wrong currency', 10000, 'USD'),
            ('missing', None, 'KES'),
            ('unreadable', 'abc', 'KES'),
            ('overpaid in the wrong currency', 20000, 'USD'),
        ]
        for label, amount, currency in cases:
            booking, pay = self.pending(5 * 60 * SEC)
            self.hook(pay.provider_reference, amount, currency)
            row = UnappliedPayment.objects.get(reference=pay.provider_reference)
            self.assertEqual((row.kind, row.status), ('booking', 'review'), label)
            pay.refresh_from_db()
            self.assertEqual(pay.status, 'failed', label)
        self.assertEqual(self.gateway.refunds, [])

    def test_review_row_is_not_duplicated_or_re_alerted_by_a_replay(self):
        booking, pay = self.pending(5 * 60 * SEC)
        self.hook(pay.provider_reference, 5000)
        self.hook(pay.provider_reference, 5000)
        self.assertEqual(UnappliedPayment.objects.count(), 1)
        self.assertEqual(self.alert.call_count, 1)

    def test_process_unapplied_never_applies_a_booking_row_and_alerts_review(self):
        row = UnappliedPayment.objects.create(
            reference='CONNECT-1-' + 'a' * 32, kind='booking', status='review',
            amount=Decimal('50'), reason='amount mismatch')
        UnappliedPayment.objects.filter(pk=row.pk).update(
            updated_at=timezone.now() - dt.timedelta(hours=2))
        retry = UnappliedPayment.objects.create(
            reference='CONNECT-2-' + 'b' * 32, kind='booking', status='retry',
            amount=Decimal('50'))
        out = StringIO()
        with mock.patch('connect.paystack_extra.apply_charge') as apply:
            call_command('process_unapplied', stdout=out)
            call_command('process_unapplied', stdout=out)
        apply.assert_not_called()
        retry.refresh_from_db()
        self.assertEqual(retry.status, 'retry')
        self.assertIn('NEEDS A HUMAN', out.getvalue())
        review_alerts = [c for c in self.alert.call_args_list if row.reference in c.args[0]]
        self.assertEqual(len(review_alerts), 1)


class UnmatchedChargeTests(MoneyBase):
    def test_unmatched_connect_reference_refunded_once(self):
        ref = f'CONNECT-4242-{uuid.uuid4().hex}'
        for _ in range(3):
            self.assertEqual(self.hook(ref, 12000).status_code, 200)
        row = UnappliedPayment.objects.get()
        self.assertEqual(
            (row.kind, row.reference, row.amount, row.status),
            ('booking', ref, Decimal('120.00'), 'refund_due'))
        # Never inline: the webhook stays fast, the sweep sends it once.
        self.assertEqual(self.gateway.refunds, [])
        self.unapplied()
        self.unapplied()
        self.assertEqual(self.gateway.refunds, [(ref, 12000, 900)])
        self.assertEqual(self.alert.call_count, 1)

    def test_unmatched_charge_with_a_bad_amount_goes_to_review(self):
        ref = f'CONNECT-4242-{uuid.uuid4().hex}'
        self.hook(ref, 12000, currency='USD')
        row = UnappliedPayment.objects.get()
        self.assertEqual(row.status, 'review')
        self.assertEqual(self.gateway.refunds, [])

    def test_a_reference_that_is_not_ours_only_alerts(self):
        self.assertEqual(self.hook('SOMETHING-ELSE', 12000).status_code, 200)
        self.assertEqual(UnappliedPayment.objects.count(), 0)
        self.assertEqual(self.gateway.refunds, [])
        self.assertEqual(self.alert.call_count, 1)

    def test_refund_survives_a_crash_and_process_unapplied_sends_it(self):
        ref = f'CONNECT-4242-{uuid.uuid4().hex}'
        with mock.patch('connect.paystack_extra.claim_refund', return_value=False):
            self.hook(ref, 12000)
        self.assertEqual(self.gateway.refunds, [])
        self.unapplied()
        self.assertEqual(len(self.gateway.refunds), 1)
