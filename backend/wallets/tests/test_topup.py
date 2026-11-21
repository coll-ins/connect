import datetime as dt
import threading
import unittest
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from connect.paystack_extra import GatewayError
from wallets import services, topup, webhook
from wallets.models import Wallet, WalletTopUp, WalletTransaction

User = get_user_model()
POSTGRES = connection.vendor == 'postgresql'
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


def make_user(name='tu', phone='+254700000201', role='passenger'):
    return User.objects.create_user(
        username=name, password='pw-123456', phone_number=phone, role=role)


def charge(topup_row, amount=None, user_id=None, currency='KES', status='success'):
    amount = topup_row.amount if amount is None else Decimal(amount)
    return {
        'reference': topup_row.reference,
        'status': status,
        'amount': int(amount * 100),
        'currency': currency,
        'metadata': {
            'purpose': 'wallet_topup',
            'user_id': topup_row.user_id if user_id is None else user_id,
        },
    }


def pending(user, amount='500.00', **extra):
    row = WalletTopUp.objects.create(user=user, amount=Decimal(amount), reference='TOPUP-tmp')
    row.reference = f'TOPUP-{row.pk}-ABCDEFGHJK'
    row.save(update_fields=['reference'])
    for k, v in extra.items():
        setattr(row, k, v)
    if extra:
        row.save()
    return row


def balance(user):
    return Wallet.objects.get(user=user).available_balance


