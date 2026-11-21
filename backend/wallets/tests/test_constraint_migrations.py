"""Wallet migrations 0003, 0004 and 0006 add CHECK/UNIQUE constraints and refuse dirty data first."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from users.models import CustomUser

M0002 = [('wallets', '0002_alter_wallettransaction_type')]
M0003 = [('wallets', '0003_wallet_ledger_topup')]
M0004 = [('wallets', '0004_wallet_nonnegative')]
M0005 = [('wallets', '0005_wallet_payout')]
M0006 = [('wallets', '0006_wallet_payout_constraints')]


class WalletConstraintMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def wallet(self, apps, balance='10', held='0'):
        user = CustomUser.objects.create(username='w', phone_number='+254711000019')
        return user, apps.get_model('wallets', 'Wallet').objects.create(
            user_id=user.pk, available_balance=Decimal(balance), held_balance=Decimal(held))

    def test_0003_names_zero_amount_rows_and_changes_nothing(self):
        apps = self.migrate(M0002)
        _, wallet = self.wallet(apps)
        Tx = apps.get_model('wallets', 'WalletTransaction')
        tx = Tx.objects.create(wallet_id=wallet.pk, type='adjustment', amount=Decimal('0'))
        with self.assertRaises(RuntimeError) as ctx:
            self.migrate(M0003)
        self.assertIn(str(tx.pk), str(ctx.exception))
        self.assertIn('wallet transactions with amount 0', str(ctx.exception))
        self.assertEqual(Tx.objects.get(pk=tx.pk).amount, Decimal('0'))
        Tx.objects.filter(pk=tx.pk).delete()

    def test_0003_clean_rows_migrate_hold_and_reverse(self):
        apps = self.migrate(M0002)
        _, wallet = self.wallet(apps)
        apps.get_model('wallets', 'WalletTransaction').objects.create(
            wallet_id=wallet.pk, type='deposit', amount=Decimal('10'))
        apps = self.migrate(M0003)
        Tx = apps.get_model('wallets', 'WalletTransaction')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tx.objects.create(wallet_id=wallet.pk, type='deposit', amount=Decimal('0'))
        apps = self.migrate(M0002)
        self.assertEqual(apps.get_model('wallets', 'WalletTransaction').objects.count(), 1)

    def test_0004_names_negative_balance_wallets_and_changes_nothing(self):
        apps = self.migrate(M0003)
        _, wallet = self.wallet(apps, balance='-5')
        with self.assertRaises(RuntimeError) as ctx:
            self.migrate(M0004)
        self.assertIn(str(wallet.pk), str(ctx.exception))
        self.assertIn('wallets with a negative balance', str(ctx.exception))
        Wallet = apps.get_model('wallets', 'Wallet')
        self.assertEqual(Wallet.objects.get(pk=wallet.pk).available_balance, Decimal('-5.00'))
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=0)

    def test_0004_negative_held_balance_is_named_too(self):
        apps = self.migrate(M0003)
        _, wallet = self.wallet(apps, held='-1')
        with self.assertRaises(RuntimeError) as ctx:
            self.migrate(M0004)
        self.assertIn(str(wallet.pk), str(ctx.exception))
        apps.get_model('wallets', 'Wallet').objects.filter(pk=wallet.pk).update(held_balance=0)

    def test_0004_clean_wallets_migrate_hold_and_reverse(self):
        apps = self.migrate(M0003)
        _, wallet = self.wallet(apps)
        apps = self.migrate(M0004)
        Wallet = apps.get_model('wallets', 'Wallet')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal('-1'))
        apps = self.migrate(M0003)
        Wallet = apps.get_model('wallets', 'Wallet')
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal('-1'))
        Wallet.objects.filter(pk=wallet.pk).update(available_balance=Decimal('10'))

    def payout(self, apps, user, wallet, key, amount, ref):
        return apps.get_model('wallets', 'WalletPayout').objects.create(
            user_id=user.pk, wallet_id=wallet.pk, amount=Decimal(amount),
            destination_phone='+254711000019', idempotency_key=key, reference=ref)

    def test_0006_names_duplicate_keys_and_non_positive_amounts(self):
        apps = self.migrate(M0005)
        user, wallet = self.wallet(apps)
        self.payout(apps, user, wallet, 'k1', '50', 'r1')
        b = self.payout(apps, user, wallet, 'k1', '50', 'r2')
        c = self.payout(apps, user, wallet, 'k2', '0', 'r3')
        with self.assertRaises(RuntimeError) as ctx:
            self.migrate(M0006)
        msg = str(ctx.exception)
        self.assertIn('duplicate idempotency keys', msg)
        self.assertIn('k1', msg)
        self.assertIn(str(c.pk), msg)
        Payout = apps.get_model('wallets', 'WalletPayout')
        self.assertEqual(Payout.objects.count(), 3)
        Payout.objects.filter(pk__in=[b.pk, c.pk]).delete()

    def test_0006_clean_payouts_migrate_hold_and_reverse(self):
        apps = self.migrate(M0005)
        user, wallet = self.wallet(apps)
        self.payout(apps, user, wallet, 'k1', '50', 'r1')
        apps = self.migrate(M0006)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.payout(apps, user, wallet, 'k1', '60', 'r2')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.payout(apps, user, wallet, 'k3', '0', 'r3')
        apps = self.migrate(M0005)
        self.assertEqual(apps.get_model('wallets', 'WalletPayout').objects.count(), 1)
