"""The real origin validator + session auth + routing (the other WebSocket tests bypass them)."""
import datetime as dt
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from bookings.models import Booking
from bookings.tests.sim import fake_gateway as fg
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
WS_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=WS_LAYERS)
class WebSocketRealStackTests(TransactionTestCase):
    def setUp(self):
        self.fake = fg.FakePaystack().install(self)
        self.addCleanup(lambda: self.assertEqual(self.fake.leaks, []))
        co = Company.objects.create(name='W Co', areas_served='N')
        route = Route.objects.create(company=co, name='R', start_point='A', end_point='B', price=Decimal('100'))
        stage = PickupStage.objects.create(route=route, name='S1', latitude=Decimal('-1.28'), longitude=Decimal('36.82'), order=1)
        drv = Driver.objects.create(name='D', phone_number='+254700000001', bus_number='K1', company=co)
        trip = Trip.objects.create(route=route, driver=drv, capacity=10, status='scheduled', departure_at=timezone.now() + dt.timedelta(days=1))
        self.owner = User.objects.create_user(username='wown', password='pw-123456', phone_number='+254711000001')
        self.stranger = User.objects.create_user(username='wstr', password='pw-123456', phone_number='+254711000002')
        self.booking = Booking.objects.create(user=self.owner, route=route, trip=trip, driver=drv, pickup_stage=stage, pickup_location='S1',
                                              seats=1, total_amount=Decimal('100'), status='confirmed')

    def cookie_for(self, user):
        c = Client()
        c.force_login(user)
        return f'sessionid={c.cookies["sessionid"].value}'.encode()

    async def attempt(self, origin, user):
        from connect.ws_origin import build_websocket_application
        headers = []
        if origin:
            headers.append((b'origin', origin.encode()))
        if user:
            headers.append((b'cookie', await database_sync_to_async(self.cookie_for)(user)))
        comm = WebsocketCommunicator(build_websocket_application(), f'/ws/bookings/{self.booking.id}/live/', headers=headers)
        connected, code = await comm.connect()
        if connected:
            await comm.disconnect()
        return connected, code

    async def test_origin_auth_and_ownership(self):
        good = 'http://localhost:5173'
        self.assertEqual(await self.attempt(good, self.owner), (True, None))
        self.assertFalse((await self.attempt('https://evil.example', self.owner))[0])
        self.assertFalse((await self.attempt(None, self.owner))[0])
        self.assertEqual(await self.attempt(good, self.stranger), (False, 4403))
        self.assertEqual(await self.attempt(good, None), (False, 4401))
        await database_sync_to_async(Booking.objects.filter(pk=self.booking.pk).update)(status='cancelled')
        self.assertEqual(await self.attempt(good, self.owner), (False, 4403))
