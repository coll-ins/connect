"""Hosted-checkout init: a definite refusal frees the booking, an uncertain failure does not.

Sim cases restore the serialized database, so they stay in the sim package, which runs before any plain transaction test.
"""
from bookings.tests.sim import fake_gateway as fg
from bookings.tests.sim import test_world_money as money


class CardInitRefusalTests(money.MoneyCase):
    settle_at_end = False

    def test_a_definite_refusal_does_not_block_a_retry(self):
        user, booking = self.pending()
        self.fake.fault('initialize', fg.HTTP_400, message='sim: refused')
        self.init_digital(user, booking, mpesa=False, expect=502)
        self.assertEqual(self.payment(booking).status, 'failed')
        self.init_digital(user, booking, mpesa=False, expect=200)
        self.assertEqual(self.payment(booking).status, 'pending')
        self.assertEqual(self.fake.leaks, [])

    def test_a_server_error_stays_in_progress_because_the_checkout_may_exist(self):
        user, booking = self.pending()
        self.fake.fault('initialize', fg.HTTP_500)
        self.init_digital(user, booking, mpesa=False, expect=502)
        self.assertEqual(self.payment(booking).status, 'pending')
        self.init_digital(user, booking, mpesa=False, expect=409)
        self.assertEqual(self.fake.leaks, [])
