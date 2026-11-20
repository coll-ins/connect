"""World simulation, part 3: wallet top-up, wallet payment, wallet refunds and withdrawals.

Withdrawals run through the REAL PaystackTransfers adapter over the fake
gateway. The adapter's Paystack names are UNVERIFIED (evidence.md BE-W3): this
proves the adapter and the ledger agree with each other, not with Paystack.
"""
import datetime as dt
import unittest
from decimal import Decimal

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from bookings import services
from bookings.models import Booking
from wallets import sweeps
from wallets import services as ws
from wallets.models import Wallet, WalletPayout, WalletTopUp, WalletTransaction

from . import fake_gateway as fg
from .base import PASSWORD, POSTGRES, SimCase


class WalletCase(SimCase):
    def setUp(self):
        super().setUp()
        self.company, self.route = self.ready_route(0, 0, index=1)
        self.trip_ = self.trip(self.route, minutes=90)
        self.fare = self.route.price

    def topup(self, user, amount):
        r = self.api(user).post(reverse('wallet-topup'), {'amount': str(amount)}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        reference = r.json()['reference']
        event = self.fake.customer_pays(reference, amount, metadata={'purpose': 'wallet_topup', 'user_id': user.pk})
        return reference, event

    def balance(self, user):
        return Wallet.objects.get(user=user).available_balance

    def fund(self, user, amount):
        reference, event = self.topup(user, amount)
        self.assertEqual(self.webhook(event).status_code, 200)

    def ledger(self, user):
        return Decimal(sum(t.amount for t in WalletTransaction.objects.filter(wallet__user=user)))


class TopUpAndSpendTests(WalletCase):
    def test_topup_credits_once_for_replays_verify_and_sweep(self):
        user = self.user()
        reference, event = self.topup(user, 500)
        for _ in range(5):
            self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual(self.balance(user), Decimal('500'))
        r = self.api(user).get(reverse('wallet-topup-status', args=[reference]))
        self.assertEqual(r.json()['status'], 'credited')
        sweeps.sweep_topups()
        self.assertEqual(self.balance(user), Decimal('500'))
        self.assertEqual(WalletTransaction.objects.filter(wallet__user=user).count(), 1)
        if POSTGRES:
            ref2, event2 = self.topup(user, 100)
            results, errors = self.run_threads([lambda: self.webhook(event2).status_code] * 6)
            self.assertEqual((errors, set(results)), ([], {200}))
            self.assertEqual(self.balance(user), Decimal('600'))

    def test_a_lost_webhook_is_recovered_by_verify_on_read(self):
        user = self.user()
        reference, event = self.topup(user, 200)          # the webhook never arrives
        r = self.api(user).get(reverse('wallet-topup-status', args=[reference]))
        self.assertEqual(r.json()['status'], 'credited')
        self.assertEqual(self.balance(user), Decimal('200'))

    def test_topup_with_a_different_amount_wrong_user_or_currency(self):
        user, other = self.user(), self.user()
        reference, event = self.topup(user, 300)
        event = self.fake.customer_pays(reference, 250, metadata={'user_id': user.pk})
        self.webhook(event)
        self.assertEqual(self.balance(user), Decimal('250'), 'credit what Paystack received')
        self.assertTrue(self.alerts('requested KES 300'))
        ref2, _ = self.topup(user, 100)
        self.webhook(self.fake.customer_pays(ref2, 100, metadata={'user_id': other.pk}))
        self.assertEqual(WalletTopUp.objects.get(reference=ref2).status, 'review')
        ref3, _ = self.topup(user, 100)
        self.webhook(self.fake.customer_pays(ref3, 100, currency='USD', metadata={'user_id': user.pk}))
        self.assertEqual(WalletTopUp.objects.get(reference=ref3).status, 'review')
        self.assertEqual(self.balance(user), Decimal('250'))

    def test_topup_flag_off_stops_new_topups_but_never_a_credit(self):
        user = self.user()
        reference, event = self.topup(user, 100)
        with self.settings(WALLET_TOPUP_ENABLED=False):
            r = self.api(user).post(reverse('wallet-topup'), {'amount': '100'}, format='json')
            self.assertEqual(r.status_code, 503)
            self.webhook(event)
        self.assertEqual(self.balance(user), Decimal('100'))

    def test_pay_booking_from_wallet_then_refund_rules_go_back_to_the_wallet(self):
        user = self.user()
        self.fund(user, 1000)
        booking = self.booking(user, self.trip_)
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual((r.status_code, r.json()['replayed']), (200, False))
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual((r.status_code, r.json()['replayed']), (200, True))
        self.assertEqual(self.balance(user), 1000 - self.fare)
        self.cancel(user, booking)                                    # passenger fault: 50% back
        self.assertEqual(self.balance(user), 1000 - self.fare / 2)
        self.assertEqual(self.fake.accepted_refunds(), [], 'a wallet refund must not reach the gateway')
        booking2 = self.booking(user, self.trip_)
        self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking2.pk]), {}, format='json')
        self.cancel(self.staff(self.company, 'company_manager'), booking2, fault='company')   # company fault: all back
        self.assertEqual(self.balance(user), 1000 - self.fare / 2)
        self.assertEqual(self.ledger(user), self.balance(user))

    def test_wallet_refusals_leave_nothing_changed(self):
        user = self.user()
        booking = self.booking(user, self.trip_)
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual((r.status_code, r.json()['code']), (400, 'insufficient_funds'))
        self.fund(user, 500)
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {'amount': '1'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.expire_hold(booking)
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual((r.status_code, r.json()['code']), (409, 'hold_expired'))
        self.assertEqual(self.balance(user), Decimal('500'))
        stranger = self.user()
        r = self.api(stranger).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual(r.status_code, 404)
        staff = self.staff(self.company, 'company_manager')
        self.assertEqual(self.api(staff).post(reverse('wallet-topup'), {'amount': '100'}, format='json').status_code, 403)

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_two_parallel_spends_of_one_balance_only_one_succeeds(self):
        user = self.user()
        self.fund(user, int(self.fare))                    # enough for exactly one booking
        trip2 = self.trip(self.route, minutes=120)
        b1, b2 = self.booking(user, self.trip_), self.booking(user, trip2)
        jobs = [lambda b=b: self.api(user).post(
            reverse('bookings:pay-from-wallet', args=[b.pk]), {}, format='json').status_code for b in (b1, b2)]
        codes, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(codes), [200, 400])
        self.assertEqual(self.balance(user), Decimal('0'))

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_wallet_refund_by_sweep_versus_cancel_has_no_deadlock(self):
        manager = self.staff(self.company, 'company_manager')
        for i in range(50):
            user = self.user()
            self.fund(user, 500) if i == 0 else ws_credit(user, 500, f'topup:sim-{i}-{user.pk}')
            booking = self.booking(user, self.trip_)
            self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
            jobs = [
                lambda: self.api(manager).post(reverse('bookings:cancel-booking', args=[booking.pk]),
                                                {'fault_party': 'company'}, format='json').status_code,
                lambda: services.settle_booking_fault(Booking.objects.get(pk=booking.pk), 'company'),
            ]
            results, errors = self.run_threads(jobs)
            self.assertEqual(errors, [], f'iteration {i}')
            self.assertEqual(self.balance(user), Decimal('500'), f'iteration {i}: refunded once, in full')
            self.assertEqual(WalletTransaction.objects.filter(wallet__user=user, type='refund').count(), 1)


