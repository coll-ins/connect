from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from users.throttles import login_blocked, record_login_failure

User = get_user_model()
ENV = {'ADMIN_PHONE': '0712345678', 'ADMIN_PASSWORD': 'Str0ng-admin-pass'}


def run():
    out = StringIO()
    call_command('ensure_superuser', stdout=out)
    return out.getvalue().strip()


class EnsureSuperuserTests(TestCase):
    def test_noop_when_unset(self):
        with mock.patch.dict('os.environ', {}, clear=False) as env:
            env.pop('ADMIN_PHONE', None)
            env.pop('ADMIN_PASSWORD', None)
            self.assertEqual(run(), '')
        self.assertFalse(User.objects.exists())

    def test_creates_superuser(self):
        with mock.patch.dict('os.environ', ENV):
            self.assertEqual(run(), 'superuser ensured')
        user = User.objects.get()
        self.assertEqual(user.phone_number, '+254712345678')
        self.assertTrue(user.is_superuser and user.is_staff and user.is_active)
        self.assertEqual(user.role, 'platform_admin')
        self.assertTrue(user.check_password('Str0ng-admin-pass'))

    def test_repairs_existing_user_and_clears_throttles(self):
        User.objects.create_user(
            username='old', password='x', phone_number='0712345678', is_active=False
        )
        for _ in range(10):
            record_login_failure('+254712345678', '10.0.0.1')
        self.assertTrue(login_blocked('+254712345678', '10.0.0.1'))
        with mock.patch.dict('os.environ', ENV):
            run()
        user = User.objects.get()
        self.assertEqual(user.username, 'old')
        self.assertTrue(user.is_active and user.is_superuser)
        self.assertEqual(user.phone_number, '+254712345678')
        self.assertTrue(user.check_password('Str0ng-admin-pass'))
        self.assertFalse(login_blocked('+254712345678', '10.0.0.1'))
