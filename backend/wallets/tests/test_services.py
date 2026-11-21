import datetime as dt
import re
import threading
import unittest
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from wallets import services
from wallets.models import Wallet, WalletTransaction

User = get_user_model()
POSTGRES = connection.vendor == 'postgresql'


def make_user(name='w1', phone='+254700000101'):
    return User.objects.create_user(username=name, password='pw-123456', phone_number=phone)


class LedgerServiceTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def _wallet(self):
        return Wallet.objects.get(user=self.user)

    def test_credit_creates_wallet_and_signed_ledger_row(self):
        row = services.credit(self.user, Decimal('150.00'), 'deposit', 'topup:A')
        self.assertEqual(row.amount, Decimal('150.00'))
        self.assertEqual(row.balance_after, Decimal('150.00'))
        self.assertEqual(row.type, 'deposit')
        self.assertEqual(self._wallet().available_balance, Decimal('150.00'))

    def test_debit_writes_negative_amount(self):
        services.credit(self.user, Decimal('150.00'), 'deposit', 'topup:A')
        row = services.debit(self.user, Decimal('40.00'), 'spend', 'spend:1')
        self.assertEqual(row.amount, Decimal('-40.00'))
        self.assertEqual(row.balance_after, Decimal('110.00'))
        self.assertEqual(self._wallet().available_balance, Decimal('110.00'))

    def test_credit_debit_idempotent_by_reference(self):
        first = services.credit(self.user, Decimal('100'), 'deposit', 'topup:A')
        again = services.credit(self.user, Decimal('100'), 'deposit', 'topup:A')
        self.assertEqual(first.pk, again.pk)
        d1 = services.debit(self.user, Decimal('30'), 'spend', 'spend:9')
        d2 = services.debit(self.user, Decimal('30'), 'spend', 'spend:9')
        self.assertEqual(d1.pk, d2.pk)
        self.assertEqual(self._wallet().available_balance, Decimal('70.00'))
        self.assertEqual(WalletTransaction.objects.count(), 2)

    def test_debit_insufficient_raises_no_row(self):
        services.credit(self.user, Decimal('50'), 'deposit', 'topup:A')
        with self.assertRaises(services.InsufficientFunds):
            services.debit(self.user, Decimal('50.01'), 'spend', 'spend:1')
        self.assertEqual(self._wallet().available_balance, Decimal('50.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_debit_exact_balance_leaves_zero(self):
        services.credit(self.user, Decimal('50'), 'deposit', 'topup:A')
        services.debit(self.user, Decimal('50'), 'spend', 'spend:1')
        self.assertEqual(self._wallet().available_balance, Decimal('0.00'))

    def test_bad_amounts_rejected(self):
        for bad in (Decimal('0'), Decimal('-5'), Decimal('1.005'), Decimal('NaN'),
                    Decimal('Infinity'), 'abc', None, 12.5):
            with self.assertRaises(ValueError, msg=repr(bad)):
                services.credit(self.user, bad, 'deposit', f'topup:{bad!r}')
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            services.credit(self.user, Decimal('5'), 'bonus', 'x:1')

    def test_empty_reference_rejected(self):
        with self.assertRaises(ValueError):
            services.credit(self.user, Decimal('5'), 'deposit', '')

    def test_ledger_sum_equals_balance(self):
        services.credit(self.user, Decimal('500'), 'deposit', 'topup:A')
        services.debit(self.user, Decimal('120.50'), 'spend', 'spend:1')
        services.credit(self.user, Decimal('20.25'), 'refund', 'refund:1')
        total = self._wallet().transactions.aggregate(s=Sum('amount'))['s']
        self.assertEqual(total, self._wallet().available_balance)
        self.assertEqual(total, Decimal('399.75'))

    def test_must_run_inside_atomic_block(self):
        # TestCase wraps a transaction, so fake the "no transaction" state.
        with mock.patch.object(services.connection, 'in_atomic_block', False):
            with self.assertRaises(AssertionError):
                services.credit(self.user, Decimal('5'), 'deposit', 'topup:A')
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_balance_check_constraint(self):
        services.credit(self.user, Decimal('10'), 'deposit', 'topup:A')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(user=self.user).update(available_balance=Decimal('-0.01'))

    def test_ledger_rejects_zero_amount_and_duplicate_reference(self):
        services.credit(self.user, Decimal('10'), 'deposit', 'topup:A')
        wallet = self._wallet()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet, type='deposit', amount=Decimal('0'), reference='z:1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet, type='deposit', amount=Decimal('1'), reference='topup:A')

    def test_two_ledger_rows_without_reference_are_allowed(self):
        wallet = Wallet.objects.create(user=self.user)
        for _ in range(2):
            WalletTransaction.objects.create(wallet=wallet, type='adjustment', amount=Decimal('1'))
        self.assertEqual(wallet.transactions.count(), 2)


class LedgerCheckCommandTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_clean_ledger_passes(self):
        services.credit(self.user, Decimal('10'), 'deposit', 'topup:A')
        out = StringIO()
        call_command('check_wallet_ledger', stdout=out)
        self.assertIn('ledger ok', out.getvalue())

    def test_drift_is_reported_and_alerted(self):
        services.credit(self.user, Decimal('10'), 'deposit', 'topup:A')
        Wallet.objects.filter(user=self.user).update(available_balance=Decimal('11'))
        with mock.patch('wallets.alerts.send') as alert:
            with self.assertRaises(CommandError):
                call_command('check_wallet_ledger', stdout=StringIO())
        alert.assert_called_once()
        self.assertIn(str(self.user.pk), alert.call_args[0][0])


class BalanceWriteBoundaryTests(TestCase):
    def test_balance_written_only_in_services(self):
        root = Path(__file__).resolve().parents[2]
        write = re.compile(
            r'available_balance\s*(\+=|-=|=(?!=))|'
            r"F\(['\"]available_balance|"
            r'WalletTransaction\.objects\.(create|bulk_create|get_or_create|update_or_create)|'
            r'transactions\.(create|bulk_create)|(?<!class )WalletTransaction\(')
        offenders = []
        for path in root.rglob('*.py'):
            rel = path.relative_to(root)
            parts = rel.parts
            if ('tests' in parts or 'migrations' in parts or path.name.startswith('test_')
                    or parts[0] in ('wallets',) and path.name == 'services.py'
                    or 'cvenv' in parts or 'venv' in parts or 'site-packages' in parts):
                continue
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if write.search(line) and 'models.DecimalField' not in line:
                    offenders.append(f'{rel}:{n}: {line.strip()}')
        self.assertEqual(offenders, [])


@unittest.skipUnless(POSTGRES, 'needs real row locks')
class LedgerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = make_user()

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

    def test_concurrent_debits_only_one_succeeds(self):
        with transaction.atomic():
            services.credit(self.user, Decimal('100'), 'deposit', 'topup:A')

        def debit(i):
            with transaction.atomic():
                return services.debit(self.user, Decimal('100'), 'spend', f'spend:{i}')

        results = self._run(debit, 8)
        ok = [r for r in results if isinstance(r, WalletTransaction)]
        failed = [r for r in results if isinstance(r, services.InsufficientFunds)]
        self.assertEqual((len(ok), len(failed)), (1, 7), results)
        self.assertEqual(Wallet.objects.get(user=self.user).available_balance, Decimal('0.00'))

    def test_concurrent_same_reference_credits_once(self):
        Wallet.objects.create(user=self.user)

        def credit(i):
            with transaction.atomic():
                return services.credit(self.user, Decimal('25'), 'deposit', 'topup:SAME')

        results = self._run(credit, 8)
        self.assertTrue(all(isinstance(r, WalletTransaction) for r in results), results)
        self.assertEqual(len({r.pk for r in results}), 1)
        self.assertEqual(Wallet.objects.get(user=self.user).available_balance, Decimal('25.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_ledger_insert_with_booking_takes_share_lock_on_booking(self):
        from bookings.models import Booking
        from companies.models import Company, Route, Trip
        from drivers.models import Driver

        company = Company.objects.create(name='Lock Co', areas_served='Nairobi')
        route = Route.objects.create(
            company=company, name='A - B', start_point='A', end_point='B', price=Decimal('100'))
        driver = Driver.objects.create(
            name='D', phone_number='+254711000555', bus_number='KDA 555A', company=company)
        trip = Trip.objects.create(
            route=route, driver=driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=2))
        booking = Booking.objects.create(
            user=self.user, trip=trip, route=route, driver=driver, seats=1,
            total_amount=Decimal('100'), status='confirmed', pickup_location='A')
        Wallet.objects.create(user=self.user)

        holding = threading.Event()
        release = threading.Event()

        def holder():
            try:
                with transaction.atomic():
                    Booking.objects.select_for_update().get(pk=booking.pk)
                    holding.set()
                    release.wait(10)
            finally:
                connection.close()

        t = threading.Thread(target=holder)
        t.start()
        holding.wait(10)
        try:
            with self.assertRaises(OperationalError):
                with transaction.atomic():
                    with connection.cursor() as cur:
                        cur.execute("SET LOCAL lock_timeout = '400ms'")
                    services.credit(
                        self.user, Decimal('10'), 'refund', f'refund:{booking.pk}', booking=booking)
        finally:
            release.set()
            t.join()
        self.assertEqual(WalletTransaction.objects.count(), 0)
