"""payment_status and verify_paystack_payment call Paystack, so each has its own per-user limit."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=LOCMEM)
class PaymentPollThrottleTests(TestCase):
    def setUp(self):
        cache.clear()  # user pks repeat between tests, and so do the counters keyed on them
        self.user = User.objects.create_user(
            username='pt', password='pw-123456', phone_number='+254700000401', role='passenger')
        self.other = User.objects.create_user(
            username='pt2', password='pw-123456', phone_number='+254700000402', role='passenger')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def hit(self, name, method='get'):
        # No such booking: the view answers without calling Paystack; the throttle runs first.
        return getattr(self.client, method)(reverse(name, args=[999999]))

    def test_status_is_limited_to_30_a_minute_per_user(self):
        for _ in range(30):
            self.assertEqual(self.hit('bookings:payment-status').status_code, 200)
        self.assertEqual(self.hit('bookings:payment-status').status_code, 429)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.hit('bookings:payment-status').status_code, 200)

    def test_verify_is_limited_to_20_a_minute_per_user(self):
        for _ in range(20):
            self.assertEqual(self.hit('bookings:verify-paystack-payment', 'post').status_code, 404)
        self.assertEqual(self.hit('bookings:verify-paystack-payment', 'post').status_code, 429)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.hit('bookings:verify-paystack-payment', 'post').status_code, 404)

    def test_the_two_limits_are_counted_separately(self):
        for _ in range(20):
            self.hit('bookings:verify-paystack-payment', 'post')
        self.assertEqual(self.hit('bookings:payment-status').status_code, 200)
