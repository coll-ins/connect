import datetime as dt
import threading
import unittest
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from wallets import payouts, services, sweeps, webhook
from wallets.gateway import (
    ACCEPTED, REFUSED, UNCERTAIN, FakeTransfers, GatewayRefused, PaystackTransfers, SendResult,
)
from wallets.models import Wallet, WalletPayout, WalletPayoutEvent, WalletTransaction

User = get_user_model()
POSTGRES = connection.vendor == 'postgresql'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
PHONE = '+254712345678'
KEY = 'key-0000-0001'


def make_user(name='wd1', phone=PHONE, role='passenger'):
    return User.objects.create_user(
        username=name, password='pw-123456', phone_number=phone, role=role)


def fund(user, amount, ref=None):
    from django.db import transaction
    with transaction.atomic():
        services.credit(user, Decimal(str(amount)), 'deposit', ref or f'topup:fund-{user.pk}-{amount}')


def balance(user):
    return Wallet.objects.get(user=user).available_balance


def event(kind, payout, amount=None, currency='KES', reference=None):
    amount = payout.amount if amount is None else Decimal(str(amount))
    return {'event': kind, 'data': {
        'reference': reference or payout.reference,
        'amount': int(amount * 100), 'currency': currency,
        'transfer_code': 'TRF_x', 'status': kind.split('.')[1]}}


class PayoutBase:
    """Fake gateway, no live HTTP, alerts captured, ledger invariants checked after every test."""

    def setUp(self):
        super().setUp()
        self.enterContext(override_settings(CACHES=LOCMEM))
        cache.clear()
        self.user = make_user()
        fund(self.user, '1000')
        self.gw = FakeTransfers()
        self.live_calls = []
        for p in (
            mock.patch('wallets.gateway.get_gateway', return_value=self.gw),
            mock.patch('wallets.alerts.send'),
            mock.patch('requests.Session.request', side_effect=self._no_live),
        ):
            m = p.start()
            self.addCleanup(p.stop)
            if p.attribute == 'send':
                self.alert = m
        self.addCleanup(self.check_invariants)

    def _no_live(self, *a, **kw):
        self.live_calls.append(a)
        raise AssertionError('live HTTP call in a test')

    def check_invariants(self):
        self.assertEqual(self.live_calls, [])
        for w in Wallet.objects.all():
            total = w.transactions.aggregate(s=Sum('amount'))['s'] or Decimal('0')
            self.assertEqual(w.available_balance, total, 'ledger sum != balance')
        for p in WalletPayout.objects.all():
            wd = WalletTransaction.objects.filter(reference=f'wd:{p.pk}')
            rev = WalletTransaction.objects.filter(reference=f'wdrev:{p.pk}')
            self.assertEqual(wd.count(), 1)
            self.assertEqual(wd.get().amount, -p.amount)
            self.assertEqual(rev.count(), 1 if p.status == 'failed' else 0, (p.pk, p.status))

    def new_payout(self, amount='100', key=KEY, status=None, age=None, user=None):
        user = user or self.user
        payout, _ = payouts.request_withdrawal(user, Decimal(amount), key)
        if status or age is not None:
            fields = {}
            if status:
                fields['status'] = status
            if age is not None:
                fields['created_at'] = timezone.now() - age
            WalletPayout.objects.filter(pk=payout.pk).update(**fields)
            payout.refresh_from_db()
        return payout


# ---------------------------------------------------------------- request flow

