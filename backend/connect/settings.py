from pathlib import Path
from dotenv import load_dotenv
import os
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Enforce secure secret key in production
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-development-key-123456789'
    else:
        raise ValueError("CRITICAL: SECRET_KEY environment variable must be set in production.")

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        'ALLOWED_HOSTS',
        'localhost,127.0.0.1,testserver'
    ).split(',')
    if host.strip()
]

INSTALLED_APPS = [
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'deliveries',
    'charters',
    'corsheaders',

    'users',
    'companies',
    'bookings',
    'drivers',
    'buses',
    'wallets'
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'connect.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR.parent / 'frontend'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'connect.wsgi.application'
ASGI_APPLICATION = 'connect.asgi.application'

# Live-location push. In-memory works for one server process only.
# Set REDIS_URL (e.g. redis://127.0.0.1:6379) to share it across processes.
import os as _os
_REDIS_URL = _os.environ.get('REDIS_URL')
if _REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_REDIS_URL]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }

# Flexible database configuration (SQLite locally, dynamic URL in production)
DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600
    )
}

AUTH_USER_MODEL = 'users.CustomUser'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # Mandatory for Django Admin access
        'rest_framework.authentication.TokenAuthentication',    # (Or JWT authentication if you use it)
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '300/minute',
        'driver_location': '60/minute',
        'boarding_verify': '5/minute',
    }
}

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5500,'
        'http://127.0.0.1:5500,'
        'http://localhost:8000,'
        'http://127.0.0.1:8000,'
        'http://localhost:5173,'
        'http://127.0.0.1:5173,'
        'http://localhost:5174,'
        'http://127.0.0.1:5174,'
        'http://localhost:5175,'
        'http://127.0.0.1:5175',
    ).split(',')
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}):5173$',
]

# Static files
STATIC_URL = '/static/'

LEGACY_FRONTEND_STATIC = BASE_DIR.parent / 'frontend' / 'static'
STATICFILES_DIRS = [LEGACY_FRONTEND_STATIC] if LEGACY_FRONTEND_STATIC.exists() else []

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

TIME_ZONE = 'Africa/Nairobi'
USE_TZ = True

# Africa's Talking settings
AT_USERNAME = os.getenv('AT_USERNAME', 'sandbox')
AT_API_KEY = os.getenv('AT_API_KEY', '')

# Critical environment variables validation
ADMIN_SIGNUP_CODE = os.getenv('ADMIN_SIGNUP_CODE')
if not ADMIN_SIGNUP_CODE:
    raise ValueError("CRITICAL: ADMIN_SIGNUP_CODE environment variable must be set.")

ADMIN_ALERT_PHONE_NUMBERS = [
    number.strip()
    for number in os.getenv(
        'ADMIN_ALERT_PHONE_NUMBERS',
        ''
    ).split(',')
    if number.strip()
]

PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY')
if not PAYSTACK_SECRET_KEY:
    if DEBUG:
        PAYSTACK_SECRET_KEY = 'sk_test_fallback_key_for_local_dev'
    else:
        raise ValueError("CRITICAL: PAYSTACK_SECRET_KEY environment variable must be set in production.")

    # Force Django to look back at the admin dashboard upon successful admin panel auth
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/admin/'


# --- production security ---
# Only active when DEBUG is off (i.e. on the live server).
if not DEBUG:
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start low; raise to a year once HTTPS is confirmed working.
    SECURE_HSTS_SECONDS = int(
        os.getenv('SECURE_HSTS_SECONDS', '3600')
    )
    SECURE_HSTS_INCLUDE_SUBDOMAINS = (
        os.getenv(
            'SECURE_HSTS_INCLUDE_SUBDOMAINS',
            'False'
        ).lower() == 'true'
    )
    SECURE_HSTS_PRELOAD = (
        os.getenv(
            'SECURE_HSTS_PRELOAD',
            'False'
        ).lower() == 'true'
    )


# Self-service platform-admin signup. On for local dev, off by default in
# production: create the first admin with `manage.py createsuperuser`.
ALLOW_ADMIN_SIGNUP = os.getenv(
    'ALLOW_ADMIN_SIGNUP', 'True' if DEBUG else 'False'
).lower() == 'true'


