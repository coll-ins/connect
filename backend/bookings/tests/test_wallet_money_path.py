"""Wallet inside the booking money path (BE-W2): spend, refund, webhook hook,
settlement, dispatcher move. Postgres-only classes at the bottom."""
import datetime as dt
import hashlib
import hmac
import json
import re
import threading
import unittest
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from bookings import services
from bookings.models import Booking, BookingHold, Payment, Payout, UnappliedPayment
from bookings.services import settle_booking_fault
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver
from wallets import services as wallet_services
from wallets.models import Wallet, WalletTopUp, WalletTransaction

User = get_user_model()
MIN = dt.timedelta(minutes=1)
WEBHOOK = '/api/bookings/webhooks/paystack/'


def _locks(queries):
    found = []
    for q in queries:
        if 'FOR UPDATE' in q['sql']:
            found.append(re.search(r'FROM "(\w+)"', q['sql']).group(1))
    return found


class WalletBase:
    """Fixtures shared by the TestCase and TransactionTestCase classes."""

    def build(self):
        self.company = Company.objects.create(name='Wal Co', areas_served='Nairobi')
        self.route = Route.objects.create(
            company=self.company, name='CBD - Ngong', start_point='CBD',
            end_point='Ngong', price=Decimal('100'))
        self.stage = PickupStage.objects.create(
            route=self.route, name='Kencom', order=1,
            latitude=Decimal('-1.2856'), longitude=Decimal('36.8250'))
        self.driver = Driver.objects.create(
            name='D', phone_number='+254711000000', bus_number='KDA 001A',
            company=self.company)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, capacity=14, status='scheduled',
            departure_at=timezone.now() + dt.timedelta(hours=3))
        self.n = 0
        self.staff = User.objects.create_user(
            username='root', password='pw-123456', phone_number='+254711888888',
            is_superuser=True, is_staff=True)

    def passenger(self, balance=None):
        self.n += 1
        user = User.objects.create_user(
            username=f'pax{self.n}', password='pw-123456',
            phone_number=f'+2547119{self.n:05d}', role='passenger')
        if balance is not None:
            wallet_services_fund(user, balance)
        return user

    def pending(self, user, amount='100', held_for=5, seats=1):
        return Booking.objects.create(
            user=user, trip=self.trip, route=self.route, driver=self.driver,
            seats=seats, total_amount=Decimal(amount), status='pending',
            held_until=timezone.now() + held_for * MIN,
            pickup_location='Kencom', pickup_stage=self.stage)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def pay(self, user, booking, **body):
        return self.client_for(user).post(
            f'/api/bookings/payments/{booking.id}/wallet/', body, format='json')

    def balance(self, user):
        return Wallet.objects.get(user=user).available_balance

    def wallet_paid(self, user, amount='100'):
        """A confirmed wallet-paid booking, made through the real endpoint."""
        booking = self.pending(user, amount)
        resp = self.pay(user, booking)
        assert resp.status_code == 200, resp.content
        return Booking.objects.get(pk=booking.pk)


def wallet_services_fund(user, amount):
    from django.db import transaction
    with transaction.atomic():
        wallet_services.credit(user, Decimal(str(amount)), 'deposit',
                               f'topup:test-{user.pk}-{amount}')


class WalletPayTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def test_wallet_pay_confirms_and_holds(self):
        user = self.passenger(500)
        booking = self.pending(user)
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['method'], 'wallet')
        self.assertEqual(resp.data['status'], 'confirmed')
        self.assertEqual(resp.data['booking_status'], 'confirmed')
        self.assertEqual(resp.data['balance'], '400.00')
        booking.refresh_from_db()
        payment = booking.payment
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(
            (payment.method, payment.status, payment.amount, payment.paid_amount,
             payment.provider_reference, payment.idempotency_key),
            ('wallet', 'confirmed', Decimal('100.00'), Decimal('100.00'), None, None))
        self.assertIsNotNone(payment.confirmed_at)
        self.assertEqual(booking.financial_hold.status, 'held')
        row = WalletTransaction.objects.get(reference=f'spend:{booking.id}')
        self.assertEqual((row.type, row.amount, row.booking_id),
                         ('spend', Decimal('-100.00'), booking.id))
        self.assertEqual(self.balance(user), Decimal('400.00'))

    def test_wallet_pay_twice_one_debit(self):
        user = self.passenger(500)
        booking = self.pending(user)
        first = self.pay(user, booking)
        second = self.pay(user, booking)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(second.data['status'], 'confirmed')
        self.assertEqual(
            WalletTransaction.objects.filter(type='spend').count(), 1)
        self.assertEqual(self.balance(user), Decimal('400.00'))

    def test_replay_after_cancel_does_not_revive_or_debit(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        self.client_for(user).post(f'/api/bookings/{booking.id}/cancel/')
        balance = self.balance(user)
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.data['code'], 'already_paid')
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')
        self.assertEqual(self.balance(user), balance)

    def test_wallet_pay_insufficient_changes_nothing(self):
        user = self.passenger(60)
        booking = self.pending(user)
        # An abandoned checkout is overwritten by wallet pay; a failed wallet
        # pay must leave it exactly as it was.
        payment = Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='pending', provider_reference=f'CONNECT-{booking.id}-aa',
            idempotency_key=f'CONNECT-{booking.id}-aa')
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['code'], 'insufficient_funds')
        self.assertEqual(resp.data['balance'], '60.00')
        self.assertEqual(resp.data['required'], '100.00')
        payment.refresh_from_db()
        self.assertEqual((payment.method, payment.status, payment.provider_reference),
                         ('digital', 'pending', f'CONNECT-{booking.id}-aa'))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'pending')
        self.assertFalse(BookingHold.objects.exists())
        self.assertEqual(WalletTransaction.objects.filter(type='spend').count(), 0)
        self.assertEqual(self.balance(user), Decimal('60.00'))

    def test_wallet_pay_with_no_wallet_row_is_insufficient(self):
        user = self.passenger()
        booking = self.pending(user)
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['code'], 'insufficient_funds')
        self.assertEqual(resp.data['balance'], '0.00')

    def test_wallet_pay_expired_hold_409_no_debit(self):
        user = self.passenger(500)
        booking = self.pending(user, held_for=-1)
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.data['code'], 'hold_expired')
        self.assertEqual(self.balance(user), Decimal('500.00'))
        self.assertFalse(Payment.objects.exists())

    def test_wallet_pay_null_hold_counts_as_live(self):
        user = self.passenger(500)
        booking = self.pending(user)
        Booking.objects.filter(pk=booking.pk).update(held_until=None)
        self.assertEqual(self.pay(user, booking).status_code, 200)

    def test_wallet_pay_cancelled_booking_rejected(self):
        user = self.passenger(500)
        booking = self.pending(user)
        Booking.objects.filter(pk=booking.pk).update(status='cancelled')
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self.balance(user), Decimal('500.00'))

    def test_wallet_pay_departed_trip_rejected(self):
        user = self.passenger(500)
        booking = self.pending(user)
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() - MIN)
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(self.balance(user), Decimal('500.00'))

    def test_wallet_pay_already_paid_by_cash_409(self):
        user = self.passenger(500)
        booking = self.pending(user)
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        Payment.objects.create(booking=booking, amount=Decimal('100'),
                               method='cash', status='confirmed')
        resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertEqual(resp.data['code'], 'already_paid')
        self.assertEqual(self.balance(user), Decimal('500.00'))

    def test_wallet_pay_amount_echo_mismatch_400(self):
        user = self.passenger(500)
        booking = self.pending(user)
        for field in ('amount', 'total_amount'):
            resp = self.pay(user, booking, **{field: '1'})
            self.assertEqual(resp.status_code, 400, resp.content)
            self.assertEqual(resp.data['code'], 'amount_mismatch')
            self.assertEqual(resp.data['expected'], '100.00')
        self.assertEqual(self.balance(user), Decimal('500.00'))
        self.assertEqual(self.pay(user, booking, amount='100.00').status_code, 200)

    def test_wallet_pay_owner_only(self):
        owner, other = self.passenger(500), self.passenger(500)
        booking = self.pending(owner)
        self.assertEqual(self.pay(other, booking).status_code, 404)
        self.assertEqual(self.balance(other), Decimal('500.00'))
        self.assertEqual(self.balance(owner), Decimal('500.00'))
        anon = APIClient().post(f'/api/bookings/payments/{booking.id}/wallet/')
        self.assertIn(anon.status_code, (401, 403))

    def test_wallet_pay_passenger_role_only(self):
        user = self.passenger(500)
        booking = self.pending(user)
        User.objects.filter(pk=user.pk).update(role='company_operator')
        resp = self.pay(User.objects.get(pk=user.pk), booking)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data['code'], 'passenger_only')
        self.assertEqual(self.balance(user), Decimal('500.00'))

    def test_wallet_pay_ignores_wallet_flags(self):
        # M6: flags gate top-up init only, never spending existing money.
        user = self.passenger(500)
        booking = self.pending(user)
        with self.settings(WALLET_TOPUP_ENABLED=False):
            self.assertEqual(self.pay(user, booking).status_code, 200)

    def test_late_digital_charge_after_wallet_pay_refunded_in_full(self):
        user = self.passenger(500)
        booking = self.pending(user)
        ref = f'CONNECT-{booking.id}-' + 'a' * 32
        Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='pending', provider_reference=ref, idempotency_key=ref)
        self.assertEqual(self.pay(user, booking).status_code, 200)
        body = json.dumps({'event': 'charge.success', 'data': {
            'reference': ref, 'amount': 10000, 'currency': 'KES'}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        sent = []

        def fake_post(url, json=None, **kw):
            sent.append(json)
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {'status': True, 'data': {'id': 9, 'status': 'pending'}}
            return resp

        with mock.patch('requests.post', fake_post), \
                mock.patch('bookings.views.send_admin_alert_sms'), \
                mock.patch('connect.paystack_extra._alert'):
            resp = APIClient().post(WEBHOOK, data=body, content_type='application/json',
                                    HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([(s['transaction'], s['amount']) for s in sent], [(ref, 10000)])
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(Payment.objects.get(booking=booking).method, 'wallet')

    def test_digital_confirm_that_lost_the_race_to_wallet_pay_is_refunded(self):
        """The webhook found the Payment by reference, then wallet pay committed
        before the webhook got its locks: the digital money must not be kept."""
        user = self.passenger(500)
        booking = self.pending(user)
        ref = f'CONNECT-{booking.id}-' + 'b' * 32
        Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='pending', provider_reference=ref, idempotency_key=ref)
        real = services._lock_payment_chain

        def wallet_pay_first(*args):
            self.pay(user, booking)
            return real(*args)

        outcome = None
        with mock.patch.object(services, '_lock_payment_chain', wallet_pay_first):
            outcome = services.confirm_booking_payment(
                reference=ref, paid_amount=10000, currency='KES')
        self.assertEqual(outcome.result, 'not_found')
        payment = Payment.objects.get(booking=booking)
        self.assertEqual((payment.method, payment.status), ('wallet', 'confirmed'))
        self.assertEqual(self.balance(user), Decimal('400.00'))


class WalletExpiryTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def test_spend_then_expiry_sweep_keeps_booking(self):
        user = self.passenger(500)
        booking = self.pending(user)
        self.assertEqual(self.pay(user, booking).status_code, 200)
        Booking.objects.filter(pk=booking.pk).update(
            status='pending', held_until=timezone.now() - MIN)
        # Even if the row looked pending again, a confirmed payment protects it.
        call_command('expire_pending_bookings', stdout=StringIO())
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'pending')
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        call_command('expire_pending_bookings', stdout=StringIO())
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')

    def test_expiry_then_spend_debits_nothing(self):
        user = self.passenger(500)
        booking = self.pending(user, held_for=-1)
        call_command('expire_pending_bookings', stdout=StringIO())
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')
        resp = self.pay(user, booking)
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertEqual(self.balance(user), Decimal('500.00'))
        self.assertEqual(WalletTransaction.objects.filter(type='spend').count(), 0)


class WalletRefundTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def refund(self, booking, fault):
        with mock.patch('bookings.services.requests.post') as post:
            amount = settle_booking_fault(Booking.objects.get(pk=booking.pk), fault)
        post.assert_not_called()
        return amount

    def test_wallet_refund_passenger_fault_50(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        self.assertEqual(self.refund(booking, 'passenger'), Decimal('50.00'))
        self.assertEqual(self.balance(user), Decimal('450.00'))
        payment = Payment.objects.get(booking=booking)
        self.assertEqual(
            (payment.refund_status, payment.refund_amount, payment.refund_reference,
             payment.status),
            ('processed', Decimal('50.00'), f'WALLET-{payment.pk}', 'confirmed'))
        self.assertIsNotNone(payment.refunded_at)
        hold = BookingHold.objects.get(booking=booking)
        self.assertEqual((hold.refunded_amount, hold.status),
                         (Decimal('50.00'), 'held'))
        row = WalletTransaction.objects.get(reference=f'refund:{payment.pk}')
        self.assertEqual((row.type, row.amount, row.booking_id),
                         ('refund', Decimal('50.00'), booking.id))

    def test_wallet_refund_company_fault_100(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        self.assertEqual(self.refund(booking, 'company'), Decimal('100.00'))
        self.assertEqual(self.balance(user), Decimal('500.00'))
        payment = Payment.objects.get(booking=booking)
        self.assertEqual((payment.status, payment.refund_status),
                         ('refunded', 'processed'))
        hold = BookingHold.objects.get(booking=booking)
        self.assertEqual((hold.status, hold.refunded_amount),
                         ('refunded', Decimal('100.00')))

    def test_wallet_refund_has_no_kes_5_floor(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user, amount='8')
        self.assertEqual(self.refund(booking, 'passenger'), Decimal('4.00'))
        self.assertEqual(self.balance(user), Decimal('496.00'))
        self.assertEqual(
            Payment.objects.get(booking=booking).refund_status, 'processed')

    def test_digital_refund_still_floors_and_goes_to_paystack(self):
        user = self.passenger()
        booking = self.pending(user, amount='8')
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        Payment.objects.create(
            booking=booking, amount=Decimal('8'), method='digital',
            status='confirmed', provider_reference='CONNECT-1-' + 'c' * 32)
        amount, claim = services.claim_booking_refund(booking, 'passenger')
        self.assertEqual((amount, claim), (Decimal('4.00'), None))
        self.assertFalse(WalletTransaction.objects.exists())

        booking2 = self.pending(self.passenger(), amount='100')
        Booking.objects.filter(pk=booking2.pk).update(status='confirmed')
        Payment.objects.create(
            booking=booking2, amount=Decimal('100'), method='digital',
            status='confirmed', provider_reference='CONNECT-2-' + 'd' * 32)
        amount, claim = services.claim_booking_refund(booking2, 'passenger')
        self.assertEqual(amount, Decimal('50.00'))
        self.assertEqual(claim.provider_reference, 'CONNECT-2-' + 'd' * 32)
        self.assertFalse(WalletTransaction.objects.exists())

    def test_wallet_refund_idempotent_x8(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        results = [self.refund(booking, 'passenger') for _ in range(8)]
        self.assertEqual(results, [Decimal('50.00')] * 8)
        self.assertEqual(self.balance(user), Decimal('450.00'))
        self.assertEqual(WalletTransaction.objects.filter(type='refund').count(), 1)
        # A later company-fault call cannot refund a second time either.
        self.assertEqual(self.refund(booking, 'company'), Decimal('50.00'))
        self.assertEqual(self.balance(user), Decimal('450.00'))

    def test_cancel_view_refunds_wallet_payment_to_wallet(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        with mock.patch('bookings.services.requests.post') as post:
            resp = self.client_for(user).post(f'/api/bookings/{booking.id}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content)
        post.assert_not_called()
        self.assertEqual(resp.data['refund_amount'], '50.00')
        self.assertNotIn('refund_status', resp.data)
        self.assertEqual(self.balance(user), Decimal('450.00'))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')

    def test_refund_credits_the_payer_not_the_staff_caller(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        resp = self.client_for(self.staff).post(
            f'/api/bookings/{booking.id}/cancel/', {'fault_party': 'company'},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.balance(user), Decimal('500.00'))
        self.assertFalse(Wallet.objects.filter(user=self.staff).exists())

    def test_refund_webhook_unaffected_by_wallet_branch(self):
        user = self.passenger()
        booking = self.pending(user)
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        ref = 'CONNECT-5-' + 'e' * 32
        payment = Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='digital',
            status='confirmed', provider_reference=ref, refund_status='processing',
            refund_amount=Decimal('50'))
        body = json.dumps({'event': 'refund.processed', 'data': {
            'transaction_reference': ref, 'refund_reference': 'rf-1',
            'amount': 5000}}).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        resp = APIClient().post(WEBHOOK, data=body, content_type='application/json',
                                HTTP_X_PAYSTACK_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.refund_status, 'processed')
        self.assertFalse(WalletTransaction.objects.exists())

    def test_noshow_sweep_refunds_wallet_fare_half(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        Trip.objects.filter(pk=self.trip.pk).update(
            departure_at=timezone.now() - dt.timedelta(hours=2))
        with mock.patch('bookings.services.requests.post') as post:
            call_command('process_noshows', stdout=StringIO())
        post.assert_not_called()
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'no_show')
        self.assertEqual(self.balance(user), Decimal('450.00'))

    def test_noshow_retry_filter_includes_wallet_payments(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user, amount='200')
        Trip.objects.filter(pk=self.trip.pk).update(status='departed')
        Booking.objects.filter(pk=booking.pk).update(status='no_show')
        call_command('process_noshows', stdout=StringIO())
        self.assertEqual(self.balance(user), Decimal('400.00'))
        self.assertEqual(WalletTransaction.objects.filter(type='refund').count(), 1)


class WalletSettlementTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def board(self, booking):
        Trip.objects.filter(pk=self.trip.pk).update(status='boarding')
        Booking.objects.filter(pk=booking.pk).update(verification_pin='1234')
        resp = self.client_for(self.staff).post(
            f'/api/bookings/{booking.id}/verify-boarding/', {'boarding_pin': '1234'},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_settle_company_includes_wallet_payments(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user, amount='300')
        self.board(booking)
        self.assertEqual(Payment.objects.get(booking=booking).settlement_status,
                         'eligible')
        call_command('settle_company', self.company.id, '--apply',
                     '--reference', 'W1', stdout=StringIO())
        payout = Payout.objects.get()
        fee = settings.PLATFORM_FEE_PER_SEAT
        self.assertEqual(payout.gross_amount, Decimal('300.00'))
        self.assertEqual(payout.net_amount, Decimal('300.00') - fee)
        payment = Payment.objects.get(booking=booking)
        self.assertEqual((payment.settlement_status, payment.payout_id),
                         ('settled', payout.id))
        call_command('settle_company', self.company.id, '--apply',
                     '--reference', 'W2', stdout=StringIO())
        self.assertEqual(Payout.objects.count(), 1)

    def test_settle_company_still_excludes_cash(self):
        booking = self.pending(self.passenger())
        Booking.objects.filter(pk=booking.pk).update(status='completed')
        Payment.objects.create(
            booking=booking, amount=Decimal('100'), method='cash',
            status='confirmed', settlement_status='eligible')
        call_command('settle_company', self.company.id, '--apply',
                     '--reference', 'C1', stdout=StringIO())
        self.assertEqual(Payout.objects.count(), 0)


class MoveCutoffTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def target(self, minutes):
        return Trip.objects.create(
            route=self.route, driver=self.driver, capacity=4, status='scheduled',
            departure_at=timezone.now() + minutes * MIN)

    def test_dispatcher_move_inside_cutoff_is_allowed(self):
        booking = self.pending(self.passenger())
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        target = self.target(5)
        resp = self.client_for(self.staff).post(
            f'/api/bookings/{booking.id}/move-trip/', {'trip_id': target.id},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(Booking.objects.get(pk=booking.pk).trip_id, target.id)

    def test_dispatcher_move_still_needs_a_departing_future_trip_with_seats(self):
        booking = self.pending(self.passenger())
        Booking.objects.filter(pk=booking.pk).update(status='confirmed')
        full = self.target(60)
        Trip.objects.filter(pk=full.pk).update(capacity=0)
        resp = self.client_for(self.staff).post(
            f'/api/bookings/{booking.id}/move-trip/', {'trip_id': full.id},
            format='json')
        self.assertEqual(resp.status_code, 409, resp.content)


class TopupHookTests(WalletBase, TestCase):
    def setUp(self):
        self.build()

    def post(self, event):
        body = json.dumps(event).encode()
        sig = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body,
                       hashlib.sha512).hexdigest()
        return APIClient().post(WEBHOOK, data=body, content_type='application/json',
                                HTTP_X_PAYSTACK_SIGNATURE=sig)

    def test_webhook_dispatches_topup_before_booking_lookup(self):
        ref = 'TOPUP-9-' + 'f' * 16
        with mock.patch('requests.post') as post, \
                mock.patch('wallets.alerts.send'), \
                mock.patch('bookings.views._alert_payment_problem') as alert, \
                mock.patch('bookings.views.confirm_booking_payment') as confirm:
            resp = self.post({'event': 'charge.success', 'data': {
                'reference': ref, 'amount': 5000, 'currency': 'KES'}})
        self.assertEqual(resp.status_code, 200)
        confirm.assert_not_called()
        alert.assert_not_called()
        post.assert_not_called()
        self.assertFalse(UnappliedPayment.objects.exists())

    def test_topup_charge_credits_wallet_through_webhook(self):
        user = self.passenger()
        WalletTopUp.objects.create(user=user, amount=Decimal('50'),
                                   reference='TOPUP-1-abc')
        resp = self.post({'event': 'charge.success', 'data': {
            'reference': 'TOPUP-1-abc', 'amount': 5000, 'currency': 'KES',
            'status': 'success', 'metadata': {'user_id': user.id}}})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.balance(user), Decimal('50.00'))
        self.assertEqual(self.post({'event': 'charge.success', 'data': {
            'reference': 'TOPUP-1-abc', 'amount': 5000, 'currency': 'KES',
            'status': 'success', 'metadata': {'user_id': user.id}}}).status_code, 200)
        self.assertEqual(self.balance(user), Decimal('50.00'))

    def test_topup_handler_error_makes_paystack_retry(self):
        with mock.patch('wallets.webhook.handle_event', side_effect=RuntimeError('db')):
            resp = self.post({'event': 'charge.success', 'data': {
                'reference': 'TOPUP-1-abc', 'amount': 5000, 'currency': 'KES'}})
        self.assertEqual(resp.status_code, 500)

    def test_non_topup_events_still_reach_booking_code(self):
        with mock.patch('bookings.views.confirm_booking_payment') as confirm:
            confirm.return_value = mock.Mock(result='not_found')
            self.post({'event': 'charge.success', 'data': {
                'reference': 'CONNECT-1-' + 'a' * 32, 'amount': 5000,
                'currency': 'KES'}})
        confirm.assert_called_once()


class NoDirectWalletWritesTests(TestCase):
    def test_bookings_code_never_writes_balances_directly(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        for path in (root / 'services.py', root / 'views.py'):
            text = path.read_text()
            self.assertIsNone(
                re.search(r'available_balance\s*(=[^=]|\+=|-=)', text), path.name)
            self.assertNotIn("update_fields=['available_balance'", text, path.name)
            self.assertNotIn('WalletTransaction.objects.create', text, path.name)


# ----------------------------- Postgres only -----------------------------

@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class WalletLockOrderTests(WalletBase, TransactionTestCase):
    def setUp(self):
        self.build()

    def test_wallet_pay_lock_order(self):
        user = self.passenger(500)
        booking = self.pending(user)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.pay(user, booking)
        self.assertEqual(resp.status_code, 200, resp.content)
        tables = _locks(ctx.captured_queries)
        order = [tables.index(t) for t in (
            'companies_trip', 'bookings_booking', 'bookings_payment',
            'wallets_wallet')]
        self.assertEqual(order, sorted(order), tables)
        # BookingHold is created (inserted) before the Wallet lock.
        inserts = [i for i, q in enumerate(ctx.captured_queries)
                   if q['sql'].startswith('INSERT INTO "bookings_bookinghold"')]
        wallet_lock = next(
            i for i, q in enumerate(ctx.captured_queries)
            if 'FOR UPDATE' in q['sql'] and 'FROM "wallets_wallet"' in q['sql'])
        self.assertTrue(inserts and inserts[0] < wallet_lock)

    def test_wallet_refund_lock_order(self):
        user = self.passenger(500)
        booking = self.wallet_paid(user)
        with CaptureQueriesContext(connection) as ctx:
            settle_booking_fault(Booking.objects.get(pk=booking.pk), 'passenger')
        tables = _locks(ctx.captured_queries)
        self.assertEqual(tables[0], 'bookings_booking')
        first = {t: tables.index(t) for t in set(tables)}
        self.assertLess(first['bookings_booking'], first['bookings_payment'])
        self.assertLess(first['bookings_payment'], first['bookings_bookinghold'])
        self.assertLess(first['bookings_bookinghold'], first['wallets_wallet'])


@unittest.skipUnless(connection.vendor == 'postgresql', 'needs real row locks')
class WalletRacesTests(WalletBase, TransactionTestCase):
    def setUp(self):
        self.build()

    def run_together(self, *targets):
        barrier = threading.Barrier(len(targets))
        out, lock = [], threading.Lock()

        def run(fn):
            barrier.wait()
            try:
                result = fn()
            except Exception as exc:
                result = repr(exc)
            finally:
                connection.close()
            with lock:
                out.append(result)

        threads = [threading.Thread(target=run, args=(t,)) for t in targets]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return out

    def test_wallet_refund_via_sweep_vs_cancel_no_deadlock(self):
        for _ in range(50):
            user = self.passenger(500)
            booking = self.wallet_paid(user)
            client = self.client_for(user)

            def sweep():
                settle_booking_fault(Booking.objects.get(pk=booking.pk), 'passenger')
                return 'sweep'

            def cancel():
                return client.post(f'/api/bookings/{booking.id}/cancel/').status_code

            results = self.run_together(sweep, cancel)
            self.assertEqual(sorted(map(str, results)), ['200', 'sweep'], results)
            payment = Payment.objects.get(booking=booking)
            self.assertEqual(
                WalletTransaction.objects.filter(reference=f'refund:{payment.pk}').count(), 1)
            self.assertEqual(self.balance(user), Decimal('450.00'))

    def test_wallet_pay_double_submit_one_debit(self):
        user = self.passenger(500)
        booking = self.pending(user)
        results = self.run_together(*[
            (lambda: self.pay(user, booking).status_code)] * 8)
        self.assertEqual(results, [200] * 8)
        self.assertEqual(WalletTransaction.objects.filter(type='spend').count(), 1)
        self.assertEqual(self.balance(user), Decimal('400.00'))

    def test_wallet_pay_vs_expiry_sweep(self):
        for _ in range(15):
            user = self.passenger(500)
            booking = self.pending(user, held_for=-1)
            Booking.objects.filter(pk=booking.pk).update(
                held_until=timezone.now() + dt.timedelta(milliseconds=1))

            def expire():
                call_command('expire_pending_bookings', stdout=StringIO())
                return 'expire'

            results = self.run_together(
                lambda: self.pay(user, booking).status_code, expire)
            booking.refresh_from_db()
            spent = WalletTransaction.objects.filter(
                reference=f'spend:{booking.id}').exists()
            # Never both: debited and cancelled, or confirmed and not debited.
            self.assertEqual(spent, booking.status == 'confirmed', (results, booking.status))
            self.assertEqual(self.balance(user), Decimal('400.00') if spent else Decimal('500.00'))