class RequestWithdrawalTests(PayoutBase, TestCase):
    def test_creates_payout_and_debit_with_unique_reference(self):
        p, created = payouts.request_withdrawal(self.user, Decimal('250.50'), KEY)
        self.assertTrue(created)
        self.assertEqual((p.status, p.amount, p.destination_phone), ('requested', Decimal('250.50'), PHONE))
        self.assertRegex(p.reference, r'^wd-[0-9a-f]{32}$')
        row = WalletTransaction.objects.get(reference=f'wd:{p.pk}')
        self.assertEqual((row.type, row.amount), ('withdrawal', Decimal('-250.50')))
        self.assertEqual(balance(self.user), Decimal('749.50'))
        self.assertEqual(self.gw.calls, [])  # request step never calls the gateway

    def test_destination_is_snapshot_of_canonical_account_phone(self):
        user = make_user('wd2', '0722000111')
        fund(user, '500')
        p, _ = payouts.request_withdrawal(user, Decimal('100'), KEY)
        self.assertEqual(p.destination_phone, '+254722000111')

    def test_replay_same_key_returns_same_payout_without_second_debit(self):
        p1, c1 = payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        p2, c2 = payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        self.assertEqual((c1, c2, p1.pk), (True, False, p2.pk))
        self.assertEqual(WalletPayout.objects.count(), 1)
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_same_key_other_amount_409(self):
        payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(self.user, Decimal('101'), KEY)
        self.assertEqual((cm.exception.code, cm.exception.http_status), ('key_reused', 409))
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_same_key_other_user_is_a_different_payout(self):
        other = make_user('wd3', '+254700000333')
        fund(other, '500')
        a, _ = payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        b, created = payouts.request_withdrawal(other, Decimal('100'), KEY)
        self.assertTrue(created)
        self.assertNotEqual(a.pk, b.pk)

    def test_one_payout_in_flight_per_user(self):
        payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(self.user, Decimal('100'), 'key-0000-0002')
        self.assertEqual((cm.exception.code, cm.exception.http_status), ('payout_in_flight', 409))
        self.assertEqual(WalletPayout.objects.count(), 1)

    def test_next_payout_allowed_once_previous_is_final(self):
        self.new_payout('100', status='paid')
        p, created = payouts.request_withdrawal(self.user, Decimal('100'), 'key-0000-0002')
        self.assertTrue(created)

    def test_insufficient_funds_creates_nothing(self):
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(self.user, Decimal('1000.01'), KEY)
        self.assertEqual((cm.exception.code, cm.exception.http_status), ('insufficient_funds', 400))
        self.assertEqual(WalletPayout.objects.count(), 0)
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_exact_balance_allowed_and_leaves_zero(self):
        payouts.request_withdrawal(self.user, Decimal('1000'), KEY)
        self.assertEqual(balance(self.user), Decimal('0.00'))

    def test_no_wallet_row_means_insufficient_funds_and_no_wallet_created(self):
        user = make_user('wd4', '+254700000444')
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(user, Decimal('100'), KEY)
        self.assertEqual(cm.exception.code, 'insufficient_funds')
        self.assertFalse(Wallet.objects.filter(user=user).exists())

    def test_limits_min_max_and_bad_amounts(self):
        fund(self.user, '30000')
        cases = {'49.99': 'amount_too_small', '20000.01': 'amount_too_large', '0': 'invalid_amount'}
        for amount, code in cases.items():
            with self.assertRaises(payouts.WithdrawalError) as cm:
                payouts.request_withdrawal(self.user, Decimal(amount), KEY)
            self.assertEqual((cm.exception.code, cm.exception.http_status), (code, 400), amount)
        for bad in (Decimal('NaN'), Decimal('Infinity'), Decimal('-100'), Decimal('100.123'), 100.0, None, True):
            with self.assertRaises(payouts.WithdrawalError) as cm:
                payouts.request_withdrawal(self.user, bad, KEY)
            self.assertEqual(cm.exception.code, 'invalid_amount', bad)
        self.assertEqual(WalletPayout.objects.count(), 0)

    def test_boundaries_accepted(self):
        fund(self.user, '30000')
        payouts.request_withdrawal(self.user, Decimal('50'), 'key-0000-0001')
        WalletPayout.objects.update(status='paid')
        payouts.request_withdrawal(self.user, Decimal('20000'), 'key-0000-0002')

    def test_user_without_usable_phone_is_refused(self):
        User.objects.filter(pk=self.user.pk).update(phone_number='12345')
        self.user.refresh_from_db()
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        self.assertEqual(cm.exception.code, 'invalid_phone')
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_non_passenger_refused_at_service(self):
        driver = make_user('drv', '+254700000555', role='driver')
        fund(driver, '500')
        with self.assertRaises(payouts.WithdrawalError) as cm:
            payouts.request_withdrawal(driver, Decimal('100'), KEY)
        self.assertEqual((cm.exception.code, cm.exception.http_status), ('passenger_only', 403))

    def test_audit_event_for_creation(self):
        p, _ = payouts.request_withdrawal(self.user, Decimal('100'), KEY)
        ev = WalletPayoutEvent.objects.get(payout=p)
        self.assertEqual((ev.from_status, ev.to_status), ('', 'requested'))


class DailyLimitTests(PayoutBase, TestCase):
    def setUp(self):
        super().setUp()
        fund(self.user, '60000')

    def _wd(self, amount, key):
        return payouts.request_withdrawal(self.user, Decimal(str(amount)), key)

    def test_rolling_24h_sum_blocks_over_limit(self):
        self.new_payout('20000', key='key-0000-0001', status='paid', age=dt.timedelta(hours=23))
        with self.assertRaises(payouts.WithdrawalError) as cm:
            self._wd('10000.01', 'key-0000-0002')
        self.assertEqual((cm.exception.code, cm.exception.http_status), ('daily_limit', 400))
        self.assertEqual(cm.exception.extra['remaining'], '10000.00')

    def test_exactly_the_limit_is_allowed(self):
        self.new_payout('20000', key='key-0000-0001', status='paid', age=dt.timedelta(hours=1))
        self._wd('10000', 'key-0000-0002')

    def test_old_payouts_roll_out_of_the_window(self):
        self.new_payout('20000', key='key-0000-0001', status='paid', age=dt.timedelta(hours=24, minutes=1))
        self._wd('20000', 'key-0000-0002')

    def test_failed_payouts_do_not_count(self):
        p = self.new_payout('20000', key='key-0000-0001')
        payouts.fail_and_reverse(p.pk, 'test', allowed_from=('requested',))
        self._wd('20000', 'key-0000-0002')

    def test_paid_review_and_in_flight_all_count_failed_does_not(self):
        self.new_payout('100', key='key-0000-0001', status='paid')
        self.new_payout('200', key='key-0000-0002', status='review')
        gone = self.new_payout('400', key='key-0000-0003')
        payouts.fail_and_reverse(gone.pk, 'x', allowed_from=('requested',))
        self.new_payout('800', key='key-0000-0004', status='submitted')
        self.assertEqual(payouts.rolling_total(self.user), Decimal('1100.00'))


# ---------------------------------------------------------------- dispatch

