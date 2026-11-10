import base64
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.departure import auto_depart_on_movement
from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver, LocationPing
from notifications import push
from users.models import PushSubscription

User = get_user_model()

# Stages roughly 1 km apart along a line.
STAGES = [('Kencom', -1.2856, 36.8250), ('KNH', -1.2946, 36.8250),
          ('Adams', -1.3036, 36.8250), ('Junction', -1.3126, 36.8250)]


class WebPushCryptoTests(TestCase):
    def test_rfc8291_appendix_a_vector(self):
        def key(d):
            return ec.derive_private_key(int.from_bytes(push.unb64u(d), 'big'), ec.SECP256R1())

        body = push.encrypt(
            b'When I grow up, I want to be a watermelon',
            'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
            'BTBZMqHH6r4Tts7J_aSIgg',
            _sender_key=key('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'),
            _salt=push.unb64u('DGv6ra1nlYgDCS1FRnbzlw'),
        )
        self.assertEqual(
            push.b64u(body),
            'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6Tl'
            'zAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN',
        )

    def test_vapid_token_verifies_against_public_key(self):
        header = push._vapid_header('https://fcm.googleapis.com/fcm/send/abc')
        token = header.split('t=')[1].split(',')[0]
        signing_input, sig = token.rsplit('.', 1)
        raw = push.unb64u(sig)
        public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), push.unb64u(push.public_key()))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big')),
                      signing_input.encode(), ec.ECDSA(hashes.SHA256()))
        claims = json.loads(base64.urlsafe_b64decode(signing_input.split('.')[1] + '=='))
        self.assertEqual(claims['aud'], 'https://fcm.googleapis.com')


class LiveTripTests(TestCase):
    def setUp(self):
        co = Company.objects.create(name='CityShuttle Test', areas_served='X')
        self.driver = Driver.objects.create(
            company=co, name='D', phone_number='+254712300001', bus_number='KA 1')
        self.route = Route.objects.create(company=co, name='CBD to Junction', price=Decimal('100'))
        self.stages = [
            PickupStage.objects.create(route=self.route, name=n, latitude=la, longitude=lo, order=i)
            for i, (n, la, lo) in enumerate(STAGES, start=1)]
        self.trip = Trip.objects.create(
            route=self.route, driver=self.driver, status='scheduled', capacity=14,
            departure_at=timezone.now() + timedelta(minutes=10))

    def rider(self, stage, phone):
        user = User.objects.create_user(username=phone, password='x', phone_number=phone)
        Booking.objects.create(user=user, route=self.route, trip=self.trip, status='confirmed',
                               pickup_stage=stage, pickup_location=stage.name)
        return user

    def fix(self, at, prev=None):
        prev = prev or at
        with mock.patch('notifications.push.notify_users') as sent, \
                self.captureOnCommitCallbacks(execute=True):
            auto_depart_on_movement(self.driver, prev[0], prev[1], at[0], at[1])
        self.trip.refresh_from_db()
        return sent

    def test_trip_runs_itself_from_gps(self):
        first = self.rider(self.stages[0], '+254712300010')
        far = (-1.20, 36.90)

        self.assertFalse(self.fix(far).called)
        self.assertEqual(self.trip.status, 'scheduled')  # not at the stage yet

        sent = self.fix(STAGES[0][1:])
        self.assertEqual(self.trip.status, 'boarding')
        self.assertEqual(sent.call_args.args[0], [first.id])

        away = (-1.2900, 36.8250)
        sent = self.fix(away, prev=away)
        self.assertEqual(self.trip.status, 'departed')
        self.assertIn('left Kencom', sent.call_args.args[2])

    def test_trip_too_far_ahead_does_not_board(self):
        self.trip.departure_at = timezone.now() + timedelta(hours=2)
        self.trip.save()
        self.fix(STAGES[0][1:])
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, 'scheduled')

    def test_rider_told_once_when_bus_passes_stage_before_theirs(self):
        self.trip.status = 'departed'
        self.trip.save()
        adams = self.rider(self.stages[2], '+254712300011')
        junction = self.rider(self.stages[3], '+254712300012')

        sent = self.fix(STAGES[1][1:])  # at KNH: Adams is next
        self.assertEqual(sent.call_count, 1)
        self.assertEqual(sent.call_args.args[0], [adams.id])
        self.assertIn('Adams, is next', sent.call_args.args[2])

        self.assertFalse(self.fix(STAGES[1][1:]).called)  # no repeat

        sent = self.fix(STAGES[2][1:])  # at Adams: Junction is next
        self.assertEqual([c.args[0] for c in sent.call_args_list], [[junction.id]])


