import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'connect.settings')

application = get_wsgi_application()

# Vercel requires 'app' to be explicitly exposed
app = application