class DispatchTests(PayoutBase, TransactionTestCase):
    def test_debit_committed_before_gateway_call_and_no_atomic(self):
        seen = {}

        def on_send(payout):
            seen['atomic'] = connection.in_atomic_block
            seen['ledger'] = list(WalletTransaction.objects.filter(
                reference=f'wd:{payout.pk}').values_list('amount', flat=True))
            seen['balance'] = balance(self.user)
            seen['status'] = WalletPayout.objects.get(pk=payout.pk).status
        self.gw.on_send = on_send
        p, _ = payouts.withdraw(self.user, Decimal('300'), KEY)
        self.assertEqual(seen, {'atomic': False, 'ledger': [Decimal('-300.00')],
                                'balance': Decimal('700.00'), 'status': 'requested'})
        self.assertEqual([c['name'] for c in self.gw.calls], ['ensure_recipient', 'send'])
        self.assertTrue(all(c['atomic'] is False for c in self.gw.calls))

    def test_gateway_gets_exact_amount_and_account_phone_fee_borne_by_connect(self):
        p, _ = payouts.withdraw(self.user, Decimal('300.25'), KEY)
        self.assertEqual(self.gw.calls[0]['args'], (PHONE,))
        send = self.gw.calls[1]
        self.assertEqual((send['payout_amount'], send['reference']), (Decimal('300.25'), p.reference))
        self.assertEqual(WalletTransaction.objects.get(reference=f'wd:{p.pk}').amount, Decimal('-300.25'))

    def test_accepted_goes_to_submitted_with_transfer_code(self):
        self.gw.send_results = [SendResult(ACCEPTED, 'TRF_abc')]
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual((p.status, p.gateway_transfer_code, p.attempts), ('submitted', 'TRF_abc', 1))
        self.assertEqual(
            list(p.events.order_by('id').values_list('from_status', 'to_status')),
            [('', 'requested'), ('requested', 'submitted')])

    def test_definite_refusal_reverses_exactly_once(self):
        self.gw.send_results = [SendResult(REFUSED, 'Recipient invalid')]
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual((p.status, p.failure_reason), ('failed', 'Recipient invalid'))
        self.assertEqual(balance(self.user), Decimal('1000.00'))
        payouts.fail_and_reverse(p.pk, 'again', allowed_from=('requested',))
        payouts.fail_and_reverse(p.pk, 'again', allowed_from=('requested', 'submitted', 'review'))
        self.assertEqual(WalletTransaction.objects.filter(type='withdrawal_reversal').count(), 1)
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_any_refusal_alerts_admin(self):
        self.gw.send_results = [SendResult(REFUSED, 'Invalid key')]
        payouts.withdraw(self.user, Decimal('100'), KEY)
        self.alert.assert_called_once()

    def test_float_refusal_alerts_admin(self):
        self.gw.send_results = [SendResult(REFUSED, 'Your balance is not enough to fulfil this request')]
        payouts.withdraw(self.user, Decimal('100'), KEY)
        self.assertTrue(any('balance' in str(c).lower() for c in self.alert.call_args_list))

    def test_recipient_failure_reverses_and_never_sends(self):
        self.gw.recipient_error = 'Invalid account'
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual(p.status, 'failed')
        self.assertEqual([c['name'] for c in self.gw.calls], ['ensure_recipient'])
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_timeout_never_reverses_stays_requested(self):
        self.gw.send_results = [SendResult(UNCERTAIN, 'timeout')]
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual(p.status, 'requested')
        self.assertEqual(balance(self.user), Decimal('900.00'))
        self.assertFalse(WalletTransaction.objects.filter(type='withdrawal_reversal').exists())

    def test_unexpected_exception_in_send_is_treated_as_uncertain(self):
        self.gw.send_results = [RuntimeError('boom')]
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual(p.status, 'requested')
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_replay_never_sends_twice(self):
        payouts.withdraw(self.user, Decimal('100'), KEY)
        payouts.withdraw(self.user, Decimal('100'), KEY)
        self.assertEqual(sum(1 for c in self.gw.calls if c['name'] == 'send'), 1)

    def test_replay_of_uncertain_payout_does_not_resend(self):
        self.gw.send_results = [SendResult(UNCERTAIN, 'timeout')]
        payouts.withdraw(self.user, Decimal('100'), KEY)
        payouts.withdraw(self.user, Decimal('100'), KEY)
        self.assertEqual(sum(1 for c in self.gw.calls if c['name'] == 'send'), 1)

    def test_dispatch_does_not_clobber_a_webhook_that_won_the_race(self):
        def on_send(payout):
            webhook.handle_event(event('transfer.success', payout))
        self.gw.on_send = on_send
        p, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        p.refresh_from_db()
        self.assertEqual(p.status, 'paid')


# ---------------------------------------------------------------- webhook

