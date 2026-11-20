import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parent.parent

DEV_ENV = {
    'DEBUG': 'True',
    'SECRET_KEY': 'ci-only-secret-key-long-enough-0123456789',
    'ADMIN_SIGNUP_CODE': 'ci-only-admin-signup-code-not-real-long',
    'PAYSTACK_SECRET_KEY': 'sk_test_ci_only_not_real',
}

PROD_ENV = {
    'DEBUG': 'False',
    'SECRET_KEY': 'x' * 64,
    'PAYSTACK_SECRET_KEY': 'sk_test_x',
    'BEHIND_TLS_PROXY': 'True',
    'NUM_PROXIES': '1',
    'ALLOWED_HOSTS': 'connect.example.com',
    'CORS_ALLOWED_ORIGINS': 'https://connect.example.com',
    'FRONTEND_URL': 'https://connect.example.com',
    'DATABASE_URL': 'postgres://u:p@127.0.0.1:5432/connect',
    'ADMIN_ALERT_PHONE_NUMBERS': '+254700000000',
    'ADMIN_SIGNUP_CODE': 'a-long-random-admin-signup-code-123',
    'REDIS_URL': 'redis://127.0.0.1:6379/0',
    'REDIS_CACHE_URL': 'redis://127.0.0.1:6379/1',
    'AT_API_KEY': 'live_key_x',
    'AT_USERNAME': 'connect',
}

PROBE = (
    'import json, os; os.environ["DJANGO_SETTINGS_MODULE"]="connect.settings";'
    'from django.conf import settings as s;'
    's.DEBUG;'  # settings load lazily; touch one so a bad env fails here
    'names=%r;'
    'print(json.dumps({n: str(getattr(s, n, "<unset>")) for n in names}))'
)


def load_settings(env, names=()):
    """Import connect.settings in a clean process; settings read env at import time."""
    full_env = {'PATH': os.environ.get('PATH', '')}
    full_env.update(env)
    proc = subprocess.run(
        [sys.executable, '-c', PROBE % (list(names),)],
        cwd=BACKEND_DIR, env=full_env, capture_output=True, text=True, timeout=120,
    )
    return proc


class PlanSettingsDefaultsTests(SimpleTestCase):
    def test_defaults_match_the_plan(self):
        names = [
            'PAYMENT_ARRIVAL_TOLERANCE_SECONDS', 'PAYMENT_STATUS_VERIFY_TIMEOUT_SECONDS',
            'BOOKING_CUTOFF_MAX_MINUTES', 'WALLET_TOPUP_ENABLED', 'WALLET_PAYOUTS_ENABLED',
            'WALLET_TOPUP_CHANNELS', 'WALLET_TOPUP_MIN_KES', 'WALLET_TOPUP_MAX_KES',
            'WALLET_MAX_BALANCE_KES', 'WALLET_WITHDRAW_MIN_KES', 'WALLET_WITHDRAW_MAX_KES',
            'WALLET_WITHDRAW_DAILY_LIMIT_KES', 'GPS_FIX_MAX_AGE_SECONDS',
            'GPS_MAX_ACCURACY_M', 'PAYMENT_HOLD_MINUTES', 'CASH_PENDING_TTL_MINUTES',
        ]
        proc = load_settings(DEV_ENV, names)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout)
        self.assertEqual(got, {
            'PAYMENT_ARRIVAL_TOLERANCE_SECONDS': '60',
            'PAYMENT_STATUS_VERIFY_TIMEOUT_SECONDS': '10',
            'BOOKING_CUTOFF_MAX_MINUTES': '240',
            'WALLET_TOPUP_ENABLED': 'False',
            'WALLET_PAYOUTS_ENABLED': 'False',
            'WALLET_TOPUP_CHANNELS': "['mobile_money']",
            'WALLET_TOPUP_MIN_KES': '50',
            'WALLET_TOPUP_MAX_KES': '20000',
            'WALLET_MAX_BALANCE_KES': '50000',
            'WALLET_WITHDRAW_MIN_KES': '50',
            'WALLET_WITHDRAW_MAX_KES': '20000',
            'WALLET_WITHDRAW_DAILY_LIMIT_KES': '30000',
            'GPS_FIX_MAX_AGE_SECONDS': '120',
            'GPS_MAX_ACCURACY_M': '200',
            'PAYMENT_HOLD_MINUTES': '10',
            'CASH_PENDING_TTL_MINUTES': '20',
        })

    def test_money_flags_can_be_flipped_from_the_environment(self):
        env = dict(DEV_ENV, WALLET_TOPUP_ENABLED='true', WALLET_PAYOUTS_ENABLED='True',
                   WALLET_TOPUP_MAX_KES='1500', WALLET_TOPUP_CHANNELS='mobile_money, card')
        proc = load_settings(env, [
            'WALLET_TOPUP_ENABLED', 'WALLET_PAYOUTS_ENABLED', 'WALLET_TOPUP_MAX_KES',
            'WALLET_TOPUP_CHANNELS'])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {
            'WALLET_TOPUP_ENABLED': 'True',
            'WALLET_PAYOUTS_ENABLED': 'True',
            'WALLET_TOPUP_MAX_KES': '1500',
            'WALLET_TOPUP_CHANNELS': "['mobile_money', 'card']",
        })

    def test_a_bad_number_names_the_variable(self):
        proc = load_settings(dict(DEV_ENV, WALLET_TOPUP_MAX_KES='twenty'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('WALLET_TOPUP_MAX_KES must be a number', proc.stderr)

    def test_a_negative_or_zero_limit_is_refused(self):
        proc = load_settings(dict(DEV_ENV, GPS_MAX_ACCURACY_M='0'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('GPS_MAX_ACCURACY_M must be greater than 0', proc.stderr)


class ProductionStartupTests(SimpleTestCase):
    def test_complete_production_env_starts(self):
        proc = load_settings(PROD_ENV, ['DEBUG'])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_every_missing_variable_is_named_in_one_error(self):
        env = {k: v for k, v in PROD_ENV.items()
               if k not in ('FRONTEND_URL', 'REDIS_URL', 'ADMIN_ALERT_PHONE_NUMBERS',
                            'DATABASE_URL')}
        proc = load_settings(env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('CRITICAL: missing required environment variables in production', proc.stderr)
        for name in ('FRONTEND_URL', 'REDIS_URL', 'ADMIN_ALERT_PHONE_NUMBERS', 'DATABASE_URL'):
            self.assertIn(name, proc.stderr)

    def test_production_still_refuses_a_money_flag_typo(self):
        proc = load_settings(dict(PROD_ENV, WALLET_TOPUP_ENABLED='yes'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('WALLET_TOPUP_ENABLED must be true or false', proc.stderr)

    def test_a_short_cron_secret_is_refused_and_named(self):
        proc = load_settings(dict(PROD_ENV, CRON_SECRET='short'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('CRON_SECRET must be at least 32 characters', proc.stderr)

    def test_a_long_cron_secret_or_none_at_all_starts(self):
        for extra in ({'CRON_SECRET': 'c' * 32}, {}):
            with self.subTest(extra=extra):
                proc = load_settings(dict(PROD_ENV, **extra))
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_short_cron_secret_is_allowed_in_development(self):
        proc = load_settings(dict(DEV_ENV, CRON_SECRET='short'))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_wildcard_allowed_host_is_refused_in_production(self):
        for hosts in ('*', 'connect.example.com, *'):
            with self.subTest(hosts=hosts):
                proc = load_settings(dict(PROD_ENV, ALLOWED_HOSTS=hosts))
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("ALLOWED_HOSTS must not contain '*'", proc.stderr)
