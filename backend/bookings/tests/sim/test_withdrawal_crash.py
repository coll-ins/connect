"""A crash between the debit commit and the gateway call never reverses and never resends.

Sim cases restore the serialized database, so they stay in the sim package, which runs before any plain transaction test.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.db import transaction
from django.utils import timezone

from bookings.tests.sim import test_world_money as money
from wallets import payouts, services as wallet_services, sweeps
from wallets.models import Wallet, WalletPayout


class WithdrawalCrashTests(money.MoneyCase):
    settle_at_end = False

    def test_a_crash_between_the_debit_commit_and_the_gateway_call_never_reverses_or_resends(self):
        user = self.user()
        with transaction.atomic():
            wallet_services.credit(user, Decimal('500.00'), 'deposit', 'topup:crash-test')
        with mock.patch.object(payouts, 'dispatch', side_effect=RuntimeError('process died')):
            with self.assertRaises(RuntimeError):
                payouts.withdraw(user, Decimal('100.00'), 'crash-key-0001')
        payout = WalletPayout.objects.get()
        self.assertEqual(payout.status, 'requested')
        self.assertEqual(Wallet.objects.get(user=user).available_balance, Decimal('400.00'))
        sweeps.sweep_payouts(now=timezone.now() + dt.timedelta(minutes=5))
        payout.refresh_from_db()
        self.assertEqual(payout.status, 'review')                         # a human decides; nothing is reversed
        self.assertEqual(Wallet.objects.get(user=user).available_balance, Decimal('400.00'))
        self.assertEqual(self.fake.calls_to('transfer'), [])              # and nothing was ever sent
        self.assertEqual(self.fake.leaks, [])
