"""A refund that failed at the gateway is retried once; an event about an older refund never reopens a newer one.

Every test installs the fake gateway through the sim base class, which fails
the test if anything reached a real host or the SMS provider.

Sim cases restore the serialized database, so they stay in the sim package, which runs before any plain transaction test.
"""
import datetime as dt

from django.utils import timezone

from bookings import services
from bookings.models import Booking
from companies.models import Trip

from bookings.tests.sim import fake_gateway as fg
from bookings.tests.sim import test_world_money as money


class Case(money.MoneyCase):
    settle_at_end = False

    def sweeps(self):
        for name in ('process_noshows', 'reconcile_refunds', 'process_unapplied', 'wallet_sweeps'):
            args = ('--min-age-minutes', '0') if name in ('reconcile_refunds', 'process_unapplied') else ()
            self.run_command(name, *args)

    def make_no_show_trip(self, trip=None):
        Trip.objects.filter(pk=(trip or self.trip_).pk).update(
            departure_at=timezone.now() - dt.timedelta(minutes=20))

    def fail_first_refund(self, ref, amount):
        first = self.fake.accepted_refunds(ref)[0]
        event = fg.refund_event('failed', ref, first['id'], amount)
        self.assertEqual(self.webhook(event).status_code, 200)
        self.assertEqual(self.payment_of(ref).refund_status, 'failed')
        self.fake.refunds.remove(first)           # it really failed at the gateway
        return event

    def payment_of(self, ref):
        from bookings.models import Payment
        return Payment.objects.get(provider_reference=ref)


class StaleRefundEventTests(Case):
    def test_a_replayed_failed_event_for_a_superseded_refund_does_not_reopen_the_claim(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        failed_a = self.fail_first_refund(ref, self.fare / 2)
        self.run_command('process_noshows')                  # the sweep sends refund B
        second = self.fake.accepted_refunds(ref)
        self.assertEqual(len(second), 1)
        self.assertEqual(self.payment(booking).refund_reference, str(second[0]['id']))
        self.assertEqual(self.payment(booking).refund_status, 'pending')
        # Paystack delivers the old failure again: it is about refund A, not B.
        self.assertEqual(self.webhook(failed_a).status_code, 200)
        self.assertEqual(self.payment(booking).refund_status, 'pending')
        self.assertEqual(self.payment(booking).refund_reference, str(second[0]['id']))
        self.run_command('process_noshows')
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.assertEqual(self.fake.leaks, [])

    def test_a_stale_event_that_arrives_while_the_retry_is_being_sent_is_ignored(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        failed_a = self.fail_first_refund(ref, self.fare / 2)
        seen = []

        def stale_event_during_the_call(record):
            seen.append((self.webhook(failed_a).status_code, self.payment(booking).refund_status))
        self.fake.hook('refund', stale_event_during_the_call)
        self.run_command('process_noshows')
        self.assertEqual(seen, [(200, 'processing')])
        self.assertEqual(self.payment(booking).refund_status, 'pending')
        self.fake.hook('refund', lambda record: None)
        self.run_command('process_noshows')
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.assertEqual(self.fake.leaks, [])

    def test_a_failed_event_about_the_stored_refund_still_fails_it(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        refund = self.fake.accepted_refunds(ref)[0]
        self.webhook(fg.refund_event('failed', ref, refund['id'], self.fare / 2))
        self.assertEqual(self.payment(booking).refund_status, 'failed')
        self.assertEqual(self.alerts('FAILED') != [], True)
        self.assertEqual(self.fake.leaks, [])


class StrandedRefundTests(Case):
    def test_failed_refund_on_a_passenger_cancelled_booking_is_retried_once_with_the_stored_half(self):
        user, booking, ref = self.paid()
        self.cancel(user, booking)
        self.fail_first_refund(ref, self.fare / 2)
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.leaks, [])

    def test_failed_refund_on_a_staff_cancelled_booking_is_retried_once_in_full(self):
        user, booking, ref = self.paid()
        self.cancel(self.staff(self.company, 'company_manager'), booking, fault='company')
        self.fail_first_refund(ref, self.fare)
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 100))
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.leaks, [])

    def test_a_retry_that_paystack_refuses_is_tried_again_by_a_later_sweep(self):
        user, booking, ref = self.paid()
        self.cancel(user, booking)
        self.fail_first_refund(ref, self.fare / 2)
        self.fake.fault('refund', fg.HTTP_400, message='sim: insufficient balance')
        self.run_command('process_noshows')
        self.assertEqual(self.fake.accepted_refunds(ref), [])
        from bookings.models import Payment
        Payment.objects.filter(pk=self.payment(booking).pk).update(
            refund_claimed_at=timezone.now() - dt.timedelta(minutes=11),
            refund_next_try_at=timezone.now() - dt.timedelta(minutes=1))
        self.run_command('process_noshows')
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.assertEqual(self.fake.leaks, [])

    def test_cancel_refused_then_seat_resold_in_the_gap_still_owes_the_passenger(self):
        Trip.objects.filter(pk=self.trip_.pk).update(capacity=1)
        user, booking, ref = self.paid()
        rival = self.user()
        taken = {}

        def rival_books(record):
            if not taken:
                taken['b'] = self.booking(rival, self.trip_)
        self.fake.hook('refund', rival_books)
        self.fake.fault('refund', fg.HTTP_400, message='sim: insufficient balance')
        self.cancel(user, booking, expect=409)
        self.assertTrue(taken, 'the rival booking never ran')
        trip = Trip.objects.get(pk=self.trip_.pk)
        self.assertLessEqual(services.seats_taken(trip), trip.capacity)       # no oversell
        self.assertEqual(Booking.objects.get(pk=booking.pk).status, 'cancelled')
        self.assertEqual(self.payment(booking).refund_reason, 'seat_lost_passenger')
        self.fake.hook('refund', lambda record: None)
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        self.sweeps()
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.leaks, [])


class RefundResultGuardTests(Case):
    def test_the_sync_refund_answer_never_downgrades_a_refund_a_webhook_already_finished(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        refund = self.fake.accepted_refunds(ref)[0]
        self.webhook(fg.refund_event('processed', ref, refund['id'], self.fare / 2))
        self.assertEqual(self.payment(booking).refund_status, 'processed')
        payment = self.payment(booking)
        claim = services.RefundClaim(
            payment.pk, booking.pk, booking.booking_number, ref, payment.refund_amount)
        services.record_refund_result(claim, 'pending', refund['id'])    # the slow sync answer arrives last
        self.assertEqual(self.payment(booking).refund_status, 'processed')
        self.assertEqual(self.fake.leaks, [])
