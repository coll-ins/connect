from django.conf import settings


def frontend_url(request, path):
    """Link back into the app on the site the request came from.

    A payment must return to the same site the passenger is logged in on.
    Only exact origins from CORS_ALLOWED_ORIGINS are trusted (not the regex
    list), so this cannot become an open redirect; anything else falls back
    to FRONTEND_URL.
    """
    origin = (request.headers.get('Origin') or '').rstrip('/')
    trusted = {o.rstrip('/') for o in getattr(settings, 'CORS_ALLOWED_ORIGINS', [])}
    base = origin if origin in trusted else getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
    return f"{base.rstrip('/')}{path}"