@override_settings(WALLET_PAYOUTS_ENABLED=False)
class TransferWebhookTests(PayoutBase, TestCase):
    """The flag is OFF in this class: transfer.* handling must run anyway (M6)."""

    def setUp(self):
        super().setUp()
        self.p = self.new_payout('100', status='submitted')

    def test_success_marks_paid_and_replay_is_idempotent(self):
        self.assertTrue(webhook.handle_event(event('transfer.success', self.p)))
        self.assertTrue(webhook.handle_event(event('transfer.success', self.p)))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'paid')
        self.assertEqual(self.p.events.filter(to_status='paid').count(), 1)
        self.assertEqual(a_note(self.p), 'webhook transfer.success')
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_failed_reverses_once_across_replays(self):
        for _ in range(3):
            self.assertTrue(webhook.handle_event(event('transfer.failed', self.p)))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'failed')
        self.assertEqual(WalletTransaction.objects.filter(type='withdrawal_reversal').count(), 1)
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_reversed_reverses_once(self):
        for _ in range(2):
            webhook.handle_event(event('transfer.reversed', self.p))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'failed')
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_reversed_after_paid_reverses_once(self):
        webhook.handle_event(event('transfer.success', self.p))
        webhook.handle_event(event('transfer.reversed', self.p))
        webhook.handle_event(event('transfer.reversed', self.p))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'failed')
        self.assertEqual(WalletTransaction.objects.filter(type='withdrawal_reversal').count(), 1)
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_failed_after_paid_alerts_and_changes_nothing(self):
        webhook.handle_event(event('transfer.success', self.p))
        self.alert.reset_mock()
        self.assertTrue(webhook.handle_event(event('transfer.failed', self.p)))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'paid')
        self.assertEqual(balance(self.user), Decimal('900.00'))
        self.alert.assert_called()

    def test_success_after_failed_alerts_and_does_not_claw_back(self):
        webhook.handle_event(event('transfer.failed', self.p))
        self.alert.reset_mock()
        webhook.handle_event(event('transfer.success', self.p))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'failed')
        self.assertEqual(balance(self.user), Decimal('1000.00'))
        self.alert.assert_called()

    def test_success_on_review_row_marks_paid(self):
        WalletPayout.objects.filter(pk=self.p.pk).update(status='review')
        webhook.handle_event(event('transfer.success', self.p))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'paid')

    def test_failed_on_review_row_reverses(self):
        WalletPayout.objects.filter(pk=self.p.pk).update(status='review')
        webhook.handle_event(event('transfer.failed', self.p))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'failed')

    def test_amount_mismatch_alerts_and_changes_nothing(self):
        self.assertTrue(webhook.handle_event(event('transfer.failed', self.p, amount='99')))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'submitted')
        self.assertEqual(balance(self.user), Decimal('900.00'))
        self.alert.assert_called()

    def test_currency_mismatch_alerts_and_changes_nothing(self):
        webhook.handle_event(event('transfer.success', self.p, currency='USD'))
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, 'submitted')
        self.alert.assert_called()

    def test_unknown_wd_reference_alerts_and_is_handled(self):
        self.assertTrue(webhook.handle_event(
            {'event': 'transfer.success', 'data': {'reference': 'wd-' + 'a' * 32}}))
        self.alert.assert_called()

    def test_foreign_transfer_reference_falls_through(self):
        self.assertFalse(webhook.handle_event(
            {'event': 'transfer.success', 'data': {'reference': 'PAYOUT-1-ABC'}}))
        self.assertFalse(webhook.handle_event({'event': 'transfer.success', 'data': {}}))
        self.assertFalse(webhook.handle_event({'event': 'transfer.success', 'data': None}))
        self.alert.assert_not_called()

    def test_non_string_reference_does_not_crash(self):
        self.assertFalse(webhook.handle_event({'event': 'transfer.success', 'data': {'reference': 5}}))

    def test_other_transfer_events_are_ignored_but_not_claimed(self):
        self.assertFalse(webhook.handle_event(event('transfer.other', self.p)))


# ---------------------------------------------------------------- sweep

@override_settings(WALLET_PAYOUTS_ENABLED=False)
class SweepTests(PayoutBase, TestCase):
    """Flag OFF: the sweep must still finalise money already in flight (M6)."""

    def old(self, amount='100', key=KEY, status='submitted', age=dt.timedelta(minutes=5)):
        return self.new_payout(amount, key=key, status=status, age=age)

    def status_of(self, p):
        p.refresh_from_db()
        return p.status

    def test_success_finalises_paid(self):
        p = self.old()
        self.gw.statuses[p.reference] = 'success'
        self.assertEqual(sweeps.sweep_payouts()['paid'], 1)
        self.assertEqual(self.status_of(p), 'paid')
        self.assertEqual(a_note(p), 'sweep status=success')
        self.assertEqual(self.gw.calls[0]['args'], (p.reference,))

    def test_failed_and_reversed_reverse_once_even_when_swept_twice(self):
        for i, st in enumerate(('failed', 'reversed')):
            user = make_user(f'sw{i}', f'+25470000070{i}')
            fund(user, '500')
            p = self.new_payout('100', key=f'key-sweep-0{i}', status='requested', age=dt.timedelta(minutes=5), user=user)
            self.gw.statuses[p.reference] = st
            sweeps.sweep_payouts()
            sweeps.sweep_payouts()
            self.assertEqual(self.status_of(p), 'failed')
            self.assertEqual(balance(user), Decimal('500.00'))

    def test_pending_stays(self):
        p = self.old(status='requested')
        self.gw.statuses[p.reference] = 'pending'
        result = sweeps.sweep_payouts()
        self.assertEqual((self.status_of(p), result['pending']), ('requested', 1))
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_recent_rows_are_not_checked(self):
        self.old(age=dt.timedelta(seconds=30))
        sweeps.sweep_payouts()
        self.assertEqual(self.gw.calls, [])

    def test_not_found_goes_to_review_never_resent_never_reversed(self):
        for i, st in enumerate(('requested', 'submitted')):
            user = make_user(f'nf{i}', f'+25470000080{i}')
            fund(user, '500')
            p = self.new_payout('100', key=f'key-nf-000{i}', status=st, age=dt.timedelta(minutes=5), user=user)
            self.gw.statuses[p.reference] = 'not_found'
            self.alert.reset_mock()
            sweeps.sweep_payouts()
            self.assertEqual(self.status_of(p), 'review')
            self.assertEqual(balance(user), Decimal('400.00'))
            self.alert.assert_called()
        self.assertFalse(any(c['name'] == 'send' for c in self.gw.calls))

    def test_otp_and_review_statuses_go_to_review_with_alert(self):
        for i, st in enumerate(('otp', 'review')):
            user = make_user(f'ot{i}', f'+25470000090{i}')
            fund(user, '500')
            p = self.new_payout('100', key=f'key-ot-000{i}', status='submitted', age=dt.timedelta(minutes=5), user=user)
            self.gw.statuses[p.reference] = st
            self.alert.reset_mock()
            sweeps.sweep_payouts()
            self.assertEqual(self.status_of(p), 'review')
            self.alert.assert_called()

    def test_error_status_leaves_the_row_alone(self):
        p = self.old()
        self.gw.statuses[p.reference] = 'error'
        sweeps.sweep_payouts()
        self.assertEqual(self.status_of(p), 'submitted')
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_gateway_exception_leaves_the_row_alone(self):
        p = self.old()
        self.gw.statuses[p.reference] = RuntimeError('down')
        sweeps.sweep_payouts()
        self.assertEqual(self.status_of(p), 'submitted')

    def test_pending_older_than_24h_goes_to_review(self):
        p = self.old(age=dt.timedelta(hours=25))
        self.gw.statuses[p.reference] = 'pending'
        sweeps.sweep_payouts()
        self.assertEqual(self.status_of(p), 'review')

    def test_timeout_then_sweep_resolves_both_ways(self):
        self.gw.send_results = [SendResult(UNCERTAIN, 'timeout')]
        a, _ = payouts.withdraw(self.user, Decimal('100'), KEY)
        WalletPayout.objects.filter(pk=a.pk).update(created_at=timezone.now() - dt.timedelta(minutes=5))
        self.gw.statuses[a.reference] = 'success'
        sweeps.sweep_payouts()
        self.assertEqual(self.status_of(a), 'paid')
        self.assertEqual(balance(self.user), Decimal('900.00'))

        self.gw.send_results = [SendResult(UNCERTAIN, 'timeout')]
        b, _ = payouts.withdraw(self.user, Decimal('100'), 'key-0000-0002')
        WalletPayout.objects.filter(pk=b.pk).update(created_at=timezone.now() - dt.timedelta(minutes=5))
        self.gw.statuses[b.reference] = 'failed'
        sweeps.sweep_payouts()
        self.assertEqual(self.status_of(b), 'failed')
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_final_rows_are_never_touched(self):
        self.old(status='paid')
        q = self.new_payout('100', key='key-0000-0002')
        payouts.fail_and_reverse(q.pk, 'x', allowed_from=('requested',))
        WalletPayout.objects.update(created_at=timezone.now() - dt.timedelta(hours=2))
        sweeps.sweep_payouts()
        self.assertEqual(self.gw.calls, [])

    def test_stuck_alert_once_per_hour(self):
        p = self.old(age=dt.timedelta(minutes=45))
        self.gw.statuses[p.reference] = 'pending'
        sweeps.sweep_payouts()
        sweeps.sweep_payouts()
        stuck = [c for c in self.alert.call_args_list if 'stuck' in str(c).lower()]
        self.assertEqual(len(stuck), 1)

    def test_command_runs_with_flag_off_and_lists_review_rows(self):
        p = self.old(status='review')
        out = StringIO()
        call_command('wallet_sweeps', stdout=out)
        self.assertIn('payouts', out.getvalue())
        self.assertIn(f'review: payout {p.pk}', out.getvalue())


