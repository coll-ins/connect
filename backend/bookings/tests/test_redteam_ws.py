from datetime import timedelta
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from bookings.live_consumers import BookingLiveConsumer
from bookings.models import Booking
from companies.models import Company, PickupStage, Route, Trip
from drivers.models import Driver

User = get_user_model()
LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


@override_settings(CHANNEL_LAYERS=LAYERS)
class RedTeamLiveSocketTests(TransactionTestCase):
    def setUp(self):
        self.co = Company.objects.create(name="A", description="d", areas_served="N")
        self.co2 = Company.objects.create(name="B", description="d", areas_served="N")
        self.route = Route.objects.create(
            company=self.co, name="R", start_point="A", end_point="B",
            price=Decimal("100.00"))
        self.stage = PickupStage.objects.create(
            route=self.route, name="S1", latitude=Decimal("-1.285"),
            longitude=Decimal("36.82"), order=1)
        self.d1 = Driver.objects.create(
            name="D1", phone_number="0700000001", bus_number="K1", company=self.co)
        self.trip = Trip.objects.create(
            route=self.route, driver=self.d1,
            departure_at=timezone.now() + timedelta(days=1),
            capacity=10, status="scheduled")
        mk = User.objects.create_user
        self.owner = mk(username="own", password="x", phone_number="0711000001")
        self.stranger = mk(username="str", password="x", phone_number="0711000002")
        self.mgr = mk(username="m1", password="x", phone_number="0711000003",
                      company=self.co, role="company_manager")
        self.mgr_b = mk(username="m2", password="x", phone_number="0711000004",
                        company=self.co2, role="company_manager")
        self.aud = mk(username="aud", password="x", phone_number="0711000005",
                      company=self.co, role="company_auditor")
        self.drv1 = mk(username="d1", password="x", phone_number="0700000001",
                       company=self.co, role="driver")
        self.drv_b = mk(username="d2", password="x", phone_number="0700000009",
                        company=self.co2, role="driver")
        self.booking = Booking.objects.create(
            user=self.owner, route=self.route, trip=self.trip, driver=self.d1,
            pickup_stage=self.stage, pickup_location="S1", seats=1,
            total_amount=Decimal("100.00"), status="confirmed")

    async def _try(self, user, booking_id=None):
        comm = WebsocketCommunicator(
            BookingLiveConsumer.as_asgi(), "/ws/bookings/x/live/")
        comm.scope["user"] = user or AnonymousUser()
        comm.scope["url_route"] = {
            "kwargs": {"booking_id": booking_id or self.booking.id}}
        connected, code = await comm.connect()
        if connected:
            await comm.disconnect()
        return connected, code

    async def test_anonymous_rejected(self):
        self.assertEqual(await self._try(None), (False, 4401))

    async def test_outsiders_rejected(self):
        for label, u in (("stranger", self.stranger),
                         ("other company manager", self.mgr_b),
                         ("other company driver", self.drv_b)):
            connected, code = await self._try(u)
            self.assertEqual((connected, code), (False, 4403), label)

    async def test_missing_booking_rejected(self):
        self.assertEqual(await self._try(self.owner, 999999), (False, 4403))

    async def test_legitimate_viewers_accepted(self):
        for label, u in (("owner", self.owner), ("manager", self.mgr),
                         ("auditor", self.aud), ("driver", self.drv1)):
            connected, _ = await self._try(u)
            self.assertTrue(connected, label)

    async def test_closed_booking_cannot_listen(self):
        for st in ("cancelled", "no_show", "completed"):
            await database_sync_to_async(
                Booking.objects.filter(pk=self.booking.pk).update)(status=st)
            for label, u in (("owner", self.owner), ("driver", self.drv1)):
                connected, _ = await self._try(u)
                self.assertFalse(connected, f"{label} on {st}")
