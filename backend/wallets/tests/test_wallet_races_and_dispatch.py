"""Wallet payout and top-up races (PostgreSQL), and the one-send guarantee of dispatch."""
import datetime as dt
import unittest
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.tests.review_base import PG, WorldMixin, fund, run_together
from bookings.tests.sim import fake_gateway as fg
from wallets import gateway


def signed(event):
    return fg.post_event(APIClient(), event).status_code


class DispatchOnceTests(WorldMixin, TestCase):
    def test_dispatch_twice_sends_once(self):
        from wallets import payouts
        from wallets.models import WalletPayout
        fund(self.pax, 500, 'topup:gap-1')
        gw = gateway.FakeTransfers()
        gw.send_results = [gateway.SendResult(gateway.UNCERTAIN, 'timeout')]
        with mock.patch('wallets.gateway.get_gateway', return_value=gw):
            payout, _ = payouts.withdraw(self.pax, Decimal('100'), 'gap-key-0001')
            self.assertEqual(WalletPayout.objects.get(pk=payout.pk).status, 'requested')
            payouts.dispatch(payout.pk)
            payouts.dispatch(payout.pk)
        self.assertEqual(len([c for c in gw.calls if c['name'] == 'send']), 1)
        self.assertEqual(WalletPayout.objects.get(pk=payout.pk).attempts, 1)


@unittest.skipUnless(PG, 'needs real row locks')
class WalletMoneyRaceTests(WorldMixin, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.gw = gateway.FakeTransfers()
        patcher = mock.patch('wallets.gateway.get_gateway', return_value=self.gw)
        patcher.start()
        self.addCleanup(patcher.stop)
        cache.clear()

    def test_parallel_withdrawals_debit_once_per_inflight(self):
        from wallets import payouts
        from wallets.models import Wallet, WalletPayout
        for i in range(10):
            u = self.passenger()
            u.phone_number = f'+25471{i:07d}'
            u.save()
            fund(u, 1000, f'topup:w-{u.pk}')
            keys = [f'key-{i}-aaaa{j}' for j in range(4)] + [f'key-{i}-same'] * 4
            res, errs = run_together([(lambda k=k: payouts.withdraw(u, Decimal('100'), k)[1]) for k in keys])
            payouts_n = WalletPayout.objects.filter(user=u).count()
            balance = Wallet.objects.get(user=u).available_balance
            self.assertEqual(Decimal('1000') - balance, Decimal('100') * payouts_n, (res, errs, payouts_n, balance))
            self.assertEqual(payouts_n, 1, (res, errs))
            self.assertEqual(len([c for c in self.gw.calls if c['name'] == 'send']), i + 1)

    def test_transfer_failed_webhook_vs_sweep_reverse_once(self):
        from wallets import payouts, sweeps
        from wallets.models import Wallet, WalletPayout, WalletTransaction
        for i in range(10):
            u = self.passenger()
            u.phone_number = f'+25472{i:07d}'
            u.save()
            fund(u, 500, f'topup:x-{u.pk}')
            payout, _ = payouts.withdraw(u, Decimal('200'), f'key-fail-{i}-abcd')
            WalletPayout.objects.filter(pk=payout.pk).update(
                created_at=timezone.now() - dt.timedelta(minutes=10))
            self.gw.statuses[payout.reference] = 'failed'
            ev = {'event': 'transfer.failed', 'data': {
                'reference': payout.reference, 'amount': 20000, 'currency': 'KES'}}
            res, errs = run_together([lambda: signed(ev), lambda: sweeps.sweep_payouts(), lambda: signed(ev)])
            self.assertEqual(errs, [], i)
            self.assertEqual(WalletTransaction.objects.filter(reference=f'wdrev:{payout.pk}').count(), 1, res)
            self.assertEqual(Wallet.objects.get(user=u).available_balance, Decimal('500.00'), res)

    def test_topup_webhook_sweep_status_credit_once(self):
        from wallets import sweeps, topup
        from wallets.models import Wallet, WalletTopUp, WalletTransaction
        for i in range(10):
            u = self.passenger()
            row = topup.create_topup(u, Decimal('100'))
            WalletTopUp.objects.filter(pk=row.pk).update(
                created_at=timezone.now() - dt.timedelta(hours=25 if i % 2 else 1))
            ev = {'event': 'charge.success', 'data': {
                'reference': row.reference, 'amount': 10000, 'currency': 'KES',
                'status': 'success', 'metadata': {'user_id': u.id}}}
            self.fake.charges[row.reference] = {
                'amount': 10000, 'currency': 'KES', 'paid': 10000, 'metadata': {'user_id': u.id}}
            res, errs = run_together([
                lambda: signed(ev), lambda: signed(ev), lambda: sweeps.sweep_topups(),
                lambda: self.api(u).get(f'/api/wallet/topup/{row.reference}/').status_code])
            self.assertEqual(errs, [], i)
            self.assertEqual(WalletTransaction.objects.filter(reference=f'topup:{row.reference}').count(), 1, res)
            self.assertEqual(Wallet.objects.get(user=u).available_balance, Decimal('100.00'), res)
            self.assertEqual(WalletTopUp.objects.get(pk=row.pk).status, 'credited', res)
