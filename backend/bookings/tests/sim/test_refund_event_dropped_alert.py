"""A refund event that does not match the stored refund is dropped, and an admin is told once a day.

Sim cases restore the serialized database, so they stay in the sim package.
"""
from django.core.cache import cache

from bookings.tests.sim import test_refund_retry_and_stale_events as base


class DroppedRefundEventTests(base.Case):
    def setUp(self):
        super().setUp()
        cache.clear()

    def stale_event_setup(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        failed_a = self.fail_first_refund(ref, self.fare / 2)
        self.run_command('process_noshows')      # refund B replaces A
        return booking, failed_a

    def test_a_dropped_event_alerts_an_admin_once_per_payment_per_day(self):
        booking, stale = self.stale_event_setup()
        before = len(self.alerts('dropped'))
        for _ in range(3):
            self.assertEqual(self.webhook(stale).status_code, 200)
        self.assertEqual(len(self.alerts('dropped')) - before, 1)
        self.assertEqual(self.payment(booking).refund_status, 'pending')
        cache.clear()                                  # a day later
        self.webhook(stale)
        self.assertEqual(len(self.alerts('dropped')) - before, 2)
        self.assertEqual(self.fake.leaks, [])

    def test_an_event_for_the_stored_refund_raises_no_dropped_alert(self):
        user, booking, ref = self.paid()
        self.make_no_show_trip()
        self.run_command('process_noshows')
        from bookings.tests.sim import fake_gateway as fg
        refund = self.fake.accepted_refunds(ref)[0]
        self.webhook(fg.refund_event('failed', ref, refund['id'], self.fare / 2))
        self.assertEqual(self.alerts('dropped'), [])
