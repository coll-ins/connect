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

from companies.models import Company, PickupStage, Route, Trip
from deliveries.models import Parcel
from drivers.models import Driver

User = get_user_model()
BASE = '/api/deliveries/'
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
class ParcelPaymentTests(APITestCase):

    def setUp(self):
        co = Company.objects.create(name='A Line', areas_served='X')
        self.sender = User.objects.create_user(username='s', password='x', phone_number='+254700000801')
        self.other = User.objects.create_user(username='o', password='x', phone_number='+254700000802')
        driver = Driver.objects.create(company=co, name='D', phone_number='+254712000031', bus_number='KA 1')
        route = Route.objects.create(company=co, name='R', price=Decimal('500'),
                                     parcel_price_small=Decimal('150.00'))
        s1 = PickupStage.objects.create(route=route, name='S1', order=1,
                                        latitude=Decimal('-1.2'), longitude=Decimal('36.8'))
        s2 = PickupStage.objects.create(route=route, name='S2', order=2,
                                        latitude=Decimal('-1.3'), longitude=Decimal('36.9'))
        trip = Trip.objects.create(route=route, driver=driver,
                                   departure_at=timezone.now() + timedelta(hours=5), capacity=5)
        self.parcel = Parcel.objects.create(
            sender=self.sender, trip=trip, pickup_stage=s1, dropoff_stage=s2, size='small',
            description='Box', receiver_name='R', receiver_phone='+254712345678',
            price=Decimal('150.00'))
        self.ref = f'PCL-{self.parcel.id}-ABCDEFGHJK'

    def status(self):
        return Parcel.objects.get(id=self.parcel.id).status

    def hook(self, ref=None, amount=15000, currency='KES', secret=SECRET):
        body, sig = signed(ref or self.ref, amount, currency, secret)
        return self.client.post(WEBHOOK, data=body, content_type='application/json',
                                HTTP_X_PAYSTACK_SIGNATURE=sig)

    # ---------- start payment ----------
    @patch('connect.paystack_extra.requests.post')
    def test_pay_uses_server_price_and_own_reference(self, post):
        post.return_value = resp({'status': True, 'data': {'authorization_url': 'https://pay.test/x'}})
        self.client.force_authenticate(self.sender)
        r = self.client.post(f'{BASE}{self.parcel.id}/pay/', {'amount': 1, 'callback_url': 'https://evil'}, format='json')
        self.assertEqual(r.status_code, 200)
        sent = post.call_args.kwargs['json']
        self.assertEqual(sent['amount'], 15000)
        self.assertEqual(sent['currency'], 'KES')
        self.assertNotIn('evil', sent['callback_url'])
        self.assertTrue(r.data['reference'].startswith(f'PCL-{self.parcel.id}-'))
        self.assertEqual(Parcel.objects.get(id=self.parcel.id).provider_reference, r.data['reference'])

    @patch('connect.paystack_extra.requests.post')
    def test_pay_access_rules(self, post):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/pay/').status_code, 404)
        Parcel.objects.filter(id=self.parcel.id).update(status='paid')
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/pay/').status_code, 409)
        post.assert_not_called()

    @patch('connect.paystack_extra.requests.post')
    def test_gateway_failure_is_reported(self, post):
        post.return_value = resp({}, 500)
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/pay/').status_code, 502)
        self.assertEqual(self.status(), 'pending_payment')

    # ---------- verify ----------
    @patch('connect.paystack_extra.requests.get')
    def test_verify_marks_paid(self, get):
        Parcel.objects.filter(id=self.parcel.id).update(provider_reference=self.ref)
        get.return_value = resp({'data': {'status': 'success', 'amount': 15000, 'currency': 'KES'}})
        self.client.force_authenticate(self.sender)
        r = self.client.post(f'{BASE}{self.parcel.id}/verify/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'paid')

    @patch('connect.paystack_extra.requests.get')
    def test_verify_pending_and_wrong_amount_do_not_pay(self, get):
        Parcel.objects.filter(id=self.parcel.id).update(provider_reference=self.ref)
        self.client.force_authenticate(self.sender)
        get.return_value = resp({'data': {'status': 'abandoned'}})
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/verify/').status_code, 202)
        get.return_value = resp({'data': {'status': 'success', 'amount': 100, 'currency': 'KES'}})
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/verify/').status_code, 409)
        self.assertEqual(self.status(), 'pending_payment')

    def test_verify_requires_started_payment_and_owner(self):
        self.client.force_authenticate(self.sender)
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/verify/').status_code, 409)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'{BASE}{self.parcel.id}/verify/').status_code, 404)

    # ---------- webhook ----------
    def test_webhook_marks_paid_and_replay_is_harmless(self):
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'paid')
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'paid')
        self.assertEqual(Parcel.objects.get(id=self.parcel.id).provider_reference, self.ref)

    def test_webhook_bad_signature_rejected(self):
        self.assertEqual(self.hook(secret='wrong-secret').status_code, 400)
        self.assertEqual(self.status(), 'pending_payment')

    @patch('notifications.sms.send_admin_alert_sms')
    def test_webhook_wrong_amount_or_currency_not_paid_and_alerts(self, alert):
        self.assertEqual(self.hook(amount=100).status_code, 200)
        self.assertEqual(self.hook(currency='USD').status_code, 200)
        self.assertEqual(self.status(), 'pending_payment')
        self.assertEqual(alert.call_count, 2)

    @patch('notifications.sms.send_admin_alert_sms')
    def test_payment_for_cancelled_parcel_alerts_admin(self, alert):
        Parcel.objects.filter(id=self.parcel.id).update(status='cancelled')
        self.assertEqual(self.hook().status_code, 200)
        self.assertEqual(self.status(), 'cancelled')
        self.assertTrue(alert.called)
