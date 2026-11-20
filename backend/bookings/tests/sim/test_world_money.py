"""World simulation, part 2: payments, refunds, faults, replays, sweeps and settlement.

The gateway is the fake in fake_gateway.py: it encodes this code's own
assumptions about Paystack, so these tests prove consistency, not compatibility.
"""
import json
import unittest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from bookings import services
from bookings.models import Booking, BookingHold, Payment, Payout, UnappliedPayment
from companies.models import Route, Trip
from wallets.models import Wallet

from . import fake_gateway as fg
from .base import POSTGRES, SimCase

User = get_user_model()
HEX = '0123456789abcdef' * 2


def old_checkout_reference(booking):
    """A reference shaped like ours that no Payment row holds (an abandoned checkout)."""
    return f'CONNECT-{booking.pk}-{HEX}'


class MoneyCase(SimCase):
    def setUp(self):
        super().setUp()
        self.company, self.route = self.ready_route(0, 0, index=1)
        self.trip_ = self.trip(self.route, minutes=90)
        self.fare = self.route.price

    def pending(self, seats=1, user=None, trip=None):
        user = user or self.user()
        return user, self.booking(user, trip or self.trip_, seats)

    def paid(self, seats=1, trip=None):
        user = self.user()
        booking, reference = self.confirmed_booking(user, trip or self.trip_, seats)
        return user, booking, reference

    def refunds_of(self, reference, kind=None):
        return [r for r in self.fake.accepted_refunds(reference) if kind in (None, r['kind'])]


