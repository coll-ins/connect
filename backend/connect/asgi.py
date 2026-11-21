import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connect.settings')
django_asgi_app = get_asgi_application()

from connect.startup import ensure_platform_admin  # noqa: E402

ensure_platform_admin()

from channels.routing import ProtocolTypeRouter  # noqa: E402

from connect.ws_origin import build_websocket_application  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": build_websocket_application(),
})
