from pathlib import Path
from dotenv import load_dotenv
import os
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Enforce secure secret key in production
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG := os.getenv('DEBUG', 'True').lower() == 'true':
        SECRET_KEY = 'django-insecure-development-key-123456789'
    else:
        raise ValueError("CRITICAL: SECRET_KEY environment variable must be set in production.")

DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        'ALLOWED_HOSTS',
        'localhost,127.0.0.1,testserver'
    ).split(',')
    if host.strip()
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',

    'users',
    'companies',
    'bookings',
    'drivers',
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
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '100/minute',
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
        'http://127.0.0.1:8000',
    ).split(',')
    if origin.strip()
]

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# Static files
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR.parent / 'frontend' / 'static',  # If your assets are in frontend/static/
    # If your folder structure is just frontend/css/ and frontend/js/, use this instead:
    # BASE_DIR.parent / 'frontend', 
]

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