@override_settings(CACHES=LOCMEM, WALLET_TOPUP_ENABLED=True)
class TopUpInitTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('wallet-topup')

    def _post(self, amount='500', **kw):
        with mock.patch('connect.paystack_extra.initialize', return_value='https://pay/x', **kw) as init:
            r = self.client.post(self.url, {'amount': amount}, format='json')
        return r, init

    def test_success_returns_url_and_creates_pending_row(self):
        r, init = self._post('500')
        self.assertEqual(r.status_code, 201, r.content)
        row = WalletTopUp.objects.get()
        self.assertEqual(r.data['authorization_url'], 'https://pay/x')
        self.assertEqual(r.data['reference'], row.reference)
        self.assertRegex(row.reference, r'^TOPUP-%d-[A-Z0-9]{10}$' % row.pk)
        self.assertEqual((row.status, row.amount, row.user), ('pending', Decimal('500.00'), self.user))
        kwargs = init.call_args.kwargs
        self.assertEqual(kwargs['reference'], row.reference)
        self.assertEqual(kwargs['amount'], Decimal('500.00'))
        self.assertEqual(kwargs['channels'], ['mobile_money'])
        self.assertEqual(kwargs['metadata'], {'purpose': 'wallet_topup', 'user_id': self.user.id})
        self.assertEqual(balance(self.user) if Wallet.objects.exists() else 0, 0)

    def test_non_passenger_403(self):
        driver = make_user('drv', '+254700000202', role='driver')
        self.client.force_authenticate(driver)
        r, init = self._post()
        self.assertEqual(r.status_code, 403)
        init.assert_not_called()

    def test_anonymous_rejected(self):
        r = APIClient().post(self.url, {'amount': '500'}, format='json')
        self.assertIn(r.status_code, (401, 403))

    @override_settings(WALLET_TOPUP_ENABLED=False)
    def test_topup_disabled_503(self):
        r, init = self._post()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['code'], 'topup_disabled')
        init.assert_not_called()
        self.assertEqual(WalletTopUp.objects.count(), 0)

    def test_flag_defaults_off_when_setting_absent(self):
        from django.conf import settings
        with override_settings():
            del settings.WALLET_TOPUP_ENABLED
            r, _ = self._post()
        self.assertEqual(r.status_code, 503)

    def test_amount_validation(self):
        cases = {
            '49.99': 'amount_too_small', '20000.01': 'amount_too_large',
            '0': 'invalid_amount', '-100': 'invalid_amount', 'abc': 'invalid_amount',
            'NaN': 'invalid_amount', 'Infinity': 'invalid_amount', '100.123': 'invalid_amount',
            '': 'invalid_amount', None: 'invalid_amount', '1e3': 'invalid_amount',
        }
        from django.core.cache import cache
        for amount, code in cases.items():
            cache.clear()  # 11 attempts would otherwise hit the hourly throttle
            r, init = self._post(amount)
            self.assertEqual(r.status_code, 400, (amount, r.content))
            self.assertEqual(r.data['code'], code, amount)
            init.assert_not_called()
        self.assertEqual(WalletTopUp.objects.count(), 0)

    def test_boundaries_accepted(self):
        for amount in ('50', '20000', '50.50'):
            self.assertEqual(self._post(amount)[0].status_code, 201, amount)

    def test_balance_cap(self):
        with self.settings(WALLET_MAX_BALANCE_KES=1000):
            services_credit(self.user, '600')
            r, _ = self._post('401')
            self.assertEqual((r.status_code, r.data['code']), (400, 'balance_cap'))
            self.assertEqual(self._post('400')[0].status_code, 201)

    def test_gateway_failure_502_keeps_pending_row(self):
        with mock.patch('connect.paystack_extra.initialize', side_effect=GatewayError('down')):
            r = self.client.post(self.url, {'amount': '500'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (502, 'gateway_error'))
        self.assertEqual(WalletTopUp.objects.get().status, 'pending')

    def test_throttled_after_ten_per_hour(self):
        codes = [self._post('100')[0].status_code for _ in range(11)]
        self.assertEqual(codes, [201] * 10 + [429])


def services_credit(user, amount, ref='seed:1'):
    from django.db import transaction
    with transaction.atomic():
        services.credit(user, Decimal(amount), 'deposit', ref)


@override_settings(WALLET_TOPUP_ENABLED=True)
class TopUpNoGatewayInsideAtomicTests(TransactionTestCase):
    def test_no_gateway_call_inside_atomic_topup(self):
        user = make_user()
        client = APIClient()
        client.force_authenticate(user)
        seen = {}

        def fake_init(**kwargs):
            seen['atomic'] = connection.in_atomic_block
            seen['committed_row'] = WalletTopUp.objects.filter(reference=kwargs['reference']).exists()
            return 'https://pay/x'

        with override_settings(CACHES=LOCMEM), mock.patch(
                'connect.paystack_extra.initialize', side_effect=fake_init):
            r = client.post(reverse('wallet-topup'), {'amount': '500'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(seen, {'atomic': False, 'committed_row': True})


class ApplyTopUpTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.row = pending(self.user, '500.00')

    def test_credits_once_and_marks_credited(self):
        self.assertEqual(topup.apply_topup_charge(self.row.reference, charge(self.row)), 'credited')
        self.assertEqual(topup.apply_topup_charge(self.row.reference, charge(self.row)), 'already_credited')
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.amount_paid), ('credited', Decimal('500.00')))
        self.assertIsNotNone(self.row.credited_at)
        self.assertEqual(balance(self.user), Decimal('500.00'))
        tx = WalletTransaction.objects.get()
        self.assertEqual((tx.type, tx.reference), ('deposit', f'topup:{self.row.reference}'))

    def test_amount_mismatch_credits_paid_and_alerts(self):
        with mock.patch('wallets.alerts.send') as alert:
            topup.apply_topup_charge(self.row.reference, charge(self.row, amount='450'))
        self.assertEqual(balance(self.user), Decimal('450.00'))
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.amount_paid), ('credited', Decimal('450.00')))
        alert.assert_called_once()

    def test_wrong_user_metadata_goes_to_review_no_credit(self):
        with mock.patch('wallets.alerts.send') as alert:
            r = topup.apply_topup_charge(self.row.reference, charge(self.row, user_id=self.user.id + 99))
        self.assertEqual(r, 'review')
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'review')
        self.assertFalse(Wallet.objects.filter(user=self.user).exists())
        alert.assert_called_once()

    def test_wrong_currency_and_bad_amount_go_to_review(self):
        bad = ({'currency': 'USD'}, {'amount': 'x'}, {'amount': 0}, {'amount': None})
        for i, override in enumerate(bad):
            row = pending(make_user(f'u{i}', f'+25470099900{i}'))
            with mock.patch('wallets.alerts.send'):
                result = topup.apply_topup_charge(row.reference, {**charge(row), **override})
            self.assertEqual(result, 'review', override)
            row.refresh_from_db()
            self.assertEqual(row.status, 'review')
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_review_row_is_not_credited_by_a_later_replay(self):
        with mock.patch('wallets.alerts.send'):
            topup.apply_topup_charge(self.row.reference, charge(self.row, currency='USD'))
            self.assertEqual(
                topup.apply_topup_charge(self.row.reference, charge(self.row)), 'review')
        self.assertEqual(WalletTransaction.objects.count(), 0)

    def test_non_success_status_changes_nothing(self):
        self.assertEqual(
            topup.apply_topup_charge(self.row.reference, charge(self.row, status='abandoned')),
            'pending')
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'pending')

    def test_expired_row_still_credits(self):
        WalletTopUp.objects.filter(pk=self.row.pk).update(status='expired')
        self.assertEqual(topup.apply_topup_charge(self.row.reference, charge(self.row)), 'credited')
        self.assertEqual(balance(self.user), Decimal('500.00'))

    def test_unknown_reference_alerts_and_credits_nothing(self):
        with mock.patch('wallets.alerts.send') as alert:
            self.assertEqual(topup.apply_topup_charge('TOPUP-999-XXXXXXXXXX', {}), 'unknown')
        alert.assert_called_once()

    @override_settings(WALLET_TOPUP_ENABLED=False)
    def test_topup_credited_when_flag_off(self):
        self.assertEqual(topup.apply_topup_charge(self.row.reference, charge(self.row)), 'credited')
        self.assertEqual(balance(self.user), Decimal('500.00'))


class WebhookHookTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.row = pending(self.user)

    def _event(self, data=None, event='charge.success'):
        return {'event': event, 'data': data if data is not None else charge(self.row)}

    @override_settings(WALLET_TOPUP_ENABLED=False)
    def test_topup_charge_is_handled_and_credited_even_with_flag_off(self):
        self.assertTrue(webhook.handle_event(self._event()))
        self.assertEqual(balance(self.user), Decimal('500.00'))

    def test_duplicate_deliveries_credit_once(self):
        for _ in range(5):
            self.assertTrue(webhook.handle_event(self._event()))
        self.assertEqual(balance(self.user), Decimal('500.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)

    def test_booking_charge_is_not_handled(self):
        self.assertFalse(webhook.handle_event(self._event({'reference': 'CONNECT-1-ABC'})))
        self.assertFalse(webhook.handle_event(self._event({'reference': 'PCL-1-ABCDEFGHJK'})))
        self.assertFalse(webhook.handle_event({'event': 'refund.processed', 'data': {'reference': 'TOPUP-1-x'}}))
        self.assertFalse(webhook.handle_event({'event': 'charge.success', 'data': {}}))
        self.assertFalse(webhook.handle_event({'event': 'charge.success', 'data': {'reference': None}}))

    def test_topup_reference_without_row_is_handled_with_alert(self):
        with mock.patch('wallets.alerts.send') as alert:
            self.assertTrue(webhook.handle_event(self._event({'reference': 'TOPUP-7-ZZZZZZZZZZ'})))
        alert.assert_called_once()

    def test_non_charge_events_ignored(self):
        self.assertFalse(webhook.handle_event(self._event(event='transfer.success')))
        self.assertEqual(WalletTransaction.objects.count(), 0)


@unittest.skipUnless(POSTGRES, 'needs real row locks')
class TopUpWebhookConcurrencyTests(TransactionTestCase):
    def test_topup_webhook_duplicate_credits_once(self):
        user = make_user()
        row = pending(user)
        barrier = threading.Barrier(3)
        errors = []

        def deliver():
            try:
                barrier.wait()
                for _ in range(5):
                    webhook.handle_event({'event': 'charge.success', 'data': charge(row)})
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=deliver) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(balance(user), Decimal('500.00'))
        self.assertEqual(WalletTransaction.objects.count(), 1)


@override_settings(CACHES=LOCMEM)
class TopUpStatusTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = make_user()
        self.row = pending(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('wallet-topup-status', kwargs={'reference': self.row.reference})

    def test_verify_on_read_credits_once(self):
        with mock.patch('connect.paystack_extra.verify', return_value=charge(self.row)) as verify:
            r1 = self.client.get(self.url)
            r2 = self.client.get(self.url)
        self.assertEqual((r1.status_code, r1.data['status']), (200, 'credited'))
        self.assertEqual(r2.data['status'], 'credited')
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(balance(self.user), Decimal('500.00'))
        self.assertEqual(r1.data['amount'], '500.00')

    @override_settings(WALLET_TOPUP_ENABLED=False)
    def test_verify_on_read_works_with_flag_off(self):
        with mock.patch('connect.paystack_extra.verify', return_value=charge(self.row)):
            self.assertEqual(self.client.get(self.url).data['status'], 'credited')

    def test_cooldown_blocks_second_gateway_call_while_pending(self):
        with mock.patch('connect.paystack_extra.verify',
                        return_value=charge(self.row, status='abandoned')) as verify:
            r1 = self.client.get(self.url)
            r2 = self.client.get(self.url)
        self.assertEqual((r1.data['status'], r2.data['status']), ('pending', 'pending'))
        self.assertEqual(verify.call_count, 1)

    def test_gateway_error_returns_current_state(self):
        with mock.patch('connect.paystack_extra.verify', side_effect=GatewayError('down')):
            r = self.client.get(self.url)
        self.assertEqual((r.status_code, r.data['status']), (200, 'pending'))

    def test_verify_data_for_other_reference_is_ignored(self):
        other = pending(make_user('o2', '+254700000299'))
        with mock.patch('connect.paystack_extra.verify', return_value=charge(other)):
            r = self.client.get(self.url)
        self.assertEqual(r.data['status'], 'pending')
        self.assertFalse(WalletTransaction.objects.exists())

    def test_other_user_gets_404(self):
        self.client.force_authenticate(make_user('o3', '+254700000298'))
        with mock.patch('connect.paystack_extra.verify') as verify:
            r = self.client.get(self.url)
        self.assertEqual(r.status_code, 404)
        verify.assert_not_called()

    def test_unknown_reference_404(self):
        r = self.client.get(reverse('wallet-topup-status', kwargs={'reference': 'TOPUP-1-NOPE'}))
        self.assertEqual(r.status_code, 404)

    def test_non_passenger_403(self):
        self.client.force_authenticate(make_user('drv2', '+254700000297', role='driver'))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class SweepTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def _age(self, row, minutes):
        WalletTopUp.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - dt.timedelta(minutes=minutes))

    def _sweep(self, **verify_kw):
        out = StringIO()
        with mock.patch('connect.paystack_extra.verify', **verify_kw) as verify:
            call_command('wallet_sweeps', stdout=out)
        return verify, out.getvalue()

    def test_sweep_credits_lost_webhook_once(self):
        row = pending(self.user)
        self._age(row, 10)
        verify, _ = self._sweep(return_value=charge(row))
        self.assertEqual(balance(self.user), Decimal('500.00'))
        self._sweep(return_value=charge(row))
        self.assertEqual(balance(self.user), Decimal('500.00'))
        self.assertEqual(verify.call_count, 1)

    def test_fresh_pending_is_not_verified(self):
        row = pending(self.user)
        self._age(row, 2)
        verify, _ = self._sweep(return_value=charge(row))
        verify.assert_not_called()

    def test_older_than_24h_expires_without_credit(self):
        row = pending(self.user)
        self._age(row, 25 * 60)
        verify, _ = self._sweep(return_value=charge(row))
        row.refresh_from_db()
        self.assertEqual(row.status, 'expired')
        verify.assert_not_called()
        self.assertFalse(WalletTransaction.objects.exists())

    def test_gateway_error_leaves_row_pending_and_continues(self):
        a, b = pending(self.user), pending(make_user('sw2', '+254700000231'))
        self._age(a, 10)
        self._age(b, 10)
        _, out = self._sweep(side_effect=[GatewayError('down'), charge(b)])
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.status, b.status), ('pending', 'credited'))

    def test_sweep_also_checks_the_ledger(self):
        services_credit(self.user, '10')
        Wallet.objects.filter(user=self.user).update(available_balance=Decimal('99'))
        with mock.patch('wallets.alerts.send'):
            with self.assertRaises(CommandError):
                self._sweep(return_value={})


class TransactionsEndpointTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_lists_only_own_rows_newest_first(self):
        other = make_user('ot', '+254700000241')
        services_credit(self.user, '100', 'topup:1')
        services_credit(other, '999', 'topup:2')
        services_credit(self.user, '5', 'topup:3')
        r = self.client.get(reverse('wallet-transactions'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t['amount'] for t in r.data], ['5.00', '100.00'])
        self.assertEqual(set(r.data[0]), {'id', 'type', 'amount', 'balance_after', 'reference', 'booking', 'created_at'})

    def test_non_passenger_403(self):
        self.client.force_authenticate(make_user('dr3', '+254700000242', role='driver'))
        self.assertEqual(self.client.get(reverse('wallet-transactions')).status_code, 403)


class InitializePayloadTests(TestCase):
    def _payload(self, **kw):
        from connect import paystack_extra
        response = mock.Mock(status_code=200)
        response.json.return_value = {'status': True, 'data': {'authorization_url': 'https://pay/x'}}
        with mock.patch('connect.paystack_extra.requests.post', return_value=response) as post:
            paystack_extra.initialize(
                email='a@b.co', amount=Decimal('50'), reference='TOPUP-1-X',
                callback_url='http://x/', metadata={}, **kw)
        return post.call_args.kwargs['json']

    def test_channels_sent_when_given(self):
        self.assertEqual(self._payload(channels=['mobile_money'])['channels'], ['mobile_money'])

    def test_channels_omitted_by_default_so_other_callers_are_unchanged(self):
        self.assertNotIn('channels', self._payload())
