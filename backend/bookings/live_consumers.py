from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from users.identity import is_driver_account_for


class BookingLiveConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.booking_id = int(self.scope["url_route"]["kwargs"]["booking_id"])
        self.group = None
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return

        if not await self._allowed(user):
            await self.close(code=4403)
            return

        self.group = f"booking_live_{self.booking_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "hello", "booking_id": self.booking_id})

    async def disconnect(self, code):
        if self.group:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def live_update(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _allowed(self, user):
        from .models import Booking

        booking = (
            Booking.objects.select_related("route", "driver")
            .filter(id=self.booking_id)
            .first()
        )

        if not booking:
            return False

        if user.is_superuser or booking.user_id == user.id:
            return True

        role = getattr(user, "role", None)
        driver = booking.driver

        if (
            driver is not None
            and role == "driver"
            and is_driver_account_for(user, driver)
        ):
            return True

        return (
            role in {"company_manager", "company_auditor", "company_operator"}
            and getattr(user, "company_id", None) == booking.route.company_id
        )
