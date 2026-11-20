"""Mixed-path races on seats and money (PostgreSQL only: they need real row locks)."""
import datetime as dt
import time
import unittest
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from bookings import services as bs
from bookings.models import Booking, Payment, Payout, UnappliedPayment
from bookings.services import seats_taken
from bookings.tests.review_base import PG, User, WorldMixin, fund, run_together
from bookings.tests.sim import fake_gateway as fg
from companies.models import Trip

pg_only = unittest.skipUnless(PG, 'needs row locks')


def charge(reference, subunits):
    return {'event': 'charge.success', 'data': {
        'reference': reference, 'amount': subunits, 'currency': 'KES', 'status': 'success'}}


@pg_only
class SeatRaceAcrossPathsTests(WorldMixin, TransactionTestCase):
    def _round(self, i):
        trip = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=3, status='boarding',
                                   departure_at=timezone.now() + dt.timedelta(minutes=40))
        other = Trip.objects.create(route=self.r1, driver=self.drv, capacity=14, status='scheduled',
                                    departure_at=timezone.now() + dt.timedelta(hours=3))
        mk = User.objects.create_user
        filler = mk(username=f'f{i}', password='x', phone_number=f'+25474400{i:04d}')
        racer = mk(username=f'r{i}', password='x', phone_number=f'+25474500{i:04d}')
        holder = mk(username=f'h{i}', password='x', phone_number=f'+25474600{i:04d}')
        self.booking(filler, trip, 1, 'confirmed')
        moved = self.booking(holder, other, 1, 'confirmed')
        expired = self.booking(holder, trip, 1, 'pending', held_until=timezone.now() - dt.timedelta(minutes=2))
        Payment.objects.create(booking=expired, amount=Decimal('100'), method='cash', status='pending')

        def create():
            return self.api(racer).post('/api/bookings/create/', {
                'trip_id': trip.id, 'seats': 1, 'pickup_stage_id': self.s1.id}, format='json').status_code

        def walk():
            return self.api(self.op_all).post(f'/api/bookings/walk-in/{trip.id}/', {
                'seats': 1, 'phone_number': f'07551{i:05d}'}, format='json').status_code

        def move():
            return self.api(self.mgr).post(
                f'/api/bookings/{moved.id}/move-trip/', {'trip_id': trip.id}, format='json').status_code

        def confirm():
            return self.api(self.mgr).post(
                f'/api/bookings/payments/{expired.id}/cash/confirm/', {}, format='json').status_code

        out, errs = run_together([create, walk, move, confirm])
        return trip, out, errs

    def test_four_paths_for_two_open_seats_never_oversell(self):
        for i in range(8):
            trip, out, errs = self._round(i)
            self.assertEqual(errs, [])
            self.assertEqual(seats_taken(trip), trip.capacity, (i, out))
            self.assertEqual(sum(1 for c in out if c in (200, 201)), 2, (i, out))

    def test_two_racers_a_walk_in_a_move_and_a_cash_confirm_never_exceed_capacity(self):
        trip = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=3, status='boarding',
                                   departure_at=timezone.now() + dt.timedelta(minutes=40))
        other = Trip.objects.create(route=self.r1, driver=self.drv, capacity=14, status='scheduled',
                                    departure_at=timezone.now() + dt.timedelta(hours=4))
        filler = self.passenger()
        for round_ in range(12):
            Booking.objects.filter(trip__in=[trip, other]).delete()
            self.booking(filler, trip, 1, 'confirmed')
            expired = self.booking(self.passenger(), trip, 1, 'pending',
                                   held_until=timezone.now() - dt.timedelta(minutes=1))
            Payment.objects.create(booking=expired, amount=Decimal('100'), method='cash',
                                   status='pending', settlement_status='not_ready')
            moving = self.booking(self.passenger(), other, 1, 'confirmed')
            racers = [self.passenger(), self.passenger()]

            def book(u):
                return lambda: self.api(u).post('/api/bookings/create/', {
                    'trip_id': trip.id, 'seats': 1, 'pickup_stage_id': self.s1.id}, format='json').status_code

            def walkin():
                return self.api(self.mgr).post(f'/api/bookings/walk-in/{trip.id}/', {
                    'seats': 1, 'phone_number': f'+25471299{round_:04d}'}, format='json').status_code

            def move():
                return self.api(self.mgr).post(
                    f'/api/bookings/{moving.id}/move-trip/', {'trip_id': trip.id}, format='json').status_code

            def cash():
                return self.api(self.mgr).post(f'/api/bookings/payments/{expired.id}/cash/confirm/').status_code

            res, errs = run_together([book(racers[0]), book(racers[1]), walkin, move, cash])
            self.assertEqual(errs, [], round_)
            self.assertLessEqual(seats_taken(Trip.objects.get(pk=trip.pk)), 3, (round_, res))


