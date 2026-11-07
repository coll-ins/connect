import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connect.settings')

application = get_wsgi_application()

from connect.startup import ensure_platform_admin  # noqa: E402

ensure_platform_admin()

# Vercel requires 'app' to be explicitly exposed
app = application