class AutoCompleteTests(LiveTripTests):
    def fix(self, at, prev=None):
        # record_driver_fix keeps each real fix as a ping before the hook runs.
        LocationPing.objects.create(driver=self.driver, latitude=at[0], longitude=at[1],
                                    recorded_at=timezone.now())
        return super().fix(at, prev)

    def test_stale_earlier_trip_does_not_block_the_current_one(self):
        r2 = Route.objects.create(company=self.route.company, name='Other', price=Decimal('100'))
        PickupStage.objects.create(route=r2, name='A', latitude=-1.0, longitude=36.0, order=1)
        PickupStage.objects.create(route=r2, name='B', latitude=-1.1, longitude=36.1, order=2)
        Trip.objects.create(route=r2, driver=self.driver, status='departed', capacity=14,
                            departure_at=timezone.now() - timedelta(hours=5))
        self.trip.status = 'departed'
        self.trip.departure_at = timezone.now() - timedelta(hours=1)
        self.trip.save()
        for stage in STAGES[1:]:
            self.fix(stage[1:])
        self.assertEqual(self.trip.status, 'completed')

    def test_route_with_close_ends_does_not_finish_on_pulling_out(self):
        PickupStage.objects.filter(route=self.route).delete()
        PickupStage.objects.create(route=self.route, name='S', latitude=-1.2900, longitude=36.8200, order=1)
        PickupStage.objects.create(route=self.route, name='M', latitude=-1.3500, longitude=36.9000, order=2)
        PickupStage.objects.create(route=self.route, name='E', latitude=-1.2900, longitude=36.8216, order=3)
        self.trip.status = 'boarding'
        self.trip.departure_at = timezone.now() - timedelta(minutes=30)
        self.trip.save()
        pt = (-1.2900, 36.8225)
        self.fix(pt, prev=pt)
        self.assertEqual(self.trip.status, 'departed')
        self.fix((-1.3500, 36.9000))
        self.fix(pt)
        self.assertEqual(self.trip.status, 'completed')

    def test_trip_ends_itself_at_last_stage_and_cannot_rerun(self):
        self.trip.status = 'departed'
        self.trip.departure_at = timezone.now() - timedelta(minutes=40)
        self.trip.save()
        rider = self.rider(self.stages[1], '+254712300013')
        Booking.objects.filter(user=rider).update(status='completed')  # PIN verified on board

        self.fix(STAGES[0][1:])
        self.fix(STAGES[2][1:])
        self.assertEqual(self.trip.status, 'departed')  # not the end yet

        sent = self.fix(STAGES[3][1:])
        self.assertEqual(self.trip.status, 'completed')
        end = [c for c in sent.call_args_list if c.args[1] == 'You have arrived']
        self.assertEqual(end[0].args[0], [rider.id])

        self.fix(STAGES[0][1:])  # back at the first stage: a finished trip never reboards
        self.assertEqual(self.trip.status, 'completed')

    def test_short_hop_does_not_end_early(self):
        self.trip.status = 'departed'
        self.trip.departure_at = timezone.now() - timedelta(minutes=5)
        self.trip.save()
        self.fix(STAGES[3][1:])
        self.assertEqual(self.trip.status, 'departed')


class GpsPrecisionTests(APITestCase):
    def setUp(self):
        co = Company.objects.create(name='GPS Co', areas_served='X')
        self.driver = Driver.objects.create(
            company=co, name='D', phone_number='+254712300030', bus_number='KA 2')
        user = User.objects.create_user(
            username='gd', password='x', phone_number='+254712300030', role='driver', company=co)
        self.client.force_authenticate(user)
        self.url = f'/api/drivers/{self.driver.id}/location/'

    def post(self, lat, lng, accuracy=None):
        body = {'latitude': lat, 'longitude': lng}
        if accuracy is not None:
            body['accuracy'] = accuracy
        r = self.client.post(self.url, body, format='json')
        self.assertEqual(r.status_code, 200)
        self.driver.refresh_from_db()
        return r.data

    def test_wifi_guess_is_ignored(self):
        self.assertEqual(self.post(-1.2856, 36.8250)['ignored'], 'no_accuracy')
        self.assertEqual(self.post(-1.2856, 36.8250, accuracy=900)['ignored'], 'low_accuracy')
        self.assertIsNone(self.driver.latitude)
        self.post(-1.2856, 36.8250, accuracy=8)
        self.assertAlmostEqual(float(self.driver.latitude), -1.2856, places=4)

    def test_teleport_is_ignored(self):
        self.post(-1.2856, 36.8250, accuracy=8)
        self.assertEqual(self.post(-1.2387, 36.6009, accuracy=8)['ignored'], 'jump')  # Kamangu in 0 s
        self.assertAlmostEqual(float(self.driver.longitude), 36.8250, places=4)


class PushSubscribeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='p', password='x', phone_number='+254712300020')
        self.client.force_authenticate(self.user)
        self.keys = {'p256dh': push.public_key(), 'auth': push.b64u(b'0123456789abcdef')}

    def test_saves_real_push_service(self):
        for url in ('https://fcm.googleapis.com/fcm/send/abc:APA91b-x_y',
                    'https://wns2-par02p.notify.windows.com/w/?token=BQYAAAD%2b',
                    'https://web.push.apple.com/QGuQyavXutnMH'):
            r = self.client.post('/api/users/push/', {'endpoint': url, 'keys': self.keys}, format='json')
            self.assertEqual(r.status_code, 201, url)
        self.assertTrue(PushSubscription.objects.filter(user=self.user).exists())

    def test_rejects_other_hosts(self):
        for url in ('http://fcm.googleapis.com/x', 'https://127.0.0.1/x',
                    'https://evil.com/fcm.googleapis.com', 'https://fcm.googleapis.com.evil.com/x',
                    'https://fcm.googleapis.com:8443/x', 'https://fcm.googleapis.com:99999/x',
                    'https://127.0.0.1\\.notify.windows.com/x', 'https://evil.com\\@fcm.googleapis.com/x',
                    'https://evil.com@fcm.googleapis.com/x', 'https://fcm.googleapis.com/x y'):
            r = self.client.post('/api/users/push/', {'endpoint': url, 'keys': self.keys}, format='json')
            self.assertEqual(r.status_code, 400, url)
        self.assertFalse(PushSubscription.objects.exists())