class LatePaymentTests(MoneyCase):
    def test_payment_after_the_hold_and_tolerance_is_refunded_in_full_exactly_once(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.expire_hold(booking, seconds_ago=120)           # past the 60 s tolerance
        event = self.fake.customer_pays(reference, booking.total_amount)
        for _ in range(5):                                   # Paystack redelivers
            self.assertEqual(self.webhook(event).status_code, 200)
        booking.refresh_from_db()
        payment = self.payment(booking)
        self.assertEqual(booking.status, 'cancelled')
        self.assertEqual(payment.refund_reason, 'late_payment')
        self.assertEqual([r['amount'] for r in self.refunds_of(reference)], [int(self.fare * 100)])
        self.run_command('process_noshows')
        self.assertEqual(len(self.refunds_of(reference)), 1, 'the sweep refunded a late payment twice')
        paid, refunded = services.charge_refund_totals(payment)
        self.assertEqual(paid, refunded)

    def test_payment_inside_the_tolerance_with_the_seat_still_free_confirms(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.expire_hold(booking, seconds_ago=30)
        self.webhook(self.fake.customer_pays(reference, booking.total_amount))
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual(self.fake.accepted_refunds(), [])

    def test_hold_expired_seat_resold_loser_refunded_once_winner_keeps_the_seat(self):
        trip = self.trip(self.route, minutes=90, capacity=2)
        a, first = self.pending(2, trip=trip)
        reference = self.init_digital(a, first, mpesa=True)
        self.expire_hold(first, seconds_ago=30)               # within tolerance
        b, second = self.pending(2, trip=trip)                # B takes the seats
        self.webhook(self.fake.customer_pays(reference, first.total_amount))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, 'cancelled')
        self.assertEqual(second.status, 'pending')
        self.assertEqual(self.fake.refunded_subunits(reference), int(first.total_amount * 100))
        ref_b = self.init_digital(b, second, mpesa=True)
        self.webhook(self.fake.customer_pays(ref_b, second.total_amount))
        second.refresh_from_db()
        self.assertEqual(second.status, 'confirmed')
        self.assertEqual(services.seats_taken(trip), 2)

    def test_payment_on_a_booking_the_passenger_cancelled_is_refunded_in_full(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.cancel(user, booking)
        self.webhook(self.fake.customer_pays(reference, booking.total_amount))
        self.assertEqual(self.fake.refunded_subunits(reference), int(self.fare * 100))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')

    def test_late_payment_refund_that_never_reached_the_gateway_is_sent_by_the_sweep(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.expire_hold(booking, seconds_ago=120)
        self.fake.fault('refund', fg.HTTP_400, times=1, message='sim: refused')
        self.webhook(self.fake.customer_pays(reference, booking.total_amount))
        self.assertEqual(self.fake.accepted_refunds(), [], 'refused: nothing refunded yet')
        self.assertEqual(self.payment(booking).refund_status, 'not_requested')
        self.run_command('process_noshows')
        self.assertEqual(self.fake.refunded_subunits(reference), int(self.fare * 100))


class WrongAmountTests(MoneyCase):
    def test_overpayment_confirms_and_refunds_the_difference_once(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        event = self.fake.customer_pays(reference, self.fare + 50)
        for _ in range(4):
            self.webhook(event)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'confirmed')
        self.assertEqual([(r['kind'], r['amount']) for r in self.fake.accepted_refunds(reference)],
                         [('unapplied', 5000)])
        # Later the passenger cancels: 50% of the FARE, never of what was paid.
        self.cancel(user, booking)
        by_kind = {r['kind']: r['amount'] for r in self.fake.accepted_refunds(reference)}
        self.assertEqual(by_kind, {'unapplied': 5000, 'booking': int(self.fare * 50)})
        paid, refunded = services.charge_refund_totals(self.payment(booking))
        self.assertEqual((paid, refunded), (self.fare + 50, self.fare / 2 + 50))

    def test_overpayment_below_the_refund_minimum_goes_to_review_with_no_refund(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.webhook(self.fake.customer_pays(reference, self.fare + 3))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(self.fake.accepted_refunds(), [])
        row = UnappliedPayment.objects.get(reference=reference)
        self.assertEqual((row.status, row.amount), ('review', Decimal('3.00')))
        self.assertTrue(self.alerts('overpaid by KES 3'))

    def test_overpaid_and_late_refunds_exactly_what_was_paid(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        self.expire_hold(booking, seconds_ago=120)
        self.webhook(self.fake.customer_pays(reference, self.fare + 50))
        self.assertEqual(self.fake.refunded_subunits(reference), int((self.fare + 50) * 100))
        self.run_command('process_noshows')
        self.run_command('process_unapplied')
        self.assertEqual(self.fake.refunded_subunits(reference), int((self.fare + 50) * 100))

    def test_underpayment_is_never_confirmed_and_waits_for_a_human(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        event = self.fake.customer_pays(reference, self.fare - 10)
        self.webhook(event)
        self.webhook(event)
        booking.refresh_from_db()
        payment = self.payment(booking)
        self.assertEqual((booking.status, payment.status), ('pending', 'failed'))
        row = UnappliedPayment.objects.get(reference=reference)
        self.assertEqual((row.status, row.amount), ('review', self.fare - 10))
        self.assertEqual(self.fake.accepted_refunds(), [])
        self.assertEqual(len(self.alerts('mismatch')), 1, 'one alert, not one per redelivery')
        # The passenger pays properly on a fresh checkout; the short payment stays for the admin.
        again = self.init_digital(user, booking, mpesa=True)
        self.assertNotEqual(again, reference)
        self.webhook(self.fake.customer_pays(again, booking.total_amount))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(UnappliedPayment.objects.get(reference=reference).status, 'review')

    def test_wrong_currency_and_unreadable_amount_are_reviewed_not_confirmed(self):
        for currency, amount in (('USD', None), ('KES', 'abc')):
            user, booking = self.pending()
            reference = self.init_digital(user, booking, mpesa=True)
            event = self.fake.customer_pays(reference, booking.total_amount, currency=currency)
            if amount is not None:
                event['data']['amount'] = amount
            self.webhook(event)
            self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'pending', (currency, amount))
            self.assertEqual(UnappliedPayment.objects.get(reference=reference).status, 'review')
            self.assertEqual(self.fake.accepted_refunds(), [])

    def test_a_tampered_amount_is_rejected_before_any_row_or_gateway_call(self):
        user = self.user()
        self.book(user, self.trip_, 1, expect=400, total_amount='1')
        self.assertFalse(Booking.objects.filter(user=user).exists())
        booking = self.booking(user, self.trip_)
        for name in ('bookings:initialize-paystack-payment', 'bookings:initialize-mpesa-payment',
                     'bookings:pay-from-wallet'):
            for field in ('amount', 'total_amount'):
                r = self.api(user).post(reverse(name, args=[booking.pk]), {field: '1'}, format='json')
                self.assertEqual(r.status_code, 400, (name, field, r.content))
        self.assertFalse(Payment.objects.filter(booking=booking).exists())
        self.assertEqual(self.fake.calls, [])


class DuplicateAndUnmatchedChargeTests(MoneyCase):
    def test_redelivered_charge_confirms_once_even_from_many_threads(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        event = self.fake.customer_pays(reference, booking.total_amount)
        for _ in range(5):
            self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual(BookingHold.objects.filter(booking=booking).count(), 1)
        self.assertEqual(self.fake.accepted_refunds(), [])
        if POSTGRES:
            user2, booking2 = self.pending()
            ref2 = self.init_digital(user2, booking2, mpesa=True)
            event2 = self.fake.customer_pays(ref2, booking2.total_amount)
            results, errors = self.run_threads([lambda: self.webhook(event2).status_code] * 8)
            self.assertEqual((errors, set(results)), ([], {200}))
            self.assertEqual(BookingHold.objects.filter(booking=booking2).count(), 1)
            self.assertEqual(Booking.objects.get(pk=booking2.pk).status, 'confirmed')
            self.assertEqual(self.fake.accepted_refunds(), [])

    def test_a_second_charge_for_an_abandoned_checkout_is_refunded_in_full_once(self):
        user, booking, reference = self.paid()
        stale = old_checkout_reference(booking)
        event = self.fake.customer_pays(stale, self.fare)
        for _ in range(3):
            self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual([r['amount'] for r in self.refunds_of(stale)], [int(self.fare * 100)])
        self.assertEqual(UnappliedPayment.objects.get(reference=stale).status, 'refunded')
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(self.refunds_of(reference), [])

    def test_unmatched_charges_that_cannot_be_refunded_automatically_alert_a_human(self):
        user, booking, _ = self.paid()
        small = old_checkout_reference(Booking(pk=booking.pk + 1000))
        self.webhook(self.fake.customer_pays(small, 4))
        self.assertEqual(UnappliedPayment.objects.get(reference=small).status, 'review')
        usd = f'CONNECT-{booking.pk}-{"a" * 32}'
        self.webhook(self.fake.customer_pays(usd, self.fare, currency='USD'))
        self.assertEqual(UnappliedPayment.objects.get(reference=usd).status, 'review')
        stranger = 'SOMEONE-ELSE-123'
        self.webhook(self.fake.customer_pays(stranger, self.fare))
        self.assertFalse(UnappliedPayment.objects.filter(reference=stranger).exists())
        self.assertTrue(self.alerts('unknown reference'))
        self.assertEqual(self.fake.accepted_refunds(), [])

    def test_unmatched_refund_gateway_faults_never_double_refund(self):
        user, booking, _ = self.paid()
        # Timeout after the gateway accepted: row stays refunding; the reconcile finds the refund.
        a = f'CONNECT-{booking.pk}-{"b" * 32}'
        self.fake.fault('refund', fg.TIMEOUT_AFTER_ACCEPT)
        self.webhook(self.fake.customer_pays(a, self.fare))
        self.assertEqual(UnappliedPayment.objects.get(reference=a).status, 'refunding')
        self.run_command('process_unapplied', '--min-age-minutes', '0')
        self.assertEqual(UnappliedPayment.objects.get(reference=a).status, 'refunded')
        self.assertEqual(len(self.refunds_of(a)), 1)
        # Timeout before the gateway accepted: reconcile finds nothing and asks a human; it never resends.
        b = f'CONNECT-{booking.pk}-{"c" * 32}'
        self.fake.fault('refund', fg.TIMEOUT)
        self.webhook(self.fake.customer_pays(b, self.fare))
        self.run_command('process_unapplied', '--min-age-minutes', '0')
        self.assertEqual(UnappliedPayment.objects.get(reference=b).status, 'review')
        self.assertEqual(self.refunds_of(b), [])
        # A definite refusal goes straight to review.
        c = f'CONNECT-{booking.pk}-{"d" * 32}'
        self.fake.fault('refund', fg.HTTP_400, message='sim: not allowed')
        self.webhook(self.fake.customer_pays(c, self.fare))
        self.assertEqual(UnappliedPayment.objects.get(reference=c).status, 'review')
        self.assertTrue(self.alerts('Refund manually'))

    def test_a_digital_charge_on_a_booking_paid_from_the_wallet_is_refunded_to_the_payer(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)       # checkout opened ...
        from wallets import services as ws
        from django.db import transaction
        with transaction.atomic():
            ws.credit(user, Decimal('500'), 'deposit', f'topup:sim-{user.pk}')
        r = self.api(user).post(reverse('bookings:pay-from-wallet', args=[booking.pk]), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)                 # ... but the wallet pays first
        self.webhook(self.fake.customer_pays(reference, booking.total_amount))   # then the old checkout is paid
        self.assertEqual(self.fake.refunded_subunits(reference), int(self.fare * 100))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed')
        self.assertEqual(Wallet.objects.get(user=user).available_balance, Decimal('500') - self.fare)


class CancellationRuleTests(MoneyCase):
    def test_passenger_fault_refunds_half_and_company_fault_refunds_all(self):
        user, booking, ref = self.paid()
        body = self.cancel(user, booking)
        self.assertEqual((body['fault_party'], body['refund_amount']), ('passenger', str(self.fare / 2)))
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')
        self.assertEqual(services.seats_taken(self.trip_), 0)
        self.cancel(user, booking, expect=400)

        user2, booking2, ref2 = self.paid()
        self.cancel(user2, booking2, fault='company', expect=403)        # a passenger cannot blame the company
        body = self.cancel(self.staff(self.company, 'company_operator'), booking2, fault='company')
        self.assertEqual(body['refund_amount'], str(self.fare))
        self.assertEqual(self.fake.refunded_subunits(ref2), int(self.fare * 100))

    def test_half_up_rounding_and_the_five_shilling_floor(self):
        Route.objects.filter(pk=self.route.pk).update(price=Decimal('55.55'))
        user, booking, ref = self.paid()
        self.assertEqual(self.cancel(user, booking)['refund_amount'], '27.78')
        self.assertEqual(self.fake.refunded_subunits(ref), 2778)
        Route.objects.filter(pk=self.route.pk).update(price=Decimal('8.00'))
        user, booking, ref = self.paid()
        self.assertEqual(self.cancel(user, booking)['refund_amount'], '4.00')
        self.assertEqual(self.fake.refunded_subunits(ref), 0, 'Paystack refuses under KES 5: no request must be sent')
        self.assertEqual(self.payment(booking).refund_status, 'not_requested')

    def test_cancelling_an_unpaid_booking_refunds_nothing_and_frees_the_seat(self):
        user, booking = self.pending(3)
        self.cancel(user, booking)
        self.assertEqual(services.seats_taken(self.trip_), 0)
        self.assertEqual(self.fake.calls, [])

    def test_passenger_cannot_cancel_once_boarding_starts_but_the_company_can(self):
        user, booking, ref = self.paid()
        Trip.objects.filter(pk=self.trip_.pk).update(status='boarding')
        self.cancel(user, booking, expect=409)
        self.cancel(self.staff(self.company, 'company_manager'), booking, fault='company')
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 100))

    def test_cash_booking_cancellation_records_the_amount_and_calls_no_gateway(self):
        user = self.user()
        booking = self.booking(user, self.trip_)
        r = self.api(user).post(reverse('bookings:initialize-cash-payment', args=[booking.pk]), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.api(self.staff(self.company, 'company_manager')).post(
            reverse('bookings:confirm-cash-payment', args=[booking.pk]), {}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.cancel(user, booking)
        payment = self.payment(booking)
        self.assertEqual((payment.method, payment.refund_amount), ('cash', self.fare / 2))
        self.assertEqual(self.fake.calls, [])

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_eight_simultaneous_cancels_make_one_refund(self):
        user, booking, ref = self.paid()
        manager = self.staff(self.company, 'company_manager')
        url = reverse('bookings:cancel-booking', args=[booking.pk])
        jobs = [lambda: self.api(user).post(url, {}, format='json').status_code] * 4
        jobs += [lambda: self.api(manager).post(url, {'fault_party': 'company'}, format='json').status_code] * 4
        codes, errors = self.run_threads(jobs)
        self.assertEqual(errors, [])
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(len(self.refunds_of(ref)), 1)


class RefundFaultTests(MoneyCase):
    def test_timeout_leaves_the_refund_processing_and_only_a_forced_resend_sends_it(self):
        user, booking, ref = self.paid()
        self.fake.fault('refund', fg.TIMEOUT)
        body = self.cancel(user, booking)
        self.assertEqual(body['refund_status'], 'processing')
        self.assertTrue(self.alerts('unconfirmed'))
        payment = self.payment(booking)
        self.assertEqual(payment.refund_status, 'processing')
        self.cancel(user, booking, expect=400)                         # no second attempt through the API
        self.run_command('process_noshows')
        self.assertEqual(len(self.fake.calls_to('refund')), 1)         # nor through the sweep
        out = self.run_command('reconcile_refunds', '--min-age-minutes', '0')
        self.assertIn('NO refund exists at Paystack', out)
        self.assertEqual(len(self.fake.calls_to('refund')), 1, 'reconcile without --resend must not resend')
        self.run_command('reconcile_refunds', '--min-age-minutes', '0', '--resend')
        self.assertEqual(len(self.refunds_of(ref)), 1)
        self.assertEqual(self.payment(booking).refund_status, 'pending')

    def test_timeout_after_the_gateway_accepted_is_recorded_not_resent(self):
        user, booking, ref = self.paid()
        self.fake.fault('refund', fg.TIMEOUT_AFTER_ACCEPT)
        self.cancel(user, booking)
        self.assertEqual(self.payment(booking).refund_status, 'processing')
        self.run_command('reconcile_refunds', '--min-age-minutes', '0', '--resend')
        self.assertEqual(len(self.refunds_of(ref)), 1, 'a refund that already exists was sent again')
        self.assertEqual(self.payment(booking).refund_status, 'pending')

    def test_500_and_unreadable_answers_are_uncertain_never_refused(self):
        for kind in (fg.HTTP_500, fg.UNREADABLE):
            user, booking, ref = self.paid()
            self.fake.fault('refund', kind)
            self.assertEqual(self.cancel(user, booking)['refund_status'], 'processing', kind)

    def test_a_refusal_restores_the_booking_and_a_retry_works(self):
        user, booking, ref = self.paid()
        self.fake.fault('refund', fg.HTTP_400, message='sim: refused')
        self.cancel(user, booking, expect=409)
        booking.refresh_from_db()
        payment = self.payment(booking)
        self.assertEqual((booking.status, payment.refund_status, payment.refund_amount), ('confirmed', 'not_requested', None))
        self.assertEqual(self.fake.accepted_refunds(), [])
        self.cancel(user, booking)
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))

    def test_a_failed_refund_event_alerts_and_the_money_is_not_marked_refunded(self):
        user, booking, ref = self.paid()
        self.cancel(self.staff(self.company, 'company_manager'), booking, fault='company')
        refund = self.fake.accepted_refunds(ref)[0]
        self.webhook(fg.refund_event('failed', ref, refund['id'], self.fare))
        payment = self.payment(booking)
        self.assertEqual(payment.refund_status, 'failed')
        self.assertEqual(payment.status, 'confirmed')
        self.assertTrue(self.alerts('Refund FAILED'))

    def test_refund_events_out_of_order_never_downgrade_a_processed_refund(self):
        user, booking, ref = self.paid()
        self.cancel(self.staff(self.company, 'company_manager'), booking, fault='company')
        refund = self.fake.accepted_refunds(ref)[0]
        for name in ('processed', 'pending', 'processing', 'processed', 'pending'):
            self.assertEqual(self.webhook(fg.refund_event(name, ref, refund['id'], self.fare)).status_code, 200)
        payment = self.payment(booking)
        self.assertEqual((payment.refund_status, payment.status), ('processed', 'refunded'))
        self.assertEqual(BookingHold.objects.get(booking=booking).status, 'refunded')
        # A charge.success redelivered after a full refund never revives the payment.
        self.webhook(self.fake.customer_pays(ref, self.fare))
        self.assertEqual(self.payment(booking).status, 'refunded')
        self.assertEqual(len(self.refunds_of(ref)), 1)


class WebhookHandlingTests(MoneyCase):
    def test_bad_signatures_and_bad_bodies_are_refused_and_change_nothing(self):
        user, booking = self.pending()
        reference = self.init_digital(user, booking, mpesa=True)
        event = self.fake.customer_pays(reference, booking.total_amount)
        self.assertEqual(self.webhook(event, signature=None).status_code, 400)
        self.assertEqual(self.webhook(event, signature='0' * 128).status_code, 400)
        body = json.dumps(event).encode()
        tampered = body.replace(b'"success"', b'"succes5"')
        self.assertEqual(self.webhook(event, signature=fg.sign(body), body=tampered).status_code, 400)
        garbage = b'{not json'
        self.assertEqual(self.webhook(None, signature=fg.sign(garbage), body=garbage).status_code, 400)
        no_ref = {'event': 'charge.success', 'data': {'amount': 100}}
        self.assertEqual(self.webhook(no_ref).status_code, 400)
        self.assertEqual(self.webhook({'event': 'customeridentification.success', 'data': {}}).status_code, 200)
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'pending')
        self.assertEqual(self.payment(booking).status, 'pending')

    def test_the_refund_endpoint_alone_also_checks_signatures(self):
        user, booking, ref = self.paid()
        event = fg.refund_event('processed', ref, 1, self.fare)
        r = fg.post_event(__import__('django').test.Client(), event, signature='bad',
                          path=reverse('bookings:paystack-refund-webhook'))
        self.assertEqual(r.status_code, 400)


class SettlementTests(MoneyCase):
    def _board(self, booking, who):
        r = self.api(who).post(reverse('bookings:verify-boarding', args=[booking.pk]),
                               {'boarding_pin': booking.verification_pin}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_each_company_is_paid_once_and_only_for_money_it_kept(self):
        company, route, trip = self.company, self.route, self.trip_
        operator = self.staff(company, 'company_operator')
        boarded = [self.paid()[1] for _ in range(2)]
        Trip.objects.filter(pk=trip.pk).update(status='boarding')
        for booking in boarded:
            self._board(booking, operator)
        # A passenger cancelled at 50% and the refund was confirmed: the company keeps the other half.
        trip2 = self.trip(route, minutes=300)
        user, half, ref = self.paid(trip=trip2)
        self.cancel(user, half)
        refund = self.fake.accepted_refunds(ref)[0]
        self.webhook(fg.refund_event('processed', ref, refund['id'], self.fare / 2))
        # A fully refunded booking (company fault) is never paid out.
        user, full, ref_full = self.paid(trip=trip2)
        self.cancel(self.staff(company, 'company_manager'), full, fault='company')
        refund = self.fake.accepted_refunds(ref_full)[0]
        self.webhook(fg.refund_event('processed', ref_full, refund['id'], self.fare))
        # Another company has its own completed booking.
        other_co, other_route = self.ready_route(1, 0, index=2)
        other_trip = self.trip(other_route, minutes=40)
        _, other_booking, _ = self.paid(trip=other_trip)
        Trip.objects.filter(pk=other_trip.pk).update(status='boarding')
        self._board(other_booking, self.staff(other_co, 'company_operator'))

        report = self.run_command('settle_company', str(company.pk))
        fee = Decimal('30.00')
        gross = 2 * route.price + route.price / 2
        expected_fee = 2 * fee + fee
        self.assertIn(f'NET TO PAY {gross - expected_fee}', report)
        self.run_command('settle_company', str(company.pk), '--apply', '--reference', 'PAY-1')
        payout = Payout.objects.get(reference='PAY-1')
        self.assertEqual((payout.gross_amount, payout.fee_amount, payout.net_amount),
                         (gross, expected_fee, gross - expected_fee))
        self.assertEqual(payout.payments_count, 3)
        again = self.run_command('settle_company', str(company.pk), '--apply', '--reference', 'PAY-2')
        self.assertIn('Nothing to pay out', again)
        self.assertEqual(Payout.objects.filter(company=company).count(), 1)
        self.assertFalse(Payment.objects.filter(booking=full, payout__isnull=False).exists())
        # The other company's money is untouched by this payout and is paid on its own.
        self.assertFalse(Payment.objects.filter(booking=other_booking, payout__isnull=False).exists())
        self.run_command('settle_company', str(other_co.pk), '--apply', '--reference', 'PAY-3')
        self.assertEqual(Payout.objects.get(reference='PAY-3').gross_amount, other_route.price)

    @unittest.skipUnless(POSTGRES, 'needs real row locks')
    def test_two_settlement_runs_at_once_pay_the_company_once(self):
        operator = self.staff(self.company, 'company_operator')
        bookings = [self.paid()[1] for _ in range(4)]
        Trip.objects.filter(pk=self.trip_.pk).update(status='boarding')
        for booking in bookings:
            self._board(booking, operator)

        def run(reference):
            def go():
                try:
                    return self.run_command('settle_company', str(self.company.pk), '--apply', '--reference', reference)
                except Exception as exc:
                    return f'error: {exc}'
            return go

        out, errors = self.run_threads([run('RACE-1'), run('RACE-2'), run('RACE-3')])
        self.assertEqual(errors, [])
        paid_out = Payout.objects.filter(company=self.company)
        self.assertEqual(sum(p.gross_amount for p in paid_out), 4 * self.fare, out)
        self.assertEqual(Payment.objects.filter(payout__isnull=False).count(), 4)


@unittest.skipUnless(POSTGRES, 'needs real row locks')
class SweepsRaceWebhooksTests(MoneyCase):
    def test_sweeps_running_while_late_and_on_time_webhooks_arrive(self):
        for iteration in range(5):
            trip = self.trip(self.route, minutes=120, capacity=6)
            late, fresh = [], []
            for _ in range(6):
                user, booking = self.pending(1, trip=trip)
                late.append((user, booking, self.init_digital(user, booking, mpesa=True)))
                self.expire_hold(booking, seconds_ago=30)
            for _ in range(6):
                user, booking = self.pending(1, trip=trip)       # the seats were resold
                fresh.append((user, booking, self.init_digital(user, booking, mpesa=True)))
            events = [self.fake.customer_pays(ref, b.total_amount) for _, b, ref in late + fresh]
            jobs = [lambda e=e: self.webhook(e).status_code for e in events]
            jobs += [lambda: self.run_command('expire_pending_bookings'),
                     lambda: self.run_command('process_noshows'),
                     lambda: self.run_command('process_unapplied'),
                     lambda: self.run_command('expire_pending_bookings')]
            results, errors = self.run_threads(jobs)
            self.assertEqual(errors, [], f'iteration {iteration}')
            self.assertEqual(results[:12], [200] * 12)
            self.assertEqual(services.seats_taken(trip), 6)
            for _, booking, ref in fresh:
                self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'confirmed', iteration)
                self.assertEqual(self.fake.accepted_refunds(ref), [])
            for _, booking, ref in late:
                self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')
                self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 100), iteration)
                self.assertEqual(len(self.refunds_of(ref)), 1)
