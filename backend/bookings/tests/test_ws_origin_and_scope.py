"""The WebSocket accepts the frontend's Origin and nothing else (plan A-1)."""
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings

from connect.ws_origin import build_websocket_application

LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
FRONTEND = "https://connect-app.vercel.app"


@override_settings(
    CHANNEL_LAYERS=LAYERS, ALLOWED_HOSTS=["api.onrender.example"],
    FRONTEND_URL=FRONTEND + "/", CORS_ALLOWED_ORIGINS=["https://staff.example.com"],
    CORS_ALLOWED_ORIGIN_REGEXES=[],
)
class WebsocketOriginTests(TransactionTestCase):
    async def attempt(self, origin):
        headers = [(b"origin", origin.encode())] if origin is not None else []
        comm = WebsocketCommunicator(
            build_websocket_application(), "/ws/bookings/1/live/", headers=headers)
        connected, code = await comm.connect()
        # The consumer refuses an anonymous user with 4401 before accepting, so
        # (False, 4401) means the Origin check passed; any other refusal is the validator.
        return ("reached_consumer" if code == 4401 else "denied"), code

    async def test_ws_origin_accepts_frontend_rejects_other(self):
        for origin in (FRONTEND, "https://staff.example.com", "https://api.onrender.example"):
            with self.subTest(origin=origin):
                self.assertEqual(await self.attempt(origin), ("reached_consumer", 4401))
        for origin in ("https://evil.example", FRONTEND + ".evil.com", "http://connect-app.vercel.app",
                       "https://connect-app.vercel.app:8443", "https://x.connect-app.vercel.app",
                       "null", None):
            with self.subTest(origin=origin):
                self.assertEqual((await self.attempt(origin))[0], "denied")

    @override_settings(CORS_ALLOWED_ORIGIN_REGEXES=[r"^http://192\.168\.\d{1,3}\.\d{1,3}:5173$"])
    async def test_private_network_dev_origin_only_through_the_regex_setting(self):
        self.assertEqual((await self.attempt("http://192.168.1.20:5173"))[0], "reached_consumer")
        self.assertEqual((await self.attempt("http://192.168.1.20:5174"))[0], "denied")
