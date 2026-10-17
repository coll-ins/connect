import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from charters.models import CharterRequest
from companies.models import Company
from drivers.models import Driver

User = get_user_model()
BASE = '/api/charters/'
WEBHOOK = '/api/bookings/webhooks/paystack/'
SECRET = 'sk_test_unit'


def resp(payload, code=200):
    m = MagicMock()
    m.status_code = code
    m.json.return_value = payload
    return m


def signed(reference, amount, currency='KES', secret=SECRET):
    body = json.dumps({'event': 'charge.success',
                       'data': {'reference': reference, 'amount': amount, 'currency': currency}}).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class CharterPaymentTests(APITestCase):

    def setUp(self):
        self.co = Company.objects.create(name='A Line', areas_served='X', accepts_charters=True)
        self.pax = User.objects.create_user(username='p', password='x', phone_number='+254700000901')
        self.other = User.objects.create_user(username='o', password='x', phone_number='+254700000902')
        self.driver = Driver.objects.create(
            company=self.co, name='D', phone_number='+254712000041', bus_number='KA 1')
        self.charter = self.make()
        self.ref = f'CHT-{self.charter.id}-ABCDEFGHJK'

    def make(self, **over):
        fields = dict(
            passenger=self.pax, company=self.co, driver=self.driver, purpose='School trip',
            pickup_location='Karen', destination='Nakuru',
            depart_at=timezone.now() + timedelta(days=3), passenger_count=40,
            contact_name='T', contact_phone='+254712345678', status='quoted',
            quote_price=Decimal('20000.00'),
            quote_valid_until=timezone.now() + timedelta(hours=48))
        fields.update(over)
        return CharterRequest.objects.create(**fields)

    def status(self):
        return CharterRequest.objects.get(id=self.charter.id).status

    def hook(self, amount=2000000, currency='KES'):
        body, sig = signed(self.ref, amount, currency)
        return self.client.post(WEBHOOK, data=body, content_type='application/json',
                                HTTP_X_PAYSTACK_SIGNATURE=sig)

    @patch('connect.paystack_extra.requests.post')
    def test_pay_uses_quote_price(self, post):
        post.return_value = resp({'status': True, 'data': {'authorization_url': 'https://pay.test/x'}})
        self.client.force_authenticate(self.pax)
        r = self.client.post(f'{BASE}{self.charter.id}/pay/', {'amount': 1}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(post.call_args.kwargs['json']['amount'], 2000000)
        self.assertTrue(r.data['reference'].startswith(f'CHT-{self.charter.id}-'))

    @patch('connect.paystack_extra.requests.post')
    def test_pay_blocked_cases(self, post):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'{BASE}{self.charter.id}/pay/').status_code, 404)
        self.client.force_authenticate(self.pax)
        CharterRequest.objects.filter(id=self.charter.id).update(
            quote_valid_until=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(f'{BASE}{self.charter.id}/pay/').status_code, 409)
        post.assert_not_called()

    @patch('connect.paystack_extra.requests.post')
    def test_pay_blocked_when_driver_already_booked(self, post):
        self.make(passenger=self.other, status='confirmed')
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.post(f'{BASE}{self.charter.id}/pay/').status_code, 409)
        post.assert_not_called()

    @patch('connect.paystack_extra.requests.get')
    def test_verify_confirms(self, get):
        CharterRequest.objects.filter(id=self.charter.id).update(provider_reference=self.ref)
        get.return_value = resp({'data': {'status': 'success', 'amount': 2000000, 'currency': 'KES'}})
        self.client.force_authenticate(self.pax)
        r = self.client.post(f'{BASE}{self.charter.id}/verify/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'confirmed')

    @patch('connect.paystack_extra.requests.get')
    def test_verify_wrong_amount_does_not_confirm(self, get):
        CharterRequest.objects.filter(id=self.charter.id).update(provider_reference=self.ref)
        get.return_value = resp({'data': {'status': 'success', 'amount': 100, 'currency': 'KES'}})
        self.client.force_authenticate(self.pax)
        self.assertEqual(self.client.post(f'{BASE}{self.charter.id}/verify/').status_code, 409)
        self.assertEqual(self.status(), 'quoted')

    def test_webhook_confirms_and_replay_is_harmless(self):
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'confirmed')
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'confirmed')

    @patch('notifications.sms.send_admin_alert_sms')
    def test_webhook_wrong_amount_alerts_and_does_not_confirm(self, alert):
        self.assertEqual(self.hook(amount=100).status_code, 200)
        self.assertEqual(self.status(), 'quoted')
        self.assertTrue(alert.called)

    @patch('notifications.sms.send_admin_alert_sms')
    def test_payment_after_double_booking_alerts_and_does_not_confirm(self, alert):
        self.make(passenger=self.other, status='confirmed')
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'quoted')
        self.assertTrue(alert.called)
