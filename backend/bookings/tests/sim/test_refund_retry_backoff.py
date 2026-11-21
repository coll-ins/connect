"""A refund Paystack keeps refusing is retried on a growing delay, then handed to a human.

Sim cases restore the serialized database, so they stay in the sim package.
"""
import datetime as dt

from django.utils import timezone

from bookings.management.commands.process_noshows import (
    REFUND_RETRY_CAP, refund_retry_delay)
from bookings.models import Payment
from bookings.tests.sim import fake_gateway as fg
from bookings.tests.sim import test_refund_retry_and_stale_events as base


def minutes(n):
    return dt.timedelta(minutes=n)


class RefundDelayTests(base.Case):
    def test_the_delay_grows_then_settles_at_a_day(self):
        got = [refund_retry_delay(n) for n in range(1, 8)]
        self.assertEqual(got, [minutes(10), minutes(30), minutes(120), minutes(360),
                               minutes(1440), minutes(1440), minutes(1440)])


class RefundBackoffTests(base.Case):
    def stranded(self):
        user, booking, ref = self.paid()
        self.cancel(user, booking)
        self.fail_first_refund(ref, self.fare / 2)
        self.fake.fault('refund', fg.HTTP_400, times=None, message='sim: refused')
        return booking, ref

    def refund_calls(self):
        return len(self.fake.calls_to('refund'))

    def due(self, booking):
        # Make the backoff and the claim-release wait over, as if time passed.
        Payment.objects.filter(pk=self.payment(booking).pk).update(
            refund_next_try_at=timezone.now() - minutes(1),
            refund_claimed_at=timezone.now() - minutes(11))

    def test_a_refused_retry_waits_ten_minutes_then_thirty(self):
        booking, ref = self.stranded()
        before = timezone.now()
        self.run_command('process_noshows')
        p = self.payment(booking)
        self.assertEqual(p.refund_attempts, 1)
        self.assertTrue(before + minutes(10) <= p.refund_next_try_at <= timezone.now() + minutes(10))
        calls = self.refund_calls()
        Payment.objects.filter(pk=p.pk).update(refund_claimed_at=timezone.now() - minutes(11))
        self.run_command('process_noshows')
        self.assertEqual(self.refund_calls(), calls, 'retried before the backoff ended')
        self.due(booking)
        before = timezone.now()
        self.run_command('process_noshows')
        p = self.payment(booking)
        self.assertEqual(p.refund_attempts, 2)
        self.assertTrue(before + minutes(30) <= p.refund_next_try_at <= timezone.now() + minutes(30))
        self.assertEqual(self.fake.leaks, [])

    def test_after_the_cap_the_payment_is_flagged_once_and_never_retried(self):
        booking, ref = self.stranded()
        for _ in range(REFUND_RETRY_CAP):
            self.due(booking)
            self.run_command('process_noshows')
        p = self.payment(booking)
        self.assertEqual((p.refund_status, p.refund_attempts), ('review', REFUND_RETRY_CAP))
        self.assertEqual(len(self.alerts('review')), 1)
        calls = self.refund_calls()
        for _ in range(3):
            self.due(booking)
            self.run_command('process_noshows')
        self.assertEqual(self.refund_calls(), calls)
        self.assertEqual(len(self.alerts('review')), 1)
        self.assertEqual(self.fake.accepted_refunds(ref), [])
        self.assertEqual(self.fake.leaks, [])

    def test_a_successful_retry_clears_the_state_and_refunds_once(self):
        booking, ref = self.stranded()
        for _ in range(2):
            self.due(booking)
            self.run_command('process_noshows')
        self.fake._sticky.clear()
        self.due(booking)
        self.run_command('process_noshows')
        p = self.payment(booking)
        self.assertEqual((p.refund_attempts, p.refund_next_try_at), (0, None))
        self.assertEqual(self.fake.refunded_subunits(ref), int(self.fare * 50))
        for _ in range(2):
            self.due(booking)
            self.run_command('process_noshows')
        self.assertEqual(len(self.fake.accepted_refunds(ref)), 1)
        self.assertEqual(self.fake.leaks, [])