def a_note(payout):
    return payout.events.filter(to_status='paid').get().note


class ResolvePayoutCommandTests(PayoutBase, TestCase):
    def test_paid_and_reverse_are_one_shot_and_review_only(self):
        a = self.new_payout('100', status='review')
        call_command('resolve_payout', str(a.pk), '--paid', stdout=StringIO())
        self.assertEqual(WalletPayout.objects.get(pk=a.pk).status, 'paid')
        self.assertEqual(a_note(a), 'admin resolve --paid')
        with self.assertRaises(CommandError):
            call_command('resolve_payout', str(a.pk), '--reverse', stdout=StringIO())

        b = self.new_payout('100', key='key-0000-0002', status='review')
        call_command('resolve_payout', str(b.pk), '--reverse', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('resolve_payout', str(b.pk), '--reverse', stdout=StringIO())
        self.assertEqual(WalletPayout.objects.get(pk=b.pk).status, 'failed')
        self.assertEqual(balance(self.user), Decimal('800.00') + Decimal('100.00'))

    def test_needs_exactly_one_flag(self):
        a = self.new_payout('100', status='review')
        with self.assertRaises(CommandError):
            call_command('resolve_payout', str(a.pk), stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('resolve_payout', str(a.pk), '--paid', '--reverse', stdout=StringIO())

    def test_not_in_review_is_refused(self):
        a = self.new_payout('100')
        with self.assertRaises(CommandError):
            call_command('resolve_payout', str(a.pk), '--paid', stdout=StringIO())


# ---------------------------------------------------------------- HTTP view

@override_settings(WALLET_PAYOUTS_ENABLED=True)
class WithdrawViewTests(PayoutBase, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('wallet-withdraw')

    def post(self, body=None, **kw):
        cache.delete(f'throttle_wallet_withdraw_{self.user.pk}')  # keep the password counter
        data = {'amount': '100', 'idempotency_key': KEY, 'password': 'pw-123456'}
        data.update(body or {})
        return self.client.post(self.url, data, format='json')

    def test_success_shape_and_masked_destination(self):
        r = self.post()
        self.assertEqual(r.status_code, 201, r.content)
        p = WalletPayout.objects.get()
        self.assertEqual(r.data['payout_id'], p.pk)
        self.assertEqual((r.data['status'], r.data['amount']), ('submitted', '100.00'))
        self.assertEqual(r.data['destination_masked'], '+254******678')
        self.assertIn('created_at', r.data)
        self.assertNotIn(PHONE, str(r.data))
        self.assertNotIn(p.reference, str(r.data))

    def test_replay_is_200_with_same_payout(self):
        a = self.post()
        b = self.post()
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(a.data['payout_id'], b.data['payout_id'])
        self.assertEqual(WalletPayout.objects.count(), 1)

    def test_refused_transfer_is_returned_as_failed_and_money_is_back(self):
        self.gw.send_results = [SendResult(REFUSED, 'nope')]
        r = self.post()
        self.assertEqual((r.status_code, r.data['status']), (201, 'failed'))
        self.assertNotIn('nope', str(r.data))
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_wrong_password_403_and_nothing_happens(self):
        r = self.post({'password': 'nope'})
        self.assertEqual((r.status_code, r.data['code']), (403, 'wrong_password'))
        self.assertEqual(WalletPayout.objects.count(), 0)
        self.assertEqual(self.gw.calls, [])

    def test_missing_or_blank_password_400(self):
        for body in ({'password': ''}, {'password': None}, {'password': 123456}):
            r = self.post(body)
            self.assertEqual((r.status_code, r.data['code']), (400, 'password_required'), body)
        data = {'amount': '100', 'idempotency_key': KEY}
        cache.clear()
        r = self.client.post(self.url, data, format='json')
        self.assertEqual(r.data['code'], 'password_required')

    def test_password_lockout_after_five_failures_even_for_right_password(self):
        for _ in range(5):
            self.assertEqual(self.post({'password': 'bad'}).status_code, 403)
        r = self.post({'password': 'pw-123456'})
        self.assertEqual((r.status_code, r.data['code']), (429, 'too_many_attempts'))
        self.assertEqual(WalletPayout.objects.count(), 0)

    def test_success_resets_failure_counter(self):
        for _ in range(4):
            self.post({'password': 'bad'})
        self.assertEqual(self.post().status_code, 201)
        WalletPayout.objects.update(status='paid')
        for _ in range(4):
            self.assertEqual(self.post({'password': 'bad', 'idempotency_key': 'key-0000-0002'}).status_code, 403)

    def test_destination_fields_are_rejected_not_ignored(self):
        for field in ('phone', 'phone_number', 'destination', 'msisdn', 'recipient', 'account_number'):
            for value in (PHONE, '+254799999999'):
                r = self.post({field: value})
                self.assertEqual((r.status_code, r.data['code']), (400, 'destination_not_allowed'), field)
        self.assertEqual(WalletPayout.objects.count(), 0)
        self.assertEqual(self.gw.calls, [])

    def test_other_users_phone_is_impossible_destination_always_account_phone(self):
        other = make_user('victim', '+254799999999')
        r = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.gw.calls[0]['args'], (PHONE,))
        self.assertEqual(WalletPayout.objects.get().destination_phone, PHONE)
        self.assertNotEqual(WalletPayout.objects.get().destination_phone, other.phone_number)

    def test_flag_off_blocks_request_503_without_side_effects(self):
        with self.settings(WALLET_PAYOUTS_ENABLED=False):
            r = self.post()
        self.assertEqual((r.status_code, r.data['code']), (503, 'feature_disabled'))
        self.assertEqual(WalletPayout.objects.count(), 0)
        self.assertEqual(self.gw.calls, [])

    def test_flag_defaults_off_when_setting_absent(self):
        from django.conf import settings
        with override_settings():
            del settings.WALLET_PAYOUTS_ENABLED
            r = self.post()
        self.assertEqual(r.status_code, 503)

    def test_non_passenger_403_and_anonymous_rejected(self):
        driver = make_user('drv', '+254700000556', role='driver')
        self.client.force_authenticate(driver)
        r = self.post()
        self.assertEqual((r.status_code, r.data['code']), (403, 'passenger_only'))
        r = APIClient().post(self.url, {'amount': '100', 'idempotency_key': KEY}, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_amount_validation_codes(self):
        fund(self.user, '30000')
        cases = [('49.99', 'amount_too_small'), ('20000.01', 'amount_too_large'), ('0', 'invalid_amount'),
                 ('-100', 'invalid_amount'), ('abc', 'invalid_amount'), ('NaN', 'invalid_amount'),
                 ('Infinity', 'invalid_amount'), ('100.123', 'invalid_amount'), ('', 'invalid_amount'),
                 (None, 'invalid_amount'), ('1e3', 'invalid_amount'), (True, 'invalid_amount'),
                 (['100'], 'invalid_amount'), ('0x10', 'invalid_amount')]
        for amount, code in cases:
            r = self.post({'amount': amount})
            self.assertEqual((r.status_code, r.data['code']), (400, code), amount)
        self.assertEqual(WalletPayout.objects.count(), 0)

    def test_idempotency_key_validation(self):
        for key in (None, '', 'short', 'x' * 65, 'has space 12345', 'semi;colon-123', 12345678, ['a' * 10]):
            r = self.post({'idempotency_key': key})
            self.assertEqual((r.status_code, r.data['code']), (400, 'invalid_key'), key)

    def test_insufficient_funds_400(self):
        r = self.post({'amount': '1000.01'})
        self.assertEqual((r.status_code, r.data['code']), (400, 'insufficient_funds'))

    def test_daily_limit_and_inflight_and_key_reuse_codes(self):
        self.assertEqual(self.post().status_code, 201)
        r = self.post({'idempotency_key': 'key-0000-0002'})
        self.assertEqual((r.status_code, r.data['code']), (409, 'payout_in_flight'))
        r = self.post({'amount': '101'})
        self.assertEqual((r.status_code, r.data['code']), (409, 'key_reused'))

    def test_hourly_throttle_returns_429(self):
        cache.clear()
        codes = []
        for i in range(6):
            r = self.client.post(self.url, {'amount': '100', 'idempotency_key': KEY,
                                            'password': 'pw-123456'}, format='json')
            codes.append(r.status_code)
        self.assertEqual(codes[-1], 429, codes)

    def test_no_gateway_call_inside_atomic_via_http(self):
        r = self.post()
        self.assertEqual(r.status_code, 201)
        self.assertTrue(self.gw.calls)
        self.assertTrue(all(c['atomic'] is False for c in self.gw.calls))

    def test_list_shows_only_own_payouts_newest_first(self):
        other = make_user('other', '+254700000600')
        fund(other, '500')
        mine = self.new_payout('100', key='key-0000-0001', status='paid')
        self.new_payout('100', key='key-0000-0002', user=other)
        mine2 = self.new_payout('100', key='key-0000-0003')
        r = self.client.get(reverse('wallet-withdrawals'))
        self.assertEqual(r.status_code, 200)
        ids = [row['payout_id'] for row in r.data['results']]
        self.assertEqual(ids, [mine2.pk, mine.pk])
        self.assertEqual(set(r.data['results'][0]), {
            'payout_id', 'status', 'amount', 'destination_masked', 'created_at'})
        self.assertIn('next_cursor', r.data)

    def test_list_non_passenger_403(self):
        self.client.force_authenticate(make_user('drv', '+254700000557', role='driver'))
        self.assertEqual(self.client.get(reverse('wallet-withdrawals')).status_code, 403)


# ---------------------------------------------------------------- races (Postgres)

@unittest.skipUnless(POSTGRES, 'needs real row locks')
class PayoutRaceTests(PayoutBase, TransactionTestCase):
    def _run(self, fn, n):
        barrier = threading.Barrier(n)
        results = [None] * n

        def work(i):
            try:
                barrier.wait()
                results[i] = fn(i)
            except Exception as exc:
                results[i] = exc
            finally:
                connection.close()
        threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def exact_balance_user(self, amount):
        user = make_user('exact', '+254700000777')
        fund(user, amount)
        return user

    def test_8_parallel_same_key_one_payout_one_send(self):
        results = self._run(lambda i: payouts.withdraw(self.user, Decimal('100'), KEY), 8)
        self.assertTrue(all(isinstance(r, tuple) for r in results), results)
        self.assertEqual(WalletPayout.objects.count(), 1)
        self.assertEqual(sum(1 for r in results if r[1]), 1)
        self.assertEqual(sum(1 for c in self.gw.calls if c['name'] == 'send'), 1)
        self.assertEqual(balance(self.user), Decimal('900.00'))

    def test_8_racing_requests_balance_for_one_succeed_once(self):
        self.user = self.exact_balance_user('100')
        results = self._run(
            lambda i: payouts.request_withdrawal(self.user, Decimal('100'), f'key-race-000{i}'), 8)
        ok = [r for r in results if isinstance(r, tuple)]
        bad = [r for r in results if isinstance(r, payouts.WithdrawalError)]
        self.assertEqual((len(ok), len(bad)), (1, 7), results)
        self.assertEqual(balance(self.user), Decimal('0.00'))

    def test_wallet_lock_and_debit_hold_with_in_flight_rule_disabled(self):
        # The one-in-flight rule alone would also pass the test above. Neutralise it.
        self.user = self.exact_balance_user('100')
        with mock.patch.object(payouts, '_has_in_flight', return_value=False):
            results = self._run(
                lambda i: payouts.request_withdrawal(self.user, Decimal('100'), f'key-race-100{i}'), 8)
        ok = [r for r in results if isinstance(r, tuple)]
        self.assertEqual(len(ok), 1, results)
        self.assertEqual(balance(self.user), Decimal('0.00'))

    def test_daily_limit_checked_under_wallet_lock(self):
        fund(self.user, '100000')
        with mock.patch.object(payouts, '_has_in_flight', return_value=False):
            results = self._run(
                lambda i: payouts.request_withdrawal(self.user, Decimal('10000'), f'key-race-200{i}'), 8)
        ok = [r for r in results if isinstance(r, tuple)]
        limited = [r for r in results if isinstance(r, payouts.WithdrawalError) and r.code == 'daily_limit']
        self.assertEqual((len(ok), len(limited)), (3, 5), results)
        self.assertEqual(payouts.rolling_total(self.user), Decimal('30000.00'))

    def test_webhook_failed_replayed_in_parallel_reverses_once(self):
        p = self.new_payout('100', status='submitted')
        results = self._run(lambda i: webhook.handle_event(event('transfer.failed', p)), 8)
        self.assertTrue(all(r is True for r in results), results)
        self.assertEqual(WalletTransaction.objects.filter(type='withdrawal_reversal').count(), 1)
        self.assertEqual(balance(self.user), Decimal('1000.00'))

    def test_webhook_failed_vs_sweep_success_never_both(self):
        p = self.new_payout('100', status='submitted', age=dt.timedelta(minutes=5))
        self.gw.statuses[p.reference] = 'success'

        def work(i):
            if i % 2:
                return webhook.handle_event(event('transfer.failed', p))
            return sweeps.sweep_payouts()
        self._run(work, 8)
        p.refresh_from_db()
        self.assertIn(p.status, ('paid', 'failed'))
        self.assertEqual(
            WalletTransaction.objects.filter(type='withdrawal_reversal').count(),
            1 if p.status == 'failed' else 0)


# ---------------------------------------------------------------- real adapter (mocked HTTP only)

def _resp(status=200, body=None, text=None):
    r = mock.Mock()
    r.status_code = status
    if body is None and text is not None:
        r.json.side_effect = ValueError('bad json')
    else:
        r.json.return_value = body
    return r


class PaystackTransfersAdapterTests(TestCase):
    """Mapping logic only. Field names are UNVERIFIED against live Paystack."""

    def setUp(self):
        self.gw = PaystackTransfers()
        self.user = make_user()
        fund(self.user, '500')
        with mock.patch('wallets.alerts.send'):
            self.payout, _ = payouts.request_withdrawal(self.user, Decimal('100.50'), KEY)

    def send(self, **kw):
        with mock.patch('wallets.gateway.requests.post', **kw) as post:
            return self.gw.send(self.payout, 'RCP_x'), post

    def test_guard_refuses_to_run_inside_a_transaction(self):
        with self.assertRaises(RuntimeError):
            self.gw.status('wd-x')  # TestCase wraps this test in atomic()

    def run_outside_atomic(self, fn):
        with mock.patch('wallets.gateway._assert_not_atomic'):
            return fn()

    def test_send_payload_and_accept(self):
        with mock.patch('wallets.gateway._assert_not_atomic'):
            result, post = self.send(return_value=_resp(200, {
                'status': True, 'data': {'status': 'pending', 'transfer_code': 'TRF_1'}}))
        self.assertEqual(result, SendResult(ACCEPTED, 'TRF_1'))
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith('/transfer'))
        self.assertEqual(kwargs['json'], {
            'source': 'balance', 'amount': 10050, 'recipient': 'RCP_x',
            'reference': self.payout.reference, 'currency': 'KES', 'reason': 'Connect wallet withdrawal'})
        self.assertEqual(kwargs['timeout'], 10)
        self.assertTrue(kwargs['headers']['Authorization'].startswith('Bearer '))

    def test_send_outcome_mapping(self):
        cases = [
            (_resp(400, {'status': False, 'message': 'Recipient is invalid'}), REFUSED),
            (_resp(422, {'status': False, 'message': 'nope'}), REFUSED),
            (_resp(401, {'status': False, 'message': 'bad key'}), REFUSED),
            (_resp(400, {'status': False, 'message': 'Transfer with this reference already exists'}), UNCERTAIN),
            (_resp(408, {}), UNCERTAIN), (_resp(429, {}), UNCERTAIN),
            (_resp(500, {}), UNCERTAIN), (_resp(502, {}), UNCERTAIN),
            (_resp(200, text='<html>'), UNCERTAIN),
            (_resp(200, {'status': False, 'message': 'x'}), UNCERTAIN),
            (_resp(200, {'status': True, 'data': {}}), UNCERTAIN),
            (_resp(200, {'status': True, 'data': {'status': 'weird', 'transfer_code': 'T'}}), UNCERTAIN),
        ]
        for response, expected in cases:
            with mock.patch('wallets.gateway._assert_not_atomic'):
                result, _ = self.send(return_value=response)
            self.assertEqual(result.outcome, expected, (response.status_code, response.json.return_value))

    def test_send_network_errors_are_uncertain(self):
        for exc in (requests.Timeout(), requests.ConnectionError(), requests.RequestException()):
            with mock.patch('wallets.gateway._assert_not_atomic'):
                result, _ = self.send(side_effect=exc)
            self.assertEqual(result.outcome, UNCERTAIN)

    def test_otp_status_on_send_is_accepted_then_review_by_sweep(self):
        with mock.patch('wallets.gateway._assert_not_atomic'):
            result, _ = self.send(return_value=_resp(200, {
                'status': True, 'data': {'status': 'otp', 'transfer_code': 'TRF_2'}}))
        self.assertEqual(result.outcome, ACCEPTED)

    def test_ensure_recipient_payload_and_result(self):
        with mock.patch('wallets.gateway._assert_not_atomic'), mock.patch(
                'wallets.gateway.requests.post',
                return_value=_resp(200, {'status': True, 'data': {'recipient_code': 'RCP_9'}})) as post:
            code = self.gw.ensure_recipient(PHONE)
        self.assertEqual(code, 'RCP_9')
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith('/transferrecipient'))
        self.assertEqual(kwargs['json'], {
            'type': 'mobile_money', 'name': 'Connect wallet', 'account_number': '0712345678',
            'bank_code': 'MPESA', 'currency': 'KES'})

    def test_ensure_recipient_failures_raise_refused(self):
        for resp in (_resp(400, {'message': 'bad'}), _resp(500, {}), _resp(200, text='x'),
                     _resp(200, {'status': True, 'data': {}})):
            with mock.patch('wallets.gateway._assert_not_atomic'), mock.patch(
                    'wallets.gateway.requests.post', return_value=resp):
                with self.assertRaises(GatewayRefused):
                    self.gw.ensure_recipient(PHONE)
        with mock.patch('wallets.gateway._assert_not_atomic'), mock.patch(
                'wallets.gateway.requests.post', side_effect=requests.Timeout()):
            with self.assertRaises(GatewayRefused):
                self.gw.ensure_recipient(PHONE)

    def status(self, response=None, exc=None):
        with mock.patch('wallets.gateway._assert_not_atomic'), mock.patch(
                'wallets.gateway.requests.get', return_value=response, side_effect=exc) as get:
            return self.gw.status('wd-abc'), get

    def test_status_mapping(self):
        mapping = {'success': 'success', 'failed': 'failed', 'reversed': 'reversed', 'otp': 'otp',
                   'pending': 'pending', 'processing': 'pending', 'received': 'pending',
                   'rejected': 'review', 'blocked': 'review', 'something-new': 'error', '': 'error'}
        for raw, expected in mapping.items():
            got, get = self.status(_resp(200, {'status': True, 'data': {'status': raw}}))
            self.assertEqual(got, expected, raw)
        self.assertTrue(get.call_args.args[0].endswith('/transfer/verify/wd-abc'))

    def test_status_errors(self):
        self.assertEqual(self.status(_resp(404, {'status': False}))[0], 'not_found')
        for resp in (_resp(500, {}), _resp(200, text='x'), _resp(200, {'data': None}),
                     _resp(200, {'data': {'status': None}}), _resp(401, {})):
            self.assertEqual(self.status(resp)[0], 'error')
        self.assertEqual(self.status(exc=requests.Timeout())[0], 'error')
