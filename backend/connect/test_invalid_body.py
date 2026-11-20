"""A JSON body that is not an object (list, string, number, null) is a 400, never a 500."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

User = get_user_model()
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
BODIES = ['[1, 2]', '"text"', '5', 'null']


@override_settings(CACHES=LOCMEM, WALLET_TOPUP_ENABLED=True, WALLET_PAYOUTS_ENABLED=True)
class NonObjectBodyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='ib', password='pw-123456', phone_number='+254700000301', role='passenger')
        self.client = APIClient()

    def post(self, url, body):
        return self.client.post(url, data=body, content_type='application/json')

    def assert_invalid_body(self, response):
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_body')

    def test_login_rejects_non_object_bodies(self):
        for body in BODIES:
            with self.subTest(body=body):
                self.assert_invalid_body(self.post(reverse('users:login'), body))

    def test_topup_rejects_non_object_bodies(self):
        self.client.force_authenticate(self.user)
        for body in BODIES:
            with self.subTest(body=body):
                self.assert_invalid_body(self.post(reverse('wallet-topup'), body))

    def test_withdraw_rejects_non_object_bodies(self):
        self.client.force_authenticate(self.user)
        for body in BODIES:
            with self.subTest(body=body):
                self.assert_invalid_body(self.post(reverse('wallet-withdraw'), body))

    def test_a_booking_view_rejects_a_non_object_body(self):
        self.client.force_authenticate(self.user)
        response = self.post(reverse('bookings:initialize-mpesa-payment', args=[1]), '[1]')
        # Booking 1 does not exist; the body is rejected only if the view reads it first.
        self.assertIn(response.status_code, (400, 404))
        self.assertNotEqual(response.status_code, 500)

    def test_objects_and_form_bodies_still_work(self):
        response = self.post(reverse('users:login'), json.dumps({'phone_number': '', 'password': ''}))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('code', response.json())
        response = self.client.post(reverse('users:login'), {'phone_number': '', 'password': ''})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn('code', response.json())
