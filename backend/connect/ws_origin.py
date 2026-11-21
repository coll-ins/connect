from urllib.parse import urlparse
import re

from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings


def _origin_of(url):
    """'https://app.example.com/path/' -> 'https://app.example.com'; None if it has no scheme and host."""
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    return f'{parsed.scheme}://{parsed.netloc}'


class FrontendOriginValidator(OriginValidator):
    """
    Accept a WebSocket only from the site's own hosts or the frontend.

    The browser sends the frontend's Origin (the Vercel domain), which is not in
    ALLOWED_HOSTS (the backend's own host names), so AllowedHostsOriginValidator
    refuses it. Scheme, host and port must match exactly: no wildcards, no
    subdomains. Read per connection so a settings change applies without reload.
    """

    def __init__(self, application):
        super().__init__(application, allowed_origins=[])

    def validate_origin(self, parsed_origin):
        exact = {
            origin for origin in (
                [_origin_of(settings.FRONTEND_URL)]
                + [_origin_of(o) for o in settings.CORS_ALLOWED_ORIGINS]
            ) if origin
        }
        self.allowed_origins = list(exact) + list(settings.ALLOWED_HOSTS)
        if super().validate_origin(parsed_origin):
            return True
        # Private-network dev origins; the list is empty in production.
        origin = f'{parsed_origin.scheme}://{parsed_origin.netloc}'
        return any(
            re.match(pattern, origin)
            for pattern in getattr(settings, 'CORS_ALLOWED_ORIGIN_REGEXES', [])
        )


def build_websocket_application():
    from bookings.live_routing import websocket_urlpatterns

    return FrontendOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    )