# Throttle counters must be shared across workers and survive restarts.
REDIS_CACHE_URL = (
    os.getenv('REDIS_CACHE_URL', '').strip()
    or _REDIS_URL
)

if REDIS_CACHE_URL:
    CACHES = {
        'default': {
            'BACKEND': (
                'django.core.cache.backends.redis.RedisCache'
            ),
            'LOCATION': REDIS_CACHE_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': (
                'django.core.cache.backends.db.DatabaseCache'
            ),
            'LOCATION': 'django_cache',
        }
    }


# --- round-2 hardening ---
# Sessions + CSRF are the only auth in use (rest_framework.authtoken is not installed).
REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = [
    'rest_framework.authentication.SessionAuthentication',
]
# 0 = never trust X-Forwarded-For. Set NUM_PROXIES=1 in production behind nginx.
REST_FRAMEWORK['NUM_PROXIES'] = int(os.getenv('NUM_PROXIES', '0'))

if not DEBUG:
    # Private-network CORS is for local development only.
    CORS_ALLOWED_ORIGIN_REGEXES = []
    for _required in ('ALLOWED_HOSTS', 'CORS_ALLOWED_ORIGINS', 'FRONTEND_URL', 'DATABASE_URL'):
        if not os.getenv(_required):
            raise ValueError(f'CRITICAL: {_required} must be set in production.')
    if not ADMIN_ALERT_PHONE_NUMBERS:
        raise ValueError(
            'CRITICAL: ADMIN_ALERT_PHONE_NUMBERS must be set in production '
            '(unapplied payments are reported there).'
        )

REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login'] = '10/hour'
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['mpesa_push'] = '10/hour'

from decimal import Decimal
PLATFORM_FEE_PER_SEAT = Decimal("20.00")  # KES the platform keeps per seat
PLATFORM_CHARTER_FEE_PERCENT = Decimal("10.00")  # percent of a completed bus-hire quote kept by the platform
PLATFORM_PARCEL_FEE_PERCENT = Decimal("10.00")  # percent of a delivered parcel price kept by the platform

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

import sys
if 'test' in sys.argv:
    # Tests only: fast hashing makes the suite several times quicker.
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

MAX_PENDING_BOOKINGS_PER_USER = 3   # unpaid bookings one user may hold at once
PENDING_BOOKING_TTL_MINUTES = 20    # expire_pending_bookings cancels unpaid bookings older than this


# --- Production hardening (active only when DEBUG is off) ---
if not DEBUG:
    if len(SECRET_KEY or '') < 50 or SECRET_KEY.startswith('django-insecure-'):
        raise ValueError('CRITICAL: SECRET_KEY must be long and random in production.')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
    # Start low. Raise to 31536000 only after HTTPS is confirmed stable.
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '3600'))
    # W005/W021 are deliberate: no includeSubDomains/preload until HTTPS is proven on every
    # subdomain. Any OTHER deploy warning still fails the release check.
    SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']
    if os.getenv('BEHIND_TLS_PROXY', 'False').lower() == 'true':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if not DEBUG and (
    len(ADMIN_SIGNUP_CODE) < 20
    or 'your_secure' in ADMIN_SIGNUP_CODE
    or 'replace-with' in ADMIN_SIGNUP_CODE
):
    raise ValueError('CRITICAL: ADMIN_SIGNUP_CODE is a placeholder or too short.')


# --- round 22: lockout counters need an atomic shared cache ---
if not DEBUG and not _REDIS_URL:
    raise ValueError("CRITICAL: REDIS_URL must be set in production (shared WebSocket channel layer and lockout counters).")
if not DEBUG and not REDIS_CACHE_URL:
    raise ValueError("CRITICAL: REDIS_CACHE_URL must be set in production (atomic PIN/QR lockout counters).")


# --- round 28: money alerts are SMS; silently not sending them is a production failure ---
if not DEBUG and (not AT_API_KEY or AT_USERNAME == 'sandbox'):
    raise ValueError("CRITICAL: AT_API_KEY and a live AT_USERNAME (not 'sandbox') must be set in production (refund/payment alerts are SMS).")