@pg_only
class WebhookVsWalletTests(WorldMixin, TransactionTestCase):
    def test_wallet_pay_between_lookup_and_locks_refunds_the_digital_charge_once(self):
        from wallets.models import Wallet
        b = self.booking(self.pax, self.trip1, 1, 'pending', held_until=timezone.now() + dt.timedelta(minutes=5))
        ref = 'CONNECT-%d-' % b.id + 'a' * 32
        Payment.objects.create(booking=b, amount=Decimal('100'), method='digital', status='pending',
                               provider_reference=ref)
        fund(self.pax, 100, 'topup:T0')
        event = self.fake.customer_pays(ref, 100, metadata={'booking_id': b.id, 'user_id': self.pax.id})
        real = bs._lock_payment_chain

        def slow(*a, **k):
            time.sleep(0.6)
            return real(*a, **k)

        def hook():
            with mock.patch('bookings.services._lock_payment_chain', slow), \
                    mock.patch('bookings.views.send_admin_alert_sms'):
                return fg.post_event(APIClient(), event).status_code

        def wallet():
            time.sleep(0.2)
            return self.api(self.pax).post(f'/api/bookings/payments/{b.id}/wallet/', {}, format='json').status_code

        out, errs = run_together([hook, wallet])
        self.assertEqual(errs, [], out)
        self.assertEqual(out, [200, 200])
        self.assertEqual(Payment.objects.get(booking=b).method, 'wallet')
        self.assertEqual(Wallet.objects.get(user=self.pax).available_balance, Decimal('0.00'))
        self.assertEqual(self.fake.refunded_subunits(ref), 10000)
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)

    def test_webhook_vs_wallet_pay_never_pays_twice(self):
        from wallets.models import Wallet, WalletTransaction
        for i in range(20):
            u = self.passenger()
            fund(u, 500, f'topup:t-{u.pk}')
            b = self.booking(u, self.trip1, 1, 'pending', held_until=timezone.now() + dt.timedelta(minutes=5))
            ref = f'CONNECT-{b.pk}-' + format(i, 'x').rjust(32, 'c')
            Payment.objects.create(booking=b, amount=Decimal('100'), method='digital',
                                   status='pending', provider_reference=ref)
            res, errs = run_together([
                lambda: fg.post_event(APIClient(), charge(ref, 10000)).status_code,
                lambda: self.api(u).post(f'/api/bookings/payments/{b.id}/wallet/').status_code])
            self.assertEqual(errs, [], (i, res))
            spent = WalletTransaction.objects.filter(reference=f'spend:{b.pk}').exists()
            unapplied = UnappliedPayment.objects.filter(reference=ref)
            balance = Wallet.objects.get(user=u).available_balance
            b.refresh_from_db()
            self.assertEqual(b.status, 'confirmed', (i, res))
            if spent:
                # the wallet won: the card charge is queued for refund, balance debited once
                self.assertEqual(balance, Decimal('400.00'), (i, res))
                self.assertEqual(unapplied.count(), 1, (i, res, balance))
            else:
                self.assertEqual(balance, Decimal('500.00'), (i, res))
                self.assertEqual(unapplied.count(), 0)

    def test_webhook_vs_cancel_refunds_at_most_once(self):
        # A boarding trip refuses passenger cancels, so use one well before the cut-off.
        trip = Trip.objects.create(route=self.r1, driver=self.drv2, capacity=14, status='scheduled',
                                   departure_at=timezone.now() + dt.timedelta(hours=3))
        for i in range(20):
            u = self.passenger()
            b = self.booking(u, trip, 1, 'pending', held_until=timezone.now() + dt.timedelta(minutes=5))
            ref = f'CONNECT-{b.pk}-' + format(100 + i, 'x').rjust(32, 'c')
            Payment.objects.create(booking=b, amount=Decimal('100'), method='digital',
                                   status='pending', provider_reference=ref)
            self.fake.customer_pays(ref, 100)
            res, errs = run_together([
                lambda: fg.post_event(APIClient(), charge(ref, 10000)).status_code,
                lambda: self.api(u).post(f'/api/bookings/{b.id}/cancel/').status_code])
            self.assertEqual(errs, [], (i, res))
            b.refresh_from_db()
            self.assertEqual(b.status, 'cancelled', (i, res))
            self.assertEqual(len(self.fake.accepted_refunds(ref)), 1, (i, res))


@pg_only
class SettleRaceTests(WorldMixin, TransactionTestCase):
    def test_two_parallel_settle_runs_pay_each_payment_once(self):
        for round_ in range(10):
            Payout.objects.all().delete()
            payments = []
            for _ in range(6):
                b = self.booking(self.passenger(), self.trip1, 1, 'completed')
                payments.append(Payment.objects.create(
                    booking=b, amount=Decimal('100'), method='digital', status='confirmed',
                    provider_reference=f'CONNECT-{b.pk}-' + 'a' * 32, settlement_status='eligible'))

            def settle(ref):
                def go():
                    call_command('settle_company', self.co.id, '--apply', '--reference', ref,
                                 stdout=StringIO())
                return go

            _, errs = run_together([settle(f'R{round_}A'), settle(f'R{round_}B')])
            self.assertEqual(errs, [], round_)
            self.assertEqual(Payout.objects.count(), 1)
            self.assertEqual(Payout.objects.get().payments_count, 6)
            self.assertEqual(Payment.objects.filter(
                payout__isnull=False, pk__in=[p.pk for p in payments]).count(), 6)
            Payment.objects.filter(pk__in=[p.pk for p in payments]).delete()
