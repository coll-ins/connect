from django.urls import path

from .live_consumers import BookingLiveConsumer

websocket_urlpatterns = [
    path("ws/bookings/<int:booking_id>/live/", BookingLiveConsumer.as_asgi()),
]