def ws_credit(user, amount, reference):
    with transaction.atomic():
        ws.credit(user, Decimal(amount), 'deposit', reference)


class WithdrawalTests(WalletCase):
    def setUp(self):
        super().setUp()
        self.user_ = self.user()
        ws_credit(self.user_, 1000, f'topup:sim-wd-{self.user_.pk}')
        self.n = 0

    def withdraw(self, amount, key=None, user=None, password=PASSWORD, expect=None, **extra):
        self.n += 1
        body = {'amount': str(amount), 'idempotency_key': key or f'sim-key-{self.n:04d}', 'password': password, **extra}
        r = self.api(user or self.user_).post(reverse('wallet-withdraw'), body, format='json')
        if expect is not None:
            self.assertEqual(r.status_code, expect, r.content)
        return r

    def payout(self, pk=None):
        return WalletPayout.objects.get(pk=pk) if pk else WalletPayout.objects.latest('id')

    def old(self):
        return timezone.now() + dt.timedelta(minutes=5)

    def test_success_through_the_webhook(self):
        self.withdraw(300, expect=201)
        payout = self.payout()
        self.assertEqual((payout.status, self.balance(self.user_)), ('submitted', Decimal('700')))
        self.assertEqual(self.fake.transfers[payout.reference]['amount'], 30000)
        self.webhook(fg.transfer_event('success', payout.reference, 300))
        self.webhook(fg.transfer_event('success', payout.reference, 300))
        self.assertEqual(self.payout().status, 'paid')
        self.assertEqual(self.balance(self.user_), Decimal('700'))

    def test_a_definite_refusal_reverses_once(self):
        self.fake.fault('transfer', fg.HTTP_400, message='Your balance is not enough to fulfil this request')
        self.withdraw(300, expect=201)
        payout = self.payout()
        self.assertEqual((payout.status, self.balance(self.user_)), ('failed', Decimal('1000')))
        self.assertTrue(self.alerts('Top up the Paystack balance'))
        self.webhook(fg.transfer_event('failed', payout.reference, 300))
        sweeps.sweep_payouts(now=self.old())
        self.assertEqual(self.balance(self.user_), Decimal('1000'))
        self.assertEqual(WalletTransaction.objects.filter(reference=f'wdrev:{payout.pk}').count(), 1)

    def test_a_timeout_is_not_reversed_and_the_sweep_asks_the_gateway(self):
        self.fake.fault('transfer', fg.TIMEOUT_AFTER_ACCEPT)         # money may really have moved
        self.withdraw(300, expect=201)
        payout = self.payout()
        self.assertEqual((payout.status, self.balance(self.user_)), ('requested', Decimal('700')))
        self.fake.set_transfer_status(payout.reference, 'success')
        result = sweeps.sweep_payouts(now=self.old())
        self.assertEqual(result['paid'], 1)
        self.assertEqual((self.payout().status, self.balance(self.user_)), ('paid', Decimal('700')))
        self.assertEqual(len(self.fake.transfers), 1, 'the sweep must never resend')

    def test_timeout_then_gateway_says_failed_reverses_once(self):
        self.fake.fault('transfer', fg.TIMEOUT_AFTER_ACCEPT)
        self.withdraw(300, expect=201)
        payout = self.payout()
        self.fake.set_transfer_status(payout.reference, 'failed')
        sweeps.sweep_payouts(now=self.old())
        sweeps.sweep_payouts(now=self.old())
        self.assertEqual((self.payout().status, self.balance(self.user_)), ('failed', Decimal('1000')))

    def test_timeout_where_the_gateway_never_saw_it_goes_to_review_not_reversal(self):
        self.fake.fault('transfer', fg.TIMEOUT)
        self.withdraw(300, expect=201)
        sweeps.sweep_payouts(now=self.old())
        payout = self.payout()
        self.assertEqual((payout.status, self.balance(self.user_)), ('review', Decimal('700')))
        self.assertTrue(self.alerts('needs review'))
        self.assertEqual(len(self.fake.transfers), 0)

    def test_success_after_a_reversal_is_flagged_for_a_human(self):
        self.fake.fault('transfer', fg.HTTP_400, message='refused')
        self.withdraw(300, expect=201)
        payout = self.payout()
        self.webhook(fg.transfer_event('success', payout.reference, 300))
        self.assertEqual(self.payout().status, 'failed')
        self.assertTrue(self.alerts('PAID'))

    def test_input_rules(self):
        self.withdraw(300, expect=201)
        self.withdraw(100, expect=409)                                  # one in flight
        self.withdraw(100, password='wrong', expect=403)
        self.withdraw(100, expect=400, phone='+254700000000')           # destination is never a field
        self.withdraw(5, expect=400)
        self.withdraw(30000, expect=400)
        self.withdraw(100, key='x', expect=400)
        self.withdraw(100, user=self.staff(self.company, 'company_manager'), expect=403)
        self.assertEqual(self.balance(self.user_), Decimal('700'))

    def test_same_key_replays_and_a_reused_key_with_another_amount_is_refused(self):
        self.withdraw(300, key='sim-same-key', expect=201)
        self.withdraw(300, key='sim-same-key', expect=200)
        self.withdraw(400, key='sim-same-key', expect=409)
        self.assertEqual(WalletPayout.objects.count(), 1)
        self.assertEqual(self.balance(self.user_), Decimal('700'))

    def test_daily_limit_over_sequential_withdrawals(self):
        ws_credit(self.user_, 49000, f'topup:sim-big-{self.user_.pk}')
        for i in range(3):
            self.withdraw(10000, expect=201)
            payout = self.payout()
            self.webhook(fg.transfer_event('success', payout.reference, 10000))
        self.withdraw(1000, expect=400)
        self.assertEqual(self.balance(self.user_), Decimal('20000'))

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_eight_parallel_requests_with_one_key_make_one_payout(self):
        jobs = [lambda: self.withdraw(300, key='sim-parallel-key').status_code] * 8
        codes, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(set(codes)), [200, 201])
        self.assertEqual(codes.count(201), 1)
        self.assertEqual(WalletPayout.objects.count(), 1)
        self.assertEqual(len(self.fake.transfers), 1)
        self.assertEqual(self.balance(self.user_), Decimal('700'))

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_parallel_different_keys_respect_the_daily_limit(self):
        ws_credit(self.user_, 49000, f'topup:sim-big-{self.user_.pk}')
        jobs = [lambda i=i: self.withdraw(10000, key=f'sim-par-key-{i}').status_code for i in range(6)]
        codes, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        self.assertEqual(codes.count(201), 1, 'one withdrawal at a time per user')
        self.assertLessEqual(self.balance(self.user_), Decimal('40000'